# Agent 3 — Stock-kernel default-unknown fallback

```yaml
round: "001"
agent: 3
task_id: agent3-stock-kernel-fallback
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
  filename: agent3-stock-kernel-fallback-report.md
  channel: "https://github.com/k1moradi/swapz/issues/118 issue comment"
```

## Objective

Independently verify the **current unpatched module** preserves normal 4KiB admission/compression without a custom producer ABI. If a matching kernel/header build exists, compile the source and explicitly record the artifact's provenance limits. A local opt-in source-extracted fixture may model a default-unknown consumer guard; do not integrate a positive producer.

## Pre-round inputs

- `src/kernel/dm-target.c` (`swapz_bio_ref`, `swapz_map()`, preparations, selected representations) and `src/kernel/Makefile` from the frozen baseline.
- The historical review-only consumer diff in [#116](https://github.com/k1moradi/swapz/issues/116#issuecomment-6890537540). It is not merged; use solely to identify what a fallback must prove.
- Current `docs/compile.md` external-module build and source-stamp restrictions.

## Independent execution plan

1. Prove from the actual baseline source that no authenticated `bio_is_zswap_stored_writeback` interface is read; document default unchanged compression/scheduling and provenance UNAVAILABLE.
2. In an available safe rootless checkout on `main`, record exact kernel header source/config/`vermagic`/compiler and attempt the ordinary non-loaded production build (W=1/W=2 where available). If unavailable report BLOCKED, not a synthetic compile PASS.
3. Build an independent *rootless* negative/default-unknown fixture anchored to the real `swapz_map` source; model unsupported macro, READ, non-swap WRITE, malformed tag, stale descriptor/reset, and no RAW-bypass selection. Label stand-ins as fixtures.
4. Report the smallest review-only consumer patch implications for later matched-kernel integration, without editing or publishing `dm-target.c`.

## Acceptance / explicit blockers

- Current-source/byte anchors are pinned; no positive origin is inferred from `REQ_SWAP`, reclaim or task identity.
- A real Kbuild is labeled PASS only with actual compiler/headers/artifact and exact commands; otherwise NOT_RUN/BLOCKED.
- Any source-extracted fixture shows both negative-path cases and clear limits: it cannot prove actual MM provenance/DM cloning.
- Compression, pending slot, CRC/generation and completion behavior remain unchanged.

## Not part of this task

Do not install the module, load `null_blk`, activate swap, run a new matched kernel/consumer, edit production `dm-target.c` on GitHub, or consume Agent 2's Round 001 recommendation.

## Report discipline

In issue [#118](https://github.com/k1moradi/swapz/issues/118), post one `message: REPORT_READY` header with `round: 001`, `agent: 3`, `task_id: agent3-stock-kernel-fallback`, `status: PASS | FAIL | BLOCKED`, source SHA, exact commands + exit codes or NOT_RUN, evidence class, modified scratch paths, blockers and next-round recommendations, then the full Markdown report. Link/identify all fixtures, source lines, hashes and negative results. PASS means only this Round 001 task's verified checks passed: **it never means zswap Phase A or physical acceptance**. Do not wait for any peer working in Round 001.
