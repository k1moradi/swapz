# Benchmark Standard

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

## Objective

Benchmark the one product, `swapz`, against an uncompressed `off` control using the same immutable logical workload. The Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`.

A performance result is useful only when the final logical image is byte-exact and source/fixture/trace provenance matches. The north-star metrics are independent lower READ and WRITE bytes **and** requests for completed useful work, including GC and flush effects, with acceptable useful throughput, read p95/p99, CPU and RAM.

## Current synthetic models

Mandatory loaded benchmarking uses newly owned RAM-backed `null_blk` only:

- slow model: 10 MiB/s lower cap, 1 ms completion delay;
- faster model: 80 MiB/s lower cap, 0.15 ms completion delay.

These model latency/bandwidth behavior; they are not measurements of real SD cards or SSDs. Do not label them as physical-media results.

The mixed QD32 matrix uses four counterbalanced pairs per model across sync/async preparation. It includes identical useful work, independent lower counters, full-image verification and bounded packed-read checks.

The write-only pilot uses QD1/4/8/32, 0% reads, finite unpaced waves, one sync and one async pair per QD/model, and exact final verification. One pair is exploratory only.

## Timed boundaries

Exclude fixture generation, device provisioning, worker allocation, buffer setup and warmup from measured useful throughput. Include the measured I/O and required final drain/fsync. Lower-sector/request deltas cover the same interval.

Report process CPU separately from kernel-worker CPU; do not imply one includes the other. RAM-backed 4MiB read tests are not cold physical swap-in.

## Current directional result

At qualified source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7`:

- slow mixed QD32 reached 6.96/7.12 MB/s sync/async with about 763 lower WRITE requests, 1.47x logical/backing ratio and only two mean deadline closes;
- faster mixed QD32 reached 19.53/22.57 MB/s with about 1400/1248 lower WRITE requests and 1.43-1.44x logical/backing ratio;
- seeded-random 4MiB lower READ traffic remained about 2.60MiB on the slow model and 2.35-2.39MiB on the faster model;
- QD1 stayed one block/request per page while reaching about 0.89-0.93x raw;
- QD8 recovered to about 0.89x raw on the slow model and 0.61-0.77x on the faster model;
- QD4 still used roughly 2025-2048 lower requests for 4096 medium writes and reached only about 0.60-0.70x raw.

Interpretation: read-service deadline charging and the prior QD8 regression are
no longer the primary blockers. QD4 now isolates a likely admitted-tail/window
chopping problem. All write-only QD figures remain exploratory one-pair pilots.

## Confirmation gate

Do not claim a QD performance improvement until each mode/QD/regime has at least five counterbalanced matched pairs, an appropriate confidence interval, unchanged correctness, provenance equality and no unacceptable regression in lower bytes, read tails, CPU/RAM or GC.

## Physical media

No current benchmark authorizes physical storage or active swap. A future real-device study requires separate owner authorization, exact device ownership/alias checks, backup/data-loss acceptance, independent safety review and a pinned source/procedure.


The next qualified comparison should specifically report whether the 512-entry
metadata cache reduces 4MiB seeded-random lower READ bytes/requests and p99, and
whether accepted-burst deadline handling reduces slow-model
`deadline_after_read` fragmentation. Cursor-aware planner reconstruction is a
WRITE-byte-neutral optimization: any increase in default lower WRITE bytes is a
rejection regardless of request count.


### Qualified admitted-tail result and next experiment

Source `b35a72cb5cc92bbb3bbe58b58a031985b62595a4` passed all five
qualification stages. Same-quantum admitted-tail draining preserved QD8,
mixed/read behavior and materially reduced async QD4 requests, but faster-model
async QD4 useful throughput regressed, so it is not promoted over
`f10a1e0...`.

The next candidate keeps `f10a1e0...` write/read geometry unchanged. When the
worker reaches its local tail it may append BIOs already present in `incoming`
and continue within the same 64-BIO quantum. Pack-ready admission also refreshes
`incoming` after preparation/copy/LZ4 work so a queue observation taken before
that work cannot falsely close a pack that already has an admitted successor.

This experiment adds no waiting interval and does not relax the accepted-burst
read cap. A QD4 request reduction therefore tests worker/window chopping rather
than a new lower-byte-versus-read-amplification tradeoff.


### Qualified adaptive retained-burst result

Source `4529140f689183ead86d94526b9974b875d915f4` passed all five
qualification stages. It confirmed that larger accepted windows can cut lower
WRITE requests dramatically: write-only QD4 used about 1032 requests, QD8 about
520, and faster-model QD32 about 138-139 for 4096 writes.

It is not promoted. Faster-model QD8 useful throughput fell materially despite
the lower request count, mixed faster-model QD32 fell to 16.39/18.06 MB/s
sync/async and accumulated about 214 mean deadline closes, and slow QD32 sync
collapsed its learned target to 3 with 82 deadline closes. The attribution
therefore shows that the learned width is useful while accepted work remains,
but harmful when an already useful packed window sits on an actually dry queue
only to wait for a larger historical target.

The next candidate keeps the accepted-burst cold-read cap at two and leaves
extent planning unchanged. A complete second pack closes immediately when the
finite accepted queue is dry; admitted-tail learning scans the worker-local FIFO
before `incoming`; and one two/three-record deadline cannot shrink the learned
target below the original four-record anti-chopping floor. No grace timer or
future-arrival wait is added. QD1 asynchronous preparation and GC allocation are
separate experiments.


