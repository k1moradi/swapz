# swapz V3.0.0-alpha.2 — loaded-kernel admission gate for Codex

**THIS IS NOT AN AUTHORIZATION TO RUN V3 ON A PHYSICAL DISK OR AS SYSTEM SWAP.**

The project's testing user has already authorized privileged operations on a
dedicated physical development host and the specific SD partition /dev/sdb1
after safety checks. **But the V3 target currently refuses non-null_blk
backing in its constructor**. This restriction is intentional and may not
be bypassed by the test harness. **ABSOLUTELY NO REBOOT.**

## Distinguish the two independently built modules

- `make -C kernel/extent-v3 W=1 all`: output `dm-swapz.ko`, an
  EXPERIMENTAL actual DM target with `swapz3` name and source
  `dm-target.c + codec.c + authority.c + engine.c`.
- `make -C kernel/extent-v3 SV3_BUILD_SMOKE=1 W=1 all`:
  `swapz_extent_v3.ko`, in-memory self-test module, **not** a DM target.
- Never link or use them in the same modpost build; run `make clean` between.
- **Module identity:** the V3 installed artifact is **`dm-swapz.ko`**
  (loaded Linux module `dm_swapz`), but its distinct alpha DM target
  keyword stays `swapz3`. V2.2 also builds `dm-swapz.ko` in
  `kernel/`; only ONE of these incompatible implementations can be
  installed or loaded at a time. Keep V2.2 and V3 checkouts/builds separate,
  and never use the previous alpha.1 `dm_swapz3` test module hash to
  qualify the current alpha.2 driver.
- **Explicit loaded FUA BIO**, not only fdatasync/PREFLUSH, is still a
  release gate; test exact upper completion timing and fault propagation.
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
4. Create `swapz3` target only over that exact null_blk node, with a
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

## Independent correctness blockers that prohibit SD / system swap

- No demonstrated loaded-kernel V3 target roundtrip on owned null_blk.
- No verified repeated live-only GC and mapping-authority preservation
  under fault injection on real lower BIOs.
- No owned-resource lifecycle/teardown test (suspend/resume/unload).
- No independent `null_blk` V3 harness with verified DM UUID and backing
  device ownership.
- No comparisons to the V2.2 baseline with matched reader achieved IOPS.

The project remains **draft V3.0.0-alpha.2**, not a production release.
No SD/HDD/SSD tests or unattended `swapon` should occur before a
separately reviewed release-gate commit removes the null_blk-only guard.

## Mandatory physical-I/O success metrics

The benchmark's goal is specified by [the project vision](../../VISION.md):
**fewer REAL lower-device 4 KiB-equivalent read/write transfers under a
verified workload**, not a better synthetic compression ratio.

- For *each* V2.2/V3 matched run, record lower sectors and completed lower
  read/write requests **separately**; report equivalent 4 KiB units as
  bytes/4096. A 16 KiB request is **four transfer units**, one request.
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
  `swapz3` target/UUID, physical backing major:minor and test isolation.
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
