#!/usr/bin/env python3
"""Immutable trace preparation and owned-device replay for off/swapz.

Synthetic BLOCK-PATH experiment, not Linux's actual swapon reclaim policy.
Generation and rootless replay need no privilege. Block replay refuses unowned
or physical storage and must be run only on preflighted RAM null_blk targets.
Both arms consume the identical fixture and ordered logical I/O trace.
"""
import argparse
import concurrent.futures
import hashlib
import json
import mmap
import math
import os
import random
import resource
import re
import stat
import subprocess
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path

PAGE = 4096
SCHEMA = 1
CANDIDATES = ("off", "swapz")
LOWER_INFLIGHT_SAMPLE_INTERVAL_NS = 500000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_load(path):
    return json.loads(Path(path).read_text())


def fixture_info(path):
    path = Path(path).resolve(strict=True)
    if path.stat().st_size % PAGE or not path.stat().st_size:
        raise ValueError("fixture must contain full 4096B pages")
    return path.stat().st_size // PAGE, digest_file(path)


def choose_slot(rng, start, count, used):
    if count <= len(used):
        raise ValueError("more simultaneous operations than available unique slots")
    slot = start + rng.randrange(count)
    for _ in range(count):
        if slot not in used:
            return slot
        slot = start + (slot - start + 1) % count
    raise ValueError("no independent logical page in this wave")


def nonzero_same_filled_page(page):
    """True for one repeated nonzero 64-bit word across the 4KiB page."""
    if len(page) != PAGE:
        raise ValueError("opportunity analysis requires complete pages")
    word = page[:8]
    return word != b"\x00" * 8 and word * (PAGE // 8) == page


def workload_opportunity(events, pages, logical_pages):
    """Offline payload opportunity only; never a kernel performance claim."""
    live = [pages[i % len(pages)] for i in range(logical_pages)]
    resident = {}
    for payload in live:
        resident[payload] = resident.get(payload, 0) + 1
    measured_writes = same_filled = same_page = resident_dup = 0
    measured_payloads = set()
    for event in events:
        if event["op"] != "W":
            continue
        old = live[event["page"]]
        new = pages[event["fixture"]]
        if event["phase"] == "measure":
            measured_writes += 1
            measured_payloads.add(new)
            same_filled += int(nonzero_same_filled_page(new))
            same_page += int(old == new)
            resident_dup += int(
                resident.get(new, 0) - (1 if old == new else 0) > 0)
        if old != new:
            resident[old] -= 1
            if not resident[old]:
                del resident[old]
            resident[new] = resident.get(new, 0) + 1
            live[event["page"]] = new
    return {
        "scope": "TRACE_FIXTURE_OPPORTUNITY_ONLY_NOT_KERNEL_SAVINGS",
        "measured_write_ops": measured_writes,
        "measured_unique_write_payloads": len(measured_payloads),
        "nonzero_same_filled_write_ops": same_filled,
        "same_page_rewrite_ops": same_page,
        "resident_duplicate_write_ops": resident_dup,
        "final_live_unique_payloads": len(resident),
        "final_live_duplicate_pages":
            sum(count for count in resident.values() if count > 1),
        "final_live_nonzero_same_filled_pages":
            sum(1 for payload in live if nonzero_same_filled_page(payload)),
    }


def prepare(args):
    fixture_pages, fixture_hash = fixture_info(args.fixture)
    if args.qd < 1 or args.qd > 32 or args.measure_ops < 1:
        raise ValueError("QD must be 1..32 and measure_ops positive")
    if args.warmup_ops < 0 or args.measure_ops % args.qd or args.warmup_ops % args.qd:
        raise ValueError("measurement and warmup operations must each be a multiple of QD")
    if not (0 <= args.read_pct <= 100):
        raise ValueError("read_pct must be in 0..100")
    if args.writer_pages < args.qd or args.writer_pages > args.logical_pages:
        raise ValueError("writer_pages must accommodate an entire QD wave")
    if args.reader_pages < args.qd or args.reader_start < 0 or (
        args.reader_start + args.reader_pages > args.logical_pages
    ):
        raise ValueError("reader region must accommodate an entire QD wave")
    if args.layout == "disjoint" and not (
        args.reader_start >= args.writer_pages
    ):
        raise ValueError("disjoint regions must not overlap")
    if args.iops < 0:
        raise ValueError("rate must be >=0")
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if list(out.iterdir()):
        raise ValueError("refusing to overwrite any existing output files")
    rng = random.Random(args.seed)
    latest = [i % fixture_pages for i in range(args.logical_pages)]
    events = []
    total = args.warmup_ops + args.measure_ops
    # A "wave" is a bounded group of QD logically independent pages.
    # It has an explicit barrier before the next wave. Completion order
    # inside a wave may vary, but data dependencies and final image cannot.
    for first in range(0, total, args.qd):
        used = set()
        wave = []
        for pos in range(args.qd):
            write = rng.randrange(100) >= args.read_pct
            if write:
                slot = choose_slot(rng, 0, args.writer_pages, used)
                fi = rng.randrange(fixture_pages)
                kind = "W"
            else:
                slot = choose_slot(rng, args.reader_start,
                                   args.reader_pages, used)
                fi = latest[slot]
                kind = "R"
            used.add(slot)
            wave.append({"seq": first + pos, "phase": "warmup" if first < args.warmup_ops else "measure",
                         "wave": first // args.qd, "op": kind,
                         "page": slot, "fixture": fi})
        events.extend(wave)
        for item in wave:
            if item["op"] == "W":
                latest[item["page"]] = item["fixture"]
    # No file extension or fake compression class decides the bytes.
    with open(args.fixture, "rb") as stream:
        pages = [stream.read(PAGE) for _ in range(fixture_pages)]
    h = hashlib.sha256()
    for e in events:
        if e["op"] == "W":
            h.update(struct.pack("<QII", e["seq"], e["page"], e["fixture"]))
            h.update(pages[e["fixture"]])
    opportunity = workload_opportunity(events, pages, args.logical_pages)
    prefill_hash = sha(b"".join(pages[i % fixture_pages] for i in range(args.logical_pages)))
    post_hash = sha(b"".join(pages[i] for i in latest))
    trace_bytes = "".join(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n"
                          for e in events).encode()
    (out / "trace.jsonl").write_bytes(trace_bytes)
    manifest = {"schema": SCHEMA, "page_bytes": PAGE,
                "logical_pages": args.logical_pages, "writer_pages": args.writer_pages,
                "reader_start": args.reader_start, "reader_pages": args.reader_pages,
                "layout": args.layout, "fixture_sha256": fixture_hash,
                "fixture_pages": fixture_pages, "trace_sha256": sha(trace_bytes),
                "warmup_ops": args.warmup_ops, "measure_ops": args.measure_ops,
                "read_pct": args.read_pct, "qd": args.qd, "iops": args.iops,
                "seed": args.seed, "prefill_sha256": prefill_hash,
                "expected_post_sha256": post_hash,
                "write_payload_stream_sha256": h.hexdigest(),
                "workload_opportunity": opportunity,
                "algorithm": "fixed-seed independent-QD-waves, deterministic complete 4KiB pages"}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"manifest": str(out / "manifest.json"), **manifest}, sort_keys=True))


def check_plan(trace_path, manifest, fixture_pages):
    data = Path(trace_path).read_bytes()
    if sha(data) != manifest["trace_sha256"]:
        raise ValueError("trace bytes differ from canonical plan manifest")
    rows = [json.loads(line) for line in data.splitlines()]
    total = manifest["warmup_ops"] + manifest["measure_ops"]
    if len(rows) != total or total % manifest["qd"]:
        raise ValueError("missing/extra logical operations")
    latest = [i % fixture_pages for i in range(manifest["logical_pages"])]
    for first in range(0, total, manifest["qd"]):
        wave = rows[first:first + manifest["qd"]]
        if len(set(row["page"] for row in wave)) != len(wave):
            raise ValueError("two in-flight operations touch the same logical page")
        for pos, row in enumerate(wave):
            seq = first + pos
            phase = "warmup" if seq < manifest["warmup_ops"] else "measure"
            if row["seq"] != seq or row["wave"] != first // manifest["qd"] or row["phase"] != phase:
                raise ValueError("operation ordering/phase mismatch")
            page, fi = row["page"], row["fixture"]
            if not 0 <= page < len(latest) or not 0 <= fi < fixture_pages:
                raise ValueError("out-of-range page / fixture index")
            if row["op"] == "W":
                if page >= manifest["writer_pages"]:
                    raise ValueError("write escaped allowed logical region")
            elif row["op"] == "R":
                if not manifest["reader_start"] <= page < (
                    manifest["reader_start"] + manifest["reader_pages"]
                ):
                    raise ValueError("read escaped allowed logical region")
                if fi != latest[page]:
                    raise ValueError("read expectation violates latest-generation oracle")
            else:
                raise ValueError("unsupported operation")
        for row in wave:
            if row["op"] == "W":
                latest[row["page"]] = row["fixture"]
    return rows, latest


