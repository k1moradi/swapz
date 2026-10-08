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

### Stale fill-buffer root-cause gate

The focused run on the pre-fix candidate reproduced the hang with:

```text
failed=0
gc_victims=1
gc_pages=1
inflight_id=-1
async_cb=0
fill_blocks=0
pack_records=0
```

The tested failing tree is preserved as:

```text
v2.2-stale-fill-blocked
3751bfb714c5aba77cdf987740b3bc60bcf6713e
```

Root cause found in `swapz_stage_write_block()`:

- it cached the current fill-buffer pointer;
- `swapz_ensure_physical_block()` could rotate segments/run GC and change
  `fill_buffer_id`;
- the function then staged the current BIO into the stale old buffer.

The post-fix source must reacquire `swapz_fill_buffer(context)` after
`swapz_ensure_physical_block()` and before using `buffer->block_count` or writing the
record.

Run:

```bash
bash tests/runtime/source-invariants.sh
```

and confirm the stale-fill ownership invariant passes.

If an older module/target is pinned from the failing run, do not reboot without explicit
operator authorization. Source/build/model checks may continue against current `main`.

After a freshly built post-fix module is loadable, run `async-progress.sh` first. One
failure is enough to stop; do not proceed to broader correctness or performance.

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

Treat a log message as a correctness blocker only when it is plausibly related to swapz,
Device Mapper, block I/O, memory corruption, lockups, hung tasks, WARN/BUG/Oops/panic, or
the test stack itself.

Do **not** stop solely for unrelated host-noise messages such as:

```text
perf: interrupt took too long (...), lowering kernel.perf_event_max_sample_rate ...
```

unless they coincide with a swapz failure, kernel lockup, or reproducible test anomaly.
Record unrelated messages in the report, but continue the gate.

If any focused run itself times out, hangs, corrupts data, leaves owned I/O behind, or
produces a swapz-relevant kernel warning:

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


### Focused stale-fill fix result

The post-fix candidate at:

```text
0f40f52956ff0b4ffc18549b916a54ce55847c02
```

has now passed the focused async/live-GC progress gate three independent times on Linux
7.0.0-34 with the freshly built module identity verified.

Observed results:

```text
run 1: 6.835 s, readback PASS, gc_victims=38, gc_pages=38, failed=0
run 2: 6.563 s, readback PASS, gc_victims=38, gc_pages=38, failed=0
run 3: 6.596 s, readback PASS, gc_victims=38, gc_pages=38, failed=0
```

Each run finished with:

```text
inflight_id=-1
async_cb=0
fill_blocks=0
pack_records=0
```

The run-3 dmesg delta contained only an unrelated perf sample-rate adjustment message.
That message is not a swapz correctness failure.

Therefore the next validation step is the broader correctness suite. No reboot is required
solely because of this focused result, provided the currently loaded module still matches
the tested kernel artifact and no stale swapz target remains.


## Performance gate is now open

The kernel source at:

```text
0f40f52956ff0b4ffc18549b916a54ce55847c02
```

has passed the full correctness campaign and is preserved on:

```text
v2.2-correctness-pass
```

Current `main` contains only test/documentation changes after that kernel source.

Before starting benchmarks, verify the permanent harness cleanups against the already loaded
matching module:

```bash
git pull --ff-only origin main
sudo bash tests/runtime/staged-rewrite-fault.sh
sudo bash tests/runtime/staged-write-fault.sh
sudo env SWAPZ_LONG_STRATEGY=staged bash tests/runtime/correctness.sh
```

The staged correctness command intentionally changes only the randomized and live-GC target
strategy. Selectivity and packed-GC remain opportunistic inside the harness.

If those pass, performance work is authorized under the existing benchmark plan:

1. analytical request plateau;
2. immediate/opportunistic/staged streaming benchmark sweep;
3. 4, 8, 16, 32, 64, 128, 256, 512, 1024 KiB batch sizes;
4. latency matrix 0.25/0.5/1/2 ms;
5. queue depths 1/8/32/64;
6. compressibility 100/50/0;
7. throughput versus swap-in-latency Pareto frontier;
8. staging cancellation effectiveness;
9. GC regression;
10. bounded real swap pressure.

Do not use physical media without explicit exact-device authorization.

If 512 -> 1024 KiB still improves drain throughput by more than 3% with acceptable read
latency, report:

```text
PLATEAU NOT REACHED — BATCH/SEGMENT CEILING NEEDS TO INCREASE
```

Do not modify kernel performance policy while benchmarking. Report measurements first; the
primary developer decides the next architecture/performance change.


## Deferred final-version resume/hibernate scope

Resume and hibernation are **not part of the current V2.x implementation or validation
scope**, but they are planned requirements for the final version of `swapz`.

For current V2.x work:

- do not add hibernation/resume features;
- do not change the volatile mapping format for speculative future resume support;
- do not treat lack of hibernation/resume support as a V2.x correctness failure;
- do not add initramfs/dracut activation solely for hibernation yet.

For the final-version phase, hibernation/resume becomes an explicit feature-development
milestone owned by the primary developer. It will require a persistent, versioned,
power-loss-safe metadata/data design plus boot-time activation and end-to-end reboot/resume
validation.

Codex must not independently design or implement that feature. When the project reaches the
final-version resume/hibernate milestone, follow the then-current repository specification
and validation contract.

## Roadmap scope guard

`ROADMAP.md` and `TODO.md` contain future-version planning. They are not authorization
for Codex to begin future feature work.

Codex must work only on the currently active validation/performance phase described in
this file unless the primary developer explicitly advances the project milestone.

In particular, do not independently begin:

- V2.3 physical-device testing without exact-device authorization;
- V2.4 byte-tight format development;
- V2.5 deployment/Dracut feature development;
- V2.6 release-hardening changes beyond requested validation;
- V3.0 persistent hibernation/resume design or implementation.

Future roadmap items may be read to understand intent, but feature implementation remains
owned by the primary developer.

## null_blk mbps backend safety rule

Linux `null_blk`'s `mbps` control has a fixed 50 Hz byte budget. A request larger than
one tick's budget is requeued forever and can pin the validation stack.

The repository benchmark now detects this condition and exits before running it.

For a bandwidth-limited null_blk run:

```text
safe_request_bytes <= (1048576 / 50) * SWAPZ_BENCH_MBPS
```

At 20 MiB/s this means the powers-of-two batch sweep is safe only through 256 KiB.

