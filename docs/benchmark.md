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

Report replay-process CPU separately from kernel callback wall residency.
Callback wall is not CPU time: ordered callback wall includes synchronous
lower-I/O sleep and callback wall may include scheduler delay. Use explicit
LZ4/CRC/copy/plan/pack/publish timers for hot-path attribution. RAM-backed 4MiB
read tests are not cold physical swap-in.

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


### Qualified retained-service/opposite-end result

Source `658f390a03f546b35ba068900d5ec700126b7e99` passed all five
owner-loaded qualification stages. The retained-window changes restored deep
write-only aggregation: QD8 used 520 lower WRITE requests in every model/mode,
and faster QD32 used 147/138 sync/async requests. QD1 async remained
7.39 MB/s with 0.37 ms p99.

Mixed QD32 also improved. Slow sync/async reached 7.12/7.28 MB/s with about
544 lower requests. Faster sync/async reached 20.19/22.65 MB/s against
19.54 MB/s raw, with packed reads faster than raw. Faster worker-empty deadline
closes fell to about 59 per pair from ~88 at 3e23441, and one-page deadline
closes fell to 31.5 from ~43.

The source is not promoted. Faster write-only QD8 still showed essentially no
asynchronous preparation gain: 17.10/17.21 MB/s against about 49.9 MB/s raw,
despite the correct 520-request geometry. QD4 similarly remained about
12.85 MB/s. Faster QD32 async reached 33.21 MB/s versus 29.25 sync, showing
that larger queued bursts can expose some preparation overlap while
intermediate queue depths still serialize.

The next candidate changes only preparation scheduling and diagnostics. Outside
synchronous lower WRITE wait, the producer receives one atomic tail-claim
credit for each ordered BIO that owns real execution time; an asynchronous
WRITE publishes that credit only after reserving its FIFO head. A normal tail
claim returns after one prepared BIO instead of draining subsequent entries.
During lower WRITE wait the producer may still drain head-first. This is
intended to split QD4/QD8 compression between the ordered worker and producer
rather than letting the producer claim every next FIFO item and make the
ordered worker wait for completion.

The official report now attributes producer head/tail claims, ordered inline
preparations, producer handoffs and actual blocking completion waits. Acceptance
requires QD1 behavior and QD8/QD32 request geometry to remain intact, QD8 async
throughput to improve materially without extra lower WRITE bytes or read-tail
regression, and blocking waits to fall relative to producer handoffs. The
remaining mixed deadline cluster is a separate later experiment.


### Qualified credited-preparation result and scheduling-only successor

Source `44363933e9e401ccaf3a3af6c1fa42b2878d2bab` passed all five
owner-loaded qualification stages. It preserved write-only aggregation:
async QD8 used exactly 520 lower WRITE requests on both RAM models and
faster-model async QD32 used 139. QD1 async remained 7.12 MB/s with 0.37 ms
p99 and recorded zero producer head/tail claims.

The one-shot ordered-execution credit did not restore write-only asynchronous
preparation. Faster QD8 async reached 17.32 MB/s versus 17.71 sync while its
diagnostics showed producer head=9, tail=1, ordered inline=5366. Faster QD32
async reached 31.15 MB/s versus 31.29 sync with producer head=24, tail=2,
ordered inline=5350. In contrast, faster mixed QD32 averaged 5464 producer-tail
claims, showing that the mechanism works when ordered service intervals are long
enough for the producer to consume the token.

The next candidate changes scheduling only. An inline ordered WRITE may leave
one earned tail token alive across the inter-BIO gap of an open retained
window; the next admitted companion can wake the producer from that atomic
token without reading worker-owned `batch_count`. The producer remains
one-for-one paced but may consume a fresh token earned while it is already
running. Any nonempty window close clears the unused token.

The serialized ordered workqueue also becomes
`WQ_MEM_RECLAIM | WQ_UNBOUND`, matching the preparation worker's unbound
placement while preserving one active ordered worker, FIFO execution,
publication authority and synchronous lower-I/O ownership. Retention/window
policy, extent planning, lower-byte gates, read policy and GC are unchanged.

Acceptance is directional until repeated pairs exist: QD1 must keep zero
producer claims, QD8/QD32 request geometry must stay near 520/~139, write-only
producer-tail claims must become substantial, and blocking waits must not
become a serial handoff convoy. Lower WRITE bytes and packed-read tails remain
hard rejection gates.


