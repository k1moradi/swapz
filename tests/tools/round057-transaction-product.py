#!/usr/bin/env python3
"""Round057 source-bound REAL production raw/flush authority, disabled import.

Compiles src/kernel/authority.c + codec.c, not a cloned authority algorithm.
The C callbacks are rootless host MODELS: no DM/PHY/native BIO admission.
"""
from pathlib import Path
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
KERNEL = ROOT / "src/kernel"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round057-transaction-product.c"
MUTANTS = (
    ("fua_error_ignored", "flush-qual.h",
     "return issue_flush ? issue_flush(opaque) : -EINVAL;",
     "return issue_flush ? (issue_flush(opaque), 0) : -EINVAL;",
     "flush_failure"),
    ("failed_write_flushes", "flush-qual.h",
     "if (write_error || !needs_fua)",
     "if (write_error && !needs_fua)",
     "failed_write_skips_flush"),
    ("short_publish", "authority.c",
     "if (io_error || completed_blocks != 1) {",
     "if (io_error && completed_blocks != 1) {",
     "short_lower_write"),
    ("raw_crc_skipped", "authority.c",
     "if (swapz_crc32c_bytes(raw_page, SWAPZ_BLOCK_BYTES) != m->raw_crc32c)",
     "if (0 && swapz_crc32c_bytes(raw_page, SWAPZ_BLOCK_BYTES) != m->raw_crc32c)",
     "raw_crc_and_exact_page"),
    ("fake_live_authorization", "zswap-import-admission.h",
     "\t(void)transaction;\n\treturn -EOPNOTSUPP;\n}\n",
     "\t(void)transaction;\n\treturn 0;\n}\n",
     "live_import_refusal"),
)


def require(source, expected, label):
    if expected not in source:
        raise RuntimeError("source drift: " + label)


def source_boundaries():
    dm = (KERNEL / "dm-target.c").read_text()
    raw = dm.split("static int swapz_raw_write(", 1)
    if len(raw) != 2:
        raise RuntimeError("source drift: real raw writer")
    raw = raw[1].split("static void swapz_refresh_accepted_followup(", 1)[0]
    for anchor in ("swapz_copy_bio_accounted(bio, ctx->input_page, false",
                   "swapz_stage(&ctx->authority",
                   "swapz_lower_write(ctx, transaction->start_block",
                   "swapz_finish_raw(&ctx->authority",
                   "swapz_preserve_first_error(error, finish_error)"):
        require(raw, anchor, "real raw writer " + anchor)
    if not (raw.index("swapz_copy_bio_accounted(bio, ctx->input_page, false") <
            raw.index("swapz_stage(&ctx->authority") <
            raw.index("swapz_lower_write(ctx, transaction->start_block") <
            raw.index("swapz_finish_raw(&ctx->authority")):
        raise RuntimeError("source drift: raw owner ordering")

    lower = dm.split("static int swapz_lower_write(", 1)[1].split(
        "static int swapz_lower_write_run(", 1)[0]
    for anchor in ("swapz_lower(ctx, REQ_OP_WRITE", "swapz_write_flush_before_publish(",
                   "if (!error)", "*completed = blocks;"):
        require(lower, anchor, "real lower write " + anchor)
    if lower.index("swapz_lower(ctx, REQ_OP_WRITE") > lower.index(
            "swapz_write_flush_before_publish("):
        raise RuntimeError("source drift: FUA before lower write")

    gc = dm.split("static int swapz_gc_move_raw(", 1)[1].split(
        "static int swapz_gc_choose_victim(", 1)[0]
    for anchor in ("swapz_lower_read(", "swapz_verify_raw(",
                   "swapz_stage(", "swapz_lower_write(",
                   "swapz_finish_raw("):
        require(gc, anchor, "real raw GC " + anchor)
    if not (gc.index("swapz_lower_read(") < gc.index("swapz_verify_raw(") <
            gc.index("swapz_stage(") < gc.index("swapz_lower_write(") <
            gc.index("swapz_finish_raw(")):
        raise RuntimeError("source drift: raw GC ordering")

    mapping = dm.split("static int swapz_map(", 1)[1].split(
        "static void swapz_drain(", 1)[0]
    for anchor in ("sector % SWAPZ_SECTORS || count != SWAPZ_SECTORS",
                   "return DM_MAPIO_KILL;", "entry = dm_per_bio_data("):
        require(mapping, anchor, "real target map " + anchor)
    require(dm, "if (upper_bio->bi_flags & (1U << BIO_CLONED))\n\t\treturn -EOPNOTSUPP;",
            "current cloned BIO refusal")
    require(dm, "#if 0 /* SWAPZ_ROUND023_COMPRESSED_DM_IMPORT_DISABLED_NO_AUTHENTIC_CARRIER */",
            "disabled import callsite")
    require(dm, "#define SWAPZ_SECTORS (SWAPZ_BLOCK_BYTES >> SECTOR_SHIFT)",
            "eight 512B target-relative sectors")
    require(dm, "return ((sector_t)ctx->data_start_block + data_block) * SWAPZ_SECTORS;",
            "protected first physical 4096")
    drain = dm.split("static void swapz_drain(", 1)[1].split(
        "static void swapz_resume(", 1)[0]
    for anchor in ("WRITE_ONCE(ctx->accepting, false);", "swapz_has_inflight(ctx)",
                   "drain_workqueue(ctx->workqueue);"):
        require(drain, anchor, "dtr/swapoff drain " + anchor)
    require((KERNEL / "zswap-import-admission.h").read_text(),
            "#define SWAPZ_ZSWAP_IMPORT_ADMISSION_ACTIVE 0U",
            "imported live admission disabled")
    require((KERNEL / "zswap-import-codec.h").read_text(),
            "#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U", "imported codec disabled")
    require((KERNEL / "codec.h").read_text(),
            "#define SWAPZ_CODEC_METADATA_ON_MEDIA 0U", "volatile records")


