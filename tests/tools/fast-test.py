#!/usr/bin/env python3
"""Development-only quick decision loop behind `make fast_test`.

It builds the working tree, runs native/replay contract checks and defaults
to three raw-versus-swapz repeats per owned null_blk scenario, then prints
development tables. Dirty trees are allowed so a policy change can be measured
before it is committed.

`RESUME=1` may reuse a matching completed native/replay stage; the current
product build, loaded preflight and selected benchmark pairs still run fresh.

`make fast_test` never qualifies a source revision, never writes or publishes
test_results.json and never replaces `make test`. Repeats are noise-screened
directional observations, not the matched confidence intervals required for
qualification; promotion still requires the full owner matrix.
"""
import argparse
import hashlib
import json
import os
import re
import runpy
import shlex
import shutil
import stat
import statistics
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Shared page protection also covers the Python fixture/stripe preparation heap.
sys.path.insert(0, str(ROOT / "tests/runtime/benchmark"))
import private_memory  # noqa: E402
# Reuse the measured replay's counter parsing/reset checks; no polling worker.
HOST_CPU = runpy.run_path(str(ROOT / "tests/runtime/benchmark/io-replay.py"))
OUT_DIR = ROOT / "build/tests/fast-test"
ADMISSION_EVIDENCE = OUT_DIR / "development-evidence.json"
RESUME_DIR = OUT_DIR / "resume"
RESUME_SCHEMA = "swapz-fast-test-resume"
RESUME_STATE_MAX_BYTES = 1024 * 1024
RESUME_INPUT_PATHS = (
    "Makefile", "src/kernel", "tests/suites", "tests/runtime/benchmark",
    "tests/runtime/native/io", "tests/runtime/native/codec/anon-page-analyzer.c",
    "tests/runtime/native/codec/anon-page-analyzer-test.py",
    "tests/tools/fast-test.py",
)
PAIR = "tests/tools/benchmark-owned-pair.sh"
STRIPED_PAIR = "tests/tools/benchmark-striped-owned.sh"
PREFLIGHT = "tests/tools/loaded-preflight.sh"
COMMON = ["--run-owned-ram-pair", "--profile", "medium", "--retain-ms", "2",
          "--unpaced"]
# Exact device models from tests/tools/test-loaded.sh, in the bounded suffix
# order that benchmark-owned-pair.sh peels from the tail.
MODELS = {
    "sd": ["--lower-mbps", "10", "--hw-queue-depth", "1",
           "--completion-nsec", "1000000"],
    "fast": ["--lower-mbps", "80", "--hw-queue-depth", "64",
             "--completion-nsec", "150000"],
    "sdcard": ["--lower-mbps", "100", "--submit-queues", "1",
               "--hw-queue-depth", "4", "--completion-nsec", "500000"],
    "sata": ["--lower-mbps", "500", "--submit-queues", "1",
             "--hw-queue-depth", "32", "--completion-nsec", "100000"],
    "nvme4": ["--lower-mbps", "6500", "--submit-queues", "4",
              "--hw-queue-depth", "64", "--completion-nsec", "25000"],
    "nvme5": ["--lower-mbps", "12000", "--submit-queues", "4",
              "--hw-queue-depth", "64", "--completion-nsec", "14000"],
}
CONTENT_WEIGHTS = {"medium": "medium=100", "entropy": "entropy=100",
                   "balanced": "medium=50,entropy=50"}
CONTENT_PROFILES = (*CONTENT_WEIGHTS, "representative")
ANON_PAGE_ANALYZER = ROOT / "build/tests/native/anon-page-analyzer"
REPRESENTATIVE_PAGE_LIMIT = 8192
DEFAULT_SCENARIOS = (
    "sata-mixed", "nvme4-mixed", "nvme5-mixed",
    "fast-mixed", "fast-w4", "fast-w8",
)
STRIPED_MODELS = ("nvme5", "sata")
DEFAULT_STRIPE_COUNTS = (1, 2, 4)
STRIPED_WRITE_QDS = (4, 8)
MIXED_MEASURE_OPS = (16384, 65536)


def quiet_host_sample():
    before = HOST_CPU["host_cpu_snapshot"]()
    time.sleep(0.2)
    return HOST_CPU["host_cpu_delta"](before, HOST_CPU["host_cpu_snapshot"]())


def performance_validity(before, after, arms):
    """Conservative development screen, not proof of an idle host or causality."""
    reasons, missing = [], False
    for label, sample in (("pre", before), ("post", after)):
        if sample.get("status") != "AVAILABLE":
            missing = True
        for field, limit, name in (("busy_fraction", .25, "busy"),
                                   ("pressure_some_fraction", .05, "CPU PSI"),
                                   ("steal_fraction", .01, "steal")):
            value = sample.get(field)
            if value is None:
                missing = True
            elif value > limit:
                reasons.append(f"{label} {name} {value:.1%}")
    # Timed CPU/PSI includes the benchmark itself; only steal is unambiguous
    # external service loss. Do not mistake target saturation for host noise.
    for label, arm in arms.items():
        sample = arm.get("host_cpu") or {}
        if sample.get("status") != "AVAILABLE":
            missing = True
        steal = sample.get("steal_fraction")
        if steal is None:
            missing = True
        elif steal > .01:
            reasons.append(f"{label} timed steal {steal:.1%}")
    noisy = bool(reasons)
    if missing:
        reasons.append("host counters unavailable")
    status = "NOISY" if noisy else "UNKNOWN" if missing else "SCREENED"
    return {"status": status, "performance_usable": status == "SCREENED",
            "reasons": reasons, "quiet_before": before, "quiet_after": after}


def base_scenario(label):
    """Strip repeat/policy suffixes without changing workload identity."""
    return label.split("#", 1)[0].split("@", 1)[0]


def reject_raw_drift(rows):
    groups = {}
    for row in rows:
        if "error" not in row:
            groups.setdefault(base_scenario(row["scenario"]), []).append(row)
    for group in groups.values():
        rates = [row["raw_w"] for row in group]
        if min(rates) <= 0:
            for row in group:
                validity = row["performance_validity"]
                if validity["status"] != "NOISY":
                    validity["status"] = "UNKNOWN"
                validity["performance_usable"] = False
                validity["reasons"].append("raw control unavailable")
            continue
        if len(rates) < 2:
            continue
        spread = max(rates) / min(rates) - 1
        if spread <= .10:
            continue
        for row in group:
            validity = row["performance_validity"]
            validity.update(status="NOISY", performance_usable=False)
            validity["reasons"].append(f"raw repeat spread {spread:.1%}")


def striped_scenario(name):
    model, _, kind = name.partition("-")
    if kind == "stripes" and model in STRIPED_MODELS:
        return model, "mixed"
    if model == "fast" and kind in ("stripes-w4", "stripes-w8"):
        return model, "write-q" + kind[-1]
    return None


def scenario_arguments(name, plan, calibration=False,
                       candidate_first=False, submitter_prepare=1,
                       hand_records=8, private_fixture=False):
    model, _, kind = name.partition("-")
    if model not in MODELS or not kind:
        raise ValueError(f"unknown scenario {name!r}")
    arguments = [*COMMON, *MODELS[model]]
    if kind.startswith("w") and kind[1:] in ("1", "4", "8", "32"):
        arguments += ["--write-only-qd", kind[1:]]
    elif kind in ("mixed-lanes", "mixed-lanes-waves"):
        arguments += ["--mixed-lanes", "persistent" if kind == "mixed-lanes" else "waves"]
    elif kind != "mixed":
        raise ValueError(f"unknown scenario {name!r}")
    arguments.append("--async-prepare")
    if not submitter_prepare:
        arguments += ["--submitter-prepare", "0"]
    if hand_records != 8:
        arguments += ["--hand-records", str(hand_records)]
    if private_fixture:
        arguments.append("--private-fixture")
    arguments += ["--shared-plan", str(plan)]
    if calibration:
        arguments.append("--linear-calibration")
    if candidate_first:
        arguments.append("--swapz-first")
    return arguments


def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, check=True, **kwargs)


