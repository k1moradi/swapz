# swapz V3.0.0-alpha.5 independent qualification

Date: 2026-10-12  
Test host: `Inspiron1564Linux`, Ubuntu 26.04.1, x86_64, kernel `7.0.0-38-generic`  
Validation worktree: `/tmp/swapz-v3-alpha5-validation-cb8624b`  
Evidence directory (raw logs retained on host): `/tmp/swapz-v3-alpha5-evidence-cb8624b`

## Executive result

The alpha.5 production target passed the tested loaded correctness gates: valid upper PREFLUSH/FUA sequencing, synthetic flush-error propagation, 1,024-write suspend/drain/resume, eight reserve rotations under all three GC selectors, and byte-exact readback. Full-destination pressure failed closed with `-ENOSPC`; one fragmentation case consumed 1 MiB of reads and 1 MiB of writes without completing a role rotation.

The performance evidence is **mixed and insufficient for a sustained-load claim**. A matched 1,024-BIO burst transferred 2.2% more lower write bytes with V3's default settings and generated 419 V3 extent write requests versus 26 V2.2 stream write requests. Separately, 16-write bursts showed that coalescing can cut write bytes by 37.5–61.5%, but it increased read traffic for uniform payloads and raised the 16-sample writer p95 into the 2–5 ms range. No long-running matched achieved-IOPS benchmark was run, so V3 has not demonstrated an overall lower-I/O performance win over V2.2.

No kernel C source or test source was changed. The only new commit is this report and compact result tables on a separate validation branch.

## Source and build identity

