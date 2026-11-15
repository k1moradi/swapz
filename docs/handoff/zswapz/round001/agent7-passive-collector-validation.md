# Agent 7 — Passive collector and interval analyzer validation

```yaml
round: "001"
agent: 7
task_id: agent7-passive-collector-validation
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
  filename: agent7-passive-collector-validation-report.md
  channel: "https://github.com/k1moradi/swapz/issues/118 issue comment"
```

## Objective

Produce a **standalone, read-only and rootless** validation of passive zswap/swapz measurement semantics and a safe evidence schema. Existing local Agent 7 tools are optional conveniences, **not required unpublished inputs**. Do not run active trials, manipulate mappers, or infer provenance from global counters.

## Pre-round inputs

- Frozen `docs/benchmark.md`, `src/userspace/swapzctl.c` and `docs/ROADMAP.md`; the draft Agent 4 accounting proposal in historical [#116](https://github.com/k1moradi/swapz/issues/116#issuecomment-6890525553) is advisory only.
- Public kernel `/proc/vmstat`, `/proc/pressure/*` and `/sys/dev/block/MAJOR:MINOR/stat` interfaces, if readable. No attached/unpublished toolkit is a mandatory dependency.

## Independent execution plan

1. Define and, if feasible, exercise a strictly read-only one-shot collector: existing `swapzctl status --json` read, kernel zswap global vmstat/debug counters, block stats, PSI totals, boot ID and monotonic sampling boundaries. Never elevate to read optional files; mark absent fields UNAVAILABLE.
2. Ensure evidence files are private create-only mode 0600; timestamps bracket all reads; no workload launch or block-device data reads. Demonstrate no kernel/sysfs/mapper state modifications by static API/command audit.
3. Test offline interval parser fixtures: same boot/mapper identity, identity drift, counter reset, missing/malformed/sparse values, zswap configuration change, zero-activity denominator, matching representation counts `Δlogical_write_bytes = 4096*(Δcompressed + Δraw + Δzero)`, block 512-byte sector conversion and PSI total deltas.
4. Keep `zswpwb` and `written_back_pages` host-global, never mapper-origin proof. Draft `foreground_committed_verified_zswap_writeback` remains UNAVAILABLE until approved and implemented. No ordinary/rejection split is provable with only two origins.
5. Package tiny read-only reproducible examples, exact commands/exits, schema version and privacy limitations; report script hashes if created.

## Acceptance / explicit blockers

- Collector does no `swapoff`, `swapon`, `dmsetup` modification, `modprobe`, `mkswap`, sysfs writes, direct `/dev` I/O, stress or workload changes.
- Rootless fixtures confirm fail-closed identity/reset/absence; intervals with zero logical commits do not invent a ratio or a verified origin.
- A synthetic fixture PASS is labeled **parser-only**; optional passive host observation is **not** a current swapz Phase A positive test.
- Work does not depend on Agent 4's Round 001 final schema.

## Not part of this task

No performance arms, 4-way A/B trials, force reclaim, active mapper changes, physical tests or Phase B bypass; positive zswap provenance awaits future rounds.

## Report discipline

In issue [#118](https://github.com/k1moradi/swapz/issues/118), post one `message: REPORT_READY` header with `round: 001`, `agent: 7`, `task_id: agent7-passive-collector-validation`, `status: PASS | FAIL | BLOCKED`, source SHA, exact commands + exit codes or NOT_RUN, evidence class, modified scratch paths, blockers and next-round recommendations, then the full Markdown report. Link/identify all fixtures, source lines, hashes and negative results. PASS means only this Round 001 task's verified checks passed: **it never means zswap Phase A or physical acceptance**. Do not wait for any peer working in Round 001.
