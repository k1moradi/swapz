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
