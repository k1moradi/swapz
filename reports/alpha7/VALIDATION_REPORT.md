# Independent V3 alpha.7 validation

**Date:** 2026-10-13
**Candidate:** PR #55, `0e199159cea3dd479224ce59513ee9c0a810a0d6`
**Validation branch:** `codex/pr55-alpha7-validation`
**Result:** **MIXED / INCONCLUSIVE overall**. The 1,024-page mixed raw/compressed burst shows a repeatable, independently counted lower-write improvement with `lower_bulk=1/2`; functional tests passed for the covered cases. This does not establish sustained performance, latency, CPU cost, all fault classes, or production readiness.

## Executive result

The exact frozen 1,024-page fixture produced the same verified 4 MiB logical workload in every successful repetition: 819 LZ4-compressed pages and 205 raw pages. Five successful trials per tested configuration all read back all 1,024 pages byte-for-byte. Independent `null_blk` counters and target counters reconciled exactly for the measured write phase.

On that burst, alpha.7 `lower_bulk=1` and `2` reduced lower write requests from 419 (alpha.6 and alpha.7 `lower_bulk=0`) to 16, and lower write bytes from 1,716,224 to 905,216. Against loaded V2.2, alpha.7 `lower_bulk=1/2` used 16 versus 26 lower write requests and 905,216 versus 1,679,360 bytes. This demonstrates the raw-write submission floor was overcome on this specific burst. `lower_bulk=2` did not improve on `1`.

Eight loaded GC role rotations completed with full-image checks after the cycles and a successful foreground refill after each rotation. The full-destination negative case failed closed with `-ENOSPC` before GC submitted relocation reads or writes. Valid loaded PREFLUSH and compressed/raw FUA operations completed; injected synthetic flush errors propagated once and failed the target closed.

The campaign did **not** run a sustained fio workload or measure read/write p95/p99, achieved IOPS, CPU, or memory cost. Trial order was grouped by implementation rather than counterbalanced. Therefore, the measured burst advantage is real for its tested workload, but the overall performance comparison remains **INCONCLUSIVE**. V3 alpha.7 is not production-qualified.

## Exact source and module provenance

The PR #55 head was checked at the beginning and after testing; both `refs/pull/55/head` and `feat/v3-mixed-lower-io` remained `0e199159cea3dd479224ce59513ee9c0a810a0d6`. The tested production source was not modified.

The validation branch has one test-only correction, commit `2b7ea292a8f006262ac7b0d020ec85f0ff472f3a`, which initializes `pages[index].raw = 0` in `extent-v3-engine-test.c`. Clang O0/O2 had exposed this uninitialized field in the test fixture. No kernel production file changed. The module used in the loaded tests has SHA-256 `405eabc1d77ee806131a57ff5a2328028ac1e829167c241ac301c049c855f2d5` and srcversion `C3512BF64435FC340AD0F62`, matching the W=2 artifact. Its name is `dm_swapz`, its Device Mapper target is `swapz3`, and vermagic is `7.0.0-38-generic SMP preempt mod_unload modversions`.

| Candidate | Commit | Module SHA-256 | Build |
|---|---|---|---|
| V3 alpha.7 | `0e199159cea3dd479224ce59513ee9c0a810a0d6` | W=1 `9c0b30715dd1c5315de8bbf917bd39134d1bdacc3cc39fd61af6774ee501ecaf`; W=2 `405eabc1d77ee806131a57ff5a2328028ac1e829167c241ac301c049c855f2d5` | W=1 and W=2, exit 0 |
| V3 alpha.6 | `4324c98497891147896ad817f4593c5cc198953b` | `26333402ee8c64fed5dbb4b1ea3493e1b7233d22b92bccda4d4a43bf238a0df1` | W=2, exit 0 |
| V2.2 frozen | `3a89ebbeba21c814dcf724e227b31d38445a3f9a` | `f6b5f0ae1f4c0b8b6ee625615daa9511aeaa4d2a936ff5d5047fa83a415a5483` | W=2, exit 0 |

The three `dm_swapz` builds were loaded strictly sequentially. Alpha.7’s actual loaded `/sys/module/dm_swapz/srcversion` matched the W=2 artifact. Source blobs and full `modinfo`/build records are included in the evidence archive.

