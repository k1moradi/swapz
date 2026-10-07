# swapz V2.2 — Streaming Strategy Validation and Plateau Benchmark

## Role

You are the secondary validation and benchmarking agent for `swapz`.

The primary developer owns feature development, architecture decisions, behavioral kernel
fixes, performance tuning, allocator/format changes, and optimization work. Your main job is
to build, stress, benchmark, measure, reproduce, and report.

### Compile/build-fix exception

You **may** make, commit, and push a minimal source change when the current candidate cannot
build for an obvious compile/build reason and the correction does not intentionally change
runtime behavior.

Allowed examples include:

- missing forward declarations or includes;
- mechanical type/signature/API compatibility fixes;
- obvious format/type mismatches;
- unused-variable/declaration-order cleanup required by the configured warning policy;
- similarly narrow build-system corrections.

Requirements for such a fix:

1. keep the diff as small and mechanical as possible;
2. do not redesign code while fixing the build;
3. do not change algorithms, I/O policy, synchronization semantics, data layout, GC policy,
   streaming behavior, compression strategy, performance parameters, or feature scope;
4. run the source-invariant gate and clean build immediately afterward;
5. commit the build fix separately with a clear `fix: build ...` or `cleanup: build ...`
   message;
6. push it to `main` and report the exact commit and diff summary;
7. if the required correction might affect runtime semantics, stop and hand it back to the
   primary developer instead of guessing.

You may also correct an obvious mechanical test-harness defect. Preserve the original
failure, keep the correction minimal, and report the exact diff.

Feature development and substantive kernel bug fixing remain out of scope for Codex.

### Review-after-fix workflow

When Codex makes an allowed minimal compile/build or mechanical test-harness fix, the
workflow is:

1. make the smallest possible fix;
2. run the source-invariant gate and the focused test(s) relevant to that fix;
3. if those pass, commit and push the fix as a separate commit;
4. report:
   - exact commit SHA;
   - exact files changed;
   - concise rationale;
   - focused tests run and their results;
   - whether any runtime semantics were intentionally changed;
5. stop feature work and hand the result back to the primary developer.

The primary developer will then review the exact diff **and the surrounding code**, not only
the commit message or test result. The primary developer may keep, narrow, correct, or
revert the Codex fix if it:

- is broader than necessary;
- changes runtime semantics unexpectedly;
- alters synchronization/ownership behavior;
- weakens an assertion or test fixture;
- hides a real failure;
- changes architecture, performance policy, or feature scope.

A Codex fix passing its focused test is therefore **provisional until primary-developer
review**.

A failure is useful. Do not optimize the report toward success.

## Mandatory checkout gate

Start with:

```bash
cd ~/swapz
git restore .
git fetch origin --prune
git switch main
git reset --hard origin/main
git status --short
git rev-parse HEAD
git rev-parse origin/main
git branch --show-current
grep 'PACKAGE_VERSION="0.2.2"' dkms.conf
```

Requirements:

```text
branch = main
HEAD = origin/main
PACKAGE_VERSION = 0.2.2
```

Verify V2.2 features are present:

```bash
grep -n 'SWAPZ_STRATEGY_IMMEDIATE' kernel/dm-swapz.c
grep -n 'SWAPZ_STRATEGY_OPPORTUNISTIC' kernel/dm-swapz.c
grep -n 'SWAPZ_STRATEGY_STAGED' kernel/dm-swapz.c
grep -n 'swapz_stream_io_complete' kernel/dm-swapz.c
grep -n 'staged_read_hits' kernel/dm-swapz.c
grep -n 'staged_early_completions' kernel/dm-swapz.c
grep -n 'staged_cancellations' kernel/dm-swapz.c
```

If the checkout does not match, stop with:

```text
STOP — WRONG CHECKOUT
```

Your final report must begin:

```text
TESTED_BRANCH=main
TESTED_HEAD=<actual origin/main SHA>
CANDIDATE=V2.2_STREAMING
```

