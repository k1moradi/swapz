# swapz size-class research — Git-native agent handoff

**Research only.** This branch is based on PR #31 head `3a89ebbeba21c814dcf724e227b31d38445a3f9a`. No kernel, benchmark runner, active swap, or privileged test is changed or authorized here.

## Repository contract

All communications, patches, review discussions, test logs, and proposed fixes should live in **GitHub issues, commits, and pull requests**. Do **not** exchange ZIP archives, packaged sources, or detached scripts.

- `geometry.py`: developer's rootless geometry-only reference model, **not** a durability or GC simulator.
- `test_geometry.py`: 11 green geometry invariants.
- `RESEARCH.md`: developer's source-informed notes; estimated numbers are explicitly not loaded-kernel evidence.
- `legacy/reviewer1_allocator.py`, `legacy/reviewer1_gc.py`, `legacy/reviewer2_allocator.py`, `legacy/reviewer2_gc.py`: verbatim Python blocks from the reviewers. **Not vetted / not suitable for benchmarks.**
- `legacy/test_known_defects.py`: five **intentionally failing** tests documenting discrepancies in those scripts. A failing run here is expected until the design is corrected, and must not be claimed as a CI regression.
- `AGENT_TASKS.md`: separate work contracts and shared acceptance criteria.

## Reproduce without privilege

From repository root:

```bash
python3 -B research/sizeclass/test_geometry.py -v
python3 -B research/sizeclass/geometry.py
python3 -B research/sizeclass/legacy/test_known_defects.py -v
```

Expected starting state: **11 green geometry tests, five red legacy defect tests**. The last command exits nonzero by design. Do not add the intentionally red legacy tests to required green CI. The original GC simulators may hang or recurse; run only with rootless timeouts when investigating.

## How agents must contribute

1. Check out this research branch and read the relevant GitHub issue.
2. Commit changes on a **new branch per reviewer assignment**. Preserve original `legacy/` scripts unmodified as evidence; put corrected modules and tests under `research/sizeclass/impl/`.
3. Run deterministic rootless tests, include exact commands/seed/commit and honest outputs.
4. Open a **draft PR targeting this research branch**, referencing the assignment issue. Put code review and test evidence in the PR. A passing prototype must not silently alter the actual kernel or claim flash endurance improvement.
5. No kernel changes, sudo, modules, DM target setup, swaps, reboots, or privileged benchmarks. Those require a separately authorized development/testing phase.

The final shared comparison must use **the same workload trace, flush-window limits, physical capacity, allocation reserve, GC policy, read distribution, and error model** across baseline and candidates. All byte totals must correspond to actual modeled completed writes, not allocations or fixed WAF multipliers.

Any purported real PR #31 fio traces must be supplied as tracked input data with hashes and provenance; otherwise label inputs synthetic. Do not commit personal/host-private data or active-swap page contents.