Host: `Inspiron1564Linux`, Ubuntu 26.04.1, kernel `7.0.0-38-generic`; GCC 15.2.0, Clang 23.1.3, fio 3.41, liblz4 1.10.0. The primary comparison used the test-only kernel BIO helper, not fio. Build output contained no production C warnings. The environment reported a GCC target-tuple string difference although both compiler versions were GCC 15.2.0; BTF generation was skipped because available pahole was version 0 while the kernel build used version 131 and `vmlinux` was unavailable.

Alpha.7 production blob IDs:

| File | Git blob |
|---|---|
| `kernel/extent-v3/dm-target.c` | `70e2e1dd4daa897ebd694fe6c41024a84ead5537` |
| `kernel/extent-v3/authority.c` | `8e43663f2ba5b8eb2f0abb824db902a459385188` |
| `kernel/extent-v3/authority.h` | `611c12971cac6d0224852b2c8dac1152a021ce63` |
| `kernel/extent-v3/engine.c` | `885662604fde89f62d99a9aa211010a8be3f613b` |
| `kernel/extent-v3/codec.c` | `f88d2697a5c15aa068ddd5d7853a5c38af397810` |
| `kernel/extent-v3/Makefile` | `be0bb1a01287069c97c6459e016d8f010bb47e74` |
| `kernel/extent-v3/MIXED_LOWER_WRITE_AGGREGATION.md` | `10057b5eb9224610ce5c3d9f7f1925de18f92f83` |

V2.2 `kernel/dm-swapz.c` blob: `a75043d1948e38f8d1ab021c99cdd4571e0f23e9`.

## Test method and matched fixture

The primary comparison reused the frozen alpha.5 1,024-page byte fixture and the same queue-probe generator/verifier. Fixture SHA-256: `41426178c19fc6f64d7b23439ac02b3c9ca36231c8123371236e6b351952b5d8`; JSON page manifest SHA-256: `31d8cc79569728c1a261bf0f4cc527bb851e28d2c34f2c5f006aa0a05c0d3c2d`. The payload generator reproduced each page emitted by the kernel queue probe. The 819 compressible pages each produce a 57-byte LZ4 output; the other 205 pages take the raw fallback. Total useful data was 4,194,304 bytes.

All candidates used the same newly owned 40 MiB memory-backed `null_blk` instance (`nullb_swapz3_a7_0e199159`, major:minor `251:0`, `memory_backed=1`, 512-byte logical block, 20 MiB/s throttle, 500,000 ns completion delay, one submit queue, hardware queue depth 64, `queue_mode=2`, cache size 8, FUA enabled). The 4 MiB DM target had 8,192 sectors. Each trial created a fresh UUID-owned target, submitted 1,024 one-page write BIOs, drained, measured lower and target counters, independently verified all pages, then ordinarily removed the target and power-cycled the owned backing device before the next trial.

V2.2 table: `0 8192 swapz <owned-nullb> opportunistic 64`. V3 table: `0 8192 swapz3 <owned-nullb> 0 64 0 2 0 0 <lower_bulk>`, giving `read_cap=0`, `window=64`, `verify=0`, `gc=2`, `coalesce_ms=0`, and `lower_bulk=0/1/2`.

Five **successful** repetitions were collected per row below. Run order was grouped by implementation and mode, not counterbalanced; this is a protocol deviation. Integer lower counters were identical across all five repetitions in each configuration. Two earlier alpha.7 `lower_bulk=0` attempts failed in the test harness before valid data measurement: one treated expected `findmnt` no-match exit 1 as fatal, and one used a queue helper with an unresolved symbol. Both failed attempts are preserved in the archive; the helper was corrected/rebuilt before successful repetitions. No primary result was taken from those attempts.

## Primary lower-I/O results

Block-stat sectors are 512-byte units. Lower bytes are `delta_write_sectors_512 * 512`. Verification reads were measured separately after the write window and excluded from write-phase counts.

