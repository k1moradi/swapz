# swapz — experimental V3 Device Mapper compression

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


**V3 remains experimental, not production-ready.** The active release
version is read from [`kernel/extent-v3/VERSION`](kernel/extent-v3/VERSION),
the single source of truth for the kernel, DKMS, CLI, CI and test helpers.
The active `swapz` kernel C implementation uses LZ4, raw fallback,
and 4/8/16 KiB physical extents to reduce independently measured lower-device
I/O for byte-exact 4 KiB logical swap pages. It admits controlled RAM-backed
`null_blk` only; a build or installed DKMS package is not permission to
activate the module on real or existing system swap. Historical V2.2
implementation and performance comparisons are retired.

## Six authoritative documents

[README](README.md) · [VISION](VISION.md) ·
[Coding standards](docs/coding_standards.md) ·
[Testing standards](docs/testing_standards.md) ·
[Compilation](docs/compile.md) ·
[Benchmarking](docs/benchmark.md)

## One replace-in-place result; no raw JSON console flood

The single official `make test -j2` command prints short CTest-style
PASS / FAIL / BLOCKED phase verdicts and an aligned off / synchronous
swapz / asynchronous swapz performance table. Raw machine-readable
JSON and host swap inventories are **not printed** by this command.
It atomically replaces exactly one user-facing report file:
`build/test_results.json.xz`. The compressed report contains the exact
source revision and summarized correctness, benchmark, backing-I/O and
swap-in latency measurements, **not** device paths, filenames from the
host swap inventory, authentication material or complete raw logs.
Privileged per-session diagnostic evidence may still remain privately
under `build/deploy/` and `build/benchmark/` to support safe failures.

