# swapz V1 — Codex Validation and Fixing Goal

## Role

You are the secondary validation and test agent for swapz, an experimental Linux Device Mapper target implementing LZ4-compressed swap on dedicated block devices.

Your primary job is to test, reproduce, measure, and report. The primary development/fixing agent owns substantive kernel changes and architecture decisions.

You may make a minimal local fix only when required to continue testing and the failure is clearly mechanical, for example a kernel API compatibility adjustment, warning-clean build fix, build-script typo, or test-harness bug. Do not redesign the allocator, change the public interface, change the storage layout, refactor unrelated code, or hide failures.

Do not push, merge, or commit tester changes to the upstream GitHub repository. If you modify anything locally, preserve the original failure and include the exact diff plus before/after results in the report.

A failure is useful. Do not optimize the report toward declaring success.

## Read first

Read these before testing:

    README.md
    DESIGN.md
    TESTING.md
    VALIDATION.md
    kernel/dm-swapz.c
    userspace/swapzctl.cpp

If implementation and documentation disagree, report the discrepancy rather than silently choosing one behavior.

## V1 invariants

V1 intentionally targets old, slow, serialized storage:

- HDD
- USB flash
- SD/eMMC
- old SATA SSD
- roughly 10–100 MB/s devices
- queue-depth-1 and low-concurrency workloads are first-class targets

V1 intentionally does not target high-performance NVMe.

The design must remain:

- Device Mapper target: swapz
- kernel module: dm-swapz.ko
- primary kernel target: Linux 7.0.x
- 4 KiB PAGE_SIZE only
- dedicated block device/partition backing only
- LZ4 only
- one serialized WQ_MEM_RECLAIM worker
- volatile RAM mappings
- 4 KiB packed physical containers
- raw 4 KiB fallback for poorly compressible pages
- append-only arena allocation
- round-robin arena rotation
- deliberately simple arena compaction
- optional upper swap DISCARD
- optional lower-device DISCARD
- no correctness dependency on DISCARD
- no encryption
- no swapfile backing
- no hibernation
- no persistent metadata
- no logical-capacity overcommit

The physical backing device is intentionally larger than the exposed logical swap device. This provides space for all-raw live data during rotation and increases the LBA range traversed before reuse.

The endurance claim is host-side only: swapz should reduce host bytes and avoid repeatedly rewriting a small LBA region. Do not claim that swapz controls the flash controller FTL or NAND wear leveling.

## Capability rule: detect, use, fall back

Assume optional features may be missing on old hardware.

For every optional feature:

1. detect before use;
2. use it when genuinely available and safe;
3. test runtime failure handling when practical;
4. use the defined fallback when unavailable or broken;
5. never convert an optional-feature failure into silent corruption.

Upper swap DISCARD and lower-device DISCARD are independent.

- Upper DISCARD tells swapz which logical mappings can be invalidated.
- Lower DISCARD is only an arena-reuse optimization.
- A lower device with no DISCARD must work normally.
- If lower DISCARD is advertised but fails at runtime, lower DISCARD should become disabled and normal reads/writes should continue.

Never infer DISCARD support from device type. Query the actual queue/device.

## Primary validation objectives

Prove or disprove:

1. Arbitrary 4 KiB pages survive writes, reads, rewrites, packing, raw fallback, logical discard, and repeated arena rotations.
2. Memory pressure does not cause reclaim recursion, deadlock, lockup, use-after-free, corruption, or unbounded allocation.
3. Compressible workloads reduce actual lower-device sectors written, not just the reported LZ4 payload.
4. On slow serialized storage the physical-I/O reduction improves or approximately preserves throughput after CPU cost.
5. Arena rotation spreads host writes across the backing partition.
6. Compaction write amplification stays low enough to preserve the endurance/I/O benefit.
7. Incompressible data falls back safely to raw pages without corruption or pathological behavior.
8. Missing upper DISCARD remains correct, although compaction may become less efficient.
9. Unsupported or broken lower DISCARD never prevents ordinary swap I/O.
10. Lower read/write errors propagate as I/O failures and never produce silent data corruption.
11. Failed writes do not replace a previously known-good mapping.
12. Repeated activation, swap-on, swap-off, teardown, and module lifecycle operations are safe.
13. swapz counters and lower block-device counters are consistent enough to support benchmark conclusions.