| Driver / setting | Repetitions | Verified pages / useful writes | Lower write bytes (min/median/max) | Lower write requests (min/median/max) | Lower reads during write | Verify reads after write | Target windows; singleton windows |
|---|---:|---:|---:|---:|---:|---:|---|
| V2.2, batch 64 | 5 | 1,024 / 4 MiB each | 1,679,360 / 1,679,360 / 1,679,360 | 26 / 26 / 26 | 0 B, 0 req | 4 MiB, 1,024 req | V2.2 exposes no matching window histogram; `max_write_batch=16` |
| Alpha.6, lower_bulk=0 | 5 | same | 1,716,224 / 1,716,224 / 1,716,224 | 419 / 419 / 419 | 0 B, 0 req | 4 MiB, 1,024 req | 214; 6 |
| Alpha.6, lower_bulk=1 | 5 | same | 1,716,224 / 1,716,224 / 1,716,224 | 419 / 419 / 419 | 0 B, 0 req | 4 MiB, 1,024 req | 214; 6 |
| Alpha.6, lower_bulk=2 | 5 | same | 1,716,224 / 1,716,224 / 1,716,224 | 419 / 419 / 419 | 0 B, 0 req | 4 MiB, 1,024 req | 214; 6 |
| Alpha.7, lower_bulk=0 | 5 | same | 1,716,224 / 1,716,224 / 1,716,224 | 419 / 419 / 419 | 0 B, 0 req | 4 MiB, 1,024 req | 214; 6 |
| Alpha.7, lower_bulk=1 | 5 | same | 905,216 / 905,216 / 905,216 | 16 / 16 / 16 | 0 B, 0 req | 4 MiB, 1,024 req | 16; 0 |
| Alpha.7, lower_bulk=2 | 5 | same | 905,216 / 905,216 / 905,216 | 16 / 16 / 16 | 0 B, 0 req | 4 MiB, 1,024 req | 16; 0 |

All 35 successful trials passed full byte-for-byte verification. During every measured write phase the independent lower-device read delta was zero. Afterward, each verifier issued exactly 1,024 lower read requests / 8,192 sectors = 4 MiB; this readback phase was equal across all candidates. Target `physical_write` bytes and request counts matched the independent lower stat deltas in all trials. The V3 status also reported 819 compressed and 205 raw pages.

Relative to alpha.6/alpha.7 `lower_bulk=0`, alpha.7 `lower_bulk=1/2` reduced lower write requests by 403/419 = **96.18%** and bytes by 811,008 = **47.26%**. Relative to loaded V2.2, it reduced requests by 10/26 = **38.46%** and bytes by 774,144 = **46.10%**. The logical-to-lower-write-byte ratio rose from 2.50x (V2.2) and 2.44x (alpha.6) to 4.63x (alpha.7 bulk 1/2). These are lower block-layer transfer counts on RAM-backed `null_blk`, not NAND operations or a physical-media endurance result.

Alpha.6 `lower_bulk=1/2` showed `bulk_io=208` while the actual backing count remained 419; callback grouping alone did not merge the block requests. Alpha.7 reported 16 mixed-format lower submissions, `bulk_mixed_io=16`, `bulk_raw_entries=205`, and its independent backing count was also 16. This is direct evidence that alpha.7’s mixed raw/compressed aggregation, rather than only a changed compression ratio, overcame the prior raw submission floor for this queue burst. `lower_bulk=2` did not improve over `1` in this workload.

The matrix was a finite high-concurrency 1,024-BIO burst—not a sustained fio comparison. It does not yield meaningful achieved-throughput, read/write p99, CPU or memory conclusions. Grouped candidate order and lack of counterbalancing also limit timing interpretation, although byte/request totals were invariant in all repetitions.

## Loaded correctness evidence