### Qualified dry accepted-pack result

Source `0d8f7f7ea90c33fbac3a57d95f410e68275c1cea` passed all five owner
qualification stages. Slow mixed QD32 reached 7.09/7.25 MB/s sync/async with
about 640/635 lower WRITE requests and only 2.8 mean deadline closes. Faster
mixed QD32 recovered to 19.04/22.63 MB/s with 1236/1043 lower requests and
faster packed-read latency than raw.

The same source is not promoted. Write-only QD8 was split into many 5-8 plus
one/two-record windows, using about 1008-1028 requests on the faster model;
faster QD32 used about 868-892 requests and almost no 17-64-record windows.
This shows that unconditional dry second-pack closure solved deadline idling
but overrode the learned burst target too early.

The next candidate separates the two decisions. Admission closes only at the
effective target. A below-target worker-tail close requires refreshed queue
state plus service evidence from an earlier packed chain or an independent
read while the retained window was open. It also allows the ordered worker to
steal an asynchronous compression only before the producer claims that FIFO
entry, using distinct producer/ordered LZ4 work memory. GC destination probing
no longer restarts at segment zero; this is direct wear-distribution logic only
and remains unqualified by loaded endurance evidence until GC victims occur.

The decisive next comparison is simultaneous preservation: mixed faster-model
throughput should remain near the qualified recovery, QD8/QD32 lower-request
counts should move back toward the earlier deep-window result without extra
lower bytes, QD1 async should improve without losing high-QD overlap, and all
correctness/lifecycle/read-tail gates must remain intact.


### Qualified worker-tail aggregation result

Source `9f11a1a63bc4a3fc447d5ae7be9493b6e690f7ff` passed all five
owner-loaded qualification stages. It resolved the request-fragmentation
regression while preserving the mixed-path recovery: slow mixed QD32 reached
7.12/7.27 MB/s sync/async with about 543.5 lower WRITE requests; faster mixed
reached 19.58/22.81 MB/s with about 1066/950.5 requests and packed reads faster
than raw. Write-only QD8 used about 520 lower requests and faster QD32 about
139, restoring the intended deep-window geometry.

The source is not promoted over the accepted directional baseline because
faster-model intermediate-QD useful throughput remains weak: QD8 sync/async
reached 17.00/28.39 MB/s against about 49.9 MB/s raw, while QD4 remained about
13 MB/s. Faster mixed still recorded about 89.5 worker-empty deadline closes
and about 40 one-page deadline closes per pair. The write-only sweep remains a
one-pair exploratory pilot.

The next candidate makes PACK_READY worker-only, samples already-admitted
first-wave width before closure, permits any nonempty residue to close on a
refreshed dry worker tail only after real packed/read service evidence, gates
the asynchronous producer wake to actual overlap opportunity, and skips
redundant 512-byte metadata-LRU validity clears when the LRU is already empty.
It does not change extent planning, the accepted-burst read cap, mapping
publication, lower-byte geometry, cache authority semantics, or GC victim
selection.

Acceptance requires the mixed faster-model deadline cluster to shrink while
retaining the 9f11 mixed throughput/request result; QD8 useful throughput must
not trade away the restored ~520-request aggregation; QD1 async should narrow
its scheduling gap without losing high-QD preparation overlap; lower WRITE
bytes and read tails remain rejection gates. GC remains unqualified unless a
loaded run reports nonzero victims.


### Qualified demand-gated preparation result

Source `3e2344134de2548c5d6f71b48f6e8bbe508bb3df` passed all five
owner-loaded qualification stages. Slow mixed QD32 reached 7.09/7.21 MB/s
sync/async with about 557/559.5 lower WRITE requests. Faster mixed reached
19.50/21.34 MB/s against 19.33 MB/s raw, with about 1105/1139.5 lower WRITE
requests, lower READ bytes than raw, and packed read p99 below raw.

The source is not promoted. Faster write-only QD8 async regressed to
17.31 MB/s from 28.39 MB/s at the prior qualified source and used about
555 lower requests rather than ~520. Faster QD32 used 241/210 requests rather
than ~139 and showed many 2-16-record windows. Faster mixed still recorded
about 88.2 worker-empty deadline closes and 43.2 one-page deadline closes per
pair. QD1 async improved to 7.43 MB/s with 0.37 ms p99, so the next candidate
must preserve that lone-head benefit while restoring high-QD parallelism.

The current candidate reverses the two measured causes rather than adding a
new wait. Pre-write tail sampling is removed; target closure is restored after
accepted-follower refresh; empty flushes no longer erase ordinary retained
burst evidence; successful retained READ/fence evidence may release only a
tiny dry residue; and true idle/hard barriers clear it. Async preparation
leaves a lone idle head for ordered inline steal, but while the ordered worker
is active the producer prepares from the opposite queue end, switching to the
head during synchronous lower WRITE wait. Prepared-page capacity is reserved
nonblocking before BIO claim so queue depths above the 64-slot bound cannot
form a semaphore/FIFO deadlock.

Acceptance is simultaneous: QD8 should return toward ~520 lower requests,
faster QD32 toward ~139, high-QD async throughput should recover materially,
and the faster mixed worker-empty deadline cluster should shrink without
increasing lower WRITE bytes or degrading packed-read tails. QD1 async should
retain its improved latency/throughput. The one-pair write-only sweep remains
directional only, and GC remains unqualified unless the loaded run observes
nonzero victims.
