# Round 003 — DRAFT: producer integration and consumer CI qualification

**Status: PREPARING — NOT OPEN; do not execute or report until a verified `ROUND_OPEN` comment appears.**
**GitHub mailbox:** [Issue #120](https://github.com/k1moradi/swapz/issues/120)
**Planning swapz source baseline:** `408728d43c16e67556c41f2e55c11e56ed68c33b` (candidate, must be reverified at opening).
**Consumer source implementation:** `a60d407f1e58879cdd6c38f79f24c8b6181d3d3d`; source-test follow-up `721133790fa77b8ab47dc870abea833351799723`.
**Proposed upstream Linux prototype:** `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` — candidate source only, not a selected, verified or loaded target kernel.
**Round 002:** [Issue #119](https://github.com/k1moradi/swapz/issues/119) was closed after 2/2 canonical reports were archived in [Round 002 closeout](../round002/round-report.md). Agent 2 remained BLOCKED_PUBLISH; Agent 3 committed the production consumer.

## Staffing — 3 agents, 2 concurrent engineering tasks

| Agent | Independently executable scope | Draft prompt |
| --- | --- | --- |
| 1 (coordinator) | Verify already completed Round 002 closeout; secure authorized Linux source publishing, freeze inputs, open only when ready, archive Round 003 reports | This README and issue #120 |
| 2 (Linux producer) | [Edit real full Linux source and commit authenticated MM/BIO provenance](agent2-real-linux-producer-integration.md) | Source `mm/`, `block/`, `include/linux/`, KUnit |
| 3 (swapz consumer) | [Investigate CI failure and fix/test actual committed consumer](agent3-consumer-qualification-and-ci-repair.md) | `src/kernel/dm-target.c` only if defect proven; narrow relevant tests/standards |

**Same-round independence:** Agent 2's work and source commits occur in the authorized Linux source repository; Agent 3 starts from the already published swapz source, not from Agent 2's Round 003 changes. Neither waits for the other. Matched producer+consumer loaded qualification requires both results and therefore belongs to a later dependency layer.

## Concrete Linux access/publisher unblock

The [source-access-unblock plan](source-access-unblock.md) distinguishes a hosted exact-source checkout from a real, approved Linux source-code publication destination. A read-only hosted workspace can unblock checkout/compile feasibility but **not** replace a committed Linux source revision. Agent 1 must independently verify both gates before the round opens. The Round 002 archival and closeout have since been completed; do not perform them a second time.

## Agent 1 mandatory PRE-OPEN gates

1. **COMPLETED, do not repeat:** 2/2 Round 002 reports archived with exact GitHub links and digests, [round report](../round002/round-report.md) committed and issue #119 closed. Phase A remains BLOCKED.
2. **Do not reopen the same Agent 2 failure.** [Hosted full source preflight #43718607383](https://github.com/k1moradi/swapz/actions/runs/43718607383) has already checked out 97,310 upstream files at the pinned SHA and passed real `defconfig` and `make prepare`; this resolves **hosted-source access**, but not the **owner-authorized durable source-commit destination**. A GitHub issue containing a diff is not a source repository. Do not push to `torvalds/linux` without rights; do not create a forbidden fork, branch, PR or worktree to work around the gate. If no permitted destination exists, **keep Round 003 PREPARING** until this prerequisite is explicitly resolved.
3. Confirm the exact GitHub source baseline, the known committed consumer source blob, Linux source revision/config/headers, and that the agents have all inputs before opening. Verify that any newer `main` commits have not invalidated baseline assumptions. Current issue #120 is a *draft*, not a work authorization.
4. Account for exact-source CI evolution: the original [native rootless failure](https://github.com/k1moradi/swapz/actions/runs/43710387874) at `721133790fa77b8ab47dc870abea833351799723` involved `quiet-lower-io-test.sh`; newer source commit `8e0b9d5674fd6a9c424774e8cfd0e6590d1d6dee` fixed passive INFO schema handling, but [its Native/Make job](https://github.com/k1moradi/swapz/actions/runs/43718116057) then failed in `test-report-test.py`. Later commits `fa44515208ac1a6b8067023bf056bf5190202c75` and `988c2889d2d70c5478cb5ccec6fb8d3ea13dd665` revised that unrelated test. Verify exact newer CI before assigning any duplicate fix; never infer PASS from commits alone.
5. Confirm one exclusive `swapz/main` code-publishing lease: Agent 3 after `ROUND_OPEN`; Agent 1 stops all `swapz/main` writes during that lease. Agent 2 does not publish to `swapz/main`. No concurrent commits or speculative source merge.
6. Publish final manifests and index as one tested documentation-only `main` commit, recheck `main`, then add the unique authoritative `message: ROUND_OPEN` comment to #120 with **task commit SHA**. Until then neither worker executes. GitHub comments alone do not activate separate agent sessions; actual task dispatch must cite final files to each session.

## Mandatory source-edit/reporting discipline

Read `AGENTS.md`, `docs/AGENT_CONTEXT.md`, relevant `docs/coding_standards.md` and `docs/testing_standards.md`. Engineers **edit actual code**, run correct tests, make focused source commits, and verify non-force publication where authorized. Diff text may aid review but never substitutes for edited source. Minimal churn, descriptive identifiers, preserve existing comments, fail-only diagnostics, no unnecessary hot-path allocations/locks, source-coupled tests and no silent behavioral changes.

Each worker submits one primary `message: REPORT_READY` to issue #120 **after `ROUND_OPEN`**, with exact committed source revision or explicit publication blocker; changed files, compiler/config/architecture, tests/exits and evidence class, first failures, and a GitHub commit link. Agent 3 explicitly releases the `swapz/main` write lease at completion. Agent 1 archives original issue evidence and prepares the next dependency layer only after both results.

Phase A remains passive, default-UNKNOWN observability; no codec/RAW/scheduling/commit-authority changes. Phase B remains OFF. No kernel install/load, mapper/swap operation, forced memory pressure, physical backing writes or unsafe host work is authorized by this draft.
