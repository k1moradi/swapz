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
`6b71b85c57c92e064413ea11b5b9f1aac110f0f2`, passed all five stages, and
published report-only commit
`21d50135e6fcfa4a6a84e07e92006b1515139ba5`. Loaded evidence is limited to
positively owned RAM-backed `null_blk`. The production kernel tree is unchanged
from the prior reviewed source `1888781`; this increment changes reporting and
host-load observation. Cross-report timing differences do not establish a new
kernel optimization or regression.

Concurrent commit `548fcf37effa75a180a2c350eccd8274060c9553` adds an
AVX-512 predictor backend after this run. That addition is outside this
qualification; current main must receive its own exact-source qualification.

Five matched fast-model sustained-write pairs measured async versus sync at
QD4 -0.57% (95% CI [-4.26%,+3.11%]), QD8 +26.59%
([+17.21%,+35.97%]), and QD32 +24.80% ([+17.76%,+31.85%]). QD4 has no
confirmed change. QD8 lower WRITE requests fell 21.90% (CI
[-26.21%,-17.59%]) while bytes rose 0.49% ([+0.23%,+0.75%]). QD32 requests
rose 38.11% ([+18.85%,+57.36%]) and bytes rose 0.85% ([+0.57%,+1.13%]).
Keep the throughput gain and its aggregation cost visible together.

Fast mixed async/sync throughput changed -0.23% (paired 95% CI
[-2.09%,+1.62%]), while lower WRITE requests rose 4.56%
([+2.31%,+6.81%]). Against raw, async delivered 22.46 versus 25.17 MB/s
useful WRITE throughput, with 34.64 versus 50.38 MB lower WRITE data and 789
versus 12,301 lower WRITE requests. The mixed-load logical READ rates were
7.45 versus 8.36 MB/s, with p99 of 1.93 versus 2.75 ms. These are lower I/O
costs with a useful-throughput loss on this fast synthetic model; the READ
rates are mixed-load observations, not fixed-volume swap-in times.

Fast sequential adjacent-range READ coalescing reduced lower requests by
27.33% (paired 95% CI [-32.01%,-22.64%]), but useful read throughput fell
5.87% ([-9.92%,-1.83%]). Its p99 change of +7.25%
([-5.20%,+19.69%]) remains unresolved. On the serial model, sequential
requests fell 37.82%, throughput rose 47.26%, and p99 fell 21.93%; their
respective intervals exclude zero. The fast random-read request change was
-0.12% ([-1.96%,+1.72%]), so the prior small random-read cost did not repeat
significantly here. These observations warrant attribution before an active
read-path change.

All 204 individual host CPU observations were available. The fast mixed
arms averaged about 39.8-40.9% host CPU activity and 4.8-7.9% CPU PSI waiting
across four online/affinity CPUs. This includes benchmark, kernel and background
work and does not isolate Codex. The report explicitly records
`idle_host_control=NOT_ESTABLISHED`; do not pool these data with earlier idle
runs or infer code causality across unlike resource conditions.

Loaded packed placement retained zero internal holes and zero hole-induced
run splits; live GC exercised 20 victims/rotations and verified 4096 pages.
The separate low-RAM/heavy-CPU release gate remains open. Next collect that
resource-pressure evidence, attribute QD32 and fast-read costs, then measure
realistic churn/GC/TRIM before deciding on asynchronous TRIM. Physical media,
real swap semantics and endurance remain unqualified.

## Documentation

- [VISION.md](VISION.md): product objective and non-negotiable constraints.
- [ROADMAP.md](ROADMAP.md): current work queue only.
- [coding_standards.md](coding_standards.md): production engineering rules.
- [testing_standards.md](testing_standards.md): required qualification and evidence.
- [compile.md](compile.md): build/install/test interface and artifacts.
- [benchmark.md](benchmark.md): benchmark design, metrics and interpretation.

Historical transcripts, rejected designs and old operator procedures are intentionally absent from current documentation; use immutable Git history when forensic provenance is required.
