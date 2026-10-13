# swapz V3 alpha.8 read-bypass validation

- **Status:** Independent loaded-kernel assessment; experimental feature remains opt-in.
- **Candidate:** PR #59, `68dca6fcd2b322524555becfd54d475cdaf973e1` (`feat/v3-read-bypass-diagnostics`).
- **Host:** Physical Ubuntu development machine, kernel `7.0.0-38-generic`; no reboot or physical-media benchmark was performed.

## Executive result

The loaded alpha.8 target passed the exercised successful ordering, read-after-write, barrier/FUA, suspend-drain, mixed raw/compressed readback, and rotating-GC checks. A controlled backing-data corruption made a bypassed read fail closed while buffered writes remained pending; those writes were rejected without a subsequent lower-write submission. This does not replace device-originated read-fault injection, which was unavailable.

Read bypass is observable and can enlarge windows under saturated disjoint read/write traffic. At QD8 and QD32, saturated 80/20 traffic reduced backing write requests relative to alpha.8 bypass-off, with a smaller byte reduction and increased reads. It did **not** beat the frozen loaded V2.2 write-request count. At matched 5,000 useful IOPS, the bypass counter was sparse and bypass-on did not improve lower I/O over bypass-off; alpha.8 was slightly worse than V2.2. Same-region traffic also showed no benefit. The decisive result is therefore **MIXED for the optimization, NO demonstrated V2.2 win at matched load**. Keep the feature opt-in pending further evidence; do not enable it by default or describe alpha.8 as a storage-I/O performance win.

The 1,024-page highly compressible burst reproduced 16 backing writes / 905,216 bytes in alpha.8, matching alpha.7; frozen V2.2 used 26 / 1,679,360 bytes on that burst. This is a short burst result, not evidence of sustained superiority.

## Source and binary provenance

The PR #59 head was rechecked before testing and remained the expected full SHA above. The isolated validation worktree is `/tmp/swapz-pr59-validation`; it contains report and test-tooling changes only, no production source edits. References were separately pinned to PR #57 `2e71c0c90b7f6f4ec96340583a0bc5c517bae97c` and frozen V2.2 `3a89ebbeba21c814dcf724e227b31d38445a3f9a`.

| Item | Value |
|---|---|
| `kernel/extent-v3/dm-target.c` blob | `ed1ce82e92034bb2b47dd189a7433abcc22edfcd` |
| `kernel/extent-v3/engine.c` blob | `885662604fde89f62d99a9aa211010a8be3f613b` |
| `kernel/extent-v3/authority.c` blob | `8e43663f2ba5b8eb2f0abb824db902a459385188` |
| `kernel/extent-v3/codec.c` blob | `f88d2697a5c15aa068ddd5d7853a5c38af397810` |
| `kernel/extent-v3/Makefile` blob | `be0bb1a01287069c97c6459e016d8f010bb47e74` |
| Running kernel | `7.0.0-38-generic` |
| GCC / Clang | GCC 15.2 / Clang 23.1.3 |
| fio / liblz4 | fio 3.41 / liblz4 1.10.0 |
| V3 module name / target | `dm_swapz` / `swapz3` |
| V3 `srcversion` | `BC8065C2CA507B0C1113ECF` |
| W=1 module SHA-256 | `2dfc2b809ac1c8ecc9e48340a2cb25af6eff3a957abf74d8287c9667acc574eb` |
| W=2 module SHA-256 | `a8cba8e1d7ffe84f91cf125fea5441885cc3d71c2e08e0bf1a3de4d11155332e` |
| Module vermagic | `7.0.0-38-generic SMP preempt mod_unload modversions` |

W=1 and W=2 production builds succeeded against the running kernel headers. No production C warnings were observed. Kbuild reported that the host compiler and pahole versions differ from those used for the kernel, and BTF generation was skipped because the matching `vmlinux` was unavailable. These are environment/BTF notices, not source warnings. The loaded trials used the W=1 module above. The binary hashes and complete logs are in the evidence bundle.

## Test device and accounting method

