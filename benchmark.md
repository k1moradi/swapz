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

Owner-loaded **bounded two-arm off/V3 pilots have passed**, including
the alpha.11 medium retained candidate; alpha.12 is NOT RUN.
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

## First isolated Stage 2 two-arm pilot: bounded, not yet loaded

A separate `make bench-pair` opt-in prepares **two** unique 64MiB
memory-backed null_blk devices with 4096B blocks: one bare
uncompressed baseline and another with a 4MiB V3 DM target
(verification/fault injection off, bounded window 64). The shared
synthetic 128-page fixture and immutable trace cover 1024 logical
pages, QD=8, 25% reads, 256 warmup and 1024 measured operations
at offered 500 IOPS. The same full readback oracle and per-device
stat deltas are required. No active host swap or physical storage is
altered; unexpected state is quarantined without forced removal.
`SWAPZ-TEST-<16hex>` is the freshly owned target UUID pattern, not a
generic `SWZ*` mapping. The source/opt-in checks are rootless only;
**actual loaded two-arm performance is NOT RUN** and GC, CPU, RAM,
repeated load and statistically reliable read p99 remain unresolved.

## First loaded off/V3 owner pilot, alpha.7 (2026-10-14)

**Measured PASS, limited to a short, synthetic, owned RAM null_blk pilot.**
Source `cebc8bd686cd1075313591c123910c302f9eee00`, host kernel
`7.0.0-38-generic`, module SHA-256
`42d64bb0cde4eec578f136c00aae129ca051fc0e6dbcc6c91807da4d969e015e`.
Host-local evidence: `build/benchmark/session.DV6KeUbd/session.log`,
`off.json`, `v3.json`, `pair.json`. Two separately owned RAM-backed
64MiB lowers (251:0 and 251:1), same immutable trace, achieved ~503 IOPS
for both arms (0.0514% mismatch), full 1024-page byte-exact SHA-256
readback and ordinary teardown with unchanged system swaps: PASS.

| Interval independent lower-device metric | Uncompressed off | V3 alpha.7 | V3 reduction |
|---|---:|---:|---:|
| WRITE bytes | 3,141,632 | 2,830,336 | 9.91% |
| WRITE requests | 767 | 691 | 9.91% |
| READ bytes | 1,052,672 | 987,136 | 6.23% |
| READ requests | 257 | 241 | 6.23% |

The measurement window contains 767 writes / 257 reads, offered
500 IOPS, QD8, 25% target reads. **Cumulative** V3 end status (which
also includes prefill/warmup) reports 1,802 windows, 1,788 singleton
windows (99.22%), 14 two-record windows, 159 zero elisions and
**zero GC victims**. Do not attribute cumulative counts to the
measurement interval alone. The synthetic profile includes very
small compressible pages; it does not prove sustained ~2KiB-page
packing, CPU efficiency, reliable read-tail latency or GC behavior.
A single 257-read p99 (off 1,680,486ns; V3 1,663,756ns) is
insufficient to establish a stable tail result; write p99 was
952,458ns off vs 1,076,038ns V3. Preserve this narrow positive
result alongside prior negative and unmatched experiments.

## Alpha.9 closure-cause diagnostic, NOT YET LOADED

Production `dm-target.c` now counts one primary reason per
**nonempty** actual window flush: full, duplicate logical WRITE,
exact-zero fence, FUA, isolated RAW fallback, same-page READ, unrelated
READ, DISCARD, PREFLUSH, worker quantum/idle, shutdown, unknown/other.
Sum of all `close_*` fields must equal cumulative `windows` in
a quiescent status sample. GC `-ENOSPC` encounters are separately
reported by `window_gc_pressure`: they may occur within a window
and are not a primary closure cause. The existing pre-admission
coalescing timer does **not** mean a cross-worker window deadline
exists; no fabricated `close_deadline` is emitted.
Alpha.9 is **instrumentation only**: no new buffered write ownership,
independent READ bypass, scheduling or medium format. Rootless
qualification and owner-loaded readback, closure conservation and
independent lower accounting are separate steps before 3B.

### Alpha.9 smoke telemetry acceptance check

