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


**V3.0.0-alpha.21 is experimental, not production-ready.**
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

## Supported root Make interface

There are **exactly four supported root commands**. Do not add aliases
or invoke internal build targets directly as public goals.

| Command | Meaning |
|---|---|
| `make -j2` | Parallel V3 build without loading a module |
| `make install` | Install version-owned V3 DKMS and safe helper without activation |
| `make uninstall` | Remove only that version-owned installation |
| `make test` | Run native/source tests, W=1/W=2, then loaded RAM-only correctness and paired 20 MiB/s sync/async benchmarks; no interactive sudo |

**Owner hold:** do not execute privileged installation or unowned-device
testing. Full `make test` now executes rootless native/source checks,
W=1/W=2 kernel compilation, an actual newly owned RAM/null_blk module
readback smoke, then four rate-limited owned-RAM benchmark sessions in
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
**Loaded async correctness, bounded-bandwidth performance and endurance:
NOT RUN.** Experimental null_blk-only admission remains enforced.

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
- [`agent.md`](agent.md)
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
