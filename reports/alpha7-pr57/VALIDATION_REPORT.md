# Independent PR #57 loaded-kernel validation

**Candidate:** PR #57, `2e71c0c90b7f6f4ec96340583a0bc5c517bae97c`<br>
**Validation branch:** `codex/pr57-write-fault-sustained-validation`<br>
**Host:** `Inspiron1564Linux`, Ubuntu 26.04.1, kernel `7.0.0-38-generic`<br>
**Overall verdict:** **MIXED performance; loaded synthetic fault behavior PASS; not a production qualification.**

## Executive result

The loaded PR #57 write-fault injector behaved fail-closed in all 18 tested combinations: `lower_bulk=0/1/2`, compressed/raw/mixed writes, and injected failure on lower-write attempt 1 or 2. Rejected attempts were injected before `dm_io`, did not increment the submitted/completed write counters, produced upper `-EIO`, and the owned mapping was ordinarily removed. A nine-rotation GC control retained and verified all 8,192 logical pages. A synthetic failure on lower-write attempt 9,217 occurred after five completed rotations; no sixth role rotation was reported and the target was normally torn down. These are loaded tests of PR #57, but the injector is **not** a device-originated partial/torn-write model.

The frozen 1,024-page burst remains reproducible: PR #57 bulk=1/2 produced 16 lower write requests and 905,216 bytes versus V2.2's 26 requests and 1,679,360 bytes. That is a real loaded `null_blk` result for an exceptionally compressible 4 MiB input, not representative sustained evidence.

The sustained evidence does **not** establish a general V3 lower-I/O win over V2.2. At matched 1,500 IOPS, PR #57 used slightly more lower write bytes and requests. At saturating mixed load, bulk=1 reduced requests substantially relative to alpha.6/alpha.7 and its own bulk=0 control at QD4–QD32, but still used 56% to 458% more lower write requests than V2.2. Absolute lower write bytes were near or above V2.2; at QD8/QD32, bytes per useful write improved under the higher V3 saturation rate, while request cost, helper CPU, and read traffic increased. QD1 remained effectively singleton and showed no bulk request reduction.

The result supports continuing the experiment, but it does not justify calling the performance objective achieved or selecting V3 over V2.2. The dominant limitation is request amplification in the production V3 path, followed by GC overhead at low queue depth. Physical-media effects were not tested.

## Source, build, and host provenance

PR #57's branch and pull-request head both resolved to the requested SHA at initial verification and at recheck; no production source was modified during validation.

| Source file | Git blob |
|---|---|
| `kernel/extent-v3/dm-target.c` | `ec276739766f028899ac7bd7ad57edac09c65825` |
| `kernel/extent-v3/engine.c` | `885662604fde89f62d99a9aa211010a8be3f613b` |
| `kernel/extent-v3/authority.c` | `8e43663f2ba5b8eb2f0abb824db902a459385188` |
| `kernel/extent-v3/codec.c` | `f88d2697a5c15aa068ddd5d7853a5c38af397810` |
| `kernel/extent-v3/Makefile` | `be0bb1a01287069c97c6459e016d8f010bb47e74` |

Environment: GCC 15.2.0, Clang 23.1.3, fio 3.41, liblz4 1.10.0, matching headers for `7.0.0-38-generic`. W=1 and W=2 production builds succeeded. The exact PR #57 loaded module was `dm-swapz.ko`, module name `dm_swapz`, target `swapz3`, SHA-256 `b4bf0082b63d5d32162888afced7595547544706656fe9284f26982bd26ac3c8`, srcversion `78ABB0DD15F1176829FFE0D`; vermagic matched the running kernel. Comparator modules were loaded sequentially. Build logs, vermagic records, hashes, compiler matrix, and raw test logs are in the evidence archive.

The disposable backing was the uniquely configured memory-backed `null_blk` instance `nullb_swapz_pr57_2e71c0c9`, `/dev/nullb_swapz_pr57_2e71c0c9`, major:minor `251:0`, 40 MiB, 512-byte logical blocks, 20 MiB/s limit, 500,000 ns completion delay, queue mode 2, hardware queue depth 64, one submit queue. Every DM target used a trial-specific name and UUID. It had no unrelated holders, mounts, or swap ownership. No physical device was used.

### Rootless qualification

