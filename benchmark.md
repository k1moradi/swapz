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
`tests/runtime/benchmark/anon-page-fixture.py` and
`tests/runtime/benchmark/io-replay.py`, with
`tests/runtime/benchmark/io-replay-test.py` for rootless helper contracts.
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
 
## First confirmed isolated V3 loaded run: October 14, 2026

**CORRECTNESS PASS; PERFORMANCE ADVANTAGE NOT ESTABLISHED.**
User-supplied local `make run` log identifies **kernel
`7.0.0-38-generic`**, exact source **`68ac4c63c41adad911b0f788b38ae4f567087fd9`**,
and module SHA-256
`8d8379385c17ae5fabe67dd6ff58592021ded1906414ca446e1ab7b29719bb9f`.
The controlled owned RAM-backed null_blk was **64MiB**; its V3 DM
mapping was **16MiB**. The C test reported **PASS** for direct 4KiB I/O,
flushes, overwrite and full 128-page readback, followed by clean
teardown of the **new test mapping/device**, with active swap unchanged.
Original host evidence location:
`build/deploy/session.0HbwPYpr/session.log` (on the test host,
not incorporated into Git evidence).

The V3 target **after-test cumulative counters** were:

| Metric | Result |
|---|---:|
| Successful logical WRITE | 786432 B = 192 x 4096 B |
| Successful lower WRITE | **786432 B in 192 requests** |
| LZ4 attempts / accepted compressed / RAW fallback | 192 / 128 / 64 |
| Accepted LZ4 payload bytes (attempt-side) | 70266 B |
| Successful LZ4 size bins | 96 <=256 B; 32 in 2049..3072 B |
| Packed windows / one-record windows / records | **128 / 128 / 128** |
| Bulk lower I/O calls / GC rotations | 0 / 0 |
| V3 completed lower READ | 1843200 B / 450 requests |
| Successful verification reads (blocks) | 192 |
| Flush calls / successful flushes | 386 / 386 |
| Target failures / errors | 0 / 0 |

The independent **end-of-run** RAM lower device stat reported
**192 WRITEs / 1536 sectors = 786432 B** and **516 READs / 4128
sectors = 2113536 B**. It was not paired with a before-measurement
backing-stat snapshot, and the discrepancy between V3 target's
450 completed reads and device's 516 cumulative reads is **not yet
attributed**. Do not treat the full read count as a per-measured-phase
amplification figure without exact boundaries.

**Interpretation:** This small, favorable compressible-page correctness
run had **NO lower WRITE-byte saving against its own logical WRITE
volume**: the successful V3 lower WRITE bytes equaled the
uncompressed 192 x 4096B writes. The 128 compressed windows were
singletons, while the 64 RAW pages used their separate write path.
The average accepted LZ4 payload among the 128 accepted pages was
~549 B, yet writes still occupied 4096B lower blocks. **Important
workload qualification:** the C smoke oracle opens its DM test mapping
with `O_DIRECT | O_SYNC`, additionally calling `fsync` at phase
boundaries. Synchronous per-page completion and flush requirements
strongly limit legal cross-page batching; **128 singleton windows in
this smoke are not, by themselves, proof of an algorithmic packing
failure under asynchronous realistic swapping**. Separate sustained
non-`O_SYNC` matched-rate data also found a high singleton fraction;
that, rather than synchronous smoke alone, is the reason to investigate
the kernel-C worker/extent packing path. This is **not** a loaded
off-versus-V3 matched-rate performance verdict. It used
verification mode (`verify=1`), which incurs additional lower
READ work. It did not exercise GC rotations or true device fault
recovery. No performance/speed/endurance win is claimed.

**Remaining requirement:** run the real two-arm **off versus V3**
immutable-trace benchmark with paired lower-device snapshots, equal
achieved work and realistic ~2KiB compressed output controls. Record
kernel-worker CPU, read p99, and exact GC traffic before optimizing
`dm-target.c`/worker/extent layout. A separate older 64MiB quarantined RAM-backed configfs
device was **later verified and removed by the user** using exact
index/configuration and major:minor checks, empty holders,
no DM mappings, mount/swap/open-user checks and an ordinary
power-off/configfs removal. The active swap inventory remained
unchanged. It was **not** automatically removed by the successful
new V3 session, and no general force-cleanup permission follows.

## Kernel-C zero-page write elimination — candidate, not measured win

V3 now attempts to avoid a complete 4096B lower write when a source
page is **exactly all-zero**: the compressed result must first be
<=64B and a byte-exact full logical 4096B equality-to-zero scan must
succeed. The write worker must drain earlier writes, advance mapping
generation via the existing authority discard contract, honor
PREFLUSH/FUA and complete only after success. The `zero_elided`
INFO counter reports successfully acknowledged logical zero writes;
`lz4_attempts` remains an attempt-side metric. This can avoid a
4KiB lower WRITE **only for exact-zero logical writes**, while leaving
other compressible and RAW pages unchanged.

**Performance hypothesis (not yet validated on loaded hardware):**
for N qualifying zero page writes, up to N 4KiB allocated lower
write requests can be eliminated, subject to actual queued-work
interactions and verification mode. Do **not** equate the counter
with measured saved device requests. Confirm it with independent
pre/post null_blk lower-sector/request deltas for **identical off/V3
fixture and trace**. Include zero and 2:1 compressed controls
separately, plus RAW. This change does not solve singleton-window
packing of ~2048B nonzero data. A loaded owner-run `make run`
readback/flush check is a necessary correctness gate; the accepted
performance claim still requires a matched off/V3 measurement.
