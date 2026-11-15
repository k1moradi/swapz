# Agent 5 — Round 005: real two-INFO provenance snapshot race and atomic output tests

**Task ID:** `agent5-double-info-origin-snapshot-races`
**Round mailbox:** https://github.com/k1moradi/swapz/issues/122
**Frozen source SHA:** `8bdc02de109aa3df65b6f0d0c22d13a04703e9e4`
**Start:** after `ROUND_OPEN` simultaneously with Agent 3; no peer inputs, tests or results are required.

## Exclusive implementation source

Own the existing **actual compiled C fixture** `tests/runtime/native/userspace/swapzctl-status.c`, which includes production `src/userspace/swapzctl.c`, plus one additive `Round 005 double-INFO provenance snapshot race tests` section in `docs/testing_standards.md`. Agent 3 owns the Linux Kbuild workflow and a separate standards section; do not touch either. Do not alter the production parser or CLI unless you can demonstrate a concrete source-bound defect and coordinate a carefully scoped fix (with applicable `docs/coding_standards.md` co-change).

## What is new, not a rerun of Round 004

Round 004 already added **372 bounded adversarial individual INFO parser cases**; source/native hosted CI succeeded. Existing fixture tests general snapshot mismatch/exhaustion via `status_reader_fixture` and `report_device_status_with_reader`, but not the **new three-key zswap provenance** through that live two-INFO selection path. Do not add another parser-only fuzz matrix.

1. Extend the existing fixture's `read_fixture_observation` and/or its bounded `status_reader_fixture` sequence only as needed, reusing real `report_device_status_with_reader`. Supply deterministic multi-observation provenance groups for both target records, not a fake parser, heap-allocated copy or global unbounded counter.
2. Prove stable legacy all-absent origin group yields **unavailable** (never measured zero); stable present all-zero group yields **measured zero** with the compile-time carrier displayed accurately. Under capability=0, reject positive counters. For stable enabled group, verify committed verified <= admitted and total represented pages.
3. Prove a **torn origin snapshot** where committed > admitted or > compressed+raw+zero causes bounded `STATUS_RETRY`, not partial printed metrics. Prove a changing but individually valid pair of origin counters fails stable two-INFO equality and exhausts the exact existing retry cap without leaking any previously selected target output. Prove a later fully stable pair eventually succeeds within the existing bounded retries without false double-counting.
4. Prove multi-target atomicity and fail precedence: later target malformed/FAILED/unavailable origin or identity mismatch does not print or retain partial earlier target values; preserve precise first-cause diagnostics without dumping sensitive INFO text. Ensure all fake DM observations are read-only and free all owned snapshot arrays.
5. Execute the **actual compiled fixture** with `make -C tests/suites SANITIZE=1 test-userspace`, plus available Clang/GCC/UBSan/ASan variants; record exact commands/exits and bounded number of simulated snapshots. Keep existing Round 003/004 tests, comments, output/JSON v1, options and reporting semantics intact. If real source reveals an implementation bug, provide focused tested source fix only if ownership can remain isolated from Agent 3, with same-commit applicable standard; no speculative refactor.

## Committed-source handoff

Create one retrievable Git tree/commit with parent frozen `8bdc02de109aa3df65b6f0d0c22d13a04703e9e4` containing the real C fixture and only your additive testing-standard section (plus strictly necessary co-changed production C). Do not update remote `main`, fork, branch, PR or secondary worktree. Source commit delivered, actual available checks and coordinator CI pending should be classified `SOURCE_READY_PENDING_COORDINATOR_CI`, NOT a false full-source PASS. A test plan or pasted patch is not delivery.

Post exactly one primary `message: REPORT_READY` in issue #122 with `round: "005"`, `agent: 5`, task ID, source-commit SHA, owned files, exact tests/exits, measured bounded retry/case counts, failing first cause, evidence class, NOT_RUN gates and limitations. Do not wait for Agent 3. Phase A BLOCKED; Phase B disabled.
