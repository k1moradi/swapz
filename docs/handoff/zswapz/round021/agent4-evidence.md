# Round 021 Agent 4 — exact swap attribution first-failure reporting

Official opening: https://github.com/k1moradi/swapz/issues/138#issuecomment-6924146448

The owner previously reported real physical anonymous_workload failure
reason=swap_attribution on source de5bc09e80484c60d003e860732ecb736a6c2f0b
after all five RAM stages passed. The retained 0600 first-error attribution
numbers have not been shared. The reported recovery is complete, but that
does NOT imply physical PASS or identify the underlying cause.

Actual source defect: physical-swap-probe.py already safely extracts ten
source-owned bounded numeric attribution fields from the primary oracle's
first Blocked exception. run-tests.py failed to allow the attribution
dictionary in parse_algorithm_pageout_diagnostic and discarded the producer's
numerical report. This focused fix adds strict reason/field/type/range and
delta/gap arithmetic checks, preserves the separate slot-release reason and
original nonzero physical exit, and prints only bounded safe observations.
Rootless console/source parser mutations were added to test-report-test.py.

The existing physical gate, immutable pre-oracle baseline, 3s guarded retry,
two identical exact matches, cgroup OOM/PSI checks, physical device protection,
memory-pressure controls and recovery are all unchanged. No private counters
can be invented; no unauthorized physical or privileged test was run.

Historical modified Linux KUnit (both y/n 5/5) and matched module Kbuild:
source/build PASS only. Loaded genuine stored-entry/MM→DM and exact original
4096 swap-in: NOT_RUN. Owner physical retrial: NOT_RUN. Phase A BLOCKED;
Phase B RAW bypass DISABLED; direct compressed transport DISABLED; current RAW
retains the original uncompressed full 4096-byte page.


## Agent 4 complementary source-function hardening and bounded rootless evidence

The first published Round 021 source commit repaired the official parser
without changing the producer. This follow-up preserves that main commit and
its public diagnostic, and strengthens the original `_confirm_exact_swap_attribution`
counter/deadline path: it checks signed/boolean/overflow inputs and a
post-sleep/post-read deadline before ever admitting two identical exact
matching sequential snapshots. Original immutable mapper baseline, three
seconds, 50ms maximum sleeping between rechecks, upper oracle deadline,
worker ownership, OOM/PSI safety and all byte-oracle requirements remain
unchanged. On timeouts the original source-defined first `Blocked`
exception now includes finite observational classes
`mapper_excess`/`cgroup_excess`/`sign_changed`/
`unconfirmed_matching_pair`/`no_recheck_sample`. The probe independently
filters the numeric units and class. The existing official runner's
ten-field first-error diagnostic remains accepted, while the new optional
classified extension undergoes an independent strict check; both preserve
nonzero exit and private log boundaries.

Safe local tests, with **no imported full repository checkout available**:

- `python3 -m py_compile /mnt/data/round021_agent4_source_excerpt.py`: exit 0.
- `python3 -B /mnt/data/round021_agent4_source_excerpt.py`: exit 0, 4/4.
- `python3 -m py_compile /mnt/data/round021_agent4_report_excerpt.py`: exit 0.
- `python3 -B /mnt/data/round021_agent4_report_excerpt.py`: exit 0, 3/3.

These are **source-extracted in-memory fixtures**, NOT the six fully
imported committed tool/test files. The complete new targeted rootless
unittests and full `git diff --check` require a genuine checkout or
exact-SHA hosted CI; their unexecuted local status is NOT_RUN.
The earlier owner's private initial/final values remain UNKNOWN, and the
underlying physical mismatch is not proven repaired. No physical/cgroup
memory pressure/module/mapper/swap mutation was executed. The separately
reported owner recovery has not been revalidated here. Read-only owner
review must precede any new authorization. Phase A BLOCKED, Phase B RAW
bypass DISABLED, direct compressed handoff DISABLED; existing RAW is the
original uncompressed 4096-byte page.