## BLOCKER-FIRST rerun

The previous V2.2 run stopped correctly on a live-GC forward-progress failure. Before any
performance work, validate the candidate completion-wakeup fix.

The failing pre-fix state is preserved on branch:

```text
v2.2-blocked
8b7c519f05e4d03cbb269c4080e6707866b843c1
```

That branch includes only the staged-recall fixture correction after the original V2.2
kernel candidate. The old failing kernel itself is unchanged from
`b66e1d31de473b224744c50698305a312b8f888e`.

### If the old blocked mapping/module is still loaded

The prior tester intentionally left the stuck live-GC mapping and module untouched.

Before replacing it, take one final read-only snapshot:

```bash
date --iso-8601=seconds
ps -eo pid,stat,wchan:32,comm,args | grep -E 'reference|swapz|submit_bio_wait' || true
sudo dmsetup ls --tree
sudo dmsetup status 2>/dev/null || true
sudo dmsetup table 2>/dev/null || true
cat /proc/pressure/io
cat /proc/pressure/memory
dmesg | tail -200
```

If the blocked writer PID is identifiable, also record:

```bash
sudo cat /proc/<PID>/stack
```

Do not spend more time waiting for the old run.

Then terminate only the disposable validation writer/targets created by the prior test,
remove the corresponding temporary swapz/loop stack, unload the old `dm_swapz` module,
and confirm no V2.2 test mapping remains. Do not touch unrelated system swap or physical
devices.

### Current asynchronous ownership hardening

The earlier `completion_work` experiment is obsolete and must **not** be present in the
current candidate.

The current V2.2 candidate combines these ownership/progress fixes:

- `alloc_ordered_workqueue(..., WQ_MEM_RECLAIM, ...)` is used for the serialized
  swapz state machine; `WQ_UNBOUND` is forbidden.
- the kernel `struct completion` is the sole lower-I/O completion token;
  `io_done` is forbidden.
- the dm-io callback directly requeues `io_work`; no separate
  `completion_work` object remains.
- every async dm-io callback holds an `async_callbacks` lifetime reference until its
  final access to the target context; suspend/teardown waits for that count to reach zero.
- fatal target paths explicitly complete every non-early-completed upper BIO still owned
  by the compression pack or unsent fill buffer instead of silently stranding it.
- the final worker reap failure loops back through that failure-drain path instead of
  exiting with an owned BIO.
- lower swap traffic preserves `REQ_SWAP`; staged early completion is forbidden for
  `REQ_FUA` writes, and a batch containing FUA propagates it to the lower request.
- a write which fails before transferring into a stream buffer restores the previous
  logical generation.

Run the source-only invariant gate whenever the current module cannot yet be loaded:

```bash
bash tests/runtime/source-invariants.sh
```

It must report:

```text
V2.2 async/source invariants: PASS
```

These changes are still unvalidated until the freshly built module passes the focused
runtime progress gate after an explicitly authorized reboot.

### Reboot authorization policy

A host reboot is **never implicitly authorized** by this validation plan.

If a stuck `D`-state process, pinned Device Mapper target, or pinned `dm_swapz` module
cannot be safely removed without rebooting, Codex must:

1. preserve a read-only diagnostic snapshot;
2. stop destructive/runtime cleanup attempts;
3. leave unrelated system swap and physical devices untouched;
4. report `NEEDS_EXPLICIT_REBOOT_AUTHORIZATION`;
5. wait for the operator's explicit permission before issuing any reboot command.

Other agents or workloads may be active on this host. Do not infer reboot permission from
the fact that the machine is a test host, from prior validation instructions, or from an
earlier generic authorization to run tests.

Source-only build, model, sanitizer, and repository checks may continue while waiting, as
long as they do not replace or unload the pinned runtime module.

### Post-reboot module identity gate