def resolve_owned_nullblk(name, expected_lower_dev,
                          config_root=Path("/sys/kernel/config/nullb"),
                          block_root=Path("/sys/block"),
                          sysdev_root=Path("/sys/dev/block"),
                          devices_file=Path("/proc/devices")):
    """Bind an exact owned configfs device to its modern/legacy kernel disk.

    A configfs name is NOT necessarily the disk name on older kernels.
    Both present, neither present, or any mismatched identity fail closed.
    """
    if not re.fullmatch(r"nullb-swapz-[a-f0-9]{16}", name):
        raise ValueError("non-owned null_blk configfs name")
    if not re.fullmatch(r"[0-9]+:[0-9]+", expected_lower_dev or ""):
        raise ValueError("invalid pinned lower major:minor")
    config = config_root / name
    if ((config / "memory_backed").read_text().strip() != "1" or
            (config / "power").read_text().strip() != "1"):
        raise ValueError("null_blk must be powered and RAM-backed")
    index_text = (config / "index").read_text().strip()
    if not re.fullmatch(r"(0|[1-9][0-9]*)", index_text):
        raise ValueError("invalid configfs index")
    index = int(index_text)
    driver_major = None
    block_section = False
    for line in devices_file.read_text().splitlines():
        if line.strip() == "Block devices:":
            block_section = True
            continue
        fields = line.split()
        if block_section and len(fields) == 2 and fields[1] == "nullb":
            driver_major = int(fields[0])
            break
    if driver_major is None:
        raise ValueError("registered null_blk driver major unavailable")
    choices = (name, f"nullb{index}")
    disks = [block_root / disk for disk in choices
             if (block_root / disk / "dev").is_file()]
    if len(disks) != 1:
        raise ValueError("owned null_blk disk missing or ambiguous")
    disk = disks[0]
    disk_dev = (disk / "dev").read_text().strip()
    if (disk_dev != expected_lower_dev or
            disk_dev != f"{driver_major}:{index}" or
            (sysdev_root / disk_dev).resolve(strict=True) !=
            disk.resolve(strict=True)):
        raise ValueError("owned null_blk driver/index/sysfs identity mismatch")
    return disk.name, disk_dev


def validate_swapz_table(table, logical_pages, lower_dev, disk_name):
    """Qualify exactly one swapz mapping on the pinned RAM null_blk.

    The target emits the original backing token in STATUSTYPE_TABLE,
    which may be either a major:minor or the exact owned /dev/<disk>.
    Reject unexpected layouts and active diagnostic fault-injection.
    """
    rows = table.strip().splitlines()
    if len(rows) != 1:
        raise ValueError("expected exactly one swapz DM table extent")
    fields = rows[0].split()
    if len(fields) != 12 or fields[:3] != [
        "0", str(logical_pages * PAGE // 512), "swapz"
    ]:
        raise ValueError("unexpected swapz DM table geometry or arguments")
    if fields[3] != lower_dev:
        if fields[3] != f"/dev/{disk_name}":
            raise ValueError("unowned swapz DM table backing path")
        backing = Path(fields[3]).stat()
        if not stat.S_ISBLK(backing.st_mode) or (
            f"{os.major(backing.st_rdev)}:{os.minor(backing.st_rdev)}" != lower_dev
        ):
            raise ValueError("swapz DM table backing block identity changed")
    if any(re.fullmatch(r"[0-9]+", value) is None for value in fields[4:]):
        raise ValueError("non-numeric swapz configuration")
    (read_budget, window, verify, gc_policy, flush_fault,
     lower_bulk, write_fault, retain_ms) = map(int, fields[4:12])
    if not (0 <= read_budget <= 3 and 1 <= window <= 64 and
            0 <= verify <= 1 and 0 <= gc_policy <= 2 and
            0 <= lower_bulk <= 2 and 0 <= retain_ms <= 4):
        raise ValueError("out-of-policy swapz benchmark geometry")
    if flush_fault or write_fault:
        raise ValueError("fault-injected swapz target is not a performance arm")
    return {"read_budget": read_budget, "window": window,
            "verify": verify, "gc_policy": gc_policy,
            "lower_bulk": lower_bulk, "retain_ms": retain_ms}


def check_owned_block(path, st, candidate, args, logical_pages):
    if not args.owned_nullblk_name or not args.expected_dev:
        raise ValueError("block I/O requires owned null_blk identity and exact major:minor")
    disk_name, null_dev = resolve_owned_nullblk(
        args.owned_nullblk_name, args.expected_lower_dev
    )
    actual = f"{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}"
    if actual != args.expected_dev or null_dev != args.expected_lower_dev:
        raise ValueError("major/minor mismatch against independently pinned owned device")
    sysdev = Path("/sys/dev/block") / actual
    actual_name = sysdev.resolve().name
    sectors = int((sysdev / "size").read_text().strip())
    if candidate == "off":
        if sectors * 512 < logical_pages * PAGE:
            raise ValueError("owned null_blk is smaller than logical working range")
        if args.expected_dm_uuid or actual != null_dev or actual_name != disk_name:
            raise ValueError("off control must use the bare exact owned null_blk")
    else:
        if not args.expected_dm_uuid or not re.fullmatch(
            r"SWAPZ-TEST-[a-f0-9]{16}", args.expected_dm_uuid
        ):
            raise ValueError("required trial-specific DM UUID missing")
        if not actual_name.startswith("dm-") or (
            sysdev / "dm/uuid"
        ).read_text().strip() != args.expected_dm_uuid:
            raise ValueError("DM UUID and exact mapped block device differ")
        if {entry.name for entry in (sysdev / "slaves").iterdir()} != {disk_name}:
            raise ValueError("DM target does not depend exclusively on owned null_blk")
        if sectors * 512 != logical_pages * PAGE:
            raise ValueError("DM mapping size differs from exact workload")
        dm_name = (sysdev / "dm/name").read_text().strip()
        table = subprocess.run(["dmsetup", "table", dm_name],
                               check=True, capture_output=True, text=True,
                               timeout=10).stdout
        swapz_config = validate_swapz_table(
            table, logical_pages, null_dev, disk_name
        )
    for line in Path("/proc/swaps").read_text().splitlines()[1:]:
        item = line.split()[0]
        try:
            swap_st = Path(item).stat()
        except (OSError, IndexError):
            continue
        if item == str(path) or (stat.S_ISBLK(swap_st.st_mode) and (
            swap_st.st_rdev in (st.st_rdev, os.makedev(*map(int, null_dev.split(":"))))
        )):
            raise ValueError("refusing an active swap identity")
    protected = {actual, null_dev}
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        fields = line.split()
        if len(fields) > 3 and fields[2] in protected:
            raise ValueError("target or backing block device is mounted")
    return {"device": actual, "owned_nullblk": args.owned_nullblk_name,
            "owned_disk": disk_name, "lower_major_minor": null_dev,
            "dm_uuid": args.expected_dm_uuid if candidate != "off" else None,
            "swapz_config": swapz_config if candidate == "swapz" else None}


def check_device(args, logical_pages):
    path = Path(args.device)
    if path.is_symlink():
        # /dev/mapper entries are symlinks. Resolve first, then validate
        # the actual DM's UUID and exclusive null_blk backing.
        path = path.resolve(strict=True)
    st = path.stat()
    if stat.S_ISBLK(st.st_mode):
        identity = check_owned_block(path, st, args.candidate, args, logical_pages)
        return path, os.O_RDWR | os.O_DIRECT | os.O_CLOEXEC, identity
    if not stat.S_ISREG(st.st_mode) or not args.regular_file_test:
        raise ValueError("only explicitly opted-in rootless test files or owned null_blk")
    root = Path(tempfile.gettempdir()).resolve()
    if not path.resolve().is_relative_to(root) or not path.name.startswith("swapz-replay-"):
        raise ValueError("rootless regular test file must be named swapz-replay-* under tempdir")
    for line in Path("/proc/swaps").read_text().splitlines()[1:]:
        swap_path = line.split()[0]
        try:
            swap_st = Path(swap_path).stat()
        except OSError:
            continue
        if (st.st_ino, st.st_dev) == (swap_st.st_ino, swap_st.st_dev):
            raise ValueError("refusing any active swap file inode")
    if st.st_size != logical_pages * PAGE:
        raise ValueError("test file must already exist and have exact logical size")
    return path, os.O_RDWR | os.O_CLOEXEC, {"test_regular_file": str(path)}


def lower_stat(name):
    if name is None:
        return None
    values = [int(x) for x in (Path("/sys/block") / name / "stat").read_text().split()]
    if len(values) < 16:
        raise ValueError("insufficient device stat fields")
    return values


class LowerInflightSampler:
    """Sample the exact owned lower block device during the timed interval.

    /sys/block/<disk>/inflight exposes current READ and WRITE requests. Sampling
    is observational: the benchmark preserves its I/O policy and reports the
    achieved sample count rather than pretending this is an event trace.
    """

    def __init__(self, disk_name):
        self._path = ((Path("/sys/block") / disk_name / "inflight")
                      if disk_name is not None else None)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = None
        self._error = None
        self._measuring = False
        self._start_ns = 0
        self._last_ns = 0
        self._current = (0, 0)
        self._start = (0, 0)
        self._samples = 0
        self._read_peak = 0
        self._write_peak = 0
        self._total_peak = 0
        self._read_weighted_ns = 0
        self._write_weighted_ns = 0
        self._total_weighted_ns = 0

    @staticmethod
    def _parse(text):
        fields = text.split()
        if len(fields) != 2 or any(
                re.fullmatch(r"(0|[1-9][0-9]*)", field) is None
                for field in fields):
            raise ValueError("invalid lower inflight counters")
        return tuple(map(int, fields))

    @classmethod
    def _read_fd(cls, fd):
        os.lseek(fd, 0, os.SEEK_SET)
        return cls._parse(os.read(fd, 64).decode("ascii"))

    def _read_once(self):
        return self._parse(self._path.read_text(encoding="ascii"))

    def _set_error(self, exc):
        with self._lock:
            if self._error is None:
                self._error = exc

    def _raise_error_locked(self):
        if self._error is not None:
            raise ValueError("lower inflight sampler failed") from self._error

    def _account_locked(self, now_ns):
        elapsed_ns = now_ns - self._last_ns
        if elapsed_ns < 0:
            raise ValueError("lower inflight sample clock moved backwards")
        read_depth, write_depth = self._current
        self._read_weighted_ns += read_depth * elapsed_ns
        self._write_weighted_ns += write_depth * elapsed_ns
        self._total_weighted_ns += (read_depth + write_depth) * elapsed_ns
        self._last_ns = now_ns

    def _observe_locked(self, current):
        self._current = current
        read_depth, write_depth = current
        self._samples += 1
        self._read_peak = max(self._read_peak, read_depth)
        self._write_peak = max(self._write_peak, write_depth)
        self._total_peak = max(self._total_peak, read_depth + write_depth)

    def _run(self):
        fd = None
        try:
            fd = os.open(self._path, os.O_RDONLY | os.O_CLOEXEC)
            self._ready.set()
            interval_s = LOWER_INFLIGHT_SAMPLE_INTERVAL_NS / 1e9
            while not self._stop.wait(interval_s):
                current = self._read_fd(fd)
                now_ns = time.monotonic_ns()
                with self._lock:
                    if self._measuring:
                        self._account_locked(now_ns)
                        self._observe_locked(current)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            self._set_error(exc)
            self._ready.set()
        finally:
            if fd is not None:
                os.close(fd)

    def start(self):
        if self._path is None:
            return
        # Fail before the timed boundary if this kernel lacks the required
        # split lower READ/WRITE inflight telemetry.
        self._read_once()
        self._thread = threading.Thread(
            target=self._run, name="swapz-lower-inflight", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=2):
            self._stop.set()
            self._thread.join(timeout=2)
            raise ValueError("lower inflight sampler did not start")
        with self._lock:
            self._raise_error_locked()

    def begin(self):
        if self._path is None:
            return time.monotonic_ns()
        current = self._read_once()
        with self._lock:
            self._raise_error_locked()
            start_ns = time.monotonic_ns()
            self._start_ns = start_ns
            self._last_ns = start_ns
            self._current = current
            self._start = current
            self._samples = 0
            self._read_peak = 0
            self._write_peak = 0
            self._total_peak = 0
            self._read_weighted_ns = 0
            self._write_weighted_ns = 0
            self._total_weighted_ns = 0
            self._observe_locked(current)
            self._measuring = True
            return start_ns

    def finish(self):
        if self._path is None:
            return time.monotonic_ns(), None
        with self._lock:
            self._raise_error_locked()
            if not self._measuring:
                raise ValueError("lower inflight sampler was not measuring")
            end_ns = time.monotonic_ns()
            self._account_locked(end_ns)
            self._measuring = False
            duration_ns = end_ns - self._start_ns
            if duration_ns <= 0:
                raise ValueError("invalid lower inflight sample interval")
            read_depth, write_depth = self._current
            metrics = {
                "target_interval_ns": LOWER_INFLIGHT_SAMPLE_INTERVAL_NS,
                "samples": self._samples,
                "read_start": self._start[0],
                "write_start": self._start[1],
                "read_end": read_depth,
                "write_end": write_depth,
                "read_peak": self._read_peak,
                "write_peak": self._write_peak,
                "total_peak": self._total_peak,
                "read_time_weighted": self._read_weighted_ns / duration_ns,
                "write_time_weighted": self._write_weighted_ns / duration_ns,
                "total_time_weighted": self._total_weighted_ns / duration_ns,
            }
            return end_ns, metrics

    def close(self):
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=2)
        if self._thread.is_alive():
            raise ValueError("lower inflight sampler did not stop")
        with self._lock:
            self._raise_error_locked()


