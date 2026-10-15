# Benchmark — V3 Lower-I/O Evidence Only

**Immutable naming policy (read before every prompt):** The project is `swapz`;
the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the
Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`.
**Never rename or version-suffix these public identities** (for example to
`swapz3`, `dm-swapz3`, or any other replacement). Enforce the same names
in production kernel C, Kbuild/DKMS, DM tables, test harnesses, benchmarks,
CI and documentation, before every agent change. Version numbers belong in
release metadata and source paths, not the project/module/target name. Keep
`SWZ3` as the distinct V3 on-disk format; the separate safe `swapz3ctl`
utility does not rename the project or module.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. This single public entry point runs native production-C/source/safety checks, W=1/W=2 builds, owned RAM-backed loaded correctness, and counterbalanced off/V3 throughput trials. It must report BLOCKED (nonzero) when noninteractive administrator permission or safe isolated devices are unavailable, never skip required loaded work while claiming a full PASS. **Do not create, publish, recommend, or document alternative test commands** (including additional Make goals, directly executed test scripts, one-off Python test invocations, and manually invoked loaded-device or benchmark helpers). Private implementation scripts/sub-Make targets and CI jobs may orchestrate individual stages internally, but are not supported operator interfaces; rootless-only CI success is explicitly partial.


**Mandatory task context:** [README.md](../README.md), [VISION.md](../VISION.md),
[coding_standards.md](coding_standards.md),
[testing_standards.md](testing_standards.md), [compile.md](compile.md),
and [benchmark.md](benchmark.md).

## Three-axis qualification specification

**Status: first bounded matrix implemented after alpha.22's capped-only
owner run.** The official `make test` now includes capped and uncapped
**mixed** QD32 trials, verified 4MiB packed-population sequential and
random READ timings, and replay-process CPU use. It does **not** yet
include independent write-only saturation, a 100MiB distinct working set,
attributed kernel worker CPU, cold-device cache behavior, or sustained
live GC. A correctness PASS must never imply those are qualified.
The full matrix still needs the owner's loaded run at the new source
commit; rootless CI cannot provide real device evidence.

### Quantities and endpoints

All rates use decimal MB/s (`bytes / seconds / 1,000,000`); distinguish
MiB/s device configuration. Measure successful 4KiB logical work, not
merely accepted/submitted pages or LZ4 attempt bytes. End timing only when
the declared work and required lower writes/flushes have drained; bracket
independent lower counters over exactly that interval. Keep prefill,
warmup and final out-of-band oracle work outside measurement and report
where verification work is timed.

| User outcome | Primary quantity | Required companion evidence |
|---|---|---|
| Swap-out speed | completed logical WRITE MB/s versus paired raw | lower WRITE MB/s, requests, WRITE tails, drain and CPU/GiB |
| Write reduction | `1 - candidate lower WRITE bytes / raw lower WRITE bytes` for identical completed work | requests saved, codec ratio, GC and lower READ traffic |
| Data-ready swap-in | actual seconds for a declared logical byte volume, plus useful READ MB/s | lower READ bytes/requests, p95/p99, decode/verification endpoint and CPU/GiB |

`codec_ratio = logical compressed-page input / accepted LZ4 payload` is
different from `write_efficiency = completed logical WRITE bytes / total
lower WRITE bytes`. The latter includes alignment, metadata, RAW and
GC. Smaller total bytes per identical workload and smaller MB/s output
per wall second are different claims when the candidate finishes sooner.
No RAM-backed result measures flash lifetime or internal NAND writes.

The current model uses a **shared READ+WRITE** null_blk byte budget:
`mbps=20` is 20MiB/s, approximately 20.97 decimal MB/s. The upstream
[Linux 7.0 null_blk implementation](https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/block/null_blk/main.c)
deducts each request's bytes from that budget before operation handling
and replenishes it on a 20ms timer. Verify the actual host configuration;
this is a synthetic throttle, not a physical device's latency model.
For a mixed stream, useful WRITE MB/s cannot consume the whole cap.

An optimistic bandwidth bound, before CPU/queue/latency limits, is:

```text
logical WRITE MB/s <= D / (r_write + a * r_read + g)
a       = logical READ bytes / logical WRITE bytes
r_write = foreground lower WRITE bytes / logical WRITE bytes
r_read  = foreground lower READ bytes / logical READ bytes
g       = GC lower READ+WRITE bytes / logical WRITE bytes
D       = shared lower READ+WRITE byte budget in MB/s
```

Do not count GC in both foreground fractions and `g`. This is a bound
under an assumed saturated byte budget, not a performance prediction.
An uncapped RAM backend can expose CPU, preparation, mapping, retention
or queue overhead even when compression helps the capped case.

### Experiment matrix behind the one official command

Compare bare raw, serialized LZ4 preparation and concurrent LZ4
preparation at the same code revision with immutable equal-work inputs,
separate owned RAM devices and counterbalanced order. The existing
"async" mode overlaps LZ4 preparation only; lower dm_io remains
synchronous and mappings/decode/GC remain serialized.

1. **Write-only saturation, capped and uncapped separately.** Use the same
   fixed logical volume and QD1/4/8/32. No offered-rate pacing in
   saturation mode: differing achieved throughput is the result, not a
   reason to reject the pair. Verify cap=0 on uncapped devices and the
   exact selected cap on both capped devices. Record useful and lower
   WRITE MB/s, upper latency, drain, CPU and actual byte-budget utilization.
2. **Mixed contention at matched load.** Use declared offered rates and
   independent readers/writers with disjoint and overlapping page sets.
   Apply the existing 5% achieved-load matching gate here, not to a peak
   throughput comparison. Preserve READ work and tails when judging WRITE
   improvements. Finite QD waves have a completion barrier and are a
   separate burst workload, not independently progressing readers.
3. **Read a real fixed volume populated by packed writes.** Write the
   measured dataset using concurrent target writes, drain and verify it,
   then time sequential and seeded random READ-only passes at QD1/4/8/32.
   The timer ends when the requested decoded data have been returned,
   with the same declared oracle policy for raw and candidate. Report
   first passes over distinct pages separately from warm/repeated reads;
   do not globally drop host caches or disguise repeated 4MiB reads as
   a 100MiB distinct working set. 100MiB means 25,600 4KiB pages;
   100 decimal MB needs its actual aligned byte count stated explicitly.
4. **Lifecycle cost.** Choose bounded live occupancy and overwrite/discard
   churn that demonstrates real live-record copying and reserve-role
   rotations, with separate GC deltas included in total lower traffic.
   Dead-segment reuse alone is not a live-GC trial. Include read tails
   during cleaning, failure/drain correctness and no hidden pending work.

Use primary nonzero measured ~2:1 pages, mixed payload sizes, near-cap
payloads and RAW controls. Keep exact-zero elision separate. Size the
owned logical/backing RAM geometry to the actual volume and GC gate;
never substitute physical or existing system swap. CPU wall counters
nest and can overlap; obtain real task CPU attribution rather than
summing `lz4_wall_ns`, commit and lower-I/O wait counters.

### Verdicts, materiality and result schema

Correctness execution and performance qualification have distinct
verdicts. Keep per-axis/per-regime outcomes, including
`CAPPED_THROUGHPUT_GAIN`, `UNCAPPED_THROUGHPUT_LOSS`,
`NO_SIGNIFICANT_ASYNC_GAIN`, `READ_AMPLIFICATION_REGRESSION`,
`INCONCLUSIVE`, `NOT_MEASURED` and `NOT_EXERCISED`. A capped gain
cannot overwrite an uncapped loss. No observed GC means NOT_EXERCISED.
Unknown latency/CPU values are null, never a fabricated zero.

For a confirmatory experiment predeclare the material gain and allowed
READ-p99, CPU/GiB, memory and lower-I/O regressions in its plan. A
starting proposal for owner review is **5% material throughput or
fixed-volume-time improvement**, with the interval for paired gains
excluding zero; this is not a universal release threshold or a newly
implemented runner rule. Use at least five counterbalanced pairs per
mode/regime, enough duration and READ samples, per-pair ratios and
spread/confidence method. More trials are required if the interval is
too wide. Tiny positive mean differences remain unestablished.

Derive every candidate/raw ratio from its own paired raw arm; do not
compare a mode's mean against raw runs belonging to another mode.
Label aggregation precisely: mean/median of trial p99 is not a pooled
p99; mean request counts may be fractional although each trial is
integer. Preserve each trial so summaries can be independently derived.

The sanitized report should retain exact tested/source/code SHAs, kernel
version, module version/SHA256/vermagic and identity-validation booleans;
regime, actual configuration, cap units/bytes-per-second/shared scope,
QD, pacing, actual operation counts/mix, working-set sizes, fixture
LZ4 histogram, immutable input and final-oracle digests; integer logical
and lower READ/WRITE bytes/requests, duration, latency sample counts and
method; interval GC/CPU/memory observations and drain/teardown verdicts.
Retain the existing source-identification and report-only Git history
semantics. Keep identifying host paths and raw private logs out of the
published artifact. Publishing status is independent of test outcomes.

### Why the current read result does not qualify packed swap-in

**Historical capped-only runner:** The earlier replay prefills pages
with sequential blocking writes. Timed mixed READs address slots512..767
while WRITEs overwrite0..255, so those READs are predominantly
singleton extents; the old 100MB time was only an extrapolation.
**New first-stage implementation:** Each arm also concurrently writes a
fresh 1024-page 4MiB logical image to encourage packed extents, drains
writes, and times byte-verified READ-only sequential and seeded-random
passes of exactly 4,194,304 bytes (QD32). A V3 packed-close counter must
rise during population. The sequential pass precedes the random pass:
they are not interchangeable cold-cache observations. This remains
RAM-only, not cold SSD/SD or a larger distinct working set.
The current compressed reader always fetches metadata block0, then
needed payload blocks, and has no extent cache. Cold medium packed
reads can therefore transfer more than the 4KiB raw page despite LZ4
compression. Future C work should address measured read reuse or
aggregation with authority/CRC/GC correctness, and qualify the actual
packed dataset before claiming faster decoded swap-in.

### Alpha.22 C change and qualification handoff

The finite QD-wave replay waits for every operation before its next
wave. Alpha.21's useful early packed commits can leave one/two retained
records waiting for a deadline while those completions hold up new work.
Alpha.22 tracks successful pack-ready history within the serialized
worker and, at a locked empty-queue boundary, drains a valid one/two
compressed-record tail immediately through the existing lower-success
publication path. It leaves initial unpaired retention and RAW/larger
tails alone. Ordinary empty fences conservatively end packed history.
`burst_tail_flushes` counts attempted tail closures, already represented
by primary `close_idle`; it does not measure saved bytes or elapsed time.

**VISION hypothesis:** reduce avoidable completion wait and improve useful
WRITE throughput/latency while retaining a measured lower-write saving.
A new arrival just after idle can lose a packing opportunity, so lower
bytes/requests and READ tails must still qualify. This is a focused
retained-path C change, not a demonstrated performance gain.

**Alpha.22 historical owner qualification:** commit
`63f6ed945044c2a133cdcb6a25282ce06b61157b` passed five stages
and four capped sessions. That evidence is valid but does not cover
the newly implemented uncapped or 4MiB read matrix. The new source
revision awaits fresh loaded device evidence; CI remains rootless only.
Earlier reports remain bound to their embedded tested commits.

## Concurrent LZ4 preparation versus lower I/O: measurement gate

Experimental `async_prepare=1` runs bounded LZ4 preparation concurrently
with the original serialized mapping/commit worker, which can still be
blocked on synchronous lower `dm_io`. The independent producer never
mutates V3 generation authority or completes a BIO. A 64-buffer
semaphore/mempool limits staging. This directly addresses the lack of
CPU/disk overlap in the previous design, not device throughput by itself.
`prep_lower_write_overlap_starts` counts compression attempts starting
while lower WRITEs are active; it is a concurrency diagnostic only.

**VISION hypothesis:** with a compressible logical stream, output
physical-byte fraction `r`, CPU prep ceiling `C`, and independent
lower write cap `D`, the optimistic overlapped logical write ceiling
is `min(C, D/r)`, before metadata/read/GC/queue overhead. At an
illustrative `D=20 MB/s` and `r=0.6`, this gives `33.3 MB/s`
if CPU and other costs permit. A simple unpaced RAM trial, even
with `prep_lower_write_overlap_starts>0`, does not establish this
result or physical flash endurance improvement.

Accept only repeated/counterbalanced same-HEAD tests with (a) loaded
byte-exact oracle, FUA/barriers/overwrite/GC/error and safe drain PASS;
(b) identical immutable logical trace and actual compression histogram;
(c) independently verified lower READ/WRITE bytes and requests, including
GC; (d) a controlled *verified* roughly 20 MB/s lower write cap with
identical device behavior for bare off, sync V3 and async V3;
(e) achieved useful logical MB/s, CPU/memory, swap-in p95/p99 and read
amplification. A measured upper throughput boost must be sustained
without a correctness or unacceptable read-tail cost. This is still
**NOT RUN** on a loaded kernel, and all V3 devices remain null_blk-only.

The owner-only QD32 benchmark also supports the exact opt-in suffix
`--lower-mbps 20` before optional `--async-prepare`. When selected,
it checks the null_blk per-device `mbps` configfs attribute, writes
20 **MiB/s** to **both** newly owned memory-backed devices while they
are powered off, verifies each configured rate both before and after
power-on, and refuses absent/mismatching attributes. Record achieved
lower bytes/elapsed wall time independently: the presence of a
configured cap is not evidence of saturation or a write-endurance win.
The full `make test` now invokes the two owned-RAM comparison variants
twice in counterbalanced order, after rootless and loaded integrity
checks. It never silently skips these loaded benchmarks. The private
`tools/test-loaded.sh` uses `sudo -n` only if already authorized,
or reports BLOCKED nonzero without a password prompt. CI invokes only
the rootless half. A successful pair verifies I/O correctness and emits
measurements; it does not assert a throughput improvement.

The owner-only benchmark supports `--async-prepare` as a suffix
to the explicitly authorized `--run-owned-ram-pair --profile medium
--retain-ms {1|2} --unpaced` experiment. It verifies the selected
`async_prepare` value from the **loaded** target status before replay,
and the opt-in asynchronous pair requires a positive observed count of
LZ4 preparations starting during lower WRITEs. This is overlap
evidence only, not proof of a real performance improvement.

## Automated evidence report and transparent per-axis verdicts

Every official `make test` run overwrites
`build/test_results.json.xz` atomically and prints a CTest-like
success/failure stage list plus a readable benchmark table. Raw stdout
JSON from fixture preparation, replay and lower-device status is
captured, validated and summarized, not dumped to the terminal. The
public report excludes exact device IDs, host swap paths, kernel module
load paths and user credentials. The optional Git sync publishes the latest sanitized copy as the
single root-level `test_results.json.xz` tracked on `main` (with earlier
versions visible in Git history). The JSON includes full exact
`tested_commit_sha`, `source_sha` and `code_commit_sha` so the
measured module source can be identified even when subsequent commits
only publish results. Report commits follow the tested commit, cannot
be mistaken for a run of the newly created commit, and contain no
host paths or raw diagnostic text. Ordinary noninteractive Git push
authorization is sufficient; failed publishing is separate from
loaded device or benchmark PASS/FAIL.

**Criterion 1, useful swap-out throughput:** use completed 4 KiB
logical swap WRITE bytes divided by measurement seconds, in decimal
MB/s, for each replay of the same exact fixture and trace. Report the
matching uncompressed `off`, synchronous V3 and async V3 and flag a
V3 gain only if the candidate beats its paired raw baseline in **both
repetitions**. Also report actual completed lower WRITE MB/s; distinguish
input useful throughput from output physical rate. A configured
20 MiB/s `null_blk` cap is not evidence that it was saturated.

**Criterion 2, I/O reduction and endurance proxy:** calculate
logical WRITE bytes / independently measured lower WRITE bytes and
the percentage fewer lower WRITE bytes and requests than the identical
raw replay. Include lower READ bytes and requests so a write saving
does not hide read amplification. Never equate fewer RAM-backed sectors
to measured SD/SSD lifetime or physical NAND writes. No compression
ratio based on the fixture alone can replace actual backing counters.

**Criterion 3, swap-in/READ cost:** report useful READ MB/s,
p95/p99 READ latency, and an **estimated** seconds to deliver 100 MB
using `100 / measured_read_MBps` under the *same mixed 25%-read
QD32* trial. Flag reduced swap-in p99 only if both candidate
repetitions beat their raw control. The previous 100 MB figure was only an estimate. The new stage times
actual 4MiB fixed-volume reads (not 100MB). Cold-cache/page-in cost,
kernel-worker CPU and full pressure tests remain separate.

**Counterbalancing / redundancy removal:** Run sync/async/async/sync
so temporal drift is balanced across policies, and alternate
`off-first`/`V3-first` within each of the two four-pair regimes. Generate a single
immutable 128-medium-page LZ4 fixture and deterministic 16,384-
operation plan per `make test`, verify its actual payload size, and
reuse it in each fresh, independently owned RAM-backed device pair.
Keep the separate loaded 128-page overwrite/flush/zero-page smoke
because it verifies semantics absent from the synthetic throughput
pilot. A PASS for bounded correctness never implies a performance win.
The reporter records incomplete, mixed and no-gain outcomes rather
than inflating them to a single positive benchmark verdict.

## Active comparison: uncompressed baseline versus V3

**No V2.2 benchmark arm, no V2.2 performance gate.** V2.2 has been
retired because it did not meet the user's compression expectations.
Retain old data only as archived diagnostic provenance.

| Arm | Actual loaded target |
|---|---|
| **off** | uncompressed direct 4096-byte I/O to newly **owned RAM-backed null_blk**; NOT `swapoff` or changing host swap |
| **V3** | V3 `swapz` target on an equivalent fresh, owned RAM-backed null_blk; experimental, not production-ready |

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
 
## Historical alpha-series measurements (retired command names)

The dated measurements below describe exact older source revisions.
Their former `make verify`, `make run`, `make deploy` and
`make bench-*` commands are **no longer supported** and must not be
run against current `main`. Their recorded PASS/FAIL/NOT RUN labels
remain version-scoped evidence, not authorization for privileged or
physical-device tests. Today the sole public testing/benchmark command
is `make test`; its loaded phase is limited to approved owned-RAM
`null_blk`. Always obtain the current version from
[`kernel/extent-v3/VERSION`](../kernel/extent-v3/VERSION).

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

## Actual measured MB/s: owner-loaded V3.0.0-alpha.13 (2026-10-14)

Owner-host original log: `Pasted text(20261014-174644).txt`, exact
source `6ec5eae5cb300a5a9fb35d7be0e866a6a5f7f52c`;
Linux `7.0.0-38-generic`; built V3 module SHA-256
`f4559cb4e0d067dea48e51ee42c881b2a43fff3680747e9177104a9875e60ee7`.
The distinct owned-RAM medium-pair sessions are
`build/benchmark/session.ZD1Podid/` (retain=0) and
`build/benchmark/session.lf9CkQnd/` (retain=2). The original
uncompressed arm, the retained arm, and the default-off arm each
completed 767 WRITE and 257 READ operations on a 4KiB page, with
the same immutable fixture, trace and full logical readback.
Independent sysfs backing read/write sector/request deltas and
ordinary RAM-only teardown were verified. Decimal units:
`MB/s = completed bytes / measured seconds / 1,000,000`.
These are **measurement-only** intervals, excluding prefill/warmup
and final-image readback.

| Source/load arm | Seconds | Logical WRITE input MB/s | Independent lower WRITE MB/s | Logical READ MB/s | Independent lower READ MB/s | Logical / lower WRITE bytes |
|---|---:|---:|---:|---:|---:|---:|
| Uncompressed, retain=2 session | 2.033645204 | 1.544828 | 1.544828 | 0.517628 | 0.517628 | 1.000x |
| V3 retain=0 | 2.033811723 | 1.544701 | 1.544701 | 0.517586 | 0.517586 | 1.000x |
| **V3 retain=2** | 2.035168464 | **1.543672** | **1.006305** | 0.517241 | 0.517241 | **1.534x** |

The retained arm's independent lower WRITE bytes were
**2,048,000**, compared with uncompressed **3,141,632**,
i.e. **34.81%** lower actual write bytes at matched input IOPS.
The retained arm recorded **17 packed-ready early closures**
(`close_pack_ready=17`), 1,168 deadline closures and no GC
on a *cumulative* target status including setup/warmup/oracle.
Sampled WRITE p99 retained V3 was **2.824ms**, versus
**0.962ms** for its uncompressed arm; the short trial cannot
establish reliable sustained p99. Device READ I/O was unchanged.

**Important qualification:** this is a FIXED OFFERED INPUT
experiment (~500 IOPS), **not** a disk-budget-saturated experiment.
The ratio 1.534x is a measured *logical bytes per backing WRITE
byte*, NOT a measured increase in maximum useful input MB/s.
RAM-backed `null_blk` does not impose a genuine physical disk
bandwidth limit. Achieving the user's desired "logical input MB/s
increases while disk write MB/s stays unchanged" requires safe,
explicitly bandwidth-limited RAM-only testing, saturation,
repeated matched trials, CPU/GC/read and latency qualification.
No physical disk is approved. Do not extrapolate to 153% of
physical disk throughput without that evidence.

The existing `io-replay.py` now reports `throughput_mbps`
per replay and per compared arm: logical WRITE, READ and combined
MB/s, independent lower WRITE, READ and combined MB/s, and
logical-write/lower-write byte efficiency. Rootless regular-file
replays mark independent disk bandwidth as **null**, not as
a fake device metric. Invalid elapsed time, count mismatches and
invalid lower-sector bytes fail closed. This is reporting and
qualification work, not a new kernel C optimization; active
alpha remains 3.0.0-alpha.13.

## Owner alpha.13 second exact-head paired MB/s replay (2026-10-14)

The owner ran at exact `0a443ca412516faf354ef30d26fdc373b7f9882a`
on Linux `7.0.0-38-generic`, module SHA-256
`f4559cb4e0d067dea48e51ee42c881b2a43fff3680747e9177104a9875e60ee7`.
Freshly owned RAM-backed `null_blk` sessions:
`build/benchmark/session.zMK2sNCZ/` for V3 `retain=0`,
`build/benchmark/session.eAzj51EF/` for `retain=2`.
Both showed matched ~503 achieved IOPS, identical
128-page medium fixture (2,073B LZ4 payloads),
unaltered immutable trace and full 1024-page byte-exact
oracle; independent lower sector/request deltas and
ordinary owned-resource teardown PASS.

| Arm | Logical WRITE MB/s | Lower WRITE MB/s | Lower WRITE requests | WRITE p99 (sample) |
|---|---:|---:|---:|---:|
| Off, retained session | 1.54464 | 1.54464 | 767 | 0.984ms |
| V3 retain=0 | 1.54473 | 1.54473 | 764 | 1.017ms |
| V3 retain=2 | **1.54350** | **1.00619** | **158** | **2.788ms** |

READ lower bytes/requests were unchanged: 1,052,672B
and 257 requests per measured arm. Retained candidate:
**34.81% less WRITE bytes** and **79.4% fewer WRITE requests**
on the synthetic QD8 paced 500 IOPS plan. Wider cumulative
V3 status included **1,185 windows**, of which **17** closed
at pack-ready and **1,168** at deadline; no GC occurred.
This did NOT saturate a backing disk bandwidth budget, does
NOT prove higher maximum input MB/s, and the 767 WRITE
samples do NOT qualify stable p99 or CPU cost.

## Alpha.14: seven-compressed-record early-commit trial — NOT RUN

Production C now considers an early commit at **seven**
accepted compressed records rather than eight. The existing
16KiB SWZ3 extent geometry accepts seven 2073B records plus
the real 128B metadata; an 8th record is not needed to
obtain 12KiB savings versus seven standalone 4KiB units.
This may reduce WRITE wait/p99 or hurt packing/reuse on
some workloads. Only an opt-in same-source loaded trial
can settle that trade-off. No alpha.14 loaded claim, no
physical-disk saturation result and no GC lifecycle result.

## Alpha.14 owner-loaded medium pilot — real MB/s, capped offered load (2026-10-14)

Owner source `89c32842546f953b46d0a1f2117036109f8222e4`,
module SHA256 `7cf9f3e92e84864633c6d2d662a28d74b12ac109dbf3883c9661085b6d4aa488`,
Linux `7.0.0-38-generic`. The default 128-page C smoke passed
full byte oracle, nine exact-zero write elisions, lower write
749568B/183 requests and lower read 2007040B/490 requests,
119/119 FUA closure and window-age conservation, unchanged
host swap identity and ordinary teardown.
Medium-pair evidence: `build/benchmark/session.MEhFyU5Z/`
(default-off) and `build/benchmark/session.BuIh5VUg/`
(retained). All 128 measured fixture pages had exactly 2073B
host-liblz4 payloads; read/write fixture/trace SHA, final 1024
logical page image and separately owned device identities
matched; achieved off/V3 ~503 IOPS and correct teardown.

| Measurement | Off (retained session) | V3 alpha.14 retain=2 |
|---|---:|---:|
| Completed logical WRITE MB/s | 1.54422 | **1.54359** |
| Independent lower WRITE MB/s | 1.54422 | **1.00625** |
| Lower WRITE bytes | 3,141,632 | **2,048,000** |
| Lower WRITE requests | 767 | **158** |
| Lower READ bytes/requests | 1,052,672 / 257 | 1,052,672 / 257 |
| Sampled WRITE p99 | 1.053 ms | 2.651 ms |

The overall medium control retain=0 also passed and moved
1.54479 logical WRITE MB/s -> 1.54479 lower WRITE MB/s.
The candidate achieved **34.81% write-byte savings** and
**79.4% fewer write requests** at fixed offer, not a
throughput ceiling. Wider cumulative V3 state included
`windows=1202`, `close_pack_ready=64` (vs alpha.13's
17 in a separate trial), `close_deadline=1138`,
`retained_read_bypasses=274`, and **0 GC victims**.
Do NOT attribute all timing differences to seven-page
early-close: the runs are not repeated counterbalanced
samples, and the 767-write p99 is not statistically
qualified sustained latency.

The 1.545 MB/s figure was *deliberately set* by 500 IOPS
times approximately 75% 4096B writes. It should not be
used to extrapolate maximum logical throughput or claim
that the physical device was saturated. The new separately
opt-in `make bench-pair-medium-unpaced` (QD32,
iops=0, 16384 measured operations) is now available but
**NOT RUN loaded**. Its `UNPACED_THROUGHPUT_MEASUREMENT_ONLY`
qualification preserves observed useful MB/s differences
rather than applying the paced 5% achieved-rate gate.
Physical drive saturation, steady-state GC and CPU cost
remain independent unfinished gates.

## Alpha.14 most recent owner-loaded paced evidence; alpha.15 throughput pending

Owner log source `a3c0a1aefda04c1ac0dfc63624fbb938d63ee381`,
Linux `7.0.0-38-generic`, module SHA-256
`7cf9f3e92e84864633c6d2d662a28d74b12ac109dbf3883c9661085b6d4aa488`.
Both default loaded 128-page full-byte-oracle and two
distinct 500-IOPS medium-payload pair runs passed with
unchanged host swap and ordinary owned null_blk teardown.
In the retained medium session
`build/benchmark/session.yPOaQcCd`, immutable off and V3
arms each executed **767 WRITEs and 257 READs**. The
uncompressed source completed **1.544721 logical WRITE
MB/s → 1.544721 lower WRITE MB/s**. V3 `retain_ms=2`
completed **1.543633 logical WRITE MB/s → 1.006280
lower WRITE MB/s**, with actual independently measured
lower WRITE bytes 2,048,000 / 158 requests (off 3,141,632
/ 767). Independently measured lower READ bytes/request
counts were unchanged at 1,052,672 / 257.
The byte-exact final 1024-page oracle passed.
Sampled WRITE p99 **2.696ms** retained versus
**1.120ms** off; `close_pack_ready=64`,
`close_deadline=1138`, `gc_victims=0` across broader
cumulative state. This demonstrates material lower
WRITE-byte/request savings under a *paced synthetic*
workload, not saturation or improved maximum throughput.

At new exact **alpha.15**, the production C hot path
avoids an unnecessary `hrtimer_cancel` for nonretained
singleton windows but leaves retained behavior alone.
**There is no alpha.15 loaded unpaced throughput result.**
Next qualified experiment: existing distinct opt-in
`make bench-pair-medium-unpaced` (16,384 operations,
QD32, rate unlimited) on *exclusively owned* RAM
null_blk, with full readback, independent lower-device
counters, GC, write/read p99 and ordinary safe teardown.
Neither null_blk nor the unpaced result imposes or
demonstrates a fixed saturated physical disk bandwidth.

## First owner-loaded unpaced input-to-backing throughput: alpha.15 (2026-10-14)

Owner exact source `75d96be0e6ec5a575811748038366d2e2d069ccf`,
Linux `7.0.0-38-generic`, module SHA-256
`df24ece353e7a51e144aed10bbff5eb9989e0651e149dbb99821f3ea184f9594`.
The default-loaded `make run` 128-page byte-exact smoke,
9 exact-zero elisions, lower WRITE 183/749,568B and
READ 490/2,007,040B, 119/119 FUA/age accounting,
unchanged existing system swap and clean owned RAM
teardown **PASS**.

The separate `make bench-pair-medium-unpaced` owner run:
`build/benchmark/session.F5KSovQL/`. It used 2 freshly
owned RAM-backed null_blk lower devices, identical
immutable fixture SHA-256
`c717dc1313d910bc75bf07f48c12008366860671e44d13e6738c5a56fa19e4a2`,
trace SHA-256
`28b30607d40136ce2c15642c33869ddf7d6a4e77f4d9988239ec4ec3227c6245`,
exact final 1024-page oracle SHA-256
`4c033b51c4ad7efaaf3252793525a2497996865d0a7d3036d73afe3ac785cfd6`.
Both arms completed 12,301 4KiB logical WRITEs,
4,083 READs; 1,024 warmup, 16,384 measured operations,
QD32 and unlimited requested IOPS. Byte-exact oracle,
independently verified owned lower bytes/requests and
ordinary teardown **PASS**.

| Measured metric | Bare owned lower | V3 alpha.15 retain_ms=2 |
|---|---:|---:|
| Seconds for same measured trace | 1.598607 | 2.026141 |
| Achieved IOPS | 10,248.923 | 8,086.307 |
| Logical WRITE input MB/s | **31.518** | **24.867** |
| Lower WRITE output MB/s | 31.518 | **14.792** |
| Lower WRITE bytes | 50,384,896 | **29,970,432** |
| Lower WRITE requests | 12,301 | **2,061** |
| Logical READ input MB/s | 10.462 | 8.254 |
| Lower READ output MB/s | 10.462 | 8.254 |
| Lower READ bytes / requests | 16,723,968 / 4,083 | 16,723,968 / 4,083 |
| Sampled WRITE p99 | 1.879ms | 2.333ms |
| Sampled READ p99 | 2.852ms | 2.736ms |

**Negative throughput result:** V3 completed 21.10%
fewer logical IOPS/MB/s despite reducing lower WRITE
bytes 40.52% and requests 83.25%. It handled the same
useful work in 26.74% longer time, with worse WRITE p99
and unchanged lower READ bytes/requests. Read MB/s was
lower merely because it took longer; no read efficiency
savings were shown. Cumulative target status (includes
prefill, warmup and final readback): `windows=3124`,
`retain_timer_arms=12228`, `close_deadline=1483`,
`close_pack_ready=1641`, `retained_read_bypasses=3675`,
`gc_victims=0`, `failed=0`.
The owner remained in the safe RAM/null_blk-only scope.
This is a single short synthetic independent-page replay;
CPU/memory, GC cycle and real physical-media constraints
are not qualified. In particular **no fixed backing
bandwidth was imposed**; this is not proof of a
saturated physical-device result.

**Alpha.16 optimization, NOT RUN loaded:** the real C
worker no longer calls `hrtimer_start()` when the
first-record deadline is already in the hrtimer queue.
The unchanged deadline and error/barrier/authority
semantics preserve previous safety contracts.
The new status counter `retain_timer_arm_skips`
allows measuring whether repeated timer restarts
actually disappear. An increase in logical WRITE
MB/s and reduction in write p99 are hypotheses,
not established outcomes. Run exactly the same
owner-loaded unpaced trace and report a negative
or neutral result without adjusting acceptance
criteria after seeing the data.

## Alpha.16 owner-loaded paced timer-rearm result and alpha.17 C hypothesis

At exact source `59acee3534fd46fbcaabb51a1f30a366098ed1fd`
on Linux `7.0.0-38-generic`, owner-loaded module SHA-256
`c3de8af49a0d1ba7961ee77df38e25bc6ee9bc9fc9275a0e908768b704cc205b`.
The isolated 128-page C byte-exact smoke passed the
183/749,568B lower WRITE and 490/2,007,040B lower READ
reconciliation, nine exact-zero write elisions, 119
FUA closures/age bins, and safe teardown. The owner also
ran the medium 500-IOPS control session
`build/benchmark/session.Zc39DHna/` and retained
candidate session `build/benchmark/session.RzrEnr5E/`.
Each used 767 logical 4KiB WRITEs and 257 READs,
identical liblz4 measured 2073B pages and immutable
trace, independent equal capacity owned RAM lower
devices, identical byte-exact 1024-page final image,
matched ~503 achieved IOPS and ordinary teardown.

| Paced QD8 arm | Logical WRITE MB/s | Lower WRITE MB/s | Lower WRITE requests | Sampled WRITE p99 |
|---|---:|---:|---:|---:|
| Uncompressed, retained trial | 1.54478 | 1.54478 | 767 | 1.104ms |
| V3 alpha.16 retain=0 | 1.54454 | 1.54454 | 761 | 1.062ms |
| V3 alpha.16 retain=2 | **1.54353** | **1.00621** | **158** | **2.688ms** |

Retained V3 moved 2,048,000 vs off 3,141,632 actual
lower WRITE bytes (**34.81% fewer**); physical READs
were identically 1,052,672B/257 requests per measured
arm, without GC. Wider cumulative V3 counters showed
`retain_timer_arms=1202`,
`retain_timer_arm_skips=844`,
`close_pack_ready=64`, `close_deadline=1138`,
`windows=1202`, `gc_victims=0`, `failed=0`.
This directly proves the guarded alpha.16 worker
**skipped** redundant timer operations, not that
useful throughput improved. No alpha.16 **unpaced**
QD32 run appears in the owner's uploaded log.

Alpha.17 changes the actual C write-window size-ordering
hot path: when all preaccepted records are valid,
non-RAW and **equal compressed length**, the proven
greedy permutation equals arrival order. The worker
uses a single linear index pass instead of repeated
O(n^2) size scans; unchanged mixed/RAW fallback and
same engine commit preserve physical byte, request
and completion semantics. It is a **performance
hypothesis only**. Benchmark alpha.17 on newly owned
RAM null_blk with the same unpaced 16,384-operation
QD32 fixture, independently measured lower
READ/WRITE counts/bytes, achieved useful input MB/s,
read/write p99, final oracle and safe teardown.
Retained alpha.15 unpaced reference: 24.867 useful
WRITE MB/s vs uncompressed 31.518 MB/s, with
40.52% fewer lower WRITE bytes. The previous
rate-500 alpha.16 result cannot establish higher
maximum input MB/s, and no physical disk bandwidth
ceiling or sustained GC qualification exists.

## Alpha.17 owner-loaded QD8 evidence; alpha.18 C phase diagnostics

The owner tested exact alpha.17
`90c0d5b9f2f668b50fc8ba1770860ff4611388fa`
on Linux `7.0.0-38-generic` with module SHA-256
`ae003b83a5e77f8f5888c9ab6477dace4efa91b88d5137603f5057d26e9b7efb`.
The owned 128-page V3 C smoke passed the byte-exact
oracle, 9 exact-zero elisions, independently matched
183/749,568B lower WRITEs and 490/2,007,040B lower
READs, and safe teardown. Paired medium fixtures
and immutable QD8/500-IOPS trace were successfully
replayed with distinct owned RAM null_blk lower devices.
The control evidence session was
`build/benchmark/session.Q4gUVDhs/`, and retained
evidence session was `build/benchmark/session.4gjrA14A/`.
Each arm performed exactly 767 WRITE and 257 READ
4KiB logical operations; 1024-page final readback
passed with stable existing host swaps and clean
owned-device teardown.

| QD8 500-IOPS metric | Uncompressed (retained session) | V3 alpha.17 retain=2 |
|---|---:|---:|
| Logical WRITE input MB/s | 1.544815 | **1.543393** |
| Independent lower WRITE MB/s | 1.544815 | **1.006123** |
| Independent lower WRITE bytes | 3,141,632 | **2,048,000** |
| Independent lower WRITE requests | 767 | **158** |
| Lower READ bytes/requests | 1,052,672 / 257 | 1,052,672 / 257 |
| Sampled WRITE p99 | 0.994ms | **2.742ms** |

This is **34.81% fewer actual backing WRITE bytes**
and 79.4% fewer WRITE requests under a *paced* load,
not higher maximum logical input throughput. Cumulative
status from setup/warmup/measurement/oracle recorded
`windows=1202`, `close_pack_ready=64`,
`close_deadline=1138`, `retain_timer_arms=1202`,
`retain_timer_arm_skips=836`, `gc_victims=0`
and no target failure. **The attached log did NOT
run alpha.17 unpaced QD32**, so whether its uniform
sort fast path improved on alpha.15's **24.867 MB/s**
retained logical WRITE rate (vs **31.518 MB/s** off)
is unknown. The QD8 WRITE p99 remains expensive
and is only a single 767-WRITE sample.

**Alpha.18 is a new production-C measurement hypothesis,
NOT a throughput result.** Kernel status reports cumulative
monotonic nanoseconds in existing synchronous code sections
`lz4_wall_ns` (LZ4 compression attempts),
`decode_wall_ns` (LZ4 reads),
`window_sort_wall_ns` (ordering),
`window_commit_wall_ns` (engine commit, including lower
I/O/publication), `lower_read_wall_ns` and
`lower_write_wall_ns` (synchronous dm_io), and
`gc_wall_ns` (GC relocations). Their intervals
**overlap** and include prefill, warmup and final
readback; they are **not kernel CPU utilization**
or per-benchmark rate measurements until appropriately
scoped counter deltas are collected. The changes
do not alter codec, layout, worker or completion policy.
Next run exact alpha.18 owner-loaded unpaced QD32
same-source control/V3 on distinct fresh RAM devices.
Preserve physical requests/bytes, write/read p95/p99,
full byte oracle and quarantine protections. No CPU,
GC/fault lifecycle or physical bandwidth ceiling has
been qualified.

## Alpha.18 first C phase-counter high-throughput replay (2026-10-14)

Owner-loaded exact `88197bf4479eeb66db6bf52301a3cbd3d4c6a6e7`,
kernel `7.0.0-38-generic`, module SHA256
`aee943cd3023027a790fcdb1152510ea60cfa76581f39e289f97ae614226b6ef`.
Owner-host rootless, W=1/W=2, default 128-page V3
C smoke PASS with 9 zero-page elisions and 490
lower READ/183 lower WRITE matched requests, full
readback, original host swap unchanged and safe
owned RAM teardown. Unpaced separate pair evidence:
`build/benchmark/session.28oQ0qoy/`. Two independently
owned RAM-backed null_blk devices, common immutable
medium 2073B actual LZ4 page fixture, common
16,384-operation QD32 zero-pacing trace, complete
byte-exact 1024-page final oracle, separate lower
I/O stats and ordinary teardown PASS.

| Exact unpaced metric | Uncompressed | Alpha.18 retained V3 |
|---|---:|---:|
| Measured seconds | 1.653304465 | 2.042863864 |
| Completed IOPS | 9,909.850 | 8,020.113 |
| Logical WRITE MB/s | **30.475268** | **24.663854** |
| Independent lower WRITE MB/s | 30.475268 | **14.672798** |
| Logical READ MB/s | 10.115480 | 8.186531 |
| Independent lower READ MB/s | 10.115480 | 8.186531 |
| Lower WRITE bytes | 50,384,896 | **29,974,528** |
| Lower WRITE requests | 12,301 | **2,062** |
| Lower READ bytes / requests | 16,723,968 / 4,083 | 16,723,968 / 4,083 |
| Sampled WRITE p99 | 2.023ms | **2.333ms** |
| Sampled READ p99 | 3.015ms | 2.726ms |

V3 saves **40.51% independent lower WRITE bytes**
and **83.24% requests**, but completes **19.07%
less useful logical throughput** than same-source
off and needs 23.56% longer to finish the identical
trace. Compared with the earlier alpha.15 trial,
V3 absolute logical WRITE input fell slightly
24.867 -> 24.664 MB/s (-0.8%); off also fell
31.518 -> 30.475 MB/s (-3.3%). The V3/off
ratio rose from 78.9% to 80.9%, a
**non-significant cross-run observation**, NOT a
verified improved peak throughput. No fixed
backing bandwidth constraint was imposed, and
all media were disposable RAM-backed null_blk.

Alpha.18 cumulative target-since-create diagnostic
wall-time counters: LZ4 **71.716ms**, decoder
8.940ms, window sorting **0.949ms**, engine
write commit **168.616ms**, synchronous lower
WRITE **69.721ms**, lower READ **57.315ms**,
GC **0ms**. They include prefill/warmup/readback
and are **overlapping**: engine commit covers
some lower WRITE time. They cannot be summed
or directly subtracted from the replay's 2.043s,
and they are not kernel CPU utilization.
Cumulative window status: 3,126 windows,
1,640 pack-ready, 1,486 deadline closes,
9,007 skipped timer arms, zero GC victims,
no target failures. These measurements
suggest scheduler/retention/host queueing
may matter more than the micro-cost of
sorting, but do not establish causal
attribution.

**Alpha.19 experiment, NOT RUN loaded**: the
production serialized C worker now handles
queued arrivals within its ORIGINAL 64-BIO
budget in the same worker invocation, while
still requeueing at budget exhaustion and
draining accepted BIOs after admission closes.
New `worker_inline_drains` reports how often
a workqueue handoff was skipped. Actual useful
MB/s gains, overhead and read/write p99
effects require fresh same-source RAM-only
unpaced replay and full oracle; no physical
storage or system swap is authorized.

## Alpha.19 owner unpaced: inline handoff optimization failed; alpha.20 rollback

At exact `841f5517798fb8ce12ae5699b0729dc15a69b36a`
(alpha.19), module SHA-256
`9ed69e810aa99df66598fd24e81fc42632e9f487db8b8a2cf0fa9d0b4b4c55a9`,
owner ran default `make run` and unpaced
`make bench-pair-medium-unpaced` on Linux
`7.0.0-38-generic`. Rootless and W=1/W=2 builds,
full byte-exact 128-page smoke and QD32 16,384-operation
paired replay passed. Session evidence:
`build/benchmark/session.HTYijeec/`.
The immutable medium fixture (128 pages each actually
LZ4-compressing to 2073B), trace and full 1024-page
final oracle matched. Off and V3 had separately
owned/verified disposable RAM-backed null_blk
lower devices. System swap remained unchanged,
and both devices were safely torn down.

| Unpaced measurement | Uncompressed off | V3 alpha.19 retain=2 |
|---|---:|---:|
| Same measured operation count | 16,384 | 16,384 |
| Completed IOPS | 10,564.904 | 7,690.293 |
| Logical WRITE MB/s | **32.489722** | **23.649572** |
| Independent lower WRITE MB/s | 32.489722 | **14.077081** |
| Logical READ MB/s | 10.784126 | 7.849866 |
| Lower WRITE bytes | 50,384,896 | **29,990,912** |
| Lower WRITE requests | 12,301 | **2,065** |
| Lower READ bytes / requests | 16,723,968 / 4,083 | 16,723,968 / 4,083 |
| Sampled WRITE p99 | 1.813ms | **2.594ms** |
| Sampled READ p99 | 2.681ms | **3.591ms** |

V3 still reduced lower WRITE bytes **40.48%**
and WRITE requests **83.21%**, but completed
**27.21% fewer logical IOPS and MB/s** than
its same-source off arm. Alpha.19's experimental
inline-worker path was exercised
(`worker_inline_drains=3153`,
`worker_requeues=0` cumulative),
and retained physical byte savings and the exact
oracle, yet its useful throughput was **not
better**: 23.650 MB/s versus separate alpha.18
24.664 MB/s. Simultaneously the off baseline
rose from 30.475 to 32.490 MB/s in separate runs.
Thus an apparent 4.1% V3 regression and 8.1
percentage-point larger normalized deficit
should not be treated as statistically proven
without counterbalanced repeated trials, but
the result warrants withdrawing the change.
There were no GC victims, CPU/memory profile,
sustained read p99 or physical-device bandwidth
ceiling. `null_blk` is RAM-only.

**Alpha.20 actual kernel C rollback on main:**
restore alpha.18's bounded worker handoff behavior;
remove `worker_inline_drains` helper/telemetry.
The previous FIFO, synchronous physical success
gate, flush/FUA ordering, GC rules and
presuspend-drain semantics are unchanged.
This is not itself a demonstrated throughput
increase. Loaded alpha.20 qualification remains
**NOT RUN**; require same-source QD32 off/V3
and, ideally, repeated alternated-arm trials
before claiming a restored or improved maximum
logical MB/s.

## Alpha.20 owner QD32 unpaced throughput recovers; 1ms duration candidate NOT RUN

Owner loaded exact `faf17bc2d3614cad56f1d027dda4d2acf6dc6e66`
(alpha.20), module SHA-256
`1f385ee3dc20f59d068a8105de190f1d5c5185d8b2c442bbfdeebde9204c7005`
on Linux `7.0.0-38-generic`. The default loaded
128-page C smoke, full final readback, independent
READ/WRITE sectors/requests, nine exact-zero elisions,
unchanged `/swapfile` and `/dev/sda1` swap identity
and ordinary teardown passed. A separate two-device
owner-controlled QD32 unpaced medium experiment
`build/benchmark/session.X2pkhys4/` passed: 128
measured 2073B LZ4 pages, same fixed fixture and
16,384-operation trace hashes and byte-identical
final 1024-page oracle. Both owned RAM lower devices
were safely torn down.

| Unpaced exact-run metric | Uncompressed | Alpha.20 retained 2ms |
|---|---:|---:|
| Achieved IOPS | 10,488.863 | **8,120.119** |
| Logical WRITE input MB/s | 32.255877 | **24.971397** |
| Independently observed lower WRITE MB/s | 32.255877 | **14.853728** |
| Logical READ MB/s | 10.706507 | **8.288612** |
| Actual lower WRITE bytes | 50,384,896 | **29,970,432** |
| Actual lower WRITE requests | 12,301 | **2,061** |
| Actual lower READ bytes/requests | 16,723,968 / 4,083 | 16,723,968 / 4,083 |
| Sampled WRITE p99 | 1.843ms | **2.340ms** |
| Sampled READ p99 | 2.786ms | 2.723ms |

The alpha.19 C inline-drain experiment had previously
measured only 23.650 V3 useful WRITE MB/s, while the
older alpha.18 run measured 24.664 MB/s and alpha.15
24.867 MB/s. Alpha.20 recovers to 24.971 MB/s,
**+5.59%** against alpha.19 as separate trials,
but its same-source useful throughput remains
**22.58% BELOW uncompressed**. Sample sizes and
cross-run workload timing are insufficient to
claim a stable absolute speedup. The alpha.20
V3 lower WRITE bytes saved **40.517%** and
requests **83.245%**; READ bytes/requests matched.
No GC, fault, physical bandwidth cap, or CPU
profile was exercised. Cumulative worker stats
record 3,171 workqueue requeues, 3,124 windows,
1,642 pack-ready and 1,482 deadline closures.
Some windows pay the configured 2ms retention
without ever obtaining 7 medium pages, so a
shorter but lower-density window is a plausible
throughput/IO trade-off **not yet measured**.

A new separate, explicitly privileged **same-source**
`make bench-pair-medium-unpaced-retain-1` probes
`retain_ms=1` while preserving all original
independent RAM-device/oracle/safety checks and
exact immutable workload. Compare it with the
unchanged `make bench-pair-medium-unpaced`
(`retain_ms=2`). This is NOT a new kernel C
optimization; it is a necessary knob qualification
before changing production retention policy.
The 1ms loaded result is **NOT RUN**. Faster
input MB/s alone is NOT acceptance if lower
WRITE bytes/requests, READ p99, GC, or correct
completion become unacceptable. Results on
RAM null_blk do not prove a fixed saturated
SD/SSD/HDD bandwidth effect.

## Alpha.21 smaller useful packed writes — unmeasured loaded hypothesis

The verified alpha.20 unpaced QD32 retained 2ms
owner run delivered **24.971397 MB/s useful logical
WRITEs -> 14.853728 MB/s independent lower
WRITEs**, while its own off arm achieved **32.255877
MB/s**. The V3 exact byte oracle and separately
owned RAM teardown passed, with 40.517% fewer
lower WRITE bytes and 83.245% fewer requests.
The target closed 1,642 windows on the
seven-record pack-ready predicate and 1,482
at deadline (cumulative). Its write p99 was
2.340ms versus off 1.843ms; GC was zero.

In **alpha.21 real kernel C**, an opted-in retained
window may commit *earlier* if exact header,
per-record descriptors and two accepted LZ4
payloads fit one 4KiB extent, or three accepted
payloads fit one 8KiB extent. Seven in 16KiB
remains admissible. For measured 2073B records,
two exceed 4KiB (4194B), while three fit 8KiB
(6283B). The three-page case saves 4096B over
three separate 4KiB writes, but can give up
density compared with a later seven-page
16KiB write. The policy does not bypass the
existing engine/lower-success/authority/FUA
publication path. A same-source loaded alpha.21
`make run` and `make bench-pair-medium-unpaced`
must qualify correctness, useful input MB/s,
independent lower WRITE and READ bytes/requests,
p95/p99, GC, and safe teardown. A speedup
with unacceptable extra lower I/O is NOT a
performance win. No loaded alpha.21 result.

## Retired V2.2 offline evidence — no qualified performance winner

The V2.2 rootless plateau analyzer, exact-latency V3 observation sidecar,
bundle-integrity checkers and virtual-device qualification checklist remain
historical **offline models**, not independent collector authentication,
physical drain, sustained throughput or a winner selection. See
historical offline benchmark-reporting findings in Git history for the
consolidated constraints and historical V2.2 reports retained in Git history
for original schemas and test provenance. No old V2.2 strategy or batch
winner is a prerequisite for the V3 same-input off/V3 benchmark.

## Normative lower-device geometry and I/O accounting (merged specification)

Do not conflate Linux swap **page size**, device **logical block size**,
device **physical block size**, preferred/minimum/optimal I/O size,
filesystem block/cluster, and opaque controller/media program/erase units.
V3 currently supports only `PAGE_SIZE=4096` with 4/8/16 KiB aligned SWZ3
extents, and admits test-owned `null_blk`. A real backing device whose
logical block size does not divide 4096 or exceeds 4096 is unsupported;
larger physical sectors, alignment offsets and preferred I/O may create
read/modify/write even when the host requests are logically aligned.

**512n** devices often have 512 B logical/physical sectors;
**512e** has 512 B logical but typically 4096 B physical (misaligned
sub-4KiB writes may trigger internal RMW); **4Kn** requires ordinary
4KiB-aligned I/O. A filesystem's 64KiB cluster is *not* a sector.
Swap partitions have no filesystem cluster; swap files require stable
supported extents and filesystem rules, and **are not a backing mode
implemented by this V3 target**.

Linux `/sys/block/<device>/stat` READ and WRITE sector fields are
always in **512-byte accounting sectors**, regardless of actual device
logical/physical block. For independent before/after deltas:

```text
lower_read_bytes  = delta_read_sectors  * 512
lower_write_bytes = delta_write_sectors * 512
read_4k_equiv     = delta_read_sectors  / 8
write_4k_equiv    = delta_write_sectors / 8
```

A single aligned 16KiB lower WRITE is **one host WRITE request**,
16KiB transferred, and *four normalized 4KiB equivalents*; it is not
four hardware commands or known NAND program operations. Keep completed
lower I/O **request counts and bytes** separately, plus attempted/failed
BIOs, merges, flush/FUA, DISCARD, GC reads/writes, queue occupancy,
achieved IOPS, CPU, RAM and read p95/p99. Errors, caches, controller
remapping and internal media RMW mean a software sector counter alone
does not attest true NAND wear, physical durability or closed drain.

Device-specific qualification must inventory `logical_block_size`,
`physical_block_size`, `minimum_io_size`, `optimal_io_size`,
`alignment_offset`, `max_sectors_kb`, queue depth, partition offset,
cache/write/FUA guarantees, DISCARD geometry and zone/rotational
properties. Compare the same byte-exact logical trace, LZ4-size histogram,
achieved work and lower read/write requests/bytes (including GC and
flush), then judge the read/WRITE/CPU/p99 Pareto tradeoff rather than
silently summing read and write savings. Actual HDD, SD/eMMC or SSD
validation needs independent, explicit owner approval; RAM-backed
`null_blk` alone cannot support endurance or production claims.

Sources: [Linux block accounting](https://www.kernel.org/doc/html/latest/block/stat.html),
[block queue ABI](https://www.kernel.org/doc/html/latest/admin-guide/abi-stable.html),
and [swap-file restrictions](https://man7.org/linux/man-pages/man8/swapon.8.html).

## Maintained offline request-size projection

`python3 -B tools/request-plateau.py` models the relationship between
fixed per-request latency, payload size and an assumed lower-link
bandwidth. Its request-size plateau and logical/physical ratio projections
are **hypothetical**, not observed READ/WRITE counts, actual GC or
performance, kernel drain, flash endurance or a qualifying V3 winner.
The old `bench/block-benchmark.sh` and the V2 loop, rotation and
write-batch regression scripts were retired rather than moved into
active V3 tools: they used legacy kernel interfaces and potentially
destructive privileged disk operations. The originals are preserved
in [Git history](https://github.com/k1moradi/swapz/tree/e69acd6525af9bc0567383bd4588d474d93404db).
Only the owner-authorized owned-RAM V3 comparison protocol supplies
loaded V3 evidence; no legacy script grants permission to touch physical
or unrelated storage.
