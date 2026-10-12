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
   extents on segment-aligned offsets, maintain 25%+two-segment GC reserve,
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

**16 × 2072-byte compressed records**: `ordered4` geometry consumes
16 × 4 KiB = **65,536 physical bytes**. The rootless V3 engine's
finite-window dynamic program consumes **ten** 4 KiB blocks, **40,960 bytes**,
or **1.600× logical/physical reduction**, by choosing 8/16 KiB extents
according to the completion/read-cost objective. This is a deterministic
in-memory C model with a fault-injected lower callback, **not** loaded-kernel
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
