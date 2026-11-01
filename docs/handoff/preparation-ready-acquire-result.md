# Acquire READY after a lost RAW-selection compare/exchange

The ordered consumer initially acquires the preparation state. If that read
sees PREPARING, the producer can publish READY before the consumer attempts
its PREPARING-to-RAW compare/exchange. The failed operation then returns READY
without guaranteeing acquisition of the producer's payload, length, CRC,
encoding or per-page compression-cost metadata.

The [Linux atomic API ordering contract](https://docs.kernel.org/core-api/wrappers/atomic_t.html)
does not guarantee ordering on conditional RMW failure. The old native shim
used acquire failure ordering and therefore gave this path a stronger contract
than portable kernel code may rely on. No corruption was observed on the x86
qualification host; the issue is an API-level ordering gap, not a measured
hardware failure.

The fix adds an acquire reread only after the RAW-selection CAS loses.
The consumer still holds its prepared-page reference, so READY cannot recycle
before that read. Ordinary READY observations and successful RAW claims keep
their existing one-acquire path. There is no new wait, retry loop, reference,
worker, buffer, codec policy, extent geometry or lower-I/O depth.

The native test deterministically inserts release publication between the
initial PREPARING read and compare/exchange for both READY_COMPRESSED and
READY_RAW. It requires a READY acquire observation and checks that the ordinary
READY and RAW-win paths add no read. The shim now uses relaxed failed-CAS
ordering. The old production header compiles but fails this regression; the
fixed header passes, while a separately compiled relaxed-reread mutant fails.
The complete native program also passes 8192 threaded transfers and
AddressSanitizer/UndefinedBehaviorSanitizer. These checks do not constitute
an LKMM proof or establish a throughput improvement.

The clean-source owner run tests
[`3ef72d9f67d642e832e2f5420c283f6824969648`](https://github.com/k1moradi/swapz/commit/3ef72d9f67d642e832e2f5420c283f6824969648).
Its published report is
[`fd5ed47e398e9c112f82e8c0b83dbbefd9f4aa2b`](https://github.com/k1moradi/swapz/blob/fd5ed47e398e9c112f82e8c0b83dbbefd9f4aa2b/test_results.json).
It finishes in 2085.68 seconds (34 minutes 46 seconds), with **BLOCKED**
overall and exit status 2 from make. This source is not fully owner-qualified.

| Stage | Result | Seconds |
| --- | --- | ---: |
| Build/helpers | PASS | 2.856 |
| Native/rootless | PASS | 132.219 |
| Kernel W=1 | PASS | 15.363 |
| Kernel W=2 | PASS | 11.935 |
| Owned loaded matrix | BLOCKED at ID36 | 1881.009 |

Before ID36, the loaded log records passes for the delta64-positive control,
byte oracle, compound BIO, live GC/pressure, TRIM, suspend/drain, retained
WRITE/FLUSH faults, completion handoff, packed placement, RAW-read fanout,
all mixed/storage-envelope regimes, both read-coalescing comparisons and all
sustained-WRITE QDs. These partial passes do not override the overall gate;
loaded correctness is marked INCOMPLETE in the final report. The structured
report verifies required delta64 with second-LZ4 acceleration four, positive
compression EWMA and zero outstanding prepared-slot/submitter gauges in all
66 recorded WRITE arms.

The terminal failure is the **raw/uncompressed control's 280-second replay
timeout under resource pressure**, before the swapz arm runs. A read-only raw
process stack shows `__mem_cgroup_handle_over_high` through filemap fault and
page-cache charging. This identifies the observed delay in raw startup; it
neither demonstrates a swapz kernel stall nor qualifies swapz under pressure.
The fixture has 576 MiB ballast and eight CPU workers. No memory allowance,
pressure requirement or timeout was relaxed, and the failed observation was
not replaced or retried.

After the timeout diagnostic was preserved, cleanup was itself slow while the
pressure load remained active. The operator created only this owned fixture's
existing `pressure.stop` barrier. Normal teardown then completed; no mapper
was force-removed. The report remains BLOCKED, and the cleanup intervention
is recorded separately. Final checks find no DM targets or pressure/replay
workers. This is not an unattended-cleanup acceptance result.

For regression monitoring, the partial fast-model persistent-WRITE results
are shown below. They are not qualified history points or a controlled source
A/B. The last column compares each report's swapz/raw ratio with the prior
qualified source `bb665730` (report `48a1580f`).

| QD | Raw MB/s | Swapz MB/s | Versus raw | Normalized change vs prior |
| --- | ---: | ---: | ---: | ---: |
| 1 | 16.43 | 12.21 | -25.7% | -1.4% |
| 4 | 73.01 | 35.92 | -50.8% | -5.1% |
| 8 | 85.16 | 61.65 | -27.6% | -4.8% |
| 32 | 85.16 | 106.59 | +25.2% | -7.4% |

These declines are watchpoints, not causal regression estimates. Fast mixed
swapz service is essentially unchanged (27.36 to 27.30 MB/s), while the raw
controls accompanying async observations rise from 23.45 to 25.76 MB/s.
Using those matched raw observations gives a +6.0% current mean service gap,
compared with +16.7% previously; the reporter's all-control raw mean is a
different aggregation. Neither establishes a performance benefit from this
portable ordering repair. Slow mixed raw-normalized service changes +0.4%;
slow QD4 changes -5.1%, also descriptive. Low-QD fast and SATA/NVMe gaps
against raw remain unresolved.

The official history generator refreshed the five plots but correctly excluded
this BLOCKED report: seven this-host PASS reports and 74 points remain, latest
qualified source `bb665730`. No failed run is relabeled or added to the PASS
cohort. This round closes with the portable correctness fix delivered and its
full-qualification boundary explicit; pressure startup/cleanup remains an
independent test-harness investigation before a qualified promotion.

Private source identities, native/mutant/sanitizer logs, the full owner log,
immutable report copy, pressure diagnostics/intervention and machine-readable
regression audit are under
`build/optimization-round/preparation-ready-acquire/`. No new production knob,
preparation width, I/O depth, buffer or codec-policy change is introduced.
