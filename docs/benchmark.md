# Benchmark Standard

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

## Objective

Benchmark the one product, `swapz`, against an uncompressed `off` control using the same immutable logical workload. The Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`.

A performance result is useful only when the final logical image is byte-exact and source/fixture/trace provenance matches. The north-star metrics are independent lower READ and WRITE bytes **and** requests for completed useful work, including GC and flush effects, with acceptable useful throughput, read p95/p99, CPU and RAM.

## Current synthetic models

Mandatory loaded benchmarking uses newly owned RAM-backed `null_blk` only:

- slow model: 10 MiB/s lower cap, 1 ms completion delay;
- faster model: 80 MiB/s lower cap, 0.15 ms completion delay.

These model latency/bandwidth behavior; they are not measurements of real SD cards or SSDs. Do not label them as physical-media results.

The mixed QD32 matrix uses four counterbalanced pairs per model across sync/async preparation. It includes identical useful work, independent lower counters, full-image verification and bounded packed-read checks.

The write-only pilot uses QD1/4/8/32, 0% reads, finite unpaced waves, one sync and one async pair per QD/model, and exact final verification. One pair is exploratory only.

## Timed boundaries

Exclude fixture generation, device provisioning, worker allocation, buffer setup and warmup from measured useful throughput. Include the measured I/O and required final drain/fsync. Lower-sector/request deltas cover the same interval.

Report process CPU separately from kernel-worker CPU; do not imply one includes the other. RAM-backed 4MiB read tests are not cold physical swap-in.

## Current directional result

At qualified source `45a5ccf09b2a4ce396d891215581476d3ee0dce3`:

- slow-model QD1 reached about 0.89-0.94x raw and faster-model QD1 about 0.76-0.86x, with unchanged 1.00x logical/lower geometry and 4096 lower requests;
- QD4 remained about 0.60x raw on the slow model and 0.63-0.70x on the faster model with about 1.33x logical/lower geometry;
- QD8 remained about 0.89-0.90x raw on the slow model and 0.59-0.76x on the faster model;
- slow-model QD32 remained about 1.26-1.27x raw, while faster-model QD32 remained about 0.61-0.62x;
- slow mixed QD32 still lost useful WRITE throughput, and its deadline closures were dominated by `deadline_after_read`;
- random packed 4MiB reads still transferred roughly 6.2MiB of lower data for 4MiB logical work.

Interpretation: learned singleton fast-close removed most of the QD1 retention tax without changing lower geometry. The next production questions are finite-wave first-pack depth, deadline fragmentation caused by already-accepted work behind slow independent reads, alignment holes in adjacent lower-run staging, and metadata-cache thrash on random reads. All QD pilot results remain exploratory.

## Confirmation gate

Do not claim a QD performance improvement until each mode/QD/regime has at least five counterbalanced matched pairs, an appropriate confidence interval, unchanged correctness, provenance equality and no unacceptable regression in lower bytes, read tails, CPU/RAM or GC.

## Physical media

No current benchmark authorizes physical storage or active swap. A future real-device study requires separate owner authorization, exact device ownership/alias checks, backup/data-loss acceptance, independent safety review and a pinned source/procedure.


The next qualified comparison should specifically report whether the 512-entry
metadata cache reduces 4MiB seeded-random lower READ bytes/requests and p99, and
whether accepted-burst deadline handling reduces slow-model
`deadline_after_read` fragmentation. Cursor-aware planner reconstruction is a
WRITE-byte-neutral optimization: any increase in default lower WRITE bytes is a
rejection regardless of request count.
