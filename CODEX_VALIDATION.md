# swapz V2 — Codex Validation and Benchmark Goal

## Role

You are the secondary validation and benchmarking agent for `swapz`.

The primary developer owns kernel fixes and architecture decisions. Your job is to build,
execute, stress, reproduce, measure, and report.

Do not commit, push, redesign, or broadly refactor kernel code.

You may make a minimal temporary local change only when a test harness or build script has
an obvious mechanical defect that blocks testing. Preserve the original failure and report
the exact diff and before/after result.

A failure is useful. Do not optimize the report toward success.

## Read first

Read:

```text
README.md
DESIGN.md
TESTING.md
VALIDATION.md
kernel/dm-swapz.c
userspace/swapzctl.cpp
tests/swapz_model.cpp
scripts/loop-smoke.sh
scripts/rotation-regression.sh
bench/block-benchmark.sh
```

Record the exact `origin/main` commit tested. Do not test a stale checkout.

## V2 purpose

V1 correctness passed on Linux 7.0.x, but its whole-live-set arena compaction failed the
performance/endurance objective.

The historical V1 result is preserved on branch `v1`.

V2 replaces V1 arena copying with:

- fixed 1 MiB / 256-block append segments;
- one OPEN segment;
- FREE, OPEN, CLOSED, and CLEANING states;
- rotating FREE-segment allocation;
- per-physical-block live-record counters;
- per-segment live-block counts;
- a 25% logical-size GC reserve plus at least two segments;
- lowest-live CLOSED victim selection;
- bounded victim-local reverse scratch;
- source-physical-block grouping during GC;
- relocation of only mappings still resident in the victim;
- one lower read per live source block;
- a serialized `WQ_MEM_RECLAIM` worker;
- no runtime heap allocation by swapz;
- LZ4 packed containers and raw fallback retained;
- no persistent metadata;
- no hibernation;
- no swapfile backing;
- no encryption.

The primary target remains old serialized storage: HDD, USB flash, SD/eMMC, and old SATA
SSD, not high-performance NVMe.

## Critical V2 hypotheses

Prove or disprove:

1. V2 preserves the V1 correctness result.
2. GC moves only victim-resident live mappings, never the full logical live set.
3. Partially-compressible and incompressible churn no longer produces V1's approximately
   2.86x lower-device write amplification.
4. GC-triggering latency is materially lower than V1's approximately 1.03 second
   full-live-set rotation result on the same 1 ms delayed stack.
5. Highly compressible queued writes retain useful packing and lower-write reduction.
6. Mapping-table scanning does not become a dominant CPU/latency problem.
7. Host allocation traverses segments broadly before reuse.
8. Missing or failing DISCARD remains an optimization issue only.
9. Lower read/write errors never produce silent data corruption.
10. Real swap pressure does not cause reclaim recursion, worker deadlock, or swapoff hangs.

## Safety

Treat every physical-media test as destructive.

Never destructively test root, mounted filesystems, active swap, boot/system partitions,
valuable data, or an ambiguous physical device.

Before any physical test record:

```bash
lsblk -o NAME,KNAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,ROTA,MODEL,SERIAL
lsblk -D
findmnt
cat /proc/swaps
```

Only use a physical device when the operator explicitly identifies that exact device or
partition as disposable.

Otherwise use loop devices or disposable DM stacks.

## Phase 1 — Source, environment, build

Start clean and current:

