# swapz V2.2 — Streaming Strategy Validation and Plateau Benchmark

## Role

You are the secondary validation and benchmarking agent for `swapz`.

The primary developer owns kernel fixes and architecture decisions. Your job is to build,
stress, benchmark, measure, reproduce, and report.

Do not commit, push, redesign, or substantively patch kernel code.

A minimal temporary test-harness correction is allowed only for an obvious mechanical test
problem. Preserve the original failure and report the exact diff.

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
inflight_blocks=
fill_blocks=
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