def iostat_delta(before, after):
    if before is None or after is None:
        return None
    if len(before) != len(after):
        raise ValueError("backing stat shape changed")
    delta = [end - start for start, end in zip(before, after)]
    if any(delta[index] < 0 for index in (0, 2, 4, 6, 15)):
        raise ValueError("backing counter reset during measurement")
    return {"lower_read_requests": delta[0], "lower_read_bytes": delta[2] * 512,
            "lower_write_requests": delta[4], "lower_write_bytes": delta[6] * 512,
            "lower_flush_requests": delta[15]}


def measured_throughput(report, require_lower=False):
    """Completed logical bytes/s against independent backing sectors/s.

    MB is decimal 1,000,000B. Only the replay measurement interval counts:
    exclude prefill, warmup and whole-device final readback. A rootless
    regular-file replay has NO independently evidenced disk bandwidth.
    Never infer saturation or extrapolate a maximum input MB/s here.
    """
    seconds = report.get("seconds")
    if (not isinstance(seconds, (int, float)) or isinstance(seconds, bool)
            or not math.isfinite(seconds) or seconds <= 0):
        raise ValueError("INVALID THROUGHPUT: nonpositive/nonfinite elapsed time")
    counts = [report.get(key) for key in ("write_ops", "read_ops", "measure_ops")]
    if any(type(n) is not int or n < 0 for n in counts) or sum(counts[:2]) != counts[2]:
        raise ValueError("INVALID THROUGHPUT: measured logical operations mismatch")
    logical_write = counts[0] * PAGE
    logical_read = counts[1] * PAGE
    result = {
        "unit": "decimal_MB_per_second", "seconds": seconds,
        "logical_write_bytes": logical_write, "logical_read_bytes": logical_read,
        "logical_write_mbps": logical_write / seconds / 1_000_000,
        "logical_read_mbps": logical_read / seconds / 1_000_000,
        "logical_total_mbps": (logical_write + logical_read) / seconds / 1_000_000,
        "lower_write_mbps": None, "lower_read_mbps": None,
        "lower_total_mbps": None, "write_input_per_lower_byte": None,
        "lower_read_per_logical_read_byte": None,
    }
    lower = report.get("lower_io")
    if lower is None:
        if require_lower:
            raise ValueError("INVALID THROUGHPUT: missing independent lower I/O")
        return result
    for key in ("lower_write_bytes", "lower_read_bytes"):
        if type(lower.get(key)) is not int or lower[key] < 0 or lower[key] % 512:
            raise ValueError("INVALID THROUGHPUT: invalid lower sector bytes")
    lower_write = lower["lower_write_bytes"]
    lower_read = lower["lower_read_bytes"]
    result.update({
        "lower_write_mbps": lower_write / seconds / 1_000_000,
        "lower_read_mbps": lower_read / seconds / 1_000_000,
        "lower_total_mbps": (lower_write + lower_read) / seconds / 1_000_000,
        "write_input_per_lower_byte": (
            logical_write / lower_write if lower_write else None
        ),
        "lower_read_per_logical_read_byte": (
            lower_read / logical_read if logical_read else None
        ),
    })
    return result


def full_write(fd, page, buf):
    n = os.pwritev(fd, [buf], page * PAGE)
    if n != PAGE:
        raise OSError("short lower write")


def full_read(fd, page, buf, expected):
    n = os.preadv(fd, [buf], page * PAGE)
    if n != PAGE or buf != expected:
        raise OSError("short or mismatched logical page read")


