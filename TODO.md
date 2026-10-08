# swapz TODO\n\nSee `ROADMAP.md` for version boundaries and `VALIDATION.md` for completed evidence.\n\n## Now — V2.2 performance characterization\n\nCorrectness baseline: `v2.2-correctness-pass` @ `0f40f52956ff0b4ffc18549b916a54ce55847c02`.\n\n### Verify permanent harness cleanup\n\n- [x] Pull current `main` (verified at focused retest; recheck for each new campaign).\n- [x] Run `tests/runtime/staged-rewrite-fault.sh` with the checked-in deterministic incompressible replacement.\n- [x] Run `tests/runtime/staged-write-fault.sh` on the host's built-in DM error target.\n- [x] Run `SWAPZ_LONG_STRATEGY=staged tests/runtime/correctness.sh` without temporary edits.\n- [x] Confirm no test-owned DM/loop state remains after PASS.\n\n### Benchmark backend follow-up

- [ ] Treat the 20 MiB/s `null_blk mbps` backend as valid only within its per-tick request budget.
- [x] Run the backend-safe 20 MiB/s sweep through 256 KiB.
- [x] Run a full 4 KiB..1 MiB latency-only sweep with `SWAPZ_BENCH_MBPS=0`.
- [x] Prototype an opt-in size-aware sparse-RAM NBD backend accepting 512 KiB
      and 1 MiB simulated requests; protocol and host validation still required.
- [ ] Execute `size-aware-nbd.py selftest` and both DM teardown mock regressions
      on the Linux test host (no root/devices required).
- [ ] Run a single isolated virtual-NBD smoke test only after checking an
      explicitly selected unused `/dev/nbdN`; verify exact data readback,
      1 MiB lower request size, and safe detach.
- [ ] Calibrate raw virtual-NBD throughput against 20 MiB/s and bound
      Python overhead before using the backend for any batch plateau claim.
- [ ] Re-run the full 20 MiB/s plateau on that backend before declaring the final V2.2 batch
      sweet spot if the safe null_blk sweep is still rising at 256 KiB.

### Synthetic lower-DISCARD GC stall

- [x] Repeat GC churn with throttled null_blk lower DISCARD disabled: 921 victims,
      `failed=0`, no outstanding I/O, clean teardown.
- [x] Check `nullblk-discard-guard.sh` source regression and actual reject-before-setup case (exit 4).
- [x] Verify `lower_discard=off`, repeated GC victims, forward progress, safe teardown.
- [x] Re-test GC with lower DISCARD enabled on **unthrottled** virtual storage: 1,125 victims,
      1,179,648,000 discarded bytes, zero failures and safe teardown.
- [ ] If GC still hangs with discard off, inspect exact swapz worker stack/ownership;
      treat as a kernel forward-progress blocker.

### Teardown safety gate

- [x] Verify teardown safety regression with busy and false-positive DM removal.
- [x] Confirm mock teardown regression preserves powered null_blk when DM removal fails.
- [x] Re-run the 1 and 2 ms backend-safe 20 MiB/s matrices (<=256 KiB).
- [x] Record transient busy removals and verify retry resolves them (29 across 100 completed cases).
- [x] Verify no residual test-owned target, backing, or D-state task.

### Remaining exact-data and performance decisions

- [ ] Reconfirm byte-for-byte live-set correctness in opportunistic and staged modes using
      reference-driven live GC; require `gc_pages>0`, not just `gc_victims>0`.
- [ ] Re-run no-lower-DISCARD live-GC correctness with exact readback. Distinguish this
      reference-model verification from the already-passed long fio GC progress test.
- [ ] Quantify staged cancellation's avoided bytes/I/Os under genuine invalidation or
      overwrite (a read alone does not cancel).
- [ ] Measure live-victim GC read/write amplification, trigger latency and concurrent read p99.
- [ ] Finish bounded real swap pressure at candidate settings and compare reclaim progress.
- [ ] Identify a size-aware synthetic bandwidth backend before asserting a 512 KiB–1 MiB
      plateau on ~20 MiB/s media. No physical device without exact authorization.