### Qualified persistent-credit result and head-cushion successor

Source `6330cb5d264a7cf563f4a161c29ac9ccd1d3e08b` passed all five
owner-loaded qualification stages. Persistent retained-burst credit restored
producer participation while preserving write-only aggregation. On the faster
RAM model, QD8 async used 520 lower WRITE requests with 2071 producer-tail
claims; QD32 async used 138 requests with 2142 tail claims. QD1 recorded zero
producer claims.

The same counters reject the current handoff policy. Faster QD4/QD8/QD32
blocking waits were 943/1373/1941 for 2029/2074/2164 handoffs, so producer work
was frequently claimed too near the ordered FIFO head. On a singular
`preparation_incoming` list, `list_last_entry` is the same entry as
`list_first_entry`; that nominal tail claim is therefore an immediate
head-of-line collision, not useful opposite-end overlap.

Faster mixed async also used 1155 lower WRITE requests and recorded 160.2 mean
one-page PACK_READY closes, compared with materially lower request counts in
earlier qualified runs. The next candidate consumes retained read/fence evidence
after a dry PACK_READY close so one serviced interruption cannot authorize
repeated later singleton closes. DUPLICATE/FULL continuation and the zero-count
flush path remain unchanged.

The next comparison keeps the unbound ordered worker, persistent credit,
retained targets, extent planner, read cap and GC policy fixed. Outside lower
WRITE wait the producer may consume a credit only when at least two unclaimed
preparation entries exist, preserving one FIFO head cushion. Acceptance requires
QD1 to retain zero producer claims, QD8/QD32 request geometry to remain near
520/~138, blocking waits to fall sharply relative to handoffs, and faster mixed
async lower WRITE requests/one-page PACK_READY closes to fall without increasing
lower WRITE bytes or regressing packed-read tails. The write-only sweep remains
directional until statistically repeated pairs exist.


### Qualified head-cushion result and singular-wake avoidance

Source `6642e7ebfce3255267f51fe99b66114122bda7e0` passed all five
owner-loaded qualification stages. The singular-head guard removed the
preparation convoy: SSD-model QD4/QD8/QD32 write-only async blocking waits
became zero instead of 943/1373/1941 at `6330cb5`. It also reduced
producer-tail claims to 16/14/0, demonstrating that staggered submissions
rarely leave two unclaimed entries for opposite-end preparation.

SSD-model QD8 async reached 26.24 MB/s versus 19.58 sync while keeping 520
lower WRITE requests; QD32 async reached 46.87 MB/s versus 46.01 sync
with 138/139 lower requests. These are single-pair pilots without confidence
intervals, not established advantages. Mixed SSD-model async reached 21.80
MB/s with 1007 lower WRITE requests, 26.5 blocking waits per pair, 136
one-page PACK_READY closes, and packed read tails below raw. The slow-model
mixed async remained 7.09 MB/s with 544.5 requests and packed read tails
worse than raw. Loaded GC victims remained zero.

The next candidate is intentionally narrower than reclaiming parallel
compression: do not wake a producer whose only unclaimed entry is the FIFO
head, because it cannot consume the retained tail token on a singular list.
The inline-WRITE and map-admission wake sites both check the protected
preparation-list topology under `queue_lock`. Active lower WRITE continues to
wake head-first without a two-entry requirement. No accepted BIO is skipped,
no credit is consumed by a rejected singular case, and no retention or
physical-byte policy changes.

Acceptance requires unchanged correctness, QD1 zero producer claims,
write-only QD8/QD32 requests near 520/~138, no reintroduced blocking waits,
and preserved mixed lower WRITE savings/read tails. An exploratory throughput
change alone is not grounds to claim a performance improvement; the project
still requires repeated counterbalanced pairs and confidence intervals.


### Rejected singular-wake suppression and rollback

Source `2ad805b02da02af95eed78945338876f831e61e0` passed all five
owner-loaded stages, so the rejection is performance/geometry based rather than
a correctness failure. Against qualified exploratory source `6642e7e`, SSD
mixed async useful WRITE throughput fell from 21.80 to 20.92 MB/s, lower WRITE
requests rose from 1007 to 1091.5, worker-empty deadlines rose from 59.5 to 74,
and one-page PACK_READY closes rose from 136 to 146. Packed sequential/random
read p99 also moved from 4.80/5.42 ms to 5.37/5.78 ms.

