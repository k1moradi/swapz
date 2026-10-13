# V3.0.0-alpha.6 — bounded contiguous lower-write aggregation retest

**Kernel architecture change: physical request submission, NOT just compression.**
Source: [PR #54](https://github.com/k1moradi/swapz/pull/54). Exact
module basename remains **dm-swapz.ko**, target keyword **swapz3**.
V2.2 comparator still builds the SAME module basename, so only load
one at a time. The constructor STILL REJECTS anything other than
memory-backed, test-owned null_blk. Never touch active /swapfile or
/dev/sdb1, other physical media or reboot.

## Why alpha.5 is not a performance win

Codex's [independent alpha.5 loaded report](https://github.com/k1moradi/swapz/pull/53)
established matched byte-exact 1024-write/4MiB bursts:

| Driver | Lower bytes written | Target lower writes |
|---|---:|---:|
| V2.2 | 1,679,360 | 26 |
| V3 alpha.5 DEFAULT | 1,716,224 | 419 (420 independent null_blk requests) |

V3 was **2.2% worse in write bytes and ~16x worse in requests**.
The source root cause is `engine.c` issuing a separate, synchronous
`dm_io` for every planned 4/8/16KiB extent. V2.2 streams larger
writes. Favorable 16-write alpha.5 microbursts did not qualify a
sustained win: they delayed write completion and increased lower reads
on difficult record sizes. Do NOT claim that format bytes/packing
scores imply hardware request or endurance savings.

## Actual alpha.6 production behavior

The same SWZ3 physical 4/8/16KiB extents and CRCs are retained.
The authority now supports **up to 64 reserved-but-UNPUBLISHED**
immutable transaction snapshots, restricted to one physical 1MiB
segment and a 64-block/256KiB contiguous lower run. The exact engine
builds independently valid extent images at their reserved physical
offsets. The **default adjacent-only mode NEVER writes extra padding
bytes**: any physical alignment gap ends the prior run. Optional
mode 2 combines across gaps and explicitly counts zero-filled padding.
Each lower run submits **one synchronous `dm_io` call** for 1..64
contiguous 4KiB blocks. A queue may split that into multiple **real
block requests** — independent `null_blk` sysfs stats determine the
true count. All padding is transferred, not credited as compression.

**No successful lower completion means NO published map and NO upper
BIO success.** Only after the ENTIRE lower run completes does the
engine restore each independently sealed transaction and invoke
the same CRC-validated, generation-safe `sv3_finish` publication.
On failed/short group completion, every associated physical
allocation is quarantined, its old mappings remain authoritative,
and the outer target fails closed. A previously successful run
can publish its independently completed logical prefix, but the
following failed run cannot claim even one successful logical page.
Unexpected metadata validation failure likewise fails closed.

The authority uses CRC32C to detect accidental mutation of staged
transaction snapshots, **not** as cryptographic authentication.
Unrelated stage or logical discard while the group is pending
returns `-EBUSY`. A GC victim exchange is forbidden while any
paused transaction exists. Duplicate logical slots and
`verify_after_write=1` deliberately take the ORIGINAL
per-extent path to preserve their ordering/readback semantics.

## Optional last positional constructor argument

```text
<owned_ram_nullb> [read_cap 0..3] [window 1..64]
    [verify 0|1] [gc 0..2] [coalesce_ms 0..4]
    [test_fail_flush_nth 0..64] [lower_bulk 0|1|2]
```

`lower_bulk=1` (DEFAULT): merge ONLY **physically contiguous**
extents, adding ZERO lower write bytes through padding.
`lower_bulk=0`: same-binary original per-extent synchronous writes
(control). `lower_bulk=2`: additionally combine across alignment
holes by writing and **accounting** zero-filled padding bytes;
it can save requests at the cost of MORE lower bytes. The
optional `verify_after_write=1` mode deliberately forces the
original serialized engine regardless of lower_bulk.

Status fields: `bulk_mode`, `bulk_io` successful combined submissions,
`bulk_extents` number of extents completed by them,
`bulk_padding` 4KiB alignment-hole units included in transfers.
Historical `physical_write_reqs` is a count of successful `dm_io`
submissions, **NOT** a guarantee about block-device physical
request count. Reconcile to independent `null_blk` stats.

## Source tests performed before loaded test

`tests/runtime/extent-v3-bulk-io-test.c` compiles ACTUAL production
`engine.c + authority.c + codec.c`, with a memory-backed faultable
lower callback and ASan/UBSan. It checks a 64-record batch: fewer
combined lower calls than distinct extents; byte-exact CRC/generation
readback; **none** of the new mappings observable inside the lower
completion callback; failure or short lower completion never
acknowledges a page; old per-extent path on duplicate slots and
verify-after-write; same-binary `lower_bulk=0` path; reject a
mutated snapshot; forbid unrelated stage/discard while pending;
and a segment-boundary failure that preserves exactly the committed
prefix of earlier successful combined runs. These are lower-IO
mocked tests, NOT loaded kernel proof.

## Independent loaded test order — do not skip gates

1. Pin exact new source sha + every production blob SHA and freshly
   rebuilt `kernel/extent-v3/dm-swapz.ko` hash/vermagic. Existing
   alpha.5 `97bba5cc...` module has DIFFERENT source and does
   NOT qualify alpha.6. Run W=1/W=2, ASan/UBSan, source checks.
2. New owned memory-backed null_blk, verify `memory_backed=1`,
   DM UUID, major/minor and no active holder. No system swap
   manipulation. Run byte-exact compressed/raw/discard/overwrites,
   FUA/PREFLUSH success and injected -EIO on both lower_bulk=0/1,
   `coalesce_ms=0/1/2/4`, `verify=0/1`.
3. **Critical combined-write fault test:** new uniquely owned null_blk
   device with target-local controlled lower write failure or lower
   slow-I/O injection. Validate no early mapping and no false
   upper completion, existing page readback after any successful
   prefix, failed target quarantine, and no hung callback at
   presuspend. Do NOT inject global faults or force-remove.
4. Force two physical-segment boundaries plus **at least eight rotating
   reserve GC cycles**, including raw/compressed mixed survivors,
   full destination and GC write/read faults. Every successfully
   acknowledged page must remain byte-exact. Run 1024-BIO suspend/
   resume, no lost requests or workqueue CPU-hog warnings.
5. **Same-binary comparison**: repeat EXACT prior alpha.5
   1024-write fixture, once `lower_bulk=0` (internal baseline),
   once `lower_bulk=1`, optionally `lower_bulk=2`, with matching
   GC/coalesce/read_cap and
   bit-identical input. Verify 1024 upper readbacks. Compare independent
   null_blk stat **read/write sector bytes AND request counts**,
   including verification I/O and all GC, physical statuses and
   achieved IOPS. One kernel `dm_io` call can split into more
   than one block-layer request.
6. After the same-binary check, load **frozen real V2.2** sequentially
   (same .ko basename, never coexist), repeat the exact fixture,
   and compare bytes, requests, p95/p99, CPU and achieved useful
   operations. Do at least 5 paired runs with counterbalanced order.
   Do not treat the prior 419 vs 26 numbers as a prediction of
   alpha.6 improvements. Also run QD1/4/8/32, steady GC churn,
   overwrite/discard, raw and uniform 2089B/1032B workloads.
7. If bulk=1 reduces lower request count but increases write bytes
   from zero-filled alignment holes, or increases cold read p99 /
   CPU, report the FULL trade-off. **Do not call it a production win
   without matched V2.2 under achieved load.** Maintain source-only
   null_blk admission. No SD/SSD/HDD until a separately reviewed
   device gate and explicit authorization, never active /dev/sdb1.

The release gate is an improved I/O frontier, not simply passing
unit tests. Negative and mixed results must be published verbatim.
