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

## Release-significant unresolved limit: 205 raw-page submissions

The original **same-input** 1024-write benchmark included **819 compressed
pages and 205 raw/incompressible pages**. Alpha.6's `lower_bulk=1/2`
combines **compressed extents only**: each raw fallback still calls
`sv3_raw_write()` -> `sv3_lower_write()` -> one synchronous
`dm_io` per RAW 4KiB page. Thus the tested fixture imposes
**at least 205 RAW lower submit calls**, before any compressed-extent
writes, whereas actual loaded V2.2 completed its entire mixed fixture
in **26 backing write requests**.

This is a *provable source-level lower bound on V3 submissions*, NOT
a new loaded host request count or a guarantee about block-layer
merging/splitting. It is strong evidence that **compressed-only
aggregation in alpha.6 cannot by itself fix the reported request
regression**. Crucially, no source CI result should be presented as
proof alpha.6 now beats V2.2 under that mixed workload.

**Follow-on architecture priority:** stage *both* raw and compressed
output into a single bounded physical write stream, without changing
on-media raw/compressed authority, mapping generations, CRCs, or
upper completion and barrier sequencing. First compare the saved
`lower_bulk=0/1/2` controls to quantify the remaining raw
submission floor and size-class/write-byte tradeoffs. Then design
a separate, independently reviewed mixed raw+compressed grouping
change rather than silently adding unsafe cross-format batching
to the unqualified alpha.6 release candidate.

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

## Additional GC economics repair: avoid provably futile full evacuation

Codex's alpha.5 full-destination test also exposed a **2MiB
wasteful GC attempt**: 256 compressed survivors near 3535B each
caused **1MiB lower reads + 1MiB lower writes**, then failed
`-ENOSPC` without any role handoff. The previous live-byte preflight
only proved its estimated payload total was below 1MiB; that is
necessary but not sufficient to prove physically packable space.

New **exact on-media format lower bound:** at most four compressed
records of length **3258B or more** fit inside one 16KiB SWZ3
extent (five records plus header and descriptors exceed capacity).
At most two fit in 8KiB; one fits in 4KiB. Every such live record
therefore requires at least one 4KiB physical allocation block
*on average*, independent of alignment/reordering, and every raw
page requires its own block. If a selected segment holds **256
or more** of those qualifying live records, its survivors cannot
leave a free block in the sole 1MiB GC destination. Reject that
candidate **before any relocation I/O**. The old payload-byte
lower bound still applies to smaller records. No new padding,
raw-page mutation or reserve-role exchange is authorized.

The driver exposes `gc_no_headroom_skips` to quantify these
preflight rejections; the same segment can be considered more
than once, so this is a **candidate-check count**, NOT physical
I/O operations or exact bytes saved. It is a necessary bound,
not a complete destination-packing proof. Exact-production-C
tests use `sv3_begin/sv3_append/sv3_seal` to prove 3257B
five-per-16KiB fits but 3258B does not, and test mixed raw/large
lower bounds. The next Codex run should repeat the old 256
x3535B live GC fixture and confirm no pointless 1MiB read/write
cycle occurs, while dense-but-eligible workloads retain successful
GC progress and CRC readback.

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

## Second-pass main-developer review: overwrite and GC authority fences

A standalone code review of the exact alpha.6 batching implementation
identified an under-tested edge: `sv3_bulk_flush` can overwrite *existing*
authoritative logical mappings, not just populate empty slots. New
exact-C tests first publish 16 existing compressed pages, then stage
replacement generations using combined lower runs:

- Inject `-EIO` on the first overwrite lower run. Assert zero replacement
  completions, every original mapping generation/start/sequence unchanged,
  **and byte-exact OLD compressed payloads readable** from the original
  physical media after the failed write.
- Permit the entire replacement lower run. Assert old generations are
  invisible to new publication until actual synchronous lower completion,
  then exactly the NEW generation and bytes are readable. Neither run may
  leave `batch_pending` or in-flight authority.
- Independently, `sv3_gc_compact_one()` now refuses GC selection when
  `batch_pending` or `batch_replaying` is set, beyond its earlier
  `in_flight` gate. Scanning a segment whose new physical extents are
  reserved-but-unpublished could otherwise mistake it for an entirely
  dead segment and allow unsafe early reuse. The presuspend drain
  already rejects unfinished bulk ownership; source contracts now pin
  both rules.

These are **source/physical-memory mock tests**, not a license to
read from a *live failed Device Mapper target* after a kernel lower-I/O
failure. The production target intentionally fails closed on such an
error. To validate preservation of old logical mappings in the loaded
kernel, use a newly owned, isolated, faultable `null_blk` device or
an exact-C test seam and inspect authority without attempting an
unsafe continuing I/O sequence on a target already marked failed.

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
