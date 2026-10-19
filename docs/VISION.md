# Vision

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

## Mission

swapz should reduce host-visible lower-storage traffic caused by swapping compressible 4KiB pages. Success means fewer independently measured lower READ and WRITE bytes **and** requests for the same verified logical workload, including flush and GC costs, while preserving correctness and keeping read latency, CPU and memory acceptable.

Compression ratio, encoded-size diagrams, mock counters, green CI or a single synthetic throughput win do not establish success. The decisive evidence is matched useful work plus independent lower-device accounting and byte-exact readback.

## Product

There is one implementation and one public product identity. Production kernel code is C under `src/kernel/`; the administrative utility is under `src/userspace/`. SWZ3 is the format name, not a product generation. The Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`.

The format uses 4KiB logical pages, LZ4 compression, whole-page RAW fallback, 4/8/16KiB extents, CRC/generation authority, bounded write windows, and serialized publication only after required lower I/O succeeds.

## Non-negotiable correctness

Every accepted upper BIO has one completion owner and is completed exactly once. Only the latest successfully committed generation is readable. Same-page dependencies, overwrites, DISCARD, PREFLUSH/FUA, suspend/drain and GC preserve ordering. Failed, short, stale or corrupt lower operations fail closed and cannot publish new mappings. GC moves only authoritative live objects and cannot reuse a referenced or uncertain extent.

All allocations, work queues, staging arrays, segment scans and retries must remain bounded. The module must reject unsupported geometry and unowned backing.

## Safety scope

Current loaded work is restricted to newly created, positively identified, RAM-backed `null_blk`. No current result authorizes physical storage, active swap, mounting, reboot, `swapon`, `swapoff`, force removal or touching unrelated mappings. Real-device work is a separately authorized future project.

## Engineering direction

Most development effort belongs in production kernel C: measured bottlenecks, completion/ordering bugs, layout decisions, read/write paths and GC. Python and shell exist only to qualify the product. Rejected experiments and historical compatibility systems should be removed after their conclusion is captured; Git history is the archive.

The next performance problem is low/medium queue-depth efficiency. The first QD pilot shows large QD1 loss and QD4/QD8 useful-throughput loss despite lower-request savings, while only the slow-model QD32 arm exceeds raw. Optimize only from measured production-C attribution and preserve all correctness gates.

Longer-horizon opportunities remain explicit rather than being forgotten:
nonzero same-filled-page representation, exact-content deduplication, queued
same-extent READ coalescing, background GC, and carefully gated K>1 lower-I/O
parallelism. Each must first prove measurable opportunity and preserve the
single authority/ordering model. Physical-device qualification remains a
separately authorized future project, not an extension of the RAM-backed
development harness.