## Destructive-test safety

Treat every physical-media benchmark as destructive.

Never run destructive tests against:

- the root device;
- a mounted filesystem;
- valuable data;
- an active swap device;
- an unspecified or ambiguous physical device.

Begin with loop devices, disposable virtual disks, or disposable Device Mapper stacks.

Only use real physical media after the operator explicitly identifies a dedicated test partition/device.

Before every physical destructive test record:

    lsblk -o NAME,KNAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,ROTA,MODEL,SERIAL
    lsblk -D
    findmnt
    cat /proc/swaps

Also record the exact lower-device queue properties when available:

    logical_block_size
    physical_block_size
    minimum_io_size
    optimal_io_size
    rotational
    discard_granularity
    discard_max_bytes

Abort rather than guess if identity is ambiguous.

Do not run blkdiscard on real media merely to discover support. Queue inspection is non-destructive. Runtime discard-failure testing belongs on disposable stacks unless explicitly approved.

## Phase 1 — Environment and source state

Record:

    uname -a
    cat /proc/version
    getconf PAGESIZE
    gcc --version
    clang --version
    ld --version
    dmsetup version
    swapon --version
    fio --version
    git status --short
    git rev-parse HEAD

Also record distribution, architecture, CPU, logical CPU count, RAM, and kernel config source if available.

PAGE_SIZE must be 4096 for V1. A different page size is NOT RUN/out of scope unless the target itself fails incorrectly.

Report pre-existing working-tree modifications.

## Phase 2 — Build gates

The primary compatibility target is an exact Linux 7.0.x kernel with matching headers.

GCC:

    make -C kernel clean KDIR=/lib/modules/$(uname -r)/build
    make -C kernel KDIR=/lib/modules/$(uname -r)/build W=1

Clang, when supported by the kernel build environment:

    make -C kernel clean KDIR=/lib/modules/$(uname -r)/build
    make -C kernel KDIR=/lib/modules/$(uname -r)/build W=1 LLVM=1

Userspace/model:

    make -C userspace clean
    make -C userspace
    make -C tests clean
    make -C tests test

Run the model under ASan + UBSan using TESTING.md.

Zero compiler warnings are expected.

Other kernels are useful secondary data, but do not substitute them for 7.0.x validation.

For every build warning/failure report exact command, full relevant diagnostic, kernel, compiler, and source location.

## Phase 3 — Disposable kernel smoke test

Run:

    sudo ./scripts/loop-smoke.sh

Verify:

- module loads;
- DM target creates;
- invalid geometry fails cleanly;
- written data reads back exactly;
- compressed packed pages verify;
- incompressible/raw pages verify;
- latest rewrite wins;
- logical discard does not damage neighbors;
- multiple arena rotations preserve every live mapping;
- dmsetup status counters are plausible;
- arena_cycle_min and arena_cycle_max advance consistently with round-robin rotation;
- teardown succeeds.

After every run inspect dmesg/journalctl -k.

Any WARN, BUG, OOPS, hung task, lockdep warning, sanitizer finding, slab/refcount/workqueue diagnostic, or data mismatch is FAIL.

## Phase 4 — Debug kernel

When practical repeat smoke/stress on a disposable kernel with useful debug options such as:

    CONFIG_KASAN
    CONFIG_UBSAN
    CONFIG_PROVE_LOCKING
    CONFIG_LOCKDEP
    CONFIG_DEBUG_LIST
    CONFIG_SLUB_DEBUG
    CONFIG_DEBUG_VM

Do not suppress sanitizer/debug failures to continue benchmarking.

If unavailable, report NOT RUN.

## Phase 5 — DISCARD matrix

Test independently.