Only after the operator has explicitly authorized and completed the reboot, first confirm the stale disposable state is gone:

```bash
sudo dmsetup ls --tree
lsmod | grep '^dm_swapz' || true
losetup -a | grep 'swapz-v21-live-gc' || true
swapon --show
```

Do not remove or modify unrelated system swap.

Fetch/reset to current `origin/main`, rebuild the kernel module, and load the freshly built
artifact directly rather than relying on an older installed copy:

```bash
sudo rmmod dm_swapz 2>/dev/null || true
sudo insmod kernel/dm-swapz.ko
```

Record:

```bash
sha256sum kernel/dm-swapz.ko
modinfo -F version kernel/dm-swapz.ko
modinfo -F srcversion kernel/dm-swapz.ko
cat /sys/module/dm_swapz/srcversion 2>/dev/null || true
```

If both source-version values are non-empty, they must match. Also record the exact
`git rev-parse HEAD` used to build the module.

Do not run the focused regression until the old mapping is gone and the loaded module is
unambiguously the freshly built candidate.

### Static async-ownership gate

Before runtime testing, verify:

```bash
bash tests/runtime/source-invariants.sh
grep -n 'alloc_ordered_workqueue' kernel/dm-swapz.c
grep -n 'try_wait_for_completion' kernel/dm-swapz.c
grep -n 'async_callbacks' kernel/dm-swapz.c
grep -n 'swapz_fail_unsent_upper_bios' kernel/dm-swapz.c
! grep -n '\bio_done\b' kernel/dm-swapz.c
! grep -n '\bcompletion_work\b' kernel/dm-swapz.c
! grep -n 'WQ_UNBOUND' kernel/dm-swapz.c
```

Also capture every swapz warning from the fresh `W=1` build verbatim, including file,
line, option, and diagnostic text. Do not summarize warnings only by category.

Do not claim any source-reviewed race fixed until the focused runtime regression below
passes on a freshly loaded module.

### Pre-reboot source-only hardening gate

While an older module is pinned and reboot permission has not been granted, run only:

```bash
git fetch origin --prune
git reset --hard origin/main
bash tests/runtime/source-invariants.sh
make -C kernel clean KDIR=/lib/modules/$(uname -r)/build
make -C kernel KDIR=/lib/modules/$(uname -r)/build W=1
make -C userspace clean && make -C userspace
make -C tests clean && make -C tests test
```

Also run the model under ASan/UBSan.

Do not attempt to unload/replace the pinned module and do not reboot without explicit
operator authorization.

The current source must contain all of these pre-reboot hardening properties:

- completion token is consumed exactly once;
- no `io_done` or obsolete `completion_work` path remains;
- async lower writes have an independent reclaim-safe delayed watchdog;
- a timed-out lower write fails non-early upper BIOs without recycling the physical buffer;
- a late completion after target failure cannot unaccount/destroy the previous good mapping;
- a same-slot rewrite persists any uncommitted previous generation before advancing the slot generation.

After a future explicitly authorized reboot, add this regression to the correctness gate:

```bash
sudo bash tests/runtime/staged-rewrite-fault.sh
```

It must prove that an early-completed staged generation survives a failed replacement of
the same logical page.

### Focused gate

After building the current `origin/main`, run:

```bash
sudo bash tests/runtime/async-progress.sh
```

Run it **three times**.

Each run must:

```text
finish within 120 seconds
failed=0
gc_victims > 0
gc_pages > 0
exact live-set readback PASS
no hung upper BIO
no residual lower/upper request after completion
```

Inspect kernel logs after every run.

If any run times out or hangs:

```text
BLOCKED — CORRECTNESS FAILURE
```

Stop. Do not benchmark.

### Broader correctness gate after focused PASS

Only after all three focused runs pass:

