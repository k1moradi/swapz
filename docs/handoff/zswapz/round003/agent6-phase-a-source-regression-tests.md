# Agent 6 — Round 003: implement Phase A source-bound negative regressions

**Task ID:** `agent6-phase-a-source-regression-tests`
**GitHub mailbox:** https://github.com/k1moradi/swapz/issues/120
**Frozen source:** `15b98edef5d8b4e401d8c5e2c9a4d7a012100ff7`. Begin immediately after Round 003 `ROUND_OPEN`, **in parallel** with Agent 4.
**Deliverable:** actual executable committed test source; not a test-plan report or text diff.

## Non-overlapping ownership

Own `tests/runtime/native/zswap-origin-consumer-source-test.py`; optionally one small adjacent `tests/runtime/native/zswap-origin-negative-path-test.py`; and the relevant same-commit `docs/testing_standards.md` update. Do not edit `src/kernel/dm-target.c`, Linux source, Agent 4's `src/userspace/swapzctl.c` or its C fixture/`docs/coding_standards.md`.

Work from the already committed exact `dm-target.c` in frozen `15b98edef5d8b4e401d8c5e2c9a4d7a012100ff7`. All four committed-origin hooks, the default-UNKNOWN descriptor reset, guarded authenticated BIO helper, admission counter and read-only INFO fields already exist before this round. You may not depend on Agent 4's new work.

## Actual code and negative tests

1. Strengthen the existing source-coupled provenance test to fail when a production C regression changes classification from default UNKNOWN, removes/relocates descriptor reset, calls the origin helper without `BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN`, admits READ or non-4KiB origin, counts before admission, duplicates/skips one of four successful foreground commit hooks, or introduces origin-driven RAW/compression behavior.
2. Implement **automated mutation-negative controls**: independently mutate relevant real-source C spans in isolated in-memory/temp fixtures; verify every mutation fails the contract while the original frozen production source passes. Exercise both carrier-present and carrier-absent source paths where statically testable, and ensure failures are deterministic. Avoid writing a competing fake kernel or a separate product implementation.
3. Include invariants for known auth/acceptance ordering, descriptor reuse/requeue and counting on success rather than failed/GC/deferred paths to the extent justified by the **real source**. Do not claim to have executed actual zswap eviction, loaded module BIO clone/split, exact readback or KUnit: this evidence remains ROOTLESS/SOURCE-CONTRACT.
4. Execute the new source test and its mutation negatives through the existing rootless testing entry point if feasible without editing unrelated files. Record exact commands, exit codes and number of negative controls. Use small maintainable helpers, no heavyweight deps, fail-only diagnostics, `git diff --check`.
5. Update applicable `docs/testing_standards.md` in the **same source commit**; preserve existing comments and do not weaken existing assertions.

## Source publication and reporting

Edit and test actual owned files in a normal main-only checkout at `15b98edef5d8b4e401d8c5e2c9a4d7a012100ff7`. Create a real retrievable Git tree/commit object parented to `15b98edef5d8b4e401d8c5e2c9a4d7a012100ff7` (or local main commit and publish its objects through GitHub Git Data connector) **without updating any remote branch**. Agent 1 is sole `swapz/main` publisher and will integrate reviewed source serially. An issue-comment patch or model-only PASS is not a real source delivery. No branches, PRs, forks or second worktrees.

Post one `message: REPORT_READY` in issue #120 with `round: "003"`, `agent: 6`, task ID, source commit SHA, files changed, actual tests/exits, mutation-negative count, evidence class and any limitations. Do not wait for Agent 4, its commit or its tests. Phase A remains unqualified; Phase B disabled.