def process_cpu():
    """Replay process+threads CPU, excluding dm kernel worker threads."""
    ru = resource.getrusage(resource.RUSAGE_SELF)
    return (ru.ru_utime, ru.ru_stime, ru.ru_maxrss)


def packed_closes(path, identity):
    if not identity.get("dm_uuid"):
        return None
    out = subprocess.run(["dmsetup", "status", str(path)], text=True,
                         capture_output=True, check=False, timeout=8)
    if out.returncode:
        raise ValueError("owned mapper status unavailable for packed read")
    match = re.search(r"(?:^|\s)close_pack_ready=(\d+)(?:\s|$)", out.stdout)
    if not match:
        raise ValueError("owned mapper lacks packed close counter")
    return int(match.group(1))

# C READ callback diagnostics: capture outside the READ stopwatch.
KERNEL_READ_FIELDS = ("read_meta_reqs", "read_payload_reqs",
                      "read_payload_blocks", "lower_read_wall_ns",
                      "decode_wall_ns", "read_copy_wall_ns",
                      "read_copy_bytes", "read_engine_nonio_wall_ns",
                      "read_meta_cache_hits", "read_meta_lru_hits",
                      "read_full_extent_reqs", "read_full_cache_hits",
                      "read_two_block_skips", "parallel_read_pairs",
                      "parallel_read_same_extent_pairs",
                      "parallel_read_distinct_extent_pairs",
                      "parallel_read_adjacent_extent_pairs",
                      "parallel_read_adjacent_extent_blocks",
                      "parallel_read_coalesced_pairs",
                      "parallel_read_coalesced_reqs_saved",
                      "parallel_read_coalesced_blocks",
                      "parallel_read_coalesce_extra_blocks",
                      "parallel_read_coalesce_skip_cached",
                      "parallel_read_coalesce_skip_noncontig_slot",
                      "parallel_read_coalesce_skip_gap",
                      "parallel_read_coalesce_skip_other",
                      "read_worker_cpu_ns")


def kernel_read_snapshot(path, identity):
    if not identity.get("dm_uuid"):
        return None
    status = subprocess.run(["dmsetup", "status", str(path)], text=True,
                            capture_output=True, check=False, timeout=8)
    if status.returncode:
        raise ValueError("owned swapz read telemetry unavailable")
    counters = {}
    for field in KERNEL_READ_FIELDS:
        match = re.search(r"(?:^|\s)" + field + r"=(\d+)(?:\s|$)",
                          status.stdout)
        if not match:
            raise ValueError("owned swapz read telemetry missing " + field)
        counters[field] = int(match.group(1))
    return counters


def kernel_read_delta(before, after):
    if before is None and after is None:
        return None
    if before is None or after is None:
        raise ValueError("incomplete swapz read telemetry")
    counters = {field: after[field] - before[field]
                for field in KERNEL_READ_FIELDS}
    if any(value < 0 for value in counters.values()):
        raise ValueError("swapz read telemetry reset during measurement")
    # Cache reuse can legitimately reduce metadata requests below payload
    # requests. Only counted payload block quantities must remain consistent.
    if (counters["read_payload_blocks"] < counters["read_payload_reqs"] or
            counters["read_full_extent_reqs"] +
            counters["read_two_block_skips"] > counters["read_meta_reqs"] or
            counters["read_full_cache_hits"] > counters["read_meta_cache_hits"]):
        raise ValueError("inconsistent swapz read request accounting")
    if (counters["parallel_read_same_extent_pairs"] > counters["parallel_read_pairs"] or
            counters["parallel_read_distinct_extent_pairs"] >
            counters["parallel_read_pairs"] or
            counters["parallel_read_adjacent_extent_pairs"] >
            counters["parallel_read_distinct_extent_pairs"] or
            counters["parallel_read_adjacent_extent_blocks"] <
            2 * counters["parallel_read_adjacent_extent_pairs"] or
            counters["parallel_read_adjacent_extent_blocks"] >
            8 * counters["parallel_read_adjacent_extent_pairs"] or
            counters["parallel_read_coalesced_pairs"] >
            counters["parallel_read_adjacent_extent_pairs"] or
            counters["parallel_read_coalesced_reqs_saved"] !=
            counters["parallel_read_coalesced_pairs"] or
            counters["parallel_read_coalesced_blocks"] <
            2 * counters["parallel_read_coalesced_pairs"] or
            counters["parallel_read_coalesced_blocks"] >
            8 * counters["parallel_read_coalesced_pairs"] or
            counters["parallel_read_coalesce_extra_blocks"] != 0):
        raise ValueError("inconsistent swapz parallel read accounting")
    return counters


# Timed workload diagnosis; dmsetup is sampled immediately around measure.
# Monotonic counters are differenced. retained_burst_target is an end-of-
# interval policy gauge and is never subtracted.
CLOSE_REASON_FIELDS = (
    "close_unknown", "close_full", "close_duplicate", "close_zero",
    "close_fua", "close_raw", "close_read_conflict", "close_read_unrelated",
    "close_discard", "close_preflush", "close_quantum", "close_idle",
    "close_shutdown", "close_other", "close_deadline", "close_pack_ready")
ONE_PAGE_CLOSE_FIELDS = (
    "win1_unknown", "win1_full", "win1_duplicate", "win1_zero",
    "win1_fua", "win1_raw", "win1_read_conflict", "win1_read_unrelated",
    "win1_discard", "win1_preflush", "win1_quantum", "win1_idle",
    "win1_shutdown", "win1_other", "win1_deadline", "win1_pack_ready")
WIN1_PACK_CAUSE_FIELDS = (
    "win1_pack_tail_target", "win1_pack_read_bypass",
    "win1_pack_wave_interrupted")
SINGLE_TAIL_FIELDS = (
    "single_tail_deferrals", "single_tail_companions",
    "win1_deadline_deferred_tail", "win1_idle_deferred_tail",
    "single_tail_other_clears")
SINGLE_TAIL_TIMING_FIELDS = (
    "single_tail_comp_age_le250us", "single_tail_comp_age_251_500us",
    "single_tail_comp_age_501_1000us", "single_tail_comp_age_gt1000us",
    "single_tail_deadline_age_le250us", "single_tail_deadline_age_251_500us",
    "single_tail_deadline_age_501_1000us", "single_tail_deadline_age_gt1000us")
SINGLE_TAIL_COMP_UPPER_FIELDS = (
    "single_tail_comp_age_1001_1250us",
    "single_tail_comp_age_1251_1500us",
    "single_tail_comp_age_1501_1750us",
    "single_tail_comp_age_gt1750us")
SINGLE_TAIL_SERVICE_FIELDS = (
    "single_tail_comp_after_lower_done", "single_tail_comp_after_read_bypass",
    "single_tail_comp_after_both", "single_tail_deadline_after_lower_done",
    "single_tail_deadline_after_read_bypass", "single_tail_deadline_after_both")
ID52_FIELDS = (
    SINGLE_TAIL_TIMING_FIELDS + SINGLE_TAIL_COMP_UPPER_FIELDS +
    SINGLE_TAIL_SERVICE_FIELDS)
PACK_CLOSE_FIELDS = (
    "pack_close_tail_target", "pack_close_tail_target_le4",
    "pack_close_burst_target", "pack_close_service_dry")
BURST_CLOSE_DETAIL_FIELDS = (
    "pack_close_burst_admission", "pack_close_burst_worker",
    "pack_close_burst_target_le4", "pack_close_burst_target_5_8",
    "pack_close_burst_target_9_16", "pack_close_burst_target_17_64",
    "pack_close_burst_count_le4", "pack_close_burst_count_5_8",
    "pack_close_burst_count_9_16", "pack_close_burst_count_17_64",
    "pack_close_burst_overshoot")
TAIL_SAMPLE_FIELDS = (
    "pack_tail_samples", "pack_tail_zero_inflight", "pack_tail_zero_idle",
    "pack_tail_one_inflight", "pack_tail_one_idle",
    "pack_tail_many_inflight", "pack_tail_many_idle",
    "burst_target_grows", "burst_target_shrinks",
    "burst_shrink_after_inflight_zero", "burst_shrink_after_read_bypass",
    "burst_shrink_other", "burst_shrink_target_le8",
    "burst_shrink_target_9_32", "burst_shrink_target_gt32")
K1_READY_WAIT_FIELDS = (
    "k1_ready_wait_windows", "k1_ready_wait_records",
    "k1_ready_wait_wall_ns", "k1_ready_wait_max_records",
    "k1_ready_wait_pack_ready", "k1_ready_wait_full",
    "k1_ready_wait_deadline", "k1_ready_wait_fence",
    "k1_ready_wait_other")
PACK_CLOSE_PRIMARY_FIELDS = (
    "pack_close_tail_target", "pack_close_burst_target",
    "pack_close_service_dry")