| Case | Result | Evidence / limits |
|---|---|---|
| Mixed 819 compressed + 205 raw queue write/read | PASS | 1,024 submitted/completed, zero BIO errors, exact 4 MiB readback; backing and target writes reconcile. |
| Raw and compressed overwrite transitions | PASS for exercised cases | Compressed-to-raw and raw-to-compressed overwrite, read-after-write, discard then zero read, and rewrite readback passed. No checksum bit-flip fault was injected. |
| Valid FUA / PREFLUSH | PASS for exercised cases | Actual upper compressed and raw `REQ_FUA` BIOs completed once with exact readback; valid zero-length `WRITE|PREFLUSH` completed in order. Aggregate valid helper status showed `flush_calls=3`, `flush_ok=3`, `flush_err=0`. |
| Synthetic flush failure | PASS for expected injected failure | `test_fail_flush_nth=1` fails before lower flush submission. PREFLUSH and post-write FUA synthetic `-EIO` completed with expected error exactly once; target status recorded `flush_err=1`, `flush_injected=1`, `failed=1,error=-5`. The preceding preflush write itself completed, but the flush BIO failed. This is not a device-originated lower flush fault. |
| Device-originated lower write/flush failures | BLOCKED | No isolated device-originated fault injection was used. Do not infer real lower-device failure behavior from synthetic pre-submission `-EIO`. |
| 1,024-BIO suspend/drain/resume, `coalesce_ms=0,1,2,4` | PASS for this matrix | Owned lower delay was 5 ms (deviation from the 500 µs primary configuration) to keep BIOs outstanding. All 1,024 BIOs completed with no errors; suspend drained, resume/read verification and ordinary teardown passed. `0 ms` had 17 windows; `1/2/4 ms` had 16; all windows were 17–64 records and none were singleton. |
| Eight GC role rotations | PASS for tested raw-heavy fixture | `gc_victims=8`, `gc_role_rotations=8`, reserve remained 512 blocks (two segments); each successful rotation was followed by foreground refill and full-image byte verification. Victim/destination sequence: 1→38, 0→1, 38→0, 1→38, 0→1, 38→0, 1→38, 0→1. Aggregate target GC counters were 32,768 bytes / 8 requests each for reads and writes. Some per-trigger backing-read windows included verifier/status reads; those are retained and not attributed solely to GC. |
| Full-destination negative case | PASS fail-closed behavior; no successful GC | On an 8,192-page logical target over the 40 MiB backing, the pre-existing 8,192 raw pages were first fully verified. A 256-page compressed prefix with 3,536-byte LZ4 output pages then failed with `-ENOSPC`. Status showed `gc_no_headroom_skips=31`, `gc_victims=0`, `gc_read=0`, `gc_write=0`, and unchanged `logical_write`/`write_submitted`. No new lower writes or role exchange occurred. The failed target rejected later reads, so the helper’s attempted post-failure readback is not evidence of data readback after failure. The exact owned mapping was removed ordinarily after zero-open/ownership checks. |
| Failure-safe target removal / module unload | PASS | Failed full-destination target removed by its exact UUID with ordinary `dmsetup remove`; `dm_swapz` had refcount zero and was ordinarily unloaded. |

The online drain matrix observed `coalesce_ms=0`: 17 windows, 1,024 window records, zero singleton, all 17 in `win17_64`; `1/2/4 ms`: 16 windows, 1,024 records, zero singleton, all 16 in `win17_64`. This burst already supplied enough queued records at 0 ms. Coalescing added one deferred event for nonzero delays, but no additional lower-write saving over bulk=1. No completion latency was measured, so this is not evidence that the delay is free.

The GC sequence began with one setup attempt whose script incorrectly assumed 32 MiB while the configured backing was 40 MiB; the test setup was corrected before the final eight-cycle sequence. The first two cycle windows also had helper sequencing/read-counter contamination; the complete per-cycle status/data records are retained. Those test-method deviations do not change the separately recorded final `gc_role_rotations=8` and full-image checks, but the GC lower-read cost should not be treated as an isolated repeated benchmark.

## Rootless tests and build commands

| Command | Result |
|---|---|
| `python3 -B /tmp/swapz-v3-alpha7-evidence-0e199159/run-validation-rootless.py` from validation branch | PASS: 15/15 targets at GCC `-O1 -Wall -Wextra -Werror -fsanitize=address,undefined`; codec, authority, snapshots, writes/readback, raw/discard, randomized engine, GC, flush, bulk-I/O and source contract. |
| Clang exact-C compile/run at `-O0` and `-O2`, 14 tests each, against validation branch | PASS: 28/28. |
| Earlier original Clang pass before test-only correction | 26/28 passed; engine fixture failed at planner assertion because `raw` was uninitialized. Fixed by commit `2b7ea29`; engine now passes at O0 and O2. |
| `make -C kernel/extent-v3 KDIR=/lib/modules/7.0.0-38-generic/build W=1 -j2 all` | PASS, exit 0. |
| Clean `make -C kernel/extent-v3 KDIR=/lib/modules/7.0.0-38-generic/build W=2 -j2 all` | PASS, exit 0. |
| Alpha.6 and V2.2 W=2 builds against the same headers | PASS, exit 0 each. |