### Lower device without DISCARD

Expected:

    activation succeeds
    lower_discard=off
    reads/writes work
    arena rotation works

### Upper swap without page DISCARD

Activate without upper page-discard notifications.

Expected:

    correctness unchanged
    upper_discards does not increase
    conservative-live data/compaction may increase

### Lower DISCARD supported

If genuinely supported on a disposable target, verify it is used only as an arena-reuse optimization. Record discard_bytes and discard_failures.

### Lower DISCARD runtime failure

If a safe fault-injection method exists, force a lower discard error.

Expected:

    bounded/fail-only error report
    discard_failures increments
    lower_discard becomes off
    ordinary I/O continues
    target does not fail solely because DISCARD failed

If no safe discard-specific fault injection exists, report NOT RUN; do not redesign the module to manufacture the test.

## Phase 6 — Lower I/O fault injection

Use dm-flakey, dm-error, or another disposable fault layer when suitable.

Test lower read and write errors independently where possible.

For failed writes verify:

- request fails;
- failed data is never acknowledged as successful;
- new mapping is installed only after successful lower write;
- previous valid mapping is not silently replaced;
- no corrupted data is returned as valid.

For failed reads verify:

- request fails;
- no uninitialized/stale buffer is returned as a valid page.

For all faults:

- no kernel crash;
- no hung worker;
- no unbounded retry;
- target failure state is visible if entered;
- teardown remains possible when kernel state permits.

Include exact reproduction stack/commands.

## Phase 7 — Lifecycle stress

Repeat create -> mkswap -> swapon -> workload -> swapoff -> remove.

Target at least 100 cycles if practical.

Also test:

- repeated module load/unload with no target;
- unload attempt while a target exists;
- cleanup after interrupted/failed setup.

Inspect kernel logs after the loop.

## Phase 8 — Real swap-pressure correctness

Only after block-level correctness passes.

Use a disposable/test machine and keep a recovery path.

Drive repeatable memory pressure above RAM but comfortably below logical swap capacity.

Collect, when available:

    vmstat 1
    cat /proc/swaps
    cat /proc/vmstat
    dmsetup status swapz0
    cat /sys/class/block/<backing-device>/stat
    dmesg -w

Exercise swap-out, swap-in, working-set churn, rewrites, long-lived swapped pages, arena rotation, swapoff, and reactivation.

Watch for reclaim recursion, hung tasks, internal-allocation OOM, BIO completion stalls, worker deadlock, corruption, swapoff deadlock, module lifetime bugs, and unexpected long uninterruptible stalls.

Use bounded durations/timeouts.

## Phase 9 — Performance benchmark

The core metric is actual lower-device I/O.

Do not use compression ratio as a substitute.

For every run record when available:

    logical bytes submitted
    compressed payload bytes
    swapz physical-write bytes
    lower sectors written
    lower sectors read
    compaction read/write bytes
    arena rotations
    arena_cycle_min
    arena_cycle_max
    CPU utilization
    throughput
    average latency
    p95/p99 latency
    wall time

Linux block-stat sector counters are in 512-byte sectors.

On the same disposable backing device run:

    A. raw baseline, compressible data
    B. swapz, same compressible data
    C. raw baseline, incompressible/random data
    D. swapz, same incompressible/random data

Test at least iodepth=1 and iodepth=8.

QD1 is a first-class result. V1 packing benefits from multiple pending compressed pages; if QD1 fails to reduce writes, report it plainly.

Tests must be long enough to force arena rotation/compaction. A run ending before rotation is not an endurance test.

Use multiple iterations when practical and report variance, not only the best run.

## Phase 10 — Endurance/write-distribution proxy

Validate three separate claims:

1. compression/packing reduces host bytes;
2. writes are predominantly forward/sequential inside an arena;
3. round-robin arena rotation avoids a persistent hot host-LBA region.

At minimum use:

    physical_write
    lower sectors written
    rotations
    arena_cycle_min
    arena_cycle_max
    gc_read/gc_write
    discard_bytes/failures