```bash
sudo bash tests/runtime/correctness.sh
sudo bash tests/runtime/buffer-recall.sh
sudo bash tests/runtime/staged-write-fault.sh
sudo bash tests/runtime/no-discard-livegc.sh
sudo bash tests/runtime/read-fault.sh
sudo bash tests/runtime/lifecycle.sh
sudo bash tests/runtime/pressure.sh
```

The nine-page staged-recall fixture is now the checked-in fixture. Do not revert it to 96
pages merely to recreate the old timing miss.

Only after these correctness gates pass may the strategy/plateau performance phases below
resume.

## V2.1 reference

The last software-validated baseline is branch:

```text
v2.1
c841a589a44ada3561a8bbed83a4db86e530ee1c
```

Do not modify it.

## What V2.2 is testing

V2.2 keeps the V2/V2.1 1 MiB segment-local GC architecture.

It compares three upper-write policies:

```text
immediate
    no useful streaming
    control path

opportunistic
    at most one asynchronous lower write in flight
    fill the second preallocated buffer while the first is writing
    do not intentionally sleep merely to make a batch larger
    upper write completes after physical persistence

staged
    same double-buffer pipeline
    compressed foreground writes may complete after their authoritative
    compressed copy is resident in a bounded stream buffer
    reads may be satisfied from filling or in-flight RAM
```

The physical batch ceiling is configurable from 4 KiB through 1 MiB.

There is no assumed 128 KiB or 256 KiB sweet spot. The test must find the throughput/latency
plateau empirically.

The current V2.2 candidate deliberately keeps the V2.1 4 KiB on-disk compressed-container
format. A separate byte-tight extent-format experiment was removed from the candidate so
streaming strategy and disk-format effects are not confounded.

## Important staged-mode semantic rule

A READ does not imply the swap slot is free.

If a page is demanded while its current generation resides in either stream buffer, swapz
may return it immediately from RAM. The record remains authoritative until logical DISCARD
or overwrite makes that generation stale.

Only a genuinely stale unsent generation may be removed/repacked before disk submission.

If an early-completed compressed write later suffers lower I/O failure, staged RAM must
remain readable so swap-in/swapoff can recover it. New writes may be rejected.

## Phase 1 — Environment and build

Record:

```bash
uname -a
cat /proc/version
getconf PAGESIZE
gcc --version
clang --version
ld --version
fio --version
dmsetup version
```

Build:

```bash
make -C kernel clean KDIR=/lib/modules/$(uname -r)/build
make -C kernel KDIR=/lib/modules/$(uname -r)/build W=1

make -C userspace clean
make -C userspace

make -C tests clean
make -C tests test
```

Run the model under ASan + UBSan.

Zero swapz source warnings are expected from the GCC build.

If the module does not compile, stop kernel runtime testing and report the first meaningful
diagnostic.

## Phase 2 — Static strategy sanity

Create small disposable loop targets for:

```text
immediate 4
opportunistic 4
opportunistic 64
opportunistic 256
opportunistic 1024
staged 4
staged 64
staged 256
staged 1024
```

Verify target creation and status fields:

```text
strategy=
batch_kib=
fill_id=
inflight_id=
inflight_blocks=
fill_blocks=
pack_records=
async_cb=
buf0_state=
buf0_blocks=
buf1_state=
buf1_blocks=
staged_hits=
staged_early=
staged_cancel=
failed=
```

Invalid strategy names and batch sizes outside 4..1024 KiB or not 4 KiB aligned must be
rejected.

## Phase 3 — Re-run V2.1 correctness gates

Before judging performance, run the established software coverage on V2.2:

```bash
sudo ./scripts/loop-smoke.sh
sudo ./scripts/rotation-regression.sh
sudo bash ./scripts/write-batch-regression.sh

sudo bash tests/runtime/correctness.sh
sudo bash tests/runtime/no-discard-livegc.sh
sudo bash tests/runtime/read-fault.sh
sudo bash tests/runtime/lifecycle.sh
sudo bash tests/runtime/pressure.sh
```

