# Benchmark Standard

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

## Objective

Benchmark the one product, `swapz`, against an uncompressed `off` control using the same immutable logical workload. The Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`.

A performance result is useful only when the final logical image is byte-exact and source/fixture/trace provenance matches. The north-star metrics are independent lower READ and WRITE bytes **and** requests for completed useful work, including GC and flush effects, with acceptable useful throughput, read p95/p99, CPU and RAM.

## Current synthetic models

Mandatory loaded benchmarking uses newly owned RAM-backed `null_blk` only:

- slow model: 10 MiB/s lower cap, 1 ms completion delay, blk-mq with one
  submit queue and `hw_queue_depth=1`;
- faster model: 80 MiB/s lower cap, 0.15 ms completion delay, blk-mq with one
  submit queue and `hw_queue_depth=64`.

These model latency/bandwidth behavior; they are not measurements of real SD cards or SSDs. Do not label them as physical-media results. Every timed arm samples the positively identified lower device's block-layer READ/WRITE in-flight counters and reports sampled boundary depth, peak and time-weighted mean. swapz mixed arms also report K=1 immutable-run slot occupancy from async submission through ordered publication.

The mixed QD32 matrix keeps four sessions on the slow model as a bounded directional control and uses ten fast-model sessions arranged as five adjacent counterbalanced sync/async matched rounds. It includes identical useful work, independent lower counters, full-image verification and bounded packed-read checks. The fast matched deltas carry two-sided Student-t 95% confidence intervals.

The write-only sweep uses QD1/4/8/32, 0% reads, finite unpaced waves and exact final verification. Fast QD8 receives ten sessions/five matched rounds with paired 95% confidence intervals; slow QDs and fast QD1/QD4/QD32 remain directional controls. Fast QD4 previously received one five-pair confirmation and returned to directional status after its CI crossed zero.

## Timed boundaries

Exclude fixture generation, device provisioning, worker allocation, buffer setup and warmup from measured useful throughput. Include the measured I/O and required final drain/fsync. Lower-sector/request deltas cover the same interval.

Report replay-process CPU separately from kernel callback wall residency.
Callback wall is not CPU time: ordered callback wall includes synchronous
lower-I/O sleep and callback wall may include scheduler delay. ID24 additionally
reports scheduler-accounted sampled worker CPU from
`current->se.sum_exec_runtime` for ordered, preparation and read-helper work.
Direct boundary samples can materially miss short callbacks that return before
the scheduler updates the current entity, so treat them only as a lower-bound
diagnostic. The report also carries separate ordered/preparation LZ4 and copy
timers and derives measured non-sleeping phase floors from LZ4/CRC/copy plus
ordered commit-non-I/O work. Those floors still do not equal total worker CPU;
use external scheduler accounting before worker-count/affinity decisions. RAM-backed 4MiB read tests are not cold physical swap-in.

Window-size bins, close reasons, one-page close reasons, deadline contexts,
burst-learning counters, preparation counters and GC-victim attribution are
sampled by `io-replay.py` at this same measured boundary. Full-process
`SWAPZ_STATUS_BEFORE/AFTER` output is not used for those report tables because
it also contains prefill, warmup and post-mixed packed-read population.
`retained_burst_target` is an end-of-interval gauge, not a delta.

The current unqualified candidate also retains successfully read payload blocks
from one immutable 16KiB extent so sequential sibling records do not re-read a
block already present in `read_scratch`. This is a duplicate-I/O elimination
experiment, not yet evidence that the faster packed-read verdict becomes
FASTER. The next owner run must report actual lower READ bytes/requests and
latency before any such claim. It also reports
`batch_snapshot_crc_wall_ns` for the unchanged full-transaction pause/resume
CRC so ID 12 can be judged from measured cost rather than estimated hash bytes.

## Current directional result

Owner-qualified source `1352e46f3051315eab273ae11c0a5a9bd54ce340`
(report-only `e25f0a0d0e1c3b4ea65e7297593f5b10d4dffe27`) passed all five
stages. It is synthetic owned-RAM evidence only.

Fast mixed async/sync is 23.12/22.63 MB/s with 977.6/883.2 lower WRITE
requests. Five matched pairs give +2.2%, CI [-3.2%,+7.7%], and absolute request
delta +94.4 CI [+14.3,+174.5]. The async throughput gain is not established and
the fragmentation penalty is significant.

ID54/55 remain stable: tail async-minus-sync is -41.2
CI [-71.1,-11.3], learned burst +90.2 [+36.9,+143.5], service-dry +30.4
[+3.5,+57.3]. Burst closes are admission-only; count17-64 is +66.2
[+26.4,+106.0] and overshoot +71.4 [+27.5,+115.3].

ID56 proves the temporal asymmetry directly. Fast sync has no post-PACK samples
while K=1 is active. Async records 604.2 tail0/inflight, 116.4 tail1/inflight
and 70.4 tail2+/inflight. Slow async also records 482.0 tail0/inflight while
sync/async throughput is equal, so the observation alone is not a universal
performance predicate.

ID57 is the bounded active test. A pending early PACK_READY close is suppressed
only while the previous detached lower write is active and not yet complete.
A zero pending tail sample is preserved while K=1 is active and across the
immediate completion-only worker pass, then resolved before processing the next
already-admitted wave. No new wait/timer/concurrency is added; FULL, DEADLINE,
ordering boundaries, tail>=1 handling, ID50 and K=1 publication/completion
ownership remain unchanged.

Latest fast write-only QD8 is +23.1%, paired CI [+8.4%,+37.9%]. Fast QD4
five-pair confirmation is +1.4%, CI [-0.7%,+3.6%], so QD4 returns to a
directional control. Latest Kread same-cache result is inconclusive
(seq -10.3% [-22.5,+1.9]%; random -0.5% [-11.0,+9.9]%) and remains unchanged.

## Confirmation gate

Do not claim a QD performance improvement until that specific QD/regime has at least five counterbalanced matched rounds, an appropriate paired confidence interval, unchanged correctness, provenance equality and no unacceptable regression in lower bytes, read tails, CPU/RAM or GC. The current confirmation harness qualifies fast mixed QD32, fast write-only QD8 and the same-cache Kread toggle for this statistical gate; QD1/QD4/QD32 write-only remain directional controls.

## Deferred idea evidence

The benchmark keeps future optimization ideas visible without turning them into
current performance claims.

**Same-filled pages and exact-content dedup (IDs 58/59).** Trace preparation now
computes a deterministic `workload_opportunity` record from the exact fixture
bytes and logical event stream before any device I/O. It reports measured write
count, unique measured payloads, nonzero same-filled writes (one repeated
64-bit word across the 4KiB page), exact same-page rewrites, writes whose exact
payload is already resident on another logical page, and final live
unique/duplicate/same-filled populations. This is a synthetic trace/fixture
opportunity measurement only. It does not estimate kernel CPU cost, metadata
cost, lower-byte savings or real swap-workload prevalence.

**READ coalescing (ID60).** The existing same-cache Kread evidence already
records `parallel_read_pairs` and `parallel_read_same_extent_pairs` for each
sequential/random pass. Use their ratio as the first gate. An active coalescing
experiment must show fewer lower READ requests/bytes without increasing p99;
it may combine only reads already waiting for service and must not wait for a
future read to manufacture a batch.

**Background GC (ID61).** Current live-GC qualification proves correctness and
accounts lower GC I/O, but it is not evidence for a background worker. Required
pre-implementation evidence is foreground GC wall/stall contribution during
useful I/O, reserve/headroom pressure and latency/throughput impact under
bounded owned-RAM pressure. Compare useful work including all GC lower traffic.

**K>1 (ID38).** A second lower-WRITE slot is gated on sustained ready-run
pressure while K=1 is genuinely busy plus demonstrated lower-device queue
headroom. ID57 busy-PACK_READY deferrals are relevant evidence, but a counter
alone is not a win: K=2 would still require matched throughput, request/byte,
read-tail and correctness qualification.

**Physical media (ID62).** No current benchmark may collect this evidence.
Physical-device behavior/endurance remains separately authorized future work;
RAM `null_blk` results must never be relabeled as device results.

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

The qualified RAW no-bounce path copies a directly mapped incompressible page
straight to its durable `batch_bytes` slot in bulk mode; non-bulk mode keeps
one later BIO copy in `swapz_raw_write()`. The attempted scheduler-accounted
per-callback CPU metric was rejected because short preparation callbacks were
materially undercounted. Current callback counters are wall residency only.


### Qualified Step-1 evidence and ping-pong successor

Owner qualification of `c8ba1180310878141f2179a3ce0fa6d95f93f049`
passed all five stages.

Exact publication attribution shows that final-image CRC is the larger publish
subphase but not the whole cost. Slow-model publication was 21.3 ms with
12.4 ms CRC and 8.9 ms authority/liveness work; fast-model publication was
18.2 ms with 9.9 ms CRC and 8.3 ms authority. Skipping the final CRC remains
invalid. The remaining engine residual is still material at 9.2/8.2 ms and is
the next CPU-attribution split worth measuring.

The lower-WRITE queue probe refutes extra workers/credits as the immediate
standalone solution. Slow-model lower WRITE consumed about 613 ms but the mean
unclaimed preparation queue was 0.00 at both start/end, with only about 0.2 ms
of preparation-LZ4 overlap. Fast-model lower WRITE consumed 220.7 ms; queue
means were only 0.11/0.07 and overlap 6.8 ms. The synchronous ordered worker is
therefore spending substantial wall time inside lower I/O without a sustained
existing preparation backlog for another worker to drain.

The successor is an asynchronous ownership experiment, not a larger worker
count. One immutable sealed run may stream to the lower device while a separate
active collector accepts and prepares the next writes. LZ4 and payload CRC run
during collection so lower completion is followed by seal/plan/submit rather
than freeze-then-compress delay. The shared collector preserves the largest
possible global set for size-aware packing.

This is not guaranteed to improve packing merely because the device is busy.
With closed-loop QD32, one well-packed run can consume the entire outstanding
upper wave, so no new wave can arrive until completions return. The candidate
must not split a good run solely to create overlap unless measured throughput
wins without lower-byte/request or tail regression.

For one-lower-depth media, the first test uses one lower run outstanding plus a
separate collector. Multiple lower runs in flight are a later explicit K
experiment for devices/workloads that can profit from queue depth. Keep one
global planner/authority rather than sharding writes into per-lane accumulators.

Loaded GC distribution is now fully even in the synthetic pressure phase:
20 victims, 20 rotations, 20 distinct victim segments and 1/1 min/max
evictions. This removes the synthetic distribution prerequisite for a bounded
dead-segment DISCARD/TRIM experiment, but does not establish flash endurance.

Packed-read behavior reinforces the latency rule. The slow model reduced lower
requests yet produced worse packed-read p99; the fast model was close but not
qualified faster. Any read queue may reorder/coalesce only work already waiting
behind active lower I/O and must dispatch immediately when the device is idle.


The mandatory synthetic models now pin queue geometry before power-on as well
as bandwidth and completion delay. The slow profile uses blk-mq, one submission
queue and hardware queue depth 1. The fast profile uses blk-mq, one submission
queue and hardware queue depth 64. These are deliberately contrasting
serial-depth and queued-depth experiments; they are not literal protocol models
for every SD/HDD/SSD/NVMe device.