Do not classify a rejected 512 KiB or 1024 KiB null_blk-mbps case as a swapz performance
failure.

After the currently pinned failed test state is cleared by an **explicitly authorized**
reboot, the next performance work should be:

```bash
# Real 20 MiB/s null_blk throttle, only backend-safe sizes.
sudo env SWAPZ_BENCH_MBPS=20   SWAPZ_BENCH_BATCHES="4 8 16 32 64 128 256"   bash tests/runtime/streaming-benchmark.sh

# Full request-size sweep with fixed command latency only.
# This is NOT a 20 MiB/s drain benchmark.
sudo env SWAPZ_BENCH_MBPS=0   SWAPZ_BENCH_BATCHES="4 8 16 32 64 128 256 512 1024"   bash tests/runtime/streaming-benchmark.sh
```

The unthrottled run may be used to study request-overhead and read-latency effects, but it
must never be reported as the 20 MiB/s physical-drain plateau.

If the 20 MiB/s result is still rising at 256 KiB, report:

```text
CONTROLLED BACKEND LIMIT — 20 MiB/s PLATEAU NOT MEASURABLE ABOVE 256 KiB WITH null_blk mbps
```

Do not modify swapz kernel policy merely to accommodate this null_blk limitation.
A separate size-aware benchmark backend is a test-infrastructure task owned by the primary
developer.


## Benchmark teardown regression gate

Codex's 1 and 2 ms synthetic sweeps exposed a **test cleanup bug**, not a
validated swapz data-path error: `dmsetup remove` could transiently return
`Device or resource busy`, and the old EXIT trap ignored that failure and
powered off null_blk while DM still referenced it.

The patched benchmark has a strict dependency-order contract:

1. finish fio and flush;
2. remove the *exact test-owned DM target* with `dmsetup remove --retry`;
3. verify the target name is absent;
4. only then power off/rmdir the test-owned null_blk backing;
5. preserve the powered backing, target, and test artifacts if DM removal fails.

Never use `dmsetup remove --force` or `--deferred` as a workaround. Never
power off the lower device merely because the benchmark's EXIT trap is running.

Before the next broad performance run:

```bash
git fetch origin --prune
git switch main
git pull --ff-only origin main
bash -n tests/runtime/streaming-benchmark.sh
bash -n tests/runtime/streaming-benchmark-teardown.sh
bash -n tests/runtime/streaming-teardown-regression.sh
bash tests/runtime/streaming-teardown-regression.sh
bash tests/runtime/source-invariants.sh
```

Verify the current built module matches the loaded module. The last Codex
snapshot showed a clean DM/null_blk test state, so **no reboot is indicated**
unless a later runtime test independently pins a target.

Then run the missing safe virtual matrix at 1.0 and 2.0 ms using <=256 KiB
batch ceilings. Confirm every completed case leaves no DM mapping and no
test null_blk before advancing. Record any busy removal and whether --retry
succeeded. Stop if target removal remains blocked; the backing must stay
powered until explicit safe operator action.

After that, continue the existing QD/compressibility/cancellation/GC/pressure
performance plan; never choose a 512 KiB / 1 MiB 20 MiB/s plateau from
null_blk's 50 Hz throttle.


## Throttled null_blk GC DISCARD deadlock gate

The 20 MiB/s `null_blk mbps` limit applies to **DISCARD request bytes too**.
Swapz's segment GC can issue an optional synchronous 1 MiB lower DISCARD when
reclaiming a fully written segment. This request exceeds null_blk's ~409.6 KiB
per-tick budget and can wedge the queue, even with a safe 16 KiB stream batch.

This matches the latest stopped GC churn run's signature: `gc_victims=1`,
`gc_pages=0`, `free_segments=0`, `inflight_id=-1`, `async_cb=0`,
one lower request blocked, and `failed=0`. Root cause is highly plausible but
must be confirmed by a focused runtime retest.

The checked-in benchmark must **not** enable lower DISCARD while using
`SWAPZ_BENCH_MBPS>0`. The fixture defaults to `SWAPZ_BENCH_DISCARD=0`,
rejects `SWAPZ_BENCH_DISCARD=1` with throttling before setup, and checks
`lower_discard=off` in every DM target status before running fio.

Codex's host still has a pinned disposable target and D-state fio workers.
**Do not reboot without explicit operator permission.** Do not force-remove,
power off its backing, or run runtime tests until the host is safely clear.

Focused gate on a clean host:

```bash
git fetch origin --prune
git switch main
git pull --ff-only origin main
bash -n tests/runtime/streaming-benchmark.sh
bash tests/runtime/nullblk-discard-guard.sh
bash tests/runtime/streaming-teardown-regression.sh
bash tests/runtime/source-invariants.sh
# Verify fresh module build/source and loaded module srcversion match.
# A rejected unsafe config must exit without creating DM/null_blk devices:
sudo env SWAPZ_BENCH_MBPS=20 SWAPZ_BENCH_DISCARD=1 \
  bash tests/runtime/streaming-benchmark.sh
# Expected explicit refusal (not PASS exit code).
```

Then rerun **only the previously failing extended GC-churn scenario** with
`SWAPZ_BENCH_MBPS=20 SWAPZ_BENCH_DISCARD=0` and the same
0.5 ms / QD64 / 50%-compressible / opportunistic 16 KiB workload.
Keep a bounded external timeout and capture status, lower I/O, dmesg and
live-set verification. Require `lower_discard=off`, more than one GC victim,
completion, no residual I/O, and successful safe teardown.

The benchmark's default 32 MiB logical / 256 MiB null_blk geometry may need
more than 60 seconds at 20 MiB/s to recycle segments; run a dedicated bounded
long-churn fixture if needed, with the same validated safety limits. Do not
call a short run with no GC a focused PASS.

If that passes, separately test lower DISCARD with
`SWAPZ_BENCH_MBPS=0 SWAPZ_BENCH_DISCARD=1` (unthrottled) and explicit GC
coverage. Compare the observed GC/discard progress.

If GC still hangs with lower discard off, classify it as a real new
forward-progress blocker and report the exact worker stack and state.
No architecture/performance changes by Codex; report measurements for
primary-developer review.


## Current handoff: GC/DISCARD retest passed (supersedes pinned-host gate)

Codex completed the focused gate against kernel source on
`111fc89e4b7edb97f2f61c7e5fd5b3acd01ee137`:

