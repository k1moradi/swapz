#!/usr/bin/env python3
"""Compose accepted R109 connected sources and the exact MM preflight overlay.

Source staging only. No build, activation, admission or runtime operation.
Caller supplies separate clean pinned checkouts and empty scratch paths.
"""
import importlib.util
from pathlib import Path

FREEZE = "1ede7cfc7be8e870cadf34afec7a655d4630750e"
TREE = "aca15a12f4691651fd6918935816d67620ac571e"
CONNECTED_FREEZE = "6394bf9aec7709744caf294f8bd7e935ca481dcd"
CONNECTED = "tests/tools/round109-connected-build-verify.py"
CONNECTED_PIN = "dc6478212a008c9e2eea24b022b69ad17b503366"
PATCH = "tests/tools/round109-original-mm-area-preflight.patch"
PATCH_PIN = "3c38d165804cb62c7f0d99e27e1ed303987ec90e"
GUARD = "SWAPZ_ROUND109_AREA_PREFLIGHT_TEST"
IMAGES = {
    "mm/swapfile.c": ("d20a7f0003405bd1450cc52af63a773c91ee86b6",
                      "8b9826f09f7b3127d4cb739a072102763d8e1ecd"),
    "include/linux/swapz_mm_carrier.h": ("bd88db905e5009e0e6161cad1d09b6d33bde2560",
                                      "8d369c402780e06ffd317919acdd6bbd4802646e"),
}


def stage(state, evidence, inputs, frozen, historical, baseline, linux, module):
    """Use the successful connected stage, then apply the accepted MM delta.

    The caller owns checkout and scratch lifetimes; no concurrent staging.
    Return the historical build helper, not a qualification result.
    """
    import hashlib

    def pin(path, expected):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("missing pinned input " + str(path))
        data = path.read_bytes()
        digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if digest != expected:
            raise RuntimeError("blob mismatch " + str(path))

    verifier = inputs / CONNECTED
    patch = inputs / PATCH
    pin(verifier, CONNECTED_PIN)
    pin(patch, PATCH_PIN)
    spec = importlib.util.spec_from_file_location("r110_frozen_connected", verifier)
    connected = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(connected)
    require, git = connected.require, connected.git
    require(git(inputs, "rev-parse", "HEAD").decode().strip() == FREEZE and
            git(inputs, "rev-parse", "HEAD^{tree}").decode().strip() == TREE,
            "R110 frozen overlay checkout")
    require(not git(inputs, "status", "--porcelain", "--untracked-files=all"),
            "dirty R110 overlay checkout")
    require(connected.FREEZE == CONNECTED_FREEZE and
            git(inputs, "rev-parse", "HEAD:src/kernel") ==
            git(frozen, "rev-parse", "HEAD:src/kernel"),
            "connected product subtree drift")
    previous = {"completed_steps": []}
    previous_evidence = evidence / "r109-connected"
    previous_evidence.mkdir()
    helper = connected.stage(previous, previous_evidence, frozen, historical,
                             baseline, linux, module)
    require(previous["stage"] == "PASS_CONNECTED_SOURCE", "R109 stage only")
    state["r109_connected_stage"] = previous
    for name, images in IMAGES.items():
        pin(linux / name, images[0])
    before = set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
    command = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
    for label, args, side in (
        ("check", ["--check"], 0), ("apply", [], 1),
        ("reverse-check", ["--reverse", "--check"], 1),
        ("reverse", ["--reverse"], 0), ("reapply", [], 1),
    ):
        helper.step(state, evidence, "r110-area-" + label, command + args + [str(patch)], linux)
        for name, images in IMAGES.items():
            pin(linux / name, images[side])
    after = set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
    require(after == before | IMAGES.keys(), "R110 staged path census")
    require(not git(linux, "diff", "--name-only") and
            not git(linux, "ls-files", "--others", "--exclude-standard"),
            "unstaged/untracked Linux source")
    helper.step(state, evidence, "r110-area-diff-check",
                ["git", "diff", "--cached", "--check"], linux)
    for name, metadata in previous["linux_stage"].items():
        pin(linux / name, IMAGES[name][1] if name in IMAGES else metadata["blob"])
    for name, metadata in previous["module_stage"].items():
        pin(module / name, metadata["blob"])
    state["linux_stage"] = {name: helper.image(linux / name) for name in sorted(after)}
    state["module_stage"] = previous["module_stage"]
    state["area_preflight_guard"] = GUARD
    state["stage"] = "PASS_R110_COMPOSED_SOURCE_ONLY"
    (evidence / "r110-composed-source.diff").write_bytes(
        git(linux, "diff", "--cached", "--binary"))
    return helper
