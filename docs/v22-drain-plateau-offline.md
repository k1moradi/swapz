# V2.2 offline lower-drain plateau evidence analyzer

This is a **source-only, read-only evaluator**, not a benchmark runner.
`tests/runtime/v22-drain-plateau-analyze.py` opens only a caller-supplied
JSON Lines file, validates one strictly defined observation per line, and
emits JSON. It never invokes fio, DM, NBD, swap or kernel sysfs operations.

## Why this was added

The current **live** `tests/runtime/streaming-benchmark.sh` computes
`drained_write_mib_s` using fio's **logical** `write.io_bytes` divided by
elapsed time (including an explicit flush). That is a useful end-to-end
logical completion timing but **not an independent lower-device drained-byte
measurement**. The script does collect `lower_write_sectors` deltas; however,
its final inline 97% frontier decision uses one run per point and assumes a
plateau whenever a point is within 97% of the maximum. That logic cannot
establish saturated physical drain, reproducibility, or a defensible p99.

This new analyzer requires **lower-device sector deltas** for its numerator.
It does not alter or execute the live benchmark script. The future authorized
collector still needs independent review to make these counters trustworthy:
isolate the backend, prove counter attribution, sample a valid drain window,
complete fsync and kernel I/O quiescence, and ensure no fixture prefill or
outside traffic contaminates the observation.

## JSON Lines observation schema

Exactly these keys are required for **every** observation (no extra fields):

| Key | Meaning |
| --- | --- |
| `schema` | Fixed `swapz-drain-observation-v1` |
| `evidence` | `synthetic`, `kernel` or `physical`; self-reported, not authenticated |
| `backend`, `profile` | Nonempty compact alphanumeric identifiers (also `._-`) |
| `strategy` | `immediate`, `opportunistic`, or `staged` |
| `batch_kib` | 4, 8, 16, 32, 64, 128, 256, 512 or 1024; `immediate` uses 4 only |
| `run_id` | Globally unique compact identifier, one per repetition |
| `source_revision` | Compact source identifier, never mix different code revisions |
| `clock` | Fixed `monotonic` |
| `duration_ns` | Strictly positive monotonic elapsed nanoseconds for the measured drain window |
| `lower_write_sectors_before`, `lower_write_sectors_after` | The independently observed *same lower device's* 512-byte sector counters before and after the window |
| `lower_write_ios_before`, `lower_write_ios_after` | Independent lower-device completed write request counters |
| `logical_write_bytes` | Positive fio logical workload bytes; **never** used for lower-drain throughput |
| `read_count` | At least 10,000 actual swap-in latency samples per run |
| `read_p99_ns` | Strictly positive p99 from those raw samples, in nanoseconds |
| `integrity_ok`, `quiescence_ok`, `flush_ok`, `all_reaped` | All must be literal JSON `true`; operator must justify each before calling the observation valid |
| `source_kind` | Fixed `lower-device-counters`, not fio upper-bandwidth |

All counters and durations are nonnegative JSON integers (never booleans),
monotonic intervals must be positive, and lower-device sector and write-I/O
counts must increase. Unexpected fields, duplicate JSON keys/IDs, bad status,
invalid types, insufficient reads, nonfinite numbers, blank rows, excessively
large inputs and contradictory provenance fail the entire input before
analysis.

Example invocation **on already collected observations only**:

```sh
python3 tests/runtime/v22-drain-plateau-analyze.py --observations /path/to/observations.jsonl
```

No fixture currently emits automatically valid production observations for
this schema. In particular, **do not relabel** the existing live script's
`drained_write_mib_s` as lower-device physical drain.

## Selection criteria

For each distinct `(evidence, backend, profile, strategy, source_revision)`
series, the analyzer:

1. Requires the complete nine-size sweep for batched strategies. Immediate
   mode's 4 KiB point is a baseline, **not** a saturation sweep.
2. Requires three or more independent observations **per** batch, each with
   10,000+ swap-in reads.
3. Derives each repeat's lower-drained MiB/s from
   `(after_sectors - before_sectors) * 512 / 2**20 / (duration_ns / 1e9)`.
4. Rejects a series with repeat-to-repeat drain range wider than 10% of
   the series point's median (noisy/incomparable evidence).
5. Requires **all three largest measured adjacent sizes**, 256, 512 and
   1024 KiB, to have median drained MiB/s within 97% of the maximum measured
   batch median. Otherwise returns `PLATEAU NOT REACHED`.
6. Finds each qualifying batch's **worst individual run's read p99** and
   permits a candidate only if that p99 is within 10% of the lowest such
   worst-run p99 on the plateau.
7. Chooses the smallest eligible batch and preserves the full point table
   with medians, min/max repeat drain, sample counts and worst-run p99.

There is no cross-backend, cross-profile, cross-strategy or cross-revision
pooling. Input tagged `synthetic` is explicitly classified
`SYNTHETIC ONLY - NOT BENCHMARK EVIDENCE`; it can demonstrate how the
algorithm behaves but can never produce a provisional performance
selection. A `kernel` or `physical` series may yield only
`PROVISIONAL - INDEPENDENT EVIDENCE REVIEW REQUIRED`, because any
JSON file can falsely *claim* provenance. The analyzer cannot authenticate
device counters, timing boundaries or the submitter's trustworthiness.

No confidence interval can be justified from only three repeats. The
median/min/max and 10%-spread check are a deliberately conservative first
gate, not a statistical guarantee. Before a final decision, inspect raw
read latency histograms, variability across different runs, workload
representativeness, completion semantics, independently observed I/O drain,
GC work and per-page correctness.

## CI and remaining work

`v22-drain-plateau-analyze-test.py` generates **only fabricated synthetic
observations**; it verifies success and refusal cases without opening
devices or creating worker processes. Both rootless workflows run it.

A future *separately authorized* collector must be reviewed and supplied
with exact disposable device identities; rootless CI results do not
authorize live benchmark operations. The final V2.2 strategy and batch
remain **UNDETERMINED**.
