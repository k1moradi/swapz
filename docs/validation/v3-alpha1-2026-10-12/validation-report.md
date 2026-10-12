# Independent V3.0.0-alpha.1 loaded-kernel validation

**Date:** 2026-10-12
**Repository:** `k1moradi/swapz`
**Primary source:** PR #45, `dbad94ffbc9a372caabc9e3a01fe225e84de2869`
**Validation branch:** `codex/pr45-live-nullblk-validation`
**Scope:** exact-source C validation, native module build, and owned memory-backed `null_blk` Device Mapper tests. No physical backing or active swap was used.

## Executive result

The exact PR #45 target built and ran as a real loaded Device Mapper target on a newly created, memory-backed `null_blk` device. Compressed and raw pages round-tripped, overwrite and discard transitions passed, all 64 pages in the mixed-size AIO phases read back exactly, live GC completed two segment-reuse cycles for both compressed and raw workloads, and independent lower-device sector/request deltas reconciled with the target counters during healthy runs.

An injected lower write error during GC failed the target closed. The previous compressed page-0 extent remained physically present with valid metadata and payload CRCs; the failed target correctly rejected later logical I/O. The old mapping therefore has direct physical preservation evidence and exact-C authority-test coverage, but could not be read through the already-failed target. This is not represented as a successful post-failure logical read.

This establishes a **loaded `null_blk` functional and bounded-I/O result**, not production readiness or a V2.2 performance win. A kernel workqueue CPU-hog warning occurred during the concurrent reader/writer experiment. The target's status string and module description also incorrectly say `alpha-no-gc` / `GC disabled` while this source performs live GC and reports nonzero GC counters; the loaded behavior was correct, but the metadata is misleading.

## Exact source, module and host identity

PR #45 remained open and at the expected head when rechecked. The branch head was `dbad94ffbc9a372caabc9e3a01fe225e84de2869`; no uncommitted kernel source was used.

| File | Git blob SHA |
|---|---|
| `kernel/extent-v3/dm-target.c` | `ec240a8275fba09ff548cc2b61e8f18501bee14c` |
| `kernel/extent-v3/codec.c` | `f88d2697a5c15aa068ddd5d7853a5c38af397810` |
| `kernel/extent-v3/authority.c` | `7a7c34e96be791cae8aa89e9aa174f6e08fdd439` |
| `kernel/extent-v3/engine.c` | `38a509604bf1b86e5db6c97c06a2f20784bcc52e` |
| `kernel/extent-v3/Makefile` | `61c8b8fc0d8fc291d86c7ea945848fe2d39ed1b1` |

Host: Ubuntu 26.04, `Inspiron1564Linux`, x86_64, kernel `7.0.0-38-generic #38-Ubuntu`; GCC 15.2.0, Clang 23.1.3, fio 3.41, liblz4 1.10.0. The module was built against `/lib/modules/7.0.0-38-generic/build`.

Selected module identity:

- Name/target: `dm_swapz3` / `swapz3`
- Version: `3.0.0-alpha.1`
- Vermagic: `7.0.0-38-generic SMP preempt mod_unload modversions`
- `srcversion`: `50BC54709AD1175693DFBA4`
- SHA-256: `b5419cf055d52b73c04135f546f96c72e2be886e40c9ea7fd2930cff358b2f64`

The live backing was only the owned configfs `null_blk` instance `nullb_swapz3_codex_20261012_01`, major/minor `251:0`, 8 MiB, `memory_backed=1`, 4 KiB logical blocks. Its target table exposed 4 MiB / 1,024 logical pages and 2,048 physical 4 KiB blocks. The module and target were loaded from this exact validation worktree and normally unloaded/removed afterward.

The active swap entries remained `/swapfile` and `/dev/sdb1`; neither was used as a test target and no swap activation/deactivation command was run. The two protected `.state` hashes remained `42edb55a…f1efb61` and `5810e0ae…82963a3`. No reboot command was issued.

## CI, rootless tests and native build

The exact PR #45 source commit had three successful workflows:

