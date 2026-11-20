# Round046 Agent3 evidence — actual current product DM lifetime NO_AUTH

Frozen engineering baseline: `00d5d7e1ad8c92a88c4f81f4680786533e3a40ce`.
Frozen task-doc baseline: `d6532a162a43a48f0a88f2b602410f0eb3ea2068`.
Agent2 peer direct-main source preserved on publication; original source test owned
exclusively by Agent2. The new Agent3 source is a **default-undefined** real
`src/kernel/dm-target.c` observational `swapz_map` helper and exact-C callsite.
The exact original pinned same-kernel GPL module is compiled with this opt-in
guard by `.github/workflows/phase-a-zswap-dm-real-ingress-observation.yml`;
default module without any CI source guard remains behavior-identical.

## Negative acceptance (never an authorization)

The independent Round046 Python tool extracts the **actual production C**,
inherits all Round030/040/041/043 true compiler+executable checks (old 150,
90, source-hostiles 7+9) and adds 90 synthetic host negatives across 1/2/4
block 4/8/16KiB extents plus 12 independent non-no-op hostile source changes.
GCC+Clang compile the source-extracted actual guard and real callsite with
`-std=gnu11 -Wall -Wextra -Wconversion -Wshadow -Werror`, ASan/UBSan.
The original production ingress workflow repeats the entire host chain and
rebuilds full genuine ORIGINAL Linux kernel and same-KDIR matched GPL module
both default and with Round046 guarded source; the fast standalone Round046
workflow independently executes host checks. The only accepted result is a
negative refusal, never copied scalar authority.

(1) A stale target/ctx reused after dtr and new ctr with identical target
begin/len must fail even with old matching numerical source/DM sector.
(2) A private byte snapshot during async callback versus GC relocation and
map generation/extent retirement is **not** a table/map/GC lease; even ABA
returning identical scalar epoch, map generation and extent must fail closed.
(3) Original source backing bdev/nonlinear physical LBA is NOT the DM target
relative eight-sector interval or the current dm_table/dtr/GC owner, even
when the synthetic numerical values are equal. No real source incarnation
ref or current table/dtr lifetime ref is available to this witness.

All in-memory test pages/headers/CRC/SHA and 4/8/16KiB extents are
**SYNTHETIC**; first 4096 bytes of any physical SWAPSPACE2 header are never
accessed. Genuine original source↔DM live ownership and physical tests are
NOT_RUN and NOT_AUTHORIZED; an artificial table pointer scalar equality
cannot turn this into positive `SOURCE_MAPPED_AUTHENTICATED`. Zswap remains
bounded compressed RAM on native MM pressure, swapz remains existing
SWAPSPACE2 disk compression/GC only. Ordinary upper RAW_4096 remains
the full original *uncompressed* page. Phase A BLOCKED, direct compressed
handoff and forced RAW disabled. Owner physical first failure remains unknown.

## CI attribution

The issue #163 `REPORT_READY` comment holds the final published source SHA,
one parent, individual final-SHA terminal job links, original matched module
and source-extraction first error if red. The historical prior-source
23-success/1-failed-original-UML count is not green qualification and is
not substituted for this final publication. No CI status is asserted here
before the new exact-source workflows actually finish.