def execute(command, *, stdin=None):
    return subprocess.run(
        command, input=stdin, text=True, capture_output=True, check=False, timeout=45,
        env={**os.environ, "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})


# Fail-only, source-bound diagnostic. Compiler stderr may include arbitrary
# runner paths, generated source, toolchain detail, credentials or huge output.
# Keep complete bounded diagnostics in a mode-0600 private repository-local log;
# print only the first recognizable source error with a repository-relative
# path and a bounded, sanitized message. No raw child stderr on the console.
SOURCE_DIAGNOSTIC = re.compile(
    r"^(?P<path>[^:\r\n]+?):(?P<line>[0-9]+)(?::(?P<column>[0-9]+))?:"
    r"\s*(?P<severity>fatal error|error):\s*(?P<detail>[^\r\n]+)$"
)


def compiler_first_error(stderr: str) -> str:
    for line in stderr.splitlines():
        match = SOURCE_DIAGNOSTIC.match(line.strip())
        if match is None:
            continue
        original_path = Path(match.group("path"))
        if original_path.is_absolute():
            try:
                source_path = original_path.relative_to(ROOT).as_posix()
            except ValueError:
                source_path = "external-source"
        else:
            source_path = original_path.as_posix()
        if (not source_path or source_path.startswith("../") or
                not re.fullmatch(r"[A-Za-z0-9_.\-/]+", source_path)):
            source_path = "external-source"
        detail = match.group("detail")
        # Never print absolute runner paths or arbitrary sensitive assignments.
        detail = re.sub(r"(?<![A-Za-z0-9_.-])/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+",
                        "[external-path]", detail)
        detail = re.sub(
            r"(?i)\b(?:token|secret|password|authorization|private_key)"
            r"\s*[:=]\s*\S+", "[redacted]", detail)
        detail = re.sub(r"[^\x20-\x7e]", "?", detail)[:150]
        return (source_path + ":" + match.group("line") +
                (":" + match.group("column") if match.group("column") else "") +
                " " + match.group("severity") + ": " + detail)
    return "compiler failed without a recognizable source-bound diagnostic"


def retain_private_compiler_error(stderr: str, compiler: str) -> str:
    details_dir = ROOT / ".private"
    details_dir.mkdir(mode=0o700, exist_ok=True)
    # Existing private directories are owned by the current test user;
    # never expose compiler stderr to a wider repository or default umask.
    details_dir.chmod(0o700)
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "-", compiler)[:32]
    with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=details_dir,
            prefix="round057-transaction-" + safe_name + "-",
            suffix=".log", delete=False) as details:
        details.write(stderr[:65536])
        details.flush()
        os.fchmod(details.fileno(), stat.S_IRUSR | stat.S_IWUSR)
        saved_path = Path(details.name)
    return saved_path.relative_to(ROOT).as_posix()