The task's exact-production-C suites passed under GCC sanitizer builds and Clang O0/O2. Counts included codec 8, authority 10, immutable snapshots 4, verify-after-write 7, dead-segment reuse 4, raw/discard authority 7, exact engine 9, GC-forbidden 3, GC cost 6, flush accounting 4, rotating GC 6, GC engine rotation 2, and bulk-I/O 24. The seeded randomized engine oracle passed 400 windows and 13,279 generated records across read caps 0–3, plus duplicate/failure cases (`seed=0x0d3a5eed`). The 24 PR #57 production-source contracts passed. Rootless teardown/ownership regressions passed. CI at the exact requested head was independently checked against the three supplied successful workflows.

No production source fix was needed. Test-side corrections were limited to selecting the proper V2.2 target keyword in an initial invalid table attempt, waiting for open references to reach zero before normal teardown, making the negative helper expect EIO, and removing a result-directory collision. Their original failures are retained; they were not counted as production passes.

## Loaded lower-write fault qualification

The ninth positional argument was exercised as `test_fail_write_nth=0/1/2` with separate fresh mappings. The 18-case matrix covers:

| `lower_bulk` | Format | Injected attempt |
|---:|---|---:|
| 0, 1, 2 | compressed, raw, mixed | 1 and 2 |

All 18 intended negative cases returned `PASS-OBSERVED-AND-CLEANED`. `write_fault_calls` reached the selected Nth attempt, `write_fault_injected=1`, and the target ended with `failed=1,error=-5`. Each submitted helper BIO had one captured completion; no read was sent through a target after it failed. The injected attempt did not count as a target `dm_io` submission or completion, and no lower write attributable to the rejected attempt appeared in independent backing statistics. Ordinary teardown removed each exact owned UUID.

For Nth=2, earlier successful groups were preserved as completed/published prefix only where actual window/run boundaries showed they had completed before the injected write. The injector's Nth physical-write attempt is not assumed to equal the Nth logical page. Rejected writes did not become authoritative; previous authority and prefix semantics are separately covered by exact-C tests. A failed production target was not read to infer data preservation.

**Limits:** This injector rejects before `dm_io`. It does not test device-originated I/O errors, short completions, torn sectors, or partially written media. Exact-C mock tests cover short/partial completion and transaction authority, but loaded device-originated failure remains BLOCKED because no isolated per-instance null_blk write-fault mechanism was available. The prior loaded GC write failure was also synthetic pre-submission EIO.

## Injection-disabled burst control

The frozen PR #56 fixture hash is `41426178c19fc6f64d7b23439ac02b3c9ca36231c8123371236e6b351952b5d8`. It is 1,024 pages / 4 MiB useful data: 819 compressed pages and 205 raw pages. Reinspection of the actual generated bytes found 56-byte user-space LZ4 outputs for the compressed population (the historical fixture was described as approximately 57 B). All valid repetitions had exact 1,024/1,024 readback. With the injector disabled, `write_fault_calls=0` and `write_fault_injected=0`.

| Driver / mode | Lower write requests | Lower write bytes | Verified pages |
|---|---:|---:|---:|
| Frozen V2.2 | 26 | 1,679,360 | 1,024/1,024 |
| Alpha.6, bulk=1 | 419 | 1,716,224 | 1,024/1,024 |
| Alpha.7, bulk=1 | 16 | 905,216 | 1,024/1,024 |
| PR #57, bulk=0 | 419 | 1,716,224 | 1,024/1,024 |
| PR #57, bulk=1 | 16 | 905,216 | 1,024/1,024 |
| PR #57, bulk=2 | 16 | 905,216 | 1,024/1,024 |

Five successful repetitions were retained per configuration. PR #57 bulk=1/2 matches alpha.7 exactly on this burst; the disabled injector did not regress this behavior. Bulk=2 provides no burst benefit over bulk=1.

## Fixture and sustained method

The independently generated fixed-seed fixture uses actual `LZ4_compress_fast()` outputs, acceleration 1, 4,096-byte inputs and the project's 3,568-byte maximum compressed size. Seed: `0x57A7C0DE`. Fixture SHA-256: `823c37ebb366a7c2e453a70faed8d99dc2f90114185f18ceeafdffe9a0029d25`.

| Input class | Page count | Measured user-space LZ4 output |
|---|---:|---:|
| Very compressible | 205 | 56 B each |
| Dense | 205 | 1,031 B each |
| Medium | 205 | 2,088 B each |
| Large | 204 | 3,499 B each |
| Raw/incompressible | 205 | 4,096 B raw |