```bash
cd ~/swapz
git restore .
git pull --ff-only
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

Record:

```bash
uname -a
cat /proc/version
getconf PAGESIZE
gcc --version
clang --version
ld --version
dmsetup version
fio --version
```

Primary build gate on Linux 7.0.x:

```bash
make -C kernel clean KDIR=/lib/modules/$(uname -r)/build
make -C kernel KDIR=/lib/modules/$(uname -r)/build W=1
make -C userspace clean
make -C userspace
make -C tests clean
make -C tests test
```

Run the C++ model under ASan + UBSan.

Zero swapz compiler warnings are expected.

If the module does not build, report the first meaningful diagnostic and stop kernel runtime
testing. Continue independent userspace/model tests.

## Phase 2 — Model-specific V2 checks

The model must exercise segment states and victim GC, not the old V1 arena algorithm.

Verify that model tests cover:

- compressed packing;
- raw fallback;
- overwrite/latest-write-wins;
- logical discard;
- segment switches;
- victim cleaning;
- mixed raw/compressed GC;
- hot-page churn;
- randomized rewrite/read/discard churn.

ASan and UBSan must remain clean.

## Phase 3 — Kernel smoke and fixed regressions

Install/load the newly built module temporarily.

Run:

```bash
sudo ./scripts/loop-smoke.sh
sudo bash ./scripts/rotation-regression.sh
```

The rotation regression now means a V2 segment boundary.

It must cover both:

```text
raw/incompressible foreground payload
compressed foreground payload
```

Verify:

- empty fsync succeeds;
- post-write fsync succeeds;
- data reads back exactly;
- at least one segment switch occurs;
- raw and compressed counters are exercised;
- `failed=0`;
- teardown succeeds.

Inspect `dmesg` and `journalctl -k`.

Any BUG, WARN, Oops, hung task, lockup, sanitizer report, refcount error, or data mismatch is a
failure.

## Phase 4 — Deterministic randomized block validation

Run at least 100,000 operations using:

```text
seed 0x5a7a2026
seed 0x00000001
seed 0x12345678
seed 0xdeadbeef
seed 0x7fffffff
```

Include writes, rewrites, reads, flushes, logical DISCARD, compressed data, and
incompressible data.

Every read must match an independent userspace reference.

Record per seed:

```text
writes
rewrites
reads
flushes
discard ranges/pages
segment switches
gc_victims
gc_scanned
gc_pages
gc_read
gc_write
compressed_pages
raw_pages
failed
```

Force actual GC, not only free-segment traversal.

## Phase 5 — Long multi-GC correctness

Run a long mixed workload containing:

- frequently rewritten hot pages;
- long-lived cold pages;
- logical discards;
- highly compressible pages;
- incompressible pages.

Target at least 100 victim cleanings when practical.

Verify all live pages against a userspace reference periodically and after the final GC.

Important invariants:

- a FREE segment must have zero live mappings;
- a cleaned victim must reach zero live blocks before reuse;
- GC must not resurrect stale mappings;
- a failed replacement must not destroy the last known-good mapping;
- `failed` remains zero during successful tests.

## Phase 6 — GC selectivity measurement

This is a primary V2 test.

Create a workload where only a small hot subset is repeatedly rewritten while most logical
pages remain cold.

Measure:

```text
logical page count
gc_victims
gc_scanned
gc_pages
gc_read
gc_write
segment switches
```

The map scan may touch all logical mapping entries, but physical relocation must be tied to
the selected victim's live data.

Compare this with the V1 full-live-set behavior.

Explicitly report:

```text
GC relocated pages per victim
GC bytes written per victim
logical-map entries scanned per victim
```

## Phase 7 — DISCARD matrix

Test:

### No lower DISCARD

Expected:

```text
lower_discard=off
normal read/write works
segment switching works
victim GC works
```

### Lower DISCARD available

Verify it is detected from the actual queue.

### Runtime lower-DISCARD rejection

If safely reproducible on a disposable DM stack:

```text
discard failure counted
lower discard becomes off
normal read/write continues
target does not fail solely because DISCARD failed
```

### No upper page DISCARD

Correctness must remain unchanged. Compare GC work with and without upper invalidation hints.

## Phase 8 — Lower I/O error behavior

Use disposable DM fault layers.

Inject lower read and write errors.

Verify:

- affected BIO fails;
- target failure is explicit;
- a failed new write does not silently replace a prior good mapping;
- no fabricated successful data is returned;
- no crash or worker deadlock occurs;
- teardown remains possible when kernel state permits.

## Phase 9 — Lifecycle

Run 100 create/use/destroy cycles.

Verify no leaked target, loop device, workqueue symptom, module reference, or delayed kernel
warning.

## Phase 10 — Real Linux swap pressure

Only after block correctness passes.

Create a disposable swapz target, run `mkswap`, activate it, and generate bounded memory
pressure.

Exercise swap-out, swap-in, churn, segment GC, swapoff, and a second swapon.

Monitor:

```bash
vmstat 1
cat /proc/swaps
cat /proc/vmstat
dmsetup status swapz0
dmesg -w
```

Look for reclaim recursion, allocation failures, worker starvation, BIO stalls, OOM caused
by swapz, and swapoff deadlock.

## Phase 11 — Benchmark methodology

Raw and swapz must submit the same logical byte count.

Do not compare fixed-duration runs by lower sectors written; that biases the result because
the faster path submits more logical data.

Use a fixed seed and fixed logical I/O volume.

For a physical disposable device, the checked-in benchmark can be used:

```bash
sudo ./bench/block-benchmark.sh \
  --backing /dev/TESTPART \
  --size 1G \
  --io-size 2G \
  --iodepth 1 \
  --destroy