An owned `make run` now fails if the 14 primary window closure
counter **deltas** do not sum to the actual `windows` delta
over its synchronous byte-exact test interval. `window_gc_pressure`
is reported separately and cannot mask missing close reasons.
The conservation gate is a diagnostic integrity check, not a
measurement of packing gains or improved device I/O.
No alpha.9 loaded-host PASS has yet been reported.

## Alpha.9 owner-loaded smoke — FAIL independent lower READ (2026-10-14)

**FAIL/BLOCKED:** exact source
`a7e5ad6994a71b07421f12cb6da66a04355c7362`;
kernel `7.0.0-38-generic`, module SHA-256
`3d5a4d2f4d365c5e272983d66c8e763f6f20e34a196015c326df68f417b2024e`.
Owner's host log: `build/deploy/session.TlILja3J/session.log`,
fresh owned RAM null_blk `nullb-swapz-652778d9e53e3fc2` (251:0).
Full readback, flush, 9 zero-page elisions, 183 physical writes /
749,568 bytes and unchanged original host swap with ordinary teardown
were observed, but the full acceptance gate **FAILED**.

| Interval lower metric | V3 completed | Independent backing |
|---|---:|---:|
| Writes | 183 / 749,568 B | 183 / 749,568 B |
| Reads | 431 / 1,765,376 B | **433 / 1,773,568 B** |
| Additional lower reads | — | **2 requests, 8,192 B** |
| Window closures | 119 actual | 119 FUA, all other causes zero |

The backing read sector difference was
`(3488-24)*512-1,765,376=8,192` B. Two external device probes
or a sequential target/stat snapshot race are plausible, but neither
is proven. The instrumented closure reasons conserve correctly in
the recorded status; the old script rejected lower READ accounting
before executing its independent reason-conservation assertion.

The harness now optionally waits for udev settle and takes **paired
unchanged full V3 status and backing stat snapshots** separated by
200ms, up to 12 bounded attempts, on both sides of the oracle.
Non-quiescent devices are BLOCKED; an independent READ mismatch is
still a **FAIL** with its exact unattributed byte/request differences,
not a whitelisted two-block tolerance. Closure conservation now runs
even when subsequent independent read reconciliation fails.
Rootless tests simulate changing target and lower counters and
truncated stat lines. **New loaded retest: NOT RUN.**
Quiescence over one sampled interval cannot prove that sporadic
unowned I/O did not occur during the oracle; persistent discrepancy
requires additional device-origin diagnosis.

## Alpha.9 owner-loaded quiescent smoke PASS — 2026-10-14

At exact source `f9b9ec88f0764e71e4181ca423e846a361fdc03f`,
Linux `7.0.0-38-generic`, module SHA-256
`3d5a4d2f4d365c5e272983d66c8e763f6f20e34a196015c326df68f417b2024e`,
the owner loaded newly owned RAM null_blk
`nullb-swapz-6387697bd4080ba1`, 251:0. Original local log:
`build/deploy/session.YYtOpRDN/session.log`.
Byte-exact C oracle, flush and overwrites, nine zero elisions,
host swap unchanged and safe ordinary teardown: PASS.
The independently measured lower write requests/bytes were
**183/749,568** on both V3 and null_blk; reads were
**490/2,007,040** on both, with before/after quiescent attempts
1 and 2. All **119** window closings were attributed to FUA and
`PASS_WINDOW_CLOSE_REASONS=windows:119 accounted:119 gc_pressure:0`.
This validates the observational closure gate, *not* aggregation
across FUA or a sustained medium-page benefit. The earlier
unexplained 8,192B excess did **not** recur; its origin remains
unknown, not retroactively explained.

## Alpha.10 first-admission-to-flush window age — NOT RUN loaded

The worker now measures the monotonic elapsed nanoseconds from the
first accepted compressed or staged RAW record to *entry* of the
matching nonempty window flush, before lower device I/O, FUA,
verification or GC. Three disjoint cumulative buckets (<=100us,
101..1000us, >1000us) must sum to the window count over an isolated
oracle interval; sum and maximum ns are diagnostic only.
The metric does **not** count total upper BIO latency, allocation or
device write completion time, and does not create a timer or defer
writes. Next go/no-go remains measuring medium nonzero LZ4 pages
and matched-load off/V3 device request/sector deltas. Alpha.10
loaded qualification: **NOT RUN**.

