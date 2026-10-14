# Current development: V3.0.0-alpha.14 experimental Device Mapper target

**Alpha.10 measures time from first accepted window record to
flush entry**, without changing worker scheduling, FUA handling,
completion authority or the media format. The alpha.9 closing-reason
telemetry remains in place.

**Alpha.9 adds observational window-closing reasons only**, without
changing flush ordering, the on-media format, or read-bypass policy.
The following alpha.6 lower-run aggregation design notes are historical
provenance from PR #54.

**V3.0.0-alpha.6 adds physical request aggregation, not another
compression-size heuristic.** The independent alpha.5 loaded test
confirmed a roughly **16x MORE lower write requests** vs real V2.2
on one matched 1024-write burst. Alpha.6 groups up to 64 aligned
4KiB lower physical units / 256KiB into a single synchronous dm_io,
while retaining individual SWZ3 extents and mapping publication only
after confirmed lower completion. Controls `lower_bulk=0/1/2`
respectively disable aggregation, combine adjacent-only without
additional write padding (DEFAULT), and optionally transfer
zero-padding across alignment holes. See
[LOWER_WRITE_AGGREGATION.md](LOWER_WRITE_AGGREGATION.md).
**No actual loaded alpha.6 performance benefit is yet proven.**

The active `dm-swapz.ko` (target name `swapz3`) is built from
`kernel/extent-v3/dm-target.c` plus the exact codec, mapping authority and
packing engine. It now includes **experimental low-live 1MiB segment
relocation**, using compressed-object size regrouping and raw 4KiB fallback.
A victim is never marked reusable until a final full mapping/refcount scan
proves it entirely dead. Foreground ENOSPC retries only the uncommitted
logical write prefix, bounded to four GC attempts per write window. Shared
physical extents are protected by whole-range discard preflight and
one-lock BIO admission/drain.

