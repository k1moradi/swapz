# Agent 6 — Production-source Phase A negative-path fixtures

```yaml
round: "001"
agent: 6
task_id: agent6-phase-a-negative-tests
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
  filename: agent6-phase-a-negative-tests-report.md
  channel: "https://github.com/k1moradi/swapz/issues/118 issue comment"
```

## Objective

Build a reproducible **rootless** negative-path matrix anchored to production source that tests stock/unknown/no-origin behavior without needing the unavailable patched MM producer. Do not treat the prior synthetic Phase B bypass oracle as Phase A evidence.

## Pre-round inputs

- Frozen `src/kernel/dm-target.c` and existing native test conventions `tests/runtime/native/` and `tests/suites/`.
- Existing [#116](https://github.com/k1moradi/swapz/issues/116) and [#117](https://github.com/k1moradi/swapz/issues/117) initial correctness contracts.
- Project `AGENTS.md` testing requirements; baseline real producer positive-origin is unavailable.

## Independent execution plan

1. Specify rootless negative tests for absent ABI, ordinary REQ_SWAP, initial zswap rejection as unknown, malformed tag, READ/DISCARD/non-swap WRITE, stale descriptor on re-entry, unsupported/non-4096-byte requests and mixed-origin fail-closed results.
2. Source-bind a minimal test (rather than merely copy a model) to the actual frozen production admission/reset site where possible; prove source anchors are unique and output provenance points to the inspected SHA.
3. Add explicit checks that the baseline never switches `preparation_force_raw` or `RAW_SELECTED` because of origin; separate existing scheduling RAW from any future bypass.
4. Produce a machine-readable A00/A01/A03/A06/A07 negative matrix showing executed vs proposed checks and why real zswap/BIO clone tests remain BLOCKED.
5. Run safe standalone native compiler/sanitizer checks when supported; report exact commands, first failure and proof limits.

## Acceptance / explicit blockers

- Negative cases and expected results are independently reproducible from pinned existing source, without a Round 001 producer or counter field.
- PASS labels only actually executed rootless source-linked fixture checks; no synthetic tag establishes MM authenticity.
- Positive A02/A04/A05, loaded and physical scenarios explicitly remain BLOCKED; unchanged Phase A codec decision is the requirement, *not* Phase B zero-codec-attempt bypass.

## Not part of this task

No mm kernel patch, no active mapper, null_blk insertion, swap use or production source publication; do not depend on Agent 3's Round 001 fallback result.

## Report discipline

In issue [#118](https://github.com/k1moradi/swapz/issues/118), post one `message: REPORT_READY` header with `round: 001`, `agent: 6`, `task_id: agent6-phase-a-negative-tests`, `status: PASS | FAIL | BLOCKED`, source SHA, exact commands + exit codes or NOT_RUN, evidence class, modified scratch paths, blockers and next-round recommendations, then the full Markdown report. Link/identify all fixtures, source lines, hashes and negative results. PASS means only this Round 001 task's verified checks passed: **it never means zswap Phase A or physical acceptance**. Do not wait for any peer working in Round 001.
