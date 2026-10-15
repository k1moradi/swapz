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
The matrix now runs **sixteen owned-RAM mixed-load QD32 pairs**:
four bandwidth-only controls (20MiB/s), four low-bandwidth/high-delay
RAM models (10MiB/s, 1ms per-request completion), four
higher-bandwidth/lower-delay RAM models (80MiB/s, 0.15ms), and four
uncapped-RAM **software-overhead diagnostics**. All share the same
source, fixture and logical trace. It shows
(1) separately labeled regime-specific useful WRITE MB/s, (2) independently measured
lower WRITE byte/request savings, and (3) actual timed, verified
**4MiB** sequential and seeded-random reads *after* concurrently
populating compressed pages. This is not a 100MB cold SSD swap-in.
Each mode/regime has only two repetitions: performance differences are
**exploratory**, with a 5% materiality floor rather than treating a
0.05% async change as a gain. Replay-process CPU times are measured,
but kernel DM worker CPU, memory pressure, live GC and real SSD/SD
endurance remain unqualified.

## Current C performance work and qualification plan

The next C revision drains an eligible one/two-page compressed tail
when an accepted burst has already completed a useful packed write and
the worker queue is empty. This removes an avoidable retention wait
that can hold up finite-QD issuers. Initial retention, actual lower-write
completion and mapping authority remain required. The new INFO field
`burst_tail_flushes` reports attempted tail closures, not measured gains.

**Alpha.22 was owner-qualified at exact source commit
`63f6ed945044c2a133cdcb6a25282ce06b61157b`:** all five stages
passed the previous *capped-only* matrix, but a general uncapped speed
improvement was not measured. The [three-axis specification](docs/benchmark.md#three-axis-qualification-specification)
is being extended inside the single official test command with a
second **uncapped mixed** regime, alpha.22 lower-write/packed-tail
diagnostic counters, verified 4MiB decoded READ trials, and clearly
scoped replay-process CPU. Independent write-only saturation, 100MiB
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
| `make test` | Run native/source tests, W=1/W=2, then loaded RAM-only correctness and paired capped, timer-delayed and uncapped-diagnostic sync/async benchmarks; no interactive sudo |

**Parallel, incremental compilation:** `make test -j2` is the same
single official test command with two compilation jobs. The Device Mapper
kernel objects, test oracle and read-only userspace helper build as
independent Make prerequisites; unchanged userspace outputs are reused.
Kernel source is staged only when its bytes change, and normal,
`W=1`, and `W=2` builds keep separate cached outputs under
`build/kernel/{experimental,w1,w2}/`. Native production-C suites inherit
the Make jobserver. Loaded `null_blk` correctness and the sixteen
counterbalanced benchmark sessions **remain strictly sequential**.
Missing noninteractive privilege still yields BLOCKED, not a partial PASS.

**Owner hold:** do not execute privileged installation or unowned-device
testing. Full `make test` now executes rootless native/source checks,
W=1/W=2 kernel compilation, an actual newly owned RAM/null_blk module
readback smoke, then sixteen owned-RAM benchmark sessions (four in each of four synthetic regimes) in
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