This is 80% compressed / 20% raw. The mixed fixture was byte-identical across comparator runs. Separate uniform class fixtures were also used for the 1,031, 2,088, 3,499, and raw cases. The target exposes compressed/raw counts but not an exact per-page kernel compressed-length histogram; the lengths above are the verified input fixture's userspace LZ4 lengths, not claimed kernel output counters.

The sustained helper issued aligned direct 4 KiB I/O against 4,096 logical pages (writer region pages 0–1,023; disjoint cold reader region 2,048–3,071), with a per-page latest-write oracle, random overwrite order, 10-second warmup, 30-second measurement, 20% reader offer for the primary queue-depth matrix, and full 4,096-page verification after the lower-stat measurement window. Verification reads are outside the reported measurement deltas. The fixed-rate matrix used exactly 45,000 operations per run (35,908 writes, 9,092 reads) over 30 seconds at 1,500 offered IOPS. This used the direct helper rather than fio; it records operation-level latency samples, errors, achieved counts and CPU/RSS for the helper process.

The combined sustained matrices contain 138 valid full-verification trials and 3 excluded records. This includes the original 120 sustained trials plus 18 coalescing-delay trials (three repetitions at each of 1/2/4 ms for QD1 and QD8). The failed records are retained in `rejected-trials.csv`: one early V2.2 QD1 helper post-run quiescence/verification gate skipped final verification despite zero helper errors and target failure; it was rerun successfully. One initial alpha.6 table used the wrong target type and failed before workload I/O. One rate run collided with an existing result-directory name and failed before target I/O. These are harness/setup exclusions, not successful trials.

## Matched 80/20 mixed workload: V2.2 versus PR #57 bulk=1

Medians over valid 30-second saturated runs; QD1/QD8 have five or more runs each, QD4/QD32 three. Lower bytes/requests are independent backing `null_blk` sysfs deltas; GC traffic is included in those totals. Latency is helper completion p99; CPU is helper-process CPU only, not total kernel CPU.

| QD | Driver / mode (n) | Useful ops/s | Lower write MiB | Lower write req | Write B/useful write | Lower read MiB | Lower read req | Read B/useful read | Write p99 ms | Read p99 ms | Helper CPU s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | V2.2 (6) | 5,101 | 476.64 | 122,022 | 4,097 | 121.57 | 31,122 | 4,110 | 0.882 | 10.711 | 2.75 |
| 1 | PR #57 bulk=1 (5) | 5,091 | 476.36 | 121,948 | 4,102 | 122.04 | 31,242 | 4,132 | 0.601 | 0.459 | 2.35 |
| 4 | V2.2 (3) | 6,135 | 449.00 | 55,058 | 3,206 | 145.73 | 37,306 | 4,105 | 17.736 | 17.500 | 4.13 |
| 4 | PR #57 bulk=1 (3) | 5,831 | 457.97 | 85,994 | 3,443 | 138.86 | 35,549 | 4,107 | 17.073 | 17.054 | 4.30 |
| 8 | V2.2 (5) | 6,365 | 438.04 | 27,592 | 3,017 | 151.07 | 38,674 | 4,105 | 18.159 | 17.771 | 4.13 |
| 8 | PR #57 bulk=1 (5) | 6,505 | 440.88 | 60,448 | 2,969 | 154.41 | 39,528 | 4,105 | 17.444 | 17.387 | 4.63 |
| 32 | V2.2 (3) | 6,424 | 421.47 | 7,353 | 2,875 | 152.50 | 39,039 | 4,105 | 19.117 | 18.353 | 5.43 |
| 32 | PR #57 bulk=1 (3) | 6,995 | 425.96 | 41,003 | 2,667 | 166.14 | 42,530 | 4,105 | 18.387 | 18.235 | 6.13 |

Against V2.2, PR #57 bulk=1 lower write requests were approximately unchanged at QD1, **56% higher at QD4, 119% higher at QD8, and 458% higher at QD32**. Absolute lower write bytes were 0.06% lower at QD1, then 2.0%, 0.65%, and 1.07% higher at QD4/QD8/QD32. At QD8/QD32 V3 completed more useful operations and used fewer lower write bytes per completed logical write, but this came with much higher lower request counts and higher aggregate reads at saturation. At matched 1,500 IOPS, V3 did not improve total I/O (below).

