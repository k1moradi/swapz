# Codex autonomous validation: swapz on dedicated physical Linux test host

**User authorization update: October 11, 2026.** This replaces the *earlier* restriction against using `/dev/sdb1` and earlier requirements to request case-by-case permission for privileged testing. This does **not** remove device-identity, ownership, active-use, source/module or teardown verification. The sole unconditional machine-operation prohibition is **NO REBOOT**: never run `reboot`, `shutdown -r`, `systemctl reboot`, `kexec`, unattended-upgrades/kernel-install steps that trigger a reboot, or any equivalent restart.

## Mission and responsibilities

**Repository:** https://github.com/k1moradi/swapz  
**Draft research PR:** https://github.com/k1moradi/swapz/pull/37  
**Research branch:** `research/sizeclass-adaptive-extent-benchmark`

You are Codex, the **independent tester**, not the primary kernel developer. **Begin autonomously as soon as this task is started**; no extra user approvals are required for rootless tests, dedicated-host kernel-module tooling, or the specifically authorized test storage described here. You may fix narrow Python/C compile warnings, test-harness issues and clearly bounded safety/test defects on **your own Git branch**, with additional regressions and a draft PR. Do not rewrite the kernel format or claim an unimplemented algorithm was tested.

Verify the current PR #37 head on GitHub and pin the **exact current commit** in every test report; do not silently use a stale SHA. Confirm the source origin and dirty files; record `uname -a`, compiler, fio, liblz4, kernel headers, `git status`, commit hashes and module hashes. Do not merge/force-push.

## Authorized machine and target

The user confirms this is a **dedicated physical Linux development/test machine, not a VM**, and confirms **`/dev/sdb1` is a dedicated SD-card partition authorized for destructive testing**.

Permitted without additional case-by-case approval, provided ownership and active-use preflights pass:

- `sudo`, `modprobe`, `rmmod`, `modinfo`, `insmod`, matching-header builds, `dmsetup`, `fio`, `blockdev`, `lsblk`, `swapon`/`swapoff` on the authorized SD partition, and normal benchmark/diagnostic commands.
- Loading and unloading the **tested, explicitly identified, unused** dm-swapz and test-only modules. Normal teardown of mappings and modules that the task itself created. Use a direct named module path and SHA when available.
- Destructive reads/writes **to verified `/dev/sdb1` only** for a separately checked SD benchmark path; not to the parent `/dev/sdb`, another partition, or an unidentified disk.
- Using independently owned disposable `null_blk` fixtures on this physical host for controlled, existing V2.2 benchmarks.

**Hard preflight for /dev/sdb1** before writing, repartitioning, formatting, swapoff or DM setup: resolve canonical device, kernel major/minor, `lsblk -o NAME,PATH,TYPE,PKNAME,TRAN,SIZE,LOG-SEC,PHY-SEC,FSTYPE,MOUNTPOINTS`, `blkid`, sysfs removable/card identity, `findmnt`, `swapon --show` and `/proc/swaps`, DM dependencies, holders and open references. Preserve logs and demonstrate this is really the user-authorized SD partition. Never infer the device's identity solely from its path; stop hardware phase if identity conflicts or is ambiguous. The previous report said **/dev/sdb1 and /swapfile were active in /proc/swaps at that time**; do not assume that is still true or that inactive now.

If the SD partition is active swap, **you are authorized to deactivate it** when current swap usage, memory headroom and workload quiescence make `swapoff /dev/sdb1` safe. Check `free`, `vmstat`, `/proc/meminfo` and running workload; do not force swapoff into OOM, and never touch `/swapfile` simply to make a benchmark run. If safe deactivation is impossible, skip/block the SD-specific phase and finish independent rootless/null_blk work. Record original configuration and restore swap use after tests when safe and technically possible; do not claim restoration unless verified. Warn that a destructive SD run will overwrite any existing contents of that dedicated partition.

Only use normal, ownership-verified Device Mapper removal and module unloading; if teardown/holder state is uncertain, **quarantine and record** rather than force-removing another owner's device. A dedicated host is not evidence that every mounted partition or mapping is disposable. Do not reboot under any circumstances.

## Phase A — independent research benchmark validation (start immediately)

From a protected checkout:

