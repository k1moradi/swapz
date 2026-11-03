#!/usr/bin/env python3
"""Bounded O(1)-oracle block replay for dedicated-SD service and churn.

Private helper. It never creates/removes a mapper, formats media, or activates
swap. Physical execution requires an already admitted target and exact identity
arguments supplied by the host scheduler.
"""
from __future__ import annotations

import argparse
import array
import concurrent.futures
import fcntl
import hashlib
import json
import math
import mmap
import os
import re
import resource
import runpy
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

PAGE = 4096
SCHEMA = "swapz-sustained-replay-v1"
REPLAY = runpy.run_path(str(Path(__file__).with_name("io-replay.py")))


def splitmix64(value: int) -> int:
    value = (value + 0x9E3779B97F4A7C15) & 0xffffffffffffffff
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & 0xffffffffffffffff
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & 0xffffffffffffffff
    return value ^ (value >> 31)


def payload_index(page: int, serial: int, fixture_pages: int, seed: int) -> int:
    if page < 0 or serial < 0 or fixture_pages < 1:
        raise ValueError("invalid deterministic payload coordinates")
    return splitmix64(seed ^ splitmix64(page) ^ splitmix64(serial + 0xD1B54A32D192ED03)) % fixture_pages


def coprime_stride(modulus: int, seed: int) -> int:
    if modulus <= 1:
        return 0
    candidate = (splitmix64(seed) % modulus) | 1
    for _ in range(modulus):
        if math.gcd(candidate, modulus) == 1:
            return candidate
        candidate = (candidate + 2) % modulus or 1
    raise ValueError("cannot choose sequence stride")


def sequence_offset(modulus: int, seed: int) -> int:
    return 0 if modulus <= 1 else splitmix64(seed ^ 0xA0761D6478BD642F) % modulus


def lane_page(lane: int, qd: int, lane_pages: int, index: int,
              stride: int, offset: int) -> int:
    local = 0 if lane_pages <= 1 else (index * stride + offset) % lane_pages
    return lane + qd * local