Adapt only invocation arguments when required to select a V2.2 strategy; do not alter
correctness assertions.

Run the long/randomized coverage at least once for `opportunistic` and once for `staged`.

Any stale read, corruption, WARN, BUG, Oops, hung task, deadlock, refcount failure, or
swapoff failure is a correctness blocker.

## Phase 4 — Required staged-buffer race test

Run:

```bash
sudo bash tests/runtime/buffer-recall.sh
```

It must prove all three user-requested cases:

1. demand data from Buffer A while Buffer B is filling;
2. demand data from Buffer B while Buffer A is being written;
3. demand data from both buffers while one lower write remains active.

Requirements:

```text
exact readback
staged_hits increases for each staged recall
recall latency remains clearly below delayed lower-read latency
failed=0
```

The test also performs a later logical DISCARD of a buffered generation.

Requirements:

```text
staged_cancel > 0
stale unsent data is not later published
remaining live records are still correct
```

A READ by itself must not be treated as invalidation.

## Phase 5 — Early-completion lower-failure safety

Run:

```bash
sudo bash tests/runtime/staged-write-fault.sh
```

This is mandatory.

The lower device intentionally rejects the asynchronous write after the compressed upper
write has already early-completed.

Requirements:

```text
upper compressed write initially succeeds
lower asynchronous failure is later observed
failed=1
staged_early > 0
the exact early-completed page remains readable from staged RAM
staged_hits > 0 after readback
new writes are rejected after failure
no crash/deadlock/use-after-free
```

If early-completed data is lost after lower failure:

```text
BLOCKED — CORRECTNESS FAILURE
```

## Phase 6 — Analytical plateau sizing

Run:

```bash
python3 bench/request-plateau.py --bandwidth 20
```

Record the complete output.

The expected qualitative result is that the plateau moves upward as command latency rises;
there is no fixed universal 128 KiB sweet spot.

Do not use the analytical model as the final performance result.

## Phase 7 — Controlled streaming plateau benchmark

Run:

```bash
sudo bash tests/runtime/streaming-benchmark.sh
```

First run the default controlled device:

```text
20 MiB/s
0.5 ms completion latency
lower QD1
50% compressibility
writer QD64
```

Sweep:

```text
immediate:      4 KiB
opportunistic:  4 8 16 32 64 128 256 512 1024 KiB
staged:         4 8 16 32 64 128 256 512 1024 KiB
```

The benchmark already runs a low-rate QD1 reader concurrently with the writer.

Record for every case:

```text
upper write/completion MiB/s
end-to-end drained write MiB/s
write avg/p99
read avg/p95/p99/max
lower read I/Os/sectors
lower write I/Os/sectors
physical_write_reqs
max_write_batch
staged_hits
staged_early
staged_cancel
CPU
```

The explicit final flush belongs inside the drain clock for staged mode.

## Phase 8 — Command-latency plateau matrix

Repeat the strategy/batch sweep at 20 MiB/s with:

```text
0.25 ms
0.50 ms
1.00 ms
2.00 ms
```

For example:

```bash
sudo env SWAPZ_BENCH_MBPS=20 SWAPZ_BENCH_LATENCY_NS=250000  bash tests/runtime/streaming-benchmark.sh
sudo env SWAPZ_BENCH_MBPS=20 SWAPZ_BENCH_LATENCY_NS=500000  bash tests/runtime/streaming-benchmark.sh
sudo env SWAPZ_BENCH_MBPS=20 SWAPZ_BENCH_LATENCY_NS=1000000 bash tests/runtime/streaming-benchmark.sh
sudo env SWAPZ_BENCH_MBPS=20 SWAPZ_BENCH_LATENCY_NS=2000000 bash tests/runtime/streaming-benchmark.sh
```

For each strategy/latency, identify:

```text
best measured drain throughput
smallest batch >=97% of best drain throughput
read p99 at every plateau candidate
latency-guarded winner
incremental gain from the largest previous step
```