### Virtual performance gate\n\n- [x] Run `bench/request-plateau.py --bandwidth 20`.\n- [x] Run default streaming benchmark: 20 MiB/s, 0.5 ms, lower QD1, writer QD64, 50% compressibility.\n- [ ] Sweep 4/8/16/32/64/128/256/512/1024 KiB for opportunistic and staged.\n- [x] Keep immediate 4 KiB as the control.\n- [ ] Repeat at 0.25/0.5/1/2 ms command latency.\n- [x] Test writer QD1/8/32/64 in the safe synthetic matrix.\n- [x] Test 100/50/0% compressibility in the safe synthetic matrix.\n- [ ] Record upper completion and end-to-end drained MiB/s separately.\n- [ ] Record concurrent read avg/p95/p99/max.\n- [ ] Record lower I/Os/sectors, physical write requests, max batch, staged metrics, CPU, and RAM cost.\n- [ ] Identify the throughput/read-latency Pareto frontier.\n- [ ] Select the smallest batch on >=97% drain plateau with read p99 within 10% of the best plateau point.\n- [ ] If 512 -> 1024 KiB is still >3% better with acceptable read latency, report `PLATEAU NOT REACHED`.\n- [ ] Run staged-vs-opportunistic cancellation/churn comparison.\n- [ ] Run GC regression with at least 20 live victims.\n- [ ] Run bounded real swap pressure at candidate opportunistic/staged points.\n- [ ] Select the V2.2 strategy winner and physical-test configuration.\n\n## V2.3 — physical-media qualification\n\n- [ ] Obtain explicit authorization for an exact disposable device/partition.\n- [ ] Confirm it is not root, mounted, or active swap.\n- [ ] Benchmark raw and swapz on the same bounded region.\n- [ ] Start with QD1 and QD8.\n- [ ] Test 100/50/0% compressibility.\n- [ ] Measure logical throughput, physical drain, sectors, I/O count, latency, CPU, and GC.\n- [ ] Test HDD/USB/SD/eMMC/older SATA SSD classes as available.\n- [ ] Record DISCARD behavior and meaningful device health/write counters.\n- [ ] Confirm incompressible QD1 remains near raw.\n- [ ] Choose the shipping strategy/batch default from physical data.\n\n## V2.4 — byte-tight format experiment\n\n- [ ] Do not start until V2.3 data justifies it.\n- [ ] Specify the on-disk record/extent format before coding.\n- [ ] Keep per-page LZ4 and random per-page decode.\n- [ ] Define metadata RAM cost, replacement atomicity, and GC behavior.\n- [ ] Build model tests first.\n- [ ] Re-run full correctness before performance.\n- [ ] Compare against the V2.3 winner on identical workloads.\n- [ ] Keep only if lower-byte savings produce material physical-media benefit.\n\n## V2.5 — deployment and boot integration\n\n- [ ] Finalize DKMS/package installation and removal.\n- [ ] Finalize `swapzctl` configuration and diagnostics.\n- [ ] Ship safe systemd activation after real root as default.\n- [ ] Use stable `/dev/disk/by-id` or `by-partuuid` backing paths.\n- [ ] Test start/stop/restart, upgrade, and uninstall.\n- [ ] Add module-build/loaded identity diagnostics.\n- [ ] Design optional Dracut early-swap integration for low-memory boot.\n- [ ] Keep Dracut early-swap opt-in and separate from hibernation.\n\n## V2.6 — hardening / volatile release candidate\n\n- [ ] Long-duration randomized churn.\n- [ ] Long-duration real swap pressure.\n- [ ] Repeated GC-heavy workloads and fault injection.\n- [ ] Repeated create/use/destroy/module lifecycle.\n- [ ] Negative configuration and packaging tests.\n- [ ] Define performance regression thresholds.\n- [ ] Freeze documentation/support envelope.\n- [ ] Tag/preserve the stable volatile release candidate.\n\n## V3.0 — final hibernate/resume version\n\n### Persistent design\n\n- [ ] Specify versioned persistent metadata/data format.\n- [ ] Define power-loss-safe commit/publication protocol.\n- [ ] Separate volatile swap state from resumable hibernation state.\n- [ ] Define integrity/corruption detection and safe rejection.\n- [ ] Define version compatibility and backing-device identity checks.\n- [ ] Define successful/abandoned resume invalidation rules.\n\n### Boot integration\n\n- [ ] Implement Dracut/initramfs resume discovery.\n- [ ] Make required dm-swapz code/configuration available before resume.\n- [ ] Define kernel resume handoff.\n- [ ] Keep ordinary cold boot safe with absent/stale/corrupt state.\n- [ ] Preserve normal non-hibernation systemd activation.\n\n### Validation\n\n- [ ] Hibernate -> poweroff -> boot -> resume.\n- [ ] Repeat many cycles.\n- [ ] Test interrupted hibernation and partial/corrupt metadata.\n- [ ] Test unsupported format version.\n- [ ] Test missing/replaced backing device and stale state.\n- [ ] Test failed-resume fallback.\n- [ ] Re-run all ordinary swap correctness, pressure, and performance tests.\n- [ ] Document operational recovery.\n\n## Ongoing engineering rules\n\n- [ ] Preserve the last validated branch before architectural changes.\n- [ ] Verify loaded-module identity for every kernel validation campaign.\n- [ ] Stop on real correctness failures before benchmarking.\n- [ ] Never reboot without explicit operator authorization.\n- [ ] Never touch physical media without explicit exact-device authorization.\n- [ ] Codex may make minimal mechanical compile/test-harness fixes only.\n- [ ] After a Codex fix, primary developer reviews the exact diff and surrounding code.\n- [ ] Codex does not implement roadmap features unless explicitly reassigned.

## 2026-10-08 — Active V2.2 safety and performance gates