DEADLINE_CONTEXT_FIELDS = (
    "deadline_before_bio", "deadline_after_read",
    "deadline_worker_with_local", "deadline_worker_empty")
PREPARATION_FIELDS = (
    "prep_lower_write_overlap_starts", "prep_wave_kicks",
    "prep_producer_head_claims", "prep_producer_tail_claims",
    "prep_ordered_inline", "prep_ordered_handoffs", "prep_ordered_waits")
WINDOW_INTERVAL_FIELDS = (
    "windows", "one_page_windows", "win1", "win2", "win3_4", "win5_8",
    "win9_16", "win17_64", "packed_early_commits",
    "single_pack_deferrals", "accepted_burst_extensions",
    "accepted_burst_tail_flushes", "accepted_burst_read_caps", "gc_victims"
) + CLOSE_REASON_FIELDS + ONE_PAGE_CLOSE_FIELDS + WIN1_PACK_CAUSE_FIELDS + SINGLE_TAIL_FIELDS + ID52_FIELDS + PACK_CLOSE_FIELDS + BURST_CLOSE_DETAIL_FIELDS + TAIL_SAMPLE_FIELDS + K1_READY_WAIT_FIELDS + DEADLINE_CONTEXT_FIELDS
KERNEL_WRITE_COUNTER_FIELDS = (
    "physical_write_reqs", "lz4_wall_ns",
    "ordered_lz4_wall_ns", "prep_lz4_wall_ns",
    "write_copy_wall_ns", "write_copy_bytes",
    "ordered_write_copy_wall_ns", "prep_write_copy_wall_ns",
    "direct_lz4_input_pages",
    "window_sort_wall_ns", "window_commit_wall_ns",
    "window_commit_nonio_wall_ns", "engine_plan_wall_ns",
    "engine_pack_wall_ns", "engine_publish_wall_ns",
    "engine_publish_crc_wall_ns", "engine_publish_auth_wall_ns",
    "engine_prehashed_records", "batch_snapshot_crc_wall_ns",
    "batch_pause_crc_wall_ns", "batch_resume_crc_wall_ns",
    "prep_crc_wall_ns", "ordered_crc_wall_ns", "lower_write_wall_ns",
    "ordered_worker_wall_ns", "prep_worker_wall_ns",
    "ordered_worker_cpu_ns", "prep_worker_cpu_ns", "read_worker_cpu_ns",
    "prep_wait_wall_ns",
    "prep_lower_write_overlap_ns", "prep_lower_write_samples",
    "prep_lower_write_start_queued", "prep_lower_write_start_nonempty",
    "prep_lower_write_end_queued", "prep_lower_write_end_nonempty",
    "pipeline_async_runs", "pipeline_active_wall_ns",
    "pipeline_finalize_wait_wall_ns",
    "write_wait_le1ms", "write_wait_1to4ms", "write_wait_gt4ms"
) + WINDOW_INTERVAL_FIELDS + PREPARATION_FIELDS
KERNEL_WRITE_GAUGE_FIELDS = ("retained_burst_target",)
KERNEL_WRITE_FIELDS = KERNEL_WRITE_COUNTER_FIELDS + KERNEL_WRITE_GAUGE_FIELDS
WRITE_WAIT_BINS = ("write_wait_le1ms", "write_wait_1to4ms",
                   "write_wait_gt4ms")


def kernel_write_snapshot(path, identity):
    if not identity.get("dm_uuid"):
        return None
    status = subprocess.run(["dmsetup", "status", str(path)], text=True,
                            capture_output=True, check=False, timeout=8)
    if status.returncode:
        raise ValueError("owned swapz write telemetry unavailable")
    counters = {}
    for field in KERNEL_WRITE_FIELDS:
        match = re.search(r"(?:^|\s)" + field + r"=(\d+)(?:\s|$)",
                          status.stdout)
        if not match:
            raise ValueError("owned swapz write telemetry missing " + field)
        counters[field] = int(match.group(1))
    return counters


def kernel_write_delta(before, after):
    if before is None and after is None:
        return None
    if before is None or after is None:
        raise ValueError("incomplete swapz write telemetry")
    counters = {key: after[key] - before[key]
                for key in KERNEL_WRITE_COUNTER_FIELDS}
    if any(value < 0 for value in counters.values()):
        raise ValueError("swapz write telemetry reset during measurement")
    for key in KERNEL_WRITE_GAUGE_FIELDS:
        counters[key] = after[key]
    if not 1 <= counters["retained_burst_target"] <= 64:
        raise ValueError("invalid swapz retained burst target")
    if sum(counters[key] for key in WRITE_WAIT_BINS) != counters["physical_write_reqs"]:
        raise ValueError("inconsistent swapz lower write wait histogram")
    if counters["window_commit_nonio_wall_ns"] > counters["window_commit_wall_ns"]:
        raise ValueError("inconsistent swapz non-I/O commit timing")
    measured_engine = sum(counters[key] for key in
                          ("engine_plan_wall_ns", "engine_pack_wall_ns",
                           "engine_publish_wall_ns"))
    if measured_engine > counters["window_commit_nonio_wall_ns"]:
        raise ValueError("inconsistent swapz engine phase timing")
    if (counters["engine_publish_crc_wall_ns"] +
            counters["engine_publish_auth_wall_ns"] !=
            counters["engine_publish_wall_ns"]):
        raise ValueError("inconsistent swapz publish attribution")
    if sum(counters[field] for field in CLOSE_REASON_FIELDS) != counters["windows"]:
        raise ValueError("inconsistent swapz timed close-reason accounting")
    if sum(counters[field] for field in ONE_PAGE_CLOSE_FIELDS) != counters["one_page_windows"]:
        raise ValueError("inconsistent swapz timed one-page accounting")
    if sum(counters[field] for field in WIN1_PACK_CAUSE_FIELDS) != counters["win1_pack_ready"]:
        raise ValueError("inconsistent swapz timed one-page PACK_READY attribution")
    if (counters["single_tail_deferrals"] !=
            counters["single_tail_companions"] +
            counters["win1_deadline_deferred_tail"] +
            counters["win1_idle_deferred_tail"] +
            counters["single_tail_other_clears"] or
            counters["win1_deadline_deferred_tail"] > counters["win1_deadline"] or
            counters["win1_idle_deferred_tail"] > counters["win1_idle"]):
        raise ValueError("inconsistent swapz deferred singleton accounting")
    if sum(counters[field] for field in SINGLE_TAIL_TIMING_FIELDS[:4]) != counters["single_tail_companions"]:
        raise ValueError("inconsistent swapz deferred companion age accounting")
    if sum(counters[field] for field in SINGLE_TAIL_TIMING_FIELDS[4:]) != counters["win1_deadline_deferred_tail"]:
        raise ValueError("inconsistent swapz deferred deadline age accounting")
    if (sum(counters[field] for field in SINGLE_TAIL_COMP_UPPER_FIELDS) !=
            counters["single_tail_comp_age_gt1000us"]):
        raise ValueError("inconsistent swapz deferred companion upper-tail accounting")
    if (sum(counters[field] for field in PACK_CLOSE_PRIMARY_FIELDS) !=
            counters["close_pack_ready"] or
            counters["pack_close_tail_target_le4"] >
            counters["pack_close_tail_target"]):
        raise ValueError("inconsistent swapz PACK_READY close attribution")
    burst = counters["pack_close_burst_target"]
    if (counters["pack_close_burst_admission"] +
            counters["pack_close_burst_worker"] != burst or
            sum(counters[field] for field in (
                "pack_close_burst_target_le4", "pack_close_burst_target_5_8",
                "pack_close_burst_target_9_16",
                "pack_close_burst_target_17_64")) != burst or
            sum(counters[field] for field in (
                "pack_close_burst_count_le4", "pack_close_burst_count_5_8",
                "pack_close_burst_count_9_16",
                "pack_close_burst_count_17_64")) != burst or
            counters["pack_close_burst_overshoot"] > burst):
        raise ValueError("inconsistent swapz burst-target close attribution")
    if (sum(counters[field] for field in (
                "pack_tail_zero_inflight", "pack_tail_zero_idle",
                "pack_tail_one_inflight", "pack_tail_one_idle",
                "pack_tail_many_inflight", "pack_tail_many_idle")) !=
            counters["pack_tail_samples"]):
        raise ValueError("inconsistent swapz post-pack tail-sample attribution")
    if (sum(counters[field] for field in (
                "burst_shrink_after_inflight_zero",
                "burst_shrink_after_read_bypass",
                "burst_shrink_other")) != counters["burst_target_shrinks"] or
            sum(counters[field] for field in (
                "burst_shrink_target_le8",
                "burst_shrink_target_9_32",
                "burst_shrink_target_gt32")) != counters["burst_target_shrinks"]):
        raise ValueError("inconsistent swapz burst-shrink attribution")
    k1_reasons = sum(counters[field] for field in (
        "k1_ready_wait_pack_ready", "k1_ready_wait_full",
        "k1_ready_wait_deadline", "k1_ready_wait_fence",
        "k1_ready_wait_other"))
    if (k1_reasons != counters["k1_ready_wait_windows"] or
            counters["k1_ready_wait_records"] < counters["k1_ready_wait_windows"] or
            counters["k1_ready_wait_max_records"] > 64 or
            (counters["k1_ready_wait_windows"] == 0 and
             counters["k1_ready_wait_max_records"] != 0) or
            counters["k1_ready_wait_wall_ns"] >
            counters["pipeline_finalize_wait_wall_ns"]):
        raise ValueError("inconsistent swapz K=1 ready-wait attribution")
    for total, lower, read, both in (
            ("single_tail_companions", "single_tail_comp_after_lower_done",
             "single_tail_comp_after_read_bypass", "single_tail_comp_after_both"),
            ("win1_deadline_deferred_tail", "single_tail_deadline_after_lower_done",
             "single_tail_deadline_after_read_bypass", "single_tail_deadline_after_both")):
        if (counters[lower] > counters[total] or counters[read] > counters[total] or
                counters[both] > counters[lower] or counters[both] > counters[read]):
            raise ValueError("inconsistent swapz deferred singleton service attribution")
    if (counters["batch_pause_crc_wall_ns"] +
            counters["batch_resume_crc_wall_ns"] !=
            counters["batch_snapshot_crc_wall_ns"]):
        raise ValueError("inconsistent swapz batch snapshot CRC attribution")
    if sum(counters[field] for field in DEADLINE_CONTEXT_FIELDS) != counters["close_deadline"]:
        raise ValueError("inconsistent swapz timed deadline accounting")
    if (counters["accepted_burst_tail_flushes"] >
            counters["accepted_burst_extensions"] or
            counters["accepted_burst_read_caps"] >
            counters["accepted_burst_extensions"]):
        raise ValueError("inconsistent swapz timed burst accounting")
    samples = counters["prep_lower_write_samples"]
    if (counters["prep_lower_write_start_nonempty"] > samples or
            counters["prep_lower_write_end_nonempty"] > samples or
            counters["prep_lower_write_start_queued"] <
            counters["prep_lower_write_start_nonempty"] or
            counters["prep_lower_write_end_queued"] <
            counters["prep_lower_write_end_nonempty"]):
        raise ValueError("inconsistent swapz lower-write queue attribution")
    return counters