```text
20 MiB/s, lower_discard=off: 921 GC victims, failed=0, clean drain/teardown
unthrottled, lower_discard=on: 1125 GC victims, 1179648000 bytes
  discarded, discard_failures=0, failed=0, clean drain/teardown
unsafe throttled + DISCARD: exit 4 before creating device
built and loaded srcversion: C0E91E94E24D50FDC42769E
```

Both configurations completed with no leaked virtual targets, processes, or
stuck tasks. **The earlier pinned-host instructions are historical, not
instructions to reboot the now-clean host.** Do not reboot without a new,
explicit operator authorization if a future independent failure requires it.

The long fio GC test proves forward progress, not exact live-set integrity.
Proceed as follows, without changing swapz kernel source:

1. Pull current `origin/main`, confirm clean test host, verify source
   invariants and loaded/fresh module identity.
2. Run exact byte-for-byte live-set readback using existing
   `tests/runtime/correctness.sh` and `tests/runtime/no-discard-livegc.sh`.
   Require `failed=0`, `gc_pages>0`, and complete reference readback.
   Test opportunistic and staged long/live-GC coverage. Do not mislabel
   the recent empty-victim churn as evidence of live-page relocation.
3. Continue the unfinished **performance-only** phases: cancellation/unsent
   stale-write avoidance, GC trigger latency/bytes and read p99, and bounded
   real swap pressure for the selected experimental policies. Retain the
   prior 1/2 ms, QD, compressibility matrix measurements as synthetic
   evidence; avoid rerunning completed matrices without a reason.
4. Keep the physical-drain plateau verdict **unresolved** until a
   size-aware 20 MiB/s backend can safely handle 512 KiB–1 MiB requests,
   or the operator explicitly authorizes an exact disposable physical
   device. The current throttled null_blk test cannot establish that
   plateau; the unthrottled results test latency/overhead only.
5. Report matched upper completion vs physical-drain throughput, read
   p95/p99/max, lower bytes/I/Os, GC/cancellation metrics, buffer RAM,
   exact tested module identity, and any remaining blockers.

Every runtime test must use disposable virtual devices and verify normal
teardown. Stop on any new pinned target, preserve its powered backing, and
request explicit reboot authorization if safe cleanup is impossible.
Codex may make only minimal mechanical compile/test-harness fixes, after
which the primary developer reviews the exact diff and nearby code.

Final milestone status until the remaining gates complete:

```text
V2.2 CORRECTNESS PASS — FOCUSED GC/DISCARD PASS —
STREAMING STRATEGY/PHYSICAL PLATEAU NOT YET SELECTED
```

 
## Optional size-aware NBD prototype gate

The primary developer has committed a **prototype**, not a validated new
benchmark backend. The existing null_blk performance and correctness contract
remains authoritative.

The prototype adds an explicitly opt-in `SWAPZ_BENCH_BACKEND=nbd` option and a
sparse-RAM userspace NBD server which models a serialized lower queue with
`latency_us + request_bytes / bandwidth`. It must not be confused with actual
physical-device measurements or treated as validated before smoke/calibration.

The next **source-only** checks may be run without root or runtime device setup:

```bash
git pull --ff-only origin main
python3 tests/runtime/size-aware-nbd.py selftest
bash -n tests/runtime/size-aware-nbd-teardown-test.sh
bash -n tests/runtime/streaming-benchmark.sh
bash -n tests/runtime/streaming-benchmark-teardown.sh
bash tests/runtime/size-aware-nbd-teardown-test.sh
bash tests/runtime/streaming-teardown-regression.sh
```

Please report the exact output and any Python or Bash syntax failure. These
checks do **not** authorize a kernel NBD attach or another benchmark matrix.
The primary developer also added rootless regressions for spoofed NBD device
identity, full-size (1 MiB) socket readback, and timeout-after-partial-send
reply framing. The backend must match the NBD sysfs major/minor number both
before and after opening the device. The Python selftest must exercise these
checks. Do not treat source inspection as execution evidence.

A later kernel NBD smoke test requires a separate explicit handoff from the
primary developer, an observed unused virtual `/dev/nbdN`, and the preflight
and safe-teardown rules in
`docs/benchmarks/v2.2-size-aware-nbd.md`. The harness will refuse other paths,
including physical disks. Never force-detach NBD under an active DM mapping
and never reboot without explicit operator permission.

The size-aware backend becomes eligible to resolve the 512 KiB–1 MiB plateau
only after its actual request sizes, raw transfer rate, exact data readback,
and teardown are demonstrated. Continue the existing V2.2 reference-driven
correctness and measured performance gates separately.


## Follow-up source-only gate: verified loop-stack teardown and GC interval analysis

**Not part of the already assigned NBD preflight/audit.** The primary
developer has since modified the disposable no-DISCARD, recall, and pressure
fixture teardown paths. Do not run their root-only workloads merely because
this section exists. First complete and report the current source-only NBD
assignment.

A **separate source-only** handoff can then run at a newly verified HEAD:

```bash
git pull --ff-only origin main
bash -n tests/runtime/test-stack-teardown.sh
bash -n tests/runtime/test-stack-teardown-regression.sh
bash -n tests/runtime/no-discard-livegc.sh
bash -n tests/runtime/buffer-recall.sh
bash -n tests/runtime/pressure.sh
bash tests/runtime/test-stack-teardown-regression.sh
python3 tests/runtime/live-gc-latency-analyze-test.py -v
```

Audit exact teardown behavior: transient busy DM removal, false-positive
remove success, info/list disagreement, lower-target removal failure, missing
resources, unknown holders, outstanding writer, service stop failure, active
swapoff failure, failure exit codes, and preservation of diagnostic/backing
files. Check scripts do not print final PASS before verified cleanup.

The interval analyzer is an **offline** utility, not a collector or a kernel
instrumentation pass. It needs matching monotonic timestamps and verified
`moved_pages` for each GC interval. It must reject empty-GC-only evidence
and insufficient correlated read samples. Its local rootless tests passed;
independent checked-out-HEAD validation is still required.

Do not attach loops/NBD, create DM mappings, activate swap, run runtime
benchmarks, touch normal system swap, or reboot without a separate explicit
virtual-runtime handoff. If a source regression fails, report the evidence
without weakening the assertion or making a substantive kernel fix.


## NBD rootless requalification after shutdown/test hardening (2026-10-08)