**Git-only publishing; no `gh` installation required.** After testing
completes (PASS, FAIL or BLOCKED), the runner tries to publish the same
sanitized file as the single
[latest tracked `test_results.json.xz`](https://github.com/k1moradi/swapz/blob/main/test_results.json.xz)
at the **repository root on GitHub**. This is an exception for one
published report, not an extra compilation directory. The local,
atomically replaced working report remains
`build/test_results.json.xz`. Ordinary Git SSH credentials with
**push** permission are sufficient. If `origin/main` changed, credentials
cannot push, or the tracked checkout is dirty, publication is visibly
SKIPPED/FAILED without hiding the actual test verdict. The runner never
forces a push or commits unrelated files.

Each JSON includes the full `tested_commit_sha` (the exact local Git HEAD
that ran), the existing `source_sha`, and `code_commit_sha` (the latest
commit changing project code/docs rather than a previous report). The
new report-only commit has the **tested HEAD as its parent**; it cannot
put its own not-yet-existing commit hash in the JSON. Git history retains
earlier reports even though the filename has no version or date. Each
report-only Git commit is marked to skip CI. The publication does not
move the local branch, index or working tree during testing; the next
normal fast-forward Git pull receives the report-only commit. Published
results can be reviewed in
[the report's Git history](https://github.com/k1moradi/swapz/commits/main/test_results.json.xz).
The tracked report is public: it contains only redacted measurements,
not host swap/device paths or credentials.

A PASS means the defined tests completed, **not** that asynchronous
preparation improves throughput or that real flash lifetime is proven.
The mandatory matrix now runs **eight owned-RAM mixed-load QD32 pairs**:
four at 10MiB/s with 1ms completion delay, and four at 80MiB/s
with 0.15ms delay. Each uses the same source, fixture and trace, with
ABBA sync/async and alternating raw/V3 order. The redundant 20MiB/s
bandwidth-only and uncapped RAM diagnostic regimes were removed from
the *mandatory* path; their source-bound measurements remain in Git
history. It shows (1) useful WRITE MB/s per storage model, (2) independently measured
lower WRITE byte/request savings, and (3) actual timed, verified
**4MiB** sequential and seeded-random reads *after* concurrently
populating compressed pages. This is not a 100MB cold SSD swap-in.
Each mode/regime has only two repetitions: performance differences are
**exploratory**, with a 5% materiality floor rather than treating a
0.05% async change as a gain. Replay-process CPU times are measured,
but kernel DM worker CPU, memory pressure, live GC and real SSD/SD
endurance remain unqualified.
**Owner-qualified read diagnosis:** `933ff984f8f603a3fa6d79dcde7a522d491e9502`
passed all five stages and eight pairs on RAM-only models (report
`18bf37313e4c`). Each fixed 4MiB packed read triggered 1,024 metadata
reads and about 632–640 additional payload reads; the SD-emulated
sequential trial took about 1.83s versus 0.40s raw. These are
successful lower-callback counts, not physical flash commands.

**Owner-qualified metadata reuse:** source `d2eac4a1697879a566e7ca22a6d66f19ffc1562e`
passed all five `make test` stages on the owner host (report-only
`3d2f2507bab9`). The SD model's verified 4MiB sequential read improved
from ~1.83s to ~1.24s, but random stayed ~1.84s with nearly zero
metadata-reuse hits. Packed reads remain slower than bare raw, and
the write-throughput loss persists.

**Owner-qualified two-block fetch:** `35fb224caba5bf61ab637181d963dadd9a94e6ef`
passed the full five-stage `make test` on the owner's RAM-only models
(report-only `0d9ec4017a5f`). SSD-model 4MiB reads reached ~0.19–0.20s
sequential and ~0.26s random, compared with ~0.23s/~0.27s raw, but
seeded-random lower READ traffic was ~8.1MiB for only 4MiB useful data.
SD-model random improved to ~1.16s but was still slower than ~0.40s raw.
The candidate continues to lose SD-model WRITE throughput.

**Owner-qualified read-offset selection:** `b848304aff321e738b5be50177143ba8797d7c32`
passed all five `make test` stages on the owner host at report-only
source HEAD `71f54532d9ab167d7f0842247c4609f1b6fd4951`; its
latest sanitized report is `b481256360f8`. Timed 4MiB random
READ transferred ~6.81MiB in the SD RAM model, down from ~8.11MiB
at `35fb224`, while time remained ~1.16s versus 0.40s raw.
SSD-model random remained ~0.26s and ~6.80MiB backing reads.
WRITE remained slower than raw (SD: 4.61/4.66 vs 7.85 MB/s).
The exact source and report-only Git commits must not be conflated.

**Next C diagnostic, NOT YET OWNER-LOADED:** classify each successfully
completed synchronous lower WRITE callback into <=1ms, 1–4ms and
>4ms wait buckets. The existing worker LZ4, window and lower-I/O
wall counters are sampled *only across the timed mixed workload*
and printed beside throughput. This isolates a potential
serialization/wait bottleneck before changing write scheduling.
Wall-time totals overlap and do not measure exclusive kernel CPU or
physical flash latency; no speedup is claimed for instrumentation.

## Current C performance work and qualification plan

The current experimental C revision drains an eligible one/two-page compressed tail
when an accepted burst has already completed a useful packed write and
the worker queue is empty. This removes an avoidable retention wait
that can hold up finite-QD issuers. Initial retention, actual lower-write
completion and mapping authority remain required. The new INFO field
`burst_tail_flushes` reports attempted tail closures, not measured gains.

**Alpha.22 was owner-qualified at exact source commit
`63f6ed945044c2a133cdcb6a25282ce06b61157b`:** all five stages
passed the previous *capped-only* matrix, but a general uncapped speed
improvement was not measured. The [three-axis specification](docs/benchmark.md#three-axis-qualification-specification)
now includes representative timer-delayed RAM-only comparisons,
alpha.22 lower-write/packed-tail diagnostic counters and verified
4MiB decoded READ trials. Buffers, worker pool creation, fixture setup
and warmup are outside timed I/O; the required final WRITE flush remains
included. Replay CPU excludes kernel workers. Independent write-only saturation, 100MiB
distinct-page SSD reads, kernel-worker CPU attribution, and sustained
live GC are still separate future qualification work.

## SD-card / existing swap partition safety boundary

**NOT READY for a real SD-card swap partition.** `make test` never
writes to physical storage or any active system swap; it verifies distinct
fresh RAM-backed `null_blk` ownership and safe teardown. The new models
simulate configured block completion delay and shared bandwidth, not
your SD card's firmware, wear leveling, erase blocks, cache, durability,
actual reclaim/page-fault latency, suspend/resume, failure and live-GC
behavior. Do not use `swapon`, `swapoff`, partition formatting or
`dmsetup` on an existing SD-card swap partition for this project.
Even if the partition is currently inactive, the experiment is not a
qualified data-safe physical-device deployment. Dedicated media testing
must be a separately designed, explicit destructive opt-in with verified
device identity and written rollback/recovery plan; no such public
operation has been authorized or implemented.

## Supported root Make interface

There are **exactly four supported root commands**. Do not add aliases
or invoke internal build targets directly as public goals.

| Command | Meaning |
|---|---|
| `make` | Build V3 without loading a module (parallel Make flags remain optional) |
| `make install` | Install version-owned V3 DKMS and safe helper without activation |
| `make uninstall` | Remove only that version-owned installation |
| `make test` | Run native/source tests, W=1/W=2, then loaded RAM-only correctness and paired latency-modeled RAM-only sync/async benchmarks; no interactive sudo |

**Parallel, incremental compilation:** `make test -j2` is the same
single official test command with two compilation jobs. The Device Mapper
kernel objects, test oracle and read-only userspace helper build as
independent Make prerequisites; unchanged userspace outputs are reused.
Kernel source is staged only when its bytes change, and normal,
`W=1`, and `W=2` builds keep separate cached outputs under
`build/kernel/{experimental,w1,w2}/`. Native production-C suites inherit
the Make jobserver. Loaded `null_blk` correctness and the eight
counterbalanced benchmark sessions **remain strictly sequential**.
Missing noninteractive privilege still yields BLOCKED, not a partial PASS.

**Owner hold:** do not execute privileged installation or unowned-device
testing. Full `make test` now executes rootless native/source checks,
W=1/W=2 kernel compilation, an actual newly owned RAM/null_blk module
readback smoke, then eight owned-RAM benchmark sessions (four in each of two synthetic regimes) in
sync/async/async/sync order. Each off/V3 comparison uses the same
immutable logical replay, reports measured lower bytes/requests, and
checks correct readback. The loaded phase requires root or previously
authorized `sudo -n` (noninteractive). Without it, the command exits
nonzero **BLOCKED**, never prompts or reports a false overall PASS.
No physical storage, active swap, swapon/swapoff or DKMS installation is
touched. CI runs a private rootless gate only; its green status is
**not** evidence of loaded throughput. The retired V2 utility is not installed.
All build products belong under the one reused `~/swapz/build/` root.

## Opt-in concurrent LZ4 preparation — candidate

The default V3 write path remains serialized. The experimental
`async_prepare=1` module parameter adds one bounded LZ4 producer
running on a separate workqueue. It can compress later accepted writes
while the existing ordered worker waits for an earlier lower WRITE.
The producer owns temporary buffers only and never publishes mappings,
issues lower I/O, or completes upper BIOs. A 64-buffer reserved mempool
and semaphore bound its resident compression staging; the ordered
consumer waits for each FIFO completion and preserves the original
SWZ3 authority, read/overwrite/flush/FUA, GC, and shutdown rules.
The on-disk format and the default `async_prepare=0` do not change.

The **only official way to execute** the controlled QD32 comparison is
`make test`. Its private harness runs same-source synchronous and
`async_prepare=1` loaded-device arms in counterbalanced order using a
verified 20 MiB/s rate limit on two independently owned RAM-backed
`null_blk` lower devices. There is no supported manual benchmark entry
point or separate privileged smoke-test command.
This is only a simulated lower-rate limit, not actual flash evidence.
The new `prep_lower_write_overlap_starts` status value measures LZ4
starts observed during a lower write; it is not a useful-MB/s win.
**Owner alpha.21 capped mixed trials passed bounded correctness and
showed write savings; current-revision testing is NOT RUN.** No
uncapped, actual fixed-volume swap-in, CPU, live-GC or physical-endurance
qualification is implied. Experimental null_blk-only admission remains enforced.

## Future physical-device gate (not currently authorized)

Testing on `/dev/sdb1` is a **future qualification milestone**, not
permission to touch it today. The current target remains restricted to
uniquely owned RAM-backed `null_blk`. Before any physical trial, the
owner must explicitly authorize the exact device and the proposed
destructive operations, and independent checks must confirm its stable
identity, inactive swap/mount state, unrelated storage isolation, safe
fallback/recovery plan, byte-exact data and flush/GC correctness and
ordinary error/teardown behavior. Past documents claiming approval do
**not** authorize present access. See
[the roadmap](docs/ROADMAP.md) and
[testing standards](docs/testing_standards.md).

## Current work and documentation

The active V3 milestones, outstanding tasks and experiment source constraints
are maintained together in [ROADMAP](docs/ROADMAP.md).
[Testing standards](docs/testing_standards.md) own safety, test oracles,
privileged loaded-test admission, recall and teardown qualifications;
[benchmark standards](docs/benchmark.md) define device geometry,
I/O-accounting and measured evidence. [Coding standards](docs/coding_standards.md)
control ownership, documentation policy and current C development;
[compile](docs/compile.md) owns build and packaging.

The `docs/` directory has only these five maintained Markdown files,
not a second TODO, status ledger, review worklog or JSON manifest.
Historical originals, including the one-time branch-consolidation JSON,
are recoverable from [the immutable pre-consolidation commit](https://github.com/k1moradi/swapz/tree/e09fcf3a8acea78355ee2a5ab1d7cd8a9017b517).
Only `main` remains; the one-time branch-pruning script and workflow
were retired along with the consumed manifest. None of the historical
results constitutes current V3 production approval.

## Maintained utilities

The shared, maintained helper programs live in [`tools/`](tools/),
alongside the owned-RAM V3 safety and benchmark scripts. The harmless
offline [`request-plateau.py`](tools/request-plateau.py) was moved out
of `bench/` unchanged. Four retired V2 scripts, including an arbitrary-
block-device destructive benchmark, were removed from the working tree
rather than exposed as active V3 tooling; Git history retains them.
The only public root Make commands remain the owner's four approved goals.

## Complete tracked Markdown directory

All remaining tracked Markdown files are directly linked here.
Component-local specs are subordinate to the six authoritative entry points.

- [`.github/copilot-instructions.md`](.github/copilot-instructions.md)
- [`AGENTS.md`](AGENTS.md)
- [`CLAUDE.md`](CLAUDE.md)
- [`CODEX_VALIDATION.md`](CODEX_VALIDATION.md)
- [`README.md`](README.md)
- [`VISION.md`](VISION.md)
- [`docs/ROADMAP.md`](docs/ROADMAP.md)
- [`docs/benchmark.md`](docs/benchmark.md)
- [`docs/coding_standards.md`](docs/coding_standards.md)
- [`docs/compile.md`](docs/compile.md)
- [`docs/testing_standards.md`](docs/testing_standards.md)
- [`kernel/BESTFIT4_TESTING.md`](kernel/BESTFIT4_TESTING.md)
- [`kernel/extent-v3/LIVE_TEST_GATE.md`](kernel/extent-v3/LIVE_TEST_GATE.md)
- [`kernel/extent-v3/LOWER_WRITE_AGGREGATION.md`](kernel/extent-v3/LOWER_WRITE_AGGREGATION.md)
- [`kernel/extent-v3/LOWER_WRITE_FAULT_QUALIFICATION.md`](kernel/extent-v3/LOWER_WRITE_FAULT_QUALIFICATION.md)
- [`kernel/extent-v3/MIXED_LOWER_WRITE_AGGREGATION.md`](kernel/extent-v3/MIXED_LOWER_WRITE_AGGREGATION.md)
- [`kernel/extent-v3/ONLINE_IO_RETEST.md`](kernel/extent-v3/ONLINE_IO_RETEST.md)
- [`kernel/extent-v3/README.md`](kernel/extent-v3/README.md)
- [`tests/runtime/README.md`](tests/runtime/README.md)
- [`tests/suites/README.md`](tests/suites/README.md)