The only test backing device was a newly created configfs instance `nullb_swapz_pr59_68dca6f`, `/dev/nullb_swapz_pr59_68dca6f`, major:minor `251:0`, 40 MiB, `memory_backed=1`, 512-byte logical blocks, queue mode 2, depth 64, one submit queue, 20 MiB/s throttle and 500,000 ns completion delay. Each target had a unique `SWZ59Q-*` UUID, was mapped only to major:minor `251:0`, and was removed normally before the next incompatible module build/load. The pre-existing `null_blk` module was not unloaded.

Independent `/sys/block/nullb_swapz_pr59_68dca6f/stat` deltas are reported as actual requests and 512-byte-sector-derived bytes. Verification reads are outside measured intervals. All timed operations used the direct-I/O helper with deterministic fixtures, fresh targets, a 10-second warmup, 30-second measurement, then full 4,096-page byte-exact verification. Matched tests completed the same 150,000 useful operations (at 5,000 IOPS) per run. “CPU” from the helper is process CPU only; it is not kernel worker CPU.

## Rootless, build, and source review

The rootless harness recorded **95 commands, 0 failures**, covering GCC ASan/UBSan exact-production-C tests, GCC/Clang optimized variants, source contracts, seeded randomized engine checks, GC/authority and teardown tests. Exact command and per-command exit status are included in the bundle. The three referenced upstream CI workflows were already green at the pinned commit; those CI results are not counted as loaded proof.

The read bypass predicate in `sv3_read_can_bypass_window()` is disabled by default and applies only to an exact one-page plain READ when a write window is nonempty and no pending BIO targets that page. Same-page reads increment the conflict-flush counter and take the normal drain path. PREFLUSH/FUA, discard, unsupported operations and suspend drain remain ordered through the serialized worker. The `sv3_flush_window()` failed-target branch completes owned buffered writes with the latched error and clears them without staging/submitting them. This is consistent with the loaded outcomes below. No credible source-level corruption or ownership defect was found in the reviewed path.

## Loaded correctness matrix

| Area | Result | Evidence / limit |
|---|---|---|
| Default-off alpha.8 burst | PASS | `read_bypassed=0`; all 1,024 pages verified; performance below. |
| Disjoint read with buffered writes | PASS | Bypass-on read completed against prior committed generation before queued writes; bypass counter advanced. Bypass-off drained first. |
| Same-page read-after-write | PASS | Compressed/compressed, raw/raw, compressed/raw and raw/compressed overwrite cases returned latest bytes; conflict flush counted. |
| Duplicate logical writes | PASS | Latest representation and generation read back exactly. |
| PREFLUSH/FUA | PASS for exercised protocol | Valid zero-sector `WRITE|PREFLUSH` plus raw/compressed 4 KiB FUA; `flush_calls=4`, `flush_ok=4`, errors 0. Cacheless null_blk reported zero physical flush requests. |
| Discard / rewrite | PASS | Pending-page, unrelated and shared-extent discard/rewrite cases verified. |
| 1,024-BIO drain/suspend/resume | PASS | coalesce 4 ms, bypass on; exactly 1,024 completions, no errors, complete readback. |
| Bypassed read failure with pending writes | PARTIAL PASS / DEVICE FAULT BLOCKED | Owned backing data corruption caused checksum/read failure; target failed closed and buffered writes were not submitted afterward. This is not a device-originated read error. No isolated safe read-error injector was available. |
| Rotating GC | PASS for control | Nine role rotations, foreground writes progressed, complete 8,192-page image verified before/after. |
| GC write fault | PASS for synthetic pre-submit EIO | `test_fail_write_nth=9217`; first five rotations remained committed; no sixth rotation; target failed closed; no post-failure read. This is not a torn/device-originated write. |
| Full-destination/no-headroom | PASS fail-closed behavior | 8,192 pages accepted; subsequent overwrite returned `ENOSPC`; 31 no-headroom candidates skipped; zero GC read/write or rotations; normal teardown. |
| Device-originated lower read/write fault | BLOCKED | Only target-local synthetic pre-`dm_io` write EIO and deterministic data corruption were available. |
| Device-originated lower flush failure | BLOCKED | No isolated null_blk lower-flush error injection. |

