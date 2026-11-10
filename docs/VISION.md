# Vision

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWAPSPACE2` is the only physical backing partition format. `SWZ` names the internal 4/8/16KiB extent-packing design; production extents contain only payload and zero padding, with all descriptors in RAM. Legacy serialized codecs are isolated test fixtures, **not** a partition format or permission to persist swapz metadata. Do not invent a new format identity.

**Three-tier test policy:** `make fast_test` is development-only and never qualifies or publishes `test_results.json`; `make test` runs the algorithm/RAM path and returns INCOMPLETE (nonzero) until physical source/run/target admission is qualified; `make test_full` retains all rootless DKMS/systemd integration and RAM qualification. Both privileged tiers report BLOCKED (nonzero) if noninteractive privilege is unavailable. RAM/integration PASS cannot certify physical storage or cold-boot production acceptance. Private scripts and CI jobs are implementation details, not operator interfaces.

## Mandatory ordinary Linux swap partition design (2026-11-09)

Real backing must be an existing, valid SWAPSPACE2 Linux swap partition.
Never repartition, run mkswap on, or rewrite its header, UUID or partition
table. After a safe swapoff and exact-exclusive admission, only the data
area after the protected 4096-byte first page may be used. The newly
created virtual Device Mapper mapper alone may receive mkswap.
Switch between ordinary swap and swapz with verified swapoff/swapon,
without reboot. An active selected partition may have nonzero `Used`; PREPARE
records that ordinary-swap policy instead of requiring an artificially empty
partition, and START lets the kernel `swapoff` migrate live pages before any
exclusive mapper mutation. After a successful trial, obtain the owner's choice:
keep swapz active or return to ordinary Linux swap.

All swapz-specific record and extent descriptors, offsets, lengths,
generations, CRCs, mapping/segment allocation and GC metadata must
be bounded volatile RAM state. Production kernel compressed extents store payload bytes and deterministic
zero padding only; descriptors, offsets/lengths, generations, CRCs, mapping,
segment allocation and GC authority live in bounded RAM. Legacy serialized
SWZ codec helpers may remain only in isolated userspace fixtures and are not a
partition format or production data path. Preserve 4/8/16KiB packing, readback
integrity, ordering, concurrency and fail-closed semantics. Physical and
production acceptance still require the current-source qualification gates.

Earlier permissions to format/repartition even the dedicated SD card
are superseded; only post-swapoff swap *data* may be overwritten.

## Mission

swapz should reduce host-visible lower-storage traffic caused by swapping compressible 4KiB pages. Success means fewer independently measured lower READ and WRITE bytes **and** requests for the same verified logical workload, including flush and GC costs, while preserving correctness and keeping read latency, CPU and memory acceptable.

**Per-device-class goals (owner-adopted, ROADMAP ID174).** Compression can
only shorten service that waits on device bandwidth or queueing. Device-bound
classes (the serial and fast models' mixed and deep-QD rows, SD card and SATA)
must beat raw useful WRITE service. Latency-bound classes (closed-loop QD1 and
fast QD4) and host-bound classes (NVMe Gen4/Gen5 envelopes, where raw is
limited by host CPU) are guards that must stay within 5% of raw. Every class
must also reduce lower-device WRITE bytes and requests, and guards must never
add them. Real reclaim writes to a Device Mapper target asynchronously, so the
synchronous QD1/QD4 rows are guards rather than targets.

Compression ratio, encoded-size diagrams, mock counters, green CI or a single synthetic throughput win do not establish success. The decisive evidence is matched useful work plus independent lower-device accounting and byte-exact readback.

## Product

There is one implementation and one public product identity. Production kernel code is C under `src/kernel/`; the administrative utility is under `src/userspace/`. SWZ remains the internal extent-packing name, not a partition format or a product generation. The Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`.

`swapzctl status` provides read-only runtime representation accounting for
active swapz targets. It reports a compressed-SWZ ratio for committed compressed
extents and an overall ratio that also includes RAW fallback and zero elision.
Both are cumulative successful foreground-write ratios since target creation;
GC traffic is shown separately and excluded. They describe the storage
representation, not current live occupancy, performance qualification or
physical-media endurance.

The current implementation's packing design uses independently decodable 4KiB logical pages, ordinary LZ4 compression, page-local delta64 plus byte-shuffle and LZ4 rescue, whole-page RAW fallback, 4/8/16KiB extents, CRC/generation authority, bounded write windows, and ordered RAM-authority publication only after required lower I/O succeeds. **Main compression requirement:** every emulated device runs and is qualified with delta64 rescue enabled, `DELTA64_SHUF8` byte-plane shuffle (the owner-confirmed requirement is byte shuffle, not a bit-level bitshuffle), and LZ4. Delta64-off is not a performance mode to benchmark, plot or compare. The module-level disable switch is retained only for debugging/compatibility and cannot qualify an emulated-device result. The scalar sampled classifier runs before ordinary LZ4 so high-score pages can try delta64 + shuffle + LZ4 first, while lower-score pages retain the ordinary-LZ4 packing-cliff route. The shuffled payload has its own DELTA64_SHUF8 encoding; plain DELTA64 remains decodable for format compatibility. Delta64 never carries state across logical pages or extents.

