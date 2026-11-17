# Round 026 Agent 3 — read-only worker-owned MAP/GC/ACK snapshot and NO_GO

Official opening: https://github.com/k1moradi/swapz/issues/143#issuecomment-6942777129
Frozen task: 3219d1b6d9eb43c27778e72836c6b7627d845650
Source baseline: 0dfcd58b2a993d04de50256ae9e49577718d3e99

## Actual source and ownership

The production `struct swapz_dm` owns `ordered_owner` (mutex; lock
order ordered_owner -> queue_lock), `ctx->authority.maps` / `ctx->maps`,
and `gc_recovery.active`. Only this serialized owner stages/finishes
lower WRITEs, publishes RAM mappings after completed lower bytes using
`swapz_engine_complete_batched_run`, and then schedules upper BIO
completions. A lower callback only marks completion and wakes that owner.
GC `swapz_gc_relocate_one` snapshots `ctx->maps[logical]` but may
relocate an extent without producing a Linux slot allocation epoch.
`swapz_complete` and deferred ACK lists retain terminal error,
while READs can be independently submitted and revalidated only under
the same authoritative ordered worker. `swapz_end_io` may force a
terminal WRITE error at the DM boundary.

## Exact compiler-only new C

A new `SWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE`-guarded,
zero-call-site `swapz_round026_dm_capture_read_snapshot` reads
the **real** current mapping via `ctx->authority.maps` with a
`lockdep_assert_held(&ctx->ordered_owner)` caller contract.
It checks live map, non-RAW representation, 4/8/16-KiB extent boundary
and segment, 1..3568 compressed length/offset, original physical
bounds, and genuine `swapz_extent_sequence_lookup`. It copies the
full actual map, extent sequence, real GC allocator/recovery state.
Failed capture zeroes its destination. Caller must own ordered mutex,
valid target lifetime and immutable transaction buffers; no pointer
may escape. There is no malloc, disk I/O, callback or production call.

`swapz_round026_dm_revalidate_and_refuse` captures a new current
snapshot, rejects changed physical start/extent sequence even if
logical generation is unchanged across GC relocation, as well as
changed map encoding, offset/length/CRC, generation, GC recovery,
teardown, short/failed lower read, invalid upper original READ 4096,
premature or duplicate ACK and bad CRC/length. Even a byte-identical
MAP/GC snapshot and all matched synthetic transaction scalars return
`-EOPNOTSUPP` because a source-owned Linux slot allocation epoch,
owned sideband, store-time original SHA and actual producer-to-DM
refcounted carrier are absent. DM source generation != Linux slot
allocation epoch != claimed GC epoch. No live importer, raw encoding,
upper BIO success or on-media metadata has changed. Output buffers
and BIOs are never written/acknowledged by either function.

## Compiler evidence and first failure

Source-extraction regression compiles these exact `dm-target.c` C
functions under GCC/Clang GNU11 strict `-Wall -Wextra -Wconversion
-Wshadow -Werror -fsanitize=address,undefined` and runs scenarios
on synthetic stand-in maps (not authenticated source epoch).
Actual x86_64/arm64 external `dm-swapz.ko` Kbuild W=1/W=2/
normal and separately CI-only KCFLAGS variant must emit BOTH Round026
read-only function symbols in real dm-target.o via `nm -a`.
GitHub run exact SHA/first failure is to be recorded after publication;
the source fixture cannot by itself establish a kernel API compile PASS.
The existing imported actual decoder negative fixture still covers
CRC32C, LZ4, SHA256 and exactly original 4096 acceptance constraints.
No false live-genuine-stored qualification.

Decision: **NO_GO** for direct zswap compressed handoff until genuine
allocator slot epoch and authenticated owned MM/BIO transport exist.
Source-only snapshot is NOT sufficient for phase A.

LOADED=NOT_RUN; LOADED_4096=NOT_RUN; PHYSICAL=NOT_RUN.
KUNIT_EXECUTED=NOT_APPLICABLE_TO_AGENT3. PHASE_A=BLOCKED,
PHASE_B_FORCED_RAW_BYPASS=DISABLED, DIRECT_COMPRESSED=DISABLED.
Current RAW is original **uncompressed** 4096 bytes. The existing
SWAPSPACE2 first 4096 header/UUID/signature and partition table are
unchanged; physical data area never touched. zswap alone owns memory
pressure and compressed-RAM eviction; swapz only disk tier.

## Post-publication preflight correction

Source audit of Round026's independent third default-off Kbuild gate
identified an outdated hard-coded original-test assertion expecting
only two `SWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE` occurrences. Follow-up
expects three blocks without touching any production or other worker
source. This was detected before claiming a completed CI pass; the
first actual compiler/source result is governed by the corrected SHA.

## Earliest genuine compiler failure and source correction

At exact Round026 SHA `7a6f42a87637d37cc0646b576963d48148cf847f`,
`Experimental swapz production C qualification` workflow
https://github.com/k1moradi/swapz/actions/runs/44047953033
failed BOTH x86-64 job `133918241398` and ARM64 job
`133918241679` during the isolated actual kernel module Kbuild
phase `round024_ingress`. First actual compiler failure at
`dm-target.c:1331`: `-Werror=strict-prototypes`, because Linux
`current` is a macro resolving to `get_current()`. The original
source-extracted host fixture lacks Linux's real `current` macro.
The narrowly scoped fix replaces only the new probe's local with
`current_snapshot`; adds source test rejecting the kernel macro
collision; does NOT weaken warnings, touch active DM, or change
representation/ACK/GC behavior. New exact-SHA Kbuild must be observed
before declaring PASS. This preserves the first true error and the
NO_GO live-transport conclusion.