After long steady-state operation, arena cycle counts should demonstrate broad round-robin reuse. Report min/max and their difference.

If blktrace/blkparse, block tracepoints, or equivalent read-only tracing is already available, summarize lower-write LBA distribution and sequentiality. If not available, report NOT RUN; do not add it as a dependency.

Collect read-only SMART/eMMC health counters where genuinely available. Many USB/SD devices expose none.

Never claim host-write reduction equals the same percentage NAND-wear reduction; the FTL is opaque.

## V1 proof targets

For at least one slow SD/USB/SATA/HDD target, look for at least 1.5x reduction in actual lower-device host bytes written on a representative compressible workload.

Also require:

- throughput improves or remains approximately neutral after CPU overhead;
- total lower writes including compaction stay below raw baseline for the compressible long-run workload;
- incompressible data remains correct;
- incompressible data does not cause runaway amplification/stalls;
- repeated rotations preserve data;
- arena cycle counts confirm broad round-robin reuse.

These are goals, not assumptions.

## Derived metrics

Report at least:

    host-write reduction ratio =
        raw baseline lower bytes / swapz lower bytes

    swapz I/O reduction =
        logical_write / physical_write

    compaction amplification =
        (new-data physical write + compaction write) / new-data physical write

    end-to-end write ratio =
        total lower bytes / logical bytes

State the exact counters used. Never substitute compressed_payload for actual lower writes in endurance claims.

## Fixing policy

You may make only minimal local unblocker fixes for:

- obvious compile/API compatibility;
- warning cleanliness;
- typo/build-script errors;
- deterministic test-harness bugs that do not change intended kernel behavior.

For mapping lifetime, BIO ownership/completion, synchronization, allocator behavior, write atomicity, compaction, reclaim/GFP behavior, Device Mapper semantics, error propagation, layout, packing policy, or performance architecture:

1. reduce to the smallest reproducible failure;
2. identify suspected source lines;
3. explain root-cause hypothesis;
4. provide a minimal proposed patch separately if useful;
5. stop and report for primary-fixer review.

Every local change must include exact diff and before/after results. Do not push it upstream. Do not alter tests or thresholds silently.

## Required consolidated report

### Environment

Kernel/config, distribution, architecture, CPU, RAM, PAGE_SIZE, compiler/tool versions, backing identity, queue properties, DISCARD capabilities.

### Source state

Commit tested, initial git status, all tester modifications.

### Build matrix

For each kernel/compiler:

    PASS / FAIL / NOT RUN
    exact command
    warnings/errors

### Test matrix

For every test:

    PASS / FAIL / NOT RUN
    exact command
    runtime
    key counters
    relevant logs

### Bugs found

For every bug:

    title
    severity: blocker/high/medium/low
    reproduction
    expected
    actual
    logs
    suspected source location
    root-cause hypothesis
    data-integrity risk

### Local fixes

For each tester modification:

    reason
    exact git diff
    before result
    after result

### Performance table

Include workload/data type, iodepth, throughput, average/p95/p99 latency when available, CPU, logical bytes, swapz physical bytes, lower sectors written, compaction bytes, rotations, and write-reduction ratio.

### Endurance observations

Include arena traversal, arena_cycle_min/max, LBA distribution if traced, compaction amplification, DISCARD capability, lower write counters, and health telemetry if available. Distinguish measured host behavior from inferred NAND behavior.

### Final assessment

Choose exactly one:

    BLOCKED — correctness failure
    CORRECTNESS PASS, PERFORMANCE FAIL
    CORRECTNESS PASS, MORE STRESS NEEDED
    V1 PROOF-OF-CONCEPT SUCCESS

Then list the three highest-priority issues for the primary fixer, ordered by data-integrity/correctness risk first, then performance/endurance impact.

## Final reporting rule

Be skeptical and reproducible. A failed hypothesis is a useful result when documented precisely enough for the primary fixer to reproduce. Never hide a failure, silently change a workload, or infer device behavior that was not measured.