If 512 -> 1024 KiB still improves drained throughput by more than 3% and read latency remains
acceptable, report:

```text
PLATEAU NOT REACHED — BATCH/SEGMENT CEILING NEEDS TO INCREASE
```

Do not falsely call 1 MiB the sweet spot in that case.

## Phase 9 — Queue-depth / reclaim-pressure matrix

Repeat the 20 MiB/s, 0.5 and 1.0 ms tests at:

```text
writer QD1
writer QD8
writer QD32
writer QD64
```

At minimum test:

```text
immediate 4 KiB
opportunistic at its latency-guarded plateau
staged at its latency-guarded plateau
```

Why this matters:

- QD1 shows whether staged early completion lets the producer continue without waiting on
  media;
- higher QD shows pipeline saturation;
- upper completion rate is a proxy for how fast original swapout pages can become
  reclaimable;
- drained throughput proves the device is actually keeping up rather than merely buffering.

Report both upper and drained throughput. Never report only upper staged throughput.

## Phase 10 — Compressibility matrix

At the selected plateau sizes, repeat:

```text
100% compressible
50% compressible
0% compressible
```

for immediate, opportunistic, and staged where practical.

Report:

```text
logical bytes
compressed payload bytes
physical bytes
lower write I/Os
upper completion throughput
drained throughput
read p99
CPU
```

The 60-80 MiB/s stretch target on ~20 MiB/s media requires approximately 3-4x effective
physical-byte reduction while keeping lower throughput close to its sequential plateau.

Do not claim 60-80 MiB/s for workloads whose measured byte reduction cannot support it.

## Phase 11 — Throughput versus swap-in latency frontier

This is a primary decision result.

For every strategy and batch size plot or tabulate:

```text
x = end-to-end drained write MiB/s
y = concurrent read p99 ms
secondary = upper completion/reclaim MiB/s
RAM cost = two stream buffers at configured batch ceiling
```

Identify Pareto-dominated points.

The candidate batch sweet spot is:

1. on the >=97% physical-drain plateau;
2. smallest practical buffer size;
3. read p99 no worse than 10% above the best read p99 among plateau candidates;
4. no correctness or GC regression.

The candidate strategy winner is not simply the highest write bandwidth. It should maximize
reclaim/upper completion rate while meeting drain, read-latency, memory-bound, and
correctness constraints.

## Phase 12 — Staging/cancellation effectiveness

Create a churn workload where recently written compressed pages are read back and then
actually invalidated/overwritten before submission.

Measure:

```text
staged_hits
staged_early
staged_cancel
staged_cancelled_blocks
lower bytes avoided
lower I/Os avoided
read latency from staged RAM
```

Compare staged versus opportunistic.

Do not count a read alone as cancellation.

## Phase 13 — GC regression

At the chosen opportunistic and staged plateaus, run sustained churn long enough to force
at least 20 live victims.

Report:

```text
gc_victims
gc_pages
gc_read
gc_write
GC-trigger p95/p99/max
total lower bytes including GC
failed
```

V2.2 must not reintroduce V1-style write amplification or long GC stalls.

## Phase 14 — Real bounded Linux swap pressure

Only after block correctness passes.

Run the existing bounded pressure harness for both:

```text
opportunistic at its chosen plateau
staged at its chosen plateau
```

Measure:

```text
actual swap usage
pswpout / pswpin deltas
upper swapout completion rate if practical
staged_early
staged_hits
staged_cancel
swapoff time
second swapon/readback
kernel logs
```

The key question is whether staged mode releases useful RAM materially faster under actual
memory pressure without causing swap-in latency or drain instability.

## Phase 15 — Physical media

Do not use any real physical device unless the operator explicitly authorizes that exact
device/partition as disposable.

If none is authorized:

```text
PHYSICAL MEDIA: NOT RUN
```

