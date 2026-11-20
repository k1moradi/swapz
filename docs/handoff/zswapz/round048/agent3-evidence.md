# Round048 Agent3 — original Linux DM core vs real target asynchronous lifetime

## Frozen exact original source

[Issue #165](https://github.com/k1moradi/swapz/issues/165),
baseline engineering `52bc177a9480ff501a35ca771ddf1223f8e18702`,
complete task `c63aa4b0476edfdbecde252e7a4eb654285c9267`.
The original C source is pristine immutable
`torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`.
The new source audit verifies original Git blobs for
`drivers/md/dm.c` `1881d86111fb2e655893ad898cf21b88f0e4e7f3`,
`drivers/md/dm-table.c` `a483f49dd4ce6383ef66464707865187aa4cf51c`
and `include/linux/device-mapper.h`
`cd4faaf5d4275c038d06ccef4da3d77430154388`,
not a synthetic stand-in or generic modern kernel.

## Actual original Linux Device Mapper lifetime result

Original `dm_get_live_table(md, &srcu_idx)` enters
`srcu_read_lock(&md->io_barrier)` and returns
`srcu_dereference(md->map, ...)`; `dm_put_live_table` releases the
specific SRCU reader. `dm_sync_table` waits for both SRCU and expedited
RCU. These functions have declarations in the original
`include/linux/device-mapper.h`, but in this exact pinned `dm.c`
**neither the acquire/release pair nor the barrier has EXPORT_SYMBOL**
for use as an external loadable `dm-swapz.ko` target. The original
`dm_table_get_md()` may be exported but that gives the mapped device
handle, **not** a transferable ref to the current `dm_table` allocation
or its target and maps. Do not mistake a visible C declaration or copied
`struct dm_target *` for a kernel lifetime guarantee.

Original `__map_bio` obtains `ti` from the clone target-IO
descriptor, calls `ti->type->map(ti, clone)` and explicitly records
`DM_MAPIO_SUBMITTED` as ownership of *that original core BIO* moving
to the target. Core `__bind`/ `__unbind` synchronize an old table
and `dm_table_destroy()` calls each target `->dtr` before freeing
the table. These do not grant a separate retained live-table owner to
copied original zswap STORED LZ4 source metadata.

The *existing product* `swapz_map` admits a genuine normal upper
RAW_4096 BIO into `ctx->incoming` under its `queue_lock` and returns
`DM_MAPIO_SUBMITTED`. Its async lower write completion dereferences
`inflight->ctx`, publishes status and completion under the same
`ctx->queue_lock`, and wakes the ordered worker. The product closes
`ctx->accepting` before drain, waits for outstanding lower completion,
drains the workqueue, then `swapz_dtr()` calls `swapz_drain()` and
`swapz_free(ctx)` before `ti->private=NULL`. This is a **current target
accepted-BIO quiescence protocol**. It is not a public, separately
transferable table/ctx/GC generation lease accessible to external
original zswap STORED source allocation or late callback on a reloaded
target with numerically identical geometry.

Current `swapz_gc_relocate_one` reads current
`ctx->maps[logical]` and stages current compressed page payload; its
snapshot cannot be used after independent ordered-owner/GC/unwind.
New and old targets can reuse numeric table epoch/map generation/extent
location. Real original source backing bdev and nonlinear physical sector
are distinct from the target-relative 8-sector `ti->begin` logical
range. The source-extracted Round046 real negative helper checks those
fields, but even **all equal fields always return -EOPNOTSUPP** and the
real guarded callsite passes NULL reports and ignores the result. No
real current table reference, durable compressed lower WRITE, map or
upper ACK is authorized.

## Source-derived negative qualification

New rootless
`tests/tools/round048-dm-live-table-source-audit.py` validates
the three pinned original Git blob SHA1s, extracts genuine source
functions from original kernel and real production target C, and verifies
acquire/release, SRCU barrier/reload, core map ownership, table destructor,
product real callback `inflight->ctx` and lock/complete ordering,
admission-closing/drain before free, GC current map snapshot, default
guarded refusal for table/map/GC ABA and original bdev/physical sector.
**18 truly source-changing targeted hostile mutations** plus one fabricated
public EXPORT_SYMBOL of the private SRCU helper must each be independently
rejected; no no-op controls or fabricated positive source authorization.
The separate Round046 actual source-C rootless suite compiles genuine
production helper plus inherited Round043/Round041 C with both GCC and
Clang `-std=gnu11 -Wall -Wextra -Wconversion -Wshadow -Werror`
ASan+UBSan and runs inherited 150, 90, new 90 negative cases and all
7+9+12 hostile source controls. New rootless workflow uses original
pinned raw Linux sources, exact Git blob verification, and only
the existing host C suites; no loaded module, fake KUnit or simulated
positive I/O. New exact-SHA full-original-kernel GPL matched DM,
native x86/ARM/policy, original UML 55/55 and patch-hygiene workflows
must independently finish before any all-green claim.

## First genuine missing owner and safety

To admit future STORED LZ4 bytes safely requires a **new genuine owner
contract**: original Linux valid counted slot allocation incarnation,
original STORED source checksum/ownership, live current DM table/target
and GC/extent/map generation lease acquired legitimately and held until
last asynchronous callback plus correctly ordered teardown/GC. Neither
this source audit nor the source-extracted synthetic C has this API.
No current positive AUTH: `SOURCE_MAPPED_AUTHENTICATED=0`,
`PHASE_A=BLOCKED`, `DIRECT_COMPRESSED_HANDOFF=DISABLED`,
`FORCED_RAW_BYPASS=DISABLED`.

Zswap alone owns bounded compressed RAM and native Linux MM pressure
eviction. Swapz alone owns existing valid SWAPSPACE2 disk tier with
4/8/16KiB compressed payload-only packing and GC, no competing reclaim.
Ordinary upper RAW_4096 is the entire original UNCOMPRESSED 4096.
Any future already-STORED dictionary-free LZ4 staging must be a
separately owned/tagged lower-I/O representation, only after real
source+table leases and durable lower WRITE -> exactly one current
map -> exactly one actual upper BIO ACK -> full original 4096
SHA-verified decoded READ. The first entire physical 4096-byte swap
header/signature/UUID and partition table remain immutable.
Prior owner's old physical `producer_refused` first cause remains
UNKNOWN despite owner-reported recovery. No `make test`,
`make fast_test`, privileged, loaded, physical/real-pressure,
swapoff/on, mkswap, null_blk, DM activation or reboot.