The source qualification workflows on the unchanged alpha.7 head were green at test start: [kernel/exact-C](https://github.com/k1moradi/swapz/actions/runs/38356537469), [teardown](https://github.com/k1moradi/swapz/actions/runs/38356537679), [combined](https://github.com/k1moradi/swapz/actions/runs/38356537466). Fresh CI for the validation branch is reported in the PR after publication.

## Kernel diagnostics and safety

Relevant test-window logs showed the expected `swapz3` registration and the explicit full-destination `-ENOSPC` fail-closed diagnostic. No test-attributable Oops, kernel warning, lockdep report, hung task, workqueue CPU-hog warning or BIO timeout was found in the reviewed logs. The synthetic FUA/PREFLUSH `-EIO` results were expected injected errors. Unrelated pre-existing host messages were not counted as swapz failures.

The backing device was only the owned configfs `null_blk`. `/dev/sdb1` and `/swapfile` remained active swap entries; no swapoff/swapon was run. At completion there were no DM mappings, the owned `dm_swapz` and queue-probe modules were absent, the owned configfs null_blk instance and block node were absent, and the pre-existing `null_blk` module remained loaded with use count zero. Protected untracked state files retained their recorded SHA-256 hashes. No reboot occurred.

## Verdicts and next work

| Qualification | Verdict |
|---|---|
| Alpha.7 build / source identity | PASS |
| Exact-C and sanitizer coverage | PASS after test-only fix |
| Loaded mixed raw/compressed 1,024-page write/read | PASS |
| Lower write aggregation benefit on this burst | BETTER: 16 requests / 905,216 B vs V2.2 26 / 1,679,360 B; vs alpha.6 419 / 1,716,224 B |
| Online coalescing 0 vs 1/2/4 ms | INCONCLUSIVE for latency; burst windows differed 17 vs 16 but no extra lower-write gain beyond bulk aggregation |
| Eight-cycle loaded GC progress | PASS for tested raw-heavy fixture; isolated GC economics remain INCONCLUSIVE |
| Full-destination rejection | PASS fail-closed; expected `-ENOSPC`, zero relocation I/O |
| Loaded lower write-fault and genuine flush-fault handling | BLOCKED |
| Sustained throughput, read/write p95/p99, CPU and memory campaign | NOT RUN |
| V2.2 matched sustained comparison | BLOCKED / NOT RUN; only the matched finite primary burst was measured |
| Physical SD/SSD/HDD qualification | NOT RUN; this campaign used null_blk only |
| Production readiness | NOT ESTABLISHED |

**Recommendation:** Keep alpha.7 as a promising aggregation candidate for further development, but do not call it a general performance win yet. The next decisive experiment is a counterbalanced sustained V2.2/alpha.6/alpha.7 run at matched achieved IOPS with read and write latency logs and verified payload-size distributions. Preserve `lower_bulk=1` as the leading candidate; the tested `lower_bulk=2` added no observed benefit. Run focused lower-write fault injection and mixed compressed/raw GC relocation before treating the loaded correctness gate as complete.

Physical-media testing is not justified by this result alone: the byte/request win is on a single high-concurrency null_blk fixture with no sustained latency or CPU evidence. No physical-media test was performed.

## Reproduction artifacts

- [`primary-trials.csv`](primary-trials.csv) — all 35 successful repetitions and measured fields.
- [`primary-summary.json`](primary-summary.json) — validated aggregates; the script rejects incomplete verification or counter mismatches.
- [`summarize-primary.py`](summarize-primary.py) — standard-library-only summarizer.
- [`evidence-alpha7.tar.gz`](evidence-alpha7.tar.gz) — source/module/build records, raw successful and failed trial records, fixture and hashes, rootless logs, live FUA/overwrite/GC/suspend records, and helper sources. Internal `SHA256SUMS` covers archive contents.
- [`SHA256SUMS`](SHA256SUMS) — hashes for report-side artifacts.

The primary runner used for these trials is in the evidence archive at `helpers/run-primary-trial.py`; it is bound to the uniquely named test null_blk and does not load modules or attempt cleanup after an ambiguous failure.