The 3,535-byte full-destination negative control avoided the former expensive futile relocation: target and backing counters showed zero GC read/write. It is expected capacity exhaustion, not a successful reclaim result. An initial test-table size was rejected by constructor reserve checks before I/O; this harness sizing correction is recorded and was not a production failure.

Harness corrections are preserved in the evidence: a trial-summary helper initially divided by zero because V2.2 exposes no V3 window histogram; it was corrected to report that metric as unavailable, then rerun across the combined 18 primary trial records. The first full-destination attempt used an invalid target size rejected before I/O, and its cleanup wrapper initially compared `dm-0` with the friendly target name and refused removal; the exact UUID was then removed normally and the ownership check was corrected before the final passing run. No forced removal was used.

## Burst reproduction

The historical 4 MiB input image is `41426178c19fc6f64d7b23439ac02b3c9ca36231c8123371236e6b351952b5d8`; it has 819 highly compressible pages (about 56-byte LZ4 output) and 205 incompressible/raw pages. The complete 4 MiB logical image was read back byte-for-byte. Median of independent runs:

| Candidate | n | Backing write requests | Backing write bytes | Verified useful pages |
|---|---:|---:|---:|---:|
| Frozen V2.2 | 5 | 26 | 1,679,360 | 1,024/1,024 |
| PR #57 alpha.7 / bulk=1 | 5 | 16 | 905,216 | 1,024/1,024 |
| Alpha.8 bypass off / bulk=1 | 6 | 16 | 905,216 | 1,024/1,024 |
| Alpha.8 bypass on / bulk=1 | 5 | 16 | 905,216 | 1,024/1,024 |

This burst validates no default-off regression and the prior alpha.7 burst packing result. It does not estimate sustained swap behavior.

The default-off comparison also retained the alpha.7 sustained behavior within trial variation: on matched 80/20 QD8, PR #57 median was 119,487 write requests / 490,143,744 bytes and alpha.8-off was 119,508 / 490,172,416; both stayed at about 1.002 records/window and `read_bypassed=0`. Alpha.8-off therefore shows no material change when the feature is disabled.

## Sustained performance: 80/20 mixed LZ4/raw fixture

The matrix used a fixed matched seed, disjoint logical read/write ranges for the disjoint workload, and identical 150,000 operations per matched run. Values below are medians; primary QD8 5,000 IOPS comparisons use five repeats for V2.2, alpha.8-off, and alpha.8-on; PR #57 has three reference repeats. QD4 at 1,500 IOPS uses five repeats, while 70/30, 50/50, same-region, and size-class groups use three. Per-trial values, latency quantiles, and corresponding sample counts are archived.

### Matched rates

| Comparison (QD8, 5,000 IOPS, 80/20) | Useful ops/run | Lower W req | Lower W MiB | Lower R req | Lower R MiB | Avg records/window | Bypassed reads | W p99 / R p99 (µs) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| V2.2 | 150,000 | 118,782 | 466.00 | 30,500 | 119.14 | n/a | n/a | 291.6 / 246.2 |
| PR #57 | 150,000 | 119,487 | 467.44 | 30,659 | 119.76 | 1.0024 | 0 | 217.4 / 151.9 |
| Alpha.8 bypass off | 150,000 | 119,438 | 467.33 | 30,658 | 119.76 | 1.0028 | 0 | 228.9 / 155.4 |
| Alpha.8 bypass on | 150,000 | 119,512 | 467.47 | 30,657 | 119.75 | 1.0023 | 65 | 211.5 / 147.1 |

At this matched point alpha.8 bypass-on produced **74 more** lower write requests than bypass-off and 730 more than V2.2 (about +0.61%); bytes were +0.03% versus off and +0.31% versus V2.2. Read request/byte deltas were nearly unchanged. The measured bypass count was nonzero but sparse and did not improve window occupancy or request count. All three five-run candidates completed 150,000 useful operations in every trial; backing write-request ranges were 118,601–118,938 (V2.2), 119,415–119,526 (off), and 119,423–119,540 (on).