The 1,500-IOPS paired runs had 45,000 verified operations each. Median PR #57 QD1 lower writes were 35,979 requests / 147.366 MB versus V2.2 35,918 / 147.116 MB; lower reads were 9,250 / 37.888 MB versus 9,186 / 37.626 MB. At QD8 the corresponding values were PR #57 35,972 / 147.362 MB and 9,250 / 37.888 MB versus V2.2 35,902 / 147.083 MB and 9,186 / 37.626 MB. Thus the measured byte/request result at matched offered and completed operations is slightly worse for PR #57, although its helper p99 was lower in these three-run samples. This does not establish a generally lower-latency result.

### Bulk-mode/window controls

Main queue-depth matrix uses `coalesce_ms=0`, `window=64`, `gc=2`, `read_cap=0`, `verify=0`; PR #57 fault index is 0. At QD1 every measured PR #57 logical window was a singleton for bulk=0/1/2, and lower write requests were indistinguishable; the aggregation mode is not useful there. Median singleton-window shares were:

| QD | Alpha.6 bulk baseline | PR #57 bulk=0 | PR #57 bulk=1 | PR #57 bulk=2 |
|---:|---:|---:|---:|---:|
| 1 | 100% | 100% | 100% | 100% |
| 4 | 60.9% | 59.9% | 49.1% | 48.8% |
| 8 | 46.1% | 47.0% | 32.0% | 31.1% |
| 32 | 38.5% | 38.5% | 22.7% | 22.9% |

For bulk=1, the histogram fields reconcile to the target's `windows` count in all selected trials. Relative to PR #57 bulk=0, bulk=1 reduced independent lower write requests by about 26% at QD4, 46% at QD8, and 62% at QD32, but it still did not beat V2.2. Bulk=2 saved a further roughly 3% of requests at QD8 and 7% at QD32 over bulk=1, while recording 595 and 2,460 padding blocks respectively (4 KiB units; about 2.3 and 9.6 MiB). It did not lower QD8 write bytes; QD32 write bytes were about 0.4% higher than bulk=1. Its tradeoff is workload and device dependent, not a default win.

### Focused online-coalescing delay follow-up

The 18 additional trials used the same direct-I/O 80/20 mixed fixture and 10-second warmup / 30-second measurement as the primary mixed workload. Each delayed setting has three fully verified repetitions. The 0 ms references are the corresponding PR #57 `bulk=1` saturated QD1/QD8 groups in the main matrix (five repetitions each). The test measured whether waiting for the timer created multi-page windows and whether that reduced independently counted backing traffic.

| QD | `coalesce_ms` | Runs | Useful ops/s | Lower write MiB | Lower write req | Lower read MiB | Lower read req | One-page windows / windows | Write p99 ms | Read p99 ms |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 5 | 5,091 | 476.36 | 121,948 | 122.04 | 31,242 | 121,760 / 121,760 | 0.601 | 0.459 |
| 1 | 1 | 3 | 622 | 58.39 | 14,949 | 15.10 | 3,865 | 14,921 / 14,921 | 2.777 | 0.112 |
| 1 | 2 | 3 | 416 | 38.94 | 9,969 | 10.20 | 2,611 | 9,957 / 9,957 | 3.925 | 0.115 |
| 1 | 4 | 3 | 249 | 23.41 | 5,993 | 6.19 | 1,584 | 5,988 / 5,988 | 5.858 | 0.120 |
| 8 | 0 | 5 | 6,505 | 440.83 | 60,448 | 154.36 | 39,528 | 19,105 / 59,685 | 17.444 | 17.387 |
| 8 | 1 | 3 | 6,541 | 439.89 | 58,873 | 155.35 | 39,764 | 17,503 / 58,046 | 17.504 | 17.443 |
| 8 | 2 | 3 | 6,544 | 439.77 | 58,762 | 155.45 | 39,790 | 17,409 / 58,011 | 17.489 | 17.440 |
| 8 | 4 | 3 | 6,543 | 439.77 | 58,746 | 155.42 | 39,782 | 17,330 / 57,930 | 17.490 | 17.437 |

At QD1, every reported window remains a singleton at every delay, including 0 ms. Longer coalescing settings sharply reduce useful throughput (about 5,091 to 622/416/249 ops/s) while write p99 rises from 0.60 ms to 2.78/3.93/5.86 ms. Lower write bytes and requests fall because far fewer logical writes complete; cost remains about 4.10 KiB and 1.00 backing request per useful write. This is a latency/throughput penalty, not improved packing.

