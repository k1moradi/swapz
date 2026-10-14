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

## October 14, 2026 — user-loaded exact-zero result, same host

**LOADED CORRECTNESS PASS; measured write-side evidence on one small
synchronous arm.** The user ran `make run` at exact source
`4c6e29b848a7f3327c1637a7f8fd234b60b840e8` on kernel
`7.0.0-38-generic`, compiled module SHA-256
`42d64bb0cde4eec578f136c00aae129ca051fc0e6dbcc6c91807da4d969e015e`
and exercised a fresh uniquely owned 64 MiB memory-backed null_blk.
The 16 MiB V3 target completed all 128-page direct-I/O oracle reads,
192 writes/overwrites, required flushes, full readback and ordinary
test-owned cleanup. Active `/swapfile` and `/dev/sda1` swap inventories
were identical before and after. Host log:
`build/deploy/session.8K4HCM7d/session.log` (only on user host,
not a checked-in raw evidence artifact).

| Count or volume | V3 target | Independent owned lower |
|---|---:|---:|
| Completed useful logical WRITE | 192 x 4096 = **786,432 bytes** | not applicable |
| Completed physical WRITE | **183 requests, 749,568 bytes** | **183 requests, 1,464 x 512B = 749,568 bytes** |
| Exact-zero write elisions | **9** | supported by missing nine 4KiB writes |
| Accepted nonzero compressed pages / RAW fallbacks | **119 / 64** | payload classification not visible |
| LZ4 attempts / accepted payload bytes | 192 / 70,243 bytes | not a media-byte counter |
| Compressed windows / singleton windows | 119 / **119** | no multi-record packing |
| Completed lower READ | 431 requests / 1,765,376 bytes | **493 requests / 3,944 x 512B = 2,019,328 bytes**, cumulative |
| Flush calls / successful | 386 / 386 | no independent per-flush count established |
| GC rotations / target errors | 0 / 0 | no GC/fault qualification |

**Result scope:** Compared with the *same arm's ideal uncompressed
logical-write equivalent*, 9 x 4096 = **36,864 bytes (36 KiB)** and nine
4KiB lower writes were avoided, reducing completed lower-write bytes
by **4.6875%**. This is corroborated by independent `null_blk`
sector/request counters, not merely `zero_elided`. It is **NOT** a
controlled off-versus-V3 comparison, a representative anonymous-page
population, or a sustained performance win. Because the C oracle uses
`O_DIRECT | O_SYNC` and `fsync`, the 119 singleton nonzero windows
cannot alone diagnose asynchronous batching. Read device-vs-target
difference (**62 lower reads / 253,952 bytes**) is **unattributed**;
the independent device read total is cumulative rather than an
isolated measured-phase delta. Verification mode was enabled
(`verify=1`) and contributed lower reads.

**Next engineering gate:** a true identical off/V3 replay with
pre/post owned lower sysfs snapshots; representative measured LZ4
output-size distributions including nonzero ~2048B payloads;
separate CPU/p99, GC and read amplification. The isolated smoke
harness now checks its own 9 zero elisions against full readback,
target lower-written bytes, and actual owned lower write-sector
deltas; failure of this guard is **not** permission to alter active
swap or move to physical devices.

## Oracle-interval independent lower READ accounting gate

The isolated `make run` harness now snapshots the **same newly owned
null_blk** `/sys/block/<disk>/stat` before and after its byte-exact C
oracle, checking 512-byte **read** sector deltas against the V3 target's
`physical_read` delta, alongside the existing write-byte and nine-zero
checks. It also reports completed lower read/write **request counts** on
both sides, but does **not** require dm_io call counts to equal queue
requests because the block layer may split or merge submissions.

**Qualification at this source revision: NOT RUN on a loaded host.**
`make verify` checks source/shell contracts only. Earlier cumulative
lower-read excess (62 requests / 253,952 B at source `4c6e29b`) cannot
be attributed to oracle work without a before/after read snapshot;
other setup/device-probing reads may be included. A discrepancy in the
new oracle-interval read **bytes** fails the isolated test rather than
being silently labeled an I/O saving. The next owner-authorized
`make run` should record both deltas and investigation evidence if they
differ. This is still a synchronous verification-mode smoke, not the
required matched achieved-load off/V3 performance comparison.

## October 14, 2026 — owner-loaded independent READ/WRITE confirmation

**PASS: isolated smoke correctness and counter accounting. Stage 2
paired performance is NOT RUN.** User's `make run` log identifies
source `2e21fac5d93ea123044c1f4cb3e7e6862ee5d793`, kernel
`7.0.0-38-generic`, and `dm-swapz.ko` SHA-256
`42d64bb0cde4eec578f136c00aae129ca051fc0e6dbcc6c91807da4d969e015e`.
The owned 64MiB RAM-backed lower was
`nullb-swapz-ac383f3cb3ace2dc` (251:0) with UUID
`SWAPZ-TEST-ac383f3cb3ace2dc`; host-local evidence:
`build/deploy/session.AMFV8jds/session.log`.
Byte-exact 128-page C I/O, 192 logical writes, flush, overwrite,
9 zero elisions, and ordinary owned teardown passed. Active swap
inventory remained unchanged.

| Oracle-interval metric | V3 completed | Independent owned null_blk |
|---|---:|---:|
| Writes | 183 requests / 749,568 bytes | 183 requests / 1,464 sectors x 512 |
| Reads | 431 requests / 1,765,376 bytes | 434-3=431 requests / (3,472-24) sectors x 512 |

The earlier 62-extra-read cumulative observation was **outside**
this correctly bracketed oracle interval; the current PASS does
not establish its precise source. Verification mode and synchronous
`O_DIRECT|O_SYNC` prevent extrapolating to a sustained workload or
nonzero-page aggregation. The newly corrected benchmark replay's
modern/legacy configfs admission and post-open descriptor check are
rootless-only security prerequisites. The first **loaded,
same-fixture/same-trace uncompressed off versus V3** benchmark,
CPU/read-p99/GC/fault qualification and real-device benefits remain
unmeasured.

## First paired-replay qualification contract (rootless, not loaded)

The active off/V3 replay now accepts a V3 `dmsetup table` backing
token as either the pinned lower `major:minor` or the *exact*
`/dev/<owned disk>` path, and verifies the latter resolves to a block
node with the pinned `st_rdev`. It refuses multi-extent tables,
incorrect target geometry, unknown constructor settings and **any
nonzero flush/write fault-injection configuration**. The supported
kernel-C `STATUSTYPE_TABLE` contains eight numeric policy parameters
after the backing argument. This check does not authorize a non-null_blk
target or create devices.

The `compare` command still proves exact immutable logical input
and full readback first, but now separates `ROOTLESS_NOT_DEVICE_EVIDENCE`
from a loaded two-device result. A loaded comparison must supply two
distinct owned lowers, a common full source SHA, nonnegative independent
read/write request and byte deltas plus flush counts, and finite
positive achieved useful IOPS. A conservative **5% relative achieved
IOPS difference** is the current predeclared qualification threshold;
outside it the result is
`INCONCLUSIVE_UNMATCHED_ACHIEVED_LOAD`, not a performance verdict.
Within it, `MATCHED_LOAD_MEASUREMENT_ONLY` is still **not** a release
win: CPU, read p99, GC, repeated trials and actual loaded evidence
must still satisfy VISION. The new parser/comparison tests use no
privileged device. First actual loaded off/V3 comparison: **NOT RUN**.
