# Agent 7 — Round 006: bounded production-linked fake-DM observer atomicity stress

**Task ID:** `agent7-native-dm-observer-atomicity-stress`
**Round mailbox:** https://github.com/k1moradi/swapz/issues/123
**Frozen `swapz/main`:** `47a793c1480556c075f23ecbe13a5b465d616916`.
**Start:** immediately after the unique issue `ROUND_OPEN`, **simultaneously with Agent 8**. Do not consume or await its results.

## Exclusive actual-source ownership

Edit **`tests/runtime/native/userspace/swapzctl-status.c`**, the existing native fixture that includes production `src/userspace/swapzctl.c`, plus a distinct small append-only `Round 006 DM observer failure-atomicity stress` section in `docs/testing_standards.md`. Do not edit `.github/workflows/phase-a-linux-source-preflight.yml`, any Linux upstream source, Agent 8's standards section or production code without a separately established defect.

The frozen source already contains 372 parser-only adversarial cases from Round 004 and 18 deterministic two-INFO origin scenarios from Round 005. **Do not reimplement or duplicate either test set.** The task is the next layer: bounded *sequence/lifetime/error atomicity* of real production read-only `report_device_status_with_reader` through the fake multi-target DM inventory.

## Implement and test actual C

1. Add a small **deterministic seeded and capped sequence** of at least 64 and at most 256 **multi-target observation schedules** with fixed-size or appropriately owned scratch arrays, reusing the production reader and existing fake-DM plumbing. Capture the seed, case index and first failing condition only. No external entropy, privileged ioctl or device.
2. Vary independent first/second-target INFO counters, target identity/generation, later-target `FAILED`/`UNAVAILABLE` or malformed status and INFO pairs that become stable after a finite number of reads. Express **expected results from independently defined invariants**, not copied production output; verify retry bound and no success from a torn pair. Keep watch schema, JSON v1 and existing ownership paths unchanged.
3. For every case, explicitly assert: **no stdout metrics on failed/mismatched/unavailable later target**; bounded attempts and stable-pair convergence when one exists; returned `report.targets` is empty on error and freed exactly once on success; failure diagnostics are field-scoped and must not echo the full INFO payload. Where testing requires injected errors, keep the existing fake callback ownership/lifetime contract, no global unbounded buffers, no leaks/double frees.
4. Preserve **all existing tests**, comments and public ABI. Use stack/contiguous test vectors where feasible, avoid churn in the production parser. Keep test-source changes small and isolate seeded helpers. Run actual compiled fixture via `make -C tests/suites SANITIZE=1 test-userspace`, plus GCC/Clang warning-clean configurations available. Use `git diff --check` if checkout available. Record exact tested source SHA and actual executed case count, never report code-defined count as executed without running.
5. Append same-commit `docs/testing_standards.md` contract naming deterministic seed/bounds, error atomicity, exact-source compilation and **limits (rootless fake DM ≠ live kernel)**. If the frozen fixture exposes an inherited failing test, report its actual first cause rather than weakening it to get green.

## Source delivery and report

Commit **real C fixture and matching testing standard source bytes** in a retrievable Git blob/tree/commit parented to `47a793c1480556c075f23ecbe13a5b465d616916`, **without moving remote `main`**, branch, fork, PR or extra worktree. Agent 1 alone reviews, serially integrates, runs hosted tests and preserves Agent 8's independent standard addition. If the worker environment has no full checkout, still implement and commit source and classify full-suite results `NOT_RUN`/`SOURCE_READY_PENDING_COORDINATOR_CI`; do not fabricate executable PASS. Do not wait for Agent 8.

Post one `message: REPORT_READY` to https://github.com/k1moradi/swapz/issues/123 with `round: "006"`, `agent: 7`, task ID, source commit SHA and changed files, actual compiler/tests/exits, seed/case bounds, errors/limits. No kernel boot/load, mapper/swap or physical operations. Phase A BLOCKED; Phase B disabled.