For V2.2 versus alpha.8-on, measured read+write bytes were 613,593,088 versus 615,772,160 (+0.36%); combined read+write requests were 149,282 versus 150,169 (+0.59%). The byte overhead is small but in the wrong direction for the stated lower-I/O objective.

Each run included 119,605 write and 30,395 read latency samples. Median across trial quantiles (microseconds) was: V2.2 write p50/p95/p99 `118.3/228.6/291.6`, read `89.9/170.0/246.2`; alpha.8-off write `108.4/152.6/228.9`, read `92.9/114.2/155.4`; alpha.8-on write `108.6/152.6/211.5`, read `93.2/114.3/147.1`. These are measured upper request completion latencies on this null_blk profile; they do not offset the slightly higher V3 lower I/O. Median helper process CPU was 9.70 s (V2.2), 10.03 s (off), and 10.18 s (on) in each 30-second trial; kernel workqueue CPU was not separately attributed.

At QD4 / 1,500 IOPS, five repeats completed 45,000 operations each (35,908 writes, 9,092 reads). Both alpha.8 modes and PR #57 had 35,977 backing write requests / 140.54 MiB, versus V2.2 at 35,909 / 140.28 MiB. Bypass count was zero. Alpha.8 bypass therefore showed no matched-QD4 benefit.

At matched QD8 / 5,000 IOPS for 70/30, V2.2 used 103,688 write requests / 406.72 MiB, alpha.8 off 104,298 / 407.89 MiB, and alpha.8 on 104,318 / 407.99 MiB (median bypass count 97). For 50/50, V2.2 used 73,250 / 289.23 MiB, alpha.8 off 74,256 / 290.94 MiB, and alpha.8 on 74,283 / 291.04 MiB (median bypass count 324). Same-region 80/20 likewise had no bypass-on advantage: 119,518 write requests / 467.55 MiB versus off 119,482 / 467.48 MiB and V2.2 118,769 / 465.97 MiB. Alpha.8 remains slightly behind V2.2 in lower write traffic across these matched tests.

### Saturation, 80/20, three repeats

The QD1/4/8/32 direct-I/O helper saturated each target independently, so operation totals differ by achieved throughput; this table is not an equal-work comparison. Median backing write requests / bytes (MiB), measured useful IOPS, and lower read MiB:

| QD | V2.2 | Alpha.8 bypass off | Alpha.8 bypass on | Bypass vs off |
|---:|---|---|---|---|
| 1 | 122,049 / 476.75; 5,102 IOPS; R 121.62 | 121,879 / 476.09; 5,088; R 121.98 | 121,947 / 476.36; 5,091; R 122.04 | no bypasses, singleton windows |
| 4 | 54,863 / 448.85; 6,138; R 145.81 | 86,414 / 458.29; 5,822; R 138.65 | 83,491 / 456.78; 5,876; R 139.93 | write req −3.4%, bytes −0.3%, avg window 1.61→1.69 |
| 8 | 26,053 / 437.16; 6,373; R 151.27 | 58,924 / 439.96; 6,536; R 155.18 | 47,476 / 432.51; 6,822; R 161.92 | write req −19.4%, bytes −1.7%, avg window 2.69→3.50 |
| 32 | 7,328 / 420.92; 6,415; R 152.30 | 41,062 / 426.06; 6,994; R 166.16 | 16,674 / 404.19; 7,555; R 179.42 | write req −59.4%, bytes −5.1%, avg window 4.32→15.60 |

At saturation bypass-on lowered V3 write requests versus bypass-off at QD4/8/32, and delivered more operations/s in these runs, but still used 52%, 82%, and 128% more lower write requests than V2.2 respectively. Normalizing by successfully completed logical writes, V3-on used about 0.594/0.291/0.092 backing write requests per logical write at QD4/8/32, versus V2.2 at 0.373/0.171/0.048. At QD8 and QD32, V3-on did transfer fewer write bytes per useful write (about 2,777 vs 3,003 bytes and 2,345 vs 2,875 bytes), but its read-byte traffic increased and its write-request rate remained much higher. Total read+write bytes were about 1.0% higher at QD8 and 1.8% higher at QD32. QD1 was effectively tied; QD4 remained worse on writes. Saturation latencies were in the multi-millisecond range at QD4+, and should not be compared with fixed-rate latencies as if equal load.