def write_development_evidence(evidence):
    """Persist exact-source dev-loop stages; this never qualifies a source."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUT_DIR / f".development-evidence.{os.getpid()}.tmp"
    payload = (json.dumps(evidence, sort_keys=True, indent=2) + "\n").encode()
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             getattr(os, "O_CLOEXEC", 0) |
                             getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=False) as output:
                output.write(payload)
                output.flush()
                os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, ADMISSION_EVIDENCE)
        directory_fd = os.open(OUT_DIR, os.O_RDONLY | os.O_DIRECTORY |
                               getattr(os, "O_CLOEXEC", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _open_resume_directory(create=False):
    directories = (ROOT / "build", ROOT / "build/tests", OUT_DIR, RESUME_DIR)
    for directory in directories:
        try:
            info = directory.lstat()
        except FileNotFoundError:
            if not create:
                return -1
            try:
                os.mkdir(directory, 0o700)
            except FileExistsError:
                pass
            info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or
                info.st_uid != os.geteuid()):
            raise OSError("resume storage is not an owned directory")

    descriptor = os.open(
        RESUME_DIR, os.O_RDONLY | os.O_DIRECTORY |
        getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        os.close(descriptor)
        raise OSError("resume storage identity changed")
    if stat.S_IMODE(info.st_mode) != 0o700:
        if not create:
            os.close(descriptor)
            return -1
        os.fchmod(descriptor, 0o700)
    return descriptor


def read_resume_checkpoint():
    """Read only a private, stable checkpoint; invalid cache is never evidence."""
    directory_fd = -1
    descriptor = -1
    try:
        directory_fd = _open_resume_directory()
        if directory_fd < 0:
            return None
        descriptor = os.open(
            "checkpoint.json", os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) |
            getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or
                stat.S_IMODE(before.st_mode) != 0o600 or
                before.st_size > RESUME_STATE_MAX_BYTES):
            return None
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                after.st_ctime_ns):
            return None
        checkpoint = json.loads(
            b"".join(chunks), object_pairs_hook=_unique_json_object)
        if (not isinstance(checkpoint, dict) or
                checkpoint.get("schema") != RESUME_SCHEMA):
            return None
        return checkpoint
    except (OSError, ValueError, TypeError, RecursionError,
            json.JSONDecodeError):
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory_fd >= 0:
            os.close(directory_fd)


def write_resume_checkpoint(checkpoint):
    """Durably replace the bounded private resume state, never admission evidence."""
    directory_fd = -1
    descriptor = -1
    temporary = None
    try:
        payload = (json.dumps(checkpoint, sort_keys=True, separators=(",", ":")) +
                   "\n").encode()
        if len(payload) > RESUME_STATE_MAX_BYTES:
            return False
        directory_fd = _open_resume_directory(create=True)
        temporary = f"checkpoint.{os.getpid()}.{time.monotonic_ns()}.tmp"
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
            getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            0o600, dir_fd=directory_fd)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(payload)
            output.flush()
            os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, "checkpoint.json", src_dir_fd=directory_fd,
                   dst_dir_fd=directory_fd)
        temporary = None
        os.fsync(directory_fd)
        return True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory_fd >= 0:
            if temporary is not None:
                try:
                    os.unlink(temporary, dir_fd=directory_fd)
                except OSError:
                    pass
            os.close(directory_fd)


def invalidate_resume_checkpoint():
    """Remove a matching old PASS before an explicitly fresh native run."""
    directory_fd = -1
    try:
        directory_fd = _open_resume_directory()
        if directory_fd < 0:
            return True
        try:
            os.unlink("checkpoint.json", dir_fd=directory_fd)
        except FileNotFoundError:
            return True
        os.fsync(directory_fd)
        return True
    except OSError:
        return False
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)


def _stable_file_digest(path):
    try:
        initial = path.lstat()
    except FileNotFoundError:
        raise
    if not stat.S_ISREG(initial.st_mode):
        raise OSError("resume input is not a regular file")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) |
        getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise OSError("resume input is not a regular file")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                after.st_ctime_ns):
            raise OSError("resume input changed while hashing")
        return digest.hexdigest(), stat.S_IMODE(before.st_mode)
    finally:
        os.close(descriptor)


def resume_input_fingerprint():
    """Hash only fast-test dependencies; unrelated rootless files may advance main."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", *RESUME_INPUT_PATHS], cwd=ROOT,
        capture_output=True, check=True).stdout.split(b"\0")
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z", "--",
         *RESUME_INPUT_PATHS], cwd=ROOT, capture_output=True,
        check=True).stdout.split(b"\0")
    paths = sorted({os.fsdecode(path) for path in (*tracked, *untracked) if path})
    if not paths:
        raise OSError("no fast-test inputs found")
    digest = hashlib.sha256()
    for relative in paths:
        input_path = ROOT / relative
        digest.update(relative.encode("utf-8", "surrogateescape") + b"\0")
        try:
            file_digest, mode = _stable_file_digest(input_path)
        except FileNotFoundError:
            digest.update(b"MISSING\0")
            continue
        digest.update(f"{mode:o}\0{file_digest}\n".encode("ascii"))
    return digest.hexdigest()


def resume_host_fingerprint():
    uname = os.uname()
    compiler = os.environ.get("CC", "cc")
    try:
        compiler_command = shlex.split(compiler)
        compiler_executable = (shutil.which(compiler_command[0])
                               if compiler_command else None)
        compiler_result = subprocess.run(
            [*compiler_command, "--version"], cwd=ROOT, capture_output=True,
            text=True, check=False, timeout=5)
        compiler_version = (compiler_result.stdout or compiler_result.stderr
                            ).splitlines()[0][:200]
    except (OSError, IndexError, subprocess.TimeoutExpired, ValueError):
        compiler_executable = None
        compiler_version = "unavailable"
    python3_executable = shutil.which("python3")
    build_environment = {
        name: os.environ.get(name, "")
        for name in ("CFLAGS", "CPPFLAGS", "LDFLAGS", "OBJDUMP",
                     "SANITIZE", "THREAD_SANITIZE", "LD_LIBRARY_PATH",
                     "LD_PRELOAD", "PYTHONPATH", "ASAN_OPTIONS",
                     "UBSAN_OPTIONS", "LSAN_OPTIONS", "TSAN_OPTIONS",
                     "SWAPZ_PRIVATE_FIXTURE")
    }
    return {
        "architecture": uname.machine,
        "kernel_release": uname.release,
        "python": sys.version.splitlines()[0],
        "python_executable": os.path.realpath(sys.executable),
        "python3_executable": (os.path.realpath(python3_executable)
                                if python3_executable else None),
        "compiler": compiler,
        "compiler_executable": compiler_executable,
        "compiler_version": compiler_version,
        "build_environment_sha256": _canonical_sha256(build_environment),
    }


def _native_artifact_paths():
    names = (
        "io-replay-native", "flush-ordering", "lower-write-aggregation",
        "window-policy", "preparation-slots", "preparation-codec-result",
        "preparation-publication-lifetime", "lane-gap", "anon-page-analyzer",
    )
    paths = [ROOT / "build/tests/native" / name for name in names]
    paths.append(ROOT / "build/tests/native/predictor-core.o")
    architecture_objects = {
        "x86_64": ("predictor-sse2.o", "predictor-avx2.o", "predictor-avx512.o"),
        "aarch64": ("predictor-neon.o",),
    }.get(os.uname().machine, ())
    paths.extend(ROOT / "build/tests/native" / name
                 for name in architecture_objects)
    return paths


def native_artifact_fingerprint():
    digest = hashlib.sha256()
    for path in _native_artifact_paths():
        try:
            file_digest, mode = _stable_file_digest(path)
        except OSError:
            return None
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(f"{mode:o}\0{file_digest}\n".encode("ascii"))
    return digest.hexdigest()