The write-only single-pair SSD QD8 result simultaneously fell from 26.24 to
20.74 MB/s while request geometry remained 520. Producer work did not increase:
QD8 recorded only 13 tail claims and zero blocking waits. This is not evidence
that singular-head claiming should return; it shows that suppressing a
credit-driven wake from an instantaneous queue snapshot changed useful
scheduling without eliminating meaningful preparation work.

The next source restores the `6642e7e` production wake behavior while keeping
the producer-side singular guard that eliminated the completion convoy.
Retention policy, LZ4/extent planning, lower-byte policy, read behavior and GC
are otherwise unchanged. The rollback must itself pass the full official
qualification before any new preparation-ahead policy is attempted.

### Qualified rollback result and accepted-wave overlap successor

Source `5aeae47f82c71bbc3e5722b977f684d08eee0083` passed all five
owner-loaded qualification stages. The restored producer wake behavior recovered
the rejected scheduling regression while retaining the producer-side singular
head guard. Slow mixed QD32 async reached 7.10 MB/s with 544.5 lower WRITE
requests. Faster mixed async reached 21.18 MB/s versus 19.49 sync and 19.39 raw,
with 1029 lower WRITE requests and 2.58 ms mixed READ p99.

The write-only pilot again preserved deep aggregation. Faster-model async QD8
used 520 lower WRITE requests and reached 29.75 MB/s versus 20.69 sync; QD32
used 138 requests and reached 46.89 MB/s versus 45.02 sync. These are
single-pair directional observations, not established performance.

The rollback is preferred over rejected `2ad805b`, but the mixed path still
has avoidable scheduling fragmentation: faster mixed averaged 70.2 worker-empty
deadline closes and 1029 lower WRITE requests, compared with about 59.5 and
1007 at qualified exploratory source `6642e7e`. Faster write-only QD4/QD8 also
showed little producer participation despite useful async throughput: QD4
recorded 30 producer-tail claims versus 5346 ordered-inline preparations and
QD8 recorded 9 versus 5363.

The next candidate uses that measured gap rather than adding another arrival
timer. Immediately after the ordered worker captures a finite incoming wave, it
may grant one tail credit when at least two unclaimed WRITE preparations already
exist. The producer still cannot claim a singular FIFO head, remains one-for-one
paced outside lower-I/O service, and continues to drain head-first only while a
synchronous lower WRITE is active. No new future-arrival wait, extent geometry,
retention rule, mapping publication rule, read policy or GC policy is added.

New attribution measures producer LZ4 time wholly contained in lower-WRITE
waits, actual ordered completion-wait time, and accepted-wave kicks. The dead
`ordered_worker_busy` state is removed. Human output is condensed into narrow
tables while the complete telemetry remains in `build/test_results.json.xz`;
sync remains a compact scheduling control rather than a verbose report arm.

Acceptance requires QD1 to retain zero producer claims, QD4/QD8 producer
participation to rise without a completion convoy, QD8/QD32 request geometry to
remain near 520/~138, and faster mixed request/deadline behavior to improve or
hold without increasing lower WRITE bytes or degrading packed-read tails. GC
endurance remains unqualified until loaded testing observes nonzero victims.



### Qualified accepted-wave result and CPU-local preparation successor

Source `e5c172177242e3f7edcc6e470989eb3a71a43e92` passed all five
qualification stages. On the faster RAM model, mixed QD32 async reached
23.74 MB/s versus 19.71 MB/s sync, with 874.5 lower WRITE requests and
2.10 ms mixed READ p99. Relative to the preceding qualified `5aeae47` run,
async useful WRITE increased about 12%, lower WRITE requests fell about 15%,
and worker-empty deadline closes fell from 70.2 to 60.5 per pair. The slow
model remained effectively neutral at 7.09 MB/s async versus 7.08 sync.

The accepted-wave kick therefore improved the mixed scheduling path, but the
new overlap counters show that producer placement is still inefficient.
Faster-model mixed recorded 70.6 ms total LZ4 wall time and 183.9 ms lower
WRITE wall time, while only 3.8 ms of producer LZ4 was wholly contained inside
lower-WRITE waits. Ordered preparation blocking was only 0.58 ms. This points
to dispatch/placement latency and CPU competition rather than a producer
completion convoy.

