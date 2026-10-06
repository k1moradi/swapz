# swapz V2 testing plan

## 1. Build/static gates

Run both GCC and Clang builds with kernel warning level 1:

```bash
make -C kernel KDIR=/lib/modules/$(uname -r)/build W=1
make -C kernel clean KDIR=/lib/modules/$(uname -r)/build
make -C kernel KDIR=/lib/modules/$(uname -r)/build W=1 LLVM=1
make -C userspace
```

The current tree passes these gates against Debian 6.12.96 headers.

Before real deployment, repeat the kernel build against the exact Linux 7.0.x headers used by each test machine.

## 2. Userspace allocator/model tests

```bash
make -C tests test
```

The model covers:

- compressible packed round-trip;
- incompressible raw fallback;
- latest-write-wins rewrites;
- logical discard;
- forced segment switches and victim GC;
- mixed raw/compressed pack-boundary segment switches;
- 5,000 randomized write/read/discard operations checked against an in-memory reference.

Sanitizer gate:

```bash
g++ -std=c++23 -O1 -g -Wall -Wextra -Wpedantic -Wconversion -Wshadow \
    -fsanitize=address,undefined -fno-omit-frame-pointer \
    tests/swapz_model.cpp -llz4 -o /tmp/swapz-model-asan
/tmp/swapz-model-asan
```

## 3. Loop-device kernel smoke test

Run inside a disposable VM or test kernel matching the built module:

```bash
sudo ./scripts/loop-smoke.sh
```

Required result:

- fio verify completes with no data mismatch;
- `dmsetup status swapz-smoke` reports nonzero compressed pages and physical writes;
- no kernel warnings/OOPS/lockdep reports.

Repeat with KASAN/UBSAN/LOCKDEP if practical.

## 4. Fault/fallback cases

Test independently:

1. backing device with `discard_granularity=0`: target activates and works;
2. mapper activated without `swapon --discard=pages`: target works and rotations preserve data;
3. lower DISCARD runtime rejection: lower discard becomes `off`, swap I/O continues;
4. incompressible fio buffers: raw-page path survives repeated rotations;
5. backing I/O error using `dm-error`/`dm-flakey`: target fails I/O rather than returning corrupted data;
6. repeated `swapoff`/`swapon` and `dmsetup remove` cycles;
7. memory pressure with active swap and module unload prevented while target exists.

## 5. Performance benchmark

Use a dedicated disposable partition.  Never run the destructive benchmark against a root/data device.

```bash
sudo ./bench/block-benchmark.sh --backing /dev/TESTPART --size 1G --runtime 60 --iodepth 8 --destroy
```

Repeat at QD1:

```bash
sudo ./bench/block-benchmark.sh --backing /dev/TESTPART --size 1G --runtime 60 --iodepth 1 --destroy
```

Record:

- fio write bandwidth and latency;
- backing `sectors written` delta from `/sys/class/block/.../stat`;
- `dmsetup status` logical/physical byte counters;
- CPU utilization;
- segment switches/GC and compaction bytes.

### V2 proof thresholds

V1 correctness passed, but its whole-live-set allocator failed the write-amplification target. V2 should not graduate unless, on at least one slow SD/USB target:

- compressible swap-like workload shows **>=1.5x lower backing host bytes written** at a realistic queue depth;
- wall-clock throughput improves or is at least neutral after CPU cost;
- incompressible control is correct and does not catastrophically regress throughput;
- victim-segment GC keeps total physical writes below the raw baseline over a long partially-compressible churn test;
- a GC-triggering write no longer exhibits V1-scale whole-live-set latency spikes;
- `gc_pages` is proportional to victim live data rather than the entire logical live set.

These are initial engineering thresholds, not promises.

## 6. Real swap-pressure test

After block-level validation, create a dedicated swapz partition and activate it with `swapzctl`.  Disable other swap temporarily only on a disposable/test system so attribution is clear.

Capture before/after:

```bash
cat /proc/swaps
vmstat 1
cat /sys/class/block/<backing-kname>/stat
sudo dmsetup status swapz0
```

Use a repeatable memory-pressure workload that exceeds RAM but remains below logical swap capacity.  Record total elapsed time, `pswpin/pswpout`, host sectors written, and `swapz` status counters.

## 7. Endurance interpretation

For SD/USB devices without health telemetry, use host sectors written plus segment-cycle distribution as the measurable proxy.  Do **not** claim the same percentage reduction in NAND P/E cycles: controller FTL write amplification is opaque.

Where SATA SMART exposes lifetime writes/host writes, record those counters across long runs as an additional validation point.