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