- [x] Record Codex's latest exact live-GC, staged cancellation and bounded
      swap-pressure PASS on kernel `d35455ec` (not a GC latency qualification).
- [x] Primary developer: implement dependency-ordered and verified cleanup
      for no-DISCARD, staged recall and pressure fixtures.
- [x] Primary developer: add rootless busy/false-positive/partial/holder/writer
      teardown regression and local source-only smoke coverage.
- [ ] Codex independently run `bash -n` and
      `bash tests/runtime/test-stack-teardown-regression.sh` at current HEAD.
- [ ] Revalidate these changed teardown scripts on disposable virtual stacks
      only after the source-only tests pass and a separate bounded authorization.
- [x] Define the live-victim GC/read-overlap metrics and create the strict
      offline latency-correlation analyzer and unit tests.
- [ ] Independently run
      `python3 tests/runtime/live-gc-latency-analyze-test.py -v`.
- [ ] Design/prove a synchronized CLOCK_MONOTONIC collection mechanism with
      **per-event** moved-page counts (cumulative gc_pages alone is insufficient).
- [ ] Obtain an explicit bounded virtual runtime gate for GC-trigger and
      GC-overlapping swap-in p95/p99/max and reference byte-for-byte readback.
- [ ] Complete the previously assigned source-only NBD preflight, followed
      separately by virtual NBD request-size validation and 20 MiB/s calibration.
- [ ] Select the V2.2 strategy and batch size only from trustworthy drain,
      swap-in latency and GC cost evidence. No real physical-device test
      without authorization of its exact disposable path.

See `docs/benchmarks/v2.2-live-gc-latency.md`.

### 2026-10-08 teardown audit requalification

- [x] Implement checked loop inventory before and after detach, with
      failure distinct from confirmed absence.
- [x] Reject DM parser errors rather than accepting missing target.
- [x] Replace cgroup.procs `-s` checks with checked content reads.
- [x] Fail closed on systemd and /proc/swaps inspection failures.
- [x] Quiesce all three staged-recall background I/O children.
- [x] Make failed child-state inspection block lower teardown.
- [x] Expand rootless teardown mocks and offline GC-analyzer unit tests.
- [ ] Codex independently execute the **updated** source-only teardown,
      pressure and analyzer regressions at the final changed HEAD.
- [ ] Review/fix any failure exposed by that independent rootless gate.
- [ ] Only after all source gates pass, obtain explicit separately scoped
      permission for disposable virtual DM/loop runtime smoke; do not
      operate host swap or physical backing.
- [ ] NBD rootless requalification assigned separately to Codex;
      NBD kernel smoke and calibration remain unapproved and unmeasured.

### 2026-10-08 executed teardown correction gate

- [x] Reject malformed successful DM inventories, including trailing fields.
- [x] Distinguish cgroup os.stat ENOENT from permission/I/O failure.
- [x] Correct false expected states after upper DM was already removed.
- [x] Avoid signaling completed-but-listed shell PIDs.
- [x] Assert pressure cleanup stop -> cgroup check -> swapoff ->
      active-swap verification -> stack cleanup order with mock event log.
- [x] Exercise missing read-result CSV header; analyzer tests now total 11.
- [x] Execute the entire revised *rootless* teardown and analyzer suite
      successfully in GitHub Actions at e92ad29a192b70cbe9e04a1421496bfaf85bd460
      (run 37772741880), including seven Bash syntax checks.
- [ ] Obtain independent Codex Linux-host source-only requalification of the
      newest teardown source after completion of the NBD assignment.
- [ ] Consider pidfd-based atomic signaling for test-owned children if needed;
      Bash job-state inspection still has a small TOCTOU PID-reuse window.
- [ ] Keep kernel device runtime and performance gates blocked until the
      appropriate independent and explicitly authorized test phases.

### 2026-10-08 NBD syscall-isolation remediation

- [x] Fix captured Python default `ioctl=fcntl.ioctl` and
      `close_fd=os.close` that bypassed selftest mocks.
- [x] Use a non-integer fake fd in all mocked `serve_kernel()` setup
      cases, preventing accidental real fd operations on number 81.
- [x] Assert the real shutdown helper resolves mock syscall dependencies
      and preserves its operation-order and cleanup-error diagnostics.
- [x] Treat unexpected non-OSError NBD_DO_IT exceptions as backend failure.
- [x] Mock active NBD PID, unreadable swap inventory, failed active-swap
      stat and the selected NBD block as active swap.
- [x] Execute exact 8 MiB NBD socketpair WRITE/READ in the selftest.
- [x] Obtain static syscall-isolation + seven source-only command PASS
      on disposable GitHub Actions runner at
      f1c458f638712a19dea8b724a7f32bd1052b791e
      (run 37774348723).
- [ ] Obtain independent Codex Linux-host source-only NBD requalification
      *after* it finishes the teardown assignment.
- [ ] Any real kernel NBD/DM/swap runtime test still requires separate
      explicit authorization; no physical or host swap access.