### Size-class matrix

Each of the following groups completed three matched QD8, 5,000 IOPS, 80/20 repetitions per candidate: 119,605 writes and 30,395 reads per run; all 4,096 logical pages verified. The archived LZ4 fixtures measured exactly 1,031, 2,088 and 3,499 output bytes with `LZ4_compress_fast(4096,3568,1)`; the raw fixture did not compress and used 4,096-byte raw pages. Results are medians; lower write requests / MiB, lower read requests / MiB, average records/window, bypass count, and write/read p99 µs:

| Input page class | V2.2 | Alpha.8 bypass off | Alpha.8 bypass on |
|---|---|---|---|
| 1,031-byte LZ4 | 118,816 / 464.25; R 30,496 / 119.12; n/a; 0; 284.7 / 232.2 | 119,524 / 466.91; R 30,655 / 119.75; 1.0021; 0; 178.1 / 138.0 | 119,549 / 466.99; R 30,653 / 119.74; 1.0017; 61; 172.0 / 136.7 |
| 2,088-byte LZ4 | 118,912 / 467.29; R 30,500 / 119.14; n/a; 0; 281.3 / 230.4 | 119,559 / 467.89; R 30,669 / 119.80; 1.0020; 0; 180.0 / 141.6 | 119,573 / 467.89; R 30,672 / 119.81; 1.0019; 58; 175.0 / 138.2 |
| 3,499-byte LZ4 | 118,805 / 467.29; R 30,500 / 119.14; n/a; 0; 288.3 / 237.6 | 119,496 / 467.94; R 30,667 / 119.79; 1.0025; 0; 201.4 / 157.3 | 119,487 / 467.94; R 30,667 / 119.79; 1.0026; 72; 194.9 / 149.7 |
| Raw 4,096-byte | 118,819 / 467.29; R 30,500 / 119.14; n/a; 0; 290.2 / 242.8 | 119,428 / 467.94; R 30,667 / 119.79; 1.0031; 0; 285.6 / 167.6 | 119,400 / 467.94; R 30,667 / 119.79; 1.0033; 88; 280.9 / 157.2 |

The tuples are `write requests / write MiB; read requests / read MiB; average records/window; read_bypassed; write p99 / read p99`. Bypass activity was measurable but sparse (58–88 calls in 150,000 operations) and did not produce a request reduction against bypass-off in three of four classes. Even where alpha.8-on used 9 fewer requests for 3,499-byte records or 28 fewer for raw input, V2.2 still used roughly 0.5% fewer write requests and less or equal write bytes. This provides no matched-rate V3 lower-I/O win for these isolated size classes.

## Accounting, CPU, and kernel diagnostics

For the primary rate-controlled matrices, the independent lower-device sector/request deltas reconciled with V3 `physical_read[_reqs]` / `physical_write[_reqs]` and bytes. A programmatic audit passed **149 trial records**, including saturation, the five-run matched QD8 group, the additional 70/30/50/50/same-region cases and all four uniform size-class groups. It checked complete verification, target health, read/write request and byte counters, and that window histogram bins sum to `windows` with `one_page_windows == win1`. Flushes on the cacheless null_blk did not show as block-stat flush requests.

The PR #58 +1 backing-write-request anomaly was traced narrowly on the exact owned device. The normal recorded burst traced `block_bio_queue` and backing request issue counts consistently. In a bounded 3,535-byte full-destination run, target `physical_write_reqs=462` and sysfs write requests=464 with identical 32 MiB bytes. Trace showed 462 bios and 464 requests, no zero-byte writes, reads or flushes; two 256-sector bios were split into (255-sector, 1-sector) requests at offsets 0 and 296 sectors. This proves request splitting can explain a two-request delta for that run. It does not prove the exact cause of each earlier PR #58 +1 trial, which was not traced at the time; target counters count `dm_io()`/extent operations rather than a guaranteed one-to-one backing request count. Use independent backing stats for the performance conclusion.