- Repository: `git@github.com:k1moradi/swapz.git`
- PR #52 head checked at start and again before publication: `cb8624b35c775adff853b2354df7153d96b282ad` (unchanged).
- PR #52 base branch: `fix/v3-flush-contract-io-aware-gc`.
- GitHub Actions for this exact commit: [kernel build/exact-C](https://github.com/k1moradi/swapz/actions/runs/38324514001), [teardown safety](https://github.com/k1moradi/swapz/actions/runs/38324514026), and [combined qualification](https://github.com/k1moradi/swapz/actions/runs/38324514061) all completed successfully.
- V3 version: `3.0.0-alpha.5`; artifact `kernel/extent-v3/dm-swapz.ko`, module `dm_swapz`, DM target `swapz3`.
- Kernel source blobs:

| File | Git blob |
|---|---|
| `kernel/extent-v3/dm-target.c` | `2321706baa9ce4126f5648f0bd4effc79083ae9f` |
| `kernel/extent-v3/authority.c` | `188485298a456ab1b6fc0005542cae3f9c2c3088` |
| `kernel/extent-v3/authority.h` | `9adb78c28538587ede9369a2ddbdfb7b31540e57` |
| `kernel/extent-v3/engine.c` | `05a2c7184aabf7b05a3c6e4f57028dbeb0ca1c47` |
| `kernel/extent-v3/codec.c` | `f88d2697a5c15aa068ddd5d7853a5c38af397810` |
| `kernel/extent-v3/gc-cost.h` | `05715e34a23323c5b70dc8196065d9bbe092b87f` |
| `kernel/extent-v3/Makefile` | `be0bb1a01287069c97c6459e016d8f010bb47e74` |

Host toolchain: GCC `15.2.0-16ubuntu1`; Clang `23.1.3`; fio `3.41`; liblz4 `1.10.0`. Matching headers were `/lib/modules/7.0.0-38-generic/build` (`/usr/src/linux-headers-7.0.0-38-generic`).

Commands, each exit 0:

```sh
make -C kernel/extent-v3 KDIR="/lib/modules/$(uname -r)/build" W=1 -j2 all
make -C kernel/extent-v3 KDIR="/lib/modules/$(uname -r)/build" W=2 -j2 all
```

Both were clean builds of the actual production module. No kernel C-source warnings were emitted. The exact W2-built artifact used for the alpha.5 loaded tests was SHA-256 `97bba5cc1476bcd9b17fbba4ced19f585bb3a0824762379b150db70c56ceb983` (715,232 bytes); `modinfo`: name `dm_swapz`, alias `dm-swapz3`, srcversion `210759D3A5DDB74BF41D79D`, vermagic `7.0.0-38-generic SMP preempt mod_unload modversions`. The separate W1 artifact was 715,224 bytes, SHA-256 `0185f72de181e7f809aaeaddddc804fed18bdf0fcf9590a09f13e1d81324a664`.

Warnings were environment diagnostics only, repeated under W=1 and W=2:

```text
warning: the compiler differs from the one used to build the kernel
  The kernel was built by: x86_64-linux-gnu-gcc (Ubuntu 15.2.0-16ubuntu1) 15.2.0
  You are using:           gcc (Ubuntu 15.2.0-16ubuntu1) 15.2.0
warning: pahole version differs from the one used to build the kernel
  The kernel was built with: 131
  You are using:             0
Skipping BTF generation for dm-swapz.ko due to unavailability of vmlinux
```

There were no source edits, so the tested SHA and module identity remain the PR #52 identities above.

## Rootless qualification

The 13 exact-production-C suites were built and run with GCC `-O1 -fsanitize=address,undefined`, Clang `-O0`, and Clang `-O2`. Each toolchain variant passed all 69 test groups: **207/207 group-runs**, zero sanitizer findings. The 69 groups include codec (8), authority (10), immutable transaction snapshot (4), write verification (7), dead-segment reuse (4), raw/discard authority (7), engine (9), GC-forbidden segment (3), GC cost (5), flush accounting (4), rotating GC (6), GC engine rotation (2), and the seeded engine oracle. The additional commands were `python3 -B tests/runtime/extent-v3-production-source-test.py -v` (19/19) and `python3 -B tests/runtime/rootless-workflow-contract-test.py -v` (32/32), both exit 0.

The deterministic oracle used seed `0x0d3a5eed`, 400 windows and 13,279 generated records plus duplicate/failure cases. The production target source-contract suite passed 19/19 and the workflow contract suite passed 32/32. Logs and compile/run exit codes are in `rootless/` and `rootless-summary.tsv` in the local evidence directory.

Commands were direct `cc`/`clang` builds of each `tests/runtime/extent-v3-*.c` against the exact `kernel/extent-v3/{codec,authority,engine}.c`, with the stated sanitizer/optimization flags, followed by each resulting binary. No test was weakened or skipped.

## Source review and live flush/FUA

The alpha.5 paths inspected included `sv3_issue_flush`, `sv3_process`, `sv3_map`, `sv3_worker`, `sv3_drain`, `sv3_gc_choose_victim`, `sv3_gc_compact_one`, and the exact-C engine write path. The review found no new credible memory-safety, lost-BIO, deadlock, or false mapping-publication defect in the inspected changes.

- The target admits valid empty `REQ_OP_WRITE|REQ_PREFLUSH`, not an invalid upper `REQ_OP_FLUSH`; `sv3_process()` drains the earlier write window before invoking the lower flush and completing the upper request (`dm-target.c:974-993`).
- `sv3_issue_flush()` accounts and propagates the `blkdev_issue_flush()` result (`dm-target.c:224-239`).
- Actual 4 KiB upper FUA writes were submitted by the test helper for compressed and raw input. Successful valid empty PREFLUSH and both FUA paths completed once; combined status reached `flush_calls=3 flush_ok=3 flush_err=0 flush_injected=0`.
- The `test_fail_flush_nth=1` synthetic injector returned `-EIO` before lower flush submission for empty PREFLUSH, compressed FUA, raw FUA, and final drain cases. Each recorded `flush_calls=1, flush_ok=0, flush_err=1, flush_injected=1, failed=1, error=-5`; helper completion was exactly once with an error. In the compressed FUA case, the lower data write occurred but mapping publication/upper success did not.
- This is **not** evidence of a device-originated lower flush failure. The null_blk interface used here did not provide safe isolated flush-error injection; that item remains blocked. A successful null_blk flush is target-path evidence, not proof of a physical cache flush command.

## Loaded reserve rotation, data integrity, and capacity failure

All live block tests used a newly owned 40 MiB memory-backed null_blk, `/dev/nullb_swapz3_a5_cb8624b`, major/minor `251:0`, `memory_backed=1`, 512-byte logical block size, `completion_nsec=500000`, `mbps=20`, one queue, depth 64. There were no mounts, swap activation, unrelated holders, or physical backing devices.

Using 1,024 logical pages, each of `gc=0`, `gc=1`, and `gc=2` completed eight role rotations, retained 512 reserve blocks (two 1 MiB segments), completed a foreground write after each rotation and passed complete page-manifest readback. Each policy measured 32,768 GC read bytes / 8 requests and 32,768 GC write bytes / 8 requests in this fixture; aggregate lower traffic was the same across policies (60,858,368 read bytes / 14,858 requests and 39,845,888 write bytes / 9,728 requests). This fixture did not differentiate the selectors.

The full-raw 8,192-page capacity case returned `-ENOSPC` before issuing GC: no victim/rotation, no GC I/O, reserve remained 2,048 blocks. A second full-device case used 256 compressed ~3,535-byte payloads followed by 7,936 raw pages. Its optimistic live-byte bound was below 1 MiB, so GC attempted evacuation: status showed `gc_pages=256`, 1,048,576 GC read bytes and 1,048,576 GC write bytes, 256 requests each, but `gc_victims=0`, `gc_role_rotations=0`, and final write error `-ENOSPC`. Thus the driver did not claim foreground progress or acknowledge the failed write, but the preflight is only a necessary bound: fragmentation can still consume a full 1 MiB relocation and return no progress. The failed target was not read afterward; its mapping was removed ordinarily after open references drained.

## Three-way GC economics

The controlled counterexample held one 3,335-byte compressed survivor in one eligible victim and three 496-byte survivors in another. Actual results:

| Policy | Victim | GC reads | GC writes | All lower reads including helper readback | Full 1,024-page verification |
|---|---:|---:|---:|---:|---|
| `gc=0` count | single large | 4,096 B / 1 req | 4,096 B / 1 req | 8,192 B / 2 req | Pass |
| `gc=1` payload bytes | three small | 12,288 B / 3 req | 4,096 B / 1 req | 16,384 B / 4 req | Pass |
| `gc=2` estimated I/O | single large | 4,096 B / 1 req | 4,096 B / 1 req | 8,192 B / 2 req | Pass |

All policies then completed a foreground write and passed the full logical-page verification. This demonstrates a real win for `gc=2` over `gc=1` in this exact case, not universal superiority. `gc=2` matched `gc=0`; the eight-rotation workload likewise showed equal total traffic among policies. The score in `gc-cost.h:27-50` charges each compressed record an extent-class read estimate plus its body/descriptor bytes. It does not deduplicate records sharing an extent or model destination packing, so actual repeated comparisons remain necessary.

## Online coalescing and matched V2.2 comparison

The frozen V2.2 control was built from `3a89ebbeba21c814dcf724e227b31d38445a3f9a`, kernel blob `a75043d1948e38f8d1ab021c99cdd4571e0f23e9`, module SHA-256 `f7bbe3b7eb3aaf29b3d753ff67555e2aafd11ab857a3c36fe1fad509f54517c0`, vermagic matching the running kernel. V3 and V2.2 were loaded **sequentially**, never together. V2.2 reported `swapz v0.2.2`; V3 reported `swapz3` alpha.5. Both used the same owned null_blk and an O_DIRECT, aligned 16-page write/readback helper with seed 91975, identical logical destinations and exact generated input pages. Each repetition completed 65,536 logical write bytes and 65,536 readback bytes with 16/16 pages byte-verified and no target error. Three repetitions were run for each V2.2/workload pair and for each V3 workload/coalesce setting; target counters were reconciled with independent null_blk statistics for all **60/60** burst repetitions.

The captured LZ4 result sizes were exactly: mixed cluster/alternating, eight 2,200 B and eight 1,599 B records; uniform-50-like, sixteen 2,089 B records; dense-75-like, sixteen 1,032 B records. The following are medians across three repetitions. Lower-device readback was part of this 16-page functional burst, not a cold-read benchmark. Each latency distribution has only 16 samples; the shown p95 (and the helper's p99, which collapses to the upper sample at this size) is underpowered and is not a production p99 estimate.

| Input | Packing setting | Lower writes B / requests | Lower reads B / requests | Writer p95 | Reader p95 |
|---|---|---:|---:|---:|---:|
| Cluster | V2.2 | 61,440 / 14 | 65,536 / 16 | 116 µs | 50 µs |
| Cluster | V3 `coalesce=0` | 65,536 / 16 | 65,536 / 16 | 237 µs | 44 µs |
| Cluster | V3 `coalesce=1` | 32,768 / 8 | 65,536 / 16 | 2.011 ms | 48 µs |
| Cluster | V3 `coalesce=2` | 32,768 / 8 | 65,536 / 16 | 3.106 ms | 39 µs |
| Cluster | V3 `coalesce=4` | 32,768 / 8 | 65,536 / 16 | 4.657 ms | 48 µs |
| Alternating | V2.2 | 57,344 / 14 | 65,536 / 16 | 137 µs | 37 µs |
| Alternating | V3 `coalesce=0` | 65,536 / 16 | 65,536 / 16 | 95 µs | 49 µs |
| Alternating | V3 `coalesce=1` | 36,864 / 9 | 65,536 / 16 | 2.612 ms | 43 µs |
| Alternating | V3 `coalesce=2` | 32,768 / 8 | 65,536 / 16 | 2.730 ms | 46 µs |
| Alternating | V3 `coalesce=4` | 32,768 / 8 | 65,536 / 16 | 4.898 ms | 35 µs |
| Uniform ~50% | V2.2 | 65,536 / 8 | 65,536 / 16 | 948 µs | 64 µs |
| Uniform ~50% | V3 `coalesce=0` | 61,440 / 14 | 73,728 / 18 | 830 µs | 36 µs |
| Uniform ~50% | V3 `coalesce=1` | 40,960 / 4 | 122,880 / 28 | 3.229 ms | 44 µs |
| Uniform ~50% | V3 `coalesce=2` | 40,960 / 4 | 122,880 / 28 | 2.755 ms | 40 µs |
| Uniform ~50% | V3 `coalesce=4` | 40,960 / 4 | 122,880 / 28 | 4.717 ms | 45 µs |
| Dense ~75% | V2.2 | 53,248 / 12 | 65,536 / 16 | 529 µs | 36 µs |
| Dense ~75% | V3 `coalesce=0` | 53,248 / 13 | 65,536 / 16 | 913 µs | 41 µs |
| Dense ~75% | V3 `coalesce=1` | 20,480 / 4 | 81,920 / 20 | 2.144 ms | 55 µs |
| Dense ~75% | V3 `coalesce=2` | 20,480 / 4 | 81,920 / 20 | 3.585 ms | 59 µs |
| Dense ~75% | V3 `coalesce=4` | 20,480 / 4 | 81,920 / 20 | 5.385 ms | 42 µs |

The 1,024-BIO loaded queue/suspend test is a second, larger direct comparison. Each driver accepted 1,024 writes (4 MiB logical), drained, resumed and passed byte-exact readback of all 1,024 pages. The fixture contained 819 compressed and 205 raw pages. V2.2 transferred 1,679,360 lower write bytes in 26 write requests, plus 4,194,304 read bytes in 1,024 requests. V3 transferred 1,716,224 write bytes in 419 target write requests (the backing sysfs delta was 420 write requests, including one additional non-data lower request); reads were the same 4,194,304 bytes / 1,024 requests. Sector bytes reconciled exactly to the target status in both drivers. The V3 default (`gc=2`, `coalesce_ms=0`) therefore used 36,864 B (2.20%) more writes and about 16.1 times as many target write requests in this bounded workload. These are matched completed operations, but no fixed-rate timed load or achieved-IOPS measurement was taken.

The production engine calls its lower `write_extent` callback once per planned extent (`engine.c:173-213`); the callback submits one `dm_io` region (`dm-target.c:241-252`). This is the clearest measured source-level explanation for the large V3 request-count increase compared with V2.2's multi-block stream writes. The online timer changes window occupancy: for example clustered 16-page inputs had a median of 14 singleton windows at `coalesce=0`, versus one 9–16-record window with 14 reordered records at `coalesce=2`; however, it buys this occupancy by delaying completion and may increase read amplification. Histogram counts reconcile for all V3 burst repetitions.

These are small controlled kernel-target bursts and a 1,024-BIO drain test, **not** the requested sustained fio campaign. We did not establish a matched achieved-IOPS comparison, adequately sampled cold-read/write p99, CPU cost, or workload-family coverage (QD1/8/32, hot/cold churn, sustained GC). The overall loaded V2.2-versus-V3 performance verdict is therefore **INCONCLUSIVE**, with a negative default-setting signal and a measured coalescing tradeoff.

## Required decisions

| Area | Verdict | Evidence / limit |
|---|---|---|
| Source safety review | PASS for reviewed alpha.5 paths | No credible new critical defect found; not a release certification. |
| W=1/W=2 builds | PASS | Actual production module; environment-only diagnostics listed above. |
| Exact-C/sanitizer tests | PASS | 207/207 group-runs plus 19 source contracts, 32 workflow contracts and seeded oracle. |
| Loaded PREFLUSH/FUA success | PASS for tested operations | Valid zero-sector PREFLUSH, compressed/raw 4 KiB FUA; exactly-once completion. |
| Loaded synthetic flush error | PASS for propagation | Pre-submission injected `-EIO`; not device-originated. |
| Device-originated lower flush failure | BLOCKED | No safe isolated null_blk flush fault path. |
| Eight GC rotations | PASS | Eight each under `gc=0/1/2`, with foreground write and full readback after cycles. |
| GC full-destination handling | PASS fail-closed; liveness cost observed | `-ENOSPC`, zero role exchanges; one case incurred 2 MiB GC I/O before failure. |
| 1,024-BIO suspend/drain/resume | PASS | `coalesce_ms=0,1,2,4`; 1,024/1,024 completions, no errors, full byte readback. |
| `gc=2` versus `gc=0/1` economy | MIXED / workload-specific | Beats `gc=1` in the measured counterexample; ties `gc=0` there and in rotation fixture. |
| Online coalescing | MIXED | Less write bytes in some bursts, extra reads on two size classes, multi-ms writer p95. |
| Loaded V2.2 comparison | INCONCLUSIVE overall | Direct bounded workloads show more V3 default write requests/bytes; no sustained matched-rate runs. |
| Independent lower I/O accounting | VERIFIED for 60 burst trials and queue cases | 512-byte sector deltas reconcile to target byte counters; writes/read requests reported separately. |
| Physical SD/SSD/HDD qualification | NOT RUN | No physical devices were accessed. A null_blk result does not establish NAND or media endurance. |
| Production readiness | NOT ESTABLISHED | Sustained workload, actual lower-fault, cold-read tail and broader GC qualification remain. |

## Next engineering priority

First investigate lower-write request aggregation: batch adjacent planned extents into fewer lower requests without weakening transaction completion and publication rules. This directly addresses the observed 419-versus-26 request count and slight write-byte regression in the matched 1,024-BIO workload. Then revisit read amplification (especially uniform 2,089-byte records at `read_cap=0`) and test coalescing with a sustained achieved-load curve rather than a 16-write barrier microburst. GC cost scoring should account for shared extents and destination packing, and the expensive full-destination failure should be measured as a liveness/GC-cost boundary, not reported as reclaimed space.

The present evidence does **not** justify physical-media qualification yet. Establish a sustained null_blk I/O frontier and matched read/write/latency results first; do not claim reduced flash wear from these RAM-backed tests.

## Cleanup and evidence integrity

V3 and V2.2 modules were loaded sequentially and removed normally. At final inventory: no DM mappings; `dm_swapz` unloaded; this task's `nullb_swapz3_a5_cb8624b` configfs instance, block device, and temporary udev rule absent. `null_blk` remains loaded at refcount 0 because its prior system ownership was not certain. `/swapfile` and `/dev/sdb1` remained active and no swap-management command was run. The reported `Used` values in `/proc/swaps` varied during the session; these counters are host-wide and cannot attribute automatic background swap I/O to this test or other host activity. Test payload I/O was directed only at the owned null_blk. No reboot occurred. The shared checkout was not changed.

The two protected state files were never opened for writing; their final hashes are:

```text
42edb55a8d096325a1c4118909cf0da6845c4745bbb769e4231861877f1efb61  local-batch-regression-0-verify.state
5810e0aefccd0d464e432afd8de7ba885e5a9f6f8b560beddcb14ba9c82963a3  local-verify-0-verify.state
```

The complete raw evidence directory is retained on the validation host at `/tmp/swapz-v3-alpha5-evidence-cb8624b` (about 56 MiB); `sha256sum -c SHA256SUMS` passed. Manifest SHA-256: `3b2bb729e29d9920c09d9f0ab7bdb610d9f80a14d7372b1dd306572c008cfbfc`. Key files are summarized in the CSVs adjacent to this report. The source-identity log, build logs/modinfo, all 39 exact-C compile/run logs, source/workflow tests, raw before/after `/sys/block/null_blk/stat`, DM status, payload and readback output, flush cases, GC summaries, queue probes, cleanup inventory and 60-run reconciliation are in the bundle.
