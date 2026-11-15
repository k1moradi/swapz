# Round 003 — DRAFT: producer integration and consumer CI qualification

**Status: PREPARING — NOT OPEN; do not execute or report until a verified `ROUND_OPEN` comment appears.**
**GitHub mailbox:** [Issue #120](https://github.com/k1moradi/swapz/issues/120)
**Planning swapz source baseline:** `408728d43c16e67556c41f2e55c11e56ed68c33b` (candidate, must be reverified at opening).
**Consumer source implementation:** `a60d407f1e58879cdd6c38f79f24c8b6181d3d3d`; source-test follow-up `721133790fa77b8ab47dc870abea833351799723`.
**Proposed upstream Linux prototype:** `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` — candidate source only, not a selected, verified or loaded target kernel.
**Round 002:** [Issue #119](https://github.com/k1moradi/swapz/issues/119), Agent 2 [BLOCKED_PUBLISH](https://github.com/k1moradi/swapz/issues/119#issuecomment-6893835007), Agent 3 [production source committed](https://github.com/k1moradi/swapz/issues/119#issuecomment-6893823232); reports not yet archived at the time this draft was written.

## Staffing — 3 agents, 2 concurrent engineering tasks

| Agent | Independently executable scope | Draft prompt |
| --- | --- | --- |
| 1 (coordinator) | Close Round 002; ensure full kernel source and authorized writable destination, freeze inputs, publish opening marker; archive Round 003 reports | This README and issue #120 |
| 2 (Linux producer) | [Edit real full Linux source and commit authenticated MM/BIO provenance](agent2-real-linux-producer-integration.md) | Source `mm/`, `block/`, `include/linux/`, KUnit |
| 3 (swapz consumer) | [Investigate CI failure and fix/test actual committed consumer](agent3-consumer-qualification-and-ci-repair.md) | `src/kernel/dm-target.c` only if defect proven; narrow relevant tests/standards |

**Same-round independence:** Agent 2's work and source commits occur in the authorized Linux source repository; Agent 3 starts from the already published swapz source, not from Agent 2's Round 003 changes. Neither waits for the other. Matched producer+consumer loaded qualification requires both results and therefore belongs to a later dependency layer.

## Agent 1 mandatory PRE-OPEN gates

1. Verify the two original Round 002 `REPORT_READY` comments, archive both with exact links/content integrity, publish `round002/round-report.md`, close #119 and update [rounds.md](../rounds.md) honestly. Distinguish Agent 2's synthetic/rootless fragment replay from a committed, compiled Linux tree. Round 002 source outcome is partial, not Phase A PASS.
2. **Do not reopen the same Agent 2 failure.** Prove that Agent 2 has a full exact-revision Linux checkout and a **previously owner-authorized durable source-commit destination**. A GitHub issue containing a diff is not a source repository. Do not push to `torvalds/linux` without rights; do not create a forbidden fork, branch, PR or worktree to work around the gate. If no permitted destination exists, **keep Round 003 PREPARING** until this prerequisite is explicitly resolved.
3. Confirm the exact GitHub source baseline, the known committed consumer source blob, Linux source revision/config/headers, and that the agents have all inputs before opening. Verify that any newer `main` commits have not invalidated baseline assumptions. Current issue #120 is a *draft*, not a work authorization.
4. Inspect CI for exact commit `721133790fa77b8ab47dc870abea833351799723`: [native rootless failed](https://github.com/k1moradi/swapz/actions/runs/43710387874), failing phase `quiet-lower-io-test.sh`, first cause unknown; do not assume regression or PASS. Distinguish this failure from other successful workflows.
5. Confirm one exclusive `swapz/main` code-publishing lease: Agent 3 after `ROUND_OPEN`; Agent 1 stops all `swapz/main` writes during that lease. Agent 2 does not publish to `swapz/main`. No concurrent commits or speculative source merge.
6. Publish final manifests and index as one tested documentation-only `main` commit, recheck `main`, then add the unique authoritative `message: ROUND_OPEN` comment to #120 with **task commit SHA**. Until then neither worker executes. GitHub comments alone do not activate separate agent sessions; actual task dispatch must cite final files to each session.

## Mandatory source-edit/reporting discipline

Read `AGENTS.md`, `docs/AGENT_CONTEXT.md`, relevant `docs/coding_standards.md` and `docs/testing_standards.md`. Engineers **edit actual code**, run correct tests, make focused source commits, and verify non-force publication where authorized. Diff text may aid review but never substitutes for edited source. Minimal churn, descriptive identifiers, preserve existing comments, fail-only diagnostics, no unnecessary hot-path allocations/locks, source-coupled tests and no silent behavioral changes.

Each worker submits one primary `message: REPORT_READY` to issue #120 **after `ROUND_OPEN`**, with exact committed source revision or explicit publication blocker; changed files, compiler/config/architecture, tests/exits and evidence class, first failures, and a GitHub commit link. Agent 3 explicitly releases the `swapz/main` write lease at completion. Agent 1 archives original issue evidence and prepares the next dependency layer only after both results.

Phase A remains passive, default-UNKNOWN observability; no codec/RAW/scheduling/commit-authority changes. Phase B remains OFF. No kernel install/load, mapper/swap operation, forced memory pressure, physical backing writes or unsafe host work is authorized by this draft.
