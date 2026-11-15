# Agent 4 — Round 008: source-linked read-only Device Mapper observer atomicity stress

**Task ID:** `agent4-native-reader-atomicity-stress`
**Issue mailbox:** https://github.com/k1moradi/swapz/issues/125
**Frozen baseline (Git commit parent):** `af334b3408b9a660fc7f4b15d82d8e5a9e6374bb`
**Start:** only at the unique Round 008 `ROUND_OPEN`; start **simultaneously with Agent 8**, with no peer dependency.

## Exact source ownership

Exclusive implementation source: `tests/runtime/native/userspace/swapzctl-status.c`. It compiles **real production `src/userspace/swapzctl.c`** and uses existing fake DM reader interfaces, `status_reader_fixture`, `report_device_status_with_reader`, and output-capture helpers. Update only this C fixture and append your own distinct `Round 008 DM observer failure-atomicity stress` section to `docs/testing_standards.md` **in the same source commit**. Do not edit production parser, CI YAML, Agent 8 Python or pinned Linux workflow.

This implements the explicitly **NOT_DELIVERED** original [Round 006 Agent 7 native stress](../round006/agent7-native-dm-observer-atomicity-stress.md) with a different accountable owner. The source already has 372 isolated Round 004 parse adversaries and 18 Round 005 two-INFO origin scenarios. **Do not duplicate either older corpus.**

## New actual C engineering

1. Add **64–256 bounded deterministic multi-target observation schedules**, with fixed documented seed and descriptive names. Reuse the actual compiled production reader and existing fake DM read callbacks; do not create a parallel production parser, open physical devices or call privileged ioctls. Prefer fixed contiguous stack/array fixtures, bounded lengths and no allocations inside hot test loops.
2. Vary *whole multi-target inventory* and actual two-read sequences independently: stable first target then later malformed/FAILED second target; torn later-target accepted/committed counters; identity/name/generation mismatch; requeue/changed but individually valid status pairs; counter overflow; exhaustion of the existing retry maximum; eventual stable convergence inside the cap. A schedule may be expected to fail: negative cases are first-class acceptance.
3. Verify independent invariants, not copied expected output: any later target failure **must not print partial earlier-target success**, must not leave partially accepted `report.targets`, must return correct fail-closed state and bounded callback count; a stable success must include two fully owned coherent targets, never double-count proven provenance, and free all target allocations exactly once. Verify field-scoped diagnostic precedence without logging raw untrusted INFO strings.
4. Preserve existing comments, C API, JSON v1, compatibility/UNAVAILABLE semantics, zero-vs-missing distinction and all existing tests. Do not change code to force a green result; expose and report source-bound first failure if inherited behavior fails. Document thread safety (fake reader is single-threaded and does not operate on real DM); no GUI or device work.
5. Compile and execute actual full-source native fixture via `make -C tests/suites SANITIZE=1 test-userspace` and available GCC/Clang high-warning/ASan/UBSan; run `git diff --check` if complete checkout. Actual executed count, sanitizer and compiler identity must be reported. When worker lacks complete checkout, **still implement and commit the actual C file**; report `SOURCE_READY_PENDING_COORDINATOR_CI` for not-run full suite, not a synthetic-only PASS.
6. Update `docs/testing_standards.md` with one new narrow titled append-only section covering seed/bound, multi-target atomicity, lifetime and the exact rootless evidence ceiling. No unrelated refactors, renames, API changes or test weakening.

## Git object and report

Create **a retrievable Git source commit** parented at `af334b3408b9a660fc7f4b15d82d8e5a9e6374bb`, containing actual owned C changes and applicable standards. Do not move remote `main`, branch/fork/PR/second worktree. Agent 1 serially integrates. Do not wait for Agent 8.

Post one new `message: REPORT_READY` in https://github.com/k1moradi/swapz/issues/125 with `round: "008"`, `agent: 4`, `task_id: agent4-native-reader-atomicity-stress`, commit SHA, owned files, exact commands/exits, seed, measured executed schedules, first error and all NOT_RUN limits. Phase A BLOCKED, Phase B disabled.
