# swapz runtime validation helpers

These scripts preserve the disposable Linux runtime checks used for the V2.1
candidate. They operate on file-backed loop devices created under `/dev/shm`;
they do not select or write a physical disk. They need root, Device Mapper,
loop devices, fio, and a kernel-built `dm-swapz` module. `correctness.sh` needs
`g++`; `ab-benchmark.sh` also needs Git, tar, make, GCC, and matching kernel
headers to build both module versions. `pressure.sh` needs systemd with the
cgroup v2 memory controller. `no-discard-livegc.sh` needs dm-crypt.
`write-batch-trace.bt` is an optional bpftrace probe for recording the lower
`dm_io()` region size.

Run from any directory:

```bash
sudo bash tests/runtime/correctness.sh
sudo bash tests/runtime/no-discard-livegc.sh
sudo bash tests/runtime/write-fault.sh
sudo bash tests/runtime/read-fault.sh
sudo bash tests/runtime/lifecycle.sh
sudo bash tests/runtime/pressure.sh
sudo bash tests/runtime/staged-write-fault.sh
sudo bash tests/runtime/buffer-recall.sh
sudo bash tests/runtime/streaming-benchmark.sh
sudo bash tests/runtime/ab-benchmark.sh | tee swapz-v21-ab.log
```

`correctness.sh` builds `reference.cpp` into a private `/dev/shm` directory,
then runs five seeded randomized runs, long live-GC stress, victim selectivity,
and eight/four/one/zero-live-record packed-container GC cases. The remaining
scripts cover lower DISCARD unavailable, lower read/write errors, 100 lifecycle
cycles and module reload, and bounded swap pressure followed by swapoff and a
second swapon.

The fault tests intentionally expect I/O errors. `write-fault.sh` submits eight
concurrent 4 KiB writes to a lower table whose first physical block works and
whose remainder returns EIO; it checks that all eight upper writes fail and the
older physical block remains unchanged. To observe the attempted batch length
while running that test in another terminal, run:

```bash
sudo bpftrace tests/runtime/write-batch-trace.bt
```

`ab-benchmark.sh` builds the pinned V2 commit and `origin/main` in a private
directory, then runs matched 64 MiB fio workloads at QD1 and QD8 over a
1 ms `dm-delay` stack. It records fio latency/CPU, loop-device read/write I/O
counts and sectors at both the `dm-delay` lower bdev and underlying loop, and each target's status. It also runs a delayed live-GC
latency probe for both modules. The workload uses only `/dev/shm` loop files.
Set `SWAPZ_V21_REF` to benchmark another V2.1 commit. If `origin/main` is not
available, the script falls back to `HEAD`.

The `pressure.sh` helper freezes the bounded process at its initial and verified
holds so `/proc/swaps`, the cgroup's `memory.swap.current`, and `dmsetup status`
can be sampled. It uses a 160 MiB data set with `MemoryMax=64M` and
`MemorySwapMax=192M`, then a 32 MiB set with 16 MiB/48 MiB limits. It regenerates
expected pages during verification instead of keeping a second working-set
copy resident.

These helpers validate the running kernel and local toolchain; they do not
change module source or install a module. Use the repository's build and
fixed-regression instructions before running them, and inspect kernel logs for
errors after fault-injection tests.


## V2.2 streaming tests

V2.2 adds two reusable runtime tests.

### Buffer recall / cancellation

```bash
sudo bash tests/runtime/buffer-recall.sh
```

This uses a deliberately slow `dm-delay` lower device and staged mode. It verifies:

1. a page in the in-flight stream buffer can be read while the second buffer is filling;
2. a page in the filling buffer can be read while the first is being written;
3. pages from both buffers can be recalled while one lower write remains active;
4. all reads return exact data from staged RAM rather than waiting for the delayed lower
   device;
5. a later logical DISCARD makes an unsent generation stale and triggers staged
   cancellation/repacking.

The test intentionally does **not** treat a READ as permission to discard swap data.

### Streaming strategy / plateau benchmark

```bash
sudo bash tests/runtime/streaming-benchmark.sh
```

The benchmark requires configurable `null_blk` controls for memory backing, completion
latency, QD1, maximum sectors, and bandwidth throttling.

Defaults model a 20 MiB/s serialized device with 0.5 ms completion latency and sweep:

```text
strategies:
    immediate
    opportunistic
    staged

batch ceilings:
    4 8 16 32 64 128 256 512 1024 KiB
```

Environment overrides include:

```text
SWAPZ_BENCH_MBPS
SWAPZ_BENCH_LATENCY_NS
SWAPZ_BENCH_RUNTIME
SWAPZ_BENCH_QD
SWAPZ_BENCH_COMPRESS
SWAPZ_BENCH_BATCHES
SWAPZ_BENCH_STRATEGIES
```

A writer and a low-rate QD1 reader run concurrently. The script reports both fio's upper
write-completion bandwidth and end-to-end drain bandwidth after explicitly flushing staged
data. It also records concurrent read latency and lower-device I/O counters.

The summary identifies the first point at >=97% of each strategy's best measured drain
throughput and then chooses the smallest plateau point whose read p99 remains within 10% of
the best read p99 among plateau candidates.

The analytical companion is:

```bash
python3 bench/request-plateau.py --bandwidth 20
```

It is only a sweep-sizing model; it never substitutes for the runtime benchmark.


### Staged asynchronous write-failure recovery

```bash
sudo bash tests/runtime/staged-write-fault.sh
```

This places a staged compressed write over a lower `dm-error` target. The upper write must
early-complete from bounded RAM, the asynchronous lower write must then fail, and the exact
page must still be readable from retained staged RAM while new writes are rejected. This is
the critical safety test for early completion.
