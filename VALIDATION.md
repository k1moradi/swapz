# swapz validation status

Date: 2026-10-06

## V1 historical result

V1 is preserved on branch `v1` at commit:

```text
025edff9fbe1d402cf6eab294e3ce1627e49a1e9
```

It was validated on Ubuntu 26.04.1 with Linux 7.0.0-34-generic x86_64.

Passed V1 gates included the Linux 7.0 GCC W=1 build, userspace/model tests,
ASan/UBSan, flush handling, five 100,000-operation randomized block runs,
120-rotation mixed stress, 100 lifecycle cycles, DISCARD fallback, lower-I/O
error propagation, bounded real swap pressure, swapoff, and a second swapon.

## Why V1 stopped

V1 copied the complete live set whenever its append arena filled.

The validation benchmark showed that highly compressible QD8 traffic packed well,
but 50%-compressible and incompressible churn wrote about 2.86x the raw
lower-device bytes after compaction. A separate latency probe measured normal
writes around 0.90 ms and rotation-triggering writes around 1.03 seconds on the
same delayed test stack.

Those are allocator-architecture problems, so development moved to V2 instead of
trying to tune V1 into V1.1.

The test device was virtual and slower than the eventual physical-media target,
so its absolute throughput is not a physical-device claim.

## V2 current status

`main` now contains the V2 allocator:

- fixed 1 MiB append segments;
- per-physical-block live-record accounting;
- per-segment live-block counts;
- rotating FREE-segment allocation;
- at least 25% logical-size GC reserve plus two segments;
- lowest-live CLOSED-segment selection;
- bounded victim-local reverse scratch;
- one lower read per live victim source block;
- relocation of only mappings resident in the selected victim;
- source-container grouping during GC;
- foreground and GC scratch separation;
- existing LZ4 packed-container and raw fallback paths retained.

V2 has not yet completed the Linux 7.0.x runtime validation pass.

The next validation must cover build/model gates, segment-boundary regressions,
long randomized multi-GC correctness, DISCARD fallback, lower-I/O errors, real
swap pressure, and paired fixed-I/O raw/swapz benchmarks.

Raw and swapz benchmarks must submit the same logical byte count. The primary
endurance proxy remains actual lower-device sectors written.
