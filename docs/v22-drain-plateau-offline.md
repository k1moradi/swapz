# V2.2 offline lower-drain plateau evidence analyzer

This is a **source-only, read-only evaluator**, not a benchmark runner.
`tests/runtime/v22-drain-plateau-analyze.py` opens only a caller-supplied
JSON Lines file, validates one strictly defined observation per line, and
emits JSON. It never invokes fio, DM, NBD, swap or kernel sysfs operations.

## Why this was added

The original **live** `tests/runtime/streaming-benchmark.sh` calculated
`drained_write_mib_s` using fio's **logical** `write.io_bytes` divided by
elapsed time including a flush. It also nominated a 97%-frontier "winner"
from only one observation per batch. Neither constituted a qualified
physical-device throughput plateau.

The source-only reporting fix now emits two **distinct diagnostics**:
`logical_flush_window_mib_s` (logical fio bytes divided by a monotonic
flush-inclusive elapsed interval) and `lower_counter_window_mib_s`
(the lower sysfs sector delta divided by that interval). Its separate
`streaming-benchmark-report.py` explicitly prints `NO QUALIFIED WINNER`
and `PLATEAU NOT REACHED`, never a one-shot optimizer verdict.
See [`streaming-benchmark-reporting.md`](streaming-benchmark-reporting.md).

This stricter analyzer requires **lower-device sector deltas** for its
numerator, plus independent repeats and sufficient raw read samples.
The future authorized collector still needs independent review to make
counters trustworthy: isolate the backend, prove counter attribution, sample
a valid drain window, complete fsync and kernel I/O quiescence, and ensure no
fixture prefill or outside traffic contaminates the observation.

## JSON Lines observation schema

The baseline `swapz-drain-observation-v1` format accepts a
**self-reported** `read_count` and `read_p99_ns`. It remains readable
for older synthetic fixtures and historical analysis, but its p99 was
never computed from latency observations by this parser. As of the
v2 safety gate, **v1 can no longer emit `provisional_selection_kib`**
even when its `evidence` field claims `kernel` or `physical`.
For v1 `kernel` or `physical` claims, both
`candidate_batch_kib` and `provisional_selection_kib` are null.
Only `synthetic` v1 records may display an illustrative algorithmic
candidate; it is never a measured winner.

Use `swapz-drain-observation-v2` for the new internal-consistency
check. It retains the v1 fields and adds **one strictly required**
`read_latency_counts` field: a JSON list of sorted
`[latency_ns, sample_count]` pairs, for example:

```json
"read_latency_counts": [[900000, 5000], [1000000, 7000]]
```

Each timestamp represents an **exact** counted latency value in
nanoseconds (not a bucket midpoint, estimated percentile, or bucket
upper limit). The list must contain 1–256 *strictly increasing*
positive latencies, each with a positive integral count; the
sum must exactly equal `read_count`, which must lie between 10,000
and 10,000,000 inclusive. Latencies may not exceed 10¹³ ns.
The parser independently computes nearest-rank p99: at count `N`,
find the sample at rank `ceil(0.99 × N)` in the expanded, ordered
count distribution. The supplied `read_p99_ns` must match exactly.
A false count or falsely low p99 is rejected.

**Practical constraint:** The 256-distinct-value limit is deliberate
and conservative for a bounded 2 MiB JSONL input. Real workloads may
produce thousands of distinct raw nanosecond values and therefore
**cannot be represented exactly** in this initial v2 schema.
Do not silently round, truncate or discard reads to make them fit.
A future independently reviewed collector can use a separately
specified conservative histogram/upper-bound format when real data
requires more bins. Neither v1 nor v2 itself authenticates the
collector, proves a sample happened, or independently establishes
true kernel I/O drain.

Exactly these common keys are required for **every** observation
(no extra fields other than the one v2 addition):

| Key | Meaning |
| --- | --- |
| `schema` | Fixed `swapz-drain-observation-v1` (legacy) or `swapz-drain-observation-v2` (bounded exact-p99 check) |
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
| `read_count` | Claimed number of swap-in latency samples, minimum 10,000 and maximum 10,000,000; recomputed against v2 counts |
| `read_p99_ns` | Positive claimed read p99 in nanoseconds; exact nearest-rank recomputation is required only for v2 |
| `read_latency_counts` *(v2 only)* | 1–256 strictly increasing `[exact_latency_ns, count]` pairs with counts summing to `read_count` |
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
this schema. In particular, **do not relabel** the new live script's
`lower_counter_window_mib_s` as independently verified physical drain or
convert its one-run diagnostics into repeated observations.

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
pooling **and no mixing of the v1 and v2 p99-integrity
schemas**. Input tagged `synthetic` is explicitly classified
`SYNTHETIC ONLY - NOT BENCHMARK EVIDENCE`; it can demonstrate how the
algorithm behaves but can never produce a provisional performance
selection. A `kernel` or `physical` **v1** series is explicitly
`UNVERIFIED P99 - EXACT LATENCY DISTRIBUTION REQUIRED` and cannot
produce a provisional selection. For **v2**, a fully matching,
internally consistent `kernel` or `physical` series may yield only
`PROVISIONAL - INDEPENDENT EVIDENCE REVIEW REQUIRED`. Any JSON file
can falsely *claim* provenance or fabricate the histogram. Recomputed
p99 proves arithmetic consistency, **not the existence, independence
or representativeness** of 10,000 swap-in reads. The analyzer cannot
authenticate device counters, timing boundaries, the sample origin
or the submitter's trustworthiness.

No confidence interval can be justified from only three repeats. The
median/min/max and 10%-spread check are a deliberately conservative first
gate, not a statistical guarantee. Before a final decision, inspect raw
read latency histograms, variability across different runs, workload
representativeness, completion semantics, independently observed I/O drain,
GC work and per-page correctness.

## CI and remaining work

`v22-drain-plateau-analyze-test.py` generates **only fabricated synthetic
observations**; it verifies v1 provisional-selection denial,
v2 nearest-rank p99 recomputation, a false sample count, malformed
and duplicate latency bins, overlarge counters, schema separation,
and refusal paths without opening devices or creating worker
processes. Both rootless workflows run it.

A future *separately authorized* collector must be reviewed and supplied
with exact disposable device identities; rootless CI results do not
authorize live benchmark operations. The final V2.2 strategy and batch
remain **UNDETERMINED**.
