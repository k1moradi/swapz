# Agent 2 — R119 direct-main CI range repair

Status: **BLOCKED_LOCAL_FULL_REGRESSION**. Actual range repair and R093 regression PASS; full unchanged kernel-debug regression blocked before discovery. Immutable source candidate delivered for Agent 1 review, not a CI or native qualification pass.

## Identity and observed failure

Frozen source `c5237321d0eb01002cec990deebff60c6f39ac64`, tree `327f200f9e45e4f06a335945cc8fbd6f41aa4f65`; task `c80097ba6ed9f9a80a955726c802f138e27c53c8`; source candidate [9cfdd9060b98cacd02dfcb5cb74ca8cd89ffc79d](https://github.com/k1moradi/swapz/commit/9cfdd9060b98cacd02dfcb5cb74ca8cd89ffc79d), tree `0070006056fcda4302cd2e74bf25f7496c5b0c5a`, sole parent task. Historical [run 46152455374 / job 141001824017](https://github.com/k1moradi/swapz/actions/runs/46152455374/job/141001824017) remains FAIL. Observed BEFORE `2d71a66a19f48b1857f512e91136fc24daafe4b6`, SOURCE `c5237321d0eb01002cec990deebff60c6f39ac64`, HEAD parent `749c7469a18ef747e838a318580d6c1a24f7bd39`. Checkout depth 2 and immediate-parent equality assumed a one-commit push; exit 1 preceded standards and test execution. A disposable three-commit Git push reproduces frozen guard exit 1 and repaired guard exit 0 on the same range.

## Repair

Only existing kernel-debug workflow, new focused rootless regression and append-only testing standards change. Full history in rootless job; exact nonzero lowercase BEFORE/SOURCE, exact HEAD, main push ref and checkout, non-shallow history, ancestor and nonempty first-parent range. Validate direct single parent, diff --check, and complete byte prefix of regular nonempty standards blob for every transition, plus final checkout standards identity. Disable replacement objects. Fixed fail-only diagnostics and corrective action; no raw Git stderr. Existing push-only scope, sparse job, existing qualification/R093 tests and probe retained. New suite extracts and executes the actual YAML guard in disposable Git repositories, not a separate model. No changes to project refs or production kernel. No peer dependency.

Source blobs:
- Workflow `a12e14f775bb01e53f6120a0eecd90eae4328ffd` (frozen `71eb882e84d551c54d0c858ff0f180a27ac7ac07`).
- Regression `5108ded8d9def8a693703dfe734bae4f6ee23d97`.
- Standards `94a82c1f12b740dacff588d518fecb27e54c4be1`; complete parent prefix verified by exact remote content comparison.

## Executed rootless qualification

Python 3.13.5, Git 2.47.3, UID 65534.

| Command (runuser -u nobody -- python3 -B) | Exit | Result |
|---|---:|---|
| tests/runtime/native/kernel-debug-main-range-test.py -v | 0 | 11/11 PASS, zero skips, 26.595 s |
| tests/runtime/native/round093-native-evidence-collector-test.py -v | 0 | 3/3 PASS, zero skips, 1.508 s, 15 negative controls |
| tests/runtime/native/kernel-debug-qualification-test.py -v | 1 | BLOCKED before test discovery: missing implementation import |

New guard regression covers actual wiring, one and three linear commits, unchanged/appended standards, missing/malformed identities, shallow/missing history, nonancestor/merge/side-parent base, intermediate whitespace and standards removal/rewrite restored later, byte-exact transition and final checkout standards. YAML parse passed. Both passing test suites actually executed unprivileged. Frozen R093 test and collector Git blobs verified. The unchanged 115512-byte broad test was recovered and hash-verified as `2a4ae070ebf4010bea0f99d337482bd6e8057b85`; actual invocation stopped on line 28 at import, FileNotFoundError for `tests/tools/kernel-debug-qualify.py` (frozen `23963fb732b44993ea6e2bb503d1019fcdcf95bd`). Zero of its 48 expected methods ran; no semantic failure or PASS asserted. First local retrieval error: git ls-remote exit 128, Could not resolve host: github.com. Connector recovery restored exact workflow and selected test blobs, not complete dependency closure. No fabricated dependency or test results. Full unchanged regression remains required on a complete exact checkout.

## Limits and handoff

No candidate CI dispatch, rerun, or build; no main ref movement, branch, PR, fork, force, native/physical execution, or selector changes. AUTH=0, Phase A BLOCKED, observation UNKNOWN, actual ORDINARY, experimental routing OFF, physical NO_GO. Agent 10 retains writer lease; Agent 1 alone accepts and integrates. Historical CI remains failed. Candidate local range and R093 PASS do not establish full qualification.
