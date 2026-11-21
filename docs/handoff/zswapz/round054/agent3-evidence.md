# Round054 Agent3 — same-address reissue cancellation negative

Frozen engineering: `713541c26f35ed812ebe75bb8c481169bdf98d3b`.
Frozen task: `feb086b499e78a8650fa723a459863fdce6a1c99`.
Official issue #171.

First checked actual previous exact-source DM run
[#44851585766](https://github.com/k1moradi/swapz/actions/runs/44851585766):
terminal SUCCESS, job 136683939012. Actual log markers verify GCC and
Clang 162 cases and 17 changed source mutants each, with inherited
144/13 and 168/22 and older C suites also successful at that SHA.

New defect is in the default-undefined host receipt helper only:
an old cancellation can match a new receipt by reused pointers while
its recorded scalar incarnation disagrees. The guarded abort now checks
six independent fields without dereferencing the observed target or BIO.
The old helper, transcribed from the frozen source and checked against
its extracted declaration/helper lengths and FNV-1a-64 fingerprints,
was compiled and executed unprivileged using both GCC and Clang.
Both reproduced first semantic failure:
ROUND054_DM_FIRST_ERROR blocks=1 fault=0 stage=stale-abort (exit 1).
The corrected extracted fragment and exact fixture executed 24 cases
and six separately changed C mutant executables under each compiler
with gnu11 strict warnings, ASan/UBSan and leak detection, no recovery.
All mutant executions returned exactly 1 with their named stale-abort
oracle (faults 0 through 5). The new fixture Git blob is
`18add4cda1c1027acb260833c6b0cbb4a4ee004e`.
The local runner exercised the same fragments; complete repository
checkout was unavailable in the local network-restricted environment.
New committed-source workflow and full inherited suites must be checked
on exact published SHA; no new terminal CI claim in this file.

All transitions are scalar negative observations of NORMAL full original
uncompressed 4096-byte BIO ownership. No real lower write, clone_endio,
upper bio_endio, actual table lease, source-slot acquisition, GC execution
or physical/loaded/pressure proof. Original kernel 63 cases are retained,
not claimed run here. No production enabled path is changed.
SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED
DIRECT_COMPRESSED_HANDOFF=DISABLED FORCED_RAW_BYPASS=DISABLED.
No owner make test/fast_test or privileged/loaded/physical/pressure trial.
