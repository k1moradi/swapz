# V3.0.0-alpha.7 — mixed raw/compressed lower-write candidate

**Stacked development PR:** [#55](https://github.com/k1moradi/swapz/pull/55), based on
the compressed-only alpha.6 [PR #54](https://github.com/k1moradi/swapz/pull/54).

**Safety:** No reboot, active swap operations, physical-device tests or
changes to `/dev/sdb1` or `/swapfile`. The constructor continues to accept
only separately owned, RAM-backed `null_blk` devices. Do not load V2.2 and
V3 together (both use `dm-swapz.ko`). Mapping authority is volatile.

## Motivation and evidence level

Codex's **loaded alpha.5** matched 1024-page fixture contained 819
compressed and 205 raw logical pages. Its V2.2 backing request count was
26, versus 420 for alpha.5. Alpha.6 combines compressed SWZ3 extents
only; each of the 205 raw pages still generated an independent
synchronous lower submit call. This is a source-level floor, **not** an
alpha.6 measured backing-request count. No loaded alpha.7 test has
yet qualified performance, fault behavior or actual backing requests.

## Architecture and ownership

The existing serialized worker retains at most 64 accepted 4KiB write BIOs
in preallocated per-slot memory. With `lower_bulk=1/2` and
`verify_after_write=0`, it copies incompressible original pages into
the same buffer as compressed records instead of immediately flushing
the window. Duplicate logical slots, reads, discards, PREFLUSH and FUA
still drain or delimit the window. A FUA write is completed only after
the combined lower write and successful required cache flush.

The preexisting size-complementary sort operates **only** on compressed
records; raw records are appended in accepted relative order. The engine
plans the compressed prefix as independent SWZ3 4/8/16KiB extents, then
appends distinct raw 4KiB allocations. An output run may contain both,
but never exceeds 64 blocks / 256KiB or crosses a 1MiB segment.
`lower_bulk=1` flushes at every physical alignment gap and does not
add padding writes. `lower_bulk=2` may write counted zero-filled
alignment gaps. A raw entry is never disguised as a SWZ3 extent.

Each physical component owns an immutable authority transaction snapshot.
No mapping is published before the entire synchronous lower write
reports full successful completion. Successful runs replay their
snapshots in order: compressed entries through `sv3_finish`, raw entries
through `sv3_finish_raw` (which publishes a volatile CRC32C sidecar).
On failed or short lower completion, every unpublished allocation in
that run is quarantined; old generations remain valid. Previously
committed runs retain an exact logical prefix. GC cannot run with
pending deferred transactions. No caller may reuse the shared scratch
or acknowledge an upper BIO while a run is pending.

Existing `lower_bulk=0` and `verify_after_write=1` retain the original
serialized raw path and are diagnostic controls. Compressed-only
singletons/duplicate-slot control behavior also remains unchanged.

## Run-composition telemetry

DM info status now exposes `bulk_mixed_io`, `bulk_raw_only_io`
and `bulk_raw_entries`. These count **successfully fully published**
runs/entries only. Existing `bulk_io`, `bulk_extents`, `raw`,
`compressed`, completed/attempted physical bytes and requests remain
available for reconciliation. A run containing both formats cannot
meaningfully assign its single submission to raw versus compressed:
use the composition counters to identify it, and separate backing
`/sys/block/nullb*/stat` deltas to determine actual requests.
Counters are not substitute evidence of lower-media improvements.

## Qualification gates

The production-source exact-C test extends
`tests/runtime/extent-v3-bulk-io-test.c` with mixed compressed/raw and
raw-only grouping, physical byte/request-call comparison to the
same-source serialized control, readback plus raw sidecar CRC,
pre-publication visibility, first-run error, short-write quarantine,
failed overwrite preservation, a later failed run across the 1MiB
boundary, and malformed-input rejection. The source contract also
checks the mixed admission, FUA, publication and safety fences.

**Green rootless CI is not loaded-kernel proof.** On a separately
owned null_blk module, first verify exact source commit, module SHA-256,
vermagic, repeated byte-exact readback, raw/compressed overwrite,
discard, REQ_FUA, valid zero-length WRITE|PREFLUSH, injected failures,
GC, presuspend and teardown. Stop on any correctness failure.

Only then replay the exact old 819 compressed / 205 raw fixture against
frozen V2.2 and alpha.6 modes 0/1/2, and compare true independent
backing write **bytes and requests**, lower read requests/bytes,
GC costs, achieved IOPS and p95/p99 latencies. A single synchronous
`dm_io` call can still become multiple backing requests: never claim
request savings from mock callback counts.

**Release state: experimental draft, not physical-media ready.**