## Alpha.10 medium compressed-data pair — NOT RUN

A separate `make bench-pair-medium` opt-in uses the original bounded
off/V3 trace, two uniquely owned independent 64MiB RAM-backed null_blk
devices and the same entire readback oracle, but changes the fixture
to `--weights medium=100`. Each synthetic 4KiB page consists of
2,040 deterministic high-entropy bytes followed by 2,056 zero bytes,
yielding approximately **2,073 bytes** on locally measured liblz4.
On the actual host, the benchmark **must verify** all 128 medium
pages, all in the 2049..2200B accepted-compression range, no RAW,
and no exact zeros from the fixture's measured liblz4 manifest
before allowing any replay. Default fixtures are unchanged.

The experiment answers whether a known poor two-per-4KiB packing
case sees **actual** lower READ/WRITE byte/request savings, or
disproves that hypothesis under QD8 and the current conservative
worker. A negative result is valid and should precede Stage 3B.
This is a single short synthetic run, **NOT** representative sustained
Linux swap, CPU, GC, or statistically reliable cold-read p99.
At this commit: rootless qualification pending CI; loaded NOT RUN.

## Alpha.10 matched medium-loaded result — small win, no practical aggregation (2026-10-14)

The owner ran source `43be096ce03841ede4a72c9b7b1b28f8f98301a7`,
Linux `7.0.0-38-generic`, module SHA-256
`ee01e2a05c152df8382de4df44cf798d52ac4bf6b5bb85134fe517fcdc987235`
in an opt-in bounded, separately owned RAM `null_blk` pair. Raw
host-local session: `build/benchmark/session.10KnHOC9/session.log`
and `{off,v3,pair}.json`. All 128 nonzero synthetic pages were
**2,073B LZ4**, `raw_pages=0`; original immutable payload and
full 1024-page image oracle matched both arms, target and independent
lower devices were owned, and original active swap was unchanged.
Achieved off 503.4781 and V3 503.4901 IOPS (<0.003% mismatch).

| Independent lower interval | uncompressed off | V3 alpha.10 |
| --- | ---: | ---: |
| WRITE bytes / requests | 3,141,632 / 767 | 3,137,536 / 760 |
| READ bytes / requests | 1,052,672 / 257 | 1,052,672 / 257 |

V3 saved **4,096B (0.1304%)** and **7 WRITE requests (0.91%)**,
with *no lower READ savings*. Sampled cold-read p99 was
1,805,221ns off and 1,887,982ns V3; 257 READs are insufficient
to claim a reliable p99 delta. Cumulative V3 stats (including
prefill/warmup/postverify) showed `windows=1961`,
`one_page_windows=1948`, `close_idle=1957`, 4 unrelated-read
closures, no GC, and only 13 multirecord windows. 1,960
windows were <=100us open and one in 101..1000us;
`age_sum_ns=577,798`, `age_max_ns=102,958`.
Do not confuse those cumulative counts with the measurement interval.
**Result:** correctness+matched-load pilot PASS; sustained
performance/benefit gate still open. This is source-grounded
reason to test the opt-in Stage 3B retention, not proof it wins.

## Alpha.11 control vs retention candidate, separate owned-RAM sessions

A same-source two-command experiment is now ready **but NOT RUN
loaded**. Use the standard `make bench-pair-medium` as unretained
`retain_ms=0` control and the separate explicit
`make bench-pair-medium-retain` for the V3 `retain_ms=2`
candidate. Both sessions independently compare against bare
uncompressed RAM and retain immutable seed/fixture/trace hashes.
The exact V3 table and status must prove the intended policy:
`retain_ms=0` on control and `retain_ms=2` on candidate.
Do not compare runs if achieved IOPS differ by more than the
predeclared 5% tolerance or the input/source hashes differ.
Separate sessions are *not* a randomized order/crossover study.
Record READ p99/CPU/GC and full resource teardown independently
before any case for default activation; negative, blocking and
unmatched results are first-class evidence.

### Alpha.11 test status on current main