Kernel worker CPU was not reliably attributable in this pass and is **UNMEASURED**. The helpers recorded their own process CPU and peak RSS in each trial; these are not total kernel CPU. At matched 80/20 QD8, median helper CPU was 10.18 s per 30 s trial (bypass off) and 10.19 s (on), versus 9.70 s for V2.2; peak helper RSS was about 26.1 MiB for all three. The small helper CPU difference is not a substitute for workqueue CPU accounting. `dm_swapz` module static `coresize` was 61,440 bytes, not a measure of per-target mappings, buffers, or worker stack allocation. Do not infer total kernel memory cost from it.

Three `Buffer I/O error on dev dm-0, logical block 0, async page read` messages followed fail-closed tests. Exact DM identity and time are preserved. For full-destination failures the helper log reports no reads after target failure and target/lower counters show no post-failure reads; a device-scoped trace showed no backing reads. This locates the error at the upper DM device path but does not identify who issued the asynchronous buffer read. It remains unexplained; it was not evidence by itself of logical data corruption and is not dismissed.

## Limits and verdicts

| Qualification | Verdict |
|---|---|
| Exact-source build / W=1, W=2 | PASS |
| Rootless tests and source contracts | PASS (95 commands, 0 failures) |
| Source ordering review | PASS for reviewed bypass/worker/drain path |
| Loaded read-bypass ordering | PASS for exercised disjoint/same-page cases |
| Bypassed-read pending-write fail-closed branch | PARTIAL PASS; real read-error injection BLOCKED |
| Flush/FUA/discard/suspend successful paths | PASS for the exercised test helpers and null_blk behavior |
| Device-originated I/O/flush errors | BLOCKED |
| GC readback and synthetic write fault | PASS for exercised cases |
| 1,024-page burst | PASS; alpha.8 matches alpha.7, better than V2.2 on this highly compressible burst |
| Saturated disjoint read-bypass request reduction vs V3 off | BETTER at QD4/8/32; no change QD1 |
| Matched-rate read-bypass improvement vs V3 off | NO; INCONCLUSIVE-to-WORSE by workload (slightly more writes/bytes in tested groups) |
| Matched loaded V3 vs V2.2 sustained I/O | WORSE for lower write bytes/requests in tested matched groups; latency often lower for V3 but not a total I/O win |
| Physical SD/SSD/HDD benefit | NOT TESTED / NOT AUTHORIZED |
| Production readiness | NOT ESTABLISHED |

**Recommendation:** retain read bypass only as an opt-in experiment. It is causally useful at high queue depth under disjoint reads, but matched 5,000 IOPS runs had too few bypass events to improve packing and remained slightly worse than V2.2 on writes. Next work should target sustained same-worker write-window formation and extent/run geometry under rate-controlled arrivals, while measuring p99 and reads; do not make the bypass feature default based on saturated request counts. The existing async Buffer I/O source and kernel-worker CPU attribution remain open validation items.

## Evidence bundle and reproducibility

The adjacent compressed archive contains raw command JSON, per-trial outputs, latency distributions, backing-device counters, status snapshots, fixtures and hashes, rootless logs, W=1/W=2 logs, module `modinfo`/hashes, source inventory, GC/full-destination/fault records, device-scoped block traces, and cleanup evidence. The evidence index and SHA-256 manifest are published alongside this report. Test scripts are included under `reports/alpha8/scripts/` and helpers under `reports/alpha8/helpers/`; they alter no production source or runner.

## Cleanup and host protection

No physical device was used. `/dev/sdb1` and `/swapfile` remained active; no `swapoff`, `swapon`, reboot, or modification of either was performed. Their active-swap entries remained present before and after testing (the live `Used` values changed with normal system activity). Only the test-owned null_blk and UUID-owned DM tables were used. After the last run, the owned DM mappings were absent, the `dm_swapz` module was unloaded with zero references, and the uniquely named null_blk instance was powered off and removed. Final inventory and cleanup command output are in `data/final-host-inventory.json` and `data/cleanup.log`; the pre-cleanup inventory and protected-state hashes are preserved separately.
