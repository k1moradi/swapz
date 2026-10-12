# Independent swapz V3.0.0-alpha.4 validation

**Date:** 2026-10-12
**Repository:** `k1moradi/swapz`
**Implementation PR:** [#50](https://github.com/k1moradi/swapz/pull/50)
**Exact tested source:** `57eccebd6138831074e69ffc0179ae82831e2d60`
**Version/target:** V3.0.0-alpha.4 / `swapz3`
**Host:** `Inspiron1564Linux`, Ubuntu 26.04.1, `7.0.0-38-generic`

## Result

The alpha.4 rotating-reserve correction **passes the loaded 32 MiB null_blk reclaim-progress reproduction**. Eight role rotations completed, each reclaimed foreground-usable space, retained two reserve segments, accepted an immediate foreground write and preserved all 1,024 logical pages under full-image byte verification.

A separate deliberately overfull destination failed closed with `ENOSPC` and did not report a role rotation. Injected read/write and payload-corruption failures also failed closed; the partial raw-relocation test confirmed that a successfully copied prefix remained physically intact and the failed second destination block was unchanged.

This is **prototype correctness evidence on null_blk**, not a performance qualification or production-readiness result. Performance testing was held because an actual upper `REQ_OP_FLUSH` probe completed with `-EOPNOTSUPP`, and lower flush-error propagation was not exercised. FUA and PREFLUSH success paths did complete in the bounded tests. No matched V2.2 test or physical-media test was run.

## Source and environment identity

The protected validation worktree was clean at the tested source commit. PR #50 remained open and draft at that exact head. Its exact-head workflows passed:

- [Experimental V3 aligned extent codec: build and exact-C sanitizer tests](https://github.com/k1moradi/swapz/actions/runs/38291108352)
- [Rootless teardown safety](https://github.com/k1moradi/swapz/actions/runs/38291108371)
- [Combined source qualification](https://github.com/k1moradi/swapz/actions/runs/38291108425)

Production source blob identities:

| File | Git blob |
|---|---|
| `kernel/extent-v3/dm-target.c` | `a14e9fe3901cc284fa6617774b7b9932aa771a15` |
| `kernel/extent-v3/authority.c` | `188485298a456ab1b6fc0005542cae3f9c2c3088` |
| `kernel/extent-v3/authority.h` | `9adb78c28538587ede9369a2ddbdfb7b31540e57` |
| `kernel/extent-v3/engine.c` | `05a2c7184aabf7b05a3c6e4f57028dbeb0ca1c47` |
| `kernel/extent-v3/codec.c` | `f88d2697a5c15aa068ddd5d7853a5c38af397810` |
| `kernel/extent-v3/gc-cost.h` | `58a3bbbdda4a37c986c4fe79597b0281e2dc0f78` |
| `kernel/extent-v3/Makefile` | `be0bb1a01287069c97c6459e016d8f010bb47e74` |

Host toolchain: GCC `15.2.0`, Clang `23.1.3`, fio `3.41`, liblz4 `1.10.0`; the `lz4` command-line utility is absent. Matching headers are `/lib/modules/7.0.0-38-generic/build` -> `linux-headers-7.0.0-38-generic`.

## Build and module identity

Both builds used the exact PR #50 source and running-kernel headers:

```sh
make -C kernel/extent-v3 KDIR=/lib/modules/$(uname -r)/build clean
make -C kernel/extent-v3 KDIR=/lib/modules/$(uname -r)/build W=1 -j2 all
make -C kernel/extent-v3 KDIR=/lib/modules/$(uname -r)/build clean
make -C kernel/extent-v3 KDIR=/lib/modules/$(uname -r)/build W=2 -j2 all
```

Both returned exit code 0. No kernel C source warnings were emitted. Environment messages were:

- GCC executable identity differs (`gcc` vs `x86_64-linux-gnu-gcc`) although both are Ubuntu GCC 15.2.0.
- Local `pahole` reports version 0 while the kernel build records 131.
- BTF generation was skipped because the matching `vmlinux` is unavailable.

The W=1 artifact SHA-256 was `c32d41f9ab3a3a7818450a09fb4eb34fddf0d35de8e7aaf0d7d1c601122c4851`. The W=2 artifact SHA-256 was `29ddc4bf44e7d82a54b078c40f3868ddf340391d2032e666a1337033b7fb077c`. The module loaded for the live tests was the latter exact artifact. `modinfo` on that file reports module name `dm_swapz`, alias `dm-swapz3`, srcversion `EC9D57DEFA5CE61B357B177`, and vermagic `7.0.0-38-generic SMP preempt mod_unload modversions`. The filename is `dm-swapz.ko`; V2.2 was not loaded.

## Rootless qualification

- GCC `-O1 -Wall -Wextra -Werror -fsanitize=address,undefined`: **63 exact-C test groups passed**, plus the production-source Python suite **17/17**.
- Clang `-O0`: same **63 exact-C groups passed**.
- Clang `-O2`: same **63 exact-C groups passed**.
- The seeded randomized engine oracle passed at all three compiler configurations: seed `0x0d3a5eed`, 400 windows and 13,279 generated records per run, plus duplicate/fault cases.
- `rootless-workflow-contract-test.py -v`: **32/32 passed**.
- `git diff --check`: passed; no production or test source was modified for this report.

The 63 C groups comprise codec 8, authority 10, immutable transaction snapshots 4, write verification 7, dead-segment reuse 4, raw/discard authority 7, engine 9, GC-forbidden segment selection 3, GC-cost selection 3, GC rotation 6, and engine/GC rotation 2. The randomized oracle reports windows/records separately and is not counted as an additional group.

## Independent source review

The reviewed role logic is consistent with the intended handoff:

- `sv3_gc_choose_victim()` validates mapped block/cost bounds and score overflow, skips empty or reserve-role segments, and excludes the paused OPEN segment (`dm-target.c:440-491`).
- `sv3_pick_dead_segment()` selects one wholly dead reserve destination in rotating mode and excludes both the paused OPEN segment and active victim (`authority.c:65-146`).
- `sv3_gc_compact_one()` stages and verifies relocated data, rescans mappings and live-record references, then calls the role commit; any failure restores the old allocation cursor and clears in-progress GC ownership without swapping roles (`dm-target.c:493-630`).
- `sv3_gc_commit_rotation()` rejects an invalid or fully consumed destination before changing role bits (`authority.c:183-263`).
- `sv3_worker()` has a finite 64-BIO normal quantum, flushes pending batches before requeue, preserves FIFO, and drains all accepted work once admission is closed (`dm-target.c:977-1032`). `sv3_drain()` closes admission under the queue lock, expedites delayed work and drains chained executions before checking for residual accepted BIOs (`dm-target.c:1095-1133`).

No additional credible memory-safety, reference-lifetime or data-corruption defect was found in the reviewed paths. The observed standalone flush result below remains an unresolved I/O-contract defect or compatibility issue and must be explained before broader performance qualification.

## Loaded GC progress and role rotation

Backing was a new test-owned configfs `null_blk` instance `nullb_swapz3_a4_57eccebd`, `/dev/nullb_swapz3_a4_57eccebd`, major:minor `251:0`, size `65,536` 512-byte sectors (32 MiB), `memory_backed=1`, block size 512, 500,000 ns configured completion delay, and 20 MiB/s configured limit. It had no mount, swap use, or unexpected holder. The primary target UUID was `SWAPZ3-A4-GC-57ECCEBD`, with 1,024 logical pages and `gc=1`.

The eight successful victim-to-destination handoffs were:

`1→30, 0→1, 30→0, 1→30, 0→1, 30→0, 1→30, 0→1`.

For every rotation, the harness checked victim and destination identity against its role model, `gc_victims` and `gc_role_rotations` increments, foreground cursor inside the new destination, reserve equal to 512 blocks (two 1 MiB segments), no failed/error status, a successful foreground write, and full independent verification of all 1,024 pages after the trigger and after refill. Final status: `gc_victims=8`, `gc_role_rotations=8`, `gc_pages=8`, `gc_read=32768`, `gc_write=32768`, `gc_read_reqs=8`, `gc_write_reqs=8`, `reserve=512`, `failed=0`, `error=0`. The final full-image verifier returned `errors=0 result=PASS`.

Per-trigger lower-device sectors converted at 512 bytes matched the target physical read/write byte counters; requests were recorded separately. Each rotation relocated one 4 KiB survivor and then performed the pending foreground write. This establishes progress and accounting for this deterministic reproduction, not sustained throughput.

### Full-reserve-destination negative case

A separate dense fixture used 6,400 logical pages on the same 32 MiB backing and filled one reserve destination with 256 raw survivors (1 MiB). The subsequent trigger returned `errno=28 (ENOSPC)`. Status showed `gc_pages=256`, `gc_read=1,048,576`, `gc_write=1,048,576`, `gc_victims=0`, `gc_role_rotations=0`, `reserve=1600`, `failed=1`, `error=-28`. Thus the destination was fully written but the target did not announce a role exchange or foreground progress. Full logical readback had passed before this deliberately failing trigger; after the target failed, no logical read through the failed target was counted as successful. The mapping was removed ordinarily by its owned identity.

## Loaded functional and fault tests

- Initially unwritten pages returned zero.
- A clustered mixed compressed batch roundtripped byte-for-byte; status showed `window_records=16`, `reordered=15`, 65,536 logical bytes and 32,768 physical write bytes (8 lower 4 KiB write requests) in that bounded functional case.
- Raw/compressed overwrite transitions, repeated same-slot overwrites, shared-extent discard, neighboring-page preservation, discard-to-zero behavior, and full 1,024-page readbacks passed.
- Raw GC relocation passed: victim 0 to destination 30, one 4 KiB live raw page relocated, full 1,024-page verification passed after GC and a subsequent foreground write, reserve remained 512 blocks.
- Source-read, destination-write, raw CRC and compressed CRC faults caused the target to fail closed. Corrupt payload reads returned `-EBADMSG`; injected lower I/O errors propagated rather than being acknowledged as successful writes.
- A controlled partial raw-GC relocation moved one record to destination block 7680, then failed the next lower write at sectors 61448–61455. The trigger returned `EIO`; `gc_victims=0`, `gc_role_rotations=0`, `reserve=512`, and zero logical bytes from the failed trigger were acknowledged. Physical snapshot checks confirmed the first moved page matched its expected bytes at both source block 254 and destination block 7680, the second page remained intact at source block 255, and failed destination block 7681 was unchanged. Because the target failed closed, no subsequent logical read through it was claimed.

## GC byte-cost policy: scoped result, not a performance winner

A matched single-run victim-choice test used the same input seeds, logical mappings and 32 MiB `null_blk` fixture for `gc=0` (record-count) and `gc=1` (live-byte-cost). Both completed the foreground write after GC and passed full 1,024-page verification.

| Policy | Selected victim | Survivors | Estimated selected cost | Actual GC lower read | Actual GC lower write | GC requests R/W |
|---|---:|---:|---:|---:|---:|---:|
| `gc=0` count | segment 0 | 1 × 3,335 B compressed | 3,351 B | 4,096 B | 4,096 B | 1 / 1 |
| `gc=1` bytes | segment 1 | 3 × 496 B compressed | 1,536 B | 12,288 B | 4,096 B | 3 / 1 |

In this intentionally constructed disagreement, the byte score chose the lower estimated payload cost but caused **3× GC read bytes and requests**, and **2× total GC transfer bytes** (16 KiB vs 8 KiB). The copied output occupied one 4 KiB block under both policies. Outside GC, lower-read interval deltas included 53,248 bytes/13 requests of helper/verification activity; those were kept separate as non-GC traffic. Target physical counters reconciled with null_blk sysfs byte/request deltas for both runs. This single case is a workload-specific counterexample to equating estimated compressed payload bytes with actual GC I/O cost; it does not establish a universal policy ranking.

## Suspend/resume, coalescing, FUA and flush

A test-only kernel helper submitted exactly 1,024 upper write BIOs to a 1,024-page target, suspended while work was pending, resumed, waited for each callback exactly once, then verified the complete 4 MiB image byte-for-byte. This was repeated at `coalesce_ms=0,1,2,4`. All cases had the same target counters: 4,194,304 logical write bytes; 1,716,224 completed physical write bytes; 419 physical write requests; 819 compressed and 205 raw pages; 214 windows and 819 window records; `win1=6`, `win2=6`, `win3_4=202`, other bins zero; `one_page_windows=6`; `failed=0`. `coalesce_deferred` was 0 at 0 ms and 1 at 1/2/4 ms. The readback SHA-256 was identical for all four cases: `41426178c19fc6f64d7b23439ac02b3c9ca36231c8123371236e6b351952b5d8`. This batch test demonstrated no coalescing-window improvement; it is not a timed performance comparison.

Actual upper `REQ_FUA` compressed and raw writes completed once with status 0. A zero-length `REQ_PREFLUSH|WRITE` following a write also completed once with status 0. Block tracing showed lower flush requests in the success path. An injected lower write failure at sector 800 returned `EIO` exactly once to both upper BIOs in a two-record window; the failed destination block remained unchanged and the failed window acknowledged zero logical bytes.

**Unresolved flush gate:** a helper submitted a genuine upper `REQ_OP_FLUSH` BIO to the loaded target. It completed once with status `-95` (`-EOPNOTSUPP`) and the helper module init returned `-95`. The target constructor sets `num_flush_bios=1` and `flush_supported=true` (`dm-target.c:1335-1338`), and the process switch calls `blkdev_issue_flush()` for `REQ_OP_FLUSH` (`dm-target.c:956-960`); successful FUA/PREFLUSH paths were separately observed. The evidence does not establish whether this result is target dispatch, backing support or another DM interaction. Lower flush-error propagation was not injected. This must be diagnosed before treating flush correctness as passed or beginning the larger benchmark matrix.

## Kernel log and cleanup

The dmesg review found no `WARNING`, `BUG`, Oops, lockdep, hung-task, soft/hard lockup or workqueue CPU-hog message associated with this run. It contains expected `null_blk` I/O errors and target failure notices from the deliberate ENOSPC, EIO and CRC corruption tests; these are retained in the raw evidence.

All test-owned DM targets were ordinarily removed by exact identity. Final inventory showed no DM mappings, no `swapz3` target registration and no loaded `dm_swapz`. The owned configfs `null_blk` instance was powered off and removed after confirming no holders, mount or swap ownership. The generic `null_blk` module remains loaded at refcount zero; it was not unloaded because its wider host ownership was not needed for this test. `/proc/swaps` still lists only `/swapfile` and `/dev/sdb1`; neither was opened or modified by this validation. No reboot occurred. The shared checkout remains on its previous commit with the two pre-existing protected `.state` files untouched; final SHA-256 values are in `protected-state-final.sha256`.

The first cleanup attempt returned exit 20 because a guard matched dmsetup's informational text `No devices found`; it made no changes. The corrected explicit target-row guard then completed ordinary V3 module unload and owned null_blk cleanup successfully. Both command logs are preserved.

## Verdicts and next step

| Qualification | Verdict |
|---|---|
| Independent source safety review | PASS for the reviewed paths; no new critical defect identified |
| W=1 / W=2 module builds | PASS; environment warnings only |
| GCC ASan/UBSan exact-C regressions | PASS (63 groups); production-source Python tests 17/17 |
| Clang exact-C regressions | PASS at O0 and O2 (63 groups each) |
| Rootless workflow contracts | PASS (32/32); exact-head CI 3/3 green |
| Exact module / DM identity | PASS for the loaded run; exact SHA and UUID recorded |
| Loaded compressed/raw functional paths | PASS for the cases above; not exhaustive workload qualification |
| Loaded rotating GC progress, eight handoffs | PASS on the 32 MiB null_blk reproduction |
| Foreground write after each handoff | PASS |
| Full-destination fail-closed behavior | PASS for the dense negative reproduction; target failed with ENOSPC without a role rotation |
| Partial relocation failure / no false acknowledgement | PASS for the tested raw two-record prefix case |
| 1,024-BIO suspend/resume | PASS at 0/1/2/4 ms in one deterministic run per setting |
| Explicit FUA and PREFLUSH | PASS in bounded success cases; lower write-error propagation PASS |
| Standalone `REQ_OP_FLUSH` | FAIL / unresolved: observed upper completion `-EOPNOTSUPP` |
| Lower flush-error injection | UNVERIFIED |
| Coalescing 0/1/2/4 performance | INCONCLUSIVE; identical batch counters and singleton windows in the functional queue test |
| Count-based vs byte-cost GC economics | MIXED; byte heuristic doubled actual GC read bytes in the constructed disagreement case |
| Independent lower-device accounting | VERIFIED for the measured rotation and policy windows; request counts kept separate from bytes |
| Matched loaded V2.2 comparison | BLOCKED; not run |
| SD/SSD/HDD qualification | NOT RUN; alpha.4 remains null_blk-only |
| Production readiness | NOT ESTABLISHED |

**Recommendation:** keep alpha.4 as a validated reclaim-progress correction on `null_blk`, but hold sustained performance qualification. First diagnose the standalone upper flush `-EOPNOTSUPP` and verify lower flush-error behavior with a safe owned-device fault mechanism. Then rerun the bounded barrier cases. After that, use repeated matched workloads to test coalescing and GC policy; the single GC-cost disagreement already shows why the byte estimator must be compared against actual read/write request and byte totals.

## Evidence

The complete raw run evidence, including all command outputs, helper sources, readbacks, raw lower stats, fault records, and tracing data, is retained at:

`/tmp/swapz-v3-alpha4-evidence-57eccebd`

`SHA256SUMS` at that directory root covers the complete raw evidence tree. A compressed archive and its SHA-256 are recorded in the validation PR after generation. A concise, text-only evidence subset is committed beside this report. The 32 MiB backing-image snapshot is retained locally and is not included in the public commit.