Core CI at source `e305d0ab` passed native/policy, exact-source C,
kernel compilation and one-revision policy. These are not runtime
fault/drain/timer tests. The new default-off target emits
`retain_ms`, `retain_passes`, `retain_timer_arms` and
`close_deadline` for the candidate; no source-derived lower-I/O win
is claimed. Before interpreting trial output, verify each session's
actual V3 `retain_ms`, full immutable input hashes, lower-sector
counters, achieved rates, complete oracle, status close conservation
and ordinary owned teardown. A measured **negative** candidate is
valid evidence, not a reason to hide or reset it.

### Alpha.11 loaded default-off correctness passed; full smoke failed inventory check

The owner ran `make run` at `b5d54fe9`: oracle readback,
all 119 FUA window reasons and open-age bins, 9 exact-zero
elisions, V3/null_blk lower writes 183/749,568B and reads
490/2,007,040B all matched. The command **FAILED** at its
final swap audit when the preexisting `/swapfile` Used fell
by 4KiB, 1,624→1,620KiB, despite unchanged swap device
identity/configuration. This is a test-harness false negative
for inventory stability, *not* proof of a new kernel bug.
`retain_ms=0` and the opt-in candidate remained NOT RUN.

Both owned harnesses now use a canonical configuration identity
rather than volatile swap usage, with genuine changes quarantined
before any removal. No tolerance was added to lower-device READ
or WRITE reconciliation. Corrected loaded retest NOT RUN.

## Owner-reported alpha.11 medium retention result; alpha.12 hypothesis

**Owner-loaded bounded correctness/matched-input PASS; sustained benefit
INCONCLUSIVE.** The supplied host logs identify exact source
`0a10cbfab1b154d2d7a351209adf22503f9d15ac`, Linux
`7.0.0-38-generic`, module SHA256
`f2f4cc0a92645960aa487728d061977d07a49d001b627bd0a2416c21c8893eca`.
Corrected smoke `build/deploy/session.ZQd7l7B2/session.log` passed
byte-exact I/O, lower reads 490/2,007,040B and writes 183/749,568B,
119 FUA closure/age checks, swap configuration audit and teardown.
These results are supplied by the owner, not independently reproduced.

Both medium sessions used 128 nonzero 2,073B LZ4 pages, QD8, offered
500 IOPS, 767 measured writes and 257 reads, no RAW/zero pages.
Fixture SHA256 was `c717dc1313d910bc75bf07f48c12008366860671e44d13e6738c5a56fa19e4a2`;
trace SHA256 was `bc76f8eccf227eb29ed11ac7393caacd5d586063f1902f78e3ce4034c3081aa3`.
Full 1024-page final oracle and original write-stream hashes matched.

| Measured interval | Off / retain=0 V3 | Off / retain=2 V3 |
| --- | ---: | ---: |
| Lower WRITE bytes | 3,141,632 / 3,141,632 | 3,141,632 / 2,293,760 |
| Lower WRITE requests | 767 / 762 | 767 / 252 |
| Lower READ bytes | 1,052,672 / 1,052,672 | 1,052,672 / 1,052,672 |
| Lower READ requests | 257 / 257 | 257 / 257 |
| Achieved useful IOPS | 503.470 / 503.264 | 503.485 / 503.459 |
| Sampled WRITE p99 | 0.994ms / 0.908ms | 1.081ms / 6.365ms |
| Sampled READ p99 | 1.554ms / 1.837ms | 1.688ms / 1.808ms |

Host-local session logs: `build/benchmark/session.fz9zUXyR/session.log`
(control), `build/benchmark/session.Cpcl4se5/session.log` (candidate).
Independent candidate write reduction was **26.99% bytes / 67.14%
requests**, with no measured READ savings and approximately sixfold
sampled WRITE p99 versus its own off arm. Cumulative candidate status
(including prefill/warmup/full verification) reported 199 unrelated-read
closures, 1,086 deadline closures and 4,812,940ns maximum open age.
Both pairs passed the 5% achieved-rate gate and ordinary owned teardown
with unchanged stable host swap configuration. No GC occurred; CPU,
repeated trials and reliable tails remain unqualified. Separate sessions
are not a counterbalanced scheduler comparison.

