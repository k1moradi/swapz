# swapz

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

swapz is an experimental Linux Device Mapper target that compresses and packs 4KiB logical pages into 4/8/16KiB SWZ physical extents. Each page first uses LZ4; a sampled page-local delta64 transform may run a second LZ4 pass only for a large or RAW baseline and is stored only when it is strictly smaller. The project exists to reduce independently measured lower-device READ and WRITE bytes and requests for the same byte-exact logical workload without sacrificing mapping correctness, ordering, integrity, bounded resource use, or acceptable read latency.

There is one product. The active product source is under `src/`; test-only code is under `tests/`; maintained documentation is under `docs/`; packaging support is under `packaging/`. Historical implementations and rejected experiments belong in Git history, not dormant source trees.

## Product identity and version

Public identities are immutable: `swapz`, `dm-swapz.ko`, `dm_swapz`, target `swapz`, alias `dm-swapz`, and the read-only utility `swapzctl`. SWZ describes the current on-disk format only and is intentionally unversioned while no incompatible deployed format exists.

[`src/kernel/VERSION`](../src/kernel/VERSION) is the single source of truth for release metadata. Do not duplicate the release number in source names, reports, workflow names, binaries, or documentation headings.

## Repository layout

- `src/kernel/`: production kernel C and private headers.
- `src/userspace/`: supported product userspace code.
- `tests/runtime/native/`: direct production-C/source/build/report regressions.
- `tests/runtime/benchmark/`: deterministic benchmark fixture and replay logic.
- `tests/tools/`: private qualification orchestration and owned-RAM helpers.
- `tests/suites/`: native test build rules.
- `docs/`: current documentation only.
- `packaging/`: install/uninstall packaging logic.
- `.github/workflows/product-codec.yml`: production-C and Kbuild qualification.
- `.github/workflows/project-goals.yml`: project-goal, rootless and governance qualification.

No legacy, recall, NBD, pressure, alternate-module, or historical-model subsystem is part of the working tree. Git history is the archive.

## Supported commands

The root Make interface is exactly `make`, `make install`, `make uninstall`, and `make test`. Installation never activates swap. The module remains limited to positively owned RAM-backed `null_blk` for current loaded qualification. Physical media, active system swap, reboot, `swapon`, `swapoff`, force removal, or unrelated block devices are not authorized.

Every completed `make test` run replaces exactly one generated evidence file,
root `test_results.json`, with the latest sanitized PASS/FAIL/BLOCKED test
and benchmark result and automatically publishes that file directly to
`main`. The artifact is UTF-8 JSON with newlines and no indentation, directly readable by GitHub and
connected readers without decompression. Historical reports remain in Git
history. Generated report-only commits are not new source revisions: the next
run records the nearest non-report code ancestor as `tested_commit_sha` even
when a report commit is at `HEAD`. Publication retries bounded transient
push/fetch failures with backoff. A concurrent main advance is accepted only
when it still descends from the exact tested source; report commits are always
normal nonforce fast-forwards and never revert newer source bytes.

Loaded reports include host CPU activity and waiting pressure alongside replay
CPU use. These counters include Codex and other background work; they do not
establish an idle host or make an idle historical run directly comparable.

## Current evidence

The latest standard owner matrix tested source
`4d73b13fa66f63b24b5edf099fcb2b7f3cab756f`, passed all five stages, and
published report-only commit
`e80d8544a311130f5c81eff9b3b2fce98225cd77`. It covers owned RAM-backed
`null_blk`, including the metadata front index and page-local delta64. The
pending production-attribution increment has not been compiled or tested.
The report demonstrates functional qualification, not a causal performance win
for either the cache change or delta64. AVX-512 runtime remains unqualified on
this SSE2-only host.

Five matched fast-model write pairs measured async versus sync throughput:
QD4 +0.64% (95% CI [-1.02%,+2.31%]), QD8 +23.63%
([+17.84%,+29.43%]), QD32 +26.15% ([+19.24%,+33.06%]). QD8 lower WRITE
requests fell 17.97% ([-20.13%,-15.81%]) while bytes rose 0.47%
([+0.34%,+0.60%]). QD32 requests rose 25.04% ([+3.98%,+46.10%]) and
bytes rose 0.68% ([+0.27%,+1.08%]). Keep the K=1 throughput benefit and its
aggregation cost visible together; QD4 has no confirmed change.

Fast mixed async/sync throughput changed +1.36% (95% CI [-3.44%,+6.16%]);
WRITE requests changed +4.43% ([-4.86%,+13.72%]). Neither interval establishes
a change in that workload. Async versus raw means were 20.77 versus 19.89 MB/s
useful WRITE input, 34.83 versus 50.38 MB lower WRITE data, and 930.2 versus
12,301 lower WRITE requests. The means describe this synthetic run only.

Fast mixed arms observed about 35.1-36.0% whole-host CPU activity and
3.5-6.1% CPU PSI waiting. Background work includes Codex; these observations
neither isolate its cost nor establish an idle host. Do not pool unlike host
conditions or attribute cross-report differences to a single source change.
Packed-read engine attribution is wall time excluding lower READ waits, not
CPU consumption. Native threshold-24 delta64 routing saved 52 modeled blocks
and 49 extents on the structured corpus; absent production counters, it cannot
establish loaded adoption, lower-I/O savings or throughput benefit.

Packed placement, byte-exact readback, GC and lifecycle qualification passed.
Resource-pressure qualification, realistic churn/GC/TRIM cost, real kernel swap
semantics and physical endurance remain open. The next report will capture
production delta64 attempts, adoptions, split payload savings and rescue wall
time without changing routing or K=1. See [benchmark.md](benchmark.md) for the
measurement scope and [ROADMAP.md](ROADMAP.md) for release gates.

## Documentation

- [VISION.md](VISION.md): product objective and non-negotiable constraints.
- [ROADMAP.md](ROADMAP.md): current work queue only.
- [coding_standards.md](coding_standards.md): production engineering rules.
- [testing_standards.md](testing_standards.md): required qualification and evidence.
- [compile.md](compile.md): build/install/test interface and artifacts.
- [benchmark.md](benchmark.md): benchmark design, metrics and interpretation.

Historical transcripts, rejected designs and old operator procedures are intentionally absent from current documentation; use immutable Git history when forensic provenance is required.
