#!/usr/bin/env python3
"""Audited, lease-guarded one-time cleanup of swapz's obsolete remote branches.

Preview by default. --apply requires an operator confirmation. Never modifies
main, working-tree files, local commits, or Linux swap devices. Run from an
up-to-date, clean main checkout; do not run while another agent is pushing.
"""

import argparse
import os
import re
import subprocess
import sys

REPOSITORY = "k1moradi/swapz"
AUDITED_MAIN = "e44ae5b099b9e0c2785a08398a4c65a1c1fcd3f2"

# Exact remote HEADs captured in the GitHub branch audit on 2026-11-15.
# Audited main is an ancestor floor; publication of this script or subsequent
# fast-forward commits does not grant authority to delete any new/moved branch.
# Do not replace these with dynamically discovered branch heads: an unexpected
# push must stop deletion rather than acquiring authority through discovery.
AUDITED_BRANCHES_TEXT = """\
agent/capacity-policy-unification d682d5f734553df42bfe34140752bdaa28acff10
agent/capacity-policy-unification-v2 62494f89b79f40f335b4e21f31cfdf331a65088e
agent11-physical-performance-methodology 322f521ac56ecfcc2e4b7fd9685ccdbc8d90d2cb
agent-13/gc-flush-no-publication-20261105 2d2be6316169c6da2f4bb5131b95766b8f899df4
agent-fix-max-capacity-report-fixture ac45bcfd5737df2677ac46f63e407d74f609bd0b
agent-physical-target-evidence d443a40940fccb39d43e402f0f57645e40dd686c
agent-physical-target-evidence-v2 5c282ff583a460c818b743966eb753e261cf0af1
agent-production-readiness-generator-fixture abf2c08f38dbff0e132754a546f5ffe36304080b
agent-production-readiness-lifecycle-gate daa008904a7ae79fbc1effb7f6d8d10b9fee88cb
agent-production-readiness-lifecycle-gate-11 c1ba267476f4759688aacb78e743ac06402eb34c
agent-release-evidence-crossbind 2df26199bc9f8d92d49ba0e116e315f5e14ac072
agent-release-evidence-crossbind-v2 a36081f0d3ebbc673baa77adf9a407bd9b0f4a3a
agent-release-target-crossbind 85f2e36d5f34c720dafdea8e1c9d97e57b85069a
agent-release-target-crossbind-v2 edb340dab6fb1c19030081a954dceba6929bce33
agent-release-target-crossbind-v3 7474555cd46df880009b10b386f05cf393aca13d
ci/independent-paired-io-sampler-20261114 9b7a327654dc7f04192005bb76ddae32fc9ee76d
ci/next-make-test-read-service 7892203d0d07ca680e1a8776e83fca3a8e5efece
ci/next-make-test-read-service-v2 8f450f522cb8dd90731b2ffbd473915aebeabb41
ci/owned-lower-progress-20261114 d328fa0606eb99eb7174a38f7db47153388977f0
ci/paired-raw-swap-contracts-20261114 e407f796934c3bf6b3a9c8fc1f88c01bf0b8d594
ci/psi-gate-diagnostics-20261114 de6b92c2d77e7ea9f34cd673460c7dfbd1f1dfb2
ci/raw-swap-psi-20261114 6ffbc84253bd5162b1c042dc156f6cd5c4fa2100
ci/raw-swap-tail-20261114 d710e761d3df964bd7723a1a25978c6b94df7345
ci/slow-swapz-psi-progress-20261114 00c975bcda3b176446bf94bc1dd44078f1e16f04
codex/id78-generation-raw-pack 4b15361a96f48a9215650df9e4ef8bb183f6adea
codex/ram-metadata-production-write 982c6bf0d948f34223173e6132e80731392e66c3
core2-cache-locality c23764e11e2a9b6c625efa3e29cd8f628ba79f4f
delta64-pack-cache-round 4884d47999c1ff2d5529cfb8169eb2ed91331c74
dev/independent-paired-io-sampler-20261114 7b8828272d4fac54f93c6731ba83316a7eca7689
dev/paired-owned-lower-progress-20261114 2cbd6cb0a69c9b7898d2253e5696599298969a80
dev/paired-raw-swap-baseline-20261114 59413036fb4289c1bc24227214462763f163b8ca
dev/raw-swap-pressure-diagnostics-20261114 023dce452118679243cf84f019b30e1b285dcfbc
dev/raw-swap-psi-recent-observations-20261114 9cb1d221287276cb336f505c6d4bdb728d4859ca
dev/slow-swapz-psi-progress-20261114 f03a47340b84beebe57b748bc41c516f3b7238eb
dev/swapz-psi-gate-diagnostics-20261114 fa4e565408a101344f5e0ed3181d0d998580e2d0
docs/deferred-read-coalescing-evidence fa0900a21783c2da2addd2a916361c5221cadda6
docs/fixed-delta64-rootless-contract 53562f10ad763cf2b82035f4981ddc71bfb658c4
evidence/class2-class4-class6 b7ebb80f84b5df878d74855322f63c435f2101c5
evidence/crc-publish-gc-probes cf0ce33cfe5eaacce794bdf84b08995d58314f55
evidence-followup-20261018 2d6590708023926e37164772321074f771b1e251
exp/delta64-parallel-prep fe8a0ec2ab19c7a4727c7c0f79f0c72d136f629d
exp/paired-perf-evidence 05c91399c28514fa7d57c44f2c241798ab189842
fix/completion-handoff-fault-gate deac1484b7c79b2d61ab51d1f83d10e1e5904c1d
fix/completion-handoff-fault-gate-v2 b22d70950d2a7324b3488795bcaca882a3b1bbfb
fix/fixed-delta64-make-interface-contract c7f6dd69f4a41e18da1a46ae6d8b698dbddbc6bf
fix/fixed-delta64-policy-contract 5cf065671f7877cc94cd50e747d1b2bcd93653d6
fix/make-interface-sequence-syntax 7da0d4fefd67e0a905762b7dba3049b826c799cc
fix/next-make-test-read-service 8eb33c948701a31ea23424ce2c11c45de119fb82
fix/privileged-checkout-ownership 588abb833bd31bac80e96d2b0e48d535d2e33646
fix/read-bypass-counter-telemetry 5ada987d6db314e745c5a5441b239551c1fb04cb
fix/6d2cf-predictor-read-superblock cfa13798b9aeae1524b29bb0582eb8252f745bdd
fix-alpha18-prep-crc-contract-20261018 c3d2ccd083876bc1f27e8392858f3478559e8f71
fix-native-prehash-init-20261018 ac7351330c7d600e6bae11d945385a14b3f8ebcd
id83-short-window-refinement 92af763434feb80e6ba235ba55414c577b1fffdb
perf/accepted-wave-overlap 97b51ac72cb1424d7a41867d8080463fd4f9e637
perf/bound-preparation-idle-fill e199ac5399808fbf3dcf470a92fa63f64e8c57fa
perf/direct-lz4-input-commit-attribution 45d8c46014ac7a7b6f38a6f333874d7c008aaaaa
perf/evidence-crc-publish-gc 2c1cfc0ff572bde0e1c8a32126f381f81395521b
perf/raw-copy-worker-cpu-attribution dcf0a18214086bf3dd5748a511422baf48ba991f
perf/revert-bound-add-copy-attribution c6d15ca56753610ed21d805333a49b6a291a36cb
perf/validated-publish-crc-gc-probes eb0b177dc5ed0001e0e97ef75b4788e5251499aa
policy/fixed-delta64-shuf8-lz4 bfdf6513050a49d43fc47f4aa6b4d094853b4a19
test/fix-direct-zero-contract 39e7787b784410140cf90d3fe3a08ad4d674f4f2
test/fix-lz4-histogram-raw-contract d63ab97c6cb104dc99c4792c207805e97e22d233
test/fix-prep-worker-cpu-contract ddb6fb0e074e8624466ab793aa5dbd4a6803e863
"""


