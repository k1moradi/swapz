# Benchmark — V3 Lower-I/O Evidence Only

**Mandatory task context:** [README.md](README.md), [VISION.md](VISION.md),
[coding_standards.md](coding_standards.md),
[testing_standards.md](testing_standards.md), [compile.md](compile.md),
and [benchmark.md](benchmark.md).

## Active comparison: uncompressed baseline versus V3

**No V2.2 benchmark arm, no V2.2 performance gate.** V2.2 has been
retired because it did not meet the user's compression expectations.
Retain old data only as archived diagnostic provenance.

| Arm | Actual loaded target |
|---|---|
| **off** | uncompressed direct 4096-byte I/O to newly **owned RAM-backed null_blk**; NOT `swapoff` or changing host swap |
| **V3** | V3 `swapz3` target on an equivalent fresh, owned RAM-backed null_blk; experimental, not production-ready |

Use **ONE immutable fixture** and **ONE immutable ordered logical I/O
trace** for both arms. Require matching fixture SHA256, trace SHA256,
write-payload-stream SHA256 (every 4KiB payload, sequence and offset),
full initial image, read expectations and final byte-exact image
readback. Equal number of useful READs and WRITEs and matched
**achieved** IOPS are mandatory. Use
`tests/runtime/anon-page-fixture.py` and
`tests/runtime/io-replay.py`, with
`tests/runtime/io-replay-test.py` for rootless helper contracts.
The replay's wave barriers control dependencies but do not imply
identical microsecond-level arrival time or native Linux reclaim.

## Success is actual lower I/O, not just compression

Target **plausibly compressible anonymous memory**:
partially filled heap/stack, strings, dirty COW, structured buffers,
decoded rasters, zero/patterns, and moderate-entropy inputs. Include
a primary controlled ~**2:1 compression** test (a 4096B page
compressing to approximately 2048B using **actual LZ4**), plus
small/medium/near-3568B distributions and incompressible controls.
Do not infer file type from lower BIO contents. The synthetic profile
weights are hypotheses, not a statistically observed Linux
swap-page population.

V3 already tries LZ4 and stores full-page RAW fallback if output
does not fit **3568B**. This avoids storing expanded compressed data
but still costs CPU to attempt LZ4. A 2048B LZ4 payload may still
generate a full **4096B lower write** if the worker submits one-record
windows. Diagnose window geometry and published extents first;
do not add speculative entropy predictors or further Python frameworks.

## Per-trial mandatory measurements

For the **owned actual null_blk** lower device, take independent
`/sys/block/<device>/stat` snapshots around measurement only.
Lower read/write bytes = **512 × sector-count delta**, regardless of
device physical sector size. Record read and write **request counts**
separately and totals including foreground, GC, PREFLUSH/FUA,
discards and read amplification. Measure:

- Full oracle/CRC, fixture/trace/write-stream and module SHAs.
- Achieved useful IOPS and completed useful logical READ/WRITE ops.
- Real lower READ/WRITE bytes and requests per useful operation.
- Read/write p50/p95/p99, cold swap-in p99, kernel CPU and RAM.
- True size bins/RAW fallback, one-record windows, packing and padding.
- GC role rotations, live-copy lower traffic, errors and safe teardown.

Measure **matched achieved rate/volume** as the main benchmark and
saturation separately. Use QD1/4/8/32, 80/20, 70/30 and 50/50 mixes,
disjoint and overlapping read/write page regions, overwrite churn
and bounded GC. Repeat representative trials; include rejected
results, sample counts, 10s warmup/30s+ measured intervals where
feasible. Do not compare unmatched achieved work as a byte win.

### Main kernel problem to solve

In previous loaded V3 studies the write worker often submitted
**single-page windows** at matched load. With one page per window,
2:1 LZ4 alone cannot guarantee lower write-byte reduction because
extent allocation and minimum lower I/O units dominate. Prior
read-bypass experimentation also did not prove a matched-load win.
Develop the **production C worker/extent/GC path** to increase
real useful packed bytes per lower request without breaking
read-after-write, authority, FUA, suspend, GC or fail-closed
semantics. Prove improvements using **off versus V3**, not retired
version comparisons. Old PR #58/#60 reports are archival only.

## Safety and status

Only user-owned, verified **RAM-backed null_blk** devices may be used
for loaded V3 tests; current source rejects physical backing. Never
reboot, `swapon`, `swapoff`, touch active `/dev/sdb1`, `/swapfile`,
physical/unowned devices or global fault injection. Quarantine
uncertain holders instead of force teardown.

The new **two-arm loaded off-versus-V3 replay has NOT RUN**.
Rootless tests and kernel compile PASS do not prove lower-I/O savings.
Report missing kernel CPU or true device faults as UNMEASURED/BLOCKED.
Keep source, binary, trace, fixture and raw CSV/JSON evidence on
`main` with PASS/FAIL/BLOCKED, and update this standard in the
same commit as every new benchmark protocol or verified finding.