**Engineering lesson:** measured LZ4 compression is useful, but when
arriving writes remain queued behind the retention delayed-work timer,
expiry can drain the old singleton before those writes are prepared.
Alpha.11 also sampled expiry twice before unsigned budget subtraction,
allowing underflow at a crossed deadline.

**Alpha.12 production-C hypothesis:** immediate preparation, absolute
hrtimer wake and dependency-checked unrelated reads will increase useful
packing while reducing artificial scheduling wait. Compare retain=0 and
retain=2 at the same final source/input and matched achieved rate; report
READ/WRITE bytes, requests and tails independently. The candidate
combines these C changes, so this comparison cannot attribute their
individual contributions. Keep the default off. **Alpha.12 compilation,
native/source and loaded tests: NOT RUN by explicit owner instruction.**
Use the one-liner in [compile.md](compile.md); sustained CPU/GC/fault/drain
qualification remains follow-up before any default-policy change.

## Alpha.12 controlled loaded result and alpha.13 packing-ready hypothesis (2026-10-14)

Owner-loaded source `2a3c872b0ffcae8df28edc606d1540275038fb39`,
Linux `7.0.0-38-generic`, production module SHA-256
`c34087f31f2162dd224b57fd10f89a0b08560104a88228194173eb412266e547`.
The 128-page exact direct-I/O smoke passed with V3 and independent
lower matching **183 / 749,568B WRITEs**, **490 / 2,007,040B
READs**, 119/119 FUA closures and window-age bins, unchanged
system swap and ordinary teardown. Pilot sessions:
`build/benchmark/session.cE1Roejk` (medium control) and
`build/benchmark/session.zwE2wsHa` (medium retention candidate).
Both used 128 exactly **2,073B-LZ4 nonzero pages** with fixture
SHA-256 `c717dc1313d910bc75bf07f48c12008366860671e44d13e6738c5a56fa19e4a2`
and trace SHA-256 `bc76f8eccf227eb29ed11ac7393caacd5d586063f1902f78e3ce4034c3081aa3`.
All 1024 final logical pages verified byte-exact with matching hashes.
Separate independently owned RAM-backed null_blk devices and DM UUID
were verified. Achieved IOPS for each arm were ~503, within
the predeclared 5% tolerance.

| Independent measurement | Off control | V3 retain=0 | V3 retain=2 |
|---|---:|---:|---:|
| Lower WRITE bytes | 3,141,632 | 3,141,632 | **2,048,000** |
| Lower WRITE requests | 767 | 763 | **158** |
| Lower READ bytes | 1,052,672 | 1,052,672 | 1,052,672 |
| Lower READ requests | 257 | 257 | 257 |
| Sampled WRITE p99 | ~0.92–1.02ms | 0.999ms | **2.933ms** |

The retained candidate saved **34.8% lower WRITE bytes**, **79.4%
WRITE requests**, and **0% lower READ bytes/requests** against off.
Its sampled WRITE p99 was about **2.9 times** its own off baseline,
not an acceptable unconditional improvement. A p99 of 2.933ms means
about 99% of the 767 measured writes completed within that
threshold (roughly eight are in the slowest 1%); it is NOT
the maximum or a statistically stable long-run tail. No GC
occurred; CPU/RAM and sustained device behavior were not tested.
Across separate sources and sessions, do not claim significance
for small latency differences.

**Alpha.13 NOT RUN loaded:** when the first eight already
staged independent compressed records form a provably packed
16KiB+4KiB layout, a retained worker now commits immediately
rather than keeping those completed-in-memory upper BIOs waiting
for the remaining 2ms timer. The proof requires **the seven largest
payloads** plus exact SWZ3 metadata to fit 16KiB, so any length
reordering remains safe. RAW, limited read-budget, FUA and default
nonretained paths do not use it. This geometry proof is
not a lower-device measurement or a guarantee of improved p99.
Next qualification needs the default-off smoke and same-source
medium control+candidate, actual read/write IOPS and p95/p99,
independent lower bytes and requests, full readback, CPU, GC,
fault and suspend/drain follow-up. Preserve negative results.