```sh
python3 -m compileall -q research/sizeclass/bench
python3 -B research/sizeclass/bench/test_model.py -v
python3 -B research/sizeclass/bench/run.py --trace fio50 --operations 1536 --window 16 --working-set 384 --segments 6 --seed 12345
python3 -B research/sizeclass/bench/run.py --trace fio75 --operations 1536 --window 16 --working-set 384 --segments 6 --seed 12345
python3 -B research/sizeclass/bench/run.py --trace hotcold --operations 3072 --window 16 --working-set 256 --segments 4 --seed 12345
python3 -B research/sizeclass/bench/run.py --trace fio50 --operations 1536 --window 32 --working-set 384 --segments 8 --seed 12345
```

Retain exact JSON/exit codes and verify same trace, window boundaries, capacity, reserve, read seed and completed logical bytes for every packing policy. The runner deliberately exits `2` for noncomparable cases. Audit CRC32 vs CRC32C, payload readback, offsets, raw fallback, finite 1 MiB segments, GC liveness, relocation bytes, failed/torn writes, 64 descriptor slots, repeated-generation races and error paths. Add adversarial W8/W16/W32 and mixed hot/cold stress tests. No invented physical-I/O or p99 claims.

## Phase B — allowed privileged test of the **existing V2.2 kernel**

This is a **baseline/diagnostic**, not a benchmark of PR #37's adaptive algorithm: PR #37 currently contains only Python research code. Check source `kernel/dm-swapz.c` and its exact SHA before compiling. May use `sudo` to compile, inspect, insert and remove a freshly built test-only module on the real host; preserve actual command results and `dmesg` differences. Run the existing guarded V2.2 `tests/runtime/streaming-benchmark.sh --run-live` **only with its supported disposable backends** and explicit source/module/host preflights, using the verified pinned version (PR #31 accounting baseline). Compare 50% and 75% compressibility, including 500 reader IOPS requested vs achieved, read p50/p95/p99, CRC32C and exact lower-device physical bytes including GC. Do not use unmatched reader achieved rates as evidence of p99 improvement. Keep module/DM ownership and normal teardown guarantees; the physical host does **not** change these source rules.

Existing `streaming-benchmark.sh` only supports `SWAPZ_BENCH_BACKEND=null_blk|nbd`; **do not pass `/dev/sdb1` as its backend, rename an SD device as `null_blk`, or bypass its backend/preflight checks**.

## Phase C — direct SD-card physical benchmarking where supported

The real SD card is now **authorized hardware** for this project. First independently determine whether a vetted SD-specific DM/fio benchmark harness exists. If none exists, prepare an **isolated, reviewable, safety-guarded SD-test harness**, with rootless preflight tests and explicit device identity, active-use, media geometry, write bounds, ownership and teardown; keep the validated null_blk runner unchanged. Narrow benchmark-harness fixes are allowed, but do not run a hastily adapted unsafe runner simply because the device is available.

Once the SD path is validated and /dev/sdb1 is idle and exclusively owned, run a bounded existing-V2.2 baseline on /dev/sdb1 with the same 50%/75% workload definitions, matched reader pressure, fio CRC32C verification, pre/post drain counters, lower-device sysfs writes, SD device health/log evidence where available, and complete readback. Report host-visible writes, not true NAND program/wear bytes. Retain exact evidence, restore original SD swap configuration if safe, and verify teardown. If any safety/functional condition fails, do not improvise an unreviewed workaround: record the blocker and continue the safe phases.

**An actual adaptive 8/16 KiB kernel benchmark is not possible from PR #37 as it stands.** Do not claim Python model comparisons measure actual SD throughput or latency. A new *main-developer-reviewed* kernel implementation covering multi-block format, read/write mapping, BIO ownership, CRC32C, GC relocation and failure handling is required before loading an adaptive build. You may identify code-level issues and propose targeted patches, but substantial new kernel implementation remains the main developer's responsibility.

## Fixes, evidence and completion

You may autonomously correct minor compiler warnings/errors, narrow harness problems and independently proven regression defects. Use isolated branches, source tests and draft PRs, not ZIP bundles. Never weaken ownership checks or tests merely to pass. Do not merge or reboot.

Post a reproducible report to draft PR #37 and link Issue #34 with: tested branch+SHA, device identity/partition before/after, active-swap state and memory checks, host/compiler/kernel/module SHA, exact commands and status, GitHub/local test runs, synthetic vs null_blk vs SD results, fio logical bytes, actual physical bytes (foreground and relocation separately where available), payload integrity, achieved reader load and p99, teardown/restoration status, and clear blockers for adaptive kernel measurement. Report partial success honestly.

**Start the task automatically when the agent is launched.** A GitHub issue/PR/task file by itself does not spawn a Codex agent.
