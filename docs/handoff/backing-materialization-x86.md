# Native RAM-backing materialization sensitivity: prospective study

ID157 attributed 165/1,019 observed owner stacks to null_blk backend work.
This study keeps production C unchanged and asks how first-touch allocation
in the RAM-backed model affects the raw/swapz comparison. It is not a product
optimization, physical NVMe qualification or a RAM-bandwidth measurement.

The [fixed plan](backing-materialization-x86-plan.json) declares eight FM/MF
rounds, three workloads and two repetitions per condition block (96 owned
pairs/192 arms). F uses fresh backing with canonical setup. M writes the full
64MiB of BOTH newly owned raw and swapz backing before target setup/timing.
Exact completed lower sectors and zero outstanding I/O are checked. Inputs,
service geometry and fresh target/allocator state remain matched. No old device
or mapping is reused and no physical device or active swap is touched.

The paired unit is the round: average two log useful-WRITE/raw observations
within each condition block, then compare M/F. Three primary endpoints use
98.3333% family intervals, adjusted exact signs, a 5% absolute practical floor
and at least seven usable rounds for a direction claim. Raw rate changes ACROSS
conditions are outcomes; the 10% raw-drift screen applies WITHIN same-condition
repetitions. Exclude both conditions of a scenario/round when either is unusable,
without replacement. Full throughput, latency, lower-I/O, GC and resource data
are retained; secondary intervals are descriptive and not product promotion.

[Temporary private helper changes](backing-materialization-x86.patch) reuse the
existing ownership checks and both-device initialization pattern already used
by ID36, without altering ID36 or the canonical performance protocol. They reject
mixing the study treatment with ID36/linear calibration. The ordinary public
Make interface is unchanged. These controls will be removed after the study.
The native host, hashed identity, C/input/helper hashes and quiet-entry policy
are frozen in the plan before samples. Results are pending at publication.


The first execution attempt completed only its F block; M failed a native
argument contract before creating a device. Its environment had appended the
study suffix to a separate linear-calibration contract. That attempt is retained
separately and contributes no paired treatment result. Before restart, argument
construction was isolated from calibration and mixed-mode use was rejected at
the parent boundary. All 22 native replay contracts pass under the materialized
environment after correction. The corrected helper hashes are frozen; the new
fixed run does not reuse or selectively replace observations from attempt 1.
