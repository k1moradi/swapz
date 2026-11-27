#!/usr/bin/env python3
"""R104 A11 exact original source and focused host/directed objects; no link."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FREEZE = "a9094f96e3fb2841ed0fa553102d98699950221d"
TASK = "3ec158e2870170bd58fc13dfc340722a89f51cae"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PRIOR = "tests/tools/round103-external-join-verify.py"
PRIOR_PIN = "11ae07a68761d11160b649a3503af64eecd3ec4a"
PATCH = "tests/tools/round104-original-mm-core-witness.patch"
PATCH_PIN = "132c03fcefe961696f468a41c763666f1dc4f90c"
FIXTURE = "tests/runtime/native/fixtures/round104-mm-core-witness.c"
FIXTURE_PIN = "3b26bb20585b28528c24fcbcdb1394ee83ddd6c6"
HEADER = "src/kernel/native-observation-integration.h"
HEADER_PIN = "e3bca3367459c7f79960105f63e9ddef4e95b4d6"
ADAPTER = "src/kernel/native-observation-adapter.h"
ADAPTER_PIN = "ffa547fbecad79b3fabf0ded4bb182c201e4a33d"
OWNER = "src/kernel/native-observation-owner.h"
OWNER_PIN = "9e44829f3920167829fc364fdb6a95bfa0930805"
OBJECTS = ("mm/zswap.o", "mm/page_io.o", "drivers/md/dm.o", "block/bio.o")
MODES = ("normal", "chain", "chain-parent", "requeue", "late", "ordinal")
PEER_SYMBOLS = ("swapz_trial_byte_active", "swapz_trial_byte_stage_input",
                "swapz_trial_byte_finish_input", "swapz_trial_byte_event",
                "swapz_trial_byte_invalidate", "swapz_trial_observation_append_sequence")
IMAGES = {
    "mm/zswap.c": [
        "833f089bc01e8803f427732975d706c894436eb3",
        "e088dd706763bec377d09a81905cf5de9b371c6a"
    ],
    "drivers/md/dm.c": [
        "e07dfd963edcdfb438af2ae1f43e3023e54544b7",
        "6912eb7ec5a9ef325f7282ef9c9226b39265f01d"
    ],
    "mm/swapz-trial-terminal.inc": [
        "3f980d04958676c22d44a6ca2778c4bd40a464fb",
        "1ecc86d30f20790f1fae7506a3f55d612200831a"
    ],
    "include/linux/swapz_mm_carrier.h": [
        "7091e456b6c09f29d68140cfff3f072e940ccd2f",
        "b930f6f04a21d3f2b8b6f2279e028a94cfc99502"
    ],
    "include/linux/swapz_trial_debt.h": [
        "207cd1b7a87f493992938cfa00ed4f95c7196811",
        "d1d2fc65084936380c211094ce6f073273596338"
    ],
    "block/bio.c": [
        "38f24ee2e414107be390d3a01c6b907e06a9dca7",
        "f6f1ddc82a5632f1f9cf8dbb0bdb2138eb8e0e64"
    ],
    "include/linux/bio.h": [
        "4079365b37690164f85ba962a0bd0918c85899cb",
        "c7d5543249003b7f190d6ea065fd6253d5572792"
    ]
}


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def pin(path, expected):
    if expected is None:
        require(not path.exists() and not path.is_symlink(), "unexpected new preimage " + path.name)
        return
    require(path.is_file() and not path.is_symlink(), "missing pinned file " + path.name)
    require(blob(path.read_bytes()) == expected, "blob mismatch " + path.name)


def git(directory, *args):
    return subprocess.check_output(["git", "-C", str(directory), "--no-replace-objects", *args])


def function(source, name):
    matches = list(re.finditer(r"(?m)^(?:static )?(?:inline )?(?:bool|int|void|u64)\s+" +
                               re.escape(name) + r"\([^;]+?\)\n\{", source))
    require(len(matches) == 1, "function anchor " + name)
    match = matches[0]
    return source[match.start():source.index("\n}", match.end()) + 3]


def ordered(code, anchors, reason):
    positions = []
    for anchor in anchors:
        require(code.count(anchor) == 1, reason + ": " + anchor)
        positions.append(code.index(anchor))
    require(positions == sorted(positions), reason)


def load_prior():
    pin(ROOT / PRIOR, PRIOR_PIN)
    spec = importlib.util.spec_from_file_location("r104_frozen_r103", ROOT / PRIOR)
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    return previous


def source_checks(linux):
    mm = (linux / "mm/zswap.c").read_text()
    terminal = (linux / "mm/swapz-trial-terminal.inc").read_text()
    page = (linux / "mm/page_io.c").read_text()
    dm = (linux / "drivers/md/dm.c").read_text()
    block = (linux / "block/bio.c").read_text()
    carrier = (linux / "include/linux/swapz_mm_carrier.h").read_text()
    store = function(mm, "zswap_store_page")
    ordered(store, ("input_token = swapz_mm_stage_input(folio, index, page_swpentry);",
                    "if (!zswap_compress(folio, index, entry, pool))",
                    "old = xa_store(", "swapz_trial_byte_finish_input(input_token, entry->original_cookie);",
                    "zswap_lru_add(entry);", "compress_failed:",
                    "swapz_trial_byte_finish_input(input_token, 0);"), "real store commit/abort")
    stage = function(mm, "swapz_mm_stage_input")
    ordered(stage, ("rcu_read_lock();", "source = kmap_local_folio(folio, 0);",
                    "token = swapz_trial_byte_stage_input(", "kunmap_local(source);",
                    "rcu_read_unlock();"), "actual source lifetime")
    comp = function(mm, "zswap_compress")
    ordered(comp, ("crypto_wait_req(crypto_acomp_compress(", "zs_obj_write(",
                   "swapz_mm_capture(entry, folio, index, pool, acomp_ctx->req);"), "real cookie provenance")
    for name, count in (("swapz_mm_observation_capture", 2), ("swapz_mm_observation_bind", 1),
                        ("swapz_mm_observation_endio", 1), ("swapz_mm_observation_release", 2)):
        code = function(mm, name)
        require(code.count("swapz_mm_observation_emit(") == count and
                "swapz_trial_observation_append(" not in code, "exact ordinal call sites " + name)
    emit = function(carrier, "swapz_mm_observation_emit")
    ordered(emit, ("swapz_trial_observation_append_sequence(record)",
                   "swapz_trial_byte_event(record, sequence, NULL, 0)",
                   "swapz_trial_byte_invalidate();"), "one ordinal and no fabricated bytes")
    require("swapz_mm_observation_endio(sio->original," in function(page, "end_swap_bio_write"),
            "actual original MM callback")
    finish = function(terminal, "swapz_mm_trial_dm_endio")
    ordered(finish, ("swapz_trial_debt_take(", "spin_unlock_irqrestore(",
                     "swapz_mm_observation_emit(&record);", "endio(bio);",
                     "swapz_mm_terminal_put(ticket, SWAPZ_TRIAL_DM);"), "original callback join")
    require("swapz_bio_is_chain_child(bio)" in function(terminal, "swapz_mm_trial_dm_enter") and
            "bio->bi_end_io == bio_chain_endio" in function(block, "swapz_bio_is_chain_child"),
            "special chain sentinel")
    require("swapz_mm_trial_dm_complete(io->orig_bio" in function(dm, "dm_swapz_original_observation_endio"),
            "actual DM core handoff to terminal witness")
    return {"actual_source_before_compression": True, "store_commit_and_abort": True,
            "actual_mm_and_dm_original_ack": True, "special_chain_sentinel": True,
            "exact_ordinal_call_sites": True}


def stage_source(previous, helper, state, evidence, frozen, baseline, linux):
    historical = evidence / "r103-stage"
    historical.mkdir()
    prior_state = {"completed_steps": []}
    previous.stage_source(helper, prior_state, historical, frozen, baseline, linux)
    require(prior_state["stage"] == "PASS", "R103 immutable stage")
    state["r103_stage"] = prior_state
    pin(ROOT / PATCH, PATCH_PIN)
    pin(ROOT / FIXTURE, FIXTURE_PIN)
    previous_paths = set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
    for path, pair in IMAGES.items():
        pin(linux / path, pair[0])
    command = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
    for name, options, index in (("check", ["--check"], 0), ("apply", [], 1),
                                 ("reverse-check", ["--reverse", "--check"], 1),
                                 ("reverse", ["--reverse"], 0), ("reapply", [], 1)):
        helper.step(state, evidence, "r104-" + name, command + options + [str(ROOT / PATCH)], linux)
        for path, pair in IMAGES.items():
            pin(linux / path, pair[index])
    require(not git(linux, "diff", "--name-only"), "unexpected unstaged tracked source")
    require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines()) ==
            previous_paths | set(IMAGES), "R104 exact staged path census")
    helper.step(state, evidence, "r104-staged-diff-check", ["git", "diff", "--cached", "--check"], linux)
    (evidence / "unified-r104.diff").write_bytes(git(linux, "diff", "--cached", "--binary"))
    state["postimages"] = {path: helper.image(linux / path) for path in IMAGES}
    # Stage only immutable declarations, never a same-round peer implementation.
    glue = linux / helper.GLUE_DIR
    state["declarations"] = {}
    for ref, path, expected in ((TASK, HEADER, HEADER_PIN), (FREEZE, ADAPTER, ADAPTER_PIN),
                                (FREEZE, OWNER, OWNER_PIN)):
        data = git(ROOT, "show", ref + ":" + path)
        require(blob(data) == expected, "frozen declaration " + path)
        dest = glue / Path(path).name
        dest.write_bytes(data)
        pin(dest, expected)
        state["declarations"][path] = helper.image(dest)
    state["static_checks"] = source_checks(linux)
    state["stage"] = "PASS"


def host(helper, state, evidence, linux, scratch):
    mm = (linux / "mm/zswap.c").read_text()
    carrier = (linux / "include/linux/swapz_mm_carrier.h").read_text()
    terminal = (linux / "mm/swapz-trial-terminal.inc").read_text()
    swapfile = (linux / "mm/swapfile.c").read_text()
    dm = (linux / "drivers/md/dm.c").read_text()
    block = (linux / "block/bio.c").read_text()
    model = scratch / "host"
    model.mkdir()
    scope = re.findall(r"(?ms)^struct swapz_mm_trial_scope \{\n.*?^\};", carrier)
    require(len(scope) == 1, "actual scope type")
    declarations = re.findall(r"(?m)^(?:int|u64|void|bool) swapz_mm_trial_[a-z_]+\([^;]*?\);", carrier)
    declarations = [d for d in declarations if "struct swapz_mm_route" not in d and
                    "struct swapz_mm_carrier" not in d]
    require(any("swapz_mm_trial_area_epoch(" in d for d in declarations), "actual area declarations")
    files = {
        "actual-scope-type.h": scope[0] + "\n",
        "actual-area-declarations.h": "\n".join(declarations) + "\n",
        "actual-next.h": function(mm, "swapz_mm_next"),
        "actual-scope-control.h": function(swapfile, "swapz_mm_trial_area_get") +
            "\n".join(function(mm, name) for name in ("swapz_mm_scope_valid", "swapz_mm_trial_scope_publish",
                       "swapz_mm_trial_scope_stop_capture", "swapz_mm_trial_scope_revoke")),
        "actual-chain.h": function(block, "swapz_bio_is_chain_child"),
        "actual-emit.h": function(carrier, "swapz_mm_observation_emit"),
        "actual-store.h": function(mm, "swapz_mm_stage_input") + "\n" + function(mm, "zswap_store_page"),
        "actual-dm-endio.h": function(dm, "dm_swapz_original_observation_endio"),
        "actual-mm-endio.h": function(mm, "swapz_mm_observation_endio"),
        "swapz-trial-terminal.inc": terminal,
    }
    for path, data in files.items():
        (model / path).write_text(data)
    state["host"] = {}
    for compiler in ("gcc", "clang"):
        binary = model / compiler
        command = [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                   "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                   "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                   "-I" + str(model), "-I" + str(linux / "include"), str(ROOT / FIXTURE), "-o", str(binary)]
        helper.step(state, evidence, compiler + "-host-compile", command, timeout=180)
        state["host"][compiler] = {"version": subprocess.check_output([compiler, "--version"], text=True).splitlines()[0],
                                    "modes": {}, "mutants": {}}
        for mode in MODES:
            label = compiler + "-" + mode
            helper.step(state, evidence, label, [str(binary), mode])
            result = (evidence / (label + ".log")).read_text()
            match = re.fullmatch(r"R104_A11_HOST_ONLY mode=" + re.escape(mode) +
                                 r" checks=(\d+) grace=(\d+) AUTH0\n", result)
            require(match, "host result or sanitizer " + label)
            state["host"][compiler]["modes"][mode] = {"checks": int(match[1]), "graces": int(match[2])}
            print(result.strip(), flush=True)
        store = files["actual-store.h"]
        stage = "input_token = swapz_mm_stage_input(folio, index, page_swpentry);"
        require(store.count(stage) == 1 and store.count("goto compress_failed;") == 1, "stage mutant anchors")
        delayed = store.replace(stage, "input_token = 0;").replace("goto compress_failed;",
                    "goto compress_failed;\n#ifdef SWAPZ_ROUND104_INTEGRATION_TEST\n\t" + stage + "\n#endif")
        mutants = (
            ("wrong-file", "swapz-trial-terminal.inc",
             "mapper_file == READ_ONCE(swapz_mm_scope_file) &&", "true &&", "normal"),
            ("wrong-store", "actual-store.h",
             "swapz_trial_byte_finish_input(input_token, entry->original_cookie);",
             "swapz_trial_byte_finish_input(input_token, entry->original_cookie + 1);", "normal"),
            ("late-input", "actual-store.h", store, delayed, "normal"),
            ("chain-child", "swapz-trial-terminal.inc", " || swapz_bio_is_chain_child(bio)",
             " || (swapz_bio_is_chain_child(bio) && false)", "chain"),
            ("early-ack", "actual-dm-endio.h",
             "(void)status;", "(void)status;\n\t\tstruct swapz_observation_record early = "
             "{.event = SWAPZ_OBS_UPPER_ENDIO, .operation = io->swapz_observation_operation, "
             ".original = io->swapz_observation_original};\n\t\tswapz_mm_observation_emit(&early);", "normal"),
        )
        for name, path, before, after, mode in mutants:
            require(files[path].count(before) == 1 and before != after, "mutant anchor " + name)
            label = compiler + "-mutant-" + name
            try:
                (model / path).write_text(files[path].replace(before, after))
                helper.step(state, evidence, label + "-compile", command, timeout=180)
                result = subprocess.run([str(binary), mode], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        timeout=30, check=False)
                (evidence / (label + ".log")).write_bytes(result.stdout)
                require(result.returncode == 77 and b"R104_A11_FIRST_ERROR" in result.stdout,
                        "mutant not rejected by assertion " + label)
                state["host"][compiler]["mutants"][name] = {"exit": result.returncode,
                    "first_error": result.stdout.decode().splitlines()[0]}
                print("R104_A11_MUTANT_KILLED " + label, flush=True)
            finally:
                (model / path).write_text(files[path])
    state["host_status"] = "PASS_ACTUAL_EXTRACTED_HOST_ONLY"


def native(helper, state, evidence, linux, build):
    helper.prerequisites(state, evidence)
    glue = linux / helper.GLUE_DIR
    guards = (helper.GUARDS + helper.OBSERVATION_GUARDS +
              " -DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST -DSWAPZ_ROUND103_EXTERNAL_JOIN_TEST -DSWAPZ_ROUND104_INTEGRATION_TEST -I" + str(glue))
    state["native_guards"] = guards.replace(str(glue), helper.GLUE_DIR)
    build.mkdir()
    make = ["make", "-C", str(linux), "O=" + str(build), "ARCH=x86_64", "CC=gcc", "KCFLAGS=" + guards]
    helper.step(state, evidence, "allnoconfig", make + ["allnoconfig"], timeout=120)
    config = ["bash", str(linux / "scripts/config"), "--file", str(build / ".config")]
    for key in helper.REQUIRED:
        config += ["--enable", key]
    for key in ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT", "MODULE_SIG",
                "DEBUG_INFO", "DEBUG_INFO_BTF", "TINY_RCU"):
        config += ["--disable", key]
    config += ["--set-val", "NR_CPUS", "4"]
    helper.step(state, evidence, "set-config", config)
    helper.step(state, evidence, "olddefconfig", make + ["olddefconfig"], timeout=120)
    config_data = (build / ".config").read_bytes()
    (evidence / "effective.config").write_bytes(config_data)
    lines = config_data.decode().splitlines()
    for key in helper.REQUIRED:
        require("CONFIG_" + key + "=y" in lines, "missing effective config " + key)
    require("CONFIG_NR_CPUS=4" in lines and "CONFIG_TINY_RCU=y" not in lines and
            "CONFIG_ZSWAP_DEFAULT_ON=y" not in lines and "CONFIG_ZSWAP_SHRINKER_DEFAULT_ON=y" not in lines,
            "SMP default-off effective config")
    state["config_sha256"] = hashlib.sha256(config_data).hexdigest()
    state["objects"] = {}
    try:
        helper.step(state, evidence, "changed-native-objects", make + ["-j2", *OBJECTS], timeout=1000)
    finally:
        for path in OBJECTS:
            source = build / path
            if source.is_file():
                destination = evidence / "objects" / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                state["objects"][path] = helper.image(source)
    require(set(state["objects"]) == set(OBJECTS), "missing directed objects")
    symbols = {
        "mm/zswap.o": ("swapz_mm_trial_scope_matches_exact", "swapz_mm_trial_dm_complete", *PEER_SYMBOLS),
        "mm/page_io.o": ("swapz_mm_observation_endio",),
        "drivers/md/dm.o": ("swapz_mm_trial_dm_complete", "swapz_trial_byte_invalidate"),
        "block/bio.o": ("swapz_bio_is_chain_child",),
    }
    state["unresolved_peer_symbols"] = {}
    for path, names in symbols.items():
        output = subprocess.check_output(["nm", str(build / path)], text=True)
        (evidence / (Path(path).name + ".symbols")).write_text(output)
        require(all(re.search(r"\b" + name + r"\b", output) for name in names), "missing symbol " + path)
        unresolved = sorted(set(re.findall(r"(?m)^\s+U\s+(\w+)$", output)) & set(PEER_SYMBOLS))
        state["unresolved_peer_symbols"][path] = unresolved
        (evidence / (Path(path).name + ".relocations")).write_bytes(
            subprocess.check_output(["readelf", "-Wr", str(build / path)]))
    require(set(state["unresolved_peer_symbols"]["mm/zswap.o"]) == set(PEER_SYMBOLS), "missing unresolved peer ABI")
    for path, (_, after) in IMAGES.items():
        pin(linux / path, after)
    for path, expected in ((HEADER, HEADER_PIN), (ADAPTER, ADAPTER_PIN), (OWNER, OWNER_PIN)):
        pin(glue / Path(path).name, expected)
    require(not (build / "vmlinux").exists() and not (build / "Module.symvers").exists(),
            "unexpected full link")
    state["native"] = "PASS_DIRECTED_OBJECTS_ONLY"


def main():
    os.umask(0o077)
    frozen, baseline, linux, evidence = (Path(arg).resolve() for arg in sys.argv[1:])
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = {"round": 104, "agent": 11, "source": git(ROOT, "rev-parse", "HEAD").decode().strip(),
             "freeze": FREEZE, "linux": LINUX, "AUTH": 0, "phase_a": "BLOCKED",
             "native_link": "NOT_RUN", "native": "NOT_RUN", "stage": "NOT_RUN",
             "completed_steps": [], "status": "FAIL", "first_error": None}
    try:
        previous = load_prior()
        helper = previous.load_helper()
        stage_source(previous, helper, state, evidence, frozen, baseline, linux)
        with tempfile.TemporaryDirectory(prefix="r104-join-") as temp:
            scratch = Path(temp)
            first_error = None
            # Host failure is retained, but does not prevent independent native
            # changed-object diagnostics for the exact same staged source.
            try:
                host(helper, state, evidence, linux, scratch)
            except Exception as error:
                first_error = str(error)
            try:
                native(helper, state, evidence, linux, scratch / "build")
            except Exception as error:
                state["native_error"] = str(error).split("\n", 1)[0][:350]
                if first_error is None:
                    first_error = str(error)
            if first_error is not None:
                raise RuntimeError(first_error)
        state["status"] = "PASS_HOST_AND_DIRECTED_ONLY"
        print("R104_A11_PASS AUTH0 DIRECTED_ONLY", flush=True)
        return 0
    except Exception as error:
        state["first_error"] = str(error).split("\n", 1)[0][:350]
        print("R104_A11_FIRST_ERROR " + state["first_error"], file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
