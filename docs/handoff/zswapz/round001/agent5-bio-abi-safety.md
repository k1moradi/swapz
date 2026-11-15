# Agent 5 — Independent BIO ABI and provenance safety review

```yaml
round: "001"
agent: 5
task_id: agent5-bio-abi-safety
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
  filename: agent5-bio-abi-safety-report.md
  channel: "https://github.com/k1moradi/swapz/issues/118 issue comment"
```

## Objective

Independently challenge the proposed BIO carrier for **runtime struct/layout compatibility**, mixed-origin false positives, clone/split/reset and requeue hazards. Remain the independent safety reviewer and do not implement Phase B.

## Pre-round inputs

- Linux source pinned in historical [#116 Agent 2 proposal](https://github.com/k1moradi/swapz/issues/116#issuecomment-6890555852) at `c339f4010dea8b0d754f84ace70cd1b089878ef8`; stock Ubuntu-header evidence in frozen swapz `docs/compile.md`.
- [Independent B0-3 issue #117](https://github.com/k1moradi/swapz/issues/117) and frozen `src/kernel/dm-target.c` boundaries. No new Agent 2/3 Round 001 artifacts needed.

## Independent execution plan

1. Compare `struct bio` and in-kernel module header/runtime layouts: added byte placement/offset/size, allocation/zeroing, exported API availability, module ABI risk and whether the capability macro alone can hide incompatible running kernel code.
2. Audit real source `bio_init`, `bio_reset`, `__bio_clone`, `bio_split`, block generic split, DM `alloc_io/alloc_tio` and swap context aggregation. Explicitly test/reason about homogeneity at a 4KiB child boundary; list all unproven paths.
3. Evaluate malformed or untrusted scalar, recycled BIO and requeue, source entry-slot races and CONFIG_ZSWAP=n. Identify tests distinguishing a correctly copied tag from a forged tag.
4. Produce a severity-ranked B0-3 gate and minimum required exact-kernel Kbuild/KUnit/loaded verification. Mark claims as static-review, simulated or real, independently of Agent 2's new round results.

## Acceptance / explicit blockers

- Exact source references and a clear go/no-go for **carrier approval**, not a claim Phase A is integrated.
- Distinguish custom 7.3-development headers vs current CI Ubuntu 7.0 and why `vermagic` alone is insufficient.
- Mixed-origin positive/negative and clone/split/reset/reuse cases have independent expected results; unsafe false-positive path fails closed.
- Reviewer remains independent of code authored by Agents 2 and 3.

## Not part of this task

Do not modify `dm-target.c`, implement bypass or act as the Phase B author; no host kernel/module/device operations and no same-round producer/consumer dependency.

## Report discipline

In issue [#118](https://github.com/k1moradi/swapz/issues/118), post one `message: REPORT_READY` header with `round: 001`, `agent: 5`, `task_id: agent5-bio-abi-safety`, `status: PASS | FAIL | BLOCKED`, source SHA, exact commands + exit codes or NOT_RUN, evidence class, modified scratch paths, blockers and next-round recommendations, then the full Markdown report. Link/identify all fixtures, source lines, hashes and negative results. PASS means only this Round 001 task's verified checks passed: **it never means zswap Phase A or physical acceptance**. Do not wait for any peer working in Round 001.
