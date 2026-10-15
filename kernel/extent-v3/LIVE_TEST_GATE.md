# Historical alpha.6 loaded-kernel gate — NOT current authorization

**Historical source protocol only; never treat its alpha.6 tests or old
host descriptions as approval to run current V3.** The active version is
defined by [VERSION](VERSION); supported operator testing is covered by
[testing standards](../../docs/testing_standards.md) and the
[roadmap](../../docs/ROADMAP.md).

**A future `/dev/sdb1` test is anticipated but NOT currently authorized.**
The present V3 constructor continues to refuse non-`null_blk` backing.
Explicit fresh authorization must identify the exact physical device,
prove it is unused by mounts/system swap and approve the exact operations
after independent RAM-only qualification and a safe rollback plan.
Never bypass the backing guard, activate system swap, force teardown
or reboot. Everything below describes the retired alpha.6 source only,
not an approved runbook for the current module.

## Alpha.6 NEW first gate — actual lower request aggregation

The alpha.5 default was measured WORSE than V2.2: **419 target
extent write submissions / 420 backing requests** versus 26 V2.2,
with 2.2% more write bytes in a matched 1024-page sample. The
alpha.6 engineering priority is physical lower-write aggregation,
not another isolated compression simulation. Read the exact
[LOWER_WRITE_AGGREGATION.md](LOWER_WRITE_AGGREGATION.md) contract
before loading the newly rebuilt `dm-swapz.ko`.

Compare table `lower_bulk=0` (historical) with `1` (DEFAULT:
adjacent-only, ZERO added padding bytes) and `2` (explicit
zero-padding to merge alignment gaps, added bytes accounted).
Ensure exact readback, short/failed entire lower write, no early
upper ack, prefix publication across runs, GC reserve role
handoffs, FUA/PREFLUSH, suspend/drain and independent backing
`/sys/block/.../stat` read/write bytes/requests before claiming
ANY benefit. One `dm_io` call is not necessarily one hardware
request; independent kernel block stats remain decisive.

Never load alpha.6 against physical disk/SD or active system swap,
never remove the physical-device constructor safeguard and NEVER
REBOOT.

## Distinguish the two independently built modules

- `make -C kernel/extent-v3 W=1 all`: output `dm-swapz.ko`, an
  EXPERIMENTAL actual DM target with `swapz` name and source
  `dm-target.c + codec.c + authority.c + engine.c`.
- `make -C kernel/extent-v3 SV3_BUILD_SMOKE=1 W=1 all`:
  `swapz_extent_v3.ko`, in-memory self-test module, **not** a DM target.
- Never link or use them in the same modpost build; run `make clean` between.
- **Module identity:** the V3 installed artifact is **`dm-swapz.ko`**
  (loaded Linux module `dm_swapz`), and its Device Mapper target
  keyword is **`swapz`**. V2.2 also builds `dm-swapz.ko` in
  `kernel/`; only ONE of these incompatible implementations can be
  installed or loaded at a time. Keep V2.2 and V3 checkouts/builds separate,
  and never use the previous alpha.1 `dm_swapz` test module hash to
  qualify the current alpha.5 driver.
- **Correct BIO flush encoding:** Linux rejects a direct
  `REQ_OP_FLUSH` BIO before the target receives it. Test a valid
  zero-length `REQ_OP_WRITE | REQ_PREFLUSH` BIO (or
  `blkdev_issue_flush(<owned DM bdev>)`) for standalone cache flush.
  Separately test actual upper FUA write and lower write/flush errors.
  A direct `REQ_OP_FLUSH` probe returning -EOPNOTSUPP is an
  **expected test-helper error**, not a V3 target bug.
- **Real and synthetic flush failures:** alpha.5 positional
  `test_fail_flush_nth=1..64` injects a diagnostic pre-submission EIO
  ONLY on memory-backed null_blk. Confirm upper once-only EIO, fail-closed
  state and `flush_calls=flush_ok+flush_err` counters. This does NOT
  establish genuine device-originated flush failure handling; independently
  qualify that separately.