```

Repeat at QD8.

Run paired raw and swapz workloads for:

```text
100% compressible
50% compressible
0% compressible
```

Record the actual lower-device sector deltas.

## Phase 12 — Safe virtual V1-versus-V2 comparison

If no physical device is authorized, reproduce a safe virtual lower stack similar to the
previous 1 ms/request test.

Absolute throughput is not a 20 MB/s physical-device claim.

Use it for an allocator A/B comparison.

The V1 reference is branch:

```text
v1
025edff9fbe1d402cf6eab294e3ce1627e49a1e9
```

Run the same fixed logical I/O volume, seed, logical size, physical size, QD, and delayed
lower stack on V1 and V2.

Unload the module and remove all DM/loop devices between versions.

Compare:

```text
lower write sectors
lower read sectors
throughput
average latency
p95
p99
max latency
GC/compaction bytes
GC-triggering latency
```

The most important V2 comparison is the 50%-compressible and incompressible long-churn case
that produced about 2.86x raw writes in V1.

## Phase 13 — GC latency

Measure individual writes around GC boundaries.

Report steady-state versus GC-triggering:

```text
average
p95
p99
max
```

Compare V2 with the historical V1 approximately 1.03 second rotation-triggering result on
the same delayed stack.

Do not hide tail latency inside average throughput.

## Phase 14 — Host-LBA distribution

Use segment cycle counters and block tracing if practical.

Report:

```text
segment_cycle_min
segment_cycle_max
segment switches
range of lower LBAs written
whether FREE-segment allocation advances broadly before reuse
```

Call this host-LBA distribution, not NAND wear leveling.

## Phase 15 — Required benchmark table

Return at least:

| Workload | Version/path | QD | Logical bytes | Throughput | Avg lat | p95 | p99 | CPU | Lower write bytes | Lower read bytes | GC write | GC read | GC victims | Write ratio |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

Include raw, V1 where compared, and V2.

## Decision metrics

Explicitly answer:

1. Did V2 eliminate V1's multi-x write amplification for partial/raw churn?
2. How much lower I/O does highly compressible V2 traffic save?
3. What is V2 QD1 overhead when packing opportunities are weak?
4. How many pages/bytes are relocated per victim?
5. What is the cost of scanning the logical map?
6. How large are GC-triggered latency spikes?
7. Does GC still preserve an endurance benefit after its reads/writes are included?
8. Does segment allocation traverse the backing space broadly?
9. Is the single worker still appropriate for the intended slow-device target?

## Final status

Choose exactly one:

```text
BLOCKED — correctness failure
CORRECTNESS PASS, PERFORMANCE FAIL
CORRECTNESS PASS, PHYSICAL BENCHMARK STILL NEEDED
V2 PROOF-OF-CONCEPT SUCCESS
```

Then list the three highest-priority findings for the primary developer.

Do not commit or push changes.
