# swapz V2.1 — Physical Media Qualification Goal

## Role

You are the secondary validation and benchmarking agent for `swapz`.

The kernel/userspace implementation is frozen for this qualification unless a correctness
failure is found.

Your job is to:

- identify the explicitly authorized disposable device;
- record its real queue/capability properties;
- run controlled raw-versus-swapz physical benchmarks;
- measure actual lower-device I/O;
- exercise sustained GC;
- test real Linux swap pressure;
- report the evidence.

Do not commit, push, redesign, retune, or patch kernel code during this qualification.

The primary developer will review the physical evidence and decide whether another software
iteration is justified.

## Software baseline

Validated kernel/userspace revision:

```text
branch: v2.1
commit: c841a589a44ada3561a8bbed83a4db86e530ee1c
version: 0.2.1
```

Current `main` also contains the reusable runtime suite under:

```text
tests/runtime/
```

Before physical testing, build and rerun the fixed smoke/batching regressions from current
`main`, but ensure the kernel/userspace source under qualification matches the validated
V2.1 code.

Read:

```text
README.md
DESIGN.md
VALIDATION.md
docs/validation/v2.1-runtime-report.md
tests/runtime/README.md
```

## Hard physical-device authorization gate

Physical tests are destructive.

Codex must not choose a device by inference.

The operator must explicitly provide the exact test device/partition, preferably a stable
path such as:

```text
/dev/disk/by-id/...
/dev/disk/by-partuuid/...
```

Set:

```bash
export SWAPZ_TEST_DEVICE=/dev/disk/by-id/EXPLICITLY-AUTHORIZED-DEVICE
export SWAPZ_TEST_DEVICE_ACK=DESTROY_CONTENTS
```

If either variable is absent, stop with:

```text
NEEDS_DEVICE_AUTHORIZATION
```

and do not write any physical device.

Do not substitute another path.

## Mandatory safety inspection

Before any destructive write record:

```bash
readlink -f "$SWAPZ_TEST_DEVICE"
lsblk -o NAME,KNAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,ROTA,MODEL,SERIAL
lsblk -D
findmnt
cat /proc/swaps
udevadm info --query=property --name="$SWAPZ_TEST_DEVICE" 2>/dev/null || true
blockdev --getsize64 "$SWAPZ_TEST_DEVICE"
blockdev --getss "$SWAPZ_TEST_DEVICE"
blockdev --getpbsz "$SWAPZ_TEST_DEVICE"
```

Abort if the authorized device is:

- the root device or an ancestor/descendant of root;
- mounted;
- active swap;
- a boot/system partition;
- read-only;
- smaller than the intended test window;
- ambiguous relative to the operator's authorization.

Do not guess.

Record model/serial where available.

## Device feature detection

Do not assume capabilities from media type.

Record the actual queue:

```bash
KNAME=$(lsblk -nro KNAME "$SWAPZ_TEST_DEVICE" | head -1)
Q=/sys/class/block/$KNAME/queue

cat "$Q/logical_block_size"
cat "$Q/physical_block_size"
cat "$Q/minimum_io_size"
cat "$Q/optimal_io_size"
cat "$Q/rotational"
cat "$Q/nr_requests"
cat "$Q/read_ahead_kb"
cat "$Q/discard_granularity"
cat "$Q/discard_max_bytes"
cat "$Q/max_sectors_kb" 2>/dev/null || true
cat "$Q/max_hw_sectors_kb" 2>/dev/null || true
```

If DISCARD is unavailable, continue normally.

If SMART/NVMe/MMC/SD health telemetry is genuinely available, record it before testing. Do
not fail qualification merely because the device exposes no health counters.

## Bounded physical test window

Do not automatically consume the entire physical device for the first qualification.

Prefer a bounded test window on the explicitly authorized device.

Default:

```text
physical test window: 4 GiB
logical swapz target:  2 GiB
```

If the authorized device is smaller, reduce both proportionally while preserving V2.1's
capacity reserve.

Create the bounded window with a disposable Device Mapper linear target over the beginning
of the authorized device. Raw and swapz benchmarks must both use this exact same physical
window.

This deliberately limits test wear while retaining real controller/media behavior.

Report the exact sector range used.

## Phase 1 — Fresh software gate

Before touching physical media:

```bash
make -C kernel clean KDIR=/lib/modules/$(uname -r)/build
make -C kernel KDIR=/lib/modules/$(uname -r)/build W=1
make -C userspace clean
make -C userspace
make -C tests clean
make -C tests test
```

Run model ASan/UBSan if practical.

Then run disposable RAM/loop regressions:

```bash
sudo ./scripts/loop-smoke.sh
sudo ./scripts/rotation-regression.sh
sudo bash ./scripts/write-batch-regression.sh
```

Do not begin physical tests if these fail.

## Phase 2 — Measure raw physical characteristics

Before raw fio tests, capture lower-device `stat`.

Run non-swap raw tests on the bounded physical window.

Use fixed logical byte counts, not fixed duration.

At minimum measure:

```text
sequential write QD1
4 KiB random write QD1
4 KiB random write QD8
4 KiB random read QD1
```

Record:

- MiB/s;
- IOPS;
- average latency;
- p95/p99/max latency;
- CPU;
- completed lower reads/writes;
- lower sectors read/written.

This establishes whether the device is bandwidth-limited, command-latency-limited, or both.

## Phase 3 — Matched raw versus swapz short benchmark

Use the exact same physical window.

Logical swapz size:

```text
2 GiB by default
```

Short benchmark logical I/O volume:

```text
1 GiB per case
```

or a smaller volume only when required by device size.

Run identical fixed-seed workloads:

