# swapz — experimental V3 Device Mapper compression

**V3.0.0-alpha.21 is experimental, not production-ready.**
The active `swapz3` kernel C implementation uses LZ4, raw fallback,
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
| `make test` | Run rootless production-C, source/fixture, safety and W=1/W=2 build checks; no sudo |

**Owner hold:** do not execute privileged install/uninstall or loaded testing
on the owner's host without separate authorization. Rootless `make test`
does **not** establish loaded correctness or device performance. Loaded
owned-RAM correctness and off/V3 trials are separately authorized operator
procedures. Missing matching kernel headers or failing rootless checks blocks
qualification; missing privilege or safe RAM-device ownership leaves the
loaded phase **BLOCKED**, not PASS. The retired V2 utility is not installed.
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

After a rootless `make test` pass, **separate explicit owner authorization**
is required for the owned-RAM-only QD32 comparison:
`sudo bash tools/benchmark-owned-pair.sh --run-owned-ram-pair --profile medium --retain-ms 2 --unpaced --async-prepare`.
The same command without `--async-prepare` is the same-source control.
Append `--lower-mbps 20` immediately before `--async-prepare` in the
candidate, and to the end of the control, to configure and verify **both**
owned null_blk lowers at 20 MiB/s before powering them on.
This is only a simulated lower-rate limit, not actual flash evidence.
The new `prep_lower_write_overlap_starts` status value measures LZ4
starts observed during a lower write; it is not a useful-MB/s win.
**Loaded async correctness, bounded-bandwidth performance and endurance:
NOT RUN.** Experimental null_blk-only admission remains enforced.

## Current work and documentation

The active [V3 roadmap](docs/ROADMAP.md) and [TODO](docs/TODO.md)
control engineering priorities. See [documentation governance](docs/DOCUMENTATION_GUIDELINES.md)
and [the curated docs index](docs/INDEX.md).
Keep root agent bootstraps in their existing paths and work on `main`;
never overwrite concurrent commits. Update the relevant engineering standard
with implementation changes in the same commit.

Dated reports, audits, review notes and obsolete evidence snapshots were
removed from the working tree. Their original content remains recoverable
from [the immutable pre-cleanup revision](https://github.com/k1moradi/swapz/tree/abbdbce277938f3678a640af93ef066394b44606).
The historical evidence does not qualify current V3 correctness or throughput.
The `docs/branch-consolidation-2026-10-13.json` manifest remains because
branch-pruning code reads its exact content.

## Complete tracked Markdown directory

Every remaining tracked Markdown file has a direct relative link here.
Descriptions and authoritative routing are in [docs/INDEX.md](docs/INDEX.md).

- [`.github/copilot-instructions.md`](.github/copilot-instructions.md)
- [`AGENTS.md`](AGENTS.md)
- [`CLAUDE.md`](CLAUDE.md)
- [`CODEX_VALIDATION.md`](CODEX_VALIDATION.md)
- [`README.md`](README.md)
- [`VISION.md`](VISION.md)
- [`agent.md`](agent.md)
- [`docs/DEVICE_GEOMETRY.md`](docs/DEVICE_GEOMETRY.md)
- [`docs/DOCUMENTATION_GUIDELINES.md`](docs/DOCUMENTATION_GUIDELINES.md)
- [`docs/INDEX.md`](docs/INDEX.md)
- [`docs/ROADMAP.md`](docs/ROADMAP.md)
- [`docs/TODO.md`](docs/TODO.md)
- [`docs/archive/README.md`](docs/archive/README.md)
- [`docs/archive/v2.1/TESTING.md`](docs/archive/v2.1/TESTING.md)
- [`docs/archive/v2.2/DESIGN.md`](docs/archive/v2.2/DESIGN.md)
- [`docs/archive/v2.2/ROADMAP.md`](docs/archive/v2.2/ROADMAP.md)
- [`docs/archive/v3/V3_GOALS.md`](docs/archive/v3/V3_GOALS.md)
- [`docs/benchmark.md`](docs/benchmark.md)
- [`docs/coding_standards.md`](docs/coding_standards.md)
- [`docs/compile.md`](docs/compile.md)
- [`docs/nbd-pidfd-owned-rootless.md`](docs/nbd-pidfd-owned-rootless.md)
- [`docs/pidfd-supervisor-design.md`](docs/pidfd-supervisor-design.md)
- [`docs/recall-control-bridge.md`](docs/recall-control-bridge.md)
- [`docs/recall-dd-allowlist.md`](docs/recall-dd-allowlist.md)
- [`docs/recall-denial-telemetry-offline.md`](docs/recall-denial-telemetry-offline.md)
- [`docs/recall-fixture-owner-and-drain-evidence.md`](docs/recall-fixture-owner-and-drain-evidence.md)
- [`docs/recall-io-drain.md`](docs/recall-io-drain.md)
- [`docs/recall-role-bridge.md`](docs/recall-role-bridge.md)
- [`docs/recall-role-process-rootless.md`](docs/recall-role-process-rootless.md)
- [`docs/testing_standards.md`](docs/testing_standards.md)
- [`docs/virtual-smoke.md`](docs/virtual-smoke.md)
- [`kernel/BESTFIT4_TESTING.md`](kernel/BESTFIT4_TESTING.md)
- [`kernel/extent-v3/LIVE_TEST_GATE.md`](kernel/extent-v3/LIVE_TEST_GATE.md)
- [`kernel/extent-v3/LOWER_WRITE_AGGREGATION.md`](kernel/extent-v3/LOWER_WRITE_AGGREGATION.md)
- [`kernel/extent-v3/LOWER_WRITE_FAULT_QUALIFICATION.md`](kernel/extent-v3/LOWER_WRITE_FAULT_QUALIFICATION.md)
- [`kernel/extent-v3/MIXED_LOWER_WRITE_AGGREGATION.md`](kernel/extent-v3/MIXED_LOWER_WRITE_AGGREGATION.md)
- [`kernel/extent-v3/ONLINE_IO_RETEST.md`](kernel/extent-v3/ONLINE_IO_RETEST.md)
- [`kernel/extent-v3/README.md`](kernel/extent-v3/README.md)
- [`tests/runtime/README.md`](tests/runtime/README.md)
- [`tests/suites/README.md`](tests/suites/README.md)