- **Raw 4KiB integrity:** deliberately mutate a raw fallback block on
  the owned backing and prove swapz rejects its CRC32C both on logical
  read and GC relocation before copying it into a new extent.

- The old `kernel/dm-swapz.ko` is the frozen V2.2 target named `swapz`
  and its results cannot be counted as loaded V3 validation.
- Track: checkout Git SHA, four source Git blob SHAs, exact
  `sha256sum dm-swapz.ko`, `modinfo` vermagic, `uname -r`, GCC and
  loaded-module identity before *any* destructive test operation.

## Admission and safety

1. Begin with source/CI inspection and run rootless test suites. Confirm
   W=1/W=2 compilation against **matching running kernel** headers.
2. Confirm `/proc/swaps`, `lsblk -o NAME,TYPE,PKNAME,SIZE,FSTYPE,MOUNTPOINTS`,
   `dmsetup ls --tree`, `lsmod`, and the host's existing mounts. Never
   displace active system swap or the authorized but still-active SD swap.
3. Provision **new, dedicated, memory-backed** null_blk configfs device
   with a unique reserved test name and externally verified backing
   sysfs major/minor. Ensure its `memory_backed` setting is 1 before
   activating any target. Bounds must allow at least three 1MiB segments
   plus 25% (minimum two segments) of reserve.
4. Create `swapz` target only over that exact null_blk node, with a
   uniquely owned DM UUID. Never point the V2.2-only benchmark runner at
   a V3 module or at the SD partition.
5. If a DM create/remove or any data I/O times out or leaves callback
   ownership uncertain, **quarantine** its DM and backing rather than
   force-remove it or power down the null_blk device.
6. A loaded V3 test is allowed only after an independent static review
   checks this PR's per-upper BIO exactly-once completion, drain-admission
   locking, raw fallback, FUA/preflush and whole-range discard semantics.
   A compiler PASS is not enough.

## Functional tests to run before a timed benchmark

- Logical zero reads on unwritten slots, compressed readback from actual
  LZ4, raw incompressible 4KiB roundtrip, repeated same-slot overwrites,
  mixed compressed sizes, random 4KiB logical addresses.
- The target's size reorder should move only distinct, already accepted
  slots in a finite <=64 record window; a read/flush/discard prevents
  reordering across that barrier.
- Every 4KiB output payload must match its original with independent CRC
  and exact byte comparison. Test that persisted compressed sizes are
  the actual LZ4 output, not the configured fio compressibility.
- Compressed raw/discard transitions, failed reads and reads of deleted
  pages; multi-page shared-extent discard must not underflow liveness.
- FUA and preflush under a write batch: upper success only after
  completed lower I/O and the indicated lower-cache flush.
- Repeated GC victim churn: at least two 1MiB segment turnovers with
  50%-like 2072B and mixed 2200/1600B compressed data; independently
  compare `gc_read`, `gc_write`, total physical writes and lower
  sector deltas.
- Fault injection: lower timeout, short completion, corrupted payload,
  partial GC relocation and close/suspend while owned I/O drains.
- Bound GC retry count and reclaim reserve so exhaustion reports
  ENOSPC **without returning success on any uncommitted upper BIO**.
- Cold read p50/p95/p99 only if achieved read load matches baseline.
  Low-QD contention, GC, and test storage service-rate must be comparable.

The active release gate ledger is [active testing standards](../../docs/testing_standards.md). The renamed alpha.5 kernel module requires new independent loaded test evidence: Codex's alpha.1 dm-swapz module hash cannot be reused. GC must exclude both the paused foreground OPEN segment and the victim, and optional raw CRC/readback needs explicit corruption tests.

## Independent correctness blockers that prohibit SD / system swap

- No demonstrated loaded-kernel V3 target roundtrip on owned null_blk.
- No verified repeated live-only GC and mapping-authority preservation
  under fault injection on real lower BIOs.