```text
100% compressible QD1
100% compressible QD8

50% compressible QD1
50% compressible QD8

0% compressible QD1
0% compressible QD8
```

For every case run raw first, then recreate swapz cleanly and run the identical workload.

Record actual lower-device statistics around each individual case.

For swapz also record:

```text
logical_write
physical_write
physical_write_reqs
multi_write_reqs
max_write_batch
compressed_payload
compressed_pages
raw_pages
gc_victims
gc_read
gc_write
segment_cycle_min
segment_cycle_max
failed
```

## Phase 4 — Sustained GC benchmark

Short tests may not invoke GC.

Use the same 4 GiB physical / 2 GiB logical test geometry.

Run one sustained 50%-compressible QD1 workload and one incompressible QD1 workload long
enough to force repeated victim cleaning.

Target:

```text
>= 20 GC victims
```

Use the smallest fixed logical I/O volume that reliably reaches that condition.

Record periodically and at completion:

```text
gc_victims
gc_pages
gc_read
gc_write
physical_write
physical_write_reqs
segment_cycle_min
segment_cycle_max
lower write I/Os
lower sectors written
```

Verify:

```text
failed=0
total lower bytes including GC do not exhibit runaway amplification
GC-triggering latency stays bounded
```

## Phase 5 — GC latency on physical media

Measure individual foreground write latency around:

```text
steady write
segment switch without GC
empty-victim GC
live-victim GC
```

Report average/p95/p99/max where sample counts permit.

Do not compare one-sample events as if they were stable percentiles.

## Phase 6 — Real Linux swap pressure on physical media

Only after block-level benchmarks pass.

Create swapz over the bounded physical window.

Run:

```text
mkswap
swapon --discard=pages if upper discard is supported
bounded memory pressure
swap-out
swap-in/readback
working-set churn
swapoff
second swapon/readback
```

If page discard cannot be enabled, run without it and record that fallback.

Monitor:

```bash
vmstat 1
cat /proc/vmstat
cat /proc/swaps
dmsetup status <target>
dmesg -w
```

Do not deliberately OOM the host.

## Phase 7 — Physical DISCARD behavior

If the actual device reports no lower DISCARD:

```text
PASS if swapz operates normally with lower_discard=off
```

If it reports DISCARD:

- verify swapz enables it;
- record discard byte counters;
- record whether device behavior/errors appear normal.

Do not force destructive vendor-specific trim operations outside swapz simply to prove the
feature exists.

## Phase 8 — Endurance evidence

Do not claim NAND wear reduction directly.

Report:

```text
logical bytes
actual lower host bytes
lower write-I/O count
GC bytes
segment-cycle spread
SMART/device host-write deltas if available
device health counters if available
```

For flash, state explicitly that the FTL controls physical NAND placement.

The intended evidence is reduced host writes plus broad sequential host-LBA reuse, not a
direct NAND erase-count claim.

## Performance targets

Use these as engineering goals, not pass/fail assumptions.

### Worst-case / incompressible

Primary QD1 floor:

```text
swapz >= 0.90x raw throughput
```

Stretch:

```text
swapz >= 0.95x raw
```

Lower bytes should remain close to raw rather than amplify substantially.

### Representative compressible workload

A useful physical success target:

```text
>= 1.5x raw logical throughput
and materially fewer lower bytes written
```

Strong target:

```text
>= 2x raw logical throughput
```

Excellent:

```text
3-4x raw logical throughput
```

### Highly compressible

Expect several-fold lower-device byte reduction if packing opportunities exist.

A strong throughput result is:

```text
>= 2x raw
```

A stretch target is:

```text
>= 4x raw
```

The ~8x packed-page ratio is an architectural upper bound, not a realistic required
throughput result.

## Required benchmark table

Return:

| Pattern | Path | QD | Logical MiB | MiB/s | IOPS | Avg ms | p95 | p99 | Max | CPU | Lower write I/Os | Lower write MiB | Lower read MiB | GC write MiB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

For swapz add:

```text
physical_write_reqs
multi_write_reqs
max_write_batch
compressed_payload
gc_victims
segment_cycle_min/max
```

## Required conclusions

Answer explicitly:

1. What are the device's real raw QD1/QD8 characteristics?
2. Is incompressible swapz within 90% of raw at QD1?
3. Does 50%-compressible traffic beat raw throughput?
4. Does highly compressible traffic achieve multiple-x logical throughput?
5. By how much are actual lower host bytes reduced?
6. Does physical write batching still form useful multi-block requests?
7. Is QD8 batching useful on this real controller?
8. Does GC preserve the write-reduction benefit over sustained churn?
9. What is the worst observed GC latency?
10. Does DISCARD work, fail, or remain unavailable?
11. Do real swap-out/swap-in and swapoff work correctly?
12. Are host writes distributed broadly across the bounded physical window?
13. What health/endurance telemetry, if any, changed during the test?

## Final status

Choose exactly one:

```text
BLOCKED — PHYSICAL CORRECTNESS FAILURE

PHYSICAL CORRECTNESS PASS, PERFORMANCE FAIL

PHYSICAL CORRECTNESS PASS, PERFORMANCE PROMISING — MORE ENDURANCE RUN NEEDED

V2.1 PHYSICAL PROOF-OF-CONCEPT SUCCESS
```

Use `V2.1 PHYSICAL PROOF-OF-CONCEPT SUCCESS` only if:

- block and real-swap correctness pass;
- incompressible QD1 is at least approximately 0.9x raw;
- a representative compressible workload materially reduces lower writes;
- sustained GC does not erase the write benefit;
- no serious tail-latency or kernel-safety problem appears.

Do not commit or push changes during qualification.