At QD8, coalescing reduces the singleton-window count by about 8.4–9.3% and lower write requests by 2.6–2.8% versus 0 ms. Lower write bytes fall only 0.24–0.27%, while lower read bytes/requests rise about 0.6%; throughput and p99 are effectively unchanged in this null_blk workload. This is a small request-count improvement at QD8, not a material lower-byte win. The 1–4 ms settings do not establish a general coalescing benefit; QD1 results are clearly worse. Per-trial data and window counters are in `sustained-trials.csv` and the raw coalescing matrix in the evidence archive.

### Mixed read/write ratio controls

Three valid QD8 runs each, same mixed fixture, 10-second warmup / 30-second measured:

| Reader share | Driver | Ops/s | Lower write MiB / requests | Lower read MiB / requests | Write/read p99 ms |
|---:|---|---:|---:|---:|---:|
| 30% | V2.2 | 6,178 | 370.46 / 22,155 | 219.91 / 56,298 | 18.30 / 18.04 |
| 30% | PR #57 bulk=1 | 6,140 | 377.55 / 56,800 | 218.55 / 55,950 | 17.69 / 17.63 |
| 50% | V2.2 | 5,837 | 249.07 / 15,119 | 344.30 / 88,140 | 18.60 / 18.33 |
| 50% | PR #57 bulk=1 | 5,582 | 267.84 / 49,362 | 329.58 / 84,372 | 18.10 / 18.06 |

These mixed ratios again show higher PR #57 write requests and bytes, while the reader totals are affected by lower achieved throughput. Keep the independent read and write columns separate; they do not combine into a single score.

### Uniform compressed-size and raw controls

Three valid QD8 repetitions per row, same 20% read mix. Lower writes are absolute for each 30-second run; “write B/op” normalizes by successfully completed upper writes.

| Measured input class | Driver | Ops/s | Lower write MiB / req | Write B/useful write | Lower read MiB | Write/read p99 ms |
|---|---|---:|---:|---:|---:|---:|
| 1,031 B LZ4 | V2.2 | 9,678 | 383.17 / 36,737 | 1,654 | 229.79 | 17.40 / 17.13 |
| 1,031 B LZ4 | PR #57 bulk=1 | 8,763 | 407.90 / 77,233 | 1,947 | 208.30 | 16.83 / 16.80 |
| 2,088 B LZ4 | V2.2 | 4,979 | 487.96 / 21,049 | 4,097 | 118.64 | 18.44 / 18.13 |
| 2,088 B LZ4 | PR #57 bulk=1 | 6,065 | 472.79 / 60,669 | 3,261 | 144.41 | 17.54 / 17.49 |
| 3,499 B LZ4 | V2.2 | 4,982 | 488.25 / 20,883 | 4,097 | 118.70 | 18.36 / 18.06 |
| 3,499 B LZ4 | PR #57 bulk=1 | 5,039 | 494.54 / 45,542 | 4,102 | 120.73 | 17.91 / 17.83 |
| Raw 4 KiB | V2.2 | 4,983 | 488.29 / 21,491 | 4,097 | 118.71 | 18.58 / 18.32 |
| Raw 4 KiB | PR #57 bulk=1 | 5,038 | 494.41 / 45,085 | 4,102 | 120.66 | 17.91 / 17.85 |

The 2,088 B case has a meaningful V3 byte-per-write reduction, but V3 still issues about 2.4 times as many lower write requests per useful write. At 1,031 B V3 is worse in both bytes and requests per useful write. At 3,499 B and raw, write bytes per operation are similar/slightly higher for V3, with about 2.1 times the lower request count. These are input LZ4 classes, not a per-write kernel histogram. The per-run CSV includes sample sizes and full percentiles.

### Backing-stat reconciliation