The previous Codex source-only PASS at `47883567` covered the older
`tests/runtime/size-aware-nbd.py`; it does not validate the later
size-aware NBD shutdown and selftest changes. Finish any already-assigned
teardown/GC analyzer audit first. This follow-up requires a separately
checked-out current HEAD.

Run only rootless/source-only operations:

```bash
git pull --ff-only origin main
git rev-parse HEAD
python3 -m py_compile tests/runtime/size-aware-nbd.py
python3 tests/runtime/size-aware-nbd.py selftest
bash -n tests/runtime/streaming-benchmark.sh
bash -n tests/runtime/streaming-benchmark-teardown.sh
bash -n tests/runtime/size-aware-nbd-teardown-test.sh
bash tests/runtime/size-aware-nbd-teardown-test.sh
bash tests/runtime/streaming-teardown-regression.sh
```

The updated selftest must prove 4 KiB versus 1 MiB timing scaling, a **wire**
1 MiB WRITE/READ, permitted TRIM via socketpair, disabled TRIM rejection,
truncated reply/EOF/timeout/mismatched cookie and magic failures, no test
thread hang, and mock coverage of disconnect, clear-socket and slow-worker
shutdown errors. An ERROR line from the intentional slow-worker mock is
expected only if the complete selftest exits 0 and checks its failure result.
Report full output and exit codes.

Review `shutdown_kernel_session()` behavior: its initial worker join is
bounded to five seconds. If the kernel worker remains alive, it logs a failure
and **waits for the worker instead of releasing the attached descriptors**;
this exceptionally may keep the NBD server process running. Never claim a
bounded process shutdown in that path. Do not force-kill the server under a
live DM mapping, force/defer DM removal, or perform an unapproved device
attachment/reboot.

The NBD backend is still EXPERIMENTAL. Do not run `serve`, open
`/dev/nbdN`, activate swap, or run a performance matrix based on these
source-only checks.

## Follow-up: teardown audit remediation independent source-only gate

**This is a separate handoff AFTER completion of the currently assigned NBD
requalification.** The primary developer has now corrected the cleanup
problems identified by Codex's read-only audit at `4307f0c9`. Do not run
root-only fixture workloads: this handoff authorizes only rootless source
parsing, mocks and offline analyzer tests.

First fast-forward and record the exact tested SHA, preserving both existing
untracked `local-*-verify.state` files. Then run:

```bash
bash -n tests/runtime/test-stack-teardown.sh
bash -n tests/runtime/test-stack-teardown-regression.sh
bash -n tests/runtime/pressure-teardown.sh
bash -n tests/runtime/pressure-teardown-regression.sh
bash -n tests/runtime/no-discard-livegc.sh
bash -n tests/runtime/buffer-recall.sh
bash -n tests/runtime/pressure.sh
bash tests/runtime/test-stack-teardown-regression.sh
bash tests/runtime/pressure-teardown-regression.sh
python3 tests/runtime/live-gc-latency-analyze-test.py -v
```

Validate that the mock regression truly injects the hazards: populated
cgroup.procs with zero st_size, failed cgroup/systemd/DM/losetup/readlink/
proc-swaps inspection, post-detach inventory failure, live swap and
swapoff failure, stopped or exited I/O children, and real find errors.
An intentionally emitted ERROR in a negative mock is expected only when the
test also asserts preserved backing and returns zero.

Audit any remaining false PASS, misplaced command-substitution error,
unbounded child wait, PID reuse, or resource-name ambiguity. Report line
numbers and exact command results; don't make substantive unreviewed
changes. Continue to require explicit separate authorization for any
NBD/DM/loop runtime operation, swap activation, physical device, or reboot.

## Additional NBD source-only review — after teardown task completes

Codex previously ran seven source-only NBD checks on `0c3a9169` (all
PASS). The source had the previously acknowledged worker-shutdown guard,
but independent audit found missing rejection-path and failure-diagnostic
coverage. The primary developer later committed additional NBD-only
source/test corrections. **These changes are not covered by the old PASS.**

When the current teardown requalification assignment finishes, a separate
NBD-only, **rootless** handoff should run:

```bash
git pull --ff-only origin main
git rev-parse HEAD
python3 -m py_compile tests/runtime/size-aware-nbd.py
python3 tests/runtime/size-aware-nbd.py selftest
bash -n tests/runtime/streaming-benchmark.sh
bash -n tests/runtime/streaming-benchmark-teardown.sh
bash -n tests/runtime/size-aware-nbd-teardown-test.sh
bash tests/runtime/size-aware-nbd-teardown-test.sh
bash tests/runtime/streaming-teardown-regression.sh
```

Inspect exact source and exit codes. Confirm the selftest now exercises
holder directory missing/permission/iteration failures, end-to-end
preflight rejection, unknown command and unsupported flags/FUA, oversized
write rejection before payload receive, an entire client transaction with
short READ payload, the exact 8 MiB model boundary, stop **during** an
active modeled wait with no successful reply, partial NBD_SET_SOCK setup,
worker startup failure, cleanup-dependent CLI result, immediate disconnect
errors, and independent close error preservation. Any intentional ERROR
output from mocked failure branches is expected only if corresponding
assertions execute and the command exits 0.

Do not modify current teardown scripts during NBD audit or claim runtime
qualification. No /dev/nbdN attach, module loads, DM/loop operations,
swap changes, physical tests, or reboot without separate explicit approval.

## Next independent teardown gate — after current NBD qualification

Codex's audit on `ae594c266d11a815091b5957b496b1705252db72`
returned source-only teardown FAIL: malformed `dmsetup ls` and unknown
cgroup directory inspections could fail open; the stack regression also
stopped on two wrong state assertions before its later cases ran.

