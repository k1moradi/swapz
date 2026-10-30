# x86 dm-linear calibration and serial-budget diagnostic

This development screen connects the previously committed owned-pair linear
arm to `make fast_test` via `CALIBRATION=linear`. It creates only two new
positively owned RAM-backed null_blk devices per pair; the linear target is a
single zero-offset 4 MiB extent on its owned lower. It skips swapz-specific
packed-read and status gates. Default product qualification is unchanged.
Calibration writes `latest-calibration.json`, separately from ordinary trials.

The prospective plan and all nine pairs are in
[the calibration packet](dm-linear-x86-calibration.json). Three repeats per
SATA mixed, persistent NVMe5 mixed and NVMe5 waves alternate raw/linear order
A/B/A. Inputs, geometry, native replay, source hashes and exclusions are recorded.
All 18 arms passed byte-exact readback. Persistent NVMe5 is excluded without
replacement because raw-repeat spread was 21%. SATA's paired geometric WRITE
change is -3.45%, family interval -21.38..+18.56%; wave NVMe5 is -8.41%,
-26.71..+14.44%. Exact two-sided sign p values are 1 and 0.25 versus 0.05/3.
Neither establishes direction or equivalence. The 3% practical floor and fixed
three-sample screen cannot justify a universal DM cost or product promotion.

A subsequent unchanged-production-C diagnostic ran three persistent NVMe5
pairs; full READ/WRITE p95/p99, independent lower bytes/requests and CPU/RSS
context are in [the diagnostic packet](serial-budget-x86-diagnostic.json).
All six arms passed readback and the host/raw screen. Submitter preparation
claimed all 12,301 WRITEs per run; ordered/background LZ4 wall was zero.
Measured elapsed service was 42.82..43.33 ms for 16,384 mixed operations.
Ordered-owner wall was 2.05..2.08 us/mixed-op; submitter preparation wall was
1.97..1.99, including LZ4 1.47..1.48 and CRC 0.129..0.130 us/mixed-op.
Plan/pack/publication wall was respectively 0.032, 0.108..0.110 and
0.252..0.255 us/mixed-op. These clocks overlap: do not sum them, infer a
5 us serialized CPU ceiling or treat all submitter LZ4 as owner-critical work.
The `*_cpu_ns` fields read scheduler-updated sum_exec_runtime at boundaries
(dm-target.c: swapz_worker_cpu_sample); they are diagnostic, not exact task CPU.
There is no exclusive READ/lock/owner CPU partition here. Linear has no swapz
GC; these short replay controls do not qualify sustained GC behavior.

Next: establish the remaining exclusive serial budget before implementing the
reviewer's combined LZ4 state/submitter experiment. Current main already has
ID150 submitter preparation; qualify a combined candidate against its exact
current production C, with matched service/latency/lower-I/O guardrails. Do not
reopen polling/direct BIO or infer gains from these diagnostic means.
No production C changed in this step. Full exact-source qualification of the
new development-loop glue remains pending; the owner qualification preceding
this change remains the production baseline. No history plots were refreshed.