- [Combined source qualification](https://github.com/k1moradi/swapz/actions/runs/38237178923)
- [V3 exact-C and module compile](https://github.com/k1moradi/swapz/actions/runs/38237178867)
- [Rootless teardown safety](https://github.com/k1moradi/swapz/actions/runs/38237178891)

On the host, all seven exact-production-C suites passed with GCC `-O1`, ASan and UBSan: codec 8, authority 10, immutable transaction snapshots 4, write verification 7, dead-segment reuse 4, raw/discard authority 5, engine 8 (**46 test groups total**). The production-source suite passed 8/8 and the workflow-contract suite passed 32/32.

I added `tests/runtime/extent-v3-randomized-engine-test.c`, a deterministic oracle-based test that compiles and invokes the exact `engine.c`, `authority.c` and `codec.c`. Seed `0x0d3a5eed` ran 100 windows at each read cap 0–3: **400 windows and 13,279 generated records**, with random sizes from 26 to 3,568 bytes, overwrite/readback oracle checks, duplicate logical IDs split across extents, and a fault in the second extent verifying committed-prefix-only publication and preservation of older mappings. It passed under GCC `-O1` ASan/UBSan, GCC `-O0`, GCC `-O2`, and Clang `-O1` ASan/UBSan.

The seven existing exact-C suites also passed with GCC `-O0`, GCC `-O2`, and Clang `-O1` ASan/UBSan. The new randomized suite passed under the same three variants. The final rootless rerun logs and compiler-variant command/output records are included in this directory. One initial randomized variant invocation was launched from outside the worktree, so its relative include path failed; rerunning all variants with the worktree as `cwd` passed. This was a test invocation error, not a source failure.

Native module builds passed with exit code 0 for `make -C kernel/extent-v3 KDIR=/lib/modules/$(uname -r)/build W=1 -j2 all`, the same command at `W=2`, and a final `W=1` rebuild. There were no kernel C-source warnings. `modinfo` and SHA-256 were taken from the final `dm-swapz3.ko`. Environment diagnostics were:

- Compiler executable name differs from the kernel build name (`gcc` versus `x86_64-linux-gnu-gcc`), while both are GCC 15.2.0 from the same Ubuntu package version.
- Kernel headers recorded pahole 131, while Kbuild detected local pahole version 0 (unavailable).
- BTF generation was skipped because the matching `vmlinux` was unavailable.

## Live functional and packing results

The loaded-target smoke verified zero reads from unwritten pages; actual kernel LZ4 compression/decompression; highly compressible, ~50%-like, ~75%-like, and incompressible raw-fallback inputs; 32 repeated overwrites of one page; compressed/raw transitions; discard of a page with zero-on-read behavior; preservation of its neighbor; and `fdatasync` drain. The raw random page produced LZ4 output length 0, used raw fallback, and read back byte-exactly.

The 16-page arrival-pattern test submitted four flush-bounded phases with the same logical IDs, payloads and seed for each phase. The target reported four write windows and 17 reordered records on the reconciled run. The physical extent parser independently checked metadata CRC, payload CRCs, descriptors, class alignment and exact page readback:

| Phase (16 pages) | Actual LZ4 lengths | Loaded V3 extents | Lower 4 KiB units |
|---|---:|---:|---:|
| Clustered, 8 large then 8 small | 8 × 2,224 B; 8 × 1,623 B | eight 4 KiB extents, two records each | 8 |
| Alternating large/small | same mixed populations | eight 4 KiB extents, two records each | 8 |
| Uniform 50%-like | 16 × 2,082 B | three 8 KiB plus one 16 KiB extent | 10 |
| Uniform 75%-like | 16 × 1,055 B | three 4 KiB plus one 8 KiB extent | 5 |

All 64 output pages matched their expected bytes. The status window/reorder counters demonstrate that this was actual loaded-target repacking, not a Python geometry model. One read-budget run split the same four flush phases into five windows and had a slightly different physical count; this timing sensitivity is recorded in the raw status snapshots.

For the 64-page mixed test, the healthy write window was 262,144 logical bytes and 126,976 lower bytes (31 4 KiB-equivalent units in 24 requests); target and null_blk sysfs byte/request deltas agreed. Thus the loaded V3 number is measured. For comparison only, an ordered 4 KiB-container geometry calculation would require 12+8+16+5=41 units for these four phases. That calculated baseline is **not** a loaded V2.2 control measurement, so it does not establish a V3-vs-V2.2 win.

## Read-budget experiment

For each budget, 64 mixed compressed writes were drained, followed by 3,200 successful, direct 4 KiB page reads per repetition with exact comparison and per-read latency capture. Physical reads and writes came from the actual target status and the uniquely owned lower null_blk sysfs counters; they reconciled in every healthy run. A physical 4 KiB-equivalent unit is `lower bytes / 4096`; lower request count is shown separately.

| Max lower blocks/record | Write units / requests for 64 pages | Logical/physical write ratio | Read units / 3,200 reads | Read amplification | Median p50 / p95 / p99 (µs) | Read reps |
|---:|---:|---:|---:|---:|---:|
| 0 | 31 / 24 | 2.065× | 4,100 / 4,000 | 1.2813 | 34.55 / 43.35 / 56.60 | 2 |
| 1 | 38 / 38 | 1.684× | 3,200 / 3,200 | 1.0000 | 26.61 / 36.64 / 43.59 | 3 |
| 2 | 32 / 26 | 2.000× | 3,900 / 3,900 | 1.2188 | 26.83 / 33.89 / 42.04 | 3 |
| 3 | 31–32 / 24–25 | 2.000–2.065× | 4,100 / 4,000 | 1.2813 | 26.86 / 36.25 / 45.44 | 3 |

Latency is software completion time against `null_blk` on this host, not an SD/SSD/HDD latency prediction. p99 sample counts were 3,200 each; budget 0 has only two latency repetitions. The measurements show the intended write/read tradeoff: read cap 1 eliminated multi-block page reads in these runs but increased write transfer units to 38. Budget 0 used fewer writes but read 1.28 backing blocks per logical page. The cap-3 first run occupied five rather than four worker windows and wrote one extra block; keep this as evidence of occupancy sensitivity rather than treating the single best result as representative.

## GC, concurrency, barriers and failure injection

The bounded GC test used 1,024 logical pages and verified the full 4 MiB logical image after each of five phases. Both compressed and raw workloads completed two segment turnovers and reused two fully dead segments:

| Workload | Logical writes | Total lower writes | GC writes | Total lower reads | GC reads | Victims / pages | End state |
|---|---:|---:|---:|---:|---:|---:|---|
| Compressed | 7,344,128 B | 7,639,040 B (1,865 units; 1,825 requests) | 294,912 B (72 units) | 23,515,136 B (5,741 units; 5,725 requests) | 1,048,576 B | 2 / 256 | `failed=0`, 2 dead-segment reuses |
| Raw fallback | 7,344,128 B | 8,392,704 B (2,049 units; 2,049 requests) | 1,048,576 B (256 units) | 22,142,976 B (5,406 units; 5,406 requests) | 1,048,576 B | 2 / 256 | `failed=0`, 2 dead-segment reuses |

These churn workloads have **write amplification**, not a write-reduction result: total lower writes were 1.040× logical bytes compressed and 1.143× raw. GC reads and writes are included, and lower sysfs deltas exactly matched target counters. No claim of write savings is made from these GC runs.

A concurrent disjoint fio test completed 145,652 reads (596,590,592 B, 48,534 achieved IOPS) and 64 direct writes plus 64 verification reads with no job errors. Reader p50/p95/p99 were 64.3/114.2/191.5 µs; writer p99 was 831.5 µs. The pre/post reader-region hashes matched. This was a short synthetic null_blk concurrency check, not a comparative latency benchmark.

Ordinary `dmsetup suspend` and `resume` both returned 0; all 64 post-resume page reads were exact. Their p99 was 94.7 µs. The run verified flush/drain behavior; no explicit upper FUA BIO was issued, so loaded FUA behavior remains unverified. Source/contract FUA tests passed.

For a foreground partial-window failure, 16 compressed page writes were submitted. Three upper writes completed successfully, 13 returned EIO, and the worker completed all 16 BIOs. Status recorded 12,288 logical bytes, one completed 8 KiB extent, `failed=1`, `error=-5`, with no false success for the uncommitted tail. The test-owned null_blk reported two attempted lower write requests / 32 sectors; the second was deliberately partial and therefore is not a completed physical extent.

For GC fault injection, a bad block was set only on the test-owned null_blk at segment 6's first block (sector 12,288; sectors 12,288–12,295), with partial-I/O mode enabled on that owned instance. The first GC relocation write failed with EIO. The target reported `failed=1`, `error=-5`, `gc_victims=0`, and rejected subsequent logical I/O. The prior page-0 compressed extent at physical block 1,024, generation 2, remained directly readable from the lower test device and passed metadata CRC, payload CRC and SHA-256 `18364c3c75a3c8981be0437b4c7b602b3b79e19a9807aa3e74d6a72786ab763d`. Because the target fail-stops, a logical read through that target after failure is expected to fail; rootless authority tests independently verify that the previous mapping remains authoritative on failed publication.

Foreground lower write error, raw write error, corrupted payload CRC, and lower read error cases also returned errors and did not report false success. Error-path null_blk sysfs write-attempt counters include attempted partial writes whereas V3 `physical_write` counts successful complete extent blocks; this difference was limited to injected failure windows and is documented in the raw snapshots. Healthy windows reconciled exactly.

## Kernel diagnostics and source-review notes

No Oops, BUG, hung-task report or panic appeared. Kernel messages for the deliberately injected bad-block/read/write failures were expected. The unsigned out-of-tree test module produced the standard signature/taint notices; no signature check was bypassed.

The kernel emitted workqueue diagnostics during the concurrent test: `sv3_worker [dm_swapz3] hogged CPU for >10000us`, with cumulative counts reaching 19. This is a real scheduling/performance warning. No workqueue change was made; the main developer should inspect producer/worker occupancy and consider this before performance qualification.

Two reporting strings are inconsistent with the observed implementation: `kernel/extent-v3/dm-target.c:1130` emits `mode=alpha-no-gc`, and line 1189 describes the module as `GC disabled`, while the same source contains `sv3_gc_compact_one()` (line 395), reports GC counters, and the loaded tests observed two live victims and two reuses. Counters themselves matched lower-device statistics. This metadata should be corrected, but it did not invalidate the tested I/O.

The source review found no reproduced memory-safety or mapping-authority defect in the tested paths. The production target serializes requests through one worker, uses per-BIO completion ownership, completes successful writes after full extent lower-I/O completion and validation, preserves the committed prefix on partial window failure, and fail-stops subsequent I/O after target errors. The tests exercise overwrite generation changes, raw/compressed transitions, discard, failure paths, suspend/resume and live GC. This review is bounded to tested source and cases; it is not a proof for arbitrary kernel races or power-loss behavior.

## Required verdicts

| Area | Verdict |
|---|---|
| Production module build | **PASS** — W=1/W=2 against running headers; environment-only compiler/pahole/BTF notes above |
| Rootless regressions | **PASS** — 46 exact-C groups, 8 production source checks, 32 workflow checks, randomized 400-window oracle suite; GCC/Clang variants pass |
| Source safety review | **PASS, bounded** — no reproduced correctness defect; status/module GC labels are inaccurate |
| Exact module/DM identity | **PASS** — exact source/blob and module identities recorded; target mapped only to owned null_blk 251:0 |
| Loaded V3 compressed read/write | **PASS** — byte-exact kernel LZ4 round trips |
| Loaded V3 raw fallback | **PASS** — incompressible 4 KiB input used raw fallback and read back exactly |
| Reordering and extent packing | **PASS** — four-phase physical extent dump and lower counters show actual packing/reordering |
| Flush/FUA and upper BIO completion | **PARTIAL** — flush, fdatasync, suspend/resume and tested completion paths pass; explicit loaded FUA BIO not exercised |
| Live GC relocation and reuse | **PASS for tested workloads** — compressed and raw, two turnovers each, full 1,024-page readback after phases |
| Failed-write mapping safety | **PASS with scope limit** — injected GC failure fail-stops, old extent bytes/CRCs remain intact, rootless authority tests pass; post-failure logical read is unavailable by fail-stop design |
| Suspend, teardown and unload | **PASS** — owned UUID removal, exact null_blk config removal, normal module unload; final inventory empty |
| Physical 4 KiB-equivalent I/O accounting | **VERIFIED on healthy null_blk windows** — status bytes/requests reconcile with independent sysfs counters |
| V3 vs V2.2 null_blk benefit | **INCONCLUSIVE** — no matched loaded V2.2 control run; geometry comparisons are explicitly calculated, not measured controls |
| SD/SSD/HDD qualification | **BLOCKED — null_blk-only admission** |
| Production readiness | **NOT READY** — alpha target, limited workloads, no matched V2.2 run, no physical-media qualification, CPU-hog warning, and explicit FUA remains untested |

## Cleanup and evidence index

The failed target was removed by its exact owned UUID after checking open count zero, no holders and drained status. The injected bad-block range was cleared and partial-I/O mode reset before powering down the owned null_blk. The target, `dm_swapz3`, null_blk configfs instance, block device and module were then removed through ordinary operations; no force/deferred removal was used. Final checks showed no Device Mapper targets, no `dm_swapz3` or `null_blk` module, no null_blk configfs/block/device node, and unchanged active swap entries.

Raw command logs, exact-C outputs, compiler variants, module build logs, raw per-read latency CSVs, status/counter snapshots, extent descriptors, fault-injection evidence, kernel logs and final cleanup inventory are stored beside this report. `SHA256SUMS` covers the committed report and evidence files. The validation branch adds only the deterministic rootless property test, its exact-C CI execution, and this report/evidence; `kernel/` is unchanged.

**Conclusion:** The loaded V3 alpha demonstrates correct compressed/raw readback, real size-class packing, bounded GC reuse and fail-closed behavior on the tested owned null_blk workload. Its measured write/read tradeoff varies materially by read budget, and the concurrency run exposed a workqueue CPU-hog warning. These results justify continued controlled validation and follow-up on warning/metadata accuracy; they do not qualify a V2.2 comparison, a production winner, or any SD/SSD/HDD benefit.