def build(compiler, workspace, binary, *, altered_source=None, altered_header=None):
    sources = [
        FIXTURE,
        altered_source if altered_source else KERNEL / "authority.c",
        KERNEL / "codec.c",
    ]
    include_options = ["-I", str(KERNEL)]
    if altered_header:
        include_options = ["-I", str(altered_header), *include_options]
    command = [
        compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
        "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-fno-pie",
        "-no-pie", *include_options,
        *(str(source) for source in sources), "-o", str(binary), "-llz4", "-lcrypto",
    ]
    result = execute(command)
    if result.returncode:
        private_path = retain_private_compiler_error(result.stderr, workspace)
        raise RuntimeError("compiler failure " + workspace + " exit=" +
                           str(result.returncode) + ": " +
                           compiler_first_error(result.stderr) +
                           " evidence=" + private_path)


def main():
    source_boundaries()
    expected = None
    with tempfile.TemporaryDirectory(prefix="swapz-round057-transaction-") as work:
        location = Path(work)
        for compiler_name in ("gcc", "clang"):
            compiler = shutil.which(compiler_name)
            if not compiler:
                raise RuntimeError("required compiler missing " + compiler_name)
            binary = location / "spine"
            build(compiler, compiler_name, binary)
            baseline = execute([str(binary)])
            if baseline.returncode or baseline.stderr or not re.fullmatch(
                    r"PASS product_raw_authority=7 map_bytes=20 "
                    r"import_record_bytes=\d+ descriptor_limit=8 staging_limit=2 "
                    r"NOT_AUTH=1 PHASE_A=BLOCKED\n", baseline.stdout):
                raise RuntimeError(compiler_name + " baseline: " +
                                   (baseline.stderr or baseline.stdout)[:250])
            if expected is not None and expected != baseline.stdout:
                raise RuntimeError("different compiler ABI/behavior")
            expected = baseline.stdout
            print("PASS " + compiler_name + " actual linked production " +
                  baseline.stdout.strip())
            for index, (name, path, original, replacement, case) in enumerate(MUTANTS):
                product = (KERNEL / path).read_text()
                if product.count(original) != 1:
                    raise RuntimeError("non-unique genuine-source mutant " + name)
                altered = product.replace(original, replacement, 1)
                copy = location / ("mutant-" + str(index))
                copy.mkdir()
                source_override = None
                header_override = None
                target = copy / Path(path).name
                target.write_text(altered)
                if path.endswith(".c"):
                    source_override = target
                else:
                    header_override = copy
                build(compiler, name, binary, altered_source=source_override,
                      altered_header=header_override)
                observed = execute([str(binary), case])
                if (observed.returncode != 1 or observed.stdout or
                        observed.stderr != "FIRST_ERROR " + case + "\n"):
                    raise RuntimeError(compiler_name + " mutation " + name +
                                       " not semantically rejected: exit=" +
                                       str(observed.returncode) + " first=" +
                                       observed.stderr[:160])
            print("PASS " + compiler_name + " actual-source semantic mutants=5")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print("FIRST_ERROR round057-transaction: " + str(error)[:350],
              file=sys.stderr)
        sys.exit(1)