Across the original 120 selected sustained trials (not including the 18 later coalescing-delay runs), independent `null_blk` lower write bytes exactly matched the target `physical_write` delta. The backing write-request count was exactly one greater than the target `physical_write_reqs` delta in every one of those 120 trials; this systematic one-request difference remains unexplained, so request conclusions use the independent lower sysfs counts. A flush was separately visible in sysfs. Read bytes matched in 113/120 trials; the other seven differed by -225,280 to +49,152 B. Of the 79 trials whose target version exposed comparable `physical_read_reqs`, 75 request deltas matched and four differed by -46 to +12. V2.2 does not expose the same lower read-request field, so its read-request target reconciliation is unavailable. The small read discrepancies are consistent with separate status/stat snapshot boundaries, but that cause is not proven. In all 18 coalescing-delay trials, lower read/write bytes and request deltas matched the target counters exactly; their window histogram counters also reconciled. Independent lower counters remain the benchmark source of record; read-counter reconciliation for the original 120 trials is therefore **not fully verified**.

## GC evidence and cost

A clean loaded GC control completed **nine** role rotations over 8,192 logical pages; every page verified before and after, and the target was normally removed. Measured target-reported GC traffic was 8,220,672 B read in 1,985 requests and 4,640,768 B written in 644 requests, relocating 1,896 pages. The lower writes were independently counted in the fixture. A synthetic write-failure trial configured `test_fail_write_nth=9,217`; it failed at overwrite 612 / slot 100 after five successful rotations. Status remained at five rotations (no sixth reserve exchange); all previously completed phase checks had passed. The failed target was not read after fail-closed EIO and was ordinarily removed. This confirms no false sixth progress indication in this scenario, not complete media-originated GC fault coverage.

The captured kernel log contains five generic `Buffer I/O error on dev dm-0, logical block 0, async page read` messages across the prior alpha.3 attempt and synthetic GC-failure runs. The GC helper records `NO_POST_FAILURE_READS_ISSUED`, and repeating the GC control/failure after `udevadm settle` did not remove the message. Its reader/source is unidentified; it is not attributed to the test helper or claimed as proof of target corruption. No Oops, BUG, lockdep report, workqueue CPU-hog warning, hung-task report, or timeout matched the captured validation interval. This unresolved asynchronous read diagnostic remains a caveat for fault-path qualification.

At primary mixed QD1, PR #57 reported median GC traffic around 0.742 MiB read / 0.730 MiB write versus V2.2 around 0.086 / 0.086 MiB. At QD4 the observed V3 GC volume was small (~0.04–0.05 MiB per direction); QD8/QD32 primary samples had no role rotations. The uniform 3,499 B and raw controls caused approximately 170–177 V3 rotations and ~0.67–0.69 MiB of GC reads/writes; V2.2 reported about 0.07 MiB each. GC traffic is already included in the independent lower totals. These results do not establish that a particular V3 GC policy is superior; this sustained campaign held PR #57 at `gc=2` and did not repeat a full three-policy victim-selection factorial.

The PR #56 full-destination/full-relocation regression's exact-C coverage passed. This validation did not reproduce its separate 256-survivor loaded test on PR #57; do not interpret the sustained and nine-rotation tests as a pass for that specific full-destination scenario.

## Failed and unavailable test classes

- Device-originated write/flush error, torn/short real lower completion: **BLOCKED**; only target-local synthetic pre-submission EIO and exact-C mocked partial-completion tests were available.
- Full loaded 256-survivor GC full-destination negative case on PR #57: **NOT RUN** in this campaign; exact-C regression passes.
- Kernel-wide CPU attribution and target memory overhead: **UNMEASURED**. The recorded CPU/RSS values belong to the userspace benchmark helper, not the worker threads/module.
- A sustained 15-case matrix for every data mix at every QD and coalesce delay: not run. The focused matrix covers QD1/4/8/32 for mixed 80/20, QD8 for 70/30 and 50/50, plus isolated size classes and fixed-rate controls.
- Physical SD/SSD/HDD: **NOT AUTHORIZED and NOT TESTED**.

## Verdicts