**Safety gate:** This is NOT a qualified system swap target.
Independent [alpha.4 loaded tests](https://github.com/k1moradi/swapz/pull/51)
did verify eight rotating GC handoffs, page readback, controlled faults
and 1,024-BIO drains on an owned RAM-backed null_blk. However the
**new alpha.5** lower-flush meter and conservative GC selector have
only exact-source/test + compile CI, not independent loaded-kernel
qualification. The previously reported `REQ_OP_FLUSH` BIO error was
caused by an invalid test-helper opcode; Linux uses a **zero-length
WRITE|PREFLUSH** BIO for an actual standalone flush. The new
`flush_fail_nth` diagnostic injects EIO *before lower submission*
and MUST NOT be advertised as a genuine device-originated error.
The alpha.5 collector also rejects provably non-reclaimable full-live
victims before wasting 1MiB of lower GC traffic.

**Do not** use active swap, `/dev/sdb1`, unrelated physical backing,
or bypass null_blk-only admission. NEVER reboot. Read the authoritative
[alpha.5 retest protocol](ONLINE_IO_RETEST.md) and
[readiness ledger](../../docs/PRODUCTION_READINESS.md).

The older sections below document the initial memory-only codec research
milestone, which remains available as `SV3_BUILD_SMOKE=1`. They are
**historical** and do not override [V3_GOALS.md](../../docs/ROADMAP.md).

---

# Main-developer V3 aligned extent prototype — kernel C

**Draft research prototype. NOT a production swap device, NOT yet a DM target.**
All codec, mapping, read and write planning functions are actual portable kernel C
linked into `swapz_extent_v3.ko`; the existing `dm-swapz.ko`, V2.2 on-disk
format, PR #31 metrics, and PR #38 default code are untouched.

## What is implemented

1. **Versioned physical layout:** exact aligned extent sizes 4, 8 and 16 KiB;
   16-byte little-endian `SWZ3` header, 16-byte descriptors, logical page,
   generation, payload bounds and CRC32C. Reject duplicate logical pages,
   noncanonical/overlapping offsets, unsupported sizes and corrupted metadata.
   Payloads may cross physical 4 KiB blocks.
2. **Finite capacity and failure authority:** single ordered-worker authority
   using caller-preallocated mapping/refcount/class arrays. Physically append
   extents on segment-aligned offsets, maintain a GC reserve of at least 25% of logical blocks and at least two 1MiB segments,
   stage generations, and publish only once **every lower block completes**,
   metadata passes and **every sibling payload CRC** passes. Failures/quarantines
   never change previous authoritative mappings. A failed write burns its
   allocation; no physical recycling or GC exists yet.
3. **Adaptive finite-window engine:** exact C dynamic programming over up to
   64 *already available* compressed logical records, choosing 4/8/16 KiB
   extents that minimize physical block writes. When byte cost ties, minimize
   predicted uncached metadata+payload physical read blocks, then write
   batches. At most 64 logical operations are considered in one window; never
   pull future records into the plan.
4. **Lower I/O adapter boundary:** synchronous completion callbacks for whole
   extents and 4 KiB-aligned read runs. Writes return completed physical block
   counts; a torn/short/error write cannot publish. A multi-extent window
   returns exactly the committed prefix on failure, not fake atomic success.
   Reads fetch block-zero metadata followed by **only** the requested
   payload's physical blocks, check exact current generation/mapping sequence
   and CRC32C, then copy into caller output.
5. **In-kernel in-memory smoke:** independently buildable
   `swapz_extent_v3.ko` exercises mapping publication and corruption
   rejection in its initializer; it never registers a DM target or opens a
   block device.

## Exact rootless experiments

CI compiles the **same kernel C** with `-Wall -Wextra -Werror`,
AddressSanitizer and UBSan, then runs:

```sh
cc -std=c11 -O1 -g -Wall -Wextra -Werror \
  -fsanitize=address,undefined -fno-omit-frame-pointer \
  tests/runtime/extent-v3-codec-test.c kernel/extent-v3/codec.c \
  -o /tmp/sv3-codec && /tmp/sv3-codec

cc -std=c11 -O1 -g -Wall -Wextra -Werror \
  -fsanitize=address,undefined -fno-omit-frame-pointer \
  tests/runtime/extent-v3-authority-test.c \
  kernel/extent-v3/authority.c kernel/extent-v3/codec.c \
  -o /tmp/sv3-authority && /tmp/sv3-authority

cc -std=c11 -O1 -g -Wall -Wextra -Werror \
  -fsanitize=address,undefined -fno-omit-frame-pointer \
  tests/runtime/extent-v3-engine-test.c \
  kernel/extent-v3/engine.c kernel/extent-v3/authority.c \
  kernel/extent-v3/codec.c -o /tmp/sv3-engine && /tmp/sv3-engine
```

Tests include CRC32C's canonical `123456789` check value,
record classes and exact geometry, metadata corruption with valid
recomputed CRC, malformed duplicate descriptors, incorrect physical class,
byte-exact payload checks, generation wrap, stale reads, failed last sibling,
partial lower write, GC-reserve exhaustion, post-failure quarantine, failed
second extent, unacknowledged-prefix handling and targeted read-block counts.

**16 synthetic 2072-byte opaque record bodies (compressed-length geometry only)**: `ordered4` geometry consumes
16 × 4 KiB = **65,536 physical bytes**. The rootless V3 engine's
finite-window dynamic program consumes **ten** 4 KiB blocks, **40,960 bytes**,
or **1.600× logical/physical reduction**, by choosing 8/16 KiB extents
according to the completion/read-cost objective. This is a deterministic
in-memory C model with a fault-injected lower callback. The synthetic record
bodies are not necessarily valid LZ4 frames; actual LZ4 compression and
decompression still need integration. This is **not** loaded-kernel
latency, NAND program bytes, real LZ4 compression overhead or swap performance.

CI also W=1-compiles the independent codec/authority/engine kernel module
against Ubuntu kernel headers **without inserting it or altering the machine**.

## Gaps before introducing V3 into real dm-swapz

**Do not connect V3 to production swap yet.** Main developer still owns:

- real Device Mapper BIO intake/completion and ordered worker integration;
  handle read/flush/FUA/discard/unmap/teardown and completion *per upper BIO*;
- real LZ4 compression/decompression (the research engine receives
  already-compressed payloads); raw 4KiB fallback and zero pages;
- segment GC/relocation with verified liveness, durable reserve, no early
  reclamation and no replay of failed half-written extents;
- actual block-device-backed `dm_io` adapter, timeout/short error cases,
  power loss semantics and exact lower sector counters;
- a format/version isolation and migration policy (do not interpret V2.2
  physical blocks as V3) and safe mapping teardown;
- full host-owned `null_blk` and dedicated `/dev/sdb1` validation with
  matching achieved reader load, fio CRC32C, physical counters and cold p99.

The user authorized physical-host `sudo` and verified SD-card experiments,
but **explicitly prohibited ANY reboot**. None of the code here makes a
module/device load into swap safe, and no privileged test has been executed
from this branch.

## Why this branch exists

Codex independently qualified the opt-in **4KiB bestfit4** implementation in
PR #38, showing **12→8** on a single clustered 2200/1600-byte mixed window,
and showing no sustained bestfit4 win in uniform 50%/75% fio profiles.
Main-developer V3 changes target the *uniform ~2072-byte cliff*, which is
mathematically unfixable by 4KiB-only reordering.

Codex's PR #39 fixture is useful but the direct-I/O helper must be bound to a
verified test-owned DM UUID/device identity before reusable privileged use.
See the review comment on PR #39 and PR #38's full independent validation
report at issuecomment-6113710422.

## Alpha.11 opt-in window retention

The ninth optional numeric policy argument after the backing path
(`retain_ms=0..4`) defaults to zero. This preserves all earlier
worker-close behavior and the same volatile SWZ3 representation.
When explicitly nonzero, the serialized worker may hold accepted
immutable scratch and upper BIO references across work items,
never extending the original absolute timer upon later admissions.
Incoming nonwrites and flush barriers retain their conservative
drain-before-observe semantics. This is a bounded experimental
scheduling change with no loaded safety or performance claim yet.

## Alpha.13 production early-commit experiment

A retained compressed window containing exactly eight staged pages
may be committed immediately when the **seven largest actual LZ4
payloads** plus the exact 16B SWZ3 header and 7x16B record
descriptors fit a 16KiB extent; the remaining valid compressed
page fits 4KiB. Only `retain_ms>0` with unrestricted read budget
is eligible. The byte-minimal planner, CRC/generation authority,
FUA/drain protocol and hrtimer remain authoritative. Default
`retain_ms=0` unchanged. The geometric bound of at most 20KiB
is NOT proof of physical request counts or lower latency;
the loaded alpha.13 test is NOT RUN.

## Alpha.14 seven-record pack-ready experiment

Alpha.14 changes the existing serialized worker's
experimental `retain_ms>0` early-close predicate: a batch
of exactly **seven** accepted non-RAW LZ4 pages may commit
before the eighth arrival or the pinned 2ms deadline if
all seven actual lengths and the exact header/descriptors
fit one 16KiB SWZ3 extent. Seven 2073B pages + 128B
metadata = 14639B, leaving a valid single-extent plan
instead of 28KiB of separate 4KiB writes. This is only
a *geometry proof*, not a guarantee about lower device
requests or write-tail latency. The existing planner and
CRC/generation authority still decide the physical
submission, publication and completion; default-off
retention and null_blk-only admission are unchanged.
Loaded alpha.14 is NOT RUN.