def measure_packed_swapin(fd, path, identity, chunks, logical_pages, qd):
    """Verify real 4MiB sequential/random reads after concurrent packed writes."""
    if logical_pages != 1024 or qd != 32:
        raise ValueError("packed read requires 4MiB logical and QD32")
    before = packed_closes(path, identity)
    with concurrent.futures.ThreadPoolExecutor(max_workers=qd) as pool:
        for base in range(0, logical_pages, qd):
            jobs = [pool.submit(full_write, fd, page,
                                chunks[page % len(chunks)])
                    for page in range(base, base + qd)]
            for job in jobs:
                job.result()
    os.fsync(fd)
    after = packed_closes(path, identity)
    packed_delta = after - before if before is not None else None
    if packed_delta is not None and packed_delta <= 0:
        raise ValueError("no packed close during concurrent read-set population")

    image_sha = sha(b"".join(chunks[i % len(chunks)]
                            for i in range(logical_pages)))
    orders = {"sequential": list(range(logical_pages)),
              "seeded_random": random.Random(0x51A0A9).sample(
                  range(logical_pages), logical_pages)}
    # Allocate buffers and start worker threads BEFORE any timed read.
    # A previous benchmark included fresh mmap, worker startup and worker
    # pool destruction in its read latency/throughput measurements.
    buffers = [mmap.mmap(-1, PAGE) for _ in range(qd)]
    views = [memoryview(buf) for buf in buffers]
    measured = {}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=qd) as pool:
            # Complete one no-I/O task per worker before first stopwatch.
            # Use a barrier so 32 concurrent kernel-request workers exist
            # before either arm's first measured read is submitted.
            barrier = threading.Barrier(qd + 1)
            jobs = [pool.submit(barrier.wait) for _ in range(qd)]
            barrier.wait(timeout=10)
            for job in jobs:
                job.result(timeout=10)

            def read_one(page, slot):
                start_ns = time.monotonic_ns()
                count = os.preadv(fd, [views[slot]], page * PAGE)
                elapsed_ns = time.monotonic_ns() - start_ns
                # Correctness checking occurs AFTER the individual I/O
                # latency sample, before buffers can be recycled.
                if count != PAGE or views[slot] != chunks[page % len(chunks)]:
                    raise OSError("short or mismatched packed swap-in page")
                return elapsed_ns

            for mode, pages in orders.items():
                kernel_before = kernel_read_snapshot(path, identity)
                lower_before = lower_stat(identity.get("owned_disk"))
                cpu_before = process_cpu()
                start_ns = time.monotonic_ns()
                durations = []
                for base in range(0, logical_pages, qd):
                    wave = pages[base:base + qd]
                    jobs = [pool.submit(read_one, page, slot)
                            for slot, page in enumerate(wave)]
                    durations.extend(job.result() for job in jobs)
                # Stop before teardown, CPU sampling, lower stat capture
                # and the digest/report calculation.
                duration = (time.monotonic_ns() - start_ns) / 1e9
                cpu_after = process_cpu()
                lower_after = lower_stat(identity.get("owned_disk"))
                kernel_after = kernel_read_snapshot(path, identity)
                if duration <= 0 or len(durations) != logical_pages:
                    raise ValueError("invalid fixed-volume read accounting")
                durations.sort()
                measured[mode] = {
                    "logical_bytes": logical_pages * PAGE,
                    "verified_pages": len(durations),
                    "verified_image_sha256": image_sha,
                    "seconds": duration,
                    "useful_read_mbps": logical_pages * PAGE / duration / 1e6,
                    "read_p99_ms": durations[int((len(durations) - 1) * .99)] / 1e6,
                    "lower_io": iostat_delta(lower_before, lower_after),
                    "kernel_read_path": kernel_read_delta(kernel_before, kernel_after),
                    "replay_cpu_user_s": max(0., cpu_after[0] - cpu_before[0]),
                    "replay_cpu_system_s": max(0., cpu_after[1] - cpu_before[1]),
                    "replay_peak_rss_kb": cpu_after[2],
                    "timed_scope": "QD32 read submission and completion; buffers and worker setup excluded",
                }
    finally:
        for view in views:
            view.release()
        for buffer in buffers:
            buffer.close()
    return {
        "qualification": ("OWNED_PACK_READY_AND_VERIFIED_4MIB_READ"
                          if packed_delta is not None else
                          "ROOTLESS_NO_PACK_PROOF"),
        "logical_bytes": logical_pages * PAGE, "logical_pages": logical_pages,
        "logical_image_sha256": image_sha, "packed_close_delta": packed_delta,
        "first_pass_is_cold": False, "passes": measured,
    }


