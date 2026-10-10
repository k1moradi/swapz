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

### NBD preflight inventory follow-up — 2026-10-08

- [x] Reject empty/malformed `/proc/self/mountinfo` and `/proc/swaps`
      inventories before NBD attachment.
- [x] Reject incomplete or nonnumeric active-swap records rather than
      treating them as absence.
- [x] Prove valid unused NBD preflight can still pass the rootless mock
      with an unrelated swap file and negative swap priority.
- [x] Pass updated static syscall isolation and full userspace NBD
      source-only CI on
      `0b93caf752aa4716100815734d3a1f299fc2dec8`
      (run 37775709673).
- [ ] Independent Codex Linux-host NBD requalification remains pending;
      no kernel NBD smoke, real device cleanup or throughput benchmark is
      authorized.

### 2026-10-08 teardown follow-up after independent Codex PASS

- [x] Independent Codex Linux-host teardown source gate PASS at
      `10c9d09bf4d3e78dd9524e20988c38b204f9ad42`.
- [x] Reject duplicate DM names and out-of-range Linux dev_t values
      in complete `dmsetup ls` inventory.
- [x] Reject incomplete, malformed or prefix-spoofed pressure
      `/proc/swaps` inventories before any mapper/loop teardown.
- [x] Verify per-unit distinct systemd ControlGroup paths.
- [x] With test swap active, verify stop failure sends **no** swapoff
      and leaves test mapping and backing untouched.
