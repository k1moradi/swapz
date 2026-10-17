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

At qualified source `c4539b3afe222372d5266be5a79bb96f23dfdeea`:

- slow-model QD1 was about 0.38x raw; QD4 about 0.60x; QD8 about 0.88–0.90x; QD32 about 1.27x;
- faster-model QD1 was about 0.19x raw; QD4 about 0.62–0.71x; QD8 about 0.61–0.76x; QD32 about 0.61–0.63x;
- lower WRITE request savings remained strong at QD4+;
- QD1 still had no aggregation benefit;
- the accepted-incoming first-pack tail fix materially recovered QD8 without changing QD1, but fast finite QD4/QD32 still expose first-pack scheduling/packing loss;
- the mixed faster-model async arm showed a preliminary useful-WRITE gain, while the slow mixed model still lost useful throughput.

Interpretation: the full retention deadline was a major QD8 bottleneck, but lower-request reduction alone is still insufficient. The later one-handoff first-pack experiment at `cb6cd5a...` is rejected: on the medium QD4 pilot it reduced some request counts while lowering logical/lower byte efficiency and materially worsening latency/throughput, so request merging alone is not a win. The next production-C question is whether repeated worker-empty singleton deadlines can safely disable retention only for demonstrably isolated closed-loop traffic. The pilot does not establish significance.

## Confirmation gate

Do not claim a QD performance improvement until each mode/QD/regime has at least five counterbalanced matched pairs, an appropriate confidence interval, unchanged correctness, provenance equality and no unacceptable regression in lower bytes, read tails, CPU/RAM or GC.

## Physical media

No current benchmark authorizes physical storage or active swap. A future real-device study requires separate owner authorization, exact device ownership/alias checks, backup/data-loss acceptance, independent safety review and a pinned source/procedure.
