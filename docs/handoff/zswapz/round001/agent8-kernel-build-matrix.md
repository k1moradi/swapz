# Agent 8 — Exact kernel/module build and CI evidence matrix

```yaml
round: "001"
agent: 8
task_id: agent8-kernel-build-matrix
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
  filename: agent8-kernel-build-matrix-report.md
  channel: "https://github.com/k1moradi/swapz/issues/118 issue comment"
```

## Objective

Inventory exact source SHA, kernel headers, generated config, arch/toolchain, module provenance and baseline GitHub CI; separate existing-module compile PASS from an **unbuilt, unmatched zswap producer/consumer candidate**. Provide a reproducible next-round matched-kernel qualification checklist, not a green Phase A gate.

## Pre-round inputs

- Frozen swapz `docs/compile.md`, root and `src/kernel/Makefile`, workflows in `.github/workflows/`, `docs/testing_standards.md` and existing CI run metadata as historical evidence.
- Existing [#116 Agent 8 observation](https://github.com/k1moradi/swapz/issues/116#issuecomment-6890579701) and the older Agent 2 custom development kernel proposal. No Round 001 Agent 2 recommendation is needed.

## Independent execution plan

1. Build an exact matrix for x86_64 and ARM64 baseline CI: checked-out source SHA, selected `kernel.release`, compiler, arch, 4KiB PAGE_SIZE assumptions, `CONFIG_ZSWAP` availability, generated headers/`Module.symvers`, W=1/W=2, artifact SHA and `vermagic` where exposed.
2. Audit whether workflow's direct `make -C src/kernel` uses fallback `SWAPZ_BUILD_SOURCE_SHA=unknown`; distinguish checked-out CI source identity from eligible source-stamped loaded artifact.
3. Verify current/frozen source GitHub workflow conclusions and cite exact run URLs and timestamps. Do not assume five workflows remain green after later pushes.
4. Write explicit acceptance commands for a *future* matched patched Linux kernel, tested producer/consumer Kbuild CONFIG_ZSWAP=y/n, KUnit BIO paths, loaded owner-qualified `null_blk`, verified real zswap origin, native sanitizers and exact `make test` report.
5. Classify A00–A09 as NOT_RUN/BLOCKED absent the integrated patched source and authorized environment; document earliest meaningful next step.

## Acceptance / explicit blockers

- Each claimed PASS has matching run/source/artifact evidence, otherwise UNKNOWN/NOT_RUN, and any CI warning is correctly attributed.
- Different Linux 7.3-development patch vs Ubuntu 7.0 CI headers clearly marked unmatched.
- Root `make test` INCOMPLETE/physical gates and rootless CI boundaries preserved; no actual writeback acceptance claimed.
- No parallel dependency on Agent 2's Round 001 kernel recommendation or Agent 6's negative fixtures.

## Not part of this task

No PR-based CI, kernel installation, module load, null_blk, live swap, physical I/O, or direct changes to production/CI; owner-host qualification is a future authorized phase.

## Report discipline

In issue [#118](https://github.com/k1moradi/swapz/issues/118), post one `message: REPORT_READY` header with `round: 001`, `agent: 8`, `task_id: agent8-kernel-build-matrix`, `status: PASS | FAIL | BLOCKED`, source SHA, exact commands + exit codes or NOT_RUN, evidence class, modified scratch paths, blockers and next-round recommendations, then the full Markdown report. Link/identify all fixtures, source lines, hashes and negative results. PASS means only this Round 001 task's verified checks passed: **it never means zswap Phase A or physical acceptance**. Do not wait for any peer working in Round 001.
