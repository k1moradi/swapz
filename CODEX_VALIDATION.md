# swapz V2.1 — Codex Validation and Benchmark Goal

## Role

You are the secondary validation and benchmarking agent for `swapz`.

The primary developer owns kernel fixes and architecture decisions. Your job is to build,
execute, stress, reproduce, measure, and report.

Do not commit, push, redesign, or broadly refactor kernel code.

A minimal temporary local change is allowed only for an obvious mechanical test-harness or
build-script defect that blocks testing. Preserve the original failure and report the exact
diff plus before/after results.

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
```

Requirements:

```text
branch = main
HEAD = origin/main
dkms.conf PACKAGE_VERSION = 0.2.1
kernel contains SWAPZ_WRITE_BATCH_BLOCKS
kernel status contains physical_write_reqs
kernel status contains multi_write_reqs
kernel status contains max_write_batch
```

Verify:

```bash
grep 'PACKAGE_VERSION="0.2.1"' dkms.conf
grep -n 'SWAPZ_WRITE_BATCH_BLOCKS' kernel/dm-swapz.c
grep -n 'physical_write_reqs' kernel/dm-swapz.c
grep -n 'multi_write_reqs' kernel/dm-swapz.c
grep -n 'max_write_batch' kernel/dm-swapz.c
```

If any check fails, stop with `WRONG CHECKOUT`.

The validated V2 A/B reference is branch `v2`, commit:

```text
1e3a0c71b4e514bccae58d79be9f319640478b5c
```

Do not replace `main` with that branch except for explicit A/B benchmark runs.

Your final report must begin:

```text
TESTED_BRANCH=main
TESTED_HEAD=<actual HEAD equal to origin/main>
CANDIDATE=V2.1_WRITE_BATCHING
```

## What changed from validated V2

Validated V2 fixed V1's allocator/write-amplification problem but remained slow because each
physical 4 KiB output was issued as one synchronous lower request.

V2.1 keeps the V2 segment-GC architecture and changes only the physical output path:

- one serialized `WQ_MEM_RECLAIM` worker remains;
- lower queue depth remains one;
- up to eight consecutive physical 4 KiB outputs are staged;
- one lower request may therefore contain up to 32 KiB;
- raw pages and compressed containers share the same batch;
- GC output uses the same batch path;
- mappings become authoritative only after the entire lower batch succeeds;
- reads, DISCARD, flush, PREFLUSH, and segment transitions force pending output to commit;
- a failed batch must leave previous mappings authoritative;
- the single-record compression wait is reduced from 500-1000 us to 50-100 us.

This is an optimization of V2, not a new allocator.

## Historical V2 measurements to compare against

On the prior 1 ms/request disposable virtual stack, validated V2 showed:

```text
partial/incompressible lower writes: ~1.00x raw
partial/incompressible V2 QD1:       ~2.0 MB/s
partial/incompressible V2 QD8:       ~3.85 MB/s
raw QD1:                              ~4.07 MB/s
raw QD8:                              ~31 MB/s
V2 live-GC tail latency:              ~7.662 ms
V1 live-set rotation latency:         ~1.03 s
```

Highly compressible QD8 V2 reduced about 67.1 MB logical/raw lower writes to about 8.47 MB.

V2.1 must preserve V2's endurance result while reducing lower request count and request
overhead.

## Phase 1 — Build and model

Record environment and build on the Linux 7.0.x machine:

```bash
uname -a
cat /proc/version
getconf PAGESIZE
gcc --version
clang --version
fio --version