| Area | Verdict | Evidence |
|---|---|---|
| Exact source/build and rootless tests | **PASS** | Exact SHA; W=1/W=2; GCC sanitizer and Clang O0/O2; 24 bulk tests and 24 source contracts. |
| Loaded PR #57 with injector disabled | **PASS** | Fault counters inactive; 1,024-page burst matches alpha.7; sustained successful readbacks. |
| Loaded pre-submission lower-write injector | **PASS** | 18/18 first/later fail cases observed EIO and ordinary cleanup. |
| Device-originated partial/torn lower writes | **BLOCKED** | Not produced by the injector; no isolated null_blk per-instance fault path. |
| Full-page sustained oracle | **PASS** | Every selected 30-second performance trial verified 4,096/4,096 pages. |
| Matched-rate lower I/O vs V2.2 | **WORSE/MIXED** | V3 is slightly higher in read/write bytes and requests at 1,500 completed IOPS; sampled p99 was lower. |
| Saturating lower write request count vs V2.2 | **WORSE** | Bulk=1 has 56% to 458% more lower write requests at QD4–32; QD1 is approximately equal. |
| Saturating lower write bytes vs V2.2 | **MIXED** | Aggregate V3 bytes near/slightly above V2.2; per-useful-write bytes improve at QD8/QD32 only as V3 reaches higher throughput. |
| Bulk=1 vs PR #57 bulk=0 | **BETTER, not enough to beat V2.2** | 26%, 46%, 62% fewer lower write requests at QD4/8/32; none at QD1. |
| Bulk=2 vs bulk=1 | **MIXED** | A few percent fewer requests at QD8/32, with padding blocks and no consistent byte or CPU benefit. |
| Coalescing 1/2/4 ms vs 0 ms | **MIXED** | QD8 saves 2.6–2.8% of write requests but less than 0.3% of write bytes, with about 0.6% more reads and no meaningful p99/throughput change. At QD1 it leaves all windows singleton, drops throughput by 88–95%, and raises write p99 to 2.78–5.86 ms. |
| Production readiness | **NOT ESTABLISHED** | Still lacks device-originated fault qualification, full loaded failure matrix, per-trial request reconciliation, kernel CPU/memory attribution and media qualification. |

## Recommendations to the primary developer

1. Investigate the independent request-count delta: every sustained sample has exact byte reconciliation but one more backing write request than `physical_write_reqs`.
2. Focus next on V3 lower request amplification against V2.2. Bulk=1 helps relative to the V3 serialized path but the steady workload still emits more backing writes.
3. Add or expose per-run compressed lengths and actual lower-I/O run geometry to determine why 1,031 B records lose while 2,088 B records save bytes per write.
4. Keep bulk=1 experimental. Bulk=2 is only potentially useful when request count is valuable enough to trade against deliberate 4 KiB padding.
5. Do not authorize a physical-media endurance claim from these null_blk measurements. A separate future media study is only justified after the V2.2 request-count gap and kernel CPU attribution are understood and a safely reviewed harness exists.

## Final cleanup and host state

After the last coalescing trial, `dmsetup ls --tree` reported no devices. The exact owned 40 MiB null_blk configfs instance had no holders, mounts, or swap ownership; it was powered off and removed normally, and its block node disappeared. The PR #57 `dm_swapz` module had refcount 0 and was unloaded normally. The pre-existing `null_blk` kernel module was left loaded. Final inventory again showed no DM mappings, no test-owned `null_blk` instance/device, and the same active swap identities (`/swapfile` and `/dev/sdb1`) as at start. No swap operation, physical-device I/O, or reboot was performed. Final host inventory and filtered kernel diagnostics are in the evidence archive.

## Reproduction artifacts

- `sustained-trials.csv`: every accepted trial's verified useful counts, independent lower bytes/requests, latency percentiles, CPU/RSS, target counters, GC, and window data.
- `sustained-summary.csv` / `.json`: grouped medians and min/max; each group records its sample count.
- `rejected-trials.csv`: excluded failed/incomplete harness runs and reasons.
- `summarize-results.py`: deterministic parser/aggregator with fail-closed trial selection.
- `make-uniform-fixtures.py`: deterministic actual-LZ4 class fixture generator.
- `run-uniform-class-matrix.py`, `run-mix-ratio-matrix.py`: matrix drivers.
- `run-sustained-coalesce-trial.py`, `run-coalesce-matrix.py`: the focused 0/1/2/4 ms online-coalescing delay comparison (the 0 ms reference comes from the primary matrix).
- `PR57_LOADED_VALIDATION_EVIDENCE.tar.gz`: raw environment, build/test logs, module metadata, fault cases, fixture manifests, per-trial JSON, latency CSVs, and cleanup evidence.
- `SHA256SUMS`: checksums for committed report artifacts and archive.

The archive SHA-256 is `db2fa602551a401a7adccb583bbdb5384f844ace8644ec50fafe62836825017b`. The archive contains raw evidence; the CSV is a derived summary. Results are loaded-kernel observations on memory-backed `null_blk`, not flash endurance or physical-device performance.
