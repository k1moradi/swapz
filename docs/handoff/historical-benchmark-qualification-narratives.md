# Historical benchmark qualification narratives

These three sections are reproduced verbatim from
[`docs/benchmark.md`](../benchmark.md) at source commit
[`9bfbca018dd639cce7abf5f9b625bb4cfdc6ae78`](https://github.com/k1moradi/swapz/commit/9bfbca018dd639cce7abf5f9b625bb4cfdc6ae78).
Their source SHAs, PASS/FAIL/BLOCKED evidence where present, measurements,
confidence intervals, caveats and unresolved decisions belong to those historical
runs. Present-tense statements below describe that historical source, **not**
current `main`, physical-media acceptance or present release readiness.
Use the active [benchmark standard](../benchmark.md) and
[qualification contract](../testing_standards.md) for current policy.

### Production delta64 attribution and Core-2 cache baseline

The earlier report `1df2e5a6d7c52682c2ac048310b0ed2f932a2791` tested source
`5bdd040334ee0739e1663e98eef4c875a1c4629a` and passed all five stages
on owned RAM-backed `null_blk`. Production delta64 telemetry is decisive for
this workload: every mixed arm observed 12,301 eligible pages but zero
classifier passes, attempts or adoptions, with zero encoded payload bytes
saved. Delta64 therefore changed neither extent packing nor lower I/O in this
loaded run. The native structured corpus remains separate opportunity evidence:
threshold 24 models 257 -> 205 physical blocks and 182 -> 133 extents.

The same report is the pre-change Core-2 cache baseline. Fast packed reads show
sequential lower READ 2830 KiB / 308.2 requests / 5.54 ms p99 and seeded-random
2493 KiB / 623.2 requests / 5.63 ms p99. Read-engine wall time excluding lower
I/O is 6.0 ms sequential and 9.4 ms random. These are the comparison points for
the subsequent 128-set x four-way metadata directory and block-zero copy-avoidance
round; host-load and lower-I/O caveats still apply.

Successor reports add metadata set lookup/hit/probe/replacement counters and
cached-block payload-copy bytes. A source-level reduction in probes or memcpy
traffic is not itself a performance claim: retain lower bytes/requests, useful
throughput, p99, read-engine attribution and host-load evidence in the verdict.

The Core-2/delta64 packing successor keeps that owner baseline and changes two
measured mechanisms together. Metadata directory tags become 16-byte entries in
aligned 64-byte four-way sets, with epoch invalidation instead of clearing 512
valid bytes on normal mutations. Delta64 keeps threshold 24 for RAW/>2024-byte
rescue, while <=2024-byte LZ4 pages may use threshold 16 only when the engine can
name a lower 4/8/16KiB SWZ packing cliff; adoption on that path requires crossing
the cliff. Production status additionally reports pack eligible/attempt/cliff/
adopted counts and score bands 0-7, 8-15, 16-23 and 24+.

Report `6f5c6e56e6d8` qualified source `9a802eff7d9d` with rescue off.
Its fast random reads use 3592 KiB and 734.6 lower requests, with 71.2%
directory hits and 309.4 replacements. Source inspection confirms that sibling
reads can duplicate a metadata key across ways; this is a defect before any
remaining distinct-key conflict question. Alpha.26 deduplicates commit, drains
late producer work before suspend invariants, and aligns preparation elements.
Report `85aeac4cbb36` then qualified this repair at source `5bf2c0a6f038`.
Keep the mixed read-bypass async gate and classifier policy fixed
for attribution. PACK_READY service-dry counts alone do not establish how many
windows that gate excluded, and a rounded 0.00 run-slot mean is not zero usage.
Consider a separate same-source gate A/B after this repair is qualified.

Alpha.27 is a separate, externally reviewed metadata-cache experiment. Each
key may reside in either of two distinct four-way sets within the same
512-slot store. Primary hits keep a one-line lookup; secondary hits and misses
inspect at most eight tags. Replacement uses an invalid candidate before the
oldest of the two sets, after checking both for an existing key. New primary
and secondary hit counters must sum to total directory hits, and the console
prints their percentages with the common lookup denominator.

The current qualified comparison is fast random 2993 KiB / 678 requests and
about 6.6 ms engine non-I/O wall time. The older 2493 KiB / 623.2-request
result is a historical target, not an acceptance oracle: write placement and
host load differ between reports. Acceptance requires fewer lower READ bytes
and requests with exact data and preserved useful throughput/read tails, while
retaining most of the engine-time advantage and inspecting CPU/PSI context.
Secondary hits alone do not prove saved I/O. This experiment is uncompiled and
untested locally and does not implement Step 3 asynchronous TRIM.

Rootless planner acceptance includes a deliberately one-byte boundary: nine
1803-byte records require five physical 4KiB blocks in five one-block extents under the existing
lower-read tie-break, while nine 1802-byte records fit in one 16KiB extent. The owner run must still demonstrate
whether real windows see that opportunity and whether lower WRITE bytes/requests
fall; cliff crossings alone are not a physical-I/O claim.


## Current directional result

On the latest qualified source, fast sequential adjacent-range READ coalescing
reduced lower requests 17.53% (paired 95% CI [-19.71%,-15.35%]) and p99
5.43% ([-9.70%,-1.16%]); useful throughput moved +8.48%
([-2.78%,+19.74%]) and therefore remains statistically unresolved. Fast seeded
random changes in requests, p99 and throughput all overlap zero.

On the serial-depth model, sequential requests fell 20.75%
([-23.32%,-18.19%]), p99 fell 12.24% ([-21.69%,-2.78%]), and useful
throughput rose 16.61% ([+13.78%,+19.43%]). All three intervals exclude zero.
Cap evidence subsequently fixed the production coalesced span at eight blocks;
the runtime cap selector is retired.

Loaded packed placement retained zero internal holes and zero hole-induced run
splits; live GC exercised 20 victims/rotations and verified 4096 pages. The
separate low-RAM/heavy-CPU release gate remains open. Next collect that
resource-pressure evidence and realistic churn/GC/TRIM before deciding on
asynchronous TRIM. Physical media, real swap semantics and endurance remain
unqualified.


## Alpha.29 work-conserving dispatcher benchmark

ID83 adds no public command or benchmark-only selector. The ordinary `make test`
storage envelopes remain the decision surface, and the SIMD qualification
matrix remains unchanged: SSE2/AVX2/AVX-512 objects on x86_64, NEON on arm64,
with runtime execution only when the host advertises the ISA.

Owner report `5f867aa81fce` qualifies exact source `5edcb2981573` across all
five stages. The short-window/service-dry refinement fixes the specific request
geometry path identified in `b4bc5e0ba965`: fast mixed async IDLE closes fall
681.6 -> 0.6, `prep_ordered_raw` falls 2751.6 -> 1001.6, lower WRITE bytes
40.68 -> 38.13 MB, and lower WRITE requests 2678.8 -> 2444.4. Explicit
PACK_READY cause accounting now reports only 25.4 BURST_TARGET closes and
1129.2 SERVICE_DRY closes.

Fast sustained scaling also improves. QD4 async-minus-sync throughput moves from
-28.1% (95% CI -37.4..-18.7) to -6.55% (-12.45..-0.65); its lower-request
change is now unresolved at +17.1% (-6.17..+40.44). QD8 is +4.22%
(-3.95..+12.39) and QD32 +1.77% (-4.83..+8.37), both statistically neutral.
The two-record ping-pong diagnosis is therefore confirmed, but QD4 is not yet
fully recovered.

The geometry gain does not translate into a fast-mixed service promotion.
Same-source fast mixed async is 37.22 MB/s versus 37.86 sync, or -1.68%
(95% CI -4.75..+1.39), while lower requests remain +30.0%
(+27.3..+32.8) and lower bytes remain about +5.3% versus sync. The previous
`b4bc5e0` report had a confirmed +13.9% async/sync service gain. Cross-report
raw throughput is nearly unchanged (62.88 -> 62.39 MB/s), so the large async
drop is unlikely to be explained solely by host-speed variation, although
cross-report scheduler/CPU attribution remains non-comparable by policy.

The new idle attribution makes the remaining cause concrete. Fast mixed async
records 679.41 ms accepted lower-idle wall: 621.35 ms undersized-batch retention,
54.71 ms worker-unscheduled, 0 ms preparation-head wait and 3.35 ms remaining
active no-ready work. The separate post-lower diagnostic is 17.29 ms. K=1 ready
wait remains zero. The next experiment therefore targets undersized retention,
not more preparation or lower-WRITE concurrency.

A bounded next policy is to preserve retention for 1..3 records but permit a
proven-dry retained window with at least one complete four-record SWZ pack to
close as SERVICE_DRY below a larger learned target. Four records is an existing
format/packing boundary rather than a new timing heuristic. Accept it only if a
new owner `make test` recovers fast mixed useful service, removes the remaining
significant QD4 deficit, preserves the current request/byte improvement, and
keeps QD8/QD32 plus slow/SD evidence non-regressing.


