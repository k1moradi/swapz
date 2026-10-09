# V2.2 streaming benchmark: safe single-sweep diagnostics

This document describes **source-only reporting changes**. No live Device
Mapper, NBD, loop, swap, fio/device benchmark, physical I/O or kernel module
operation was performed to qualify these changes.

## The fixed misleading claim

The previous `tests/runtime/streaming-benchmark.sh` called

`fio logical write bytes / elapsed time including flush`

`drained_write_mib_s`, then used its largest value to select a
`first_97pct` and `latency_guarded` **winner** from a single run for
each batch. Logical workload completion and a flush-inclusive timing are
useful information, but they cannot independently establish how many bytes
completed at the backing device or show a stable plateau, and the default
three-second workload cannot supply the required 10,000 read samples.

The benchmark script now records, in separate JSONL fields:

- `logical_flush_window_mib_s`: **logical** fio write bytes per
  monotonic elapsed second from a pre-workload timestamp through an
  explicit flush.
- `lower_counter_window_mib_s`: **lower-device counter-window** MiB/s,
  calculated as `(lower_write_sectors_delta * 512 / 1048576) / elapsed_s`
  from its already recorded `/sys/class/block/$BACKING_KNAME/stat`
  counters. This is *not independently attested physical drain*: the
  backing device might have other clients and flush completion does not
  establish all required kernel quiescence guarantees.
- `drain_window_s`: the positive `time.monotonic_ns()` elapsed interval
  containing the workload and flush, not wall-clock `date` time.
- `read_count`: the fio reader `total_ios` value, exposing inadequate
  sample counts instead of relying on an unqualified p99.
- Existing `lower_write_ios`, `lower_write_sectors`,
  `upper_write_mib_s`, `read_p99_ms` and other counters remain.

The misleading `drained_write_mib_s` field is no longer produced.
`streaming-benchmark-report.py` reads only the already generated JSONL
and cross-checks both rate numerators, positive monotonic interval, read
count, counters, status `failed=0`, strategy/batch identity and distinct
backend. Malformed, conflicting, duplicate, negative or nonfinite data
causes a nonzero report exit. The authorized live script therefore
preserves its diagnostics on an invalid report rather than printing PASS.

It prints per-strategy **single-sweep diagnostics**, and unconditionally
states **NO QUALIFIED WINNER** and **PLATEAU NOT REACHED**, even when all
rows are valid. It never invokes the optimizer and never chooses a
candidate from a one-run sweep.

## Offline regression

`tests/runtime/streaming-benchmark-report-test.py` works only on
fabricated fio data and temporary JSONL files. Besides direct reporter
negative tests, it extracts the actual inline Python formatter from
`streaming-benchmark.sh` and runs *only that parser* with fake fio JSON,
lower-sector snapshots and monotonic timestamps. It proves the two
throughput metrics cannot be confused, a counter regression fails closed
and the one-run script no longer computes `best_drain` or
`latency_guarded`.

`bash -n` checks syntax without sourcing or running the live script.
Both mandatory rootless workflows require these tests at one exact code
revision.

## What remains unqualified

These changes do **not** satisfy the separate collector provenance
contract defined in `v22-drain-plateau-offline.md`. That strict future
contract requires at least three independent runs at each of nine batch
sizes, 10,000 read samples per run, a stable 97% lower-throughput plateau,
worst-repeat read-p99 within 10% of the best eligible plateau point,
verifiable backend identity and exclusive counter attribution, plus an
independent kernel I/O-drain/teardown guarantee. No batch or V2.2 strategy
is yet established as the winner.

Only a separately operator-authorized, disposable virtual-device
benchmark may collect genuine new evidence. Physical-device benchmarking
requires its own explicit approval. Codex owns independently trusted GNU
`dd`, mapper lifecycle identity and drain/quiescence admission; the
changes here do not modify that work.
