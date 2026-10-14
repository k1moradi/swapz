#!/usr/bin/env python3
"""Immutable trace preparation and owned-device replay for off/V3.

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
import os
import random
import re
import stat
import subprocess
import struct
import tempfile
import time
from pathlib import Path

PAGE = 4096
SCHEMA = 1
CANDIDATES = ("off", "v3")


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


def check_owned_block(path, st, candidate, args, logical_pages):
    if not args.owned_nullblk_name or not args.expected_dev:
        raise ValueError("block I/O requires owned null_blk identity and exact major:minor")
    name = args.owned_nullblk_name
    if not re.fullmatch(r"nullb_swapz_[A-Za-z0-9_-]{4,70}", name):
        raise ValueError("rejecting backing name without unique swapz null_blk prefix")
    conf = Path("/sys/kernel/config/nullb") / name
    disk = Path("/sys/block") / name
    if (conf / "memory_backed").read_text().strip() != "1" or (
        conf / "power"
    ).read_text().strip() != "1":
        raise ValueError("null_blk is not powered on and memory-backed")
    null_dev = (disk / "dev").read_text().strip()
    actual = f"{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}"
    if actual != args.expected_dev or null_dev != args.expected_lower_dev:
        raise ValueError("major/minor mismatch against independently pinned owned device")
    sysdev = Path("/sys/dev/block") / actual
    actual_name = sysdev.resolve().name
    sectors = int((sysdev / "size").read_text().strip())
    if candidate == "off":
        if sectors * 512 < logical_pages * PAGE:
            raise ValueError("owned null_blk is smaller than logical working range")
        if args.expected_dm_uuid or actual != null_dev or actual_name != name:
            raise ValueError("off control must use the bare exact owned null_blk")
    else:
        if not args.expected_dm_uuid or not re.fullmatch(
            r"SWZ[A-Za-z0-9_-]{4,120}", args.expected_dm_uuid
        ):
            raise ValueError("required trial-specific DM UUID missing")
        if not actual_name.startswith("dm-") or (
            sysdev / "dm/uuid"
        ).read_text().strip() != args.expected_dm_uuid:
            raise ValueError("DM UUID and exact mapped block device differ")
        if {entry.name for entry in (sysdev / "slaves").iterdir()} != {name}:
            raise ValueError("DM target does not depend exclusively on owned null_blk")
        if sectors * 512 != logical_pages * PAGE:
            raise ValueError("DM mapping size differs from exact workload")
        dm_name = (sysdev / "dm/name").read_text().strip()
        got = subprocess.run(["dmsetup", "table", dm_name],
                             check=True, capture_output=True, text=True,
                             timeout=10).stdout.strip().split()
        want_type = "swapz3"
        if len(got) < 4 or got[:4] != [
            "0", str(logical_pages * PAGE // 512), want_type, null_dev
        ]:
            raise ValueError("DM target type/length/backing differs from candidate")
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
    return {"device": actual, "owned_nullblk": name, "lower_major_minor": null_dev,
            "dm_uuid": args.expected_dm_uuid if candidate != "off" else None}


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


def iostat_delta(before, after):
    if before is None or after is None:
        return None
    if len(before) != len(after):
        raise ValueError("backing stat shape changed")
    delta = [end - start for start, end in zip(before, after)]
    if any(x < 0 for x in (delta[0], delta[2], delta[4], delta[6])):
        raise ValueError("backing counter reset during measurement")
    return {"lower_read_requests": delta[0], "lower_read_bytes": delta[2] * 512,
            "lower_write_requests": delta[4], "lower_write_bytes": delta[6] * 512,
            "lower_flush_requests": delta[15]}


def full_write(fd, page, buf):
    n = os.pwritev(fd, [buf], page * PAGE)
    if n != PAGE:
        raise OSError("short lower write")


def full_read(fd, page, buf, expected):
    n = os.preadv(fd, [buf], page * PAGE)
    if n != PAGE or buf != expected:
        raise OSError("short or mismatched logical page read")


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
        fd = os.open(path, flags)
        try:
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

            def execute(item):
                start = time.monotonic_ns()
                if item["op"] == "W":
                    full_write(fd, item["page"], chunks[item["fixture"]])
                else:
                    buffer = mmap.mmap(-1, PAGE)
                    view = memoryview(buffer)
                    try:
                        full_read(fd, item["page"], view, chunks[item["fixture"]])
                    finally:
                        view.release()
                        buffer.close()
                return time.monotonic_ns() - start

            warmup_ns = 0
            samples = {"W": [], "R": []}
            measured_start_ns = None
            measured_end_ns = None
            before = None
            after = None
            with concurrent.futures.ThreadPoolExecutor(max_workers=mf["qd"]) as pool:
                for first in range(0, len(trace), mf["qd"]):
                    wave = trace[first:first + mf["qd"]]
                    if wave[0]["phase"] == "measure" and measured_start_ns is None:
                        before = lower_stat(args.owned_nullblk_name)
                        measured_start_ns = time.monotonic_ns()
                    if wave[0]["phase"] == "warmup":
                        warmup_ns = time.monotonic_ns()
                    if mf["iops"] and wave[0]["phase"] == "measure":
                        # Fixed offered schedule; equal operation sequence,
                        # not a false claim of identical physical arrival.
                        due = (measured_start_ns +
                               (wave[0]["seq"] - mf["warmup_ops"]) * 1000000000 // mf["iops"])
                        remain = due - time.monotonic_ns()
                        if remain > 0:
                            time.sleep(remain / 1e9)
                    futures = [pool.submit(execute, item) for item in wave]
                    for item, future in zip(wave, futures):
                        elapsed = future.result()  # fail closed on any short/mismatch
                        if item["phase"] == "measure":
                            samples[item["op"]].append(elapsed)
                os.fsync(fd)
                measured_end_ns = time.monotonic_ns()
                after = lower_stat(args.owned_nullblk_name)
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
        "prefill_sha256": mf["prefill_sha256"],
        "expected_post_sha256": mf["expected_post_sha256"],
        "verified_post_sha256": post_hash.hexdigest(),
        "qd": mf["qd"], "layout": mf["layout"], "seed": mf["seed"],
        "iops_requested": mf["iops"], "warmup_ops": mf["warmup_ops"],
        "measure_ops": mf["measure_ops"], "write_ops": len(samples["W"]),
        "read_ops": len(samples["R"]), "verified_pages": mf["logical_pages"],
        "seconds": seconds, "achieved_iops": mf["measure_ops"] / seconds,
        "lower_io": iostat_delta(before, after), "verdict": "PASS",
        "read_p50_ns": percentile(samples["R"], .50),
        "read_p95_ns": percentile(samples["R"], .95),
        "read_p99_ns": percentile(samples["R"], .99),
        "write_p50_ns": percentile(samples["W"], .50),
        "write_p95_ns": percentile(samples["W"], .95),
        "write_p99_ns": percentile(samples["W"], .99),
    }
    result_path = Path(args.result)
    if result_path.exists():
        raise ValueError("refusing to overwrite a prior trial result")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


def compare(args):
    entries = [safe_load(name) for name in args.reports]
    if set(x["candidate"] for x in entries) != set(CANDIDATES) or len(entries) != 2:
        raise ValueError("exactly one off and one v3 result required")
    immutable = ("fixture_sha256", "trace_sha256", "write_payload_stream_sha256",
                 "prefill_sha256", "expected_post_sha256", "manifest_sha256",
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
    normalized = sorted(entries, key=lambda x: CANDIDATES.index(x["candidate"]))
    output = {"verdict": "PASS_IDENTICAL_LOGICAL_INPUT",
              "scope": ("exact same fixture, prefill, ordered independent-page "
                        "operation waves, logical reads, and final oracle; "
                        "NOT identical per-BIO kernel arrival timing"),
              "fixture_sha256": entries[0]["fixture_sha256"],
              "trace_sha256": entries[0]["trace_sha256"],
              "write_payload_stream_sha256": entries[0]["write_payload_stream_sha256"],
              "read_ops": entries[0]["read_ops"], "write_ops": entries[0]["write_ops"],
              "results": [{k: entry.get(k) for k in
                           ("candidate", "source_sha", "achieved_iops", "lower_io")}
                          for entry in normalized]}
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