def replay(args):
    mf = safe_load(args.manifest)
    if mf.get("schema") != SCHEMA or mf.get("page_bytes") != PAGE:
        raise ValueError("unsupported trace schema")
    count, fixture_hash = fixture_info(args.fixture)
    if fixture_hash != mf["fixture_sha256"] or count != mf["fixture_pages"]:
        raise ValueError("fixture differs from exact shared workload manifest")
    trace, final_map = check_plan(args.trace, mf, count)
    if mf["qd"] > 32:
        raise ValueError("unsupported QD")
    path, flags, identity = check_device(args, mf["logical_pages"])
    if path.samefile(args.fixture) or path.samefile(args.trace):
        raise ValueError("the benchmark target must not be its source fixture or trace")
    manifest_sha = digest_file(args.manifest)
    # Verify canonical payload hash, including logical write offsets and
    # the actual four-thousand-ninety-six source bytes for each write.
    with open(args.fixture, "rb") as source:
        mm = mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ)
        mem = memoryview(mm)
        chunks = [mem[i * PAGE:(i + 1) * PAGE] for i in range(count)]
        h = hashlib.sha256()
        for item in trace:
            if item["op"] == "W":
                h.update(struct.pack("<QII", item["seq"], item["page"], item["fixture"]))
                h.update(chunks[item["fixture"]])
        if h.hexdigest() != mf["write_payload_stream_sha256"]:
            raise ValueError("write bytes differ from manifest's canonical stream")
        print(f"BENCH_IO_PHASE={args.candidate}:prefill", file=sys.stderr, flush=True)
        fd = os.open(path, flags)
        try:
            # Trust the opened descriptor, not just the preflight pathname.
            # A replaced device node or symlink cannot redirect benchmark I/O.
            opened = os.fstat(fd)
            if "device" in identity:
                device_number = f"{os.major(opened.st_rdev)}:{os.minor(opened.st_rdev)}"
                if not stat.S_ISBLK(opened.st_mode) or device_number != identity["device"]:
                    raise ValueError("opened block device differs from preflight")
            else:
                current = path.stat()
                if not stat.S_ISREG(opened.st_mode) or (
                    opened.st_dev, opened.st_ino
                ) != (current.st_dev, current.st_ino):
                    raise ValueError("opened rootless fixture differs from preflight")
            bufmap = mmap.mmap(-1, PAGE)
            scratch = memoryview(bufmap)
            try:
                for page in range(mf["logical_pages"]):
                    full_write(fd, page, chunks[page % count])
                os.fsync(fd)
                for page in range(mf["logical_pages"]):
                    full_read(fd, page, scratch, chunks[page % count])
                prefill_digest = hashlib.sha256()
                for page in range(mf["logical_pages"]):
                    prefill_digest.update(chunks[page % count])
                if prefill_digest.hexdigest() != mf["prefill_sha256"]:
                    raise ValueError("prefill image digest mismatches shared trace")
            finally:
                scratch.release()
                bufmap.close()

            print(f"BENCH_IO_PHASE={args.candidate}:mixed", file=sys.stderr, flush=True)
            # Allocate reusable QD-slot read buffers before warmup and
            # measurement. The old hot path did mmap/free for EVERY read.
            # The throughput clock covers exactly the measured I/O waves,
            # including their required final device flush.
            # Pre-split the immutable trace before any benchmark clock;
            # list slicing is workload preparation, not target I/O.
            replay_waves = [trace[i:i + mf["qd"]]
                            for i in range(0, len(trace), mf["qd"])]
            mixed_buffers = [mmap.mmap(-1, PAGE) for _ in range(mf["qd"])]
            mixed_views = [memoryview(buf) for buf in mixed_buffers]
            samples = {"W": [], "R": []}
            measured_start_ns = None
            measured_end_ns = None
            cpu_before = None
            cpu_after = None
            before = None
            after = None
            kernel_write_before = None
            kernel_write_after = None
            lower_inflight = None
            lower_inflight_sampler = LowerInflightSampler(
                identity.get("owned_disk"))
            try:
                def execute(item, slot):
                    start = time.monotonic_ns()
                    if item["op"] == "W":
                        count = os.pwritev(fd, [chunks[item["fixture"]]],
                                           item["page"] * PAGE)
                    else:
                        count = os.preadv(fd, [mixed_views[slot]],
                                          item["page"] * PAGE)
                    elapsed = time.monotonic_ns() - start
                    # Never include Python byte-oracle checking in the
                    # individual I/O latency measurement. Still fail the
                    # operation BEFORE the wave and buffer slot can advance.
                    if count != PAGE or (item["op"] == "R" and
                            mixed_views[slot] != chunks[item["fixture"]]):
                        raise OSError("short or mismatched timed logical I/O")
                    return elapsed

                with concurrent.futures.ThreadPoolExecutor(max_workers=mf["qd"]) as pool:
                    barrier = threading.Barrier(mf["qd"] + 1)
                    jobs = [pool.submit(barrier.wait) for _ in range(mf["qd"])]
                    barrier.wait(timeout=10)
                    for job in jobs:
                        job.result(timeout=10)
                    for wave in replay_waves:
                        if wave[0]["phase"] == "measure" and measured_start_ns is None:
                            lower_inflight_sampler.start()
                            before = lower_stat(identity.get("owned_disk"))
                            kernel_write_before = kernel_write_snapshot(path, identity)
                            cpu_before = process_cpu()
                            measured_start_ns = lower_inflight_sampler.begin()
                        if mf["iops"] and wave[0]["phase"] == "measure":
                            due = (measured_start_ns +
                                   (wave[0]["seq"] - mf["warmup_ops"]) *
                                   1000000000 // mf["iops"])
                            remain = due - time.monotonic_ns()
                            if remain > 0:
                                time.sleep(remain / 1e9)
                        futures = [pool.submit(execute, item, slot)
                                   for slot, item in enumerate(wave)]
                        for item, future in zip(wave, futures):
                            elapsed = future.result()  # fail closed on mismatch
                            if item["phase"] == "measure":
                                samples[item["op"]].append(elapsed)
                    # Acknowledged write completion requires final drain.
                    # Buffer and executor teardown are not part of the clock.
                    os.fsync(fd)
                    measured_end_ns, lower_inflight = lower_inflight_sampler.finish()
                    cpu_after = process_cpu()
                    after = lower_stat(identity.get("owned_disk"))
                    kernel_write_after = kernel_write_snapshot(path, identity)
            finally:
                lower_inflight_sampler.close()
                for view in mixed_views:
                    view.release()
                for buffer in mixed_buffers:
                    buffer.close()
            post_hash = hashlib.sha256()
            buffer = mmap.mmap(-1, PAGE)
            scratch = memoryview(buffer)
            try:
                for page, fi in enumerate(final_map):
                    full_read(fd, page, scratch, chunks[fi])
                    post_hash.update(scratch)
            finally:
                scratch.release()
                buffer.close()
            if post_hash.hexdigest() != mf["expected_post_sha256"]:
                raise ValueError("final image SHA differs from trace oracle")
            if args.packed_read:
                print(f"BENCH_IO_PHASE={args.candidate}:packed_read",
                      file=sys.stderr, flush=True)
            packed_read = (measure_packed_swapin(
                fd, path, identity, chunks, mf["logical_pages"], mf["qd"])
                if args.packed_read else None)
        finally:
            os.close(fd)
        for chunk in chunks:
            chunk.release()
        mem.release()
        mm.close()
    if measured_start_ns is None:
        raise ValueError("no measured waves were replayed")
    seconds = (measured_end_ns - measured_start_ns) / 1e9
    def percentile(values, fraction):
        if not values:
            return None
        vals = sorted(values)
        return vals[min(len(vals) - 1, int((len(vals) - 1) * fraction))]
    report = {
        "candidate": args.candidate, "source_sha": args.source_sha,
        "device_identity": identity, "fixture_sha256": fixture_hash,
        "trace_sha256": mf["trace_sha256"], "manifest_sha256": manifest_sha,
        "write_payload_stream_sha256": mf["write_payload_stream_sha256"],
        "workload_opportunity": mf["workload_opportunity"],
        "prefill_sha256": mf["prefill_sha256"],
        "expected_post_sha256": mf["expected_post_sha256"],
        "verified_post_sha256": post_hash.hexdigest(),
        "qd": mf["qd"], "layout": mf["layout"], "seed": mf["seed"],
        "iops_requested": mf["iops"], "warmup_ops": mf["warmup_ops"],
        "measure_ops": mf["measure_ops"], "write_ops": len(samples["W"]),
        "read_ops": len(samples["R"]), "verified_pages": mf["logical_pages"],
        "seconds": seconds, "achieved_iops": mf["measure_ops"] / seconds,
        "mixed_replay_cpu_user_s": max(0., cpu_after[0] - cpu_before[0]),
        "mixed_replay_cpu_system_s": max(0., cpu_after[1] - cpu_before[1]),
        "mixed_replay_peak_rss_kb": cpu_after[2],
        "cpu_scope": "replay process+threads only; kernel DM workers excluded",
        "mixed_timed_scope": ("measured logical QD waves and required final fsync; "
                              "excludes prefill, fixture/trace setup, warmup, "
                              "buffer allocations, executor startup and post-run oracle"),
        "packed_read": packed_read,
        "kernel_write_path": kernel_write_delta(kernel_write_before, kernel_write_after),
        "lower_inflight": lower_inflight,
        "lower_io": iostat_delta(before, after), "verdict": "PASS",
        "read_p50_ns": percentile(samples["R"], .50),
        "read_p95_ns": percentile(samples["R"], .95),
        "read_p99_ns": percentile(samples["R"], .99),
        "write_p50_ns": percentile(samples["W"], .50),
        "write_p95_ns": percentile(samples["W"], .95),
        "write_p99_ns": percentile(samples["W"], .99),
    }
    report["throughput_mbps"] = measured_throughput(
        report, require_lower=bool(identity.get("owned_disk"))
    )
    result_path = Path(args.result)
    if result_path.exists():
        raise ValueError("refusing to overwrite a prior trial result")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


def compare(args):
    entries = [safe_load(name) for name in args.reports]
    if set(x["candidate"] for x in entries) != set(CANDIDATES) or len(entries) != 2:
        raise ValueError("exactly one off and one swapz result required")
    immutable = ("fixture_sha256", "trace_sha256", "write_payload_stream_sha256",
                 "workload_opportunity", "prefill_sha256",
                 "expected_post_sha256", "manifest_sha256",
                 "qd", "layout", "seed", "iops_requested", "warmup_ops",
                 "measure_ops", "read_ops", "write_ops", "verified_pages",
                 "verified_post_sha256")
    for key in immutable:
        if len({str(entry.get(key)) for entry in entries}) != 1:
            raise ValueError("INVALID COMPARISON: mismatch in " + key)
    for entry in entries:
        if entry.get("verdict") != "PASS" or (
            entry.get("verified_post_sha256") != entry.get("expected_post_sha256")
        ):
            raise ValueError("INVALID COMPARISON: failing oracle or unverified result")
    if any(entry.get("packed_read") is not None for entry in entries):
        packed = [entry.get("packed_read") for entry in entries]
        if not all(isinstance(p, dict) for p in packed):
            raise ValueError("INVALID COMPARISON: mixed packed-read qualification")
        if any(p.get("logical_bytes") != 4194304 or
               p.get("logical_image_sha256") != packed[0].get("logical_image_sha256")
               for p in packed):
            raise ValueError("INVALID COMPARISON: differing packed-read volume/image")
        for mode in ("sequential", "seeded_random"):
            phases = [p.get("passes", {}).get(mode) for p in packed]
            if any(not isinstance(phase, dict) or
                   phase.get("verified_pages") != 1024 or
                   phase.get("verified_image_sha256") != packed[0]["logical_image_sha256"]
                   for phase in phases):
                raise ValueError("INVALID COMPARISON: packed READ byte oracle mismatch")
        if packed[1].get("packed_close_delta") is not None and (
                packed[1]["packed_close_delta"] <= 0):
            raise ValueError("INVALID COMPARISON: swapz packed write not proven")
    normalized = sorted(entries, key=lambda entry: CANDIDATES.index(entry["candidate"]))
    first, second = normalized
    identities = [entry.get("device_identity") for entry in normalized]
    rootless = all(identity and "test_regular_file" in identity for identity in identities)
    loaded = all(identity and "device" in identity for identity in identities)
    if not (rootless or loaded):
        raise ValueError("INVALID COMPARISON: mixed, missing or unowned arm identity")
    output = {"verdict": "PASS_IDENTICAL_LOGICAL_INPUT",
              "scope": ("exact same fixture, prefill, ordered independent-page "
                        "operation waves, logical reads, and final oracle; "
                        "NOT identical per-BIO kernel arrival timing"),
              "fixture_sha256": first["fixture_sha256"],
              "trace_sha256": first["trace_sha256"],
              "write_payload_stream_sha256": first["write_payload_stream_sha256"],
              "workload_opportunity": first.get("workload_opportunity"),
              "read_ops": first["read_ops"], "write_ops": first["write_ops"],
              "results": [{k: entry.get(k) for k in
                           ("candidate", "source_sha", "achieved_iops", "lower_io")}
                          for entry in normalized]}
    throughput = [measured_throughput(entry, require_lower=loaded)
                  for entry in normalized]
    for entry, rates in zip(output["results"], throughput):
        entry["throughput_mbps"] = rates
    output["bandwidth_scope"] = (
        "actual completed logical 4KiB IO / measurement seconds versus "
        "independent backing-sector deltas / each arm's measurement seconds; "
        "no matched physical disk bandwidth budget; unpaced means no "
        "artificial offered-rate sleep, not proven SSD saturation"
    )
    if rootless:
        output["performance_qualification"] = "ROOTLESS_NOT_DEVICE_EVIDENCE"
    else:
        if first.get("source_sha") != second.get("source_sha") or not re.fullmatch(
            r"[a-f0-9]{40}", str(first.get("source_sha", ""))
        ):
            raise ValueError("INVALID COMPARISON: loaded source revision mismatch")
        if (identities[0].get("owned_disk") == identities[1].get("owned_disk") or
                identities[0].get("lower_major_minor") ==
                identities[1].get("lower_major_minor") or
                identities[0].get("dm_uuid") is not None or
                not identities[1].get("dm_uuid")):
            raise ValueError("INVALID COMPARISON: backing arms are not independent")
        required = ("lower_read_requests", "lower_read_bytes",
                    "lower_write_requests", "lower_write_bytes",
                    "lower_flush_requests")
        for entry in normalized:
            lower_io = entry.get("lower_io")
            if not isinstance(lower_io, dict) or any(
                not isinstance(lower_io.get(key), int) or
                lower_io[key] < 0 for key in required
            ):
                raise ValueError("INVALID COMPARISON: missing independent lower I/O")
        off_bytes = first["lower_io"]["lower_write_bytes"]
        swapz_bytes = second["lower_io"]["lower_write_bytes"]
        output["lower_write_bytes_saved_fraction"] = (
            (off_bytes - swapz_bytes) / off_bytes if off_bytes else None
        )
        # Same useful completed work; may be paced or unpaced.
        # No inference about a fixed physical-disk bandwidth budget.
        output["write_input_per_lower_byte_swapz"] = (
            throughput[1]["write_input_per_lower_byte"]
        )
        achieved = [entry.get("achieved_iops") for entry in normalized]
        if any(not isinstance(rate, (int, float)) or
               not math.isfinite(rate) or rate <= 0 for rate in achieved):
            raise ValueError("INVALID COMPARISON: invalid achieved IOPS")
        # A conservative explicit comparison policy. This is a matching
        # gate, never proof that matching rates imply matching BIO arrivals.
        mismatch = abs(achieved[0] - achieved[1]) / max(achieved)
        output["achieved_iops_difference_fraction"] = mismatch
        output["logical_write_mbps_ratio_swapz_to_off"] = (
            throughput[1]["logical_write_mbps"] / throughput[0]["logical_write_mbps"]
            if throughput[0]["logical_write_mbps"] > 0 else None
        )
        output["lower_write_mbps_ratio_swapz_to_off"] = (
            throughput[1]["lower_write_mbps"] / throughput[0]["lower_write_mbps"]
            if throughput[0]["lower_write_mbps"] > 0 else None
        )
        if first["iops_requested"] == 0:
            # Differing achieved throughput is the observation, not a
            # violation of the paced 5% offered-work matching contract.
            output["rate_mode"] = "unpaced"
            output["allowed_iops_difference_fraction"] = None
            output["performance_qualification"] = "UNPACED_THROUGHPUT_MEASUREMENT_ONLY"
        else:
            output["rate_mode"] = "paced"
            output["allowed_iops_difference_fraction"] = 0.05
            output["performance_qualification"] = (
                "MATCHED_LOAD_MEASUREMENT_ONLY" if mismatch <= 0.05
                else "INCONCLUSIVE_UNMATCHED_ACHIEVED_LOAD"
            )
    print(json.dumps(output, sort_keys=True))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="create immutable workload trace")
    prep.add_argument("--fixture", required=True)
    prep.add_argument("--output-dir", required=True)
    prep.add_argument("--seed", type=lambda x: int(x, 0), default=0x51A0A9)
    prep.add_argument("--logical-pages", type=int, default=4096)
    prep.add_argument("--writer-pages", type=int, default=1024)
    prep.add_argument("--reader-start", type=int, default=2048)
    prep.add_argument("--reader-pages", type=int, default=1024)
    prep.add_argument("--layout", choices=("disjoint", "same-region"), default="disjoint")
    prep.add_argument("--qd", type=int, default=8)
    prep.add_argument("--read-pct", type=int, default=20)
    prep.add_argument("--warmup-ops", type=int, default=8000)
    prep.add_argument("--measure-ops", type=int, default=24000)
    prep.add_argument("--iops", type=int, default=5000)
    run = sub.add_parser("run", help="replay one candidate and verify full image")
    run.add_argument("--fixture", required=True)
    run.add_argument("--trace", required=True)
    run.add_argument("--manifest", required=True)
    run.add_argument("--candidate", choices=CANDIDATES, required=True)
    run.add_argument("--source-sha", required=True)
    run.add_argument("--device", required=True)
    run.add_argument("--result", required=True)
    run.add_argument("--regular-file-test", action="store_true")
    run.add_argument("--packed-read", action="store_true")
    run.add_argument("--owned-nullblk-name")
    run.add_argument("--expected-dev")
    run.add_argument("--expected-lower-dev")
    run.add_argument("--expected-dm-uuid")
    cmp = sub.add_parser("compare", help="fail closed unless all logical inputs match")
    cmp.add_argument("--reports", nargs=2, required=True)
    args = ap.parse_args()
    try:
        if args.command == "prepare":
            prepare(args)
        elif args.command == "run":
            replay(args)
        else:
            compare(args)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        ap.exit(2, "BLOCKED/FAIL: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