def latest_write_index(local_page: int, completed_writes: int,
                       lane_pages: int, stride: int, offset: int):
    """Latest zero-based write index for a page, without a page-sized oracle map."""
    if completed_writes <= 0:
        return None
    if lane_pages <= 1:
        return completed_writes - 1
    first = ((local_page - offset) * pow(stride, -1, lane_pages)) % lane_pages
    if first >= completed_writes:
        return None
    return first + ((completed_writes - 1 - first) // lane_pages) * lane_pages


LATENCY_SUB_BUCKETS = 16
LATENCY_EXPONENTS = 65
LATENCY_BIN_COUNT = LATENCY_SUB_BUCKETS * LATENCY_EXPONENTS


class LatencyHistogram:
    """Compact log histogram with <=6.25% relative bucket width."""
    def __init__(self):
        self.bins = array.array("Q", [0]) * LATENCY_BIN_COUNT
        self.count = 0
        self.sum_ns = 0
        self.max_ns = 0

    def observe(self, value: int) -> None:
        if value <= 0:
            raise ValueError("latency must be positive")
        exponent = min(LATENCY_EXPONENTS - 1,
                       max(0, value.bit_length() - 1))
        base = 1 << exponent
        sub_bucket = min(
            LATENCY_SUB_BUCKETS - 1,
            ((value - base) * LATENCY_SUB_BUCKETS) // base)
        index = exponent * LATENCY_SUB_BUCKETS + sub_bucket
        self.bins[index] += 1
        self.count += 1
        self.sum_ns += value
        self.max_ns = max(self.max_ns, value)

    def merge(self, other) -> None:
        for index, value in enumerate(other.bins):
            self.bins[index] += value
        self.count += other.count
        self.sum_ns += other.sum_ns
        self.max_ns = max(self.max_ns, other.max_ns)

    def percentile(self, fraction: float):
        if not self.count:
            return None
        target = max(1, math.ceil(self.count * fraction))
        seen = 0
        for index, value in enumerate(self.bins):
            seen += value
            if seen >= target:
                exponent, sub_bucket = divmod(index, LATENCY_SUB_BUCKETS)
                base = 1 << exponent
                # Conservative exclusive upper edge; unlike a single
                # power-of-two bin, this cannot dominate a 25% tail gate.
                return base + (
                    (sub_bucket + 1) * base + LATENCY_SUB_BUCKETS - 1
                ) // LATENCY_SUB_BUCKETS
        return self.max_ns

    def summary(self) -> dict:
        return {"count": self.count, "mean_ns": self.sum_ns / self.count if self.count else None,
                "p50_ns": self.percentile(.50), "p95_ns": self.percentile(.95),
                "p99_ns": self.percentile(.99), "max_ns": self.max_ns if self.count else None}


class ProgressTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_ns = time.monotonic_ns()
        self.max_gap_ns = 0

    def completed(self) -> None:
        now = time.monotonic_ns()
        with self.lock:
            self.max_gap_ns = max(self.max_gap_ns, now - self.last_ns)
            self.last_ns = now

    def snapshot_max_gap_ns(self) -> int:
        now = time.monotonic_ns()
        with self.lock:
            return max(self.max_gap_ns, now - self.last_ns)


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fixture_info(name: str, profile: str):
    path = Path(name).resolve(strict=True)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not info.st_size or info.st_size % PAGE:
        raise ValueError("fixture must be a regular stream of complete 4096-byte pages")
    metadata_path = path.with_suffix(".json")
    if not metadata_path.is_file() or metadata_path.is_symlink():
        alternate = path.parent / "fixture.json"
        if not alternate.is_file() or alternate.is_symlink():
            raise ValueError("fixture content metadata is missing")
        metadata_path = alternate
    metadata = json.loads(metadata_path.read_text())
    pages = info.st_size // PAGE
    digest = digest_file(path)
    if metadata.get("pages") != pages or metadata.get("page_bytes") != PAGE or metadata.get("fixture_sha256") != digest:
        raise ValueError("fixture metadata does not bind exact bytes")
    profiles = metadata.get("profile_pages") or {}
    if sum(profiles.values()) != pages:
        raise ValueError("fixture profile page accounting is incomplete")
    if profile == "entropy" and (profiles != {"entropy": pages} or metadata.get("raw_pages") != pages):
        raise ValueError("entropy fixture is not proven all-RAW entropy content")
    if profile == "balanced" and not (profiles.get("medium") == pages // 2 and
            profiles.get("entropy") == pages - pages // 2 and len(profiles) == 2):
        raise ValueError("balanced fixture must be exactly medium/entropy")
    if profile == "medium" and profiles != {"medium": pages}:
        raise ValueError("medium fixture metadata mismatch")
    if profile == "representative" and not (
            metadata.get("content_profile") == "representative" or profiles == {"representative": pages}):
        raise ValueError("representative fixture classification is missing")
    return path, pages, digest


def maximum_logical_pages(device_bytes: int) -> int:
    if device_bytes < PAGE or device_bytes % PAGE:
        return 0
    physical = ((device_bytes // PAGE - 1) // 256) * 256

    def fits(logical):
        reserve = max((logical + 7) // 8, 512)
        return reserve < physical and logical <= ((physical - reserve) // 256) * 256

    low, high = 0, physical
    while low < high:
        candidate = low + (high - low + 1) // 2
        if fits(candidate):
            low = candidate
        else:
            high = candidate - 1
    return low


def dev_text(device: int) -> str:
    return f"{os.major(device)}:{os.minor(device)}"


def sys_block_from_dev(text: str) -> Path:
    if not re.fullmatch(r"[0-9]+:[0-9]+", text or ""):
        raise ValueError("invalid expected major:minor")
    return (Path("/sys/dev/block") / text).resolve(strict=True)


def ancestry(dev: str) -> set[str]:
    pending, seen = [sys_block_from_dev(dev)], set()
    while pending:
        node = pending.pop()
        if node.name in seen:
            continue
        seen.add(node.name)
        slaves = node / "slaves"
        if slaves.is_dir():
            pending.extend(child.resolve(strict=True) for child in slaves.iterdir())
    return seen


def mount_device(path: Path):
    result = subprocess.run(["findmnt", "-T", str(path), "-nro", "MAJ:MIN,FSTYPE"],
                            text=True, capture_output=True, check=False, timeout=10)
    if result.returncode or not result.stdout.strip():
        raise ValueError("cannot resolve benchmark evidence filesystem")
    fields = result.stdout.split()
    if len(fields) != 2 or fields[1] in ("tmpfs", "ramfs", "devtmpfs", "overlay"):
        raise ValueError("benchmark evidence must reside on persistent non-target storage")
    return fields[0]


def require_clean_source(source_sha: str) -> None:
    root = Path(__file__).resolve().parents[3]

    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], text=True,
                              capture_output=True, check=True, timeout=20).stdout.strip()

    if git("rev-parse", "HEAD") != source_sha or git("rev-parse", "origin/main") != source_sha:
        raise ValueError("physical qualification requires HEAD == origin/main == source SHA")
    if git("status", "--porcelain"):
        raise ValueError("physical qualification requires clean source")


def acquire_physical_lock():
    path = Path("/run/lock/swapz-performance.lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    info = os.fstat(fd)
    if info.st_uid != 0 or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        os.close(fd)
        raise ValueError("physical benchmark lock is not root-private")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise ValueError("physical benchmark card is already owned")
    return fd


def selector_matches(partuuid: str) -> None:
    path = Path("/etc/swapz/primary-target")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("protected primary selector ownership is invalid")
    if path.read_text() != f"PARTUUID={partuuid}\n":
        raise ValueError("protected selector no longer names admitted card")


def check_in_use(devices: set[int]) -> None:
    for line in Path("/proc/swaps").read_text().splitlines()[1:]:
        try:
            info = Path(line.split()[0]).stat()
        except OSError:
            continue
        if stat.S_ISBLK(info.st_mode) and info.st_rdev in devices:
            raise ValueError("block replay refuses active swap identity")
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        fields = line.split()
        if len(fields) > 3:
            try:
                device = os.makedev(*map(int, fields[2].split(":")))
            except ValueError:
                continue
            if device in devices:
                raise ValueError("block replay refuses mounted identity")


def mapper_status(path: Path) -> str:
    result = subprocess.run(["dmsetup", "status", str(path)], text=True,
                            capture_output=True, check=False, timeout=10)
    if result.returncode:
        raise ValueError("swapz status unavailable")
    return result.stdout


def status_value(text: str, field: str) -> int:
    match = re.search(r"(?:^|\s)" + re.escape(field) + r"=(-?[0-9]+)(?:\s|$)", text)
    if not match:
        raise ValueError("swapz status missing " + field)
    return int(match.group(1))


def check_physical(args, logical_pages: int):
    if os.geteuid() != 0:
        raise ValueError("physical qualification requires root")
    virt = subprocess.run(["systemd-detect-virt", "--quiet"], check=False, timeout=10)
    if virt.returncode == 0:
        raise ValueError("physical qualification refuses VM/container")
    if virt.returncode != 1:
        raise ValueError("virtualization detection was inconclusive")
    required = (args.physical_partuuid, args.expected_lower_dev, args.expected_device_bytes,
                args.expected_parent_dev, args.expected_parent_model, args.expected_parent_transport)
    if any(value in (None, "") for value in required):
        raise ValueError("physical identity bundle is incomplete")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{7,127}", args.physical_partuuid):
        raise ValueError("invalid physical PARTUUID")
    require_clean_source(args.source_sha)
    selector_matches(args.physical_partuuid)
    args._physical_lock_fd = acquire_physical_lock()

    alias = (Path("/dev/disk/by-partuuid") / args.physical_partuuid).resolve(strict=True)
    lower_info = alias.stat()
    if not stat.S_ISBLK(lower_info.st_mode) or dev_text(lower_info.st_rdev) != args.expected_lower_dev:
        raise ValueError("PARTUUID alias major:minor mismatch")
    lower_sys = sys_block_from_dev(args.expected_lower_dev)
    if not (lower_sys / "partition").is_file():
        raise ValueError("selected target is not a partition")
    if int((lower_sys / "size").read_text()) * 512 != args.expected_device_bytes:
        raise ValueError("selected partition byte size changed")
    parent = lower_sys.parent
    if (parent / "dev").read_text().strip() != args.expected_parent_dev:
        raise ValueError("removable parent major:minor changed")
    if (parent / "removable").read_text().strip() != "1":
        raise ValueError("parent is not removable")
    model = (parent / "device/model").read_text().strip()
    transport = subprocess.run(["lsblk", "-dnro", "TRAN", "/dev/" + parent.name],
                               text=True, capture_output=True, check=True, timeout=10).stdout.strip()
    if model != args.expected_parent_model or transport != args.expected_parent_transport:
        raise ValueError("parent model/transport changed")
    partitions = [child for child in parent.iterdir() if (child / "partition").is_file()]
    if len(partitions) != 1 or partitions[0].resolve() != lower_sys:
        raise ValueError("selected card is not the sole-partition topology")
    root_dev = subprocess.run(["findmnt", "/", "-nro", "MAJ:MIN"], text=True,
                              capture_output=True, check=True, timeout=10).stdout.strip()
    if parent.name in ancestry(root_dev):
        raise ValueError("target parent participates in root storage")
    for local in (Path(args.fill_fixture), Path(args.churn_fixture), Path(args.result).parent):
        if parent.name in ancestry(mount_device(local.resolve())):
            raise ValueError("fixture/result storage shares the target parent")
    if logical_pages != maximum_logical_pages(args.expected_device_bytes):
        raise ValueError("physical replay must use manager maximum logical capacity")

    target = Path(args.device).resolve(strict=True)
    target_info = target.stat()
    if not stat.S_ISBLK(target_info.st_mode):
        raise ValueError("physical target is not block device")
    lower_dev = lower_info.st_rdev
    if args.candidate == "raw":
        if target_info.st_rdev != lower_dev or args.expected_dm_uuid:
            raise ValueError("raw arm must be exact bare partition with no DM UUID")
        if any((lower_sys / "holders").iterdir()):
            raise ValueError("raw partition has holder")
        if (logical_pages + 1) * PAGE > args.expected_device_bytes:
            raise ValueError("raw offset plus logical range exceeds partition")
        data_offset = PAGE
        dm_uuid = None
    else:
        if not args.expected_dm_uuid or not re.fullmatch(r"SWAPZ-(?:PRIMARY|BENCH)-[a-f0-9]{32}", args.expected_dm_uuid):
            raise ValueError("swapz arm requires pinned run UUID")
        target_sys = sys_block_from_dev(dev_text(target_info.st_rdev))
        if not target_sys.name.startswith("dm-") or (target_sys / "dm/uuid").read_text().strip() != args.expected_dm_uuid:
            raise ValueError("mapper UUID/device mismatch")
        if {child.resolve().name for child in (target_sys / "slaves").iterdir()} != {lower_sys.name}:
            raise ValueError("mapper does not depend exclusively on selected partition")
        if {child.resolve().name for child in (lower_sys / "holders").iterdir()} != {target_sys.name}:
            raise ValueError("selected partition has foreign/additional holder")
        if int((target_sys / "size").read_text()) * 512 != logical_pages * PAGE:
            raise ValueError("mapper size differs from maximum logical capacity")
        name = (target_sys / "dm/name").read_text().strip()
        table = subprocess.run(["dmsetup", "table", name], text=True,
                               capture_output=True, check=True, timeout=10).stdout
        config = REPLAY["validate_swapz_table"](table, logical_pages, args.expected_lower_dev, lower_sys.name)
        fresh = mapper_status(target)
        for field in ("logical_write", "physical_write", "gc_victims", "windows", "failed"):
            if status_value(fresh, field) != 0:
                raise ValueError("swapz arm is not fresh: " + field)
        data_offset = 0
        dm_uuid = args.expected_dm_uuid
    check_in_use({target_info.st_rdev, lower_dev})
    return target, os.O_RDWR | os.O_DIRECT | os.O_CLOEXEC, data_offset, {
        "device": dev_text(target_info.st_rdev), "owned_disk": parent.name,
        "lower_major_minor": args.expected_lower_dev, "physical_partuuid": args.physical_partuuid,
        "physical_device_bytes": args.expected_device_bytes, "parent_major_minor": args.expected_parent_dev,
        "parent_model": model, "parent_transport": transport, "dm_uuid": dm_uuid,
        "swapz_config": config if args.candidate == "swapz" else None,
    }


def check_rootless(args, logical_pages: int):
    path = Path(args.device).resolve(strict=True)
    info = path.stat()
    root = Path(tempfile.gettempdir()).resolve()
    if not stat.S_ISREG(info.st_mode) or not path.is_relative_to(root) or not path.name.startswith("swapz-sustain-"):
        raise ValueError("rootless target must be an explicit private temp regular file")
    if info.st_size != logical_pages * PAGE:
        raise ValueError("rootless target size mismatch")
    return path, os.O_RDWR | os.O_CLOEXEC, 0, {"test_regular_file": str(path)}


def quiet_window():
    before = REPLAY["host_cpu_snapshot"]()
    time.sleep(.2)
    after = REPLAY["host_cpu_snapshot"]()
    observed = REPLAY["host_cpu_delta"](before, after)
    reasons = []
    if observed.get("status") != "AVAILABLE":
        reasons.append("quiet-window counters unavailable")
    else:
        if observed.get("busy_fraction", 1) > .25:
            reasons.append("quiet-window busy exceeds 25%")
        if observed.get("pressure_some_fraction", 1) > .05:
            reasons.append("quiet-window CPU PSI exceeds 5%")
        if observed.get("steal_fraction", 1) > .01:
            reasons.append("quiet-window steal exceeds 1%")
    return {"observed": observed, "reasons": reasons}


def parse_process_hwm_bytes(status_text: str) -> int:
    matches = re.findall(
        r"^VmHWM:[ \t]+([0-9]+)[ \t]+kB[ \t]*$",
        status_text, re.MULTILINE)
    if len(matches) != 1:
        raise RuntimeError("cannot read unique process VmHWM")
    kib = int(matches[0])
    if kib <= 0 or kib > (1 << 53) // 1024:
        raise RuntimeError("process VmHWM is outside supported bounds")
    return kib * 1024


def process_hwm_bytes() -> int:
    with open("/proc/self/status", "r", encoding="ascii") as stream:
        status_text = stream.read(65537)
    if len(status_text) > 65536:
        raise RuntimeError("/proc/self/status exceeds bounded parser input")
    return parse_process_hwm_bytes(status_text)


def process_cpu():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # ru_maxrss is intentionally not used: Linux preserves resource usage
    # high-water counters across execve(), so a replay launched by a large
    # harness can inherit a peak it never allocated. VmHWM is post-exec.
    return usage.ru_utime, usage.ru_stime, process_hwm_bytes()


def full_write(fd: int, offset: int, payload) -> None:
    if os.pwrite(fd, payload, offset) != PAGE:
        raise OSError("short direct write")


def full_read(fd: int, offset: int, view, expected) -> None:
    if os.preadv(fd, [view], offset) != PAGE or view != expected:
        raise OSError("short or mismatched direct read")


def read_fixture(path: Path):
    stream = path.open("rb")
    mapping = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
    view = memoryview(mapping)
    chunks = [view[i:i + PAGE] for i in range(0, len(view), PAGE)]
    return stream, mapping, view, chunks


def fill_device(fd, data_offset: int, occupied: int, qd: int, chunks, seed: int,
                pool):
    start = time.monotonic_ns()

    def lane(lane_index):
        for page in range(lane_index, occupied, qd):
            full_write(fd, data_offset + page * PAGE,
                       chunks[payload_index(page, 0, len(chunks), seed)])

    list(pool.map(lane, range(qd)))
    os.fsync(fd)
    seconds = (time.monotonic_ns() - start) / 1e9
    return {"pages": occupied, "seconds": seconds,
            "logical_write_mbps": occupied * PAGE / seconds / 1_000_000}


def phase_workers(fd, data_offset: int, args, hot_pages: int, fill_chunks, churn_chunks,
                  warmup: bool, pool, initial_writes=None, progress=None):
    qd = args.qd
    initial_writes = initial_writes or [0] * qd
    progress = progress or ProgressTracker()
    phase_start = time.monotonic_ns()
    phase_seconds = args.warmup_seconds if warmup else args.measure_seconds
    deadline = phase_start + int(phase_seconds * 1e9) if phase_seconds is not None else None
    operations = args.warmup_operations if warmup else args.measure_operations
    per_lane = [operations // qd + (1 if lane < operations % qd else 0)
                for lane in range(qd)] if operations is not None else None

    def worker(lane):
        lane_pages = (hot_pages - lane + qd - 1) // qd if lane < hot_pages else 0
        if lane_pages <= 0:
            return {"lane": lane, "writes": initial_writes[lane],
                    "read": LatencyHistogram(), "write": LatencyHistogram(),
                    "minutes": {}, "ops": 0}
        stride = coprime_stride(lane_pages, args.seed ^ (lane << 20))
        offset = sequence_offset(lane_pages, args.seed ^ (lane << 28))
        write_count = initial_writes[lane]
        read_hist, write_hist, minutes = LatencyHistogram(), LatencyHistogram(), {}
        operation = 0
        while ((per_lane is None and time.monotonic_ns() < deadline) or
               (per_lane is not None and operation < per_lane[lane])):
            chooser = splitmix64(args.seed ^ (lane << 48) ^ (write_count << 16) ^
                                 operation ^ (0xBAD5EED if warmup else 0xC0FFEE))
            is_read = chooser % 100 < args.read_percent
            minute = max(0, (time.monotonic_ns() - phase_start) // 60_000_000_000)
            bucket = minutes.setdefault(int(minute), {
                "read": LatencyHistogram(), "write": LatencyHistogram(), "writes": 0})
            if is_read:
                local = splitmix64(chooser ^ 0x9E3779B97F4A7C15) % lane_pages
                page = lane + qd * local
                latest = latest_write_index(local, write_count, lane_pages, stride, offset)
                expected = (
                    fill_chunks[payload_index(page, 0, len(fill_chunks), args.seed)]
                    if latest is None else
                    churn_chunks[payload_index(page, latest + 1, len(churn_chunks), args.seed)]
                )
                buffer = mmap.mmap(-1, PAGE)
                view = memoryview(buffer)
                try:
                    begin = time.monotonic_ns()
                    full_read(fd, data_offset + page * PAGE, view, expected)
                    elapsed = time.monotonic_ns() - begin
                finally:
                    view.release()
                    buffer.close()
                read_hist.observe(elapsed)
                bucket["read"].observe(elapsed)
            else:
                page = lane_page(lane, qd, lane_pages, write_count, stride, offset)
                payload = churn_chunks[payload_index(
                    page, write_count + 1, len(churn_chunks), args.seed)]
                begin = time.monotonic_ns()
                full_write(fd, data_offset + page * PAGE, payload)
                elapsed = time.monotonic_ns() - begin
                write_hist.observe(elapsed)
                bucket["write"].observe(elapsed)
                bucket["writes"] += 1
                write_count += 1
            operation += 1
            progress.completed()
        return {"lane": lane, "writes": write_count, "read": read_hist,
                "write": write_hist, "minutes": minutes, "ops": operation}

    results = list(pool.map(worker, range(qd)))
    os.fsync(fd)
    return results, progress, (time.monotonic_ns() - phase_start)


def merge_phase(results, wall_ns: int, hot_pages: int | None = None):
    read_hist, write_hist = LatencyHistogram(), LatencyHistogram()
    minutes = {}
    lane_count = len(results)
    for result in results:
        read_hist.merge(result["read"])
        write_hist.merge(result["write"])
        lane = result["lane"]
        for minute, row in result["minutes"].items():
            target = minutes.setdefault(minute, {
                "read": LatencyHistogram(), "write": LatencyHistogram(),
                "writes": 0, "lane_writes": [0] * lane_count})
            target["read"].merge(row["read"])
            target["write"].merge(row["write"])
            target["writes"] += row["writes"]
            target["lane_writes"][lane] += row["writes"]

    rows = []
    cumulative_lane_writes = [0] * lane_count
    for minute in sorted(minutes):
        row = minutes[minute]
        seconds = min(60.0, wall_ns / 1e9 - minute * 60.0)
        combined = LatencyHistogram()
        combined.merge(row["read"])
        combined.merge(row["write"])
        cumulative_lane_writes = [
            total + current
            for total, current in zip(cumulative_lane_writes, row["lane_writes"])
        ]
        output = {
            "minute": minute,
            "logical_write_mbps":
                row["writes"] * PAGE / max(seconds, 1e-9) / 1_000_000,
            "p95_ns": combined.percentile(.95),
            "p99_ns": combined.percentile(.99),
            "read_p95_ns": row["read"].percentile(.95),
            "read_p99_ns": row["read"].percentile(.99),
            "write_p95_ns": row["write"].percentile(.95),
            "write_p99_ns": row["write"].percentile(.99),
            "read_operations": row["read"].count,
            "write_operations": row["write"].count,
            "operations": combined.count,
        }
        if hot_pages is not None:
            output["cumulative_overwrite"] = overwrite_coverage(
                hot_pages, lane_count, cumulative_lane_writes)
        rows.append(output)
    return read_hist, write_hist, rows


def overwrite_coverage(hot_pages: int, qd: int,
                       measured_writes_per_lane: list[int]) -> dict:
    """Summarize measured-phase overwrites without a page-sized oracle map."""
    if hot_pages < qd or len(measured_writes_per_lane) != qd:
        raise ValueError("invalid overwrite coverage geometry")
    touched = 0
    rewritten = 0
    repeat_operations = 0
    minimum_writes = None
    maximum_writes = 0
    for lane, writes in enumerate(measured_writes_per_lane):
        if type(writes) is not int or writes < 0:
            raise ValueError("invalid measured lane write count")
        lane_pages = (hot_pages - lane + qd - 1) // qd
        if lane_pages <= 0:
            raise ValueError("empty measured overwrite lane")
        full_cycles, remainder = divmod(writes, lane_pages)
        touched += min(writes, lane_pages)
        repeat_operations += max(0, writes - lane_pages)
        if full_cycles == 0:
            lane_rewritten = 0
        elif full_cycles == 1:
            lane_rewritten = remainder
        else:
            lane_rewritten = lane_pages
        rewritten += lane_rewritten
        minimum_writes = (full_cycles if minimum_writes is None
                          else min(minimum_writes, full_cycles))
        maximum_writes = max(
            maximum_writes, full_cycles + (1 if remainder else 0))
    return {
        "hot_pages": hot_pages,
        "measured_hot_pages_touched": touched,
        "measured_hot_pages_rewritten": rewritten,
        "measured_repeat_write_operations": repeat_operations,
        "measured_rewrite_fraction": rewritten / hot_pages,
        "measured_min_writes_per_hot_page": minimum_writes or 0,
        "measured_max_writes_per_hot_page": maximum_writes,
    }


def final_oracle(fd, data_offset, args, occupied, hot,
                 fill_chunks, churn_chunks, writes_per_lane):
    digest_expected, digest_actual = hashlib.sha256(), hashlib.sha256()
    mismatches = 0
    buffer = mmap.mmap(-1, PAGE)
    view = memoryview(buffer)
    try:
        for page in range(occupied):
            if page < hot:
                lane = page % args.qd
                local = page // args.qd
                lane_pages = (hot - lane + args.qd - 1) // args.qd
                stride = coprime_stride(lane_pages, args.seed ^ (lane << 20))
                offset = sequence_offset(lane_pages, args.seed ^ (lane << 28))
                latest = latest_write_index(
                    local, writes_per_lane[lane], lane_pages, stride, offset)
            else:
                latest = None
            expected = (
                fill_chunks[payload_index(page, 0, len(fill_chunks), args.seed)]
                if latest is None else
                churn_chunks[payload_index(page, latest + 1, len(churn_chunks), args.seed)]
            )
            if os.preadv(fd, [view], data_offset + page * PAGE) != PAGE:
                raise OSError("short final read")
            digest_expected.update(expected)
            digest_actual.update(view)
            if view != expected:
                mismatches += 1
                if mismatches > 16:
                    raise ValueError("final oracle mismatch limit exceeded")
    finally:
        view.release()
        buffer.close()
    return {"verified_pages": occupied, "mismatches": mismatches,
            "expected_sha256": digest_expected.hexdigest(),
            "actual_sha256": digest_actual.hexdigest()}


def cold_read(fd, data_offset, args, occupied, hot, fill_chunks):
    cold = occupied - hot
    count = min(args.cold_read_pages, cold)
    if count <= 0:
        return {"pages": 0, **LatencyHistogram().summary()}
    hist = LatencyHistogram()
    buffer = mmap.mmap(-1, PAGE)
    view = memoryview(buffer)
    try:
        for index in range(count):
            page = hot + index * cold // count
            expected = fill_chunks[payload_index(page, 0, len(fill_chunks), args.seed)]
            begin = time.monotonic_ns()
            full_read(fd, data_offset + page * PAGE, view, expected)
            hist.observe(time.monotonic_ns() - begin)
    finally:
        view.release()
        buffer.close()
    return {"pages": count, **hist.summary()}


def status_snapshot(path: Path, identity: dict):
    if not identity.get("dm_uuid"):
        return None
    text = mapper_status(path)
    fields = ("gc_wall_ns", "gc_no_headroom_skips", "gc_victims",
              "gc_role_rotations", "gc_pages", "gc_read", "gc_write",
              "gc_read_reqs", "gc_write_reqs", "alloc_probe_segments",
              "alloc_probe_full_scans", "alloc_probe_wall_ns",
              "segment_program_sum", "cursor", "reserve", "last_gc_victim",
              "last_gc_destination", "failed", "error")
    return {field: status_value(text, field) for field in fields}


def status_delta(before, after, wall_ns):
    if before is None and after is None:
        return None
    if before is None or after is None:
        raise ValueError("incomplete target status interval")
    gauges = {
        "cursor", "reserve", "last_gc_victim", "last_gc_destination",
        "failed", "error",
    }
    result = {}
    for field in before:
        result[field] = after[field] if field in gauges else after[field] - before[field]
        if field not in gauges and result[field] < 0:
            raise ValueError("target counter reset: " + field)
    result["wall_fraction"] = result["gc_wall_ns"] / wall_ns if wall_ns else None
    return result


class SustainedIntervalSampler:
    """Low-rate host/lower-device telemetry outside the replay hot path."""

    def __init__(self, lower_disk: str | None, progress: ProgressTracker,
                 interval_seconds: float = 60.0):
        self.lower_disk = lower_disk
        self.progress = progress
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.thread = None
        self.previous = None
        self.rows = []
        self.error = None
        self.start_ns = None

    def _snapshot(self) -> dict:
        return {
            "time_ns": time.monotonic_ns(),
            "host_cpu": REPLAY["host_cpu_snapshot"](),
            "lower": REPLAY["lower_stat"](self.lower_disk),
            "max_no_progress_ns": self.progress.snapshot_max_gap_ns(),
        }

    def _append(self, current: dict, minimum_ns: int = 0) -> None:
        previous = self.previous
        if previous is None:
            self.previous = current
            return
        duration_ns = current["time_ns"] - previous["time_ns"]
        if duration_ns < minimum_ns:
            return
        lower = (
            REPLAY["iostat_delta"](previous["lower"], current["lower"])
            if previous["lower"] is not None else None)
        self.rows.append({
            "interval": len(self.rows),
            "start_seconds": (previous["time_ns"] - self.start_ns) / 1e9,
            "end_seconds": (current["time_ns"] - self.start_ns) / 1e9,
            "duration_seconds": duration_ns / 1e9,
            "host_cpu": REPLAY["host_cpu_delta"](
                previous["host_cpu"], current["host_cpu"]),
            "lower_io": lower,
            "max_no_progress_seconds":
                current["max_no_progress_ns"] / 1e9,
        })
        self.previous = current

    def _run(self) -> None:
        try:
            while not self.stop_event.wait(self.interval_seconds):
                self._append(self._snapshot())
        except (OSError, ValueError) as exc:
            self.error = exc
            self.stop_event.set()

    def start(self) -> None:
        if self.thread is not None:
            raise ValueError("sustained interval sampler already started")
        self.start_ns = time.monotonic_ns()
        self.previous = self._snapshot()
        self.thread = threading.Thread(
            target=self._run, name="swapz-sustained-telemetry", daemon=True)
        self.thread.start()

    def stop(self) -> list[dict]:
        if self.thread is None:
            return []
        self.stop_event.set()
        self.thread.join(timeout=max(5.0, self.interval_seconds / 2.0))
        if self.thread.is_alive():
            raise ValueError("sustained interval telemetry failed to stop")
        if self.error is not None:
            raise ValueError(
                "sustained interval telemetry failed: " + str(self.error))
        self._append(self._snapshot(), minimum_ns=1_000_000_000)
        return list(self.rows)


def run(args):
    if not 1 <= args.qd <= 32 or not 0 <= args.read_percent <= 100:
        raise ValueError("invalid queue depth/read percentage")
    if not 1 <= args.occupancy_percent <= 100 or not 1 <= args.hot_percent <= args.occupancy_percent:
        raise ValueError("invalid logical occupancy/hot percentages")
    if (args.measure_operations is None) == (args.measure_seconds is None):
        raise ValueError("select exactly one measured operation or duration bound")
    if args.warmup_operations is not None and args.warmup_seconds is not None:
        raise ValueError("select at most one warmup bound")
    physical = not args.regular_file_test
    if physical and not re.fullmatch(r"[a-f0-9]{40}", args.source_sha or ""):
        raise ValueError("physical qualification requires exact source SHA")
    if physical and args.candidate == "swapz" and args.metadata_and_target_peak_ram_bytes is None:
        raise ValueError("physical swapz qualification requires observed metadata/target peak RAM")
    if args.metadata_and_target_peak_ram_bytes is not None and args.metadata_and_target_peak_ram_bytes < 0:
        raise ValueError("metadata/target peak RAM must be nonnegative")

    private = REPLAY["private_memory"]
    if (args.fill_content_profile == "representative" or
            args.churn_content_profile == "representative" or
            private.fixture_is_representative(args.fill_fixture) or
            private.fixture_is_representative(args.churn_fixture)):
        private.protect_private_memory()
        os.environ["SWAPZ_PRIVATE_FIXTURE"] = "1"
    fill_path, fill_pages, fill_sha = fixture_info(
        args.fill_fixture, args.fill_content_profile)
    churn_path, churn_pages, churn_sha = fixture_info(
        args.churn_fixture, args.churn_content_profile)
    logical = args.logical_pages
    occupied = logical * args.occupancy_percent // 100
    hot = logical * args.hot_percent // 100
    if logical < args.qd or occupied <= hot or hot < args.qd:
        raise ValueError("logical geometry too small")
    target, flags, data_offset, identity = (
        check_rootless(args, logical) if args.regular_file_test
        else check_physical(args, logical))
    partial = {"schema": SCHEMA, "workload_id": args.workload_id,
               "candidate": args.candidate, "source_sha": args.source_sha,
               "device_identity": identity}
    args._partial_report = partial

    fill_stream, fill_map, fill_view, fill_chunks = read_fixture(fill_path)
    churn_stream, churn_map, churn_view, churn_chunks = read_fixture(churn_path)
    try:
        fd = os.open(target, flags)
        try:
            # Reuse one bounded QD worker set across fill, warmup and measure.
            # Recreating pthread pools can retain multiple default-size stacks
            # in libc and make peak RSS scale with phase count instead of QD.
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.qd) as pool:
                fill = fill_device(
                    fd, data_offset, occupied, args.qd, fill_chunks, args.seed,
                    pool)
                partial["fill"] = fill
                warm_results, _, _ = phase_workers(
                    fd, data_offset, args, hot, fill_chunks, churn_chunks, True,
                    pool)
                initial_writes = [row["writes"] for row in warm_results]

                pre_quiet = quiet_window()
                if identity.get("dm_uuid"):
                    REPLAY["kernel_write_profile_epoch"](target, identity)
                lower_before = REPLAY["lower_stat"](identity.get("owned_disk"))
                write_before = REPLAY["kernel_write_snapshot"](target, identity)
                read_before = REPLAY["kernel_read_snapshot"](target, identity)
                status_before = status_snapshot(target, identity)
                host_before = REPLAY["host_cpu_snapshot"]()
                cpu_before = process_cpu()
                measured_progress = ProgressTracker()
                interval_sampler = (
                    SustainedIntervalSampler(
                        identity.get("owned_disk"), measured_progress)
                    if args.measure_seconds is not None else None)
                if interval_sampler is not None:
                    interval_sampler.start()
                start = time.monotonic_ns()
                try:
                    measured, measured_progress, wall_ns = phase_workers(
                        fd, data_offset, args, hot, fill_chunks, churn_chunks, False,
                        pool, initial_writes, measured_progress)
                    end = time.monotonic_ns()
                    cpu_after = process_cpu()
                    host_after = REPLAY["host_cpu_snapshot"]()
                finally:
                    interval_rows = (
                        interval_sampler.stop()
                        if interval_sampler is not None else [])
            status_after = status_snapshot(target, identity)
            read_after = REPLAY["kernel_read_snapshot"](target, identity)
            write_after = REPLAY["kernel_write_snapshot"](target, identity)
            lower_after = REPLAY["lower_stat"](identity.get("owned_disk"))
            post_quiet = quiet_window()

            seconds = (end - start) / 1e9
            read_hist, write_hist, minute_rows = merge_phase(
                measured, wall_ns, hot)
            read_ops, write_ops = read_hist.count, write_hist.count
            measured_writes_per_lane = [
                row["writes"] - initial_writes[index]
                for index, row in enumerate(measured)
            ]
            if sum(measured_writes_per_lane) != write_ops:
                raise ValueError("measured overwrite accounting mismatch")
            overwrite = overwrite_coverage(
                hot, args.qd, measured_writes_per_lane)
            logical_write_bytes, logical_read_bytes = write_ops * PAGE, read_ops * PAGE
            lower = (REPLAY["iostat_delta"](lower_before, lower_after)
                     if lower_before is not None else None)
            if lower is not None:
                lower["lower_write_bytes_per_logical_write_byte"] = (
                    lower["lower_write_bytes"] / logical_write_bytes
                    if logical_write_bytes else None)
                lower["lower_write_requests_per_1000_logical_writes"] = (
                    lower["lower_write_requests"] * 1000 / write_ops
                    if write_ops else None)
                lower["lower_read_bytes_per_logical_read_byte"] = (
                    lower["lower_read_bytes"] / logical_read_bytes
                    if logical_read_bytes else None)
            kernel_write = REPLAY["kernel_write_delta"](write_before, write_after)
            kernel_read = REPLAY["kernel_read_delta"](read_before, read_after)
            worker_cpu_ns = (
                sum((kernel_write or {}).get(key, 0)
                    for key in ("ordered_worker_cpu_ns", "prep_worker_cpu_ns")) +
                (kernel_read or {}).get("read_worker_cpu_ns", 0))
            replay_cpu = (
                max(0., cpu_after[0] - cpu_before[0]) +
                max(0., cpu_after[1] - cpu_before[1]))
            useful = logical_write_bytes + logical_read_bytes
            measured_cpu = replay_cpu + worker_cpu_ns / 1e9
            screening = list(pre_quiet["reasons"]) + list(post_quiet["reasons"])
            host_cpu = REPLAY["host_cpu_delta"](host_before, host_after)
            if host_cpu.get("steal_fraction") is None or host_cpu.get("steal_fraction") > .01:
                screening.append("timed-arm steal exceeds 1% or is unavailable")

            cold_lower_before = REPLAY["lower_stat"](identity.get("owned_disk"))
            cold_read_result = cold_read(
                fd, data_offset, args, occupied, hot, fill_chunks)
            cold_lower_after = REPLAY["lower_stat"](identity.get("owned_disk"))
            cold_read_result["lower_io"] = (
                REPLAY["iostat_delta"](cold_lower_before, cold_lower_after)
                if cold_lower_before is not None else None)

            writes_per_lane = [row["writes"] for row in measured]
            oracle = final_oracle(
                fd, data_offset, args, occupied, hot,
                fill_chunks, churn_chunks, writes_per_lane)
            if oracle["mismatches"]:
                raise ValueError("final byte oracle failed")
            gc = status_delta(status_before, status_after, wall_ns)

            report = {
                "schema": SCHEMA, "verdict": "PASS",
                "workload_id": args.workload_id, "candidate": args.candidate,
                "source_sha": args.source_sha, "device_identity": identity,
                "logical_pages": logical, "occupied_pages": occupied,
                "hot_pages": hot, "occupancy_percent": args.occupancy_percent,
                "hot_percent": args.hot_percent, "qd": args.qd,
                "read_percent": args.read_percent, "workload_seed": args.seed,
                "fill_fixture_sha256": fill_sha,
                "churn_fixture_sha256": churn_sha,
                "fill_content_profile": args.fill_content_profile,
                "churn_content_profile": args.churn_content_profile,
                "operation_recipe_sha256": hashlib.sha256(json.dumps({
                    "seed": args.seed, "logical": logical,
                    "occupied": occupied, "hot": hot, "qd": args.qd,
                    "read": args.read_percent, "fill": fill_sha,
                    "churn": churn_sha}, sort_keys=True).encode()).hexdigest(),
                "warmup_operations": args.warmup_operations,
                "warmup_seconds": args.warmup_seconds,
                "measure_operations": args.measure_operations,
                "measure_seconds_requested": args.measure_seconds,
                "fill": fill, "seconds": seconds,
                "read_ops": read_ops, "write_ops": write_ops,
                "throughput": {
                    "logical_write_mbps": logical_write_bytes / seconds / 1_000_000,
                    "logical_read_mbps": logical_read_bytes / seconds / 1_000_000,
                    "logical_total_mbps": useful / seconds / 1_000_000},
                "latency": {
                    "read_p50_ns": read_hist.percentile(.50),
                    "read_p95_ns": read_hist.percentile(.95),
                    "read_p99_ns": read_hist.percentile(.99),
                    "read_max_ns": read_hist.max_ns,
                    "write_p50_ns": write_hist.percentile(.50),
                    "write_p95_ns": write_hist.percentile(.95),
                    "write_p99_ns": write_hist.percentile(.99),
                    "write_max_ns": write_hist.max_ns},
                "cpu": {
                    "replay_user_seconds": max(0., cpu_after[0] - cpu_before[0]),
                    "replay_system_seconds": max(0., cpu_after[1] - cpu_before[1]),
                    "exported_swapz_worker_cpu_seconds": worker_cpu_ns / 1e9,
                    "measured_cpu_seconds_per_useful_byte": (
                        measured_cpu / useful if useful else None),
                    "scope": (
                        "replay process plus exported swapz worker CPU; "
                        "other kernel CPU excluded")},
                "resources": {
                    "replay_peak_rss_bytes": cpu_after[2],
                    "replay_process_maxrss_bytes": cpu_after[2],
                    "replay_measurement_start_maxrss_bytes": cpu_before[2],
                    "replay_measurement_peak_rss_growth_bytes":
                        max(0, cpu_after[2] - cpu_before[2]),
                    "metadata_and_target_peak_ram_bytes":
                        args.metadata_and_target_peak_ram_bytes or 0,
                    "metadata_ram_scope": (
                        "scheduler-observed mapper creation/workload peak"
                        if identity.get("dm_uuid") else "not applicable")},
                "host_cpu": host_cpu,
                "performance_screening": {
                    "status": "SCREENED" if not screening else "EXCLUDED",
                    "reasons": screening, "pre": pre_quiet, "post": post_quiet},
                "lower_io": lower, "kernel_write_path": kernel_write,
                "kernel_read_path": kernel_read, "gc": gc,
                "cold_read": cold_read_result, "minute_buckets": minute_rows,
                "sustained_intervals": interval_rows,
                "overwrite": overwrite,
                "occupancy_transitions": [
                    {"phase": "initial", "occupied_pages": 0,
                     "logical_occupancy_percent": 0},
                    {"phase": "post-fill", "occupied_pages": occupied,
                     "logical_occupancy_percent": args.occupancy_percent},
                    {"phase": "post-warmup", "occupied_pages": occupied,
                     "logical_occupancy_percent": args.occupancy_percent},
                    {"phase": "measured-end", "occupied_pages": occupied,
                     "logical_occupancy_percent": args.occupancy_percent},
                ],
                "target_status_before": status_before,
                "target_status_after": status_after,
                "max_no_progress_seconds": measured_progress.max_gap_ns / 1e9,
                "oracle": oracle,
                "claim_boundary": (
                    "host-visible lower bytes/requests are physical I/O cost, "
                    "not direct NAND endurance"),
            }
            args._partial_report = report
            output = Path(args.result)
            if output.exists():
                raise ValueError("refusing to overwrite sustained result")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            print(json.dumps(report, sort_keys=True))
        finally:
            os.close(fd)
    finally:
        for view in fill_chunks + churn_chunks:
            view.release()
        fill_view.release()
        churn_view.release()
        fill_map.close()
        churn_map.close()
        fill_stream.close()
        churn_stream.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload-id", required=True)
    parser.add_argument("--candidate", choices=("raw", "swapz"), required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--fill-fixture", required=True)
    parser.add_argument("--churn-fixture", required=True)
    parser.add_argument("--fill-content-profile",
                        choices=("entropy", "balanced", "representative", "medium"),
                        required=True)
    parser.add_argument("--churn-content-profile",
                        choices=("entropy", "balanced", "representative", "medium"),
                        required=True)
    parser.add_argument("--logical-pages", type=int, required=True)
    parser.add_argument("--occupancy-percent", type=int, required=True)
    parser.add_argument("--hot-percent", type=int, required=True)
    parser.add_argument("--qd", type=int, required=True)
    parser.add_argument("--read-percent", type=int, required=True)
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=0x51A0A9)
    parser.add_argument("--warmup-operations", type=int)
    parser.add_argument("--warmup-seconds", type=float)
    parser.add_argument("--measure-operations", type=int)
    parser.add_argument("--measure-seconds", type=float)
    parser.add_argument("--cold-read-pages", type=int, default=65536)
    parser.add_argument("--regular-file-test", action="store_true")
    parser.add_argument("--physical-partuuid")
    parser.add_argument("--expected-lower-dev")
    parser.add_argument("--expected-device-bytes", type=int)
    parser.add_argument("--expected-parent-dev")
    parser.add_argument("--expected-parent-model")
    parser.add_argument("--expected-parent-transport")
    parser.add_argument("--expected-dm-uuid")
    parser.add_argument("--metadata-and-target-peak-ram-bytes", type=int)
    args = parser.parse_args()
    exit_error = None
    try:
        run(args)
    except (OSError, ValueError, KeyError, TypeError,
            subprocess.SubprocessError) as exc:
        failure = dict(getattr(args, "_partial_report", {}) or {})
        failure.update({
            "schema": SCHEMA, "verdict": "FAIL",
            "workload_id": args.workload_id, "candidate": args.candidate,
            "source_sha": args.source_sha, "failure_reason": str(exc)})
        try:
            output = Path(args.result)
            if not output.exists():
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    json.dumps(failure, indent=2, sort_keys=True) + "\n")
        except OSError:
            pass
        exit_error = exc
    finally:
        lock_fd = getattr(args, "_physical_lock_fd", None)
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
    if exit_error is not None:
        parser.exit(2, "BLOCKED/FAIL: " + str(exit_error) + "\n")


if __name__ == "__main__":
    main()
