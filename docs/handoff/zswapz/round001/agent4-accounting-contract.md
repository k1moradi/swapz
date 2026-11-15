# Agent 4 — Commit-side provenance accounting contract

```yaml
round: "001"
agent: 4
task_id: agent4-accounting-contract
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
  filename: agent4-accounting-contract-report.md
  channel: "https://github.com/k1moradi/swapz/issues/118 issue comment"
```

## Objective

Finalize a **reviewable proposal**, with rootless reconciliation tests, for the minimal Phase A committed verified-zswap-writeback counter and its eventual status-reader contract. No production `dm-target.c` edits until Agent 1/3 approve an exclusive integration window.

## Pre-round inputs

- Frozen `src/kernel/dm-target.c` success paths, `src/userspace/swapzctl.c` status parser and current committed `logical_write_bytes`/`compressed_pages`/`raw_pages`/`zero_elided_pages` semantics.
- Existing Agent 4 draft publicly described in [#116](https://github.com/k1moradi/swapz/issues/116#issuecomment-6890525553), plus Phase A semantic contract. The newly planned Round 001 reports are not inputs.

## Independent execution plan

1. Define `foreground_committed_verified_zswap_writeback`: 64-bit per-mapper count, one per successfully committed logical 4096-byte foreground write of verified origin regardless of compressed/RAW/zero representation, incremented at authoritative commit-publication only.
2. Enumerate synchronous batched, detached/deferred ACK, zero-elision, standalone RAW and error/abort/GC paths; specify sole increment site/owner and exactly-once rules without moving existing counters.
3. Define versioned read-only status exposure and atomic/snapshot semantics, reset/lifetime rules, unsupported-carrier absence vs measured zero, valid monotonic intervals and overflow behavior.
4. Create independent rootless fixtures for success, overwrite, deferred ACK, duplicate/failed callbacks, GC, zero, RAW no-fit and reset/missing origin. Check the inequalities `0 <= verified <= compressed+raw+zero` and `logical_write_bytes == 4096*(compressed+raw+zero)` cumulatively and by valid delta.
5. Explicitly DEFER all four `raw_committed_*` reason fields, their causal accounting and any RAW bypass. Document a **future** orthogonal reason vector without claiming it exists.

## Acceptance / explicit blockers

- Contract ties field units, scope, commit boundary and reader validity to real source locations; separates admission from success and source origin from representation.
- Presence/absence/zero semantics are explicit, with negative/error and lifetime tests run or BLOCKED with exact commands.
- Never equate global `zswpwb` or debugfs events to per-mapper committed origin; ordinary and initial rejected writes remain UNKNOWN in the two-value model.
- Phase A must not change codec attempts, RAW choice or lower I/O.

## Not part of this task

No concurrent production telemetry edits, no change to `swapzctl` on main, no claim the proposed field exists in current status and no reliance on Agent 3's same-round fixture.

## Report discipline

In issue [#118](https://github.com/k1moradi/swapz/issues/118), post one `message: REPORT_READY` header with `round: 001`, `agent: 4`, `task_id: agent4-accounting-contract`, `status: PASS | FAIL | BLOCKED`, source SHA, exact commands + exit codes or NOT_RUN, evidence class, modified scratch paths, blockers and next-round recommendations, then the full Markdown report. Link/identify all fixtures, source lines, hashes and negative results. PASS means only this Round 001 task's verified checks passed: **it never means zswap Phase A or physical acceptance**. Do not wait for any peer working in Round 001.
