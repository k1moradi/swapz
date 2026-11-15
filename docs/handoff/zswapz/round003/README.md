# Round 003 — independent source-edit implementation and regression

**Status:** Authoritative `ROUND_OPEN` in [issue #120](https://github.com/k1moradi/swapz/issues/120) is the sole start signal.
**Frozen baseline:** `15b98edef5d8b4e401d8c5e2c9a4d7a012100ff7`.
**Staffing:** Agent 1 coordinator and **two parallel workers, Agents 4 and 6**.
**Scope:** source-bound Phase A passive provenance, with Phase A still BLOCKED and Phase B disabled.

## Why the pre-opening draft assignments were replaced

The historical [Agent 2 draft](agent2-real-linux-producer-integration.md) depends on an owner-authorized durable **writable Linux source repository** that does not exist. The separate GitHub-hosted [97,310-file Linux 7.3 checkout and `make prepare`](https://github.com/k1moradi/swapz/actions/runs/43718607383) passed, but an ephemeral CI workspace is not a committed Linux producer. Sending Agent 2 to execute the blocked assignment again would be knowingly unproductive.

The historical [Agent 3 draft](agent3-consumer-qualification-and-ci-repair.md) was substantially completed **before this round opened**. Its [pre-opening report](https://github.com/k1moradi/swapz/issues/120#issuecomment-6894963968) documents committed userspace/test CI repairs and a released publication lease. It remains as historical evidence, not a Round 003 completion. **Both old drafts are superseded before execution**; do not dispatch them.

## Final independent workers

| Worker | Owned actual source files | Required result |
| --- | --- | --- |
| [Agent 4](agent4-passive-origin-status-reader.md) | `src/userspace/swapzctl.c`; `tests/runtime/native/userspace/swapzctl-status.c`; `docs/coding_standards.md` | Implement and compile a strict, optional read-only origin INFO parser and human-readable status with regression tests; preserve JSON v1 |
| [Agent 6](agent6-phase-a-source-regression-tests.md) | `tests/runtime/native/zswap-origin-consumer-source-test.py`; optionally one adjacent narrow negative test; `docs/testing_standards.md` | Commit executable source-bound provenance negative/mutation tests with deterministic negative controls |

Both use the exact frozen baseline `15b98edef5d8b4e401d8c5e2c9a4d7a012100ff7` and the already committed kernel INFO fields: `verified_zswap_origin_admitted`, `foreground_committed_verified_zswap_writeback`, and `origin_carrier_compiled`. **Neither needs a Linux repository, another worker's output, privileged devices or CI from this round.** The files are disjoint. Both start **simultaneously** after `ROUND_OPEN`.

## Direct source edits, real commits, single integration writer

Each worker edits real C/test/standard files in a normal main-only checkout and runs the changed code, not a speculative test plan or diff-only patch. For independent concurrent development, each worker can produce a real Git tree/commit object with parent frozen baseline via the GitHub Git Data connector, **without updating any remote branch**. No branches, forks, PRs, alternate worktrees, force pushes or conflicting `main` writes. Git issue comments are only the mailbox for the source-commit SHA and complete test evidence, not the code deliverable.

Agent 1 is the **only remote `swapz/main` publisher** in Round 003. After reviewing retrievable committed source objects, Agent 1 serially integrates the owned C/test files with applicable same-commit standards, tests and non-force expected-head verification, then archives the agents' original GitHub reports. Do not claim an unreferenced commit object is already on `main`.

Both workers post exactly one primary `message: REPORT_READY` to issue #120 with task ID, source commit SHA, owned files, tests/exits, first failures and evidence class. They never wait for each other's report or integration.

## Evidence limits and CI state

Read `AGENTS.md`, `docs/AGENT_CONTEXT.md`, `docs/coding_standards.md` and `docs/testing_standards.md`. Minimal churn, preserve comments and existing APIs, bounded/fail-only diagnostics, no new hot-path locks or allocations, real executable tests and high warnings. Native rootless passed at frozen baseline, but that SHA's repository-policy check failed on historical workflow commit `a1e66250...` because its **same-commit `docs/testing_standards.md` co-change was missing**. This is a separately tracked coordinator historical-policy issue, not a new Agent 4/6 blocker; do not weaken policy or claim overall CI green.

No kernel load, live swap, mapper mutation, forced reclaim or physical testing. No actual authenticated producer→consumer positive writeback has been qualified. Phase B RAW bypass stays disabled.
