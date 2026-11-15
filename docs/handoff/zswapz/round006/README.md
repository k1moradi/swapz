# Round 006 — independent, unblocked native safety and LLVM source-build qualification

**Execution gate:** begin ONLY after the sole authoritative `message: ROUND_OPEN` on [issue #123](https://github.com/k1moradi/swapz/issues/123).
**Frozen `swapz/main` source:** `47a793c1480556c075f23ecbe13a5b465d616916`.
**Team:** Agent 1 (coordinator/only remote `main` writer) plus exactly **two independently working agents: 7 and 8**.
**Milestone:** strengthen rootless reader safety and independent stock-source compilation; **Phase A BLOCKED, Phase B DISABLED**.

## Pre-existing inputs (no worker dependency)

Round 005 [source closeout](../round005/round-report.md) integrated the real two-INFO source fixture and a pinned Linux stock-module CI workflow. Its long-running native fixture and GCC linked-module runs were explicitly **IN_PROGRESS at closeout**; Agent 1 owns their subsequent qualification and first-error remediation. **Neither worker's Round 006 task depends on those results, another worker, a new kernel repository, or privileged physical I/O.**

The repeatable earlier stock Linux `CONFIG_ZSWAP=y/n` GCC object build [passed](https://github.com/k1moradi/swapz/actions/runs/43726191654) at pinned `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`. Existing native test sources and production `swapzctl.c` are committed at the frozen baseline. Both tasks can edit those **actual tracked files immediately** and use hosted CI to qualify them after Agent 1 publication.

| Worker | Exclusive implementation file | Meaningful executable deliverable |
| --- | --- | --- |
| [Agent 7](agent7-native-dm-observer-atomicity-stress.md) | `tests/runtime/native/userspace/swapzctl-status.c` | Bounded, seeded production-linked *two-target* DM fake-reader lifecycle/error/atomicity stress tests, not another parser-only corpus |
| [Agent 8](agent8-pinned-linux-clang-config-build.md) | `.github/workflows/phase-a-linux-source-preflight.yml` | Separate independent full pinned-source LLVM/Clang `CONFIG_ZSWAP=y/n` object-build GitHub Actions job; continues even if the existing GCC linked-module job fails |

**Only shared file:** each worker appends its **distinct titled** governing `docs/testing_standards.md` section in the same actual source commit, based on the same frozen baseline; Agent 1 serially integrates both sections without overwriting intervening standards. No same-round code consumption or edits to another worker's path. Do not touch `src/kernel/dm-target.c` or real upstream Linux producer code as a shortcut.

## Required execution contract

Read `AGENTS.md`, `docs/AGENT_CONTEXT.md`, `docs/coding_standards.md` and `docs/testing_standards.md`. Edit actual source files with minimal changes and existing comments preserved. Use descriptive variables, source-bound compile/test evidence, bounded resources, fail-only diagnostics and no hidden API/schema changes. A posted diff, patch file, memo or synthetic-only PASS is not implementation.

Workers create a **retrievable Git source commit** with parent `47a793c1480556c075f23ecbe13a5b465d616916` using actual edited file bytes; no forks, feature branches, PRs, secondary worktrees, force-push or worker update of remote `main`. Agent 1 alone checks source ownership, integrates via non-force expected-head updates, merges additive standards, runs exact-source CI, archives original reports and closes honestly. If a worker lacks local full checkout/hosted execution, real source commit with `SOURCE_READY_PENDING_COORDINATOR_CI` is a valid *handoff*, but NOT an engineering test PASS.

Each worker posts exactly one primary `message: REPORT_READY` to issue #123, with task ID, source object SHA, changed paths, exact commands/exits, source/compiler identity, first failure and explicit NOT_RUN/blocked limits. Both start simultaneously after `ROUND_OPEN`; neither waits for other worker's commit or test.

**Safety:** CI may fetch, configure and compile pinned public Linux source only in disposable runners. No kernel/module installation or loading, no active mapper/swap/reclaim, no physical device operations. No stock-header compile or fake DM INFO test qualifies the absent authenticated MM→BIO producer or positive zswap stored-entry writeback. Phase A remains BLOCKED; Phase B RAW bypass disabled.