- [x] Cover stopped shell-owned child CONT/TERM ordering with a rootless mock.
- [x] Accurately label the cgroup pseudo-file simulation as mocked reads.
- [x] GitHub rootless teardown workflow PASS at
      `68360c26214c4c08a57180f50ae032746d68342f`
      (https://github.com/k1moradi/swapz/actions/runs/37777532521):
      seven Bash syntax checks, both teardown regressions, and 11 analyzer
      unit tests.
- [ ] Requalify both latest NBD and teardown sources at a single exact
      commit after Codex's current NBD independent audit.
- [ ] Treat shell PID identity TOCTOU as open until a safe separately
      reviewed pidfd-based signaling design is justified and tested.
- [ ] No real device or performance testing without explicit new approval.

### 2026-10-08 NBD 8 MiB race and mountinfo qualification follow-up

- [x] Fix the observed 8 MiB socketpair EBADF race: stop/join-before-close.
- [x] Apply join-before-close to malformed-request and cancellation tests.
- [x] Strengthen /proc/self/mountinfo parse for mount IDs, major:minor
      syntax, and exact field separator; test malformed ten-field entries.
- [x] Preserve valid optional mountinfo tags and escaped path fixtures.
- [x] Match NBD pull_request CI path filter to its push filter.
- [x] Rootless NBD full seven-command gate PASS at
      `edbf6d1452bd8c87b36c44daa6ad349967592a22`
      (run https://github.com/k1moradi/swapz/actions/runs/37778788448).
- [x] Execute full NBD selftest 25 additional times in separate CI
      processes (25/25 PASS; 26 including initial run), reaching previously
      blocked serve_kernel setup and worker-error tests.
- [ ] Obtain independent Codex Linux-host NBD requalification of the
      revised blob once its teardown task is complete.
- [ ] Perform joint teardown + NBD source-only gate at one common HEAD
      before asking for any separately authorized virtual runtime test.
- [ ] No live kernel NBD/DM/loop/swap or physical testing approved.

### Combined rootless source gate — 2026-10-08

- [x] Run both updated NBD and teardown source-only suites on one
      **exact** checkout and SHA, rather than comparing separately
      tested versions.
- [x] Add `.github/workflows/rootless-combined.yml` to gate relevant
      runtime source changes on push and pull request.
- [x] CI SUCCESS at `8116bdfb8b61a69f67e6548904e82c191b979f23`
      (https://github.com/k1moradi/swapz/actions/runs/37779371716):
      10 Bash syntax checks; 2 teardown rootless regressions; 11 offline
      analyzer tests; NBD syscall isolation, compile and full selftest;
      25 additional full NBD selftest repetitions (26 total); and both
      NBD/streaming teardown mocks.
- [ ] Collect Codex's currently assigned independent Linux-host
      teardown gate at its *own* exact tested HEAD.
- [ ] Obtain an independent Linux-host requalification of the updated
      NBD source if the previous run tested an older blob.
- [ ] Investigate the remaining Bash PID-reuse check-to-signal race
      separately; no unreviewed process-signaling mechanism.
- [ ] Do not infer real kernel NBD behavior, live GC-overlap swap-in
      latency, calibrated bandwidth or batch-size choice from mocks.

### 2026-10-08 Codex whitespace-DM fail-open follow-up

- [x] Accept only truly empty / documented `No devices found`
      successful DM inventory as absence; **reject spaces/tabs/newline-only**
      and whitespace rows mixed with valid device rows.
- [x] Preserve `dmsetup ls` trailing newlines across Bash command
      substitution so malformed inventories cannot masquerade as empty.
- [x] Mock Codex's precise whitespace-only proof-of-failure, post-upper
      removal ambiguity, and positive empty/unrelated/present cases.
- [x] Pin pressure transient test units to `system.slice`, enforce the
      exact nonempty ControlGroup path for each distinct unit, reject
      duplicated/wrong/traversal paths with no swapoff/DM cleanup.
- [x] Test the actual staged-recall stop-all-children -> DM/loop cleanup
      guard on failure and success, without real process/device actions.
- [x] Add malformed `Used` numeric field to the pressure swap mocks.
- [x] Clean GitHub teardown CI PASS at
      `3b60d7659df8cf59716286dfe0d1504307eb2e78`
      (https://github.com/k1moradi/swapz/actions/runs/37781726152).
- [x] Clean same-revision combined source-only CI PASS at
      `3b60d7659df8cf59716286dfe0d1504307eb2e78`
      (https://github.com/k1moradi/swapz/actions/runs/37781726172).
- [ ] Obtain Codex independent host requalification of updated teardown
      after it finishes its currently assigned NBD audit.
- [ ] PID-reuse check-to-signal race remains unresolved; no unreviewed
      atomic signaling mechanism has been introduced.
- [ ] Real swap/NBD/DM runtime, GC-overlap p99 and physical testing
      remain unauthorized.

### 2026-10-08 NBD mountinfo dev_t and partition preflight qualification

- [x] Correct Codex's NBD source-only FAIL: reject syntactically valid
      but impossible mountinfo major/minor tuples outside Linux 12-bit
      major / 20-bit minor limits.
- [x] Compare mountinfo device identity numerically so a selected NBD
      mount using leading zeros is not misclassified as unrelated.
- [x] Extend malformed first/second-row, max/zero-valid-device and
      mounted-device rootless preflight cases.
- [x] Reject an NBD sysfs partition child (`nbd0p1`) in a direct
      full-preflight rootless test and fail closed on unreadable
      partition enumeration.
- [x] Updated NBD rootless CI PASS at
      `40678c7d9743d6efca943885f40be1a0388d3ca6`:
      https://github.com/k1moradi/swapz/actions/runs/37783419565
      (all seven-command equivalents plus 25/25 additional full
      selftest executions; 26 in total).
- [x] Updated combined same-commit rootless gate PASS:
      https://github.com/k1moradi/swapz/actions/runs/37783419522
      (teardown, NBD and 11 offline GC analyzer tests).
- [ ] Independent Codex Linux-host NBD requalification of the new
      source blob after its ongoing teardown audit.
- [ ] No live kernel NBD, swap, DM/loop or GC-overlap/physical tests
      without separate explicit authorization.

### 2026-10-08 post-Codex teardown-PASS regression completion

- [x] Record Codex independent **SOURCE-ONLY TEARDOWN GATE PASS**
      at `0f2f169631d08fc1b92e2aba1bed398e1ef795ff` after all
      ten commands and supplemental DM/ControlGroup checks passed.
- [x] Check in direct tests of duplicate, empty, invalid-suffix,
      traversal, slash and malformed transient unit names.
- [x] Check in ControlGroup-empty plus live MainPID, active state and
      both unsafe tests simultaneously; retain positive tests for
      stopped/reaped inactive and failed services.
- [x] Record systemctl property reads and unexpected process signals
      in a file-backed log that persists across Bash subshells.
- [x] Fix uncovered sequencing issue: prevalidate both transient unit
      names before any systemd inspection/stop, even if the second
      name is malformed.
- [x] Teardown CI **PASS** at
      `e64509318576f3c4d65050426af234c2910b70ff`:
      https://github.com/k1moradi/swapz/actions/runs/37784883620
- [x] Combined NBD+teardown same-source CI **PASS**:
      https://github.com/k1moradi/swapz/actions/runs/37784883592
      (26/26 NBD selftests, 11 offline GC analyzer tests, all teardown mocks).
- [ ] Await Codex independent Linux-host audit of the revised NBD
      mountinfo bounds/partition source blob.
- [ ] Review the remaining Bash PID reuse check-to-signal TOCTOU
      separately before introducing new process signaling.
- [ ] Real kernel, swap, device, GC overlap and physical performance
      qualification remains unauthorized.

### 2026-10-08 — NBD exceptional socketpair cleanup follow-up

- [x] Codex independent **NBD SOURCE-ONLY GATE PASS** at
      `bd9fac18d06f1c4642c913618de645401611698e`
      (all seven commands, 10/10 additional timed selftests).
- [x] Factor 8 MiB wire socketpair stop/join/shutdown/join/close
      into a test-only bounded cleanup helper, not production kernel shutdown.
- [x] Fail with an explicit diagnostic if worker remains alive after
      both bounded joins, including when closing sockets later unblocks it.
- [x] Deterministically fault-inject first-join exit, second-join exit,
      local shutdown error, still-active worker, unexpected worker
      exception, unstarted cleanup and wire-transaction failure.
- [x] New NBD rootless CI **PASS** at
      `52a2d6330428c64b39f2f8fe1c42aa1ff70a4cc9`:
      https://github.com/k1moradi/swapz/actions/runs/37788553329
      (one full NBD selftest and 25/25 additional processes).
- [x] Same-revision combined NBD+teardown CI **PASS**:
      https://github.com/k1moradi/swapz/actions/runs/37788553094
      (full NBD and teardown mocks and 11 offline analyzer tests).
- [ ] Collect Codex's separately assigned identity-safe PID signaling
      design and independent latest pressure teardown prevalidation audit.
- [ ] Leave real NBD, swap, DM/loop, module, GC latency and physical
      performance qualification blocked pending explicit authorization.

### 2026-10-08 — Pressure checkpoint token migration and mock proof

- [x] Remove both checkpoint `kill -CONT "$pid"` calls and the
      SIGSTOP/wait pattern from the pressure workload helper.
- [x] Remove numeric MainPID `SIGCONT` from pressure teardown.
      Keep unit stop by exact name and fail-closed cgroup/swap checks.
- [x] Provide a bounded `filled` -> `release-filled` ->
      `verified` -> `release-verified` protocol with a fresh
      128-bit nonce per transient unit and per-unit private paths.
- [x] Atomically publish full marker/release data without overwriting
      stale tokens; reject malformed, duplicate and wrong-phase tokens.
- [x] Add 8 new rootless tests for phase ordering, wrong-phase/cross-unit
      release, timeout, interruption, malformed/stale token, readback
      corruption and successful completion.
- [x] Extend pressure teardown mock to prove **zero numeric-PID
      signals**, even with a nonzero mocked MainPID.
- [x] Teardown source-only CI **PASS** at
      `1c5cfe5305ba0bad9c8edbf404390b4093bdfbec`:
      https://github.com/k1moradi/swapz/actions/runs/37791843695
- [x] Same-commit combined NBD/teardown CI **PASS**:
      https://github.com/k1moradi/swapz/actions/runs/37791843564
      (8 pressure token tests, 11 analyzer tests, 26/26 complete NBD selftests).
- [ ] Independently review rootless pressure protocol's behavior under
      the supported real systemd service manager before any authorized
      live pressure test.
- [ ] Collect Codex's separately assigned gated pidfd supervisor
      prototype and review; **recall PID-reuse race is still open**.
- [ ] No live pressure, systemd service, swap, DM/loop/NBD, kernel module
      or physical testing without separate explicit authorization.

### 2026-10-08 — Private pressure token file integrity

- [x] Eliminate unbounded/following `read_bytes()` token reads and
      shell `cat` of checkpoint markers; use nofollow, nonblocking,
      regular-file, inode-stable, single-link and exact-size checks.
- [x] Reject symlink/hardlink/FIFO and oversized marker/release files,
      including a replacement between lstat and open; check command
      validates readiness without publishing a release.
- [x] Raise explicit errors on malformed token files while preserving
      the monotonic wait timeout and exact `phase:nonce` protocol.
- [x] Grow rootless pressure checkpoint suite to 16 tests; repeat all
      16 in 10 independently timed processes in both CI workflows.
- [x] Teardown CI **PASS** at
      `6755e82b18c59f9b9047098ec6da97dba620c3f6`:
      https://github.com/k1moradi/swapz/actions/runs/37794454277
- [x] Combined rootless CI **PASS** at
      `45ac8b7dc668200315bea8556708bffa944dcb3d`:
      https://github.com/k1moradi/swapz/actions/runs/37794468550
      (10/10 pressure suite repeats, 26 NBD selftests, 11 analyzer tests).
- [ ] No live systemd, swap, device, GC latency, or physical qualification
      without separate authorization.
- [ ] Recall PID reuse remains open pending independently tested
      gated-pidfd supervisor design and later integration approval.

### 2026-10-08 — Production pressure controller source-only integration

- [x] Extract pressure phase controller into side-effect-free
      `tests/runtime/pressure-runner.sh`, sourced and called by the
      real fixture, enabling safe rootless testing of production flow.
- [x] Add `pressure-runner-regression.sh` to mock all systemd, device,
      cgroup and swap operations, execute positive/negative phase
      progression, and assert no incorrect checkpoint release.
- [x] Detect and correct conditional Bash `errexit` fail-open:
      failed `memory.swap.current`, swap usage, DM status or GC
      accounting previously could be ignored when the function was
      invoked under a conditional, wrongly issuing
      `release-verified`.
- [x] Use explicit guarded returns with exact DM `failed=0`
      matching and positive decimal memory/swap/required-GC checks.
- [x] Update static token test to verify the live fixture sources
      and invokes the same tested controller.
- [x] Teardown source-only CI **PASS** at
      `c484ac0c9a90c5ff33b0c17b2b1044f5be80110d`:
      https://github.com/k1moradi/swapz/actions/runs/37801182069
- [x] Combined same-revision source-only CI **PASS**:
      https://github.com/k1moradi/swapz/actions/runs/37801181958
      (production controller mocks, 16 pressure protocol tests
      repeated 10 times, 11 analyzer tests, 26 NBD selftests).
- [ ] Independent host source review of pressure controller before
      authorized real systemd pressure execution.
- [ ] Await Codex's gated-pidfd recall-supervisor prototype; recall's
      numeric-PID signaling safety remains an open qualification.

### 2026-10-08 — Strict pressure swap inventory before phase releases

- [x] Replace the controller's ambiguous AWK `Used+0` coercion and
      missing-row default with a strict full `/proc/swaps` parser.
- [x] Validate exact header, five fields per row, path/type, ASCII
      decimal Size/Used/Priority, nonzero Size and Used ≤ Size;
      require **exactly one** canonical row matching the test device.
- [x] Fail closed at filled and verified checkpoints for unreadable,
      missing, duplicate, truncated or malformed swap inventories.
- [x] Add 23 standalone parser tests, including bad Used suffix,
      malformed unrelated entries and valid symlink alias.
- [x] Execute the actual production controller with mock inventories,
      verifying that malformed cases do not authorize phase release.
- [x] Teardown rootless CI **PASS**:
      https://github.com/k1moradi/swapz/actions/runs/37802473498
      (commit `3f4d1cd334074ba423b87b0801b1bccd72d0021c`).
- [x] Combined rootless CI **PASS**:
      https://github.com/k1moradi/swapz/actions/runs/37802481882
      (commit `b3833393c2a6d4e351e2610e647eaad0863eed05`,
      23 parser tests, 10/10 pressure suite repeats, 26/26 NBD
      selftests and 11 offline analyzer tests).
- [ ] Independently review controller behavior under a supported
      systemd installation before any authorized live pressure test.
- [ ] Recall PID reuse remains open until Codex's gated-pidfd
      supervisor prototype is reviewed and later integrated.

### 2026-10-08 — Direct recall I/O plan and pidfd CI milestone

- [x] Check in fixture-neutral `recall-io-plan.py` constructing
      direct `dd` argv arrays with no background Bash wrappers.
- [x] Preserve the nine-page deterministic fixture, exact 4096-byte
      comparisons, staged single A/B reads, and both dual readers
      **launched before either is waited**.
- [x] Preserve all returned opaque supervisor handles, including
      already-reaped readers and the outstanding staged writer.
- [x] Block mock cleanup callback after any ambiguous worker launch,
      wait, reap, identity, comparison, stop report or supervisor error.
- [x] Add 25 rootless fake-supervisor tests with synthetic pages,
      injected errors and AST process-syscall isolation assertions.
- [x] Gate Codex's 27-case gated-pidfd supervisor suite in both
      workflows with three additional finite-timeout process repeats.
- [x] Teardown rootless GitHub CI **PASS** at
      `a276218feba2454b5f4c1e9c515d276a8155c468`:
      https://github.com/k1moradi/swapz/actions/runs/37808199284
- [x] Same-revision combined NBD/teardown CI **PASS**:
      https://github.com/k1moradi/swapz/actions/runs/37808199250
      (27 supervisor tests + 3 repeats, 25 I/O-plan tests, 26
      NBD selftests, pressure and teardown mocks, 11 analyzer tests).
- [ ] Await Codex's independently reviewed opaque-handle IPC
      control-service work before a separately reviewed adapter.
- [ ] Do not claim original recall PID reuse risk is resolved:
      `buffer-recall.sh` still launches numeric-PID Bash jobs.
- [ ] Real kernel, DM/loop, swap, systemd pressure and physical
      device/latency qualification requires separate authorization.

### 2026-10-08 — Recall I/O source and readback file integrity

- [x] Stop following symlinks or blocking on special files while preparing
      expected recall pages or comparing worker readback results.
- [x] Read only exact-sized single-link regular files with nofollow,
      nonblocking descriptor opens and lstat/fstat inode identity checks.
- [x] Reject malformed nine-page source, short/oversized readback,
      symlink/FIFO/hardlink, and injected path-replacement races.
- [x] Create expected 4096-byte pages exclusively (`O_EXCL`); reject
      dangling pre-existing or racing symlink output paths.
- [x] Preserve the plan's fail-closed stop/reap and cleanup-callback
      contract on every file preparation/readback failure.
- [x] Grow source-only direct recall suite from 25 to **37 tests**.
- [x] Teardown CI **PASS** at
      `4181df6ad91099ae0717fa6474750be153ed8734`:
      https://github.com/k1moradi/swapz/actions/runs/37809491958
- [x] Same-source combined NBD/teardown CI **PASS**:
      https://github.com/k1moradi/swapz/actions/runs/37809491946
      (37 recall tests, 27 supervisor tests + 3 repeats,
      26 NBD selftests, 23 swap-parser tests, 11 analyzer tests).
- [ ] Await independently tested Codex pidfd IPC service; do not
      wire up `buffer-recall.sh` before a separate integration review.
- [ ] Source-only file tests are not live device, swap or latency proof.

### 2026-10-08 — Recall trusted reference data and stop-report attestation

- [x] Preserve immutable in-memory expected bytes when preparing each
      4096-byte recall page so matching corrupt on-disk expected and
      readback files cannot produce a false positive.
- [x] Require each detailed supervisor stop result to have a distinct,
      exact-match opaque handle from the full registered handle set,
      confirmed reap and no per-worker errors; reject report-level
      errors even with `cleanup_allowed=true`.
- [x] Add 9 adversarial tests, raising the source-only recall plan
      suite from 37 to **46 tests**.
- [x] Rootless teardown CI **PASS** on
      `ec70195d1d1c7a44a72aea83de65043c5fef323f`:
      https://github.com/k1moradi/swapz/actions/runs/37810629055
- [x] Same-commit combined NBD/teardown CI **PASS**:
      https://github.com/k1moradi/swapz/actions/runs/37810628795
      (46 recall tests, 27 pidfd supervisor tests + 3 repeats,
      26 NBD selftests, 23 strict swap-parser tests and 11 GC analyzer tests).
- [ ] Retain separate Codex control-service implementation and
      independent review before any production recall IPC integration.
- [ ] Production Bash recall still contains the numeric-PID reuse race
      and untracked background read-function descendants.

### 2026-10-08 — Test-only pidfd IPC adapter and mandatory CI

- [x] Add `recall-ipc-adapter.py` with only fixed `sleep` and
      `exit` test-worker admission, opaque handle registry and
      typed worker-result/stop-attestation objects.
- [x] Require complete exact-handle, all-reaped and no-errors
      `stop_all` attestation before any provisional cleanup decision.
- [x] Require successful shutdown, actual service exit code zero
      and independent client exit confirmation before allowing even
      a **synthetic** cleanup callback; fail closed on channel or
      worker failure.
- [x] Add 20 rootless adapter tests: fabricated contradictory
      reports, missing/duplicate/unknown workers, exit and transport
      failure, plus actual private socketpair IPC with short-lived
      test-only service children.
- [x] Require 23 IPC service tests and **10 additional 15-second
      bounded separate suite runs** in both rootless workflows.
- [x] Preserve the 27-test supervisor gate + three repetitions,
      46 recall I/O tests, all pressure/teardown and NBD checks.
- [x] Teardown rootless CI **PASS** at
      `d6a92486d71ba0e1f6c27cf1c1b4781e4ce1cd81`:
      https://github.com/k1moradi/swapz/actions/runs/37814381219
- [x] Same-commit combined rootless CI **PASS**:
      https://github.com/k1moradi/swapz/actions/runs/37814381190
      (20 adapter tests, 23 IPC service tests + 10/10 repeats,
      27 supervisor tests + 3 repeats, 46 direct recall plan tests,
      26/26 NBD selftests, 11 offline GC analyzer tests).
- [ ] Await Codex's independent IPC report-verification hardening
      and rerun cross-component gates if its service blobs change.
- [ ] Review the narrow direct-`dd` command grammar, controlled
      supervisor ownership, descendant containment, and Bash-facing
      adapter before replacing the numeric-PID recall fixture.
- [ ] Real kernel, NBD/DM/loop, swap, systemd and physical
      performance qualification remains unapproved and untested.

### 2026-10-08 — Strict direct dd allowlist ready for integration review

- [x] Add `recall-dd-allowlist.py`: exactly five fixed, one-use
      roles (writer, a, b, a2, b2) with explicit 4096-byte direct
      `dd` flags, page offsets and fixture-owned input/output paths.
- [x] Bind a trusted source directory and test-specific mapper
      name; reject arbitrary argv, wrong flags and paths, role reuse,
      readers before writer, symlinked/ambiguous source and output
      files, changed fixture identities and unsafe root/path grammar.
- [x] Verify generated argv matches `recall-io-plan.py` exactly.
- [x] Add **26** new rootless adversarial allowlist tests and
      gate them in both source-only GitHub workflows.
- [x] Teardown rootless CI **PASS** at
      `8aa82dfef9a455ee3e6b26e7e3533c2eb98758d3`:
      https://github.com/k1moradi/swapz/actions/runs/37815480268
- [x] Combined same-revision CI **PASS**:
      https://github.com/k1moradi/swapz/actions/runs/37815480464
      (26 allowlist, 20 IPC adapter, 23 IPC service + 10 repeats,
      27 supervisor + 3 repeats, 46 recall plan, 26 NBD and
      all prior pressure/GC analysis gates).
- [ ] Review fixture-owned private directory permissions and bind
      file/mapper identity through actual process launch; argv/path
      prechecks alone do **not** close a postvalidation path race.
- [ ] Await independent Codex IPC hardening, then design/review
      integration with a production direct-`dd` service allowlist.
- [ ] `buffer-recall.sh` remains unchanged: numeric-PID safety
      and hidden read-worker descendants are still unresolved.

### 2026-10-08 — Persistent rootless Bash pidfd control bridge

- [x] Create `recall-control-bridge.py` owning one persistent
      private IPC socketpair, one test-only pidfd service Popen
      and one continuous opaque-handle registry.
- [x] Implement bounded Bash JSON `LAUNCH_TEST`, `WAIT`,
      `STOP_ALL`, `SHUTDOWN`, `FINALIZE` protocol with
      monotonically increasing IDs and no numeric-PID signaling,
      direct-`dd` execution or arbitrary argv.
- [x] Require full worker accounting, clean shutdown, observed
      zero service exit and clean control-socket close before
      the sole positive FINALIZE cleanup decision.
- [x] Add 23 Python rootless cases and genuine Bash coprocess
      rootless regressions for three-worker continuity,
      dual launch-before-wait ordering, malformed replies,
      nonzero child exit and abrupt controller disconnection.
- [x] Gate bridge compilation, Bash syntax and runtime regression
      in both GitHub rootless workflows.
- [x] Rootless teardown CI PASS at
      `ec52145bd0543f80e7576236231184d32656f1e1`:
      https://github.com/k1moradi/swapz/actions/runs/37855300271
- [x] Combined NBD/teardown CI PASS at same code revision:
      https://github.com/k1moradi/swapz/actions/runs/37855300287
      (23 bridge, 34 IPC service + 10 repeats, 27 pidfd
      supervisor + 3 repeats, 20 adapter, 26 dd-allowlist,
      46 I/O plan, 26 NBD selftests plus teardown/pressure).
- [ ] Codex to separately review a fixture-bound direct-dd
      launch path and address path identity at the actual spawn
      boundary before production integration.
- [ ] Replace production `buffer-recall.sh` numeric-PID
      cleanup and background reader subshells only after
      independent integration tests and safety review.
- [ ] Test-owned bridge is source-only: real DM/loop/NBD,
      swap, GC/latency, physical-media operations remain
      unapproved/unverified.

### 2026-10-08 — Pinned direct-dd role admission and real rootless worker regression

- [x] Verify Codex's new two-commit opt-in launch-gate work
      (`a0a1252a`, `afffddad`) and review the direct-child pidfd,
      descriptor-pinning, role admission, IPC and shutdown code.
- [x] Preserve default service and Bash bridge as test-only.
      No direct `dd` request is accepted by the current bridge.
- [x] Add independent rootless regression that executes genuine pinned
      GNU `dd` with an ordinary temporary file as synthetic mapper,
      verifies all five roles and exact bytes, and checks source/output
      path-replacement redirection after role admission.
- [x] Gate that regression in both rootless workflows and trigger both
      workflows whenever either mandatory workflow changes.
- [x] Teardown and combined CI both PASS at executable-source revision
      `4a89dc77752a28c53d62a6f81eec276e6438dfe0`:
      https://github.com/k1moradi/swapz/actions/runs/37858629277
      https://github.com/k1moradi/swapz/actions/runs/37858629165
- [ ] Add a separately reviewed trusted direct-dd bootstrap for the
      fixture-owned live mapper with authoritative identity, and prevent
      concurrent DM table changes while supervised I/O is outstanding.
- [ ] Preserve the pinned *output descriptor identity* through readback
      validation, so replacing a pathname cannot subvert exact comparison.
- [ ] Add approved role commands to a rootless persistent bridge integration;
      retain complete opaque handle inventory, stop/reap, process exit and
      FINALIZE before any synthetic cleanup authorization.
- [ ] Independently prove no I/O-producing descendants survive and define
      service-crash containment/preservation before production recall migration.
- [ ] Migrate production `buffer-recall.sh` without weakening nine-page
      A/B staged hits, concurrent read timing, exact readback, 300 ms
      threshold, discard, writer wait, fsync or cancellation assertions.
- [ ] Keep live DM/loop/NBD/swap, pressure, module and physical-media
      operations gated on separate explicit user authorization.

### 2026-10-08 — Identity-bound readback and rootless fixed-role bridge

- [x] Add descriptor-pinned 4 KiB readback attestation, independent
      immutable reference comparison, pathname/inode/size checks and
      fail-closed negative tests.
- [x] Implement opt-in `RecallRoleIPCAdapter` with exactly five one-use
      workers, handle retention, all-role completion requirements,
      simultaneous A2/B2 launch-before-wait gating and writer lifetime
      through completed reader checks.
- [x] Implement synthetic-only injected `RootlessRoleBridge`, strict
      role-only JSON, sticky finalization failure, and no change to the
      normal bridge or service CLI's fixed test-worker allowlist.
- [x] Add true AF_UNIX service-wire + Codex launch gate regression with
      temporary regular files and a non-forking fake supervisor.
- [x] Add real Bash coprocess synthetic-role success/failure/disconnect
      qualification, with only synthetic backing-marker deletion.
- [x] Extend both required rootless workflows; PASS at executable SHA
      `0592b47693ca95ca7ff3f07fc7f56a502bc83519`:
      https://github.com/k1moradi/swapz/actions/runs/37860393441
      https://github.com/k1moradi/swapz/actions/runs/37860393481
- [ ] Review Codex's independently implemented worker-crash/descendant
      containment and obtain same-revision joint CI after integration.
- [ ] Implement a *trusted* separate-service bootstrap that binds the
      actual test DM descriptor identity and each newly created output
      descriptor to immutable reference bytes across the IPC boundary.
      Neither an after-the-fact path check nor an unchecked callback is
      sufficient to authorize production teardown.
- [ ] Connect proven real direct-worker pidfd lifecycle, identity
      attestation and service-process exit into the approved Bash bridge;
      test service crash/reuse/errors under rootless regular files first.
- [ ] Only then migrate production `buffer-recall.sh`, preserving nine
      deterministic 4 KiB pages, staged A/B hits, 500 ms lower delay,
      concurrent-phase completion, 300 ms read threshold, discard,
      exact data, writer wait, fsync and cancellation/failed counters.
- [ ] Obtain separate operator approval before live DM/loop/NBD/swap,
      kernel pressure/GC latency campaigns or physical benchmarking;
      complete 4 KiB..1 MiB drain-throughput/read-p99 plateau
      qualification and choose V2.2 strategy/batch only from measured data.

### 2026-10-08 — Genuine cross-process rootless recall integration

- [x] Start a separate, test-owned `Popen` service over an inherited private
      AF_UNIX socket. Restrict its mapper to an owned exact-size regular file;
      reject root operation and do not enable the normal service CLI.
- [x] Use the real `GatedPidfdSupervisor` with parent-death and seccomp
      containment for actual fixed-role direct `dd` workers.
- [x] Capture service-owned output descriptors before reader launches and
      verify exact pinned inode and independent 4096-B expected bytes after
      each worker's zero-exit wait/reap.
- [x] Validate a fixed role + opaque-handle + expected SHA-256 readback
      receipt on the trusted process socket without granting arbitrary
      caller-supplied paths, argv, fds or verification booleans.
- [x] Confirm all five receipts and the true service process's zero exit
      before permitting *synthetic-only* backing-marker cleanup.
- [x] Test failure preservation for output pathname replacement, mutated
      source data, writer/concurrent wait ordering, supervisor SIGKILL by
      test-owned pidfd and controller EOF.
- [x] Both mandatory CI workflows PASS at executable revision
      `f1e07734b44ea88ebcb2f956773b92bd51cdc6ea`:
      https://github.com/k1moradi/swapz/actions/runs/37878408360
      https://github.com/k1moradi/swapz/actions/runs/37878408375
- [x] Draft `docs/v22-virtual-benchmark-qualification.md` (NOT measured
      results) with drain, GC/swap-in p99, 4..1024 KiB sweep and exact
      approval gates.
- [ ] Review/integrate Codex's independently trusted GNU executable
      provenance, DM UUID/table lifecycle and I/O-drain policy, then run
      same-revision rootless joint qualification.
- [ ] Add further rootless fault injection for missing/forged receipts,
      worker exec/nonzero failures, descriptor-close failure and service
      crash during a deliberately held I/O operation.
- [ ] Bind the trusted service to the real production Bash-controller
      lifecycle without allowing device paths/argv from the control channel.
- [ ] Only after exclusive mapper lifecycle ownership and kernel drain
      guarantees: independently review migration of production
      `buffer-recall.sh` preserving all prior page, staging, timing,
      discard, fsync and cancellation assertions.
- [ ] Obtain explicit operator approval for disposable DM/loop/NBD/swap
      tests and, separately, physical benchmarks. V2.2 strategy and batch
      remain **UNDETERMINED**; do not substitute the rootless CI results
      for measured kernel performance.

### 2026-10-09 — Rootless evidence gate for V2.2 batch/strategy choice

- [x] Implement `v22-drain-plateau-analyze.py` as an offline
      strict-schema, no-device benchmark evidence validator, using
      **independent lower-write sector deltas** rather than logical fio
      completion for the drain throughput numerator.
- [x] Implement 15 rootless selftests for candidate selection, 97%
      high-batch plateau requirement, 10% worst-repeat read-p99,
      incomplete/noisy sweeps, insufficient samples, impossible sector
      deltas, failed safety flags, contradictory/duplicate JSON, and
      explicit synthetic-vs-measured result classification.
- [x] Run source-only regression in both mandatory GitHub workflows
      at exact executable revision
      `bca327fd11d841870715171693faec2abc054838`:
      https://github.com/k1moradi/swapz/actions/runs/37907017405
      https://github.com/k1moradi/swapz/actions/runs/37907017408
- [x] Document current `streaming-benchmark.sh` performance
      mislabeling: `drained_write_mib_s` is logical fio bytes /
      elapsed time, **not** physical lower-device bytes /
      measurement window. Never select a V2.2 winner using that
      field without independent physical-counter qualification.
- [ ] Separately review and instrument the *authorized virtual*
      benchmark collection path to capture verified lower-device
      sectors, completed I/O count, monotonic drain window, exclusive
      backend ownership, kernel I/O-drain proof, raw read-latency
      samples/count and robust experiment metadata.
- [ ] Rerun the nine-size strategy sweep with >=3 independent
      calibrated runs each under approved disposable virtual
      stacks; do not declare a plateau with missing, unstable or
      p99-incompatible data.
- [ ] Obtain distinct operator approval before physical media;
      V2.2 strategy, batch and throughput plateau remain
      **NOT ESTABLISHED** by rootless testing.

### 2026-10-09 — Safer live benchmark *reporting* (source-only)

- [x] Eliminate `streaming-benchmark.sh`'s false
      `drained_write_mib_s` label and its one-run
      `first_97pct/latency_guarded` winner nomination.
- [x] Record separate `logical_flush_window_mib_s` and
      `lower_counter_window_mib_s` using a monotonic timed window,
      plus fio's actual `read_count`, without relabeling the lower
      counter rate as independently attested physical drain.
- [x] Add read-only `streaming-benchmark-report.py` which
      validates the fio/sysfs numerator arithmetic and always reports
      `NO QUALIFIED WINNER / PLATEAU NOT REACHED` for a one-run sweep.
- [x] Qualify 14 purely fabricated-fio rootless regressions, including
      extracting and running the actual embedded fio JSON formatter
      *without ever invoking the live benchmark shell*.
- [x] Both mandatory GitHub workflows PASS at executable revision
      `ecd06d89b8c5f85bf67c6ec07b232625cce079ec`:
      https://github.com/k1moradi/swapz/actions/runs/37909068184
      https://github.com/k1moradi/swapz/actions/runs/37909068343
- [ ] After Codex's GNU/DM identity and kernel I/O-drain gate,
      independently review a trusted, **operator-authorized**
      collector for lower counters, exclusive backend ownership,
      raw p99 samples, real quiescence, >=3 independent runs/size,
      and completeness under the `swapz-drain-observation-v1` schema.
- [ ] Keep existing one-run streaming output strictly diagnostic.
      Do not promote any nominal 97% point to V2.2 strategy/batch
      winner without qualified virtual and separately authorized
      physical tests. Actual winner remains **UNDETERMINED**.

### 2026-10-09 — Mocked DM drain orchestration and NBD PID-reuse containment

- [x] Add both original `recall-io-drain-policy-test.py` (8 tests) and
      new `recall-io-drain-orchestrator-test.py` (15 tests) to **both**
      mandatory source-only CI workflows and teardown path triggers.
- [x] Introduce a strictly synthetic operations provider that
      executes all 15 ordered drain-policy transitions, records
      attempted actions, fails closed on every malformed/unknown
      observation, and never makes real device calls.
- [x] Bind synthetic backing-marker removal to complete policy
      authorization and revalidation of the private original inode.
      Tests cover corrupt worker inventory, swapoff, ordinary suspend,
      noflush, open counts, holders, changed DM identity, false-positive
      removal, loop failure, unexpected fields and marker replacement.
- [x] Remove the NBD teardown helper's numeric `kill -0`,
      `kill -TERM` and `ps -p NBD_PID` paths; obsolete positive
      SIGTERM assertions were replaced with fail-closed preservation
      mocks, including a fake numeric PID that must never be signaled.
- [x] Explicitly **disable the live NBD streaming benchmark mode**
      before fixture allocation, while retaining rootless, no-device
      NBD userspace socket selftests. `setup_nbd()` also refuses any
      attempted direct call. Do not silently bypass this guard.
- [x] Both mandatory rootless CI gates PASS at exact source revision
      `4843e385e54a3389ab9156bc1ad08509affdd00c`:
      https://github.com/k1moradi/swapz/actions/runs/37910706506
      https://github.com/k1moradi/swapz/actions/runs/37910706553
- [ ] Implement a separately reviewed **pidfd-owned NBD server
      controller** with stable child ownership, startup identity,
      graceful shutdown, clean exit and full descendant containment,
      then complete rootless fault injection before considering
      re-enabling authorized disposable NBD benchmarking.
- [ ] Replace the synthetic DM observation provider with separately
      trusted, privileged-fixture-owned evidence collection only
      after the GNU/mapper identity gate. Require ordinary real
      suspend, verified absence, swap inventory, open/holder checks
      and kernel I/O quiescence before any actual backing cleanup.
- [ ] Connect full rootless recall-worker completion and subsequent
      drain authorizations to production fixture only after separate
      review. Never infer kernel drain from a reaped `dd` worker.
- [ ] Obtain explicit operator approval for disposable virtual DM/loop
      and later distinct physical media testing. Strategy and batch
      remain **UNDETERMINED** without repeated valid lower-device
      drain and read-p99 measurements.

### 2026-10-09 — Fixed synthetic NBD server, stable pidfd ownership

- [x] Implement rootless `nbd-pidfd-owned-session.py`, which launches
      **one fixed synthetic child** over an inherited private AF_UNIX
      socket, pins it with `os.pidfd_open`, verifies a nonce-bound
      READY packet, delivers TERM/KILL only through the retained pidfd,
      and uses its exact `Popen.wait` result. No arbitrary executable,
      PID, NBD device or command arrives via an IPC field.
- [x] Qualify 19 actual separate-process rootless tests for normal
      verified exit, wrong/absent/delayed readiness, abort, exit
      failure, SIGTERM timeout/ignore, failed pidfd signal,
      missing pidfd APIs, lost pidfd acquisition after spawn,
      reused lifecycle calls, forged worker modes and path safety.
- [x] Preserve all synthetic backing in **every** result, including
      a zero-exit process; explicit return flags never imply real
      NBD detach, DM drain or backing cleanup.
- [x] Run the same 19-case suite in rootless NBD, teardown and
      combined GitHub workflows, all PASS at executable revision
      `3a039d7207c301f8b12a7aac4bd98bb8bc51a51c`:
      https://github.com/k1moradi/swapz/actions/runs/37913643602
      https://github.com/k1moradi/swapz/actions/runs/37913643708
      https://github.com/k1moradi/swapz/actions/runs/37913643598
- [ ] Prove real server descendants and parent-crash containment,
      independent server binary/argv and NBD session identity,
      fail-closed kernel NBD disconnect and device absence, and
      proper integration with the real DM suspend/drain evidence
      chain under a separately controlled privileged fixture.
- [ ] The currently disabled `SWAPZ_BENCH_BACKEND=nbd` must
      **remain disabled** until the entire actual server and kernel
      lifecycle is reviewed and separately authorized on disposable
      virtual resources; passing rootless pidfd mock tests is
      insufficient to re-enable it.
- [ ] Continue trusted GNU provenance and exclusive mapper owner
      work separately; actual V2.2 lower-device throughput, swap-in
      read-p99 plateau, strategy winner and batch remain UNDETERMINED.

### 2026-10-09 — Main-developer Codex review and real-process mock crash containment

- [x] Review Codex's `d2240b06e8a8fc5649d407d0c0344308896196e0`
      trust-bootstrap/mapper-owner commit, including actual code,
      changed-file scope, trust boundaries and same-revision CI;
      record findings in `docs/codex-trust-bootstrap-review-2026-10-09.md`.
- [ ] **HIGH:** Never use `MapperLifecycleOwner.cleanup_allowed` as
      backing release authority. It attests only that *one mapping*
      was removed; require independently verified worker/descriptor
      receipts, DM kernel suspend/drain, complete stack/loop/NBD
      dependencies and normal detach before real backing cleanup.
      Codex owns any follow-up to this owner API.
- [ ] **HIGH:** The static GNU `dd` build provenance, externally
      provisioned Ed25519 key, compatible actual child seccomp run
      and enforceable privileged DM table exclusivity remain unqualified.
      Fixed-root-path cryptographic verification and injected owner
      success are not substitutes.
- [x] In the *fixed rootless synthetic NBD-like child*, register
      Linux `PR_SET_PDEATHSIG=SIGKILL` before READY, recheck exact
      expected parent identity, and treat missing/unsupported registration
      as hard denial.
- [x] Block synthetic mock descendants and executable replacement
      via architecture-checked Linux seccomp BPF denying fork/vfork/
      clone/clone3/execve/execveat, then explicitly attempt fork
      and exec in the rootless mock to verify EPERM.
- [x] Use a separate test-owned observer with `SCM_RIGHTS`
      pidfd transfer to check exact child exit after controller
      `os._exit` before READY, after READY and during idle,
      including an EOF-resistant test mode to isolate PDEATHSIG.
      The independent observer verifies exit, not orphan reaping.
- [x] Preserve the retained child pidfd after failed SIGTERM,
      failed SIGKILL and bounded wait; allow a later pidfd-only
      `close()` retry without numeric-PID fallback.
- [x] Run 24 non-skipped, real, fixed-child rootless regressions
      and qualify all three source-only workflows at exact
      executable revision
      `14d1b9ae7b9a40906835b52d761640e58500e02e`:
      https://github.com/k1moradi/swapz/actions/runs/37916615965
      https://github.com/k1moradi/swapz/actions/runs/37916615903
      https://github.com/k1moradi/swapz/actions/runs/37916615659
- [ ] **Still blocked:** separately authenticate the actual
      size-aware NBD server and control its full runtime/descendants,
      prove exact device/kernel NBD session association and
      independently verify kernel disconnect/drain and backing
      dependencies before considering a separate live-device review.
- [ ] Keep NBD streaming backend fail-closed and disabled; the mock
      owner and child cannot authorize real device I/O, mapper
      admission, lower backing detach or a V2.2 performance winner.

### 2026-10-09 — Strict read-p99 evidence and unrounded plateau qualification

- [x] Review offline V2.2 analyzer for evidence that directly
      substantiates its `read_count` and `read_p99_ns` claims;
      identify that legacy v1 trusted arbitrary self-reported
      values even on `kernel`/`physical`-labeled observations.
- [x] Add strict `swapz-drain-observation-v2` with a bounded sorted
      exact-value `read_latency_counts` array, integral per-value
      counts, a verified sum matching `read_count`, and an
      independently recomputed nearest-rank 99th percentile.
- [x] Deny both algorithmic candidate and provisional batch selection
      for v1 `kernel`/`physical` claims. Preserve synthetic v1
      as explicitly illustrative only; do not pool v1/v2 series.
      Even v2 self-labeled device evidence remains provisional and
      requires independently verified collector provenance.
- [x] Use unrounded sector-derived repeat medians in the 97% lower-
      device drain check; keep 6-decimal formatting for display only.
      Reject a fabricated 19.3999999-vs-20.0 MiB/s false plateau.
- [x] Add 12 new rootless adversarial tests; total offline suite:
      **27 tests**. Strict type, duplicate, sort, count, positive
      latency, sample ceilings, schema mixing, percentile edge
      and raw-threshold regression gates PASS.
- [x] Qualify both mandatory workflows against exact executable
      revision `6f42f13fb00296e8c809eee79b4780fb67a0cfec`:
      https://github.com/k1moradi/swapz/actions/runs/37917836052
      https://github.com/k1moradi/swapz/actions/runs/37917836051
- [ ] A future **independently authenticated** real collector must
      supply exact per-read latency evidence via the now-reviewed
      `swapz-drain-observation-v3` binary RLE sidecar format
      (no longer limited to 256 distinct timestamps). V3 integrity
      checks alone do not prove sample or kernel I/O origin.
      Verify backend isolation, monotonic window, real kernel
      quiescence, swap-in sample origin and 10,000+ reads/run.
- [ ] Separately investigate an intermittent existing combined
      CI failure: separate-process direct-dd role admission rejected
      a worker as `unconfirmed or duplicated` in earlier runs.
      Do not conflate a final green run with deterministic
      reliability; maintain fail-closed behavior.
- [ ] Do not run a live device sweep or nominate a V2.2 winner
      without separate operator authorization, qualified drain,
      repeated virtual and physical evidence and p99 review.
      V2.2 strategy/batch remains **UNDETERMINED**.

### 2026-10-09 — GNU 9.11 review and rootless recall/fixture-release qualification

- [x] Independently inspect Codex's GNU 9.11 qualification
      code, build records, five-role execution claim and exact
      GitHub Actions results; record trust-boundary gaps in
      `docs/codex-gnu-9-11-review-2026-10-09.md`.
- [x] Confirm Codex's follow-up `d168378c` removes unconfined
      candidate version execution and independently hashes both
      pinned build outputs before accepting the same-host record.
      This does NOT establish independent builder reproducibility.
- [x] Integrate GNU 9.11 source/ELF qualification-policy tests
      and build-record tests explicitly into both mandatory
      rootless workflows, with bounded timeouts and triggers.
- [x] Include Codex's newly added signed/ordered fixture-release
      **model** (five tests) in both workflows and retain its
      separate backing-authorization semantics.
- [x] Diagnose a previously intermittent positive rootless
      readback mismatch: a short synthetic writer was still
      populating the mapper's private ordinary file when readers
      started. Use a bounded, exact-inode/expected-byte fixture
      barrier rather than weaken worker READY or page-integrity
      attestation. No production mapper/worker code is changed.
- [x] Add bounded launch/WAIT error evidence, explicit
      unconfirmed, malformed and duplicate READY handle negative
      tests; denied synthetic backing remains preserved.
- [x] Repeat six independent five-role positive sessions in
      both workflows and fail on the first denial. Both
      exact-revision rootless workflows PASS at
      `f4c0be7eb7bc6d62c2d7485208018c527ee351af`:
      https://github.com/k1moradi/swapz/actions/runs/37941810631
      https://github.com/k1moradi/swapz/actions/runs/37941810576
- [ ] Confirm GNU 9.11 from an **independent controlled build
      host**, review production manifest and signing-key
      provisioning, and independently verify the trusted OS
      closure for dynamic OpenSSL/GPG verifiers.
- [ ] Implement an independently privileged, enforceable exact
      mapper owner, actual kernel-side I/O quiescence checks
      and a separately qualified full-stack backing-release gate.
      Session-HMAC report tests are policy models, not kernel data.
- [ ] Keep testing repeated positive recall sessions across
      different runner and scheduling conditions; six clean
      sessions do not prove flake-free behavior. Never authorize
      cleanup after a failed role receipt or partial writer.
- [ ] No V2.2 batch or strategy winner until explicitly authorized
      disposable virtual, then physical, drain/read-p99 experiments.

### 2026-10-09 — Exact-inode writer-readiness fault coverage and Codex owner audit

- [x] Independently inspect Codex's follow-up GNU build binding,
      `MapperLifecycleOwner` and session-HMAC fixture-release
      model; confirm passive executable inspection, two real output
      hashes and removal of mapper-only `cleanup_allowed`.
      See `docs/main-developer-fixture-owner-review-2026-10-09.md`.
- [x] Add a fail-closed **rootless test-only** writer-readiness
      controller latch: bridge and adapter deny further role
      admission, IPC client denies any cleanup and closes the
      control socket; never delete the synthetic backing marker.
- [x] Require pinned private regular-file identity and exact
      full-buffer content under a bounded deadline before positive
      reader launches. Refuse symlink, path/inode substitution,
      truncated/wrong output, interrupted reads and service exit.
- [x] Add ten adversarial writer-readiness cases, including
      refusal **after a real writer role was admitted**. Full
      separate-process suite **20/20 PASS**, strict positive
      independent five-role repetition **6/6 PASS** in both
      same-source workflows.
- [x] Exact source revision
      `08f28d60648ce501ad6c86648db4f486f404994d`:
      https://github.com/k1moradi/swapz/actions/runs/37957362142
      https://github.com/k1moradi/swapz/actions/runs/37957362071
      GNU policy 7+10, owner-release model 5 and NBD mock
      stress 25/25 remain included in combined rootless CI.
- [ ] Codex: implement separately privileged fixture owner and
      independently sourced kernel drain observation producer.
      A session HMAC on synthetic positive event reports does
      not establish a real kernel postcondition.
- [ ] Independent administrator: reproduce signed GNU source
      and static binary on a different controlled build host,
      review and provision the root-owned application manifest
      trust anchor, and verify OS verifier loader/library closure.
- [ ] Only after independent operator authorization, qualify
      disposable real DM mapping/suspend/removal and exact
      holder/loop/NBD absence. Rootless writer polling and
      service pidfd reaping NEVER authorize real backing deletion.
- [ ] V2.2 performance comparison and read-p99 qualification
      remain blocked; winner UNDETERMINED.

### 2026-10-09 — Broker test CI coverage, model risks and handoff

- [x] Review the Codex `2f74389f` broker/evidence producer,
      typed mapper release-report implementation, exact changed
      files and claimed test counts. Record independently confirmed
      security findings in
      `docs/main-developer-broker-review-2026-10-09.md`.
- [x] Gate `recall-fixture-owner.py` and its 15-case rootless test
      suite in both mandatory combined and teardown workflows.
      Expand teardown push paths for the new module and test.
- [x] Add three fail-fast **fresh-process** repetitions of the full
      15-case broker suite to **each** mandatory workflow, retaining
      all existing recall/GNU/NBD/pressure/drain gates.
- [x] Exact executable SHA
      `5c8acc47efe40e07baa8dd5fa8090dd453d5e965`:
      [combined PASS](https://github.com/k1moradi/swapz/actions/runs/37995672935);
      [teardown PASS](https://github.com/k1moradi/swapz/actions/runs/37995673013).
      Both logs confirm broker 15+3×15 rootless cases and
      direct recall process 6/6; combined NBD stress 25/25.
- [ ] **P0 — Codex:** Bind the immutable **five-role** recall
      profile and verified phase/readback completion before any
      positive broker backing authorization. Current model
      explicitly permits release after only `writer,a,b`.
      Require denied zero/truncated/reordered/duplicate role
      inventories and unmatched handles.
- [ ] **P0 — Codex:** Own ambiguous child launches before handle
      acknowledgment; all created synthetic child PIDs/pidfds
      must be registered and reaped or leave session irrevocably
      backing-preserving. Current best-effort stop tracks only
      handles already returned by `_worker_launcher`.
- [ ] **P1 — Codex:** Replace fake peer-identity callbacks with
      rootless Unix-socket kernel credential verification, and
      correct or remove the permanently zero
      `_request_inflight` pseudo-observation.
- [ ] **P1 — Codex:** Model upper-to-lower DM dependencies and
      NBD disconnect/absence separately from the current
      one-mapper/loop fixture. Do not claim rootless HMAC evidence
      proves actual kernel or host-root authority.
- [ ] **External:** independently reproduce GNU static binary,
      provision independently reviewed production signing/trust,
      and obtain explicit authorization before any real virtual
      device, kernel drain or physical read-p99 qualification.
      Production mapper admission remains disabled; V2.2 winner
      remains UNDETERMINED.

### 2026-10-09 — Main-developer independent CI safety maintenance

- [x] Audit teardown workflow push triggers against **all runtime
      scripts referenced by executed job steps**, not only test
      entrypoints. Found `tests/runtime/no-discard-livegc.sh`
      omitted even though the workflow syntax-checked it.
- [x] Add the missing trigger and explicitly trigger on
      `tests/runtime/rootless-workflow-contract-test.py` updates.
- [x] Implement six rootless standard-library workflow-contract
      tests asserting complete script-trigger coverage, bounded
      execution of critical GNU/recall/drain/fixture-owner tests,
      three fail-fast broker repetitions, six fail-fast positive
      recall repetitions, and read-only workflow token rights.
      Inject deliberate missing trigger / disabled gate / non-failfast
      mutations to prove the contract denies unsafe edits.
- [x] Make the contract a mandatory early gate in both workflows.
      **Exact executable SHA**
      `866002a13e74a8800a18c1cd3a3dc43fb9cf6292`:
      [teardown PASS](https://github.com/k1moradi/swapz/actions/runs/37996532817),
      [combined PASS](https://github.com/k1moradi/swapz/actions/runs/37996532854).
      Each ran 6/6 new contract tests, positive recall 6/6,
      and broker repeats 3/3; combined NBD 25/25.
- [x] Extend mandatory CI-maintenance contract to the
      **standalone rootless NBD** workflow: protect its static
      syscall-isolation gate, 25 strict fresh-process NBD stress
      repetitions, pidfd-owned mock tests, exact push triggers,
      and NBD-workflow-to-teardown trigger. The suite now runs
      11/11 in all three workflows at exact executable commit
      `00fbf74f155d537664b16252b92386636a34cc44`:
      [NBD PASS](https://github.com/k1moradi/swapz/actions/runs/37996938322),
      [teardown PASS](https://github.com/k1moradi/swapz/actions/runs/37996938227),
      [combined PASS](https://github.com/k1moradi/swapz/actions/runs/37996938277).
      No actual NBD attachment or privileged device I/O.
- [x] Enforce **offline exact-artifact/run identity consistency**
      for supplied V2.2 JSONL plus a separate bounded manifest,
      including exact file/line digests, one claimed 40-hex Git
      revision, session, collector, lower-device, backend, profile,
      evidence and unique ordered run IDs. Never pool mixed records.
      Reject unauthenticated measured V1 p99. This is NOT
      cryptographic provenance, physical device proof or a
      production selection decision. See
      `docs/v22-evidence-bundle-offline.md`.
- [ ] Obtain independently **authenticated collector provenance**
      and root-controlled production trust for actual measurements;
      reconcile original measurement artifacts with trusted Git
      tree identities and physical device inventory before any
      physical throughput/p99 qualification.
- [ ] Continue rootless regression monitoring and separate-process
      fault diagnostics when Codex changes the trusted-owner
      architecture. All live device qualification and backing
      release remain blocked.

### Additional independent, non-overlapping work while Codex owns the broker

- [x] **Offline evidence-bundle consistency:** independent
      rootless checker and **20 synthetic adversarial tests**
      reject conflicting asserted Git SHA, duplicate/missing run
      IDs, run order, claimed device/session/collector identity,
      malformed V2 nearest-rank p99 or altered original bytes.
      The manifest is self-reported and cannot authenticate the
      claimed lower device. Full gate passes in both workflows
      at `cf0752da282465bdf63b763c2b5621ce693b46a7`:
      [teardown](https://github.com/k1moradi/swapz/actions/runs/37997610540),
      [combined](https://github.com/k1moradi/swapz/actions/runs/37997610606);
      [standalone NBD](https://github.com/k1moradi/swapz/actions/runs/37997610596)
      also passed at that exact revision.

- [x] **Concurrent broker finalize denial — rootless model only:**
      [issue #2](https://github.com/k1moradi/swapz/issues/2) closed after
      Codex's `ae5f812e7647236ec91e8cae2102cceef0d6d9d5` monotonic
      abort/checkpoint fix and main-developer stronger independent contract
      `1d026ae61dbaa7717cdb64ee8fe744f60811c648`.
      [combined](https://github.com/k1moradi/swapz/actions/runs/38003419963)
      and [teardown](https://github.com/k1moradi/swapz/actions/runs/38003420160)
      green at exact independent test SHA; rootless closure is not
      privileged kernel drain or backing-release qualification.
- [x] **Standalone CI artifact traceability:** record exact
      workflow/source tree identity and selected safety-test
      marker inventory in a machine-readable, bounded source-only
      report; do not mistake the report for cryptographic
      attestation or external trust.
- [x] **Synthetic recall failure telemetry:** analyze bounded
      launch failure and service-error diagnostics across
      repeated rootless sessions; never retry over a failed
      positive session or turn a missing receipt into approval.
- [x] **Future Codex review:** independently test complete five-role
      broker lifecycle and stable owned-child startup once those
      interfaces land, without editing Codex-owned files or
      authorizing kernel/device operations.

### Parallel follow-ups — integrity without privileged device access

- [x] Make the standalone NBD gate rerun when either
      `rootless-teardown.yml` or `rootless-combined.yml`
      changes; the NBD workflow invokes the shared
      `rootless-workflow-contract-test.py` and must not
      silently accept a stale version of its dependencies.
      Its contract now includes a negative test for dropped
      joint-workflow triggers (**12/12 tests** in each
      exact-source workflow).
- [x] Develop a deterministic **source-only CI evidence
      inventory** recording SHA, workflow name and required
      test completion markers with explicit limitations:
      no locally generated file can attest trusted
      external identity by itself. Keep this separate
      from Codex's privileged owner/evidence producer.
- [x] Add offline, bounded **telemetry fault classification**
      for observed pidfd/recall launch and WAIT denial
      categories without creating positive cleanup authority.
      Codex owns the broker implementation.

### 2026-10-09 — Main-developer lossless V3 latency evidence

- [x] Introduce `swapz-drain-observation-v3` with a bounded
      exact 16-byte per-distinct-nanosecond-count sidecar, direct
      original-byte SHA-256 validation, monotonic sorted counts, and
      integer nearest-rank p99 recomputation, keeping v1/v2 unchanged.
- [x] Bound V3 parsing to at most 10,000,000 reads per run and
      512 MiB of sidecar bytes per invocation, with a fixed-size
      streaming parser, retained regular-file descriptors and
      sibling-path traversal protection. Rootless test suite 39/39.
- [x] Enforce fail-closed V3 exclusion from the legacy JSONL-only
      bundle manifest, whose schema cannot bind binary sidecar
      bytes. Evidence-bundle policy suite now 22/22.
- [x] Verify mandatory joint workflow contracts (15/15)
      and old plateau suite (31/31); all the above passed at
      `ea18d3b6d81a5d307a855ce45228d3aabb07915f`:
      [combined](https://github.com/k1moradi/swapz/actions/runs/38026623024)
      [teardown](https://github.com/k1moradi/swapz/actions/runs/38026623030).
- [x] Implement a separate V3-aware measurement bundle schema
      `swapz-v22-evidence-bundle-v2` binding original sidecar bytes
      and digest/length to each run's session, collector, source,
      backend/profile, and claimed device identities. 43 adversarial
      bundle tests and 16 workflow-contract tests passed on exact
      `98370f95e3cb6a1e708ecde242946c47c1b276e4`:
      [combined](https://github.com/k1moradi/swapz/actions/runs/38027940132),
      [teardown](https://github.com/k1moradi/swapz/actions/runs/38027940134).
      This is offline hash consistency, not authenticated collector or
      production trust. Legacy bundle v1 still rejects V3.
- [ ] Independently audit kernel V2 staged-write generation
      invalidation and live GC relocation under concurrent I/O,
      without enabling production mapper/device operations.

### 2026-10-09 — Independently implemented V3 bundle integrity binding

- [x] Add `tests/runtime/v22-evidence-bundle-v3.py`,
      exact v2 manifest schema, one pinned directory, bounded regular-file
      checks, one-use sidecar filenames, strict run/source/session/collector/
      backend/device assertions and original-byte SHA-256 binding.
- [x] Add 43 rootless adversarial tests and mandatory 35-second
      source-only test steps in both joint workflows. Enforce the gate
      with a negative workflow-contract test (16 total).
- [x] Exact executable SHA
      `98370f95e3cb6a1e708ecde242946c47c1b276e4`,
      all 3 workflows PASS:
      [combined](https://github.com/k1moradi/swapz/actions/runs/38027940132),
      [teardown](https://github.com/k1moradi/swapz/actions/runs/38027940134),
      [standalone NBD](https://github.com/k1moradi/swapz/actions/runs/38027940133).
- [ ] Independently authenticate collector signing keys, device and
      kernel drain event provenance, and signed binary sidecar bundle
      origin before accepting any real benchmark nomination.
### 2026-10-09 — Kernel logical-range preflight correction

- [x] Correct the V2.2 discard partial-invalidation hazard: validate
      the entire sector_t logical range before flushing the pack,
      advancing a generation or invalidating any mapping. Reject
      an out-of-range tail atomically at the source-policy level.
- [x] Avoid narrowing high read/write sector_t page indexes to u32
      before exact alignment and logical-page bounds validation.
- [x] Compile and execute the two actual production C range guards
      as short-lived rootless userspace code with 30 boundary,
      mutation and source-order contract tests. Keep kernel module
      and real block-device operations disabled.
- [x] Run the mandatory guard on kernel/dm-swapz.c changes in both
      rootless combined and teardown workflows, with negative
      workflow trigger/execution checks (18 workflow-contract tests).
      Exact executable commit:
      `af2b394e90805a7f9647c68cc58659ee83f8ff95`.
      [combined](https://github.com/k1moradi/swapz/actions/runs/38028920840)
      [teardown](https://github.com/k1moradi/swapz/actions/runs/38028920862).
- [ ] Independently audit live-GC segment relocation against stale
      generation publication and asynchronous write failures,
      with reproducible rootless model/source contracts.
- [ ] Separately review full kernel build, real DM discard/flush/FUA
      behavior, GC concurrency, memory-reclaim safety and production
      qualification only under separately authorized infrastructure.
### 2026-10-09 — GC source-buffer alias corrected

- [x] Audit staged-generation and live-GC relocation source path. A multi-live
      compressed victim block formerly lived in `context->io_buffer`, while
      nested submission/compaction could overwrite that buffer before later
      records of the same source block were decoded.
- [x] Add one preallocated 4 KiB `gc_source_buffer` for the entire victim
      block's decode lifetime, pass explicit source bytes to the shared
      decoder, preserve readback's existing io_buffer, and free the snapshot
      on all context teardown/failed-construction paths. No allocations
      were added to the GC hot path and no on-disk format was changed.
- [x] Execute verbatim production decoder + generation predicate in a
      rootless C harness with synthetic container records and a stub
      decompressor, including the alias counterexample, no-alias
      preservation, negative allocation/free and buffer-binding mutants,
      stale-generation tests and source-level victim reclamation barriers.
      New GC test suite 17/17; kernel-range suite 30/30; workflow contract
      suite 19/19 in both mandatory workflows on exact executable SHA
      `0d7e51a0273ec6124f7922567612cf0c2e00e05d`:
      [combined](https://github.com/k1moradi/swapz/actions/runs/38032711626),
      [teardown](https://github.com/k1moradi/swapz/actions/runs/38032711514).
- [ ] Audit the generation increment before nested GC when foreground
      allocation/relocation occurs, using source-anchored fault injection;
      current evidence does not establish a second confirmed bug.
- [ ] Qualify live kernel GC, LZ4 compression/decompression,
      lower-I/O timeouts, batch FUA/flush, physical source identity, and
      backing release only under separately authorized infrastructure.

### 2026-10-10 — GC compressed output lifetime (second nested alias)

- [x] Fix another nested GC/compaction scratch collision: GC formerly
      passed `context->compressed_buffer` into `swapz_store_page`;
      pack rollover or physical-block reservation could call
      `swapz_compact_fill_buffer` before the compressed payload was
      copied into `pack_buffer`. The compactor reused that same scratch.
- [x] Add one preallocated 4-KiB `gc_compressed_buffer` with
      constructor fail-closed check and common destructor unwind.
      Preserve the already isolated `gc_source_buffer`, foreground
      `write_compressed_buffer`, and existing compactor scratch.
      No hot-path allocation, generation scheme, mapping layout, or
      on-disk record format changed.
- [x] Compile the verbatim production `swapz_add_compressed_record`
      C function in an unprivileged harness, exercise actual staging
      with first-pack and rollover scratch-overwrite injection,
      intentional old-alias counterexamples, error paths,
      and allocation/source-binding negative mutations.
      **15/15 new GC compressed contract tests**, **17/17 GC source
      tests**, **30/30 kernel range tests**, and **20/20 workflow
      contract tests** passed on exact executable SHA
      `f5379bc048b868be88210023229cdd133910c46c`:
      [combined](https://github.com/k1moradi/swapz/actions/runs/38033528668),
      [teardown](https://github.com/k1moradi/swapz/actions/runs/38033528694),
      [standalone NBD](https://github.com/k1moradi/swapz/actions/runs/38033528707).
- [ ] Revisit nested foreground generation increment and GC relocation
      under failpoints, generation wrap, failed or timed-out lower I/O,
      flush/FUA and real kernel concurrency; no production claims yet.

### 2026-10-10 — Foreground generation transaction under nested GC

- [x] Review the foreground write's transient generation advance and
      reentrant GC source path without inventing a data-loss defect.
      Existing previous-generation commit and failed-store rollback
      ordering were retained because the source review did not prove
      that transient GC relabeling itself loses data.
- [x] Add 21 rootless regression/negative tests that compile actual
      production C range/current-record/previous-generation/write
      functions with deterministic nested-GC and lower-failure
      substitutes. Cover uncommitted pack/ref barriers, rejected
      lower batch, source-bound GC, failed new-write rollback,
      U32_MAX rollover, bad sectors and five negative mutations.
- [x] Add independently executable `rootless-kernel-source.yml`
      so kernel correctness qualification runs even when Codex's
      supervisor/service integration is under development.
      Exact executable SHA
      `ea41bae05b23d62128013864229ebf9a28658a46`:
      [isolated kernel source qualification](https://github.com/k1moradi/swapz/actions/runs/38034762176)
      PASS (21 generation + 30 range + 17 GC source + 15 GC output).
- [ ] Cross-system combined and teardown gates still need a green
      integration revision. As of the preceding
      `9707bffaee190ec991bf1c99e62d72763f5322ff`,
      both were blocked in Codex's recall IPC adapter tests by a
      strict worker-result field-schema mismatch, before the
      kernel generation gate. Do not count this as kernel CI green.
- [ ] Separately qualify real kernel GC, asynchronous dm-io callback
      failure/timeout, physical block readback, REQ_FUA/PREFLUSH and
      privileged teardown under fresh external authorization.

### 2026-10-10 — Async reaper, timeout and callback ownership (source-only)

- [x] Independently audit lower-write submission, watchdog reporting,
      late callbacks, reaper finalization, staged-data retention,
      upper BIO exactly-once completion and teardown callback lifetime.
      No proven new production-kernel defect: preserved production
      reaper/worker code rather than risking speculative changes.
- [x] Compile and run seven verbatim production C functions in a
      bounded rootless harness with stubbed Linux synchronization,
      mapping and BIO primitives. All **22/22** async scenarios and
      source-mutant cases passed on exact executable SHA
      `7ae05dedb66bdea71f1a39a2ced510c8a5f9628e`.
- [x] Require the new async test on the isolated kernel source
      workflow and both mandatory joint workflows; expand the
      workflow-contract suite to **22/22** negative/positive checks.
      [Isolated kernel source](https://github.com/k1moradi/swapz/actions/runs/38035848146):
      PASS; [combined](https://github.com/k1moradi/swapz/actions/runs/38035848163):
      PASS; [teardown](https://github.com/k1moradi/swapz/actions/runs/38035848200):
      PASS, all at exact SHA. Combined NBD stress 25/25.
- [ ] Kernel in-situ injection of asynchronous write failure,
      boundary completion races, never-completing lower requests,
      true LZ4 readback, and REQ_FUA/PREFLUSH durability under
      independently authorized disposable infrastructure.

### 2026-10-10 — Source-qualified PREFLUSH and FUA batch ordering

- [x] Audit production upper dispatch, compressed/raw stage, mixed
      FUA/non-FUA flag aggregation, lower dm-io write flags,
      flush barriers and async upper BIO completion. No confirmed
      new correctness defect, so no speculative production change.
- [x] Add `tests/runtime/swapz-flush-fua-contract-test.py`
      compiling the real dispatch, flush and stage C functions.
      9/9 tests cover 20 bounded C scenarios and six negative
      source mutants, including preflush failure, FUA early-ack
      exclusion and mixed-batch flag retention.
- [x] Mandate the bounded gate in kernel-only, combined and
      teardown CI and add a workflow-contract negative test
      (now 23/23).
      All exact executable SHA
      `83d2e41d7d72e7dbedb3ad5860b0dc4359aac988`:
      [kernel 38039036487](https://github.com/k1moradi/swapz/actions/runs/38039036487),
      [combined 38039036567](https://github.com/k1moradi/swapz/actions/runs/38039036567),
      [teardown 38039036488](https://github.com/k1moradi/swapz/actions/runs/38039036488),
      [NBD 38039036489](https://github.com/k1moradi/swapz/actions/runs/38039036489);
      PASS. Combined NBD stress 25/25.
- [ ] Real kernel dm-io FUA/flush write-fault injection, media
      persistence and independent device I/O quiescence remain
      separately authorized work; rootless C flags are not
      proof of physical durability.

### 2026-10-10 — Mapping replacement failure-state accounting

- [x] Fix `swapz_install_mapping` unaccounting the old live mapping
      *before* validating replacement block bounds and capacity.
      Reject the invalid replacement without decrementing the
      still-authoritative old block or segment; permit a full
      same-physical-block replacement when the old record makes space.
- [x] Compile the five actual production C mapping helpers with
      bounded metadata and exercise 16 success/failure scenarios.
      Execute a second old-ordering mutation binary to prove that
      invalid new blocks previously left old live-reference
      accounting inconsistent. New suite 7/7.
- [x] Require mapping accounting in isolated kernel, combined,
      teardown CI and the workflow-contract suite (24/24).
      Exact executable SHA
      `89ddc5fbd1a98979aa6c661085370a6bc0cff53d`:
      [kernel](https://github.com/k1moradi/swapz/actions/runs/38039927758),
      [combined](https://github.com/k1moradi/swapz/actions/runs/38039927690),
      [teardown](https://github.com/k1moradi/swapz/actions/runs/38039927750),
      all PASS; combined NBD 25/25.
- [ ] Exercise real GC mapping/counter publication failures and
      segment recycle on separately authorized disposable kernel
      infrastructure; rootless failure-state checks are not device
      corruption, device drain or physical persistence evidence.
