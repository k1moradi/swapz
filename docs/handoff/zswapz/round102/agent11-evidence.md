# R102 A11 — ordered composition repair / frozen unified stage

**SOURCE_PUBLISHED / QUALIFICATION_PENDING.** Agent1 owns integration and acceptance.

## Immutable source
Freeze d2baba1bda02b78eb7df265d22c5e9dbee09e2b1, tree aec0bc814dc0e0c17c71ccaff2cdd9bd3d9727cc; task 5635a75aa422eef52ed1bf50544bca50b4a9e75e; Linux c339f4010dea8b0d754f84ace70cd1b089878ef8; frozen target 46c2cb832ff0071a028a27b35f63daa84f29914f. [Source commit](https://github.com/k1moradi/swapz/commit/dd9aad11d9e5cbae90a9ab4ae91f6c5858137439) dd9aad11d9e5cbae90a9ab4ae91f6c5858137439, sole fresh parent 5635a75aa422eef52ed1bf50544bca50b4a9e75e, tree 2b2d4a6bf01976e9ec7084040294f1d7e11b6ad9. Nonforce expected-head publication and ref readback verified. No same-round peer source consumed; no product edits.

- `tests/tools/round091-selected-dm-ordered-verify.py`: `7b73911f892bdec5d89e31d0e1396403b9d87c13`
- `tests/tools/round102-unified-stage-verify.py`: `20e6681c00ada2e72fc53d5dd6bc8073b1c4bf58`
- `.github/workflows/phase-a-round088-selected-dm-admission-host.yml`: `db02bcf836490c62c6c07a99cdc304e036dbca24`
- `docs/testing_standards.md`: `0f270b3ae33c82859d3018e2f184a06212db3dfd`

Full preceding standards content reconstructed at exact blob e549c90bdfa19bc1042ae99d6f08855960df709f and preserved as byte prefix; appended content read back.

## Ordered composition
Original [R092 job](https://github.com/k1moradi/swapz/actions/runs/45921767780/job/140253903049) failed after 34 typed controls: `ROUND091_FIRST_ERROR ordered claim lock gate` (exit 1). The old extraction includes a separate scoped reserve/cancel/commit function. New audit uses lexical masking, unique complete balanced function, exact lock/core validation/claim/mark/unlock/return order and explicit call allowlist. Separately proves both actual transaction variants and their caller order; exact credit, refusal cancellation, success commit, no queue lock. Eleven static hostile mutants added: storage, wait, list, I/O under claim lock, wrong lock, early unlock, missing/duplicate boundary, reserve after claim, wrong cancel credit, transaction queue lock. Existing four behavioral mutants and original C fixture, typed/registry tests and sanitizer flags retained. Equivalent connector-side lexical inspection of frozen target found no malformed residual token, unique claim body (2802 masked chars), expected call names. Not execution of Python or mutants.

## Unified staging
Exact pinned R098 and R101 verifier inputs, full original Linux, frozen product census (R098 differs only in corrected target). Ordered R089/R090/R091/R088/R092/R094/R095/R096/R097/R098 MM and DM/R101 overlay apply, hash, reverse and reapply; strict diff and census. Built-in selected owner/adapter, matched staged broker C/H/inc, corrected target, alternate recorder excluded; freeze identity in glue. One final unified-manifest.json and staged source diff; no compilation or link. Historical intermediate manifests not final authority. Existing R092 workflow full composition with frozen target; no R100 skip. No manual replay.

## Qualification
Local git ls-remote exit128 DNS (Could not resolve host: github.com). Hosted [run 45924444583 / job 140262410396](https://github.com/k1moradi/swapz/actions/runs/45924444583/job/140262410396) **QUEUED**; artifacts 0. No actual Python/static mutant result, GCC/Clang counts, semantic mutant kills or unified stage verdict yet. No unchanged native object replay or disconnected full link.

R101 broader corrected run census (exact run IDs in JSON):
- 790fcb30bad5062956808f0cd0418d2123511245: {"success":19,"in_progress":9,"failure":1,"queued":1}.
- 1b2b3101c391398587e8725c1ca9afc48e89044a: {"queued":4,"success":4,"in_progress":2}.
Original idle-map failure job 140253037259: test_idle_lane_submitter_dispatch_never_waits_inside_map, 9678 not less than 4979. Corrected product-codec [45921767811](https://github.com/k1moradi/swapz/actions/runs/45921767811) all four jobs successful. Prior R092 remains red until new qualification. No whole-main PASS.

AUTH0 Phase A BLOCKED; compressed handoff/forced RAW/import OFF; physical NO_GO. No branch, PR, force, duplicate dispatch, activation, VM, load, physical I/O or full build.
