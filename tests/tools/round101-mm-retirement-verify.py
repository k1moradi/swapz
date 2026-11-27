#!/usr/bin/env python3
"""R101 A11: exact staged MM/broker change, changed-case host tests, directed objects."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FREEZE = "28ffacb0a50fede481d010c0b688271badbbae6e"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
MM = "mm/zswap.c"
CARRIER = "include/linux/swapz_mm_carrier.h"
PAGE = "mm/page_io.c"
BROKER = "src/kernel/zswap-original-ticket.c"
OWNER = "src/kernel/zswap-original-broker-owner.inc"
HEADER = "src/kernel/zswap-original-ticket.h"
PATCH = "tests/tools/round101-original-mm-retirement.patch"
PATCH_PIN = "4d34b0d771789c09967b38fdf84b0f2b6513cd60"
PRE = {MM: "cad0d9ba05cd614b95b335ed0c7d70d9e69d00f0",
       CARRIER: "5e11fe42a9dce147cdaf7f30c43b1c8b6feff59a",
       BROKER: "70109f2c2ce9f60681649bd4807382248d0a41a2",
       OWNER: "278a93a3fd3fd260444aebc55d4a87112e56f704",
       HEADER: "c7f4ff59c11ee3475e7577dcc62f7c8db5a578ea"}
POST = {MM: "fcb2f7487cb7ed02ae8ca9a8d486909f721a2ef6",
        CARRIER: "f50911d4c1ff7f87b502cec042b90968ba3a282f",
        BROKER: "e605bb0b8fbf5e6411a4d5d6182cab1a44d48bea",
        OWNER: "a6a025b1d56513919ac83f4367e9c306fa12c933",
        HEADER: "6c79e41cb18082b925311bf62d0cfbed45a9e53b"}
INPUTS = {
    BROKER: "7ba56c5ee602853c8d0717f23aad9efc69d111ea",
    HEADER: "0630f9e4fad26458ed0778ca6ae040150e28f078",
    OWNER: "0eda8753b91d3209c55f65eb90014fd9b8c6ad7c",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/native-observation-adapter.c": "f94371ff06ba8296e292ccec9e28dd230ded5bbd",
    "src/kernel/native-observation-adapter.h": "27f1140f4dcc510662fbb1f4519f7be4236e1b10",
    "src/kernel/native-observation-owner.c": "69bd5c018bf4cc502c14c1c3f1cc02c1959c1673",
    "src/kernel/native-observation-owner.h": "e266f0e0c2dec0d399cc863da329e44f38b0c536",
}
FIXTURES = {
    "native-observation-owner-host-model.h": "47042c1c9f388f29e2989492c15ef479573b1019",
    "native-observation-adapter-host-model.h": "3dac25d2edb2d7475af3231c98af753f09e4063f",
    "round094-owner-shim.h": "bc49e924eeee826496264503d0af1b4f1fb8e611",
    "round092-module-shim.h": "79623955e77b0b35d17bd14f322412d8ee202c84",
}
ADDITIONAL = [
    ("round092-original-module-boundary.patch", "62db468c14f23b59e7adaae65a11dcb9969f02b3",
     {MM: "98a8a6a66858204b61875ad9b2e8cfb0ecf8980a", CARRIER: "da1e7a367f4f5d16dc6854f33064631251acb153",
      BROKER: "634b38e52b3b1e6493d6b10a694065ccc4b698ad", HEADER: "6afac83a0655e532ce1ef9b8f290a367e8aabfce"}),
    ("round094-original-broker-owner.patch", "e33bb8451210f9e1a97eb6d9bc0423f6b13a2edd",
     {BROKER: "ba5e891ef7f80bf0b3021ee6c676529cb72f1972", HEADER: PRE[HEADER]}),
    ("round095-mm-capture-off.patch", "fee3d20b8ef872528b1301597eb33e0e0282da52",
     {MM: "9278abca17077bf9c0e94885eb4d46cdbd9202bd"}),
    ("round096-original-owner-retry.patch", "6ee63e6515dd2f0337c49d1a868f39435b93119c",
     {BROKER: PRE[BROKER], OWNER: PRE[OWNER]}),
    ("round097-original-mm-producer.patch", "c35b35c18cc11f9b86c0b65856dbc0cd2a0bd2c8",
     {MM: "128495cf9b35d37b93db1b165dc1562de94b5b89", CARRIER: "7083f7acdb439022a073c22261b7541d15806e5e",
      PAGE: "08c11d2f9a16a322093b305afa10ba011f67fc2b"}),
    ("round098-original-mm-scope-events.patch", "3832b6aa76b783f3790b869cf40512b114d66cd6",
     {MM: PRE[MM], CARRIER: PRE[CARRIER]}),
]
GLUE = "mm/round101-swapz"
OBJECTS = [MM.replace(".c", ".o"), PAGE.replace(".c", ".o"), GLUE + "/zswap-original-ticket.o"]

def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)

def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def pin(path, expected):
    require(path.is_file() and not path.is_symlink(), "missing source " + path.name)
    data = path.read_bytes()
    require(blob(data) == expected, "blob mismatch " + path.name + " actual=" + blob(data))
    return data

def image(path):
    data = path.read_bytes()
    return {"blob": blob(data), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

def git(directory, *args):
    return subprocess.check_output(["git", "-C", str(directory), *args])

def step(output, name, argv, cwd=ROOT, timeout=180):
    result = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=timeout, check=False)
    (output / (name + ".log")).write_bytes(result.stdout)
    if result.returncode:
        lines = result.stdout.decode(errors="replace").splitlines()
        first = next((line for line in lines if re.search(
            r"fatal error:|error:|undefined reference|FIRST_ERROR|patch failed|not found", line, re.I)),
            lines[-1] if lines else "no child output")
        raise RuntimeError(name + ": " + first[:350])
    return result.stdout

def import_pinned(name, relative, expected):
    path = ROOT / relative
    pin(path, expected)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def stage(linux, output, state):
    previous = import_pinned("r098_native_pins", "tests/tools/round098-smp-directed-native-compile-verify.py",
                             "96e6750971c182dfe87e6e57eac048c7c3a529b6")
    extract = import_pinned("r097_extract", "tests/tools/round097-mm-producer-verify.py",
                            "dad98ce49b64ce7bb3f6d48ba4a9395299a2da5e")
    require(git(linux, "rev-parse", "HEAD").decode().strip() == LINUX, "Linux checkout pin")
    require(not git(linux, "status", "--porcelain", "--untracked-files=all"), "Linux checkout dirty")
    # Complete actual source checkout, not the earlier sparse host fixture.
    require(all((linux / path).is_file() for path in
                ("Makefile", "init/main.c", "kernel/rcu/tree.c", "arch/x86/Kconfig")), "full Linux checkout")
    for path, (before, _) in previous.IMAGES.items():
        if path.startswith("drivers/md/"):
            continue
        if before is None:
            require(not (linux / path).exists(), "unexpected carrier preimage")
        else:
            pin(linux / path, before)
    for path, expected in previous.GLUE_PREIMAGES.items():
        pin(linux / path, expected)
    for path, expected in INPUTS.items():
        if path in (BROKER, HEADER, OWNER):
            destination = linux / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            require(not destination.exists(), "broker input exists")
            destination.write_bytes(git(ROOT, "show", FREEZE + ":" + path))
            pin(destination, expected)
    git(linux, "add", "--", BROKER, HEADER, OWNER)
    chain = [(Path(name).name, expected, previous.PATCH_STAGES[name])
             for name, expected in previous.PATCHES.items() if "dm-selected" not in name] + ADDITIONAL
    apply = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
    state["stages"] = {}
    for name, expected, images in chain:
        path = ROOT / "tests/tools" / name
        pin(path, expected)
        step(output, name + "-check", apply + ["--check", str(path)], linux)
        step(output, name + "-apply", apply + [str(path)], linux)
        for changed, after in images.items():
            pin(linux / changed, after)
        state["stages"][name] = {"patch": expected, "images": images}
    for path, expected in PRE.items():
        pin(linux / path, expected)
    require(not git(linux, "diff", "--name-only"), "unexpected unstaged preimage")
    patch = ROOT / PATCH
    pin(patch, PATCH_PIN)
    # Zero-context packaging keeps the repository diff whitespace-clean.
    # Exact whole-file pre/postimages remain mandatory for each raw hunk.
    new_apply = ["git", "apply", "--unidiff-zero", "--whitespace=error"]
    step(output, "r101-check", new_apply + ["--check", str(patch)], linux)
    step(output, "r101-apply", new_apply + [str(patch)], linux)
    require(set(git(linux, "diff", "--name-only").decode().splitlines()) == set(POST), "R101 changed path census")
    step(output, "r101-diff-check", ["git", "diff", "--check"], linux)
    for path, expected in POST.items():
        pin(linux / path, expected)
    (output / "actual-r101.diff").write_bytes(git(linux, "diff", "--binary"))
    git(linux, "add", "--", *POST)
    step(output, "r101-reverse-check", apply + ["--reverse", "--check", str(patch)], linux)
    state["actual_preimages"] = PRE
    state["actual_postimages"] = {path: image(linux / path) for path in POST}
    state["stage"] = "PASS"
    return previous, extract

def host(linux, output, state, extractor):
    host_dir = output / "host-build"
    host_dir.mkdir()
    include = host_dir / "include/linux"
    include.mkdir(parents=True)
    for name in ("types", "atomic", "rcupdate", "build_bug", "limits", "string", "export", "kernel", "mutex", "slab", "vmalloc"):
        (include / (name + ".h")).write_text('#include "native-observation-owner-host-model.h"\n')
    (host_dir / "include/crypto").mkdir()
    (host_dir / "include/crypto/sha2.h").write_text('#include "native-observation-owner-host-model.h"\n')
    kernel = linux / "src/kernel"
    for path, expected in INPUTS.items():
        if path in (BROKER, HEADER, OWNER):
            continue
        destination = kernel / Path(path).name
        destination.write_bytes(git(ROOT, "show", FREEZE + ":" + path))
        pin(destination, expected)
    for name, expected in FIXTURES.items():
        path = host_dir / name
        path.write_bytes(git(ROOT, "show", FREEZE + ":tests/runtime/native/fixtures/" + name))
        pin(path, expected)
    header = (linux / CARRIER).read_text()
    mm = (linux / MM).read_text()
    types = []
    for name in ("swapz_mm_route", "swapz_mm_trial_scope", "swapz_mm_carrier"):
        match = re.search(r"(?ms)^struct " + name + r" \{.*?^\};", header)
        require(match is not None, "carrier type " + name)
        types.append(match[0])
    (host_dir / "r101-types.h").write_text("\n".join(types) + "\n")
    declarations = mm[mm.index("static DEFINE_MUTEX(swapz_mm_scope_lock)"):
                      mm.index("#else\nstatic const struct swapz_mm_trial_scope swapz_mm_scope;")]
    fn = extractor.function
    geometry_start = header.index("static inline bool swapz_mm_bio_matches(")
    geometry = header[geometry_start:header.index("\n}\n", geometry_start) + 3]
    before_geometry = ("swapz_mm_scope_matches", "swapz_mm_scope_valid", "swapz_mm_trial_scope_publish",
                       "swapz_mm_trial_scope_stop_capture", "swapz_mm_trial_scope_revoke",
                       "swapz_mm_trial_scope_bind_permitted", "swapz_mm_trial_scope_matches_route",
                       "swapz_mm_trial_scope_matches_origin", "swapz_mm_capture_permitted")
    after_geometry = ("swapz_mm_candidate_get", "swapz_mm_candidate_observation",
                      "swapz_mm_observation_capture", "swapz_mm_observation_bind",
                      "swapz_mm_observation_endio", "swapz_mm_observation_release")
    (host_dir / "r101-extracted.h").write_text(declarations +
        "\n".join(fn(mm, name) for name in before_geometry) + geometry +
        "\n".join(fn(mm, name) for name in after_geometry))
    # The actual page_io call site, not a rewritten host page_io function.
    extractor.ordered(fn((linux / PAGE).read_text(), "swap_bdev_submit_write"),
                      ["swapz_mm_bio_matches(", "swapz_mm_observation_bind(",
                       "rcu_assign_pointer(bio->bi_swapz_original", "submit_bio"])
    extractor.ordered(fn(mm, "swapz_mm_capture"),
                      ["swapz_mm_eligible(", "rcu_dereference(swapz_mm_capture_scope)",
                       "entry->original_cookie ="])
    extractor.ordered(fn(mm, "swapz_mm_route_try"),
                      ["rcu_dereference(swapz_mm_capture_scope)", "swapz_mm_scope_matches(",
                       "swapz_ticket_broker_try_get("])
    common = ["-std=c2x", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
              "-DSWAPZ_NATIVE_OBSERVATION_ADAPTER", "-DSWAPZ_TRIAL_OBSERVATION",
              "-DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST", "-DSWAPZ_ORIGINAL_TICKET_TEST=1",
              "-DSWAPZ_TICKET_MODULE_HOST_TEST=1", "-DSWAPZ_TICKET_OWNER_HOST_TEST=1",
              '-DSWAPZ_OBSERVATION_BUILD_SOURCE="' + state["source"] + '"',
              "-O2", "-g", "-Wall", "-Wextra", "-Wconversion", "-Wsign-conversion",
              "-Wshadow", "-Wpedantic", "-Werror", "-fsanitize=address,undefined",
              "-fno-omit-frame-pointer", "-fno-sanitize-recover=all", "-fno-pie", "-pthread",
              "-I" + str(host_dir / "include"), "-I" + str(host_dir), "-I" + str(kernel)]
    fixture = ROOT / "tests/runtime/native/fixtures/round101-mm-retirement.c"
    state["fixture"] = image(fixture)
    state["host"] = {}
    for compiler in ("gcc", "clang"):
        state["host"][compiler] = {"version": step(output, compiler + "-version",
            [compiler, "--version"]).decode().splitlines()[0]}
        binary = host_dir / (compiler + "-r101")
        step(output, compiler + "-host-compile", [compiler, *common, "-no-pie",
             str(kernel / "native-observation-adapter.c"), str(kernel / "native-observation-owner.c"),
             str(kernel / "codec.c"), str(fixture), "-lcrypto", "-o", str(binary)])
        for mode in ("worker", "explicit"):
            result = subprocess.run([str(binary), mode], timeout=30, check=False,
                capture_output=True, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                           "UBSAN_OPTIONS": "halt_on_error=1"})
            (output / (compiler + "-" + mode + ".log")).write_bytes(result.stdout + result.stderr)
            match = re.fullmatch(rb"R101_A11_HOST_ONLY mode=" + mode.encode() +
                                 rb" checks=(\d+) retries=(\d+)\n", result.stdout)
            require(result.returncode == 0 and not result.stderr and match and int(match[2]) == 1,
                    compiler + "/" + mode + ": " + result.stderr.decode(errors="replace")[:200])
            state["host"][compiler][mode] = {"checks": int(match[1]), "retries": int(match[2])}
            print(compiler, result.stdout.decode().strip(), flush=True)
        binary.unlink()
    state["host_status"] = "PASS_CHANGED_CASES_HOST_MODELS"

def native(linux, build, output, state, previous):
    glue = linux / GLUE
    glue.mkdir()
    kernel = linux / "src/kernel"
    for path in INPUTS:
        name = Path(path).name
        data = (kernel / name).read_bytes()
        (glue / name).write_bytes(data)
        pin(glue / name, POST.get(path, INPUTS[path]))
    (glue / "Makefile").write_text("obj-y += zswap-original-ticket.o\n")
    with (linux / "mm/Kconfig").open("a") as destination:
        destination.write(previous.KCONFIG)
    with (linux / "mm/Makefile").open("a") as destination:
        destination.write(previous.MAKEFILE.replace("round098-swapz", "round101-swapz"))
    guards = ("-DSWAPZ_ORIGINAL_TICKET_TEST -DSWAPZ_NATIVE_OBSERVATION_ADAPTER "
              "-DSWAPZ_TRIAL_OBSERVATION -DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST -Werror -I" + str(glue))
    build.mkdir()
    make = ["make", "-C", str(linux), "O=" + str(build), "ARCH=x86_64", "CC=gcc", "KCFLAGS=" + guards]
    step(output, "allnoconfig", make + ["allnoconfig"])
    config = ["bash", str(linux / "scripts/config"), "--file", str(build / ".config")]
    for key in previous.REQUIRED:
        config += ["--enable", key]
    for key in ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT",
                "MODULE_SIG", "DEBUG_INFO", "DEBUG_INFO_BTF", "TINY_RCU"):
        config += ["--disable", key]
    config += ["--set-val", "NR_CPUS", "4"]
    step(output, "set-config", config)
    step(output, "olddefconfig", make + ["olddefconfig"])
    config_data = (build / ".config").read_bytes()
    (output / "effective.config").write_bytes(config_data)
    config_lines = config_data.decode().splitlines()
    for key in previous.REQUIRED:
        require("CONFIG_" + key + "=y" in config_lines, "missing effective config " + key)
    require("CONFIG_NR_CPUS=4" in config_lines and "CONFIG_TINY_RCU=y" not in config_lines and
            "CONFIG_ZSWAP_DEFAULT_ON=y" not in config_lines, "effective config SMP/default-off")
    state["config_sha256"] = hashlib.sha256(config_data).hexdigest()
    state["config"] = {"SMP": True, "TREE_RCU": True, "TINY_RCU": False, "NR_CPUS": 4}
    state["native_status"] = "RUNNING"
    state["objects"] = {}
    try:
        step(output, "changed-objects", make + ["-j2", *OBJECTS], timeout=1000)
    finally:
        for path in OBJECTS:
            original = build / path
            if original.is_file():
                state["objects"][path] = image(original)
                dest = output / "objects" / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(original.read_bytes())
    require(set(state["objects"]) == set(OBJECTS), "missing changed objects")
    for path, symbols in ((OBJECTS[0], ("swapz_mm_trial_scope_stop_capture", "swapz_mm_trial_scope_revoke",
                                      "swapz_mm_trial_scope_bind_permitted")),
                          (OBJECTS[1], ()), (OBJECTS[2], ("swapz_mm_broker_owner_retired", "owner_retry_workfn"))):
        actual = subprocess.check_output(["nm", "--defined-only", str(build / path)], text=True)
        (output / (Path(path).name + ".defined")).write_text(actual)
        require(all(re.search(r"\b" + symbol + r"\b", actual) for symbol in symbols), "missing new symbol " + path)
        (output / (Path(path).name + ".relocations")).write_bytes(
            subprocess.check_output(["readelf", "-Wr", str(build / path)]))
    for path, expected in POST.items():
        pin(linux / path, expected)
    for path in (BROKER, OWNER, HEADER):
        pin(glue / Path(path).name, POST[path])
    require(not (build / "vmlinux").exists() and not (build / "Module.symvers").exists(), "unexpected full link")
    state["native_status"] = "PASS_DIRECTED_OBJECTS_ONLY"

def main():
    linux, build, output = (Path(value).resolve() for value in sys.argv[1:4])
    os.umask(0o077)
    output.mkdir(parents=True, exist_ok=True)
    state = {"source": git(ROOT, "rev-parse", "HEAD").decode().strip(),
             "parent": git(ROOT, "rev-parse", "HEAD^").decode().strip(),
             "freeze": FREEZE, "linux": LINUX, "status": "FAIL",
             "stage": "NOT_RUN", "host_status": "NOT_RUN", "native_status": "NOT_RUN",
             "first_error": None, "auth": 0, "phase_a": "BLOCKED",
             "compressed_handoff": False, "forced_raw": False, "import": False,
             "full_link": False, "module_load": False, "vm": False, "physical_io": False}
    failed = False
    try:
        previous, extractor = stage(linux, output, state)
        try:
            host(linux, output, state, extractor)
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
            failed = True
            state["host_status"] = "FAIL"
            state["first_error"] = str(error)[:450]
            print("R101_A11_FIRST_ERROR host:", state["first_error"], file=sys.stderr, flush=True)
        # Native build is the independent directed lane, not a retry of host.
        try:
            native(linux, build, output, state, previous)
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
            failed = True
            state["native_status"] = "FAIL"
            state["native_error"] = str(error)[:450]
            if state["first_error"] is None:
                state["first_error"] = state["native_error"]
            print("R101_A11_NATIVE_ERROR:", state["native_error"], file=sys.stderr, flush=True)
        if not failed:
            state["status"] = "PASS_CHANGED_OBJECTS_AND_HOST_ONLY"
            print("R101_A11_PASS AUTH0 DIRECTED_ONLY", flush=True)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        failed = True
        state["first_error"] = str(error)[:450]
        print("R101_A11_FIRST_ERROR stage:", state["first_error"], file=sys.stderr, flush=True)
    finally:
        (output / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return 2 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