class CleanupBlocked(Exception):
    """A fail-closed cleanup refusal."""


def run_git(*arguments: str, timeout: int = 45) -> str:
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    environment.setdefault("GIT_SSH_COMMAND",
                           "ssh -o BatchMode=yes -o ConnectTimeout=8")
    try:
        completed = subprocess.run(
            ["git", *arguments], check=False, capture_output=True,
            text=True, timeout=timeout, env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CleanupBlocked("Git command unavailable or timed out") from error
    if completed.returncode != 0:
        # Remote stderr may contain private network/credential details.
        raise CleanupBlocked(
            f"Git operation failed (exit {completed.returncode}); "
            "inspect authentication or branch permissions separately"
        )
    return completed.stdout.strip()


def expected_branches() -> dict[str, str]:
    branches = {}
    for line in AUDITED_BRANCHES_TEXT.splitlines():
        name, commit = line.split()
        if (name == "main" or name in branches or
                re.fullmatch(r"[a-zA-Z0-9_./-]+", name) is None or
                re.fullmatch(r"[0-9a-f]{40}", commit) is None):
            raise CleanupBlocked("The audited branch inventory is malformed")
        branches[name] = commit
    if len(branches) != 65:
        raise CleanupBlocked("The audited branch inventory is incomplete")
    return branches


def current_branches() -> dict[str, str]:
    output = run_git("ls-remote", "--heads", "origin", timeout=45)
    branches = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or not fields[1].startswith("refs/heads/"):
            raise CleanupBlocked("Remote reference inventory is malformed")
        sha, ref = fields
        name = ref[len("refs/heads/"):]
        if (name in branches or re.fullmatch(r"[0-9a-f]{40}", sha) is None or
                re.fullmatch(r"[a-zA-Z0-9_./-]+", name) is None):
            raise CleanupBlocked("Remote reference inventory contains invalid entries")
        branches[name] = sha
    return branches


def validate_inventory(expected: dict[str, str], actual: dict[str, str],
                       local_main: str) -> list[str]:
    if actual.get("main") != local_main:
        raise CleanupBlocked(
            "remote main differs from local main; synchronize before deletion"
        )
    unexpected = set(actual) - set(expected) - {"main"}
    if unexpected:
        raise CleanupBlocked(
            f"{len(unexpected)} new remote branches appeared; stop and audit them"
        )
    changed = [name for name, sha in expected.items()
               if name in actual and actual[name] != sha]
    if changed:
        raise CleanupBlocked(
            f"{len(changed)} audited branch heads moved; stop and re-review"
        )
    return sorted(name for name in expected if name in actual)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="delete audited obsolete remote branches")
    arguments = parser.parse_args()
    try:
        if run_git("symbolic-ref", "--quiet", "--short", "HEAD") != "main":
            raise CleanupBlocked("Run only from the main checkout")
        local_main = run_git("rev-parse", "HEAD")
        if re.fullmatch(r"[0-9a-f]{40}", local_main) is None:
            raise CleanupBlocked("Local main revision is malformed")
        # Publishing the tool advances main. Require the original audited
        # source to remain an ancestor, never a history rewrite.
        run_git("merge-base", "--is-ancestor", AUDITED_MAIN, local_main)
        if run_git("status", "--porcelain"):
            raise CleanupBlocked("Working tree/index is not clean; preserve owner changes")
        remote_pattern = (
            r"(?:git@github[.]com:|ssh://git@github[.]com/|"
            r"https://github[.]com/)" + re.escape(REPOSITORY) + r"(?:[.]git)?"
        )
        for option in ((), ("--push",)):
            if re.fullmatch(remote_pattern,
                            run_git("remote", "get-url", *option, "origin")) is None:
                raise CleanupBlocked("origin does not match the audited repository")
        expected = expected_branches()
        remaining = validate_inventory(expected, current_branches(), local_main)
        print(f"Verified audited main ancestor: {AUDITED_MAIN[:12]}")
        print(f"Verified aligned current main: {local_main}")
        print(f"Matched remote branches to delete: {len(remaining)}")
        for branch in remaining:
            print(f"  {branch}  {expected[branch][:12]}")
        if not arguments.apply:
            print("DRY RUN: Nothing deleted. Use --apply after reviewing the list.")
            return 0
        if not remaining:
            print("PASS: only remote main remains")
            return 0
        answer = input(f"Type 'DELETE {len(remaining)}' to proceed: ")
        if answer != f"DELETE {len(remaining)}":
            raise CleanupBlocked("Operator confirmation did not match")
        # Recheck the full inventory after operator input. Each deletion uses
        # an exact-head lease, so a racing push is never discarded silently.
        for index, branch in enumerate(remaining, start=1):
            # A concurrent main advance or new branch blocks the next push;
            # the exact-head lease independently stops replacement of this
            # branch, even if it races the inventory check.
            validate_inventory(expected, current_branches(), local_main)
            # This force-with-lease protects *deletion only*: no branch is
            # force-updated and main is never a destination.
            run_git(
                "push", "--porcelain",
                f"--force-with-lease=refs/heads/{branch}:{expected[branch]}",
                "origin", f":refs/heads/{branch}", timeout=90,
            )
            print(f"[{index}/{len(remaining)}] deleted {branch}", flush=True)
        final = current_branches()
        if final != {"main": local_main}:
            raise CleanupBlocked("Post-deletion remote inventory not main-only")
        print("PASS: remote repository contains only main")
        return 0
    except (CleanupBlocked, EOFError, KeyboardInterrupt) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