## Non-negotiable correctness

Every accepted upper BIO has one completion owner and is completed exactly once. Only the latest successfully committed generation is readable. Same-page dependencies, overwrites, DISCARD, PREFLUSH/FUA, suspend/drain and GC preserve ordering. Failed, short, stale or corrupt lower operations fail closed and cannot publish new mappings. GC moves only authoritative live objects and cannot reuse a referenced or uncertain extent.

All allocations, work queues, staging arrays, segment scans and retries must remain bounded. The module must reject unsupported geometry and unowned backing.

## Safety scope

Generic loaded qualification remains restricted to newly created, positively identified RAM-backed `null_blk`. The algorithm tier is not physical qualified until the protected admission protocol works; full rootless integration/RAM PASS is not equivalent to physical production acceptance. Physical backing remains disabled by default and requires explicit module opt-in, an unchanged valid SWAPSPACE2 header, and exact exclusive ownership. For the current dedicated development PC, the owner has granted standing destructive and live-swap authority over the positively identified removable SD card described in [AGENT_CONTEXT.md](AGENT_CONTEXT.md); repeated per-run owner/external-review permission is not a release gate for that target. Exact device identity, source/artifact qualification, active-page protection and fail-closed lifecycle checks remain mandatory. Codex must not reboot or intentionally crash the PC, and no fallback swap is required.

## Engineering direction

Most development effort belongs in production kernel C: measured bottlenecks, completion/ordering bugs, layout decisions, read/write paths and GC. Python and shell exist only to qualify the product. Rejected experiments and historical compatibility systems should be removed after their conclusion is captured; Git history is the archive.

Current production policy keeps bounded asynchronous preparation enabled,
the delta64 + `DELTA64_SHUF8` + LZ4 stack fixed on for every emulated device,
lower-WRITE submission fixed at one immutable run, ordinary LZ4 fixed at
acceleration one, delta64 preparation fixed at one producer lane, and exact
adjacent READ coalescing bounded to eight 4KiB blocks. The existing eight
private READ slots overlap independent compressed or RAW misses; RAW retains
its authority CRC and bypasses compressed caches. The earlier write-only
wave driver remains historical burst evidence; current qualification uses
persistent lane-owned workers with no per-I/O main-thread dispatch.

The forward scheduling goal is **work-conserving lower service**. Compression,
packing and delta64 are representation optimizations, not correctness
prerequisites. When accepted independent WRITE data exists and a lower-WRITE
dispatch opportunity would otherwise be idle, a future qualified scheduler may
seal the best representation already available: compressed pages that are ready
plus whole-page RAW fallback for preparation that is not ready. It must never
wait solely to make a representation more compact when doing so loses more
useful service than the saved lower I/O is worth. Slow media should naturally
receive more completed compression because long lower service provides
preparation overlap; fast media may trade some lower bytes for continuous
service. The idle wait that retention may spend is therefore relative to the
device: once accepted work is staged, both accepted FIFOs are dry and no lower
WRITE is in flight, a window waits at most half of one measured lower-WRITE
service time, never a fixed millisecond timer that a fast device cannot repay.
RAW is chosen for latency only when measured compression time exceeds the lower
service its extra bytes would cost, so fast compression keeps both the
throughput and the host-write reduction. The existing per-BIO descriptor queue
remains the low-copy admission queue and the 64-slot preparation array the
stable RAW+compressed reservoir; K=1, SWZ and the single authority are
unchanged. The ID101–ID104 candidate (see ROADMAP) moves fast mixed, fast QD8
and fast QD32 above raw useful WRITE while writing 25–31% fewer lower bytes and
keeps the SD gains; SATA/NVMe mixed and fast QD4 still trail raw and are the
next targets. Promotion requires same-source owner `make test` evidence.

The next qualification priorities are work-conserving fast-media dispatch,
realistic churn/GC/TRIM evidence and representative-content evidence, not
dormant runtime concurrency knobs.

Longer-horizon opportunities remain explicit rather than being forgotten:
nonzero same-filled-page representation, exact-content deduplication,
compound/folio input coverage, background GC if foreground evidence justifies
it, and new concurrency experiments only when a fresh workload proves measured
pressure. Each must preserve the single authority/ordering model. Physical-device
qualification on the current dedicated SD card is an active production-readiness
workstream under the standing scope in [AGENT_CONTEXT.md](AGENT_CONTEXT.md);
generic physical-device claims still require device-specific evidence and never
follow automatically from RAM-backed qualification.