Virtual results are sufficient to choose the strategy for the next physical test, but not
to claim real-device success.

## Required strategy comparison

Return one summary table:

| Strategy | Cmd latency | QD | Compressibility | Batch KiB | Upper MiB/s | Drain MiB/s | Read p99 ms | Read max ms | Lower write I/Os | Lower MiB | Staged hits | Early completions | Cancellations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

Then explicitly answer:

1. Where is the measured batch-size plateau at each command latency?
2. Was the 1 MiB ceiling sufficient, or is the plateau still rising?
3. Which policy wins: immediate, opportunistic, or staged?
4. Does asynchronous double buffering materially improve drain throughput?
5. Does staged early completion materially improve QD1/real-pressure reclaim progress?
6. Can reads from A, B, and both buffers be served without waiting for the lower write?
7. How much lower I/O is avoided by stale unsent-record cancellation?
8. What is the read-p99 penalty as batch size grows?
9. What is the RAM cost of the winning point?
10. Does GC behavior remain acceptable?
11. Is the measured compression/packing ratio sufficient to make 60-80 MiB/s logical
    throughput physically plausible on 20 MiB/s media?
12. What should the next physical test use for strategy and batch ceiling?

## Final status

Choose exactly one:

```text
BLOCKED — CORRECTNESS FAILURE

CORRECTNESS PASS, STREAMING PERFORMANCE FAIL

CORRECTNESS PASS, PLATEAU NOT REACHED

CORRECTNESS PASS, STRATEGY WINNER IDENTIFIED — PHYSICAL BENCHMARK NEEDED

V2.2 SOFTWARE PROOF-OF-CONCEPT SUCCESS
```

Use `V2.2 SOFTWARE PROOF-OF-CONCEPT SUCCESS` only if the strategy winner is clear,
correctness is solid, the batch plateau is actually identified within the supported range,
and the throughput/read-latency tradeoff is quantitatively acceptable.

Do not commit or push changes.


## Reporting a pinned stale-module gate

If the module currently loaded in the kernel does not match the freshly built candidate
and a stuck D-state BIO prevents unloading/replacing it, do **not** attribute that old
runtime failure to the current source candidate.

Use:

```text
NEEDS_EXPLICIT_REBOOT_AUTHORIZATION — CURRENT CANDIDATE NOT RUNTIME TESTED
```

and report both identities:

```text
CURRENT_SOURCE_HEAD=<git HEAD>
BUILT_MODULE_SRCVERSION=<new module srcversion>
LOADED_MODULE_SRCVERSION=<pinned old module srcversion>
PINNED_RUNTIME_SOURCE=<known old commit if established>
```

A current candidate may receive `BLOCKED — CORRECTNESS FAILURE` only after that candidate's
module was actually loaded and reproduced a correctness failure.

Never reboot automatically; wait for explicit operator authorization.


## Current post-reboot compile-recovery gate

The first post-reboot attempt on `4dbde71100ed6e82682e8071c16b9c1bc116ee2f`
did not reach runtime because the kernel source called
`swapz_wait_async_callbacks()` before its static declaration/definition.

That compile blocker has been fixed on current `origin/main`.

The host snapshot from that attempt showed:

```text
no swapz DM devices
dm_swapz not loaded
normal /swapfile and /dev/sda1 swap only
```

Therefore **another reboot is not required** merely to test the compile fix.

On the next run:

1. fetch/reset to current `origin/main`;
2. run `tests/runtime/source-invariants.sh`;
3. clean-build the kernel with `W=1`;
4. if and only if the build succeeds, load `kernel/dm-swapz.ko` directly;
5. verify the loaded `srcversion` matches the freshly built module;
6. run the focused `async-progress.sh` gate three times;
7. continue broader correctness only after 3/3 focused passes.

Do not load the older installed module from
`/lib/modules/.../updates/dm-swapz.ko` as a substitute for the freshly built artifact.
