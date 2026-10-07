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
