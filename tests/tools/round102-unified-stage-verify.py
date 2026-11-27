#!/usr/bin/env python3
"""R102 frozen unified source stage: no compiler, link, module or device."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FREEZE = "d2baba1bda02b78eb7df265d22c5e9dbee09e2b1"
TARGET = "46c2cb832ff0071a028a27b35f63daa84f29914f"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
STAGE_TOOL = "tests/tools/round098-smp-directed-native-compile-verify.py"
STAGE_PIN = "96e6750971c182dfe87e6e57eac048c7c3a529b6"
RETIRE_TOOL = "tests/tools/round101-mm-retirement-verify.py"
RETIRE_PIN = "4ead4211a1c33cb003cc75571c7d1e80d06828b8"
TAIL = (
    ("round098-original-mm-scope-events.patch", "3832b6aa76b783f3790b869cf40512b114d66cd6",
     {"mm/zswap.c": "128495cf9b35d37b93db1b165dc1562de94b5b89",
      "include/linux/swapz_mm_carrier.h": "7083f7acdb439022a073c22261b7541d15806e5e"},
     {"mm/zswap.c": "cad0d9ba05cd614b95b335ed0c7d70d9e69d00f0",
      "include/linux/swapz_mm_carrier.h": "5e11fe42a9dce147cdaf7f30c43b1c8b6feff59a"}),
    ("round098-original-dm-upper-observation.patch", "5b0b0a3582b16e54046f1f11355e6814c9ca4e1f",
     {"drivers/md/dm.c": "e51af0d14465e92323970a84c1d62df3a8eb61c3"},
     {"drivers/md/dm.c": "f0c0cd4add03bf2b6f9bf37997444ecd08bbb83b",
      "drivers/md/dm-core.h": "a010598cb4e884a78f06ab66ab4488a1a7f9c418"}),
)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    os.umask(0o077)
    frozen, baseline, linux, evidence = (Path(arg).resolve() for arg in sys.argv[1:])
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = {"status": "FAIL", "source_freeze": FREEZE, "linux": LINUX,
             "AUTH": 0, "phase_a": "BLOCKED", "physical_io": False,
             "compile": "NOT_RUN", "link": "NOT_RUN", "completed_steps": [],
             "first_error": None}
    try:
        import hashlib
        def blob(data):
            return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        for relative, expected in ((STAGE_TOOL, STAGE_PIN), (RETIRE_TOOL, RETIRE_PIN)):
            path = frozen / relative
            if not path.is_file() or path.is_symlink() or blob(path.read_bytes()) != expected:
                raise RuntimeError("frozen helper pin " + relative)
        stage = load(frozen / STAGE_TOOL, "frozen_r098")
        retire = load(frozen / RETIRE_TOOL, "frozen_r101")
        require, pin, git = stage.require, stage.pin, stage.git
        state["tested_commit"] = git(ROOT, "rev-parse", "HEAD").decode().strip()
        require(git(frozen, "rev-parse", "HEAD").decode().strip() == FREEZE and
                not git(frozen, "status", "--porcelain", "--untracked-files=all"),
                "frozen checkout identity/cleanliness")
        require(all((linux / name).is_file() for name in
                    ("Makefile", "init/main.c", "kernel/rcu/tree.c", "arch/x86/Kconfig")),
                "full Linux checkout")
        product = dict(stage.PRODUCT, **{"dm-target.c": TARGET})
        require({path.name for path in (frozen / "src/kernel").iterdir()} == set(product),
                "frozen product inventory")
        for name, expected in product.items():
            pin(frozen / "src/kernel" / name, expected)
        # The selected baseline is independently pinned by its original verifier.
        # Every product input except the corrected DM target is byte identical.
        with tempfile.TemporaryDirectory(prefix="r102-stage-") as scratch:
            module = Path(scratch) / "round102-product-module"
            stage.stage(state, evidence, baseline, linux, module)
            apply = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
            tails = list(TAIL) + [(Path(retire.PATCH).name, retire.PATCH_PIN, retire.PRE, retire.POST)]
            state["r102_tail"] = []
            for name, digest, before, after in tails:
                patch = frozen / "tests/tools" / name
                pin(patch, digest)
                # dm-core.h has a pristine Linux preimage, not an earlier overlay.
                pre = dict(before)
                for path in after.keys() - pre.keys():
                    pristine = git(linux, "show", "HEAD:" + path)
                    pre[path] = stage.blob(pristine)
                for path, expected in pre.items():
                    pin(linux / path, expected)
                stage.step(state, evidence, name + "-check", apply + ["--check", str(patch)], linux)
                require(not git(linux, "diff", "--name-only"), "apply check mutated source")
                stage.step(state, evidence, name + "-apply", apply + [str(patch)], linux)
                for path, expected in after.items():
                    pin(linux / path, expected)
                stage.step(state, evidence, name + "-reverse-check",
                           apply + ["--reverse", "--check", str(patch)], linux)
                stage.step(state, evidence, name + "-reverse",
                           apply + ["--reverse", str(patch)], linux)
                for path, expected in pre.items():
                    pin(linux / path, expected)
                stage.step(state, evidence, name + "-reapply", apply + [str(patch)], linux)
                for path, expected in after.items():
                    pin(linux / path, expected)
                state["r102_tail"].append({"patch": name, "blob": digest,
                    "preimages": pre, "postimages": after})
            # Preserve the actual historical raw index, with new raw files
            # materialized from the frozen overlays rather than stale copies.
            glue = linux / stage.GLUE_DIR
            raw = {path: stage.final_raw_pin(path) for path in
                   set(stage.IMAGES) | set(stage.R092_IMAGES) | set(stage.R096_IMAGES)}
            for _, _, _, after in tails:
                raw.update(after)
            for path, expected in raw.items():
                pin(linux / path, expected)
            # Verify ALL early overlays in reverse order on a disposable index
            # and worktree copy of only touched raw files. No second Linux tree.
            reverse_root = Path(scratch) / "raw-reverse"
            reverse_root.mkdir()
            for path in raw:
                dest = reverse_root / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(linux / path, dest)
            historical = [(path, digest, stage.PATCH_STAGES[path]) for path, digest in stage.PATCHES.items()]
            historical += [(path, digest, {key: pair[1] for key, pair in images.items()})
                           for path, digest, images in (
                               (stage.R092_OVERLAY, stage.R092_OVERLAY_PIN, stage.R092_IMAGES),
                               (stage.R094_OVERLAY, stage.R094_OVERLAY_PIN, stage.R094_IMAGES),
                               (stage.R095_CAPTURE_OFF, stage.R095_CAPTURE_OFF_PIN, stage.R095_IMAGES),
                               (stage.R096_RETRY, stage.R096_RETRY_PIN, stage.R096_IMAGES),
                               (stage.R097_PRODUCER, stage.R097_PRODUCER_PIN, stage.R097_IMAGES))]
            chain = historical + [("tests/tools/" + name, digest, after) for name, digest, _, after in tails]
            plain = ["git", "apply", "--unidiff-zero", "--whitespace=error"]
            for relative, digest, after in reversed(chain):
                patch = frozen / relative
                pin(patch, digest)
                for path, expected in after.items():
                    pin(reverse_root / path, expected)
                stage.step(state, evidence, Path(relative).stem + "-full-reverse",
                           plain + ["--reverse", str(patch)], reverse_root)
            pristine = {path: pair[0] for path, pair in stage.IMAGES.items()}
            pristine["drivers/md/dm-core.h"] = stage.blob(git(linux, "show", "HEAD:drivers/md/dm-core.h"))
            pristine.update({"src/kernel/" + name: stage.PRODUCT[name]
                             for name in (*stage.BROKER_INPUTS, stage.OWNER_INC)})
            for path, expected in pristine.items():
                if expected is None:
                    require(not (reverse_root / path).exists(), "reverse new file retained")
                else:
                    pin(reverse_root / path, expected)
            for relative, digest, after in chain:
                patch = frozen / relative
                stage.step(state, evidence, Path(relative).stem + "-full-reapply",
                           plain + [str(patch)], reverse_root)
                for path, expected in after.items():
                    pin(reverse_root / path, expected)
            for path, expected in raw.items():
                pin(reverse_root / path, expected)
            # The selected owner/adapter are built-in only; the standalone
            # recorder implementation remains unselected. Broker ABI matches.
            for name in (*stage.BROKER_INPUTS, stage.OWNER_INC):
                path = "src/kernel/" + name
                for dest in (glue / name, module / name):
                    shutil.copyfile(linux / path, dest)
                    pin(dest, raw[path])
            shutil.copyfile(frozen / "src/kernel/dm-target.c", module / "dm-target.c")
            pin(module / "dm-target.c", TARGET)
            for name in stage.RECORDER:
                pin(glue / name, product[name])
                require(not (module / name).exists(), "duplicate recorder " + name)
            for name in stage.UNSELECTED:
                require(not (glue / name).exists() and not (module / name).exists(),
                        "unselected recorder included")
            makefile = glue / "Makefile"
            content = makefile.read_text()
            require(content.count(stage.BASELINE) == 1, "recorder build source anchor")
            makefile.write_text(content.replace(stage.BASELINE, FREEZE, 1))
            git(linux, "add", "--", stage.GLUE_DIR)
            require(not git(linux, "diff", "--name-only"), "unstaged final source")
            additions = set(stage.GLUE_PREIMAGES) | {
                stage.GLUE_DIR + "/" + name for name in (*stage.MM_INPUTS, "Makefile")}
            require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
                    == set(raw) | additions, "unified staged path census")
            stage.step(state, evidence, "unified-source-diff-check",
                       ["git", "diff", "--cached", "--check"], linux)
            state["authoritative_manifest"] = {
                "frozen_product": product, "linux_pristine": pristine,
                "ordered_chain": [{"path": path, "blob": digest, "postimages": post}
                                  for path, digest, post in chain],
                "raw_final": {path: stage.image(linux / path) for path in sorted(raw)},
                "glue_final": {path: stage.image(linux / path) for path in sorted(additions)},
                "module_final": {p.name: stage.image(p) for p in sorted(module.iterdir())},
                "observation_build_source": FREEZE,
                "selected_recorder": list(stage.RECORDER), "excluded_recorder": sorted(stage.UNSELECTED),
                "kernel_guards": stage.GUARDS + stage.OBSERVATION_GUARDS,
                "module_guards": stage.MODULE_GUARDS + stage.OBSERVATION_GUARDS +
                    " -DSWAPZ_ROUND098_SCOPED_TARGET_TEST",
                "native_compilation": "NOT_RUN"}
            (evidence / "unified-source.diff").write_bytes(git(linux, "diff", "--cached", "--binary"))
            state["status"] = "PASS_STAGE_ONLY"
            print("R102_A11_UNIFIED_STAGE_PASS AUTH0 NO_COMPILE", flush=True)
        return 0
    except Exception as error:
        state["first_error"] = str(error).split("\n", 1)[0][:350]
        print("R102_A11_FIRST_ERROR " + state["first_error"], file=sys.stderr)
        return 1
    finally:
        # The older helper also writes preliminary manifests; this final file
        # alone binds the entire unified stage including the three tail overlays.
        (evidence / "unified-manifest.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
