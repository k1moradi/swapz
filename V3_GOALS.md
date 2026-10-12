# swapz V3 — active project goals (supersedes the old V2.x sequencing)

## Product direction

**Minimize completed lower 4 KiB block writes and reads on slow SD/eMMC,
SATA SSD, HDD and USB storage while preserving byte-exact swap semantics.**
The physical unit for accounting is always 4 KiB; a single kernel BIO may
cover multiple adjacent physical 4 KiB blocks, and actual device transfer /
read-amplification is measured rather than assumed.

V3 is inspired by zsmalloc's **object-size classification and compaction**,
not by copying its in-memory page allocator. It is a volatile Device Mapper
swap target, with individual 4 KiB logical pages compressed using LZ4.

The necessary pipeline is:

1. Compress 4 KiB logical pages immediately.
2. Reorder **only already accepted, safe-to-reorder, different-slot** records
   inside a bounded 64-record window to pair complementary sizes.
3. Prefer tightly packed **physical 4 KiB blocks** when records fit.
4. Use versioned, aligned **8 or 16 KiB extents** for cases such as
   2,072-byte LZ4 objects where two cannot fit inside a single 4 KiB block.
   Physical blocks can contain parts of different compressed records.
5. Read only the 4 KiB metadata block and additional blocks actually
   containing the requested record. Expose a per-record 4 KiB read budget.
6. Reclaim stale records with generation-safe segment-local GC, relocating
   only live objects into dense extents, without invalidating old authority
   until replacement lower writes finish. Recycle a victim only after all
   live records have moved and read pins / IO ownership are safe.
7. Preserve raw incompressible 4 KiB pages and zero/discard handling.
8. Drain before flush/FUA, reject torn writes, preserve mapping authority
   and byte-exact reads, and account lower **completed bytes and requests**.
9. Benchmark meaningful workloads on verified disposable devices: uniform
   2,072B, 1,048B, clustered 2,200/1,600B, alternating, mixed and hot/cold;
   report lower writes+reads+GC, achieved IOPS, CPU, drain and p95/p99.

The optimization is a **write/read/CPU/GC Pareto frontier**, not compression
ratio or physical writes alone. A device whose minimum read is one physical
4 KiB block is never claimed to perform a sub-4KiB read.

## Version decision

- **V2.2** is retained unchanged as the stable *control implementation* and
  any proven production-like functionality. Package `dkms.conf` for the old
  `dm-swapz.ko` intentionally stays `0.2.2`; old installations must never
  silently upgrade to an incompatible layout.
- **V3.0.0-alpha.1** is the **new active development line**. Its distinct
  `SWZ3` format and the experimental DM target name `swapz3` do not
  decode V2.2's `SPWZ` layout. No in-place migration is supported.
  V3 does **not** imply persistent/resumable data.
- Prior ROADMAP.md reserved V3.0 for persistent hibernation. That was a
  planning name, not a released contract. **Persistent hibernation/resume
  moves to a separate future V4.0 architecture** and remains forbidden
  until crash-consistent durable metadata, boot/resume and power-loss tests
  are independently qualified.

## Hard exit gates (do not imply success merely from CI)

**M1 — codec + transaction core.** Versioned 4/8/16KiB bytes, CRC32C,
staged-generation immutability, quarantine and fail-closed publication.
PRs #40, #42, #43 and independent PR #41 underpin these tests.

**M2 — actual standalone V3 Device Mapper target.** Separate
`dm-swapz3.ko` with actual LZ4+raw fallback, sorted bounded write windows,
lower synchronous DM I/O, exact per-upper-BIO ownership and completion,
targeted reads, whole-range discard, flush/FUA and safe removal.
Validate on rootless source tests and *real loaded* `null_blk` only after
source/static+kernel compile gates. Target must not borrow the V2.2 tables.

**M3 — reclaim and density maintenance.** Low-live segment selection, bounded
relocation through size-class regrouping, GC lower **read and write** counters,
no allocation recursion, victim reuse only after full migration and safe
read ownership. Pressure test repeated victim reuse and reserve exhaustion.
**No sustained swap pressure or SD-card benchmark before M3 passes.**

**M4 — physical-medium qualification.** Guarded SD-specific harness for the
user-authorized dedicated `/dev/sdb1`, with exact identity/active swap,
holders, mount and memory checks; SSD/HDD as separately available. No
reboot. Compare against V2.2 on identical LZ4 inputs and achieved reader
load, including concurrency, GC, p99 and physical sectors. No unsupported
claims of flash program granularity, endurance or partial-block reads.

**M5 — hardening and release.** Repeated teardown, error/timeout/fault cases,
module provenance and CI, DKMS opt-in V3 packaging, system integration and
explicit incompatible-format labeling.

## Agent roles and test authorization

ChatGPT writes and reviews production allocator, DM, GC and disk-format code.
Codex independently reproduces defects, tests real host/kernel and benches,
and may repair minor build/harness defects on isolated review branches.
No test agent may reinterpret rootless geometry as loaded-kernel speed.

The physical host / dedicated `/dev/sdb1` testing authorization already
exists after verifying device identity and safety. **ABSOLUTELY NO REBOOT.**
Do not point a null_blk-only runner at the SD card or change existing swap.
Only touch owned devices, and no performance test counts unless the exact
source, `.ko`, active mapper and lower-device identity are reconciled.

## Version success criteria

V3 becomes a user-facing release only when it handles real compressed and
raw swap pages with long-lived GC, passes exact readback under real device
fault/pressure conditions and improves the measured completed physical
4KiB read/write I/O frontier without unacceptable read p99/CPU regressions.