make -C kernel clean KDIR=/lib/modules/$(uname -r)/build
make -C kernel KDIR=/lib/modules/$(uname -r)/build W=1
make -C userspace clean
make -C userspace
make -C tests clean
make -C tests test
```

Run the model under ASan + UBSan.

The checked-in mixed raw/compressed GC fixture has been corrected. It must now pass without a
temporary patch and must actually report live GC work (`gc_pages > 0`).

Any compile error, warning attributable to swapz, model failure, or sanitizer diagnostic is
a failure.

## Phase 2 — Fixed kernel regressions

Load the newly built module and run:

```bash
sudo ./scripts/loop-smoke.sh
sudo ./scripts/rotation-regression.sh
sudo bash ./scripts/write-batch-regression.sh
```

The new batching regression must show:

```text
raw_pages > 0
physical_write_reqs > 0
multi_write_reqs > 0
max_write_batch > 1
physical_write_reqs < raw_pages
failed=0
```

Inspect `dmesg` and `journalctl -k` after each phase.

## Phase 3 — V2 correctness regression

Repeat the validated V2 correctness suite against V2.1:

- five deterministic 100,000-operation seeds;
- long mixed live-GC stress;
- victim selectivity and packed-container GC;
- lower read/write fault injection;
- upper/lower DISCARD fallback;
- 100 lifecycle cycles;
- bounded real Linux swap pressure;
- swapoff and second swapon.

All previously validated correctness properties must remain true.

Pay special attention to batching failure semantics:

1. inject a lower write failure while a multi-block batch is pending;
2. every BIO belonging to that failed batch must fail;
3. no mapping from the failed batch may become authoritative;
4. an older successfully-written mapping must remain readable where the target's failure
   policy permits verification;
5. no silent partial-batch success is acceptable.

## Phase 4 — Batch observability

For representative QD1 and QD8 workloads record:

```text
logical_write
physical_write
physical_write_reqs
multi_write_reqs
max_write_batch
compressed_pages
raw_pages
gc_write
gc_read
gc_victims
failed
```

Also record the actual lower block-device write-I/O count and sectors written from
`/sys/class/block/<lower>/stat`.

Calculate:

```text
physical blocks / swapz lower request
lower write-I/O reduction versus validated V2
lower sectors / logical sectors
```

The internal request counters and lower-device request counters should tell a consistent
story.

## Phase 5 — Mandatory V2 versus V2.1 A/B

Use the same disposable backing stack, logical target size, fixed logical I/O volume, random
seed, block size, compressibility, and queue depth.

Compare:

```text
V2 branch: 1e3a0c71b4e514bccae58d79be9f319640478b5c
V2.1:      current origin/main
```

Unload the module and remove all temporary devices between versions.

Run at minimum:

```text
100% compressible: QD1, QD8
50% compressible:  QD1, QD8
0% compressible:   QD1, QD8
```

Use fixed logical bytes, not fixed duration.

Report for both versions:

| Workload | Version | QD | Throughput | Avg lat | p95 | p99 | Max | Lower write I/Os | Lower write bytes | GC write | GC read |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

For V2.1 also include `physical_write_reqs`, `multi_write_reqs`, and
`max_write_batch`.

## Phase 6 — QD1 requirement

QD1 is a primary target, not an afterthought.

The lower write batch cannot create concurrency when only one upper request exists, so the
important V2.1 QD1 change is the shorter single-record pack wait.

Measure QD1 carefully for all three data classes.

Determine whether the prior approximately 2x partial/raw penalty versus raw is materially
reduced.

Also verify the shorter wait does not destroy compression packing under normal swap-out
bursts.

## Phase 7 — QD8 diagnostic

QD8 is a diagnostic of request overhead, not a goal to compete with NVMe.

On the 1 ms/request virtual stack, validated V2 was limited to about 3.85 MB/s for
partial/incompressible QD8 while raw reached about 31 MB/s.

V2.1 should demonstrate that several consecutive 4 KiB outputs can share one serialized
lower request.

The key evidence is:

```text
max_write_batch > 1
multi_write_reqs > 0
substantially fewer lower write I/Os
material QD8 throughput improvement over V2
```

Do not declare failure merely because raw QD8 still benefits from eight concurrent lower
requests. The physical design target remains serialized media.

## Phase 8 — Endurance regression

V2.1 must not undo the validated V2 endurance result.

For partial and incompressible long churn:

```text
V2.1 lower bytes should remain approximately raw, not return toward V1's 2.86x raw
GC write amplification must not materially increase
host-LBA traversal must remain broad
```

For highly compressible queued writes, useful lower-byte reduction must remain.

## Phase 9 — GC latency regression

Repeat the live-GC latency probe.

Validated V2 was approximately 7.662 ms on the prior virtual test.

Report steady, segment-switch, and GC-triggering latency. Batching should not reintroduce
V1-scale stalls.

## Phase 10 — Physical-media safety

No physical test device is implicitly authorized.

If the operator does not explicitly identify an exact disposable physical device/partition,
report:

```text
PHYSICAL BENCHMARK: NOT RUN
```

Do not guess based on existing disks or swap partitions.

## Required conclusions

Explicitly answer:

1. Did V2.1 preserve V2 correctness?
2. Did multi-block batching actually occur?
3. By how much did lower write-I/O count fall?
4. Did partial/incompressible QD8 improve versus V2?
5. Did QD1 improve after reducing the pack wait?
6. Did lower bytes written remain at or below the V2 level?
7. Did highly compressible packing remain effective?
8. Did GC latency or write amplification regress?
9. Is serialized 32 KiB batching a good fit for the intended old storage target?

## Final status

Choose exactly one:

```text
BLOCKED — CORRECTNESS FAILURE
CORRECTNESS PASS, BATCHING INEFFECTIVE
CORRECTNESS PASS, VIRTUAL PERFORMANCE IMPROVED — PHYSICAL BENCHMARK NEEDED
V2.1 PROOF-OF-CONCEPT SUCCESS
```

Use `V2.1 PROOF-OF-CONCEPT SUCCESS` only if an explicitly authorized physical target has
also demonstrated the intended performance/endurance benefit.

Do not commit or push changes.
