# Experimental V2.2 bestfit4 kernel mode — benchmark preparation

This is the **first kernel implementation step** of a size-aware allocator, not
the new 8/16 KiB physical-extent format. The driver remains on the existing
4 KiB wire format and uses the same completed-lower-write and upper BIO
ownership logic as the validated PR #31 code. It is intentionally **opt-in**.

## Invocation and bounds

Existing Device Mapper target tables stay valid:

```
0 <logical_sectors> swapz <verified_backing> opportunistic 64
```

To request bounded 4 KiB best-fit lookahead:

```
0 <logical_sectors> swapz <verified_backing> opportunistic 64 bestfit4
```

Only batches of 4–64 KiB are admitted in `bestfit4` mode; larger batches
are rejected during target creation rather than imposing unbounded memory or
CPU demand. The default `ordered4` mode is unmodified. The experimental
lookahead considers at most 128 surviving records in up to 16 resident 4 KiB
blocks. It checks the full existing geometry/upper-BIO contracts before
considering changes; it strictly falls back to the ordered compactor when no
fewer containers are planned. It allocates all source snapshots and record
coordinates during target construction, **never in the swap I/O hot path**.
The ordered worker owns these buffers exclusively; asynchronous lower
completion callbacks cannot access mutable best-fit scratch.

A full 64 KiB batch snapshot requires 64 KiB data plus 16 original block
descriptors and a 128-record index table. A failed construction frees all of
the above through the existing target destructor. Repacked references still
use the original `swapz_update_repacked_ref()` helper.

## Rootless kernel qualification

CI exercises `tests/runtime/kernel-bestfit4-geometry-test.py` and, more
importantly, extends
`tests/runtime/swapz-compaction-container-contract-test.py` to compile and
**execute the exact production C** for clustered 2200/1600-byte records,
uniform 2072-byte records, each descriptor's byte-level payload, and a
registered upper BIO whose ownership coordinates move during repacking.
The default compactor's original corruption/mutation tests remain active.

The separate `Experimental kernel bestfit4 qualification` workflow also
compiles the kernel module under distribution headers with `W=1`. This is a
**compile-only gate**: no hosted GitHub runner loads modules or performs
privileged tests.

## Guarded real-machine V2.2 comparison

Use the **existing** `tests/runtime/streaming-benchmark.sh --run-live` with
the new explicit `SWAPZ_BENCH_PACKING=bestfit4` option; when the environment
variable is omitted or set to `ordered4`, the original table string is
preserved exactly. The planner rejects batches >64 KiB for best-fit before
root/device setup. A typical controlled `null_blk` comparison uses identical:

- source commit and selected compiled module hash;
- selected dedicated physical host and host/source/module preflights;
- 64 KiB batch, opportunistic strategy, 20 MiB/s and 500000 ns latency;
- 30 second fio runtime, writer QD64, 500 requested reader IOPS;
- 50% and 75% synthetic compressibility cases, separately;
- exact fio CRC32C, sentinel readback, drained kernel/sysfs physical counters;
- reader achieved IOPS, p50/p95/p99 and reader sample count, matching loads.

Example configuration values (the source/module SHA and host checks must first
be established by the test agent):

```sh
export SWAPZ_BENCH_BACKEND=null_blk
export SWAPZ_BENCH_STRATEGIES=opportunistic
export SWAPZ_BENCH_BATCHES=64
export SWAPZ_BENCH_COMPRESS=50
export SWAPZ_BENCH_PACKING=bestfit4
export SWAPZ_BENCH_MBPS=20
export SWAPZ_BENCH_LATENCY_NS=500000
export SWAPZ_BENCH_QD=64
export SWAPZ_BENCH_RUNTIME=30
export SWAPZ_BENCH_READ_IOPS=500
export SWAPZ_BENCH_DISCARD=0
export SWAPZ_BENCH_KEEP_ARTIFACTS=1
# Establish all required SWAPZ_BENCH_SOURCE_SHA, MODULE_SHA256,
# host/source preflights before invoking the guarded --run-live runner.
```

Repeat with `SWAPZ_BENCH_PACKING=ordered4` and with compression level 75.
**The 50% uniform ~2072-byte fio data cannot fit two records in 4 KiB**:
no physical-write reduction is predicted from this option, and a lower
read-p99 claim cannot be made without matched achieved reader IOPS.
The clustered 2200/1600 synthetic geometry supports 12 to 8 containers in
one bounded window; a corresponding reproducible **mixed-payload real fio
generator is a separate required benchmark extension**, not silently
substituted for the uniform benchmark.

## Authorization and device safety

The user authorized privileged work on a dedicated physical Linux development
machine and a verified, disposable `/dev/sdb1` SD-card partition, **but
strictly prohibited any reboot**. Check canonical device identity, active
swap, memory headroom, mounts/holders, and normal DM/module teardown before
destructive physical media work. The existing benchmark runner accepts only
`null_blk` or `nbd` and **must not be redirected to `/dev/sdb1`**.
A separately reviewed SD-specific harness is needed for actual physical media.

No kernel module or SD-card write has been executed in this PR by ChatGPT.

## Next kernel milestone: aligned multi-block extents

The current bestfit4 change is deliberately not a solution to the uniform
50% compression cliff. A versioned 8/16 KiB extent format must separately
prove: full-extent completion authority, per-record generation metadata,
mapping to start block and extent size, spanning one/two physical reads,
CRC32C before upper BIO success, GC survivor relocation with no premature
victim release, finite free-segment reserve, no partial-write data loss,
and acceptable cold-read p99. Prototype all paths on a separately reviewable
experimental branch before any real device test.
