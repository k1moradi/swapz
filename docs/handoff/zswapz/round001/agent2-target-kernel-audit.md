# Agent 2 — Target kernel/source/config audit

```yaml
round: "001"
agent: 2
task_id: agent2-target-kernel-audit
baseline_sha: c128ac32374a753a0b27ae0ebec67693355b1b55
round_issue: https://github.com/k1moradi/swapz/issues/118
task_commit_sha: "Use the immutable SHA from the issue's ROUND_OPEN comment"
inputs:
  - "swapz main at baseline_sha, with AGENTS.md and docs/AGENT_CONTEXT.md"
  - "Existing ROADMAP/context/compile/benchmark documents and source, as relevant"
  - "Historical issues #116 and #117, not new same-round replies"
same_round_dependencies: []
allowed_changes:
  - "Local unpublished scratch documents, diffs and rootless fixtures only"
deliverables:
  - "One complete source-pinned GitHub issue report with verifiable evidence"
  - "Optional smallest reproducible local patch/fixture (never a direct push)"
acceptance: "All task-specific checks below are evidenced or explicitly BLOCKED"
constraints:
  - "No branch, PR, secondary worktree or fork; no worker publication to main"
  - "No live mapper/swap, privileged device operation, host stress or physical I/O"
  - "No Phase B RAW bypass or speculative kernel/DM contract approval"
report:
  filename: agent2-target-kernel-audit-report.md
  channel: "https://github.com/k1moradi/swapz/issues/118 issue comment"
```

## Objective

Evaluate realistic **test-kernel choices** for the Phase A producer/BIO ABI. Produce a compatibility-ranked recommendation and explicit owner-host information still needed. **Do not select a kernel by guess, port a producer, or claim Kbuild success** unless real exact-source evidence exists.

## Pre-round inputs

- Frozen swapz repo's `docs/compile.md` and CI headers selection; `docs/ROADMAP.md`, `docs/context.md`.
- Existing Agent 2 proposal in historical [#116](https://github.com/k1moradi/swapz/issues/116#issuecomment-6890555852): upstream Linux `c339f401...` development source with proposed `BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN`.
- Compare the existing Ubuntu 7.0.0-43 header environment against a possible owner-supported exact kernel, without assuming the custom header exists.

## Independent execution plan

1. Enumerate each candidate kernel by full Git commit, `UTS_RELEASE`, architecture, CONFIG_SWAP/CONFIG_ZSWAP/CONFIG_BLK_DEV_DM, 4KiB PAGE_SIZE, headers, generated headers, Module.symvers and toolchain availability; mark missing values UNKNOWN.
2. Locate exact `zswap_writeback_entry`, `swap_io_ctx` or alternative, `swap_can_merge`, BIO alloc/reset/clone/split and DM clone sites for the actual candidate source; identify changes relative to proposed 7.3 source.
3. Decide which option minimizes producer port risk without claiming authority over owner's current host. Include separately the stock 7.0 fallback, patched exact-kernel prototype and unknown owner-host source.
4. Produce a compact compatibility matrix and a recommended **next-round kernel decision request** listing evidence to obtain before Agent 1 signs a carrier.

## Acceptance / explicit blockers

- Each candidate is tied to an exact source/header/config identity or explicitly UNAVAILABLE, with credible version-sensitive anchors.
- Distinguish source-only review, synthetically replayed patch and real full-Kbuild; record all missing prerequisites.
- State which exact tests will be required next (CONFIG_ZSWAP=y/n, W=1/W=2, BIO homogeneity/clone/split) and why.
- No unsupported claim that upstream 7.3 matches Ubuntu 7.0; no same-round Agent 8 result is required.

## Not part of this task

No new Linux patch in swapz, no kernel installation/boot, no module insertion, no active swap and no dependence on Agent 3/5/8's Round 001 reports.

## Report discipline

In issue [#118](https://github.com/k1moradi/swapz/issues/118), post one `message: REPORT_READY` header with `round: 001`, `agent: 2`, `task_id: agent2-target-kernel-audit`, `status: PASS | FAIL | BLOCKED`, source SHA, exact commands + exit codes or NOT_RUN, evidence class, modified scratch paths, blockers and next-round recommendations, then the full Markdown report. Link/identify all fixtures, source lines, hashes and negative results. PASS means only this Round 001 task's verified checks passed: **it never means zswap Phase A or physical acceptance**. Do not wait for any peer working in Round 001.