def _canonical_sha256(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def checkpoint_matches_native(checkpoint, input_sha256, host):
    if not isinstance(checkpoint, dict):
        return False
    native = checkpoint.get("native")
    if not isinstance(native, dict):
        return False
    return (native.get("status") == "PASS" and
            native.get("input_sha256") == input_sha256 and
            re.fullmatch(r"[0-9a-f]{64}",
                         str(native.get("artifacts_sha256", ""))) is not None and
            re.fullmatch(r"[0-9a-f]{40}",
                         str(native.get("measurement_head", ""))) is not None and
            isinstance(native.get("completed_at_ns"), int) and
            not isinstance(native.get("completed_at_ns"), bool) and
            native.get("completed_at_ns") > 0 and
            native.get("host") == host and
            native.get("artifacts_sha256") == native_artifact_fingerprint())


def checkpoint_state(checkpoint):
    if not isinstance(checkpoint, dict) or checkpoint.get("schema") != RESUME_SCHEMA:
        return {"schema": RESUME_SCHEMA, "native": None}
    return checkpoint


def loaded_preflight_diagnostic(output):
    pattern = re.compile(
        r"^BLOCKED: LOADED_PREFLIGHT=([A-Z_]+) check=([a-z0-9_]+) "
        r"errno=([A-Za-z0-9_-]+)(?: remedy=.*)?$")
    matches = [pattern.fullmatch(line.strip())
               for line in output.splitlines()]
    matches = [match for match in matches if match]
    if len(matches) != 1:
        return {"status": "BLOCKED", "check": "unclassified",
                "errno": "unavailable"}
    match = matches[0]
    return {"status": match.group(1), "check": match.group(2),
            "errno": match.group(3)}


def build():
    jobs = f"-j{max(1, min(os.cpu_count() or 1, 16))}"
    run(["make", jobs, "--no-print-directory"], stdout=subprocess.DEVNULL)


def build_native_checks():
    jobs = f"-j{max(1, min(os.cpu_count() or 1, 16))}"
    run(["make", jobs, "--no-print-directory", "-C", "tests/suites",
         "test-replay-helper", "test-lower-io", "test-anon-page-analyzer"],
        stdout=subprocess.DEVNULL)
    run([sys.executable, "-B", "tests/runtime/benchmark/io-replay-test.py"],
        stdout=subprocess.DEVNULL)


def prepare_representative_fixture(plan, sample_path):
    if not sample_path:
        raise ValueError("representative content requires an owner-supplied page sample")
    # Python bytes, hashes and striped plans are protected before any page read.
    private_memory.protect_private_memory()
    # Child replays detect fixture.json themselves; never leak a global
    # representative-content marker into unrelated synthetic scenarios.

    flags = (os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) |
             getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        source_fd = os.open(os.fspath(sample_path), flags)
    except OSError:
        raise ValueError("cannot open representative page sample safely") from None

    fixture_path = plan / "fixture.bin"
    output_fd = -1
    try:
        with os.fdopen(source_fd, "rb") as source:
            source_fd = -1
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("representative page sample must be a regular file")
            if before.st_size % 4096:
                raise ValueError("representative page sample has a partial 4 KiB page")
            page_count = before.st_size // 4096
            if not 128 <= page_count <= REPRESENTATIVE_PAGE_LIMIT:
                raise ValueError("representative page sample must contain 128..8192 pages")

            output_flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                            getattr(os, "O_CLOEXEC", 0) |
                            getattr(os, "O_NOFOLLOW", 0))
            output_fd = os.open(fixture_path, output_flags, 0o600)
            os.fchmod(output_fd, 0o600)
            digest = hashlib.sha256()
            remaining = before.st_size
            with os.fdopen(output_fd, "wb") as destination:
                output_fd = -1
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("representative page sample changed while copying")
                    destination.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                if source.read(1):
                    raise ValueError("representative page sample changed while copying")
                after = os.fstat(source.fileno())
                before_identity = (before.st_dev, before.st_ino, before.st_size,
                                   before.st_mtime_ns, before.st_ctime_ns)
                after_identity = (after.st_dev, after.st_ino, after.st_size,
                                  after.st_mtime_ns, after.st_ctime_ns)
                if before_identity != after_identity:
                    raise ValueError("representative page sample changed while copying")
                destination.flush()
                os.fsync(destination.fileno())

        with fixture_path.open("rb") as sample_stream:
            analyzed = subprocess.run(
                [str(ANON_PAGE_ANALYZER)], stdin=sample_stream,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if analyzed.returncode:
            raise ValueError("representative page analyzer rejected the sample")
        analysis = json.loads(analyzed.stdout)
        if (analysis.get("schema") != "swapz-anon-page-analysis-v1" or
                analysis.get("pages") != page_count or
                analysis.get("page_bytes") != 4096):
            raise ValueError("representative page analyzer returned invalid aggregates")

        lz4 = analysis["lz4"]
        return {
            "definition": "owner-supplied anonymous pages; offline analysis; no swapon",
            "content_profile": "representative",
            "pages": page_count,
            "page_bytes": 4096,
            "profile_pages": {"representative": page_count},
            "raw_pages": lz4["raw_pages"],
            "raw_page_bytes": lz4["raw_pages"] * 4096,
            "lz4_size_buckets": lz4["size_buckets"],
            "lz4_accepted_payload_bytes": lz4["payload_bytes"],
            "fixture_sha256": digest.hexdigest(),
            "offline_page_analysis": analysis,
        }
    except OSError:
        raise ValueError("cannot prepare representative page sample safely") from None
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if output_fd >= 0:
            os.close(output_fd)


def prepare_plan(content="medium", need_stripes=False, striped_write_qds=(),
                 mixed_ops=16384, sample_path=None):
    if mixed_ops not in MIXED_MEASURE_OPS:
        raise ValueError("MIXED_OPS must be 16384 or 65536")
    if content not in CONTENT_PROFILES:
        raise ValueError("unsupported benchmark content profile")
    if content == "representative" and not sample_path:
        raise ValueError("representative content requires an owner-supplied page sample")
    if content != "representative" and sample_path:
        raise ValueError("an anonymous page sample requires CONTENT=representative")
    (ROOT / "build/tests").mkdir(parents=True, exist_ok=True)
    plan = Path(tempfile.mkdtemp(prefix="benchmark-plan.",
                                 dir=ROOT / "build/tests"))
    try:
        replay = ["python3", "-B", "tests/runtime/benchmark/io-replay.py",
                  "prepare", "--fixture", str(plan / "fixture.bin"),
                  "--logical-pages", "1024", "--writer-pages", "256",
                  "--reader-start", "512", "--reader-pages", "256"]
        quiet = {"stdout": subprocess.DEVNULL}
        if content == "representative":
            fixture = prepare_representative_fixture(plan, sample_path)
            (plan / "fixture.json").write_text(
                json.dumps(fixture, indent=2, sort_keys=True) + "\n")
        else:
            weights = CONTENT_WEIGHTS[content]
            run(["python3", "-B", "tests/runtime/benchmark/anon-page-fixture.py",
                 "--output-prefix", str(plan / "fixture"), "--pages", "128",
                 "--seed", "0x51a0a9", "--weights", weights], **quiet)
        run([*replay, "--output-dir", str(plan / "plan"), "--qd", "32",
             "--read-pct", "25", "--warmup-ops", "1024", "--measure-ops",
             str(mixed_ops), "--iops", "0"], **quiet)
        for mode in ("waves", "persistent"):
            run([*replay, "--output-dir", str(plan / f"plan-mixed-lanes-{mode}"),
                 "--qd", "32", "--read-pct", "25", "--warmup-ops", "1024",
                 "--measure-ops", str(mixed_ops), "--iops", "0",
                 "--mixed-lanes", mode], **quiet)
        if need_stripes:
            run([*replay, "--output-dir", str(plan / "plan-striped-base"),
                 "--qd", "32", "--read-pct", "25", "--warmup-ops", "1024",
                 "--measure-ops", "16384", "--iops", "0", "--mixed-lanes",
                 "persistent", "--stripe-partitionable"], **quiet)
        for qd in striped_write_qds:
            if qd not in STRIPED_WRITE_QDS:
                raise ValueError("striped WRITE QD must be 4 or 8")
            run([*replay, "--output-dir", str(plan / f"plan-striped-write-qd{qd}"),
                 "--qd", str(qd), "--read-pct", "0", "--warmup-ops", "256",
                 "--measure-ops", "4096", "--iops", "0", "--sustained-write",
                 "--stripe-partitionable"], **quiet)
        for qd in (1, 4, 8, 32):
            run([*replay, "--output-dir", str(plan / f"plan-write-qd{qd}"),
                 "--qd", str(qd), "--read-pct", "0", "--warmup-ops", "256",
                 "--measure-ops", "4096", "--iops", "0", "--sustained-write"],
                **quiet)
        return plan
    except BaseException:
        shutil.rmtree(plan, ignore_errors=True)
        raise




def hash_fixture_page_map(fixture_pages, page_indices):
    """Hash page contents in map order without another full logical buffer."""
    digest = hashlib.sha256()
    for page_index in page_indices:
        digest.update(fixture_pages[page_index])
    return digest.hexdigest()


def prepare_striped_plans(plan, stripe_counts, workload="mixed"):
    """Split a lane-owned immutable trace, conserving every original I/O."""
    if workload == "mixed":
        base_dir = plan / "plan-striped-base"
        stripe_prefix = "striped"
        expected_mode = "persistent-mixed"
        expected_qd = 32
    elif workload in ("write-q4", "write-q8"):
        expected_qd = int(workload[-1])
        base_dir = plan / f"plan-striped-write-qd{expected_qd}"
        stripe_prefix = f"striped-{workload}"
        expected_mode = "persistent-write"
    else:
        raise ValueError("unsupported striped workload")
    manifest = json.loads((base_dir / "manifest.json").read_text())
    rows = [json.loads(line) for line in
            (base_dir / "trace.jsonl").read_text().splitlines()]
    fixture_bytes = (plan / "fixture.bin").read_bytes()
    page_bytes = manifest["page_bytes"]
    fixture_pages = [
        fixture_bytes[offset:offset + page_bytes]
        for offset in range(0, len(fixture_bytes), page_bytes)
    ]
    if (manifest.get("replay_mode") != expected_mode or
            not manifest.get("stripe_partitionable") or
            manifest.get("qd") != expected_qd or
            any(row.get("lane") != row["page"] % expected_qd for row in rows) or
            (expected_mode == "persistent-write" and
             (manifest.get("read_pct") != 0 or
              any(row["op"] != "W" for row in rows)))):
        raise ValueError("striped base plan is not page/lane partitionable")

    for stripe_count in stripe_counts:
        if stripe_count not in DEFAULT_STRIPE_COUNTS or expected_qd % stripe_count:
            raise ValueError("stripe count must be one of 1,2,4")
        stripe_root = plan / f"{stripe_prefix}-{stripe_count}"
        stripe_root.mkdir()
        local_qd = manifest["qd"] // stripe_count
        logical_pages = manifest["logical_pages"] // stripe_count
        writer_pages = manifest["writer_pages"] // stripe_count
        reader_start = manifest["reader_start"] // stripe_count
        reader_pages = manifest["reader_pages"] // stripe_count
        for stripe_index in range(stripe_count):
            output = stripe_root / f"stripe-{stripe_index}"
            output.mkdir()
            transformed = []
            initial = [
                (page * stripe_count + stripe_index) % len(fixture_pages)
                for page in range(logical_pages)
            ]
            latest = list(initial)
            write_hash = hashlib.sha256()
            for local_seq, original in enumerate(
                    row for row in rows if row["lane"] % stripe_count == stripe_index):
                if original["page"] % stripe_count != stripe_index:
                    raise ValueError("stripeable base event escaped page partition")
                row = dict(original)
                row["seq"] = local_seq
                row["wave"] = local_seq // local_qd
                row["lane"] = original["lane"] // stripe_count
                row["page"] = original["page"] // stripe_count
                if row["op"] == "R" and row["fixture"] != latest[row["page"]]:
                    raise ValueError("striped READ no longer matches deterministic prefill")
                if row["op"] == "W":
                    write_hash.update(struct.pack(
                        "<QII", row["seq"], row["page"], row["fixture"]))
                    write_hash.update(fixture_pages[row["fixture"]])
                    latest[row["page"]] = row["fixture"]
                transformed.append(row)
            trace_bytes = "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in transformed).encode()
            (output / "trace.jsonl").write_bytes(trace_bytes)
            prefill_hash = hash_fixture_page_map(fixture_pages, initial)
            post_hash = hash_fixture_page_map(fixture_pages, latest)
            child = dict(manifest)
            child.update({
                "logical_pages": logical_pages,
                "writer_pages": writer_pages,
                "reader_start": reader_start,
                "reader_pages": reader_pages,
                "qd": local_qd,
                "warmup_ops": manifest["warmup_ops"] // stripe_count,
                "measure_ops": manifest["measure_ops"] // stripe_count,
                "trace_sha256": HOST_CPU["sha"](trace_bytes),
                "prefill_sha256": prefill_hash,
                "expected_post_sha256": post_hash,
                "write_payload_stream_sha256": write_hash.hexdigest(),
                "prefill_fixture_stride": stripe_count,
                "prefill_fixture_offset": stripe_index,
                "stripe_count": stripe_count,
                "stripe_index": stripe_index,
                "parent_trace_sha256": manifest["trace_sha256"],
                "workload_opportunity": HOST_CPU["workload_opportunity"](
                    transformed, fixture_pages, logical_pages, initial),
                "algorithm": (
                    "exact modulo-N partition of one persistent page/lane-owned "
                    f"{workload} trace; aggregate QD and operation count conserved"),
            })
            (output / "manifest.json").write_text(
                json.dumps(child, indent=2, sort_keys=True) + "\n")
            checked, final_map = HOST_CPU["check_plan"](
                output / "trace.jsonl", child, len(fixture_pages))
            if checked != transformed or final_map != latest:
                raise ValueError("striped plan failed byte-exact reconstruction")


def prepare_striped_workload_plans(plan, stripe_counts, striped_specs):
    """Build one shared trace split per selected workload, not per model."""
    try:
        workloads = dict.fromkeys(workload for _, workload in striped_specs)
        for workload in workloads:
            prepare_striped_plans(plan, stripe_counts, workload)
    except BaseException:
        # The caller owns this fresh temporary plan; do not leave a partial
        # directory that can confuse later development runs after setup fails.
        shutil.rmtree(plan, ignore_errors=True)
        raise


def parse_stripe_counts(value):
    try:
        counts = tuple(int(item) for item in re.split(r"[,\s]+", value) if item)
    except ValueError as error:
        raise ValueError("STRIPE_COUNTS must contain only 1,2,4") from error
    if (not counts or len(set(counts)) != len(counts) or
            any(count not in DEFAULT_STRIPE_COUNTS for count in counts)):
        raise ValueError("STRIPE_COUNTS must be a unique subset of 1,2,4")
    return counts


def parse_striped_pair(output):
    matches = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("experiment") == "multi-target-stripes":
            matches.append(record)
    if len(matches) != 1:
        raise ValueError("striped helper did not emit exactly one result")
    return matches[0]


def summarize_striped(label, pair, seconds):
    off, swapz = pair["arms"]["off"], pair["arms"]["swapz"]
    return {
        "scenario": label,
        "model": pair["model"],
        "workload": pair["workload"],
        "offered_qd": pair["aggregate_model"]["offered_qd"],
        "stripes": pair["stripes"],
        "pair_s": seconds,
        "replay_order": pair["order"],
        "raw_w": off["throughput_mbps"]["logical_write_mbps"],
        "swapz_w": swapz["throughput_mbps"]["logical_write_mbps"],
        "raw_r": off["throughput_mbps"]["logical_read_mbps"],
        "swapz_r": swapz["throughput_mbps"]["logical_read_mbps"],
        "raw_lw_bytes": off["lower_io"]["lower_write_bytes"],
        "swapz_lw_bytes": swapz["lower_io"]["lower_write_bytes"],
        "raw_lw_reqs": off["lower_io"]["lower_write_requests"],
        "swapz_lw_reqs": swapz["lower_io"]["lower_write_requests"],
        "raw_r_p99": (off["read_p99_ns"] / 1e6
                      if off.get("read_p99_ns") is not None else None),
        "swapz_r_p99": (swapz["read_p99_ns"] / 1e6
                        if swapz.get("read_p99_ns") is not None else None),
        "raw_w_p99": (off.get("write_p99_ns") or 0) / 1e6,
        "swapz_w_p99": (swapz.get("write_p99_ns") or 0) / 1e6,
        "raw_write_peaks": off["lower_inflight"]["per_stripe_write_peak"],
        "swapz_write_peaks": swapz["lower_inflight"]["per_stripe_write_peak"],
        "raw_simultaneous_write_devices":
            off["lower_inflight"]["max_simultaneous_write_devices"],
        "swapz_simultaneous_write_devices":
            swapz["lower_inflight"]["max_simultaneous_write_devices"],
        "swapz_aggregate_write_depth_peak":
            swapz["lower_inflight"]["max_aggregate_write_depth"],
        "source_sha": pair["source_sha"],
        "parent_trace_sha256": pair["parent_trace_sha256"],
        "arms": pair["arms"],
    }


def print_striped_table(rows):
    if not rows:
        return
    print("\nMulti-target stripe experiment — development only")
    print("  N independent existing K=1 swapz targets; aggregate QD, bandwidth "
          "and lower queue capacity are held fixed.")
    header = (f"{'scenario':<22} {'Q':>4} {'raw W':>9} {'swapz W':>9} "
              f"{'S/raw':>8} {'save B':>8} {'save req':>9} {'simW':>6}")
    print(header)
    print("-" * len(header))
    for row in rows:
        quality = row["performance_validity"]["status"]
        byte_save = (1 - row["swapz_lw_bytes"] / row["raw_lw_bytes"]
                     if row["raw_lw_bytes"] else 0.0)
        req_save = (1 - row["swapz_lw_reqs"] / row["raw_lw_reqs"]
                    if row["raw_lw_reqs"] else 0.0)
        ratio = row["swapz_w"] / row["raw_w"] if row["raw_w"] else 0.0
        print(f"{row['scenario']:<22} {quality:>4} {row['raw_w']:9.2f} "
              f"{row['swapz_w']:9.2f} {ratio:8.3f} {byte_save:8.1%} "
              f"{req_save:9.1%} "
              f"{row['swapz_simultaneous_write_devices']:6d}")

    usable = [row for row in rows
              if row["performance_validity"]["performance_usable"]]
    groups = {}
    for row in usable:
        key = (row["model"], row["workload"], row["stripes"])
        groups.setdefault(key, []).append(row)
    for model, workload in (("nvme5", "mixed"), ("sata", "mixed"),
                            ("fast", "write-q4"), ("fast", "write-q8")):
        counts = sorted(count for candidate, kind, count in groups
                        if candidate == model and kind == workload)
        if not counts:
            continue
        print(f"  {model} {workload} usable normalized swapz/raw WRITE ratios:")
        for count in counts:
            group = groups[(model, workload, count)]
            ratios = [row["swapz_w"] / row["raw_w"] for row in group
                      if row["raw_w"] > 0]
            simultaneous = max(
                row["swapz_simultaneous_write_devices"] for row in group)
            print(f"    N={count}: mean={statistics.mean(ratios):.3f} "
                  f"n={len(ratios)} observed simultaneous swapz lowers={simultaneous}")
        if 1 in counts and counts[-1] > 1:
            base = statistics.mean(
                row["swapz_w"] / row["raw_w"] for row in groups[(model, workload, 1)])
            top = statistics.mean(
                row["swapz_w"] / row["raw_w"]
                for row in groups[(model, workload, counts[-1])])
            print(f"    N=1 -> N={counts[-1]} normalized ratio shift: "
                  f"{(top / base - 1) * 100:+.1f}%")
    print("  A concurrency claim additionally requires observed simultaneous "
          "swapz lower WRITEs for N>1; absence in the sampler is inconclusive, "
          "not proof that overlap never occurred.")


def privileged(seconds, script, *arguments):
    prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
    return subprocess.run(
        [*prefix, "bash", "-c",
         'limit="$1"; shift; exec timeout --signal=TERM --kill-after=10s '
         '"${limit}s" bash "$@"', "swapz-fast-test", str(seconds), script,
         *arguments],
        cwd=ROOT, capture_output=True, text=True)


def parse_arms(output, candidate="swapz"):
    arms = {}
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("candidate") in ("off", candidate) and \
                obj.get("verdict") == "PASS":
            arms[obj["candidate"]] = obj
    return arms


def summarize(name, arms, seconds):
    off, swapz = arms["off"], arms["swapz"]

    def rate(arm, key):
        return (arm.get("throughput_mbps") or {}).get(key) or 0.0

    def lower(arm, key):
        return (arm.get("lower_io") or {}).get(key) or 0

    def ms(arm, key):
        value = arm.get(key)
        return value / 1e6 if isinstance(value, (int, float)) else 0.0

    kernel = swapz.get("kernel_write_path") or {}
    windows = kernel.get("windows") or 0
    logical_write_bytes = (
        (swapz.get("throughput_mbps") or {}).get("logical_write_bytes") or 0)
    swapz_lower_write_requests = lower(swapz, "lower_write_requests")
    logical_write_pages = logical_write_bytes / 4096.0
    return {
        "scenario": name,
        "raw_w": rate(off, "logical_write_mbps"),
        "swapz_w": rate(swapz, "logical_write_mbps"),
        "raw_r": rate(off, "logical_read_mbps"),
        "swapz_r": rate(swapz, "logical_read_mbps"),
        "raw_lw_bytes": lower(off, "lower_write_bytes"),
        "swapz_lw_bytes": lower(swapz, "lower_write_bytes"),
        "raw_lw_reqs": lower(off, "lower_write_requests"),
        "swapz_lw_reqs": swapz_lower_write_requests,
        "hand_records": kernel.get("work_conserving_hand_records") or 0,
        "hand_closes": kernel.get("work_conserving_hand_closes") or 0,
        "pages_per_lower_write": (
            logical_write_pages / swapz_lower_write_requests
            if swapz_lower_write_requests else 0.0),
        "raw_r_p99": ms(off, "read_p99_ns"),
        "swapz_r_p99": ms(swapz, "read_p99_ns"),
        "raw_w_p99": ms(off, "write_p99_ns"),
        "swapz_w_p99": ms(swapz, "write_p99_ns"),
        "windows": windows,
        "deadline": kernel.get("close_deadline") or 0,
        "idle_bound": kernel.get("idle_bound_closes") or 0,
        "service_us": (kernel.get("lower_write_service_ewma_ns") or 0) / 1e3,
        "block_service_us":
            (kernel.get("lower_write_block_service_ewma_ns") or 0) / 1e3,
        "idle_ms": (kernel.get("accepted_work_lower_idle_ns") or 0) / 1e6,
        "lw_busy_ms": (kernel.get("lower_write_wall_ns") or 0) / 1e6,
        "admit_samples": kernel.get("write_admit_worker_samples") or 0,
        "admit_ms": (kernel.get("write_admit_worker_wall_ns") or 0) / 1e6,
        "worker_wall_ms": (kernel.get("ordered_worker_wall_ns") or 0) / 1e6,
        "worker_cpu_ms": (kernel.get("ordered_worker_cpu_ns") or 0) / 1e6,
        "idle_unsched_ms":
            (kernel.get("accepted_work_lower_idle_worker_unscheduled_ns") or 0) / 1e6,
        "prepare_copy_ms": sum((kernel.get(key) or 0) for key in (
            "ordered_lz4_wall_ns", "prep_lz4_wall_ns",
            "ordered_write_copy_wall_ns", "prep_write_copy_wall_ns")) / 1e6,
        "order_plan_ms": sum((kernel.get(key) or 0) for key in (
            "window_sort_wall_ns", "engine_plan_wall_ns")) / 1e6,
        "pack_crc_ms": sum((kernel.get(key) or 0) for key in (
            "engine_pack_wall_ns", "ordered_crc_wall_ns", "prep_crc_wall_ns")) / 1e6,
        "publish_ms": (kernel.get("engine_publish_wall_ns") or 0) / 1e6,
        "post_lower_ms": (kernel.get("pipeline_post_lower_wall_ns") or 0) / 1e6,
        "sync4_windows": kernel.get("sync4_windows") or 0,
        "sync4_wall_ms": (kernel.get("sync4_wall_ns") or 0) / 1e6,
        "sync4_lower_ms": (kernel.get("sync4_lower_write_ns") or 0) / 1e6,
        "sync4_nonio_ms": (kernel.get("sync4_nonio_ns") or 0) / 1e6,
        "sync4_reissue_samples": kernel.get("sync4_reissue_samples") or 0,
        "sync4_reissue_ms": (kernel.get("sync4_reissue_gap_ns") or 0) / 1e6,
        "wall_s": swapz.get("seconds") or 0.0,
        "pair_s": seconds,
        "lane_gap": (
            {key: kernel[key] for key in HOST_CPU["LANE_GAP_COUNTER_FIELDS"]}
            if all(key in kernel for key in HOST_CPU["LANE_GAP_COUNTER_FIELDS"])
            else None),
        "host_busy_pct": (
            swapz.get("host_cpu", {}).get("busy_fraction", 0) * 100
            if isinstance(swapz.get("host_cpu", {}).get("busy_fraction"), (int, float))
            else None),
    }



def lane_gap_table_rows(rows):
    """Same ID178 descriptive attribution as make test; skip unmeasured rows."""
    phase_fields = HOST_CPU["LANE_GAP_PART_FIELDS"]
    successor_bins = HOST_CPU["LANE_SUCCESSOR_BIN_NAMES"]
    suffixes = HOST_CPU["LANE_DWELL_BIN_NAMES"]
    bounds = ("<=1us", "<=4us", "<=16us", "<=64us",
              "<=256us", "<=1ms", ">1ms")
    selected = ("sata-mixed", "nvme4-mixed", "nvme5-mixed", "fast-mixed")
    result = []
    for row in rows:
        if base_scenario(row.get("scenario", "")) not in selected:
            continue
        kernel = row.get("lane_gap")
        if not kernel:
            continue
        runs, total = kernel["lane_gap_runs"], kernel["lane_gap_wall_ns"]
        count = kernel["ack_dwell_deferred_count"]
        rank, cumulative, bound = (count * 99 + 99) // 100, 0, "n/a"
        for suffix, upper in zip(suffixes, bounds):
            cumulative += kernel[f"ack_dwell_deferred_{suffix}"]
            if count and cumulative >= rank:
                bound = upper
                break
        result.append({
            "scenario": row["scenario"],
            "runs": runs,
            "foreign_runs": kernel["lane_gap_foreign_runs"],
            "foreign_gap_ms": kernel["lane_gap_foreign_ns"] / 1e6,
            "unpaired_runs": kernel["lane_gap_unpaired_runs"],
            "gap_per_run_us": total / runs / 1000 if runs else None,
            "part_shares": {
                key: kernel[key] * 100 / total if total else None
                for key in phase_fields},
            "successor_admitted_distribution": [
                kernel[f"lane_successor_admitted_by_completion_{suffix}"]
                for suffix in successor_bins],
            "successor_owned_distribution": [
                kernel[f"lane_successor_owned_by_completion_{suffix}"]
                for suffix in successor_bins],
            "owner_read_ms": kernel["lane_gap_owner_read_ns"] / 1e6,
            "owner_reads": kernel["lane_gap_owner_reads"],
            "deferred_ack_p99_bin_bound": bound,
            "host_busy_pct": row.get("host_busy_pct"),
        })
    return result


def print_lane_gap_table(rows):
    """Single diagnostic table; never used for exclusion or selection."""
    if not rows:
        return
    phases = HOST_CPU["LANE_GAP_PART_FIELDS"]

    def fmt(value):
        return "n/a" if value is None else f"{value:.1f}"

    def distribution(values):
        return "/".join(str(value) for value in values)

    headers = ("scenario", "paired", "foreign", "unpaired", "gap/run us",
               "foreign ms", "wake", "publish", "no work", "unowned",
               "staged", "seal", "succ admit", "succ owned", "READ ms/#",
               "ACK p99 bin", "host busy")
    records = []
    for row in rows:
        records.append((
            row["scenario"], row["runs"], row["foreign_runs"],
            row["unpaired_runs"], fmt(row["gap_per_run_us"]),
            fmt(row["foreign_gap_ms"]),
            *(fmt(row["part_shares"][key]) + "%" if
              row["part_shares"][key] is not None else "n/a"
              for key in phases),
            distribution(row["successor_admitted_distribution"]),
            distribution(row["successor_owned_distribution"]),
            f"{row['owner_read_ms']:.3f}/{row['owner_reads']}",
            row["deferred_ack_p99_bin_bound"],
            "n/a" if row["host_busy_pct"] is None else
            fmt(row["host_busy_pct"]) + "%",
        ))
    widths = [max(len(headers[index]),
                  *(len(str(row[index])) for row in records))
              for index in range(len(headers))]
    print("\nSSD lower-lane gap attribution")
    print("  " + " | ".join(f"{name:<{widths[i]}}"
                           for i, name in enumerate(headers)))
    print("  " + "-+-".join("-" * widths[i] for i in range(len(headers))))
    for row in records:
        print("  " + " | ".join(f"{str(value):<{widths[i]}}"
                               for i, value in enumerate(row)))
    print("  Six phases are % of paired gaps; successor bins are "
          "0/1/2-3/4-7/8-15/16+; foreign gaps are whole-gap exclusions; "
          "READ ms/# overlaps the partition; ACK p99 is an inclusive bin "
          "bound (>1ms open-ended). Descriptive, not a gate.")



def pct(candidate, baseline):
    if not baseline:
        return "   n/a"
    return f"{(candidate / baseline - 1.0) * 100.0:+6.1f}%"


def print_table(rows):
    header = (f"{'scenario':<24} {'raw W':>7} {'swapz W':>8} {'dW':>7} "
              f"{'raw R':>6} {'swapz R':>7} {'lowW B':>7} {'reqs raw>swapz':>15} "
              f"{'R p99 raw>swapz':>16} {'W p99 raw>swapz':>16} "
              f"{'win':>5} {'hand':>4} {'hc':>4} {'pg/lw':>6} "
              f"{'dl':>4} {'ib':>4} {'idle':>6} {'lwbusy':>7} "
              f"{'svc':>6} {'blk':>6} {'wall':>6} {'quality':>8}")
    print(header)
    print("-" * len(header))
    for row in rows:
        if "error" in row:
            print(f"{row['scenario']:<24} ERROR: {row['error']}")
            continue
        bytes_ratio = (row["swapz_lw_bytes"] / row["raw_lw_bytes"]
                       if row["raw_lw_bytes"] else 0.0)
        reqs = f"{row['raw_lw_reqs']}>{row['swapz_lw_reqs']}"
        rp99 = f"{row['raw_r_p99']:.2f}>{row['swapz_r_p99']:.2f}"
        wp99 = f"{row['raw_w_p99']:.2f}>{row['swapz_w_p99']:.2f}"
        print(f"{row['scenario']:<24} {row['raw_w']:7.2f} {row['swapz_w']:8.2f} "
              f"{pct(row['swapz_w'], row['raw_w']):>7} {row['raw_r']:6.2f} "
              f"{row['swapz_r']:7.2f} {bytes_ratio:7.3f} {reqs:>15} "
              f"{rp99:>16} {wp99:>16} {row['windows']:5d} "
              f"{row['hand_records']:4d} {row['hand_closes']:4d} "
              f"{row['pages_per_lower_write']:6.2f} "
              f"{row['deadline']:4d} {row['idle_bound']:4d} {row['idle_ms']:6.1f} "
              f"{row['lw_busy_ms']:7.1f} {row['service_us']:6.0f} "
              f"{row['block_service_us']:6.0f} {row['wall_s']:6.3f} "
              f"{row['performance_validity']['status']:>8}")
        if row["performance_validity"]["reasons"]:
            print("  excluded: " + "; ".join(row["performance_validity"]["reasons"]))
    print("Legend: W/R useful MB/s; dW swapz vs raw useful WRITE; lowW B "
          "swapz/raw lower WRITE bytes (endurance proxy, lower is better);\n"
          "        reqs lower WRITE requests; p99 in ms; win swapz windows; "
          "hand selected hand width; hc early hand closes; pg/lw useful pages per "
          "lower WRITE;\n"
          "        dl/ib deadline and idle-bound closes; idle accepted-work lower-idle "
          "ms; lwbusy lower-WRITE service ms; svc/blk lower-WRITE run/block "
          "service EWMA us;\n"
          "        wall swapz measured seconds. "
          "Single unpaired observations; only make test qualifies.\n"
          "        quality: SCREENED passes the noise screen; NOISY/UNKNOWN "
          "excludes performance inference, not correctness.\n"
          "        200ms pre/post: busy >25%, CPU PSI >5%, steal >1%; "
          "timed steal >1% or raw-repeat spread >10% also excludes.\n"
          "        This heuristic can miss noise between samples; "
          "SCREENED does not establish an idle host.")


def print_profile(rows):
    """Compact ID114 summary; detailed per-run reports stay in latest.json."""
    groups = {}
    for row in rows:
        if "error" in row:
            continue
        groups.setdefault(row["scenario"].split("#", 1)[0], []).append(row)

    print("\nK=1 critical-path profile (SCREENED repeats only)")
    header = (f"{'scenario':<12} {'n':>3} {'admit us':>9} {'sched diag':>10} "
              f"{'idle sched':>10} {'prep/copy':>10} {'ord/plan':>9} "
              f"{'pack/crc':>9} {'lower':>9} {'publish':>9} {'post':>8}")
    print(header)
    print("-" * len(header))
    for name, group in groups.items():
        usable = [row for row in group
                  if row["performance_validity"]["performance_usable"]]
        if not usable:
            print(f"{name:<12} {0:>3} {'excluded':>9}")
            continue

        def mean(field):
            return statistics.mean(row[field] for row in usable)

        admit_samples = sum(row["admit_samples"] for row in usable)
        admit_ms = sum(row["admit_ms"] for row in usable)
        admit_us = admit_ms * 1000.0 / admit_samples if admit_samples else 0.0
        print(f"{name:<12} {len(usable):3d} {admit_us:9.2f} "
              f"{mean('worker_cpu_ms'):10.2f} {mean('idle_unsched_ms'):10.2f} "
              f"{mean('prepare_copy_ms'):10.2f} {mean('order_plan_ms'):9.2f} "
              f"{mean('pack_crc_ms'):9.2f} {mean('lw_busy_ms'):9.2f} "
              f"{mean('publish_ms'):9.2f} {mean('post_lower_ms'):8.2f}")
    print("  admit us = accepted WRITE -> first ordered-worker ownership; "
          "idle sched = accepted lower-idle after a wake until worker entry.")
    print("  sched diag = scheduler-updated runtime deltas; pending execution may be "
          "missed or earlier execution charged at callback boundaries.")
    print("  ACK helper has no dedicated CPU measurement. Phase rows are partial wall time, can overlap and include preemption; "
          "neither these rows nor sched diag establishes total worker CPU.")

    sync_groups = []
    for name, group in groups.items():
        usable = [row for row in group
                  if row["performance_validity"]["performance_usable"]]
        windows = sum(row["sync4_windows"] for row in usable)
        if windows:
            sync_groups.append((name, usable, windows))
    if sync_groups:
        print("\nSynchronous four-record cycle")
        header = (f"{'scenario':<12} {'win':>6} {'cycle us':>10} "
                  f"{'lower us':>10} {'nonio us':>10} {'reissue us':>11}")
        print(header)
        print("-" * len(header))
        for name, usable, windows in sync_groups:
            wall = sum(row["sync4_wall_ms"] for row in usable)
            lower = sum(row["sync4_lower_ms"] for row in usable)
            nonio = sum(row["sync4_nonio_ms"] for row in usable)
            samples = sum(row["sync4_reissue_samples"] for row in usable)
            gaps = sum(row["sync4_reissue_ms"] for row in usable)
            print(f"{name:<12} {windows:6d} {wall * 1000.0 / windows:10.2f} "
                  f"{lower * 1000.0 / windows:10.2f} "
                  f"{nonio * 1000.0 / windows:10.2f} "
                  f"{(gaps * 1000.0 / samples if samples else 0.0):11.2f}")
        print("  reissue = previous successful synchronous four-record completion "
              "to the next successful four-record commit start.")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    resume_setting = os.environ.get("RESUME", "0")
    if resume_setting not in ("0", "1"):
        parser.error("RESUME must be 0 or 1")
    parser.add_argument("--resume", action="store_true",
                        default=resume_setting == "1",
                        help="reuse only matching private fast-test checkpoints")
    parser.add_argument("--scenarios", default=os.environ.get("SCENARIOS", ""))
    parser.add_argument("--repeat", type=int,
                        default=int(os.environ.get("REPEAT", "3") or 3))
    parser.add_argument("--content", choices=CONTENT_PROFILES,
                        default=os.environ.get("CONTENT", "medium"))
    parser.add_argument("--anon-page-sample",
                        default=os.environ.get("ANON_PAGE_SAMPLE"),
                        help="private regular file of owner-supplied 4 KiB pages; used only with representative content")
    parser.add_argument("--calibration", choices=("none", "linear"),
                        default=os.environ.get("CALIBRATION", "none"))
    parser.add_argument("--stripe-counts",
                        default=os.environ.get("STRIPE_COUNTS", "1,2,4"))
    parser.add_argument("--stripe-repeat", type=int,
                        default=int(os.environ.get("STRIPE_REPEAT", "5") or 5))
    parser.add_argument("--submitter-prepare", type=int, choices=(0, 1),
                        default=int(os.environ.get("SUBMITTER_PREPARE", "1")))
    parser.add_argument("--host-load-profile",
                        choices=("uncontrolled", "quiet-intended", "browser-video-144p"),
                        default=os.environ.get("HOST_LOAD_PROFILE", "uncontrolled"))
    parser.add_argument("--hand-records", type=int, choices=(8, 16, 64),
                        default=int(os.environ.get("HAND_RECORDS", "8")))
    parser.add_argument("--mixed-ops", type=int, choices=MIXED_MEASURE_OPS,
                        default=int(os.environ.get("MIXED_OPS", "16384")))
    args = parser.parse_args()
    calibration = args.calibration == "linear"
    candidate = "linear" if calibration else "swapz"
    scenarios = [item for item in re.split(r"[,\s]+", args.scenarios) if item] \
        or list(DEFAULT_SCENARIOS)
    stripe_counts = parse_stripe_counts(args.stripe_counts)
    scenario_specs = [(name, striped_scenario(name)) for name in scenarios]
    striped_specs = [spec for _, spec in scenario_specs if spec]
    ordinary_scenarios = [name for name, spec in scenario_specs if not spec]
    if not 1 <= args.repeat <= 10:
        parser.error("REPEAT must be 1..10")
    if args.content == "representative" and not args.anon_page_sample:
        parser.error("CONTENT=representative requires --anon-page-sample or ANON_PAGE_SAMPLE")
    if args.content != "representative" and args.anon_page_sample:
        parser.error("--anon-page-sample requires CONTENT=representative")
    if not 1 <= args.stripe_repeat <= 10:
        parser.error("STRIPE_REPEAT must be 1..10")
    if len(striped_specs) != len(set(striped_specs)):
        parser.error("each striped model/workload may be selected only once")
    if calibration and striped_specs:
        parser.error("striped scenarios cannot use linear calibration")
    if not args.submitter_prepare and (calibration or striped_specs):
        parser.error("SUBMITTER_PREPARE=0 requires ordinary swapz fast_test scenarios")
    if args.hand_records != 8 and (calibration or striped_specs):
        parser.error("HAND_RECORDS requires an ordinary swapz fast_test scenario")
    if args.mixed_ops != 16384 and (calibration or striped_specs or any(
            name.partition("-")[2] not in
            ("mixed", "mixed-lanes", "mixed-lanes-waves")
            for name in ordinary_scenarios)):
        parser.error("MIXED_OPS=65536 requires ordinary mixed-only scenarios")
    for name in ordinary_scenarios:
        scenario_arguments(name, "/dev/null",
                           submitter_prepare=args.submitter_prepare,
                           hand_records=args.hand_records,
                           private_fixture=args.content == "representative")

    if os.geteuid() != 0 and subprocess.run(
            ["sudo", "-n", "true"], capture_output=True).returncode:
        print("BLOCKED: make fast_test needs noninteractive sudo for owned null_blk",
              file=sys.stderr)
        return 2
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "tests"],
                           cwd=ROOT, capture_output=True, text=True).stdout.strip()
    print(f"swapz fast_test (development only; not qualification) "
          f"content={args.content} submitter_prepare={args.submitter_prepare} "
          f"hand_records={args.hand_records} "
          f"mixed_ops={args.mixed_ops} "
          f"host_load={args.host_load_profile} "
          f"resume={'enabled' if args.resume else 'disabled'} "
          f"HEAD={head[:12]}{' +dirty' if dirty else ''}")
    nonce = os.environ.get("SWAPZ_DEVELOPMENT_ADMISSION_NONCE")
    if nonce is not None and not re.fullmatch(r"[0-9a-f]{32}", nonce):
        print("BLOCKED: invalid development admission nonce", file=sys.stderr)
        return 2
    evidence = {
        "schema": "swapz-fast-test-development-evidence-v1",
        "head": head,
        "dirty": bool(dirty),
        "nonce": nonce,
        "native_status": "PENDING",
        "loaded_preflight": {"status": "NOT_RUN"},
        "fast_test_status": "IN_PROGRESS",
        "resume": {"requested": args.resume, "native_reused": False},
    }
    write_development_evidence(evidence)
    started = time.monotonic()
    build()
    try:
        input_sha256 = resume_input_fingerprint()
        host_fingerprint = resume_host_fingerprint()
    except (OSError, subprocess.CalledProcessError, ValueError):
        input_sha256 = None
        host_fingerprint = None
    checkpoint = checkpoint_state(read_resume_checkpoint())
    checkpoint_matches_current = bool(
        input_sha256 and host_fingerprint and
        checkpoint_matches_native(checkpoint, input_sha256, host_fingerprint))
    native_reused = args.resume and checkpoint_matches_current
    new_native_checkpoint = None
    if native_reused:
        evidence["resume"]["native_reused"] = True
        evidence["resume"]["native_checkpoint_head"] = (
            checkpoint["native"].get("measurement_head"))
        print("  build + native/replay contract checks: PASS "
              "(matching checkpoint reused; product build refreshed)", flush=True)
    else:
        if (not args.resume and checkpoint_matches_current and
                not invalidate_resume_checkpoint()):
            evidence["native_status"] = "BLOCKED"
            evidence["fast_test_status"] = "BLOCKED"
            evidence["blocker"] = "matching_resume_checkpoint_could_not_be_invalidated"
            write_development_evidence(evidence)
            print("BLOCKED phase=native_replay expected=fresh_checkpoint_invalidated "
                  "observed=checkpoint_removal_failed; checks=not_run",
                  file=sys.stderr, flush=True)
            return 2
        if args.resume:
            print("  resume: no matching native checkpoint; running native/replay checks",
                  flush=True)
        build_native_checks()
        if input_sha256 and host_fingerprint:
            artifacts_sha256 = native_artifact_fingerprint()
            if artifacts_sha256:
                new_native_checkpoint = {
                    "status": "PASS",
                    "input_sha256": input_sha256,
                    "host": host_fingerprint,
                    "artifacts_sha256": artifacts_sha256,
                    "measurement_head": head,
                    "completed_at_ns": time.time_ns(),
                }
    try:
        head_after = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, check=True).stdout.strip()
        input_after = resume_input_fingerprint() if input_sha256 else None
    except (OSError, subprocess.CalledProcessError, ValueError):
        head_after = None
        input_after = None
    if (head_after != head or
            (input_sha256 and input_after != input_sha256)):
        evidence["native_status"] = "BLOCKED"
        evidence["fast_test_status"] = "BLOCKED"
        evidence["blocker"] = "source_changed_during_native_checks"
        write_development_evidence(evidence)
        print("BLOCKED phase=native_replay expected=stable_source_inputs "
              "observed=source_changed_or_unreadable; loaded_preflight=not_run",
              file=sys.stderr, flush=True)
        return 2
    if new_native_checkpoint:
        checkpoint["native"] = new_native_checkpoint
        if not write_resume_checkpoint(checkpoint):
            print("  resume: private checkpoint unavailable; "
                  "successful checks remain usable for this invocation",
                  file=sys.stderr, flush=True)
    evidence["native_status"] = "PASS"
    evidence["resume"]["input_sha256"] = input_sha256
    write_development_evidence(evidence)
    if not native_reused:
        print(f"  build + native/replay contract checks: PASS "
              f"({time.monotonic() - started:.1f}s)", flush=True)
    preflight = privileged(60, PREFLIGHT)
    if preflight.returncode:
        diagnostic = preflight.stdout + preflight.stderr
        print(diagnostic, file=sys.stderr)
        evidence["loaded_preflight"] = loaded_preflight_diagnostic(diagnostic)
        evidence["fast_test_status"] = "BLOCKED"
        write_development_evidence(evidence)
        print("BLOCKED: loaded preflight failed", file=sys.stderr)
        return 2
    evidence["loaded_preflight"] = {"status": "PASS", "check": "complete",
                                    "errno": "0"}
    write_development_evidence(evidence)
    try:
        plan = prepare_plan(
            args.content, ("nvme5", "mixed") in striped_specs or
            ("sata", "mixed") in striped_specs,
            tuple(qd for qd in STRIPED_WRITE_QDS
                  if ("fast", f"write-q{qd}") in striped_specs),
            mixed_ops=args.mixed_ops, sample_path=args.anon_page_sample)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        evidence["fast_test_status"] = "BLOCKED"
        evidence["blocker"] = "content_plan"
        write_development_evidence(evidence)
        print(f"BLOCKED: content plan preparation failed: {error}",
              file=sys.stderr)
        return 2
    try:
        prepare_striped_workload_plans(plan, stripe_counts, striped_specs)
        fixture = json.loads((plan / "fixture.json").read_text())
        OUT_DIR.mkdir(parents=True, exist_ok=True)
    except BaseException:
        shutil.rmtree(plan, ignore_errors=True)
        raise
    rows, raw_reports = [], []
    status = 0
    try:
        for name in ordinary_scenarios:
            for attempt in range(args.repeat):
                candidate_first = bool(calibration and attempt % 2)
                label = name if args.repeat == 1 else f"{name}#{attempt + 1}"
                quiet_before = quiet_host_sample()
                begin = time.monotonic()
                proc = privileged(720, PAIR, "--validated-source", head,
                                  *scenario_arguments(name, plan, calibration,
                                                      candidate_first,
                                                      args.submitter_prepare,
                                                      args.hand_records,
                                                      args.content == "representative"))
                elapsed = time.monotonic() - begin
                quiet_after = quiet_host_sample()
                arms = parse_arms(proc.stdout, candidate)
                if proc.returncode or set(arms) != {"off", candidate}:
                    status = 1
                    tail = (proc.stdout + proc.stderr).strip().splitlines()[-12:]
                    rows.append({"scenario": label,
                                 "error": f"pair failed rc={proc.returncode}"})
                    print(f"  {label}: FAIL ({elapsed:.1f}s)\n    " +
                          "\n    ".join(tail), flush=True)
                    continue
                if calibration:
                    row = {"scenario": label, "pair_s": elapsed,
                           "replay_order": "linear-first" if attempt % 2 else "raw-first",
                           "raw_w": arms["off"]["throughput_mbps"]["logical_write_mbps"],
                           "linear_w": arms["linear"]["throughput_mbps"]["logical_write_mbps"]}
                else:
                    row = summarize(label, arms, elapsed)
                row["performance_validity"] = performance_validity(
                    quiet_before, quiet_after, arms)
                rows.append(row)
                raw_reports.append({"scenario": label, "arms": arms})
                measured = row["linear_w"] if calibration else row["swapz_w"]
                print(f"  {label}: raw W {row['raw_w']:.2f} {candidate} W "
                      f"{measured:.2f} ({pct(measured, row['raw_w']).strip()}) "
                      f"[{elapsed:.1f}s]", flush=True)

        striped_rows = []
        for model, workload in striped_specs:
            for round_index in range(args.stripe_repeat):
                offset = round_index % len(stripe_counts)
                rotated = stripe_counts[offset:] + stripe_counts[:offset]
                for stripe_count in rotated:
                    scenario_suffix = "stripes" if workload == "mixed" else (
                        "stripes-w" + workload[-1])
                    label = (f"{model}-{scenario_suffix}-n{stripe_count}"
                             f"#{round_index + 1}")
                    quiet_before = quiet_host_sample()
                    begin = time.monotonic()
                    arguments = [
                        "--validated-source", head, "--run-owned-striped",
                        "--model", model, "--stripes", str(stripe_count),
                        "--shared-plan", str(plan),
                    ]
                    if args.content == "representative":
                        arguments.append("--private-fixture")
                    arguments += [
                        "--workload", workload,
                    ]
                    if round_index % 2:
                        arguments.append("--swapz-first")
                    proc = privileged(720, STRIPED_PAIR, *arguments)
                    elapsed = time.monotonic() - begin
                    quiet_after = quiet_host_sample()
                    if proc.returncode:
                        status = 1
                        tail = (proc.stdout + proc.stderr).strip().splitlines()[-12:]
                        striped_rows.append({
                            "scenario": label,
                            "error": f"striped pair failed rc={proc.returncode}",
                        })
                        print(f"  {label}: FAIL ({elapsed:.1f}s)\n    " +
                              "\n    ".join(tail), flush=True)
                        continue
                    try:
                        pair = parse_striped_pair(proc.stdout)
                        if (pair.get("model") != model or
                                pair.get("workload") != workload or
                                pair.get("aggregate_model", {}).get("offered_qd") !=
                                (32 if workload == "mixed" else int(workload[-1])) or
                                pair.get("stripes") != stripe_count):
                            raise ValueError("striped helper result identity mismatch")
                        row = summarize_striped(label, pair, elapsed)
                    except (KeyError, TypeError, ValueError) as error:
                        status = 1
                        striped_rows.append({
                            "scenario": label,
                            "error": f"invalid striped result: {error}",
                        })
                        print(f"  {label}: FAIL invalid result ({error})", flush=True)
                        continue
                    row["performance_validity"] = performance_validity(
                        quiet_before, quiet_after, pair["arms"])
                    striped_rows.append(row)
                    print(f"  {label}: raw W {row['raw_w']:.2f} swapz W "
                          f"{row['swapz_w']:.2f} "
                          f"({pct(row['swapz_w'], row['raw_w']).strip()}) "
                          f"simultaneous-lowers="
                          f"{row['swapz_simultaneous_write_devices']} "
                          f"[{elapsed:.1f}s]", flush=True)
    finally:
        shutil.rmtree(plan, ignore_errors=True)
    reject_raw_drift(rows)
    if striped_specs:
        reject_raw_drift(striped_rows)
    # Derived summaries are identical in the JSON and console paths.
    lane_gap_rows = lane_gap_table_rows(rows)
    result_name = "latest-calibration.json" if calibration else "latest.json"
    (OUT_DIR / result_name).write_text(
        json.dumps({"head": head, "dirty": bool(dirty),
                    "input_fingerprint_sha256": input_sha256,
                    "resume": {
                        "requested": args.resume,
                        "native_contracts_reused": native_reused,
                    },
                    "calibration": args.calibration,
                    # CALIBRATION=linear replays a DM-linear target: no swapz
                    # module or compression stack is involved in that file.
                    "compression_policy": ("none-dm-linear" if calibration
                                           else "delta64-shuf8-lz4"),
                    "delta64_rescue": None if calibration else 1,
                    "submitter_prepare": args.submitter_prepare,
                    "hand_records": args.hand_records,
                    "mixed_measure_ops": args.mixed_ops,
                    "host_load_profile": args.host_load_profile,
                    "content_profile": args.content, "fixture": fixture, "rows": rows,
                    "lane_gap_attribution": lane_gap_rows,
                    "reports": raw_reports,
                    "striped_target_experiment": {
                        "scope": "DEVELOPMENT_ONLY_MULTI_TARGET_K1_NO_KERNEL_C_CHANGE",
                        "counts": list(stripe_counts),
                        "repeats": args.stripe_repeat,
                        "models": sorted(set(model for model, _ in striped_specs)),
                        "model_workloads": [
                            {"model": model, "workload": workload}
                            for model, workload in striped_specs],
                        "rows": striped_rows if striped_specs else [],
                    }}, sort_keys=True) + "\n")
    print()
    if calibration:
        print("DM-linear calibration only: same-host synthetic reference; "
              "not an unavoidable DM overhead budget.")
        for row in rows:
            print(json.dumps(row, sort_keys=True))
    else:
        print_table(rows)
        print_lane_gap_table(lane_gap_rows)
        print_profile(rows)
        print_striped_table(striped_rows if striped_specs else [])
    print(f"\n  Detailed telemetry: {(OUT_DIR / result_name).relative_to(ROOT)} "
          f"(total {time.monotonic() - started:.0f}s)")
    evidence["fast_test_status"] = "PASS" if status == 0 else "FAIL"
    evidence["result_file"] = result_name
    write_development_evidence(evidence)
    return status


if __name__ == "__main__":
    sys.exit(main())