The write-only pilot remains directional. Faster QD8 async kept 520 lower
WRITE requests and exceeded its same-run sync control by about 18%, but the
single absolute async point was 21.80 MB/s versus 29.75 MB/s in the preceding
run. Because both sync and async moved and there is one pair per point, this is
not confirmatory evidence by itself. QD1 still recorded zero producer claims.

Source `e199ac5399808fbf3dcf470989eb3a71a43e92` qualified the CPU-local
preparation experiment and rejected it on useful behavior. Faster-model proven
LZ4-inside-lower-WRITE overlap increased from 3.8 ms to 6.4 ms and ordered
preparation wait fell from 0.58 ms to 0.01 ms, but async mixed WRITE fell from
23.74 to 20.37 MB/s, lower WRITE requests rose from 874.5 to 1055, and
worker-empty deadline closes rose from 60.5 to 72.5. Faster write-only QD8
preserved 520 lower requests but async reached 19.32 MB/s versus 20.49 sync.
The experiment therefore improved overlap while regressing the product metric;
bound preparation placement is removed rather than layered with another
scheduling heuristic.

The next candidate restores the accepted unbound preparation workqueue and adds
kernel-C attribution for explicit RAM-copy wall time/bytes. It also measures
write-engine commit time and targeted-read engine time with synchronous lower-I/O
wait subtracted. This is diagnostic instrumentation, not a new I/O/layout
policy. If copy time is material, the next optimization can target direct
single-BIO LZ4 input/output; if non-I/O engine time dominates, packing/CRC and
authority work become the next profiling target.


### Direct write-input and commit-phase successor

Qualified source `c6d15ca56753610ed21d805333a49b6a291a36cb` made the
previously hidden memory/CPU cost measurable. Faster-model mixed async recorded
83.6 ms LZ4, 22.4 ms explicit WRITE copies moving 59.4 MiB, 46.2 ms write
commit non-I/O, and 216.6 ms synchronous lower WRITE. Packed-read output copying
was only 1.1-1.4 ms, so read-side zero-copy is deprioritized. Faster write-only
QD8 remained directionally favorable at +19.5% async versus sync with 524 lower
requests, while QD1 remained producer-free.

Source inspection shows that serialized commit still copies each compressed
payload from batch storage into `bulk_scratch` in `swapz_append()`, computes
its payload CRC there, and later revalidates the sealed extent/payload CRC during
`swapz_finish()`. Batch snapshot pause/resume also hashes the transaction.
Those checks are intentionally unchanged in the next candidate.

The successor maps a complete single-bvec 4KiB upper WRITE page directly for
LZ4 and zero scanning, preserving the existing copy fallback and RAW persistent
staging. It also reports planner, pack and post-I/O publish wall time inside the
46.2 ms commit non-I/O envelope. Acceptance requires lower copy time/bytes with
no loss of useful throughput, request geometry, read tails or lifecycle
correctness; engine phase timing is diagnostic and must not itself change
packing/publication behavior.


### Qualified direct-input result and RAW/CPU successor

Source `39e7787b784410140cf90d3fe3a08ad4d674f4f2` passed full qualification.
Direct input covered 12,301 mixed foreground pages. Faster-model explicit
WRITE-copy cost fell to 3.9 ms / 11.0 MiB from 22.4 ms / 59.4 MiB, while mixed
async reached 21.22 MB/s versus 19.89 sync and write-only QD8 reached 25.50
versus 19.84 MB/s with 520 lower requests. Slow-model explicit copying fell to
4.7 ms / 9.1 MiB and useful mixed behavior remained neutral.

The 48.5 ms faster-model commit non-I/O interval split into 5.2 ms planner,
16.4 ms pack, 18.9 ms publish and 8.0 ms residual. Publish is not synonymous
with CRC: it includes batch resume, validation, liveness/generation checks and
mapping publication. Residual is likewise not synonymous with batch CRC: it
contains stage/pause/allocation, alignment-hole clearing and control overhead.
Future CRC removal requires isolated evidence plus equivalent fail-closed
validation.

The successor removes one remaining inline RAW bounce. A directly mapped
incompressible page is copied straight to its durable `batch_bytes` slot when
bulk RAW admission is active. In non-bulk mode the mapping is simply released
and the still-owned BIO is copied once later by `swapz_raw_write()`. It also
reports scheduler-accounted CPU time for the ordered and preparation workqueue
callbacks using the exported cputime API. These CPU counters are diagnostics
and overlap wall-time phases.
