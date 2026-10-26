# Vision

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

## Mission

swapz should reduce host-visible lower-storage traffic caused by swapping compressible 4KiB pages. Success means fewer independently measured lower READ and WRITE bytes **and** requests for the same verified logical workload, including flush and GC costs, while preserving correctness and keeping read latency, CPU and memory acceptable.

Compression ratio, encoded-size diagrams, mock counters, green CI or a single synthetic throughput win do not establish success. The decisive evidence is matched useful work plus independent lower-device accounting and byte-exact readback.

## Product

There is one implementation and one public product identity. Production kernel code is C under `src/kernel/`; the administrative utility is under `src/userspace/`. SWZ is the current unversioned format name, not a product generation. The Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`.

The format uses independently decodable 4KiB logical pages, ordinary LZ4 compression, optional page-local delta64 plus LZ4 rescue, whole-page RAW fallback, 4/8/16KiB extents, CRC/generation authority, bounded write windows, and serialized publication only after required lower I/O succeeds. Delta64 rescue is experimental and off by default; when explicitly enabled, its scalar sampled classifier runs before ordinary LZ4 so high-score pages can try delta64 first, while lower-score pages retain the ordinary-LZ4 packing-cliff route. Delta64 never carries state across logical pages or extents.

## Non-negotiable correctness

Every accepted upper BIO has one completion owner and is completed exactly once. Only the latest successfully committed generation is readable. Same-page dependencies, overwrites, DISCARD, PREFLUSH/FUA, suspend/drain and GC preserve ordering. Failed, short, stale or corrupt lower operations fail closed and cannot publish new mappings. GC moves only authoritative live objects and cannot reuse a referenced or uncertain extent.

All allocations, work queues, staging arrays, segment scans and retries must remain bounded. The module must reject unsupported geometry and unowned backing.

## Safety scope

Current official loaded qualification is restricted to newly created, positively identified, RAM-backed `null_blk`. Physical backing remains disabled by default and is admitted only behind an explicit module opt-in plus a matching block-0 SWAPZ authorization header on a dedicated device. The formatter/guard are safety prerequisites, not performance or endurance qualification. No current result authorizes active system swap, mounting, reboot, `swapon`, `swapoff`, force removal or touching unrelated mappings. Real-device work remains a separately authorized qualification project.

## Engineering direction

Most development effort belongs in production kernel C: measured bottlenecks, completion/ordering bugs, layout decisions, read/write paths and GC. Python and shell exist only to qualify the product. Rejected experiments and historical compatibility systems should be removed after their conclusion is captured; Git history is the archive.

Current production policy keeps bounded asynchronous preparation enabled,
lower-WRITE submission fixed at one immutable run, ordinary LZ4 fixed at
acceleration one, delta64 preparation fixed at one producer lane, and exact
adjacent READ coalescing bounded to eight 4KiB blocks. The earlier write-only
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
service. Alpha.29 implements the first bounded candidate without changing SWZ: the
existing per-BIO descriptor queue stays the low-copy admission queue and the
64-slot preparation array is a stable RAW+compressed reservoir. Owner
`make test` now passes full correctness/lifecycle qualification on source
`91c2cb2edb1e` (report `aacf96c02325`), so the remaining ID83 question is
performance policy rather than basic lifetime safety. That same run shows the
first dispatcher policy is not yet qualified on fast media: it creates
significantly more lower WRITE requests than synchronous preparation and
regresses sustained QD32 service. The next bounded refinement therefore keeps
K=1/SWZ/authority unchanged, forces RAW only when lower service is truly idle,
extends an eight-record pressure hand across already-READY accepted work, and
closes READY dry tails without retention sleep. The stable RAW snapshot remains
a mandatory ownership boundary. Promotion still requires same-source owner
evidence that preserves the SD gains while improving fast-media useful service
and lower-I/O economics.

The next qualification priorities are work-conserving fast-media dispatch,
realistic churn/GC/TRIM evidence and representative-content evidence, not
dormant runtime concurrency knobs.

Longer-horizon opportunities remain explicit rather than being forgotten:
nonzero same-filled-page representation, exact-content deduplication,
compound/folio input coverage, background GC if foreground evidence justifies
it, and new concurrency experiments only when a fresh workload proves measured
pressure. Each must preserve the single authority/ordering model. Physical-
device qualification remains a separately authorized future project, not an
extension of the RAM-backed development harness.