Primary developer has corrected these issues and obtained **rootless CI
PASS** at `e92ad29a192b70cbe9e04a1421496bfaf85bd460`
(https://github.com/k1moradi/swapz/actions/runs/37772741880).
The run exercised all 7 syntax checks, the *entire* stack teardown mock,
the pressure teardown mock, and 11 offline GC analyzer tests. It does not
supersede the need for a separately reported Codex Linux-host check.

Once the current independent NBD audit is complete, run read-only/rootless:

```bash
git pull --ff-only origin main
git rev-parse HEAD
git rev-parse HEAD:kernel/dm-swapz.c
git status --short --branch
for f in \
  tests/runtime/test-stack-teardown.sh \
  tests/runtime/test-stack-teardown-regression.sh \
  tests/runtime/pressure-teardown.sh \
  tests/runtime/pressure-teardown-regression.sh \
  tests/runtime/no-discard-livegc.sh \
  tests/runtime/buffer-recall.sh \
  tests/runtime/pressure.sh; do bash -n "$f" || exit; done
bash tests/runtime/test-stack-teardown-regression.sh
bash tests/runtime/pressure-teardown-regression.sh
python3 tests/runtime/live-gc-latency-analyze-test.py -v
```

Audit critical behavior at the exact tested HEAD: malformed DM inventory
output is never accepted as an absent mapping; cgroup EACCES/EIO never
counts as confirmed removal; post-detach inventory failures and
completed-but-listed reused PID mocks execute; pressure stop/cgroup/
swapoff/swap-inventory/cleanup event sequence is asserted, and test swap
remains untouched on any inspection error. Keep any existing untracked
`local-*-verify.state` files unchanged.

A Bash jobs -pr/-ps snapshot removes the reproduced completed-job
false-positive, but does not supply an atomic signal target. State
the remaining PID reuse TOCTOU limit. No root, real DM/loop/NBD,
modprobe, swap commands, block devices, fio, physical media, or reboot.

## Latest NBD source-only requalification handoff: corrected mock isolation

**Do not rerun the older `2fc80f4` NBD selftest.** Codex demonstrated
that the earlier test's captured syscall defaults attempted real
NBD_CLEAR_SOCK and close against test fd 81, despite mocks. The primary
developer replaced captured defaults with late binding, and every mocked
`serve_kernel()` now uses a non-integer fake fd sentinel. The intended
mock call order was verified on a disposable GitHub Actions runner.

**Authoritative corrected source-only evidence:**

- Commit: `f1c458f638712a19dea8b724a7f32bd1052b791e`
- Rootless NBD workflow: https://github.com/k1moradi/swapz/actions/runs/37774348723
- Static syscall-isolation check: **PASS**
- Seven prior NBD source-only commands: **PASS**

After completing the current independent teardown audit, Codex should
fast-forward `main`, record HEAD/source blobs, then independently inspect
the corrected keyword defaults and the non-integer fake-fd test before
running the updated, **rootless-only** NBD gate:

```bash
git pull --ff-only origin main
git rev-parse HEAD
git rev-parse HEAD:tests/runtime/size-aware-nbd.py
git rev-parse HEAD:kernel/dm-swapz.c
git status --short --branch
python3 -m py_compile tests/runtime/size-aware-nbd.py
python3 tests/runtime/size-aware-nbd.py selftest
bash -n tests/runtime/streaming-benchmark.sh
bash -n tests/runtime/streaming-benchmark-teardown.sh
bash -n tests/runtime/size-aware-nbd-teardown-test.sh
bash tests/runtime/size-aware-nbd-teardown-test.sh
bash tests/runtime/streaming-teardown-regression.sh
```

Verify the direct partial-setup cleanup mock intercepts NBD_SET_SOCK,
NBD_CLEAR_SOCK, and descriptor close, rather than invoking kernel syscalls.
Verify non-OSError NBD worker failure causes nonzero backend status;
active NBD PID, swap-file read/stat error and exact 8 MiB wire READ/WRITE
cases execute. Expected injected shutdown ERROR messages alone are
not a failing result if the test assertions execute and the command returns
0. Preserve the two pre-existing `local-*-verify.state` files.

Do **not** run this against the failed historical NBD source blob. Do not
open a real /dev/nbdN, create DM or loop mappings, run swapon/swapoff,
load modules, access physical media, benchmark fio, or reboot. A full
kernel NBD smoke remains a separately authorized next phase.

## NBD preflight follow-up to include in later independent NBD audit

After the captured-default mock correction passed in CI, the primary
developer additionally hardened `validate_nbd_node()` against successful
but corrupt `/proc/self/mountinfo` and `/proc/swaps` reads. Neither
empty/malformed mount inventories nor a malformed swap header/entry
can establish device absence.

A subsequent rootless NBD CI run passed at
`0b93caf752aa4716100815734d3a1f299fc2dec8`:
https://github.com/k1moradi/swapz/actions/runs/37775709673.
The suite includes malformed and absent mountinfo, corrupt swap headers,
incomplete/nonnumeric swap records, failed swap path stat, and a safe
positive validation path with a non-NBD active swap. It still opens no
real block devices.

When assigned to NBD **after completing the ongoing teardown task**,
Codex should fetch the latest HEAD and NBD blob, review the corrected
mock-isolation source before running the seven-command rootless gate
already listed above, and audit whether every new negative case tests
its intended rejection path rather than a different mock failure.
Do not revisit the historical NBD blob whose selftest attempted a real
ioctl/close. Do not conduct any kernel NBD, DM/loop, swap, physical
media, module, or benchmarking operations without explicit approval.

## Follow-up teardown source-only requalification after Codex's PASS

Codex independently tested teardown source at `10c9d09bf4d3e78dd9524e20988c38b204f9ad42`
and reported **SOURCE-ONLY TEARDOWN GATE PASS** (ten commands,
including 11 GC-analyzer tests). The primary developer then addressed
its remaining mock-coverage and inventory-parsing gaps without touching
the concurrent NBD source or the kernel.

The GitHub-hosted rootless teardown gate passed at
`68360c26214c4c08a57180f50ae032746d68342f`:
https://github.com/k1moradi/swapz/actions/runs/37777532521

Changes after the older independent test include:

- DM inventory rejection of duplicate names or major/minor > 4095/1048575
- Exact checked /proc/swaps header and numeric row fields
- Distinct cgroup paths for first and second systemd units in the mock
- Stop-failure test starting with active swap and proving no swapoff
- Stopped child CONT/TERM ordering and truthful pseudo-file mock description

After finishing the concurrent NBD source audit, review the latest HEAD
and recheck the combined source-only gates (no device runtime):

```bash
git pull --ff-only origin main
git rev-parse HEAD
git rev-parse HEAD:kernel/dm-swapz.c
git rev-parse HEAD:tests/runtime/size-aware-nbd.py
git status --short --branch
bash -n tests/runtime/test-stack-teardown.sh
bash -n tests/runtime/test-stack-teardown-regression.sh
bash -n tests/runtime/pressure-teardown.sh
bash -n tests/runtime/pressure-teardown-regression.sh
bash -n tests/runtime/no-discard-livegc.sh
bash -n tests/runtime/buffer-recall.sh
bash -n tests/runtime/pressure.sh
bash tests/runtime/test-stack-teardown-regression.sh
bash tests/runtime/pressure-teardown-regression.sh
python3 tests/runtime/live-gc-latency-analyze-test.py -v
```

Preserve `local-batch-regression-0-verify.state` and
`local-verify-0-verify.state`. Do not change any source as part of
verification. Verify that bad inventory outputs fail closed and no
rootless mock performs actual device/swap operations.

The remaining Bash job identity check is non-atomic. Completed jobs are
excluded, but PID reuse between job enumeration and kill remains
theoretical; never report perfect PID reuse protection.

No live NBD/DM/loop/swap operations, modprobe, fio, physical devices or reboot.

## Next NBD independent Linux-host requalification after 8 MiB EBADF fix

Codex's preceding NBD source-only test at
`977023f4aca61e4e8d408065504966f3646b5eee`
**FAILED** only on the userspace 8 MiB socketpair cleanup race:
closing the server socket before joining its active recv thread
intermittently raised EBADF and blocked later mock assertions.
Codex verified syscall-mock isolation was already correct; there
was no reported live NBD ioctl during this failed test.

Primary developer has since changed 8 MiB and related socketpair
cleanup to stop -> join -> close, strengthened the mountinfo parser
(numeric IDs/major:minor and exact final-three-fields separator),
added malformed minimum-length and optional-fields positive tests,
and completed the NBD workflow's pull_request path filters.

**Executed rootless CI** at
`edbf6d1452bd8c87b36c44daa6ad349967592a22`:
https://github.com/k1moradi/swapz/actions/runs/37778788448
reported full NBD seven-command PASS, plus **25/25 repeated full
selftests** (26 full passes including the initial run). The normal
selftest logs the explicit
`NBD preflight, 8 MiB wire, setup cleanup and worker exceptions: PASS`
marker, so previously blocked cases demonstrably executed in CI.

After completing the current teardown independent Linux-host audit,
run the next NBD **rootless-only** check against the most recent
`main` (record full HEAD and NBD/kernel blob):

```bash
git pull --ff-only origin main
git rev-parse HEAD
git rev-parse HEAD:tests/runtime/size-aware-nbd.py
git rev-parse HEAD:kernel/dm-swapz.c
git status --short --branch
python3 -m py_compile tests/runtime/size-aware-nbd.py
python3 tests/runtime/size-aware-nbd.py selftest
bash -n tests/runtime/streaming-benchmark.sh
bash -n tests/runtime/streaming-benchmark-teardown.sh
bash -n tests/runtime/size-aware-nbd-teardown-test.sh
bash tests/runtime/size-aware-nbd-teardown-test.sh
bash tests/runtime/streaming-teardown-regression.sh
```

**Before executing selftest**, independently verify the fake-fd
`object()` sentinel, mocked ioctl/close call containment, and
late-bound `shutdown_kernel_session()` dependencies. Specifically
inspect 8 MiB cleanup order and ten-field bad mountinfo tests.
Preserve existing `local-*-verify.state` files exactly. No device
runtime operation, swapping, kernel module change, benchmark, physical
media or reboot is authorized. The rootless PASS is not an actual
NBD driver qualification or GC latency measurement.

## Combined source-only clean-runner evidence at one exact revision

While Codex was independently auditing the teardown source, the primary
developer added the rootless-only integration workflow:
`.github/workflows/rootless-combined.yml`.

**Execution PASS:** https://github.com/k1moradi/swapz/actions/runs/37779371716

- **Tested HEAD:** `8116bdfb8b61a69f67e6548904e82c191b979f23`
- **NBD source blob:** `768ff896e82198829cde83e28c8e0a35ddad368c`
- **Kernel blob:** `7589022ecdf0525716717270ab063a867a21f473`

The combined job statically verified that NBD mock ioctl/close
dependencies cannot use captured real syscall defaults before it
ran selftest, then passed ten Bash syntax checks, the rootless DM/loop
and pressure teardown regressions, 11 offline GC analyzer tests,
NBD compilation and full userspace selftest, 25 additional NBD
selftest processes (26 total), and both NBD/streaming teardown mocks.
The expected cgroup `NotADirectoryError` traceback is an intentional
negative test; the suite was successful.

**Codex follow-up:** Finish/report the assigned independent Linux-host
teardown gate at your exact checked-out HEAD; do not replace it with
this GitHub runner result. Before any new independent NBD selftest,
review syscall isolation and the non-integer fake fd as previously
specified. Preserve existing `local-*-verify.state` files.
A combined source-only PASS is **not** a live kernel NBD driver smoke
or calibrated GC latency/physical bandwidth benchmark. Continue to
avoid root, real DM/loop/NBD, swap, module and physical disk operations.

## Teardown whitespace-inventory follow-up after Codex independent FAIL

Codex's independent teardown source-only gate at
`5a3aea67fc303748c7efae7e4a36e595ba4c7ab7`
reported **FAIL**, despite all ten listed commands passing.
The supplemental mocked `dmsetup ls` response consisting only of
spaces/tabs was incorrectly accepted as mapping absence.
The previous green GitHub run did not exercise this input.

The primary developer fixed the production DM inventory parser to
preserve even newline-only stdout (which plain Bash command
substitution would discard) and to fail on blank/whitespace inventory
records. Truly empty stdout and `No devices found` remain accepted.
Regression cases exercise the exact reported failure and lower-backing
preservation after upper removal.

Other Codex findings corrected simultaneously:

- Pinned pressure transient workers to `system.slice`; the pressure
  cleanup helper verifies exact, distinct `/system.slice/$unit`
  ControlGroup identity instead of arbitrary absolute paths. Mocked
  wrong, swapped, duplicated, unrelated and traversal paths block
  swapoff and mapper cleanup.
- Staged recall calls a shared testable child-stop-before-DM-cleanup
  helper. Rootless tests exercise unresponsive child failure and
  all-three-worker failure/success with actual cleanup decision.
- The pressure parser test includes nonnumeric `Used` swap entry.

**Fresh same-revision source-only CI PASS:** commit
`3b60d7659df8cf59716286dfe0d1504307eb2e78`.

- Teardown: https://github.com/k1moradi/swapz/actions/runs/37781726152
- Combined NBD/teardown:
  https://github.com/k1moradi/swapz/actions/runs/37781726172

Both workflows passed, including the new whitespace rejection and
ControlGroup identity regressions. The combined workflow also verified
NBD syscall isolation and executed 26 complete userspace NBD selftests
(25 repeats) on the *same commit*.

Once the current NBD independent host assignment finishes, Codex may
re-run its ten-command rootless teardown gate against the latest HEAD.
Record exact blobs, preserve the two `local-*-verify.state` files and
reproduce the whitespace-only DM mock. Do not claim the residual
shell-job PID-check-to-kill TOCTOU has been eliminated.

Do not conduct any real DM/loop/NBD, swapon/swapoff, kernel module,
physical-media, fio, benchmark or reboot activity without separate
explicit authorization.

## NBD independent qualification handoff after mountinfo dev_t correction

Codex's NBD source-only qualification at
`b838ad11e7ac49327514d55a1f2aeea9e3e1769e` reported **FAIL**
although all seven rootless commands and 10/10 complete selftests
passed. The observed remaining fail-open case was a numeric but
out-of-range mountinfo device tuple (for example `4096:0`,
`43:1048576`); NBD sysfs partition rejection had no direct test.

The primary developer now validates mountinfo major/minor integers
against 4095/1048575, compares the device identity numerically
(including leading zeros), and tests bad first and second rows,
valid boundary device numbers, synthetic `nbd0p1` partition presence
and partition-enumeration failures. Both CI gates passed on the
**same code commit**
`40678c7d9743d6efca943885f40be1a0388d3ca6`:

- NBD source-only rootless CI:
  https://github.com/k1moradi/swapz/actions/runs/37783419565
- Combined teardown+NBD rootless CI:
  https://github.com/k1moradi/swapz/actions/runs/37783419522

Each workflow completed 26 full NBD selftests (initial selftest plus
25 repetitions) with no reported EBADF or assertion errors.
The combined workflow also passed the DM/loop and pressure teardown
mocks, ten syntax checks and 11 offline analyzer tests.

**After finishing the independently assigned teardown audit:**
refresh `main`, record HEAD, kernel blob and updated NBD blob; preserve
both local `*-verify.state` files. Before running the NBD selftest
review late-bound ioctl/close mocks, the noninteger fake fd and the
thread-stop/join-before-socket-close ordering. Run the seven NBD
source-only commands listed in the prior NBD section, check the new
out-of-bounds and partition negative cases truly exercise their
respective failure paths, and report the exact Linux-host verdict.
Do not reuse the historical unsafe captured-default source blob.

A GitHub CI PASS does not supersede independent Linux-host review,
nor does any rootless result prove live kernel NBD shutdown, actual
swap-in p99, GC overlap, device throughput or physical performance.
No module, device, swap, fio, teardown fixture or reboot is permitted.

## Post-independent teardown-PASS pressure mock coverage and testable ordering

Codex's source-only teardown test at
`0f2f169631d08fc1b92e2aba1bed398e1ef795ff`
reported **SOURCE-ONLY TEARDOWN GATE PASS**. All ten Bash/Python
commands exited zero; additional DM parser inventory reproduction
was rejected fail closed. Codex found no new P0 but identified missing
checked-in negative tests for duplicate/invalid service names and
empty cgroups in active/nonzero-MainPID states.

The primary developer added those regressions using a **file-backed
show/signal event log**, avoiding the known subshell counter issue.
New cases explicitly reject duplicate, blank, path/traversal,
nonsuffixed and malformed names before systemd; empty ControlGroup
with live PID or active state also fails before any stop/swapoff.
Empty ControlGroup with MainPID zero and inactive/failed unit continues
to pass. Every rejected case starts with simulated active swap and
asserts no swapoff or mapper removal. A production ordering correction
now validates both names *before touching either unit*, rather than
detecting an invalid second name after contacting the first.

The complete rootless teardown and combined NBD/teardown suites
passed on one checked-out commit:
`e64509318576f3c4d65050426af234c2910b70ff`.

- Teardown: https://github.com/k1moradi/swapz/actions/runs/37784883620
- Combined: https://github.com/k1moradi/swapz/actions/runs/37784883592

The latter also passed static NBD syscall isolation, NBD compilation,
26 full NBD selftests and all NBD/streaming teardown mocks.

For Codex's **concurrent NBD source-only independent task**, retain
the specified pre-execution mock syscall containment review and
record the latest NBD and kernel blob. Do not infer Linux kernel
runtime behavior from socketpair mocks. Keep both existing untracked
`local-*-verify.state` files untouched. The Bash jobs-to-PID
check-to-kill race remains an explicit source-only qualification.

All work remains rootless; no real systemd service, block device,
swap command, physical media, kernel module, fio or reboot.

## Source-only follow-up after Codex independent NBD PASS — 8 MiB cleanup

Codex independently confirmed **NBD SOURCE-ONLY GATE PASS** on
`bd9fac18d06f1c4642c913618de645401611698e`,
blob `3138df5d431b086ad61a4debda04159f6e0a6010`, with all seven
rootless commands and 10 additional timed selftests passing.
The only reported P2 NBD test edge was the exceptional local
socketpair cleanup path if its worker remained alive after two
bounded join attempts.

The primary developer extracted a test-only
`finish_test_socketpair_worker()` from the 8 MiB wire test and
added `selftest_socketpair_cleanup()` with deterministic fake-worker
and fake-socket scenarios. A still-alive worker fails explicitly
with a diagnostic; both socket closes run even on cleanup failure;
shutdown OSError is tolerated only if the subsequent bounded join
proves worker exit. Worker exceptions and original wire-transaction
failures remain failures. Production NBD kernel shutdown and its
intentional descriptor-preserving join are unchanged.

**Executed combined source-only qualification** at
`52a2d6330428c64b39f2f8fe1c42aa1ff70a4cc9`:

- https://github.com/k1moradi/swapz/actions/runs/37788553329
  (NBD rootless, 26/26 complete full selftests)
- https://github.com/k1moradi/swapz/actions/runs/37788553094
  (joint NBD/teardown, 26/26 NBD tests, all teardown mocks,
  ten Bash checks and 11 offline GC analyzer tests)

Both workflows logged `NBD 8 MiB socketpair fault-injected cleanup: PASS`
and the complete preflight, wire, setup/worker-error PASS.
No EBADF or uncontrolled test-thread wait was recorded.

Codex's independent teardown gate previously passed on
`0f2f169631d08fc1b92e2aba1bed398e1ef795ff`;
the later pressure unit-name two-unit prevalidation is being
independently rechecked. Its design-only PID-safe signaling review
must not be mistaken for an approved pidfd implementation.

When updating source-only qualification again, record exact HEAD and
source blobs, preserve the two local untracked `*-verify.state`
files and verify syscall patch containment *before* any NBD selftest.
No real NBD, DM/loop, swap, systemd pressure fixture, module,
fio, physical device, kernel attachment or reboot is authorized.

## Pressure checkpoint migration after independent PID-reuse architecture review

Codex's last independently reported teardown validation passed
at `78e15e38a73c937c329932d8cc1c93c9131c92b7`, confirming both
transient unit names are validated before systemd calls, and identifying
the remaining numeric PID SIGCONT uses in `pressure.sh` and
`pressure-teardown.sh`.

The primary developer has now **removed these pressure numeric-PID
signal paths**. The helper does not SIGSTOP itself; instead it
publishes nonce-bound phase markers (`filled`, `verified`) and
blocks on distinct atomic, private `release-filled` /
`release-verified` files. The controller uses a fresh 128-bit
nonce per unit; the helper holds its allocated pressure buffer while
waiting and imposes a monotonic timeout. The pressure cleanup uses
systemd's named-unit stop and cgroup-empty verification with no
manual PID resume.

Independent source-only code paths were exercised in eight new
rootless `pressure-checkpoint-test.py` cases: two-phase handshake,
wrong-phase and cross-unit nonce, malformed/reused files, timeout,
interruption, readback corruption and successful release. Pressure
teardown mocks now assert zero numeric-PID signals, including when
systemctl returns a nonzero MainPID, and maintain stop/verify/swapoff/
cleanup dependency order.

**Executed GitHub Actions PASS**, tested commit
`1c5cfe5305ba0bad9c8edbf404390b4093bdfbec`:

- https://github.com/k1moradi/swapz/actions/runs/37791843695
  — teardown source safety, 8 protocol tests, 11 offline analyzer tests
- https://github.com/k1moradi/swapz/actions/runs/37791843564
  — combined NBD/teardown, 8 protocol tests, 26 full NBD selftests,
  11 offline analyzer tests

**Next independent host task:** when Codex's gated pidfd recall
prototype finishes, independently inspect the new pressure token
protocol source and its mock boundaries before any separately approved
live pressure fixture. Do not infer that this source-only change
proves production systemd behavior. The Bash recall PID check-to-signal
race remains unresolved until the new supervisor is integrated and
independently requalified.

Keep both host-local `local-*-verify.state` files unchanged. Never
run real systemd units, pressure fixtures, block devices, swap
commands, kernel modules, physical disk tests, fio or reboot absent
fresh explicit authorization.

## Pressure checkpoint token file-integrity regression handoff

While Codex independently develops the recall gated-pidfd
supervisor, the primary developer hardened private pressure
checkpoint markers and releases. They no longer trust unbounded
`Path.read_bytes()` or shell `cat`. Checkpoint reads validate
the file without following symlinks, reject FIFOs, hardlinks,
non-regular files, overlong contents and lstat/open inode changes,
and read only the exact expected token length (plus one).
The new controller-side `check` mode validates both markers
without creating release files; `release` remains exact-nonce,
phase-specific and no-replace atomic.

New rootless cases grow the suite from 8 to **16 tests**. Each
workflow runs one suite and then **10 additional independent timed
suite processes**. Tested results:

- Teardown: https://github.com/k1moradi/swapz/actions/runs/37794454277
  commit `6755e82b18c59f9b9047098ec6da97dba620c3f6` — PASS.
- Combined: https://github.com/k1moradi/swapz/actions/runs/37794468550
  commit `45ac8b7dc668200315bea8556708bffa944dcb3d` — PASS,
  26 NBD userspace selftests and 11 offline analyzer tests included.

The two executions share the same pressure code/tests; the
subsequent revision added the combined workflow repeat step.
These source-only mocks do not exercise real pressure, systemd,
swap or block devices. Codex's separate recall pidfd prototype
has not been integrated; do not claim PID reuse elimination.

Future independent review: preserve the two host-local
`local-*-verify.state` files and verify that malformed checkpoint
files cannot lead to release or device teardown. No actual DM/loop,
NBD, swap, module, fio or physical-device operations are permitted.

## Pressure production phase-controller regression and fail-closed repair

During Codex's separately assigned rootless pidfd supervisor work,
the primary developer made the pressure fixture's phase controller
sourceable from `tests/runtime/pressure-runner.sh`, with no action at
import time. The real `pressure.sh` sources and invokes that exact
function. A new rootless shell regression mocks all systemd, cgroup,
DM, swap and process operations while exercising the actual controller
and real private-file token CLI.

**New safety finding, now fixed:** in a conditional call context,
Bash suppresses `set -e` for the body of the called function.
Failed verified-accounting assertions (including
`memory.swap.current=0`) previously did not necessarily stop
execution and could allow `release-verified`. The new regression
caught this. Production now explicitly checks every required
inventory read and the exact `failed=0` DM status field, demands
positive decimal memory-swap and used-swap counts and positive
`gc_pages` where required, and returns failure before any
inappropriate phase release. It also guards unit launch, checkpoint
polling and command failures instead of relying on implicit errexit.

Rootless controller cases include both positive paths; malformed,
missing, symlink and FIFO phase markers; wrong cgroup, early unit exit,
bad/unavailable DM status, no measured memory swap, no swap used,
zero GC pages and unit failure. The existing static test now asserts
that production actually sources the tested controller library.

**Exact-source combined CI PASS**
`c484ac0c9a90c5ff33b0c17b2b1044f5be80110d`:

- Teardown: https://github.com/k1moradi/swapz/actions/runs/37801182069
- Combined NBD and teardown:
  https://github.com/k1moradi/swapz/actions/runs/37801181958

Both run the new controller gate, pressure token mocks and teardown
regressions. The combined workflow additionally ran static NBD syscall
isolation, 26 NBD selftests and 11 offline analyzer tests.
Previously failing experimental CI revisions were corrected before
these final PASS results.

This is source-only rootless coverage; do not interpret it as real
systemd, pressure workload, swap, kernel, throughput or GC-overlap
qualification. Codex's independent supervisor prototype remains
unintegrated and the recall PID-reuse limitation persists.
