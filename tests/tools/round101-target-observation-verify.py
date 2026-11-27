#!/usr/bin/env python3
"""R101 target-only exact stage and directed object; never link/load/boot."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / "tests/tools/round098-smp-directed-native-compile-verify.py"
STAGE_PIN = "96e6750971c182dfe87e6e57eac048c7c3a529b6"
TARGET_PIN = "ef9aa4208cd2f8783ed6eb6c03f91970cf7cad2a"
PATCHES = {
    "round098-original-mm-scope-events.patch": ("3832b6aa76b783f3790b869cf40512b114d66cd6", {
        "mm/zswap.c": "cad0d9ba05cd614b95b335ed0c7d70d9e69d00f0",
        "include/linux/swapz_mm_carrier.h": "5e11fe42a9dce147cdaf7f30c43b1c8b6feff59a"}),
    "round098-original-dm-upper-observation.patch": ("5b0b0a3582b16e54046f1f11355e6814c9ca4e1f", {
        "drivers/md/dm.c": "f0c0cd4add03bf2b6f9bf37997444ecd08bbb83b",
        "drivers/md/dm-core.h": "a010598cb4e884a78f06ab66ab4488a1a7f9c418"}),
}

def main():
    baseline, linux, evidence = map(lambda arg: Path(arg).resolve(), sys.argv[1:])
    evidence.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("frozen_stage", STAGE)
    stage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    require = stage.require
    pin = stage.pin
    state = {"source": stage.git(ROOT, "rev-parse", "HEAD").decode().strip(),
             "status": "FAIL", "completed_steps": [], "AUTH": 0, "phase_a": "BLOCKED",
             "native_link": "NOT_RUN", "first_error": None}
    try:
        pin(STAGE, STAGE_PIN)
        target = ROOT / "src/kernel/dm-target.c"
        pin(target, TARGET_PIN)
        source = target.read_text()
        with tempfile.TemporaryDirectory(prefix="r101-target-") as tmp:
            scratch = Path(tmp)
            module = scratch / "round098-product-module"
            out = scratch / "round098-x86-build"
            stage.stage(state, evidence, baseline, linux, module)
            apply = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
            for name, (digest, post) in PATCHES.items():
                patch = ROOT / "tests/tools" / name
                pin(patch, digest)
                stage.step(state,evidence,name+"-check",apply+["--check",str(patch)],linux)
                stage.step(state,evidence,name+"-apply",apply+[str(patch)],linux)
                stage.step(state,evidence,name+"-reverse",apply+["--reverse","--check",str(patch)],linux)
                for path, expected in post.items():
                    pin(linux / path, expected)
            pin(linux / "mm/page_io.c", "08c11d2f9a16a322093b305afa10ba011f67fc2b")
            shutil.copyfile(target, module / "dm-target.c")
            pin(module / "dm-target.c", TARGET_PIN)
            state["target"] = stage.image(module / "dm-target.c")
            state["r098_postimages"] = {path: stage.image(linux / path)
                for _, post in PATCHES.values() for path in post}
            def function(text, name):
                match = list(re.finditer(r"(?m)^(?:static )?(?:bool|int|void|u32) " +
                                        name + r"\([^;]+?\)\n\{", text))
                require(len(match) == 1, "function anchor " + name)
                start = match[0].start()
                end = text.index("\n}", match[0].end()) + 2
                return text[start:end] + "\n"
            core = (linux / "drivers/md/dm.c").read_text()
            map_body = function(source, "swapz_map")
            read = function(source, "swapz_read")
            require(map_body.count("entry = dm_per_bio_data(bio, sizeof(*entry));") == 1,
                    "single real map descriptor lookup")
            require(map_body.index("entry->observation_operation = 0;") <
                    map_body.index("if (map_refusal != DM_MAPIO_SUBMITTED)") <
                    map_body.index("INIT_LIST_HEAD(&entry->list);"), "reset before refusal/FIFO")
            require(map_body.index("list_add_tail(&entry->list, &ctx->incoming);") <
                    map_body.index("swapz_scope_observe_plain_accept_locked(ctx, entry,"),
                    "core binding after actual FIFO admission")
            require(map_body.count("swapz_scope_observe_plain_accept_locked(ctx, entry,") == 1,
                    "unique plain admission")
            require("SWAPZ_OBS_UPPER_ENDIO" not in source, "target must not emit original ACK")
            require(read.index("swapz_round097_read_original_pinned(") <
                    read.index("swapz_copy_bio_accounted(") <
                    read.index("swapz_shared_original_put(&ctx->authority, original_pin)"),
                    "pin through actual final BIO copy")
            require("SWAPZ_OBS_ORACLE" not in read, "no independent read oracle")
            begin = read.index("\terror = swapz_copy_bio_accounted(")
            end = read.index("\n\tif (!error)\n\t\tctx->logical_read_bytes",begin)
            final_copy = read[begin:end]
            require(final_copy.index("swapz_scope_observe_invalid();") <
                    final_copy.index("swapz_shared_original_put("), "loss before pin release")
            functions = [function(source,name) for name in
                ("swapz_scope_status","swapz_scope_observation_live","swapz_scope_observe_invalid",
                 "swapz_scope_observe_clone","swapz_scope_route_ready_locked",
                 "swapz_scope_observation_selected_locked")]
            functions += [function(core,name) for name in
                ("dm_swapz_original_observation_endio","dm_swapz_trial_observation_origin")]
            functions += [function(source,name) for name in
                ("swapz_scope_observe_plain_accept_locked","swapz_end_io")]
            functions += ["static int actual_final_copy(struct swapz_dm *ctx, struct bio *bio, u64 original_pin)\n{\n"
                          "\tint error;\n"+final_copy+"\n\treturn error;\n}\n"]
            (scratch/"actual-target-core.h").write_text("\n".join(functions))
            state["host"] = {}
            for compiler in ("gcc","clang"):
                binary = scratch / compiler
                stage.step(state,evidence,compiler+"-host-compile",
                    [compiler,"-std=gnu11","-DSWAPZ_ROUND090_SELECTED_DM_COMPOSITION_TEST",
                     "-O2","-g","-Wall","-Wextra","-Werror","-Wconversion","-Wshadow",
                     "-fsanitize=address,undefined","-fno-sanitize-recover=all","-fno-pie","-no-pie",
                     "-I"+str(scratch),str(ROOT/"tests/runtime/native/fixtures/round101-target-observation.c"),
                     "-o",str(binary)],timeout=90)
                stage.step(state,evidence,compiler+"-host-execute",[str(binary)],timeout=30)
                result = (evidence/(compiler+"-host-execute.log")).read_text()
                match = re.fullmatch(r"PASS target/core serial host checks=(\d+) AUTH=0\n", result)
                require(match is not None, compiler+" host result")
                state["host"][compiler] = int(match[1])
                print(compiler,result.strip(),flush=True)
            # Only the changed target object. All other source is staged from
            # frozen pins; no peer R101 changes or full kernel/module link.
            stage.prerequisites(state,evidence)
            guards = stage.GUARDS + stage.OBSERVATION_GUARDS + " -DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST"
            module_guards = stage.MODULE_GUARDS + stage.OBSERVATION_GUARDS + \
                " -DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST -DSWAPZ_ROUND098_SCOPED_TARGET_TEST"
            include = " -I"+str(linux/stage.GLUE_DIR)
            make = ["make","-C",str(linux),"O="+str(out),"ARCH=x86_64","CC=gcc"]
            out.mkdir()
            stage.step(state,evidence,"allnoconfig",make+["KCFLAGS="+guards+include,"allnoconfig"],timeout=120)
            config = ["bash",str(linux/"scripts/config"),"--file",str(out/".config")]
            for key in stage.REQUIRED:
                config += ["--enable",key]
            for key in ("ZSWAP_DEFAULT_ON","ZSWAP_SHRINKER_DEFAULT_ON","KUNIT","MODULE_SIG",
                        "DEBUG_INFO","DEBUG_INFO_BTF","TINY_RCU"):
                config += ["--disable",key]
            config += ["--set-val","NR_CPUS","4"]
            stage.step(state,evidence,"set-config",config)
            stage.step(state,evidence,"olddefconfig",make+["KCFLAGS="+guards+include,"olddefconfig"],timeout=120)
            shutil.copyfile(out/".config",evidence/"effective.config")
            effective = (out/".config").read_text().splitlines()
            require(all("CONFIG_"+key+"=y" in effective for key in stage.REQUIRED),"required config")
            require("CONFIG_NR_CPUS=4" in effective and "CONFIG_TINY_RCU=y" not in effective,"SMP/RCU config")
            state["config"] = stage.image(out/".config")
            state["module_guards"] = module_guards
            state["native_attempts"] = 1
            stage.step(state,evidence,"prepare",make+["KCFLAGS="+guards+include,"modules_prepare"],timeout=900)
            stage.step(state,evidence,"target-object",make+["KCFLAGS="+module_guards+include,
                       "M="+str(module),"-j2","dm-target.o"],timeout=900)
            obj = module/"dm-target.o"
            require(obj.is_file(),"missing target object")
            state["object"] = stage.image(obj)
            shutil.copyfile(obj,evidence/"dm-target.o")
            imports = subprocess.check_output(["nm","-u",str(obj)],text=True)
            (evidence/"target-imports.txt").write_text(imports)
            require("dm_swapz_trial_observation_origin" in imports,"core original import absent")
            require("swapz_trial_observation_append" in imports,"observation import absent")
            require("swapz_mm_trial_scope_matches_route" in imports,"scope query import absent")
            print("PASS directed target object",state["object"],flush=True)
        state["status"] = "PASS_HOST_AND_DIRECTED_TARGET_OBJECT_ONLY"
        return 0
    except (stage.Failure,OSError,ValueError,subprocess.SubprocessError) as error:
        state["first_error"] = str(error)[:400]
        print("FIRST_ERROR",state["first_error"],file=sys.stderr)
        return 1
    finally:
        stage.write_json(evidence/"results.json",state)

if __name__ == "__main__":
    sys.exit(main())
