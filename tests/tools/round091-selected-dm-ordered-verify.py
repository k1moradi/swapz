#!/usr/bin/env python3
"""Actual extracted ordered transaction and typed READ; frozen product + Linux.
Synthetic selected provenance, RAM lower callbacks; never native DM or AUTH.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE = "2499405464110e6a97f054db5527de54b8aafb3a"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
SHARED_FIXTURE = "tests/runtime/native/fixtures/round089-shared-original-storage.c"
ORDERED_FIXTURE = "tests/runtime/native/fixtures/round091-selected-dm-ordered.c"
OLD_BASE = "e8a3f08000f81dcc3b1bda74b407b9e523ed3bab"
STAGE_PATHS = ("src/kernel", "tests/tools/round085-original-decode-verify.py",
               "tests/tools/round080-original-lzo1x-independent-decoder-verify.py",
               SHARED_FIXTURE)
PINS = {
    "src/kernel/zswap-original-ticket.h": "0630f9e4fad26458ed0778ca6ae040150e28f078",
    "src/kernel/zswap-original-ticket.c": "7ba56c5ee602853c8d0717f23aad9efc69d111ea",
    "src/kernel/zswap-original-storage.h": "38924c3931419a93a7783de9ba622024a5e2e65c",
    "src/kernel/zswap-original-storage.c": "1f9030030f5d0fb3b06d0b0a159dd8aa6818f8dd",
    "src/kernel/zswap-original-decoder-bridge.h": "507b25debe0ca7b30b57ed6a350dab4868dced51",
    "src/kernel/zswap-original-decoder-bridge.c": "9324a581e27bad62d4e2d9c90192f6ad8b96faca",
    "src/kernel/authority.h": "c63741157141b2aa9a15de1e9182e27435fc0a3e",
    "src/kernel/authority.c": "14fe52cf4cf28f18568d3bf2b6ced449c9c182a3",
    "src/kernel/engine.c": "e7c50c3e78449157439fba9c69e5d23b1c317f4e",
    "tests/runtime/native/fixtures/round089-shared-original-storage.c": "95cee696fe99b3438f387ff1bf45cb4634f70fab",
}
MUTANTS = (
    ("ignore_claim_refusal", "if (try_claim(context, credit)) {",
     "if (try_claim(context, credit) == 12345) {"),
    ("leak_canceled_credit", "*error = swapz_shared_storage_cancel_reserved(storage, credit);",
     "*error = credit ? 0 : -EINVAL;"),
    ("fallback_after_commit_failure",
     "*error = swapz_shared_storage_commit_reserved(storage, credit);\n\treturn true;",
     "*error = swapz_shared_storage_commit_reserved(storage, credit);\n\treturn *error == 0;"),
    ("leak_read_pin", "release_error = swapz_shared_original_put(authority, pin);",
     "release_error = pin ? 0 : -EINVAL;"),
)


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "--no-replace-objects", *args], cwd=ROOT)


def verify_stage(stage):
    # Every archived file, including transitive quoted includes and helpers.
    entries = git("ls-tree", "-r", "-z", BASE, "--", *STAGE_PATHS).split(b"\0")
    expected = {}
    for entry in filter(None, entries):
        metadata, name = entry.split(b"\t", 1)
        mode, kind, digest = metadata.decode().split()
        require(kind == "blob" and mode in ("100644", "100755"), "nonregular staged input")
        expected[name.decode()] = digest
    actual = {str(path.relative_to(stage)) for path in stage.rglob("*") if path.is_file()}
    require(actual == set(expected), "staged file inventory")
    for path, digest in expected.items():
        require(git_blob((stage / path).read_bytes()) == digest, "staged blob " + path)
    return len(expected)


def verify_fixture(path, expected):
    require(git_blob(path.read_bytes()) == expected, "mixed-version fixture rejected")


def isolate_fixture(stage, work):
    # Compile from scratch, not the current source-relative include directory.
    fixture = work / "ordered-fixture.c"
    current = git("show", "HEAD:" + ORDERED_FIXTURE)
    require(current == (ROOT / ORDERED_FIXTURE).read_bytes(), "current ordered fixture drift")
    fixture.write_bytes(current)
    shared = work / "frozen-round089-shared-original-storage.c"
    shared.write_bytes((stage / SHARED_FIXTURE).read_bytes())
    verify_fixture(shared, PINS[SHARED_FIXTURE])
    return fixture, shared


def fragment(source, name):
    begin, end = f"/* ROUND091_{name}_BEGIN */", f"/* ROUND091_{name}_END */"
    require(source.count(begin) == source.count(end) == 1, "fragment " + name)
    return source.split(begin, 1)[1].split(end, 1)[0]


# Keep byte offsets while masking comments and literals. A malformed token
# or function boundary is a failed audit, not a shorter accepted fragment.
C_TOKEN = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'')
DEFINITION = re.compile(r"(?m)^static (?:bool|int|void) (\w+)\(")


def code_only(source):
    masked = C_TOKEN.sub(lambda match: re.sub(r"[^\n]", " ", match.group()), source)
    require(not re.search(r'/\*|//|["\']', masked), "malformed C token")
    return masked


def complete_function(source, name):
    masked = code_only(source)
    matches = list(re.finditer(r"(?m)^static (?:bool|int) " + re.escape(name) + r"\(", masked))
    require(len(matches) == 1, "ambiguous function boundary " + name)
    start = matches[0].start()
    # A declaration cannot stand in for a complete definition.
    opening = masked.find("{", matches[0].end())
    require(opening >= 0 and ";" not in masked[matches[0].end():opening] and
            not DEFINITION.search(masked, matches[0].end(), opening),
            "malformed function boundary " + name)
    require(re.search(r"\)\s*$", masked[matches[0].end():opening]) is not None,
            "malformed function signature " + name)
    depth = 0
    for brace in re.finditer(r"[{}]", masked[opening:]):
        position = opening + brace.start()
        if brace.group() == "{":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                require(position > 0 and masked[position - 1] == "\n" and
                        (position + 1 == len(masked) or masked[position + 1] == "\n") and
                        not DEFINITION.search(masked, opening + 1, position),
                        "malformed function boundary " + name)
                return masked[opening:position + 1]
    raise RuntimeError("unterminated function " + name)


def ordered_once(code, anchors, reason):
    positions = []
    for anchor in anchors:
        require(code.count(anchor) == 1, reason + ": " + anchor)
        positions.append(code.index(anchor))
    require(positions == sorted(positions), reason)


def claim_and_transactions(source):
    claim = complete_function(source, "swapz_round091_claim_reserved")
    lock = "spin_lock_irqsave(&ctx->queue_lock, flags);"
    unlock = "spin_unlock_irqrestore(&ctx->queue_lock, flags);"
    ordered_once(claim, (
        "lockdep_assert_held(&ctx->ordered_owner);", lock,
        "rcu_read_lock();", "dm_swapz_round091_accepted_clone_matches(",
        "dm_swapz_round090_route_live(", "rcu_read_unlock();",
        "if (!selected)", "swapz_ticket_claim_under_queue_lock(&entry->original_candidate, key);",
        "if (!error)", "entry->original_claimed = true;", "unlock:", unlock,
        "return error;"), "ordered claim lock gate")
    # Explicit allowed calls fence indirect new storage/list/I/O/wait helpers.
    # list_empty is an existing nonmutating descriptor validation.
    allowed = {"lockdep_assert_held", "spin_lock_irqsave", "spin_unlock_irqrestore",
               "if", "list_empty", "atomic_read", "rcu_read_lock", "rcu_read_unlock",
               "dm_swapz_round091_accepted_clone_matches", "dm_swapz_round090_route_live",
               "defined", "swapz_scope_key_matches_locked",
               "swapz_ticket_claim_under_queue_lock", "swapz_scope_observe_credit"}
    calls = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", claim))
    require(calls <= allowed and not re.search(r"\(\s*\*\s*\w+\s*\)\s*\(", claim),
            "ordered claim forbidden call")
    require(claim.count("spin_lock_irqsave(") == claim.count("spin_unlock_irqrestore(") == 1 and
            claim.count("return ") == 1 and
            re.search(r"if\s*\(!selected\)\s*goto unlock;", claim) and
            re.search(r"if\s*\(!error\)\s*\{\s*entry->original_claimed = true;", claim) and
            re.search(r"unlock:\s*" + re.escape(unlock) + r"\s*return error;\s*\}$", claim),
            "ordered claim lock gate")
    for name, storage, claim_call, refusal in (
        ("swapz_round091_reserve_claim_commit", "storage",
         "if (try_claim(context, credit)) {", "if (try_claim(context, credit)) {"),
        ("swapz_scope_transaction", "ctx->original_storage",
         "refused = swapz_round091_claim_reserved(claim, credit);", "if (refused) {"),
    ):
        transaction = complete_function(source, name)
        reserve = f"*error = swapz_shared_storage_reserve({storage}, spec, input, &credit);"
        cancel = f"*error = swapz_shared_storage_cancel_reserved({storage}, credit);"
        commit = f"*error = swapz_shared_storage_commit_reserved({storage}, credit);"
        sequence = [reserve, "if (*error)", claim_call]
        if refusal != claim_call:
            sequence.append(refusal)
        sequence.extend((cancel, "return *error != 0;", commit, "return true;"))
        ordered_once(transaction, sequence, "ordered transaction " + name)
        require(not re.search(r"\b(?:spin_\w+|mutex_\w+|raw_spin_\w+|wait_for_\w+)\s*\(", transaction) and
                all(transaction.count("swapz_shared_storage_" + operation + "(") == 1
                    for operation in ("reserve", "cancel_reserved", "commit_reserved")) and
                re.search(r"return \*error != 0;\s*\}", transaction) and
                re.search(r"return true;\s*\}$", transaction),
                "ordered transaction lock/terminal " + name)
    process = complete_function(source, "swapz_round091_process_candidate")
    require("lockdep_assert_held(&ctx->ordered_owner);" in process and
            not re.search(r"\b(?:spin_\w+|raw_spin_\w+)\s*\(", process) and
            re.search(r"if \(!swapz_scope_transaction\(ctx, &spec, &input, &claim_context, &error\)\)\s*goto decline;", process) and
            re.search(r"if \(!swapz_round091_reserve_claim_commit\(ctx->original_storage, &spec,\s*&input, swapz_round091_claim_reserved, &claim_context, &error\)\)\s*goto decline;", process),
            "ordered transaction actual caller")


def static_mutants(source):
    # These mutate the actual frozen function, not a toy substitute. A
    # mutant must fail this audit independently of the earlier map checks.
    anchor = "spin_lock_irqsave(&ctx->queue_lock, flags);"
    start = source.index("static int swapz_round091_claim_reserved(")
    end = source.index("\n}", start) + 2
    original = source[start:end]
    mutants = (
        ("storage_inside_claim", anchor, anchor + "\n\tswapz_shared_storage_reserve(0, 0, 0, 0);"),
        ("wait_inside_claim", anchor, anchor + "\n\twait_for_completion(0);"),
        ("list_inside_claim", anchor, anchor + "\n\tlist_add_tail(0, 0);"),
        ("io_inside_claim", anchor, anchor + "\n\tsubmit_bio(0);"),
        ("wrong_lock", anchor, "spin_lock_irqsave(&ctx->other_lock, flags);"),
        ("unlock_before_claim", "error = swapz_ticket_claim_under_queue_lock",
         "spin_unlock_irqrestore(&ctx->queue_lock, flags);\n\terror = swapz_ticket_claim_under_queue_lock"),
        ("malformed_boundary", "\n}", "\n"),
        ("duplicate_boundary", "\n}", "\n}\n" + original),
    )
    killed = []
    def kill(name, changed):
        try:
            claim_and_transactions(changed)
        except RuntimeError:
            killed.append(name)
        else:
            raise RuntimeError("static mutant survived " + name)
    for name, old, new in mutants:
        require(original.count(old) == 1, "static mutation anchor " + name)
        kill(name, source[:start] + original.replace(old, new, 1) + source[end:])
    reserve = "*error = swapz_shared_storage_reserve(ctx->original_storage, spec, input, &credit);"
    claim = "refused = swapz_round091_claim_reserved(claim, credit);"
    require(source.count(reserve) == source.count(claim) == 1, "transaction mutant anchors")
    kill("reserve_after_claim", source.replace(reserve, "", 1).replace(claim, claim + "\n\t" + reserve, 1))
    cancel = "*error = swapz_shared_storage_cancel_reserved(ctx->original_storage, credit);"
    require(source.count(cancel) == 1, "cancel mutant anchor")
    kill("wrong_cancel_credit", source.replace(cancel, cancel.replace(", credit)", ", credit + 1)"), 1))
    kill("transaction_queue_lock", source.replace(reserve, anchor + "\n\t" + reserve, 1))
    return killed


def typed_read_checks(source):
    read = complete_function(source, "swapz_read")
    masked = code_only(source)
    start = masked.index("static int swapz_read(")
    signature = masked[start:masked.index("{", start)]
    match = re.fullmatch(
        r"static int swapz_read\(struct swapz_dm \*ctx, struct bio \*bio"
        r"(\n#if defined\(SWAPZ_ROUND104_INTEGRATION_TEST\)\n"
        r"[ \t]*, bool independent\n#endif\n[ \t]*)?\)\n", signature)
    require(match is not None, "typed READ signature/conditional guard")
    # R096 transfers the authoritative pin to the actual READ caller.
    # Keep the original typed-before-cache assertion and prove the new
    # release point is after the final upper BIO copy.
    typed_call = "swapz_round096_read_original_pinned("
    gated_call = "swapz_round097_read_original_pinned("
    release = "swapz_shared_original_put(&ctx->authority, original_pin)"
    anchors = ["SWAPZ_MAP_ORIGINAL"]
    if match.group(1) or gated_call in read:
        require(re.search(
            r"#if defined\(SWAPZ_ROUND097_GATED_TARGET_TEST\)\s*"
            r"error = swapz_round097_read_original_pinned\([^;]+;\s*"
            r"#else\s*error = swapz_round096_read_original_pinned\([^;]+;\s*#endif",
            read) is not None, "typed READ gated and historical alternatives")
        anchors.append(gated_call)
    anchors.extend((typed_call, "swapz_engine_read_page(",
                    "swapz_copy_bio_accounted(", release))
    ordered_once(read, anchors,
                 "typed READ precedes ordinary cache and retains pin through upper copy")


def typed_read_mutants(source):
    start = source.index("static int swapz_read(")
    end = source.index("\n}", start) + 2
    original = source[start:end]
    release = "release_error = swapz_shared_original_put(&ctx->authority, original_pin);"
    copy = re.search(r"error = swapz_copy_bio_accounted\([^;]+;", original)
    require(copy is not None and original.count(release) == 1,
            "typed READ mutation anchors")
    mutants = [
        ("typed_read_missing_boundary", original[:-1]),
        ("typed_read_duplicate_boundary", original + "\n" + original),
        ("typed_read_release_before_copy",
         original.replace(copy.group(), "", 1).replace(
             release, release + "\n\t\t" + copy.group(), 1)),
    ]
    if "bool independent" in original:
        mutants.append(("typed_read_wrong_signature_guard",
                        original.replace("ROUND104_INTEGRATION_TEST",
                                         "ROUND103_INTEGRATION_TEST", 1)))
    killed = []
    for name, changed in mutants:
        try:
            typed_read_checks(source[:start] + changed + source[end:])
        except RuntimeError:
            killed.append(name)
        else:
            raise RuntimeError("static mutant survived " + name)
    return killed


def static_checks(source, patch):
    anchor = "list_add_tail(&entry->list, &ctx->incoming);"
    require(source.count(anchor) == 1, "canonical FIFO")
    mapping = source.split("static int swapz_map(struct dm_target *ti, struct bio *bio)", 1)[1].split("static void swapz_drain(", 1)[0]
    require(mapping.index("swapz_round090_candidate_get(ti, bio,") <
            mapping.index("spin_lock_irqsave(&ctx->queue_lock, flags)") <
            mapping.index("swapz_round091_retain_candidate_locked(ctx, entry,") <
            mapping.index(anchor) < mapping.index("if (original_retained)"),
            "retention before canonical FIFO")
    require("swapz_ticket_claim_under_queue_lock" not in mapping and
            "swapz_shared_storage_reserve" not in mapping, "map claims/reserves")
    retain = fragment(source, "RETAIN")
    require("swapz_ticket_claim" not in retain and "entry->original_candidate = *ref;" in retain,
            "retention is unclaimed")
    require(source.count("swapz_process(ctx, entry->bio)") == 1, "ordinary process bypass")
    require(source.index("wait_for_completion(&entry->preparation_snapshot_ready)") <
            source.index("swapz_process(ctx, entry->bio)"), "ordinary preparation wait")
    require("swapz_round091_ordered_claim_permitted(void)\n{\n\treturn false;\n}" in source,
            "frozen live claim guard")
    claim_and_transactions(source)
    require("map_scope && (!tio->len_ptr || *tio->len_ptr != 8U)" in patch and
            "tio->io->orig_bio, false)" in patch, "accepted clone transient length guard")
    require("swapz_shared_original_segment_pinned(a, segment)" in source and
            "swapz_shared_storage_relocate(ctx->original_storage" in source, "GC and TRIM guard")
    typed_read_checks(source)
    require("bi_bvec_done" not in source, "obsolete bvec member")


def run_command(args, evidence, label, expected=0):
    env = {key: value for key, value in os.environ.items() if key not in
           ("CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "OBJC_INCLUDE_PATH")}
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=180,
                            env=env | {"ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                                       "UBSAN_OPTIONS": "halt_on_error=1"})
    if result.returncode != expected:
        (evidence / "first-child-error.log").write_text((result.stderr + result.stdout)[:12000])
        raise RuntimeError(f"{label}: exit {result.returncode}, expected {expected}")
    return result


def run_compiler(compiler, stage, linux, work, prior, helpers, fragments, evidence):
    standard = helpers["compiler_standard"](compiler)
    shim = prior["build_shim"](linux, work, helpers)
    staged = work / "staged"
    staged.mkdir()
    (staged / "lz4_compress.c").write_bytes(
        prior["staged_bytes"]((linux / prior["LZ4_SOURCE"]).read_bytes(), LINUX, ""))
    (staged / "lz4_decompress.c").write_bytes(
        prior["staged_decoder_bytes"]((linux / prior["LZ4_DECODER_SOURCE"]).read_bytes(), LINUX, ""))
    (staged / "lz4defs.h").write_bytes((linux / "lib/lz4/lz4defs.h").read_bytes())
    objects = []
    for part in ("lib/lzo/lzo1x_compress_safe.c", "lib/lzo/lzo1x_decompress_safe.c",
                 "lib/lz4/lz4_compress.c", "lib/lz4/lz4_decompress.c"):
        path = staged / Path(part).name if part.startswith("lib/lz4") else linux / part
        obj = work / ("original-" + path.stem + ".o")
        helpers["compile_object"](compiler, "-std=gnu11", path, obj,
                                  ["-I", str(shim), "-DCONFIG_64BIT=1"], original=True)
        objects.append(obj)
    kernel = stage / "src/kernel"
    adapter = work / "original-compressor.c"
    adapter.write_text(prior["COMPRESS_ADAPTER"])
    flags = ["-I", str(shim), "-I", str(kernel), "-I", str(work),
             "-I", str(stage / "tests/runtime/native/fixtures"),
             "-DSWAPZ_ORIGINAL_TICKET_TEST=1", "-DSWAPZ_ORIGINAL_STORAGE_TEST=1",
             "-DSWAPZ_ORIGINAL_EXTENT_TEST=1", "-DSWAPZ_ROUND066_IMPORT_DISK_TEST=1",
             "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST=1", "-DSWAPZ_SHARED_ORIGINAL_TEST=1"]
    host_flags = [standard, "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                  "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                  "-fno-omit-frame-pointer", "-fno-pie",
                  "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST=1",
                  "-DSWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST=1",
                  "-DSWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST=1",
                  "-D_POSIX_C_SOURCE=200809L", "-D__maybe_unused=__attribute__((unused))",
                  "-include", "stddef.h"]
    for name in ("authority.c", "engine.c", "codec.c", "zswap-original-storage.c",
                 "zswap-original-extent.c", "zswap-original-ticket.c",
                 "zswap-import-decoder-owner.c", "zswap-original-decode.c",
                 "zswap-original-decoder-bridge.c"):
        path = kernel / name
        obj = work / ("product-" + path.stem + ".o")
        run_command([compiler, *host_flags, *flags, "-c", str(path), "-o", str(obj)],
                    evidence, "compile " + name)
        objects.append(obj)
    obj = work / "original-compressor.o"
    run_command([compiler, *host_flags, *flags, "-c", str(adapter), "-o", str(obj)],
                evidence, "compile original adapter")
    objects.append(obj)
    fixture, shared = isolate_fixture(stage, work)
    result = {}
    for name, old, new in (("baseline", "", ""), *MUTANTS):
        code = fragments
        if old:
            require(code.count(old) == 1, "mutation anchor " + name)
            code = code.replace(old, new, 1)
        (work / "ordered-fragments.h").write_text(code)
        program = work / "ordered-host"
        verify_fixture(shared, PINS[SHARED_FIXTURE])
        run_command([compiler, *host_flags, *flags, str(fixture),
                     *(str(item) for item in objects), "-pthread", "-lcrypto", "-no-pie",
                     "-o", str(program)], evidence, "fixture " + name)
        execution = run_command([str(program)], evidence, "run " + name, 77 if old else 0)
        if old:
            require(execution.stderr.startswith("SEMANTIC_FAIL line=") and not execution.stdout,
                    "not a semantic kill " + name)
            result["mutants"].append(name)
        else:
            match = re.fullmatch(r"PASS ROUND091_ORDERED checks=(\d+) claims=5 refusals=3 typed_reads=2 terminal_owners=5 AUTH0\n",
                                 execution.stdout)
            require(match and not execution.stderr, "baseline counts or sanitizer")
            result = {"checks": int(match.group(1)), "claims": 5, "refusals": 3,
                      "typed_reads": 2, "modeled_terminal_owners": 5, "mutants": []}
    print(Path(compiler).name, json.dumps(result, sort_keys=True), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--frozen-r102-target", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    report = {"round": "092", "agent": 3, "tested_commit": git("rev-parse", "HEAD").decode().strip(),
              "frozen_product": BASE, "linux": LINUX, "AUTH": 0, "phase_a": "BLOCKED",
              "physical_io": False, "native_dm": "NOT_RUN", "compilers": {},
              "first_error": None, "conclusion": "FAIL"}
    try:
        if args.frozen_r102_target:
            frozen = "d2baba1bda02b78eb7df265d22c5e9dbee09e2b1"
            target = git("show", frozen + ":src/kernel/dm-target.c")
            require(git_blob(target) == "46c2cb832ff0071a028a27b35f63daa84f29914f",
                    "R102 frozen target pin")
            source = target.decode()
            report["target_ref"] = frozen
        else:
            source = (ROOT / "src/kernel/dm-target.c").read_text()
        report["target_blob"] = git_blob(source.encode())
        patch = (ROOT / "tests/tools/round088-original-dm-selected-clone.patch").read_text()
        static_checks(source, patch)
        report["static_mutants"] = static_mutants(source) + typed_read_mutants(source)
        print("ORDERED_STATIC_PASS mutants=" + str(len(report["static_mutants"])), flush=True)
        fragments = fragment(source, "TRANSACTION") + fragment(source, "TYPED_READ")
        report["fragment_sha256"] = hashlib.sha256(fragments.encode()).hexdigest()
        linux = args.linux_root.resolve()
        require(subprocess.check_output(["git", "-C", str(linux), "rev-parse", "HEAD"]).decode().strip() ==
                LINUX, "original Linux pin")
        with tempfile.TemporaryDirectory(prefix="round091-ordered-") as temp:
            workspace = Path(temp)
            stage = workspace / "frozen"
            stage.mkdir()
            archive = git("archive", BASE, *STAGE_PATHS)
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(stage, filter="data")
            report["frozen_inventory_count"] = verify_stage(stage)
            mixed = workspace / "mixed-version-fixture.c"
            mixed.write_bytes(git("show", OLD_BASE + ":" + SHARED_FIXTURE))
            try:
                verify_fixture(mixed, PINS[SHARED_FIXTURE])
            except RuntimeError as error:
                require(str(error) == "mixed-version fixture rejected", "wrong negative cause")
            else:
                raise RuntimeError("mixed-version fixture was accepted")
            report["mixed_version_negative"] = "PASS"
            for path, pin in PINS.items():
                require(git_blob((stage / path).read_bytes()) == pin, "frozen pin " + path)
            prior = runpy.run_path(str(stage / "tests/tools/round085-original-decode-verify.py"))
            require(prior["PIN"] == LINUX and
                    prior["LZ4_POSTIMAGE"] == "63eb4be2e23caf770649af18f6a7b2b82d79a5e7" and
                    prior["LZ4_DECODER_POSTIMAGE"] == "8ca9e57ea0d03918e85e4aabcf472fe906b6bc7f",
                    "frozen isolated codec pins")
            helpers = prior["verify_inputs"](linux)
            for compiler in ("gcc", "clang"):
                work = workspace / compiler
                work.mkdir()
                report["compilers"][compiler] = run_compiler(
                    compiler, stage, linux, work, prior, helpers, fragments, evidence)
        report["conclusion"] = "PASS_HOST_ONLY"
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError, AssertionError, ValueError) as error:
        report["first_error"] = str(error).split("\n", 1)[0][:220]
        print("ROUND091_FIRST_ERROR " + report["first_error"], file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