- No owned-resource lifecycle/teardown test (suspend/resume/unload).
- No independent `null_blk` V3 harness with verified DM UUID and backing
  device ownership.
- No comparisons to the V2.2 baseline with matched reader achieved IOPS.

The project remains **draft V3.0.0-alpha.6**, not a production release.
No SD/HDD/SSD tests or unattended `swapon` should occur before a
separately reviewed release-gate commit removes the null_blk-only guard.

## Device geometry is not always 4KiB

The current V3 codec allocates aligned 4KiB units and accepts only
`PAGE_SIZE=4096`; this **does not** mean all actual backing drives
have 4KiB physical sectors or read/write in 4KiB operations. Before
any future SD/SSD/HDD admission, record both backing
`queue/logical_block_size` and `queue/physical_block_size`, along
with `minimum_io_size`, `optimal_io_size`, partition alignment,
FUA/cache/discard behavior and device limits. A 512n/512e drive can
address 512B units; 4Kn generally requires 4KiB alignment; a large
filesystem allocation cluster is NOT the physical sector size.

The `/sys/block/<device>/stat` sector fields are **always 512-byte
accounting sectors**: `read_bytes = Δread_sectors * 512`,
`write_bytes = Δwrite_sectors * 512`, and **4KiB equivalents**
`= Δsectors / 8`. A 16KiB single lower request equals four *byte
equivalents* but is NOT four physical I/O operations. Read and write
request counts must be recorded separately. Host counters do not prove
flash NAND program/erase counts or physical SD endurance.

See [device geometry and benchmark standards](../../docs/benchmark.md) and
[current benchmark criteria](../../docs/benchmark.md).
The current `null_blk`-only target admission remains mandatory.

## Mandatory physical-I/O success metrics

The benchmark's goal is specified by [the project vision](../../VISION.md):
**less actual lower-device read and write BYTES AND request
counts under the same verified achieved workload**, including GC.
4KiB equivalents are normalization, not physical-operation counts.

- For *each* V2.2/V3 matched run, record lower **512-byte Linux
  stat-sector deltas**, lower read/write **bytes** and independent request
  counts **separately**. Report equivalent 4KiB byte units as
  stat sectors/8, clearly labeled normalization (NOT four separate
  physical operations). A 16KiB request can be one request, 32
  stat sectors, four normalized 4KiB units.
- Include all GC relocation writes **and reads**, foreground I/O, and lower
  cache-flush/discard activity as distinct dimensions. Do not omit the
  IO needed to free a packed segment.
- Reconcile status counters against the uniquely owned backing device's
  pre/post sector and request counters after confirmed drain. If independent
  observation is not available, mark the result **unverified**, not PASS.
- Compare identical actual LZ4 input-size distributions, logical operations,
  seeds, flush/barrier behavior, hot/cold rewrites, device configuration and
  **achieved** reader/writer IOPS (not merely requested IOPS).
- Show cold-read amplification (4 KiB backing blocks per successful logical
  swap-in), p50/p95/p99 latency, CPU cost and reserve pressure. A write
  reduction that breaks read service is not an overall win.
- Keep source and target identity pinned: exact Git SHA, source blob SHA,
  compiled `dm-swapz.ko` SHA-256 and vermagic, actual mapped
  `swapz` target/UUID, physical backing major:minor and test isolation.
- Report one-window geometry, rootless benchmark, loaded `null_blk` and
  genuine SD/SSD/HDD results as **four distinct evidence classes**. Do not
  claim physical-media improvement from only the first three.

The current constructor's **null_blk-only** restriction remains in force.
Even a completely green loaded-null_blk report is *not* authorization to
test the SD card until a separate independently reviewed release gate.

## Report acceptance

Attach source/module identities, command exit codes, raw logs and hashes.
Separate (1) CI compiled kernel source, (2) real loaded kernel
functional tests, (3) timed RAM null_blk V3 physical sectors, and
(4) SD/SSD/HDD data (currently **NOT PERMITTED BY V3 ADMISSION**).
Do not claim success on (2)-(4) when only (1) has completed.
