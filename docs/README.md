# swapz

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

swapz is an experimental Linux Device Mapper target that compresses and packs 4KiB logical pages into 4/8/16KiB SWZ3 physical extents. The project exists to reduce independently measured lower-device READ and WRITE bytes and requests for the same byte-exact logical workload without sacrificing mapping correctness, ordering, integrity, bounded resource use, or acceptable read latency.

There is one product. The active product source is under `src/`; test-only code is under `tests/`; maintained documentation is under `docs/`; packaging support is under `packaging/`. Historical implementations and rejected experiments belong in Git history, not dormant source trees.

## Product identity and version

Public identities are immutable: `swapz`, `dm-swapz.ko`, `dm_swapz`, target `swapz`, alias `dm-swapz`, and the read-only utility `swapzctl`. The SWZ3 name describes the disk format only.

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
root `test_results.json.xz`, with the latest sanitized PASS/FAIL/BLOCKED test
and benchmark result and automatically publishes that file directly to
`main`. Generated report-only commits are not new source revisions: the next
run records the nearest non-report code ancestor as `tested_commit_sha` even
when a report commit is at `HEAD`. Publication retries bounded transient
push/fetch failures with backoff. A concurrent main advance is accepted only
when it still descends from the exact tested source; report commits are always
normal nonforce fast-forwards and never revert newer source bytes.

## Current evidence

The standard owner matrix tested source
`faaf9f9371b85193ae61949ce25140c054539266` and passed all five stages. Its
report-only commit is
`0e0683e58f5f997f9f0ac66fd249300a28df8aec`. Loaded qualification is limited to
positively owned RAM-backed `null_blk`. The packed-placement segment-edge fix
passed byte-exact loaded verification with zero internal holes and zero
hole-induced run splits.

The default-on bounded async-preparation path passed the standard lifecycle
matrix with K=1 and existing activation gates. Five matched fast-model
sustained-write pairs measured async versus sync at QD4 +0.52% (95% CI
[-6.90%,+7.95%]), QD8 +30.21% ([+26.03%,+34.39%]), and QD32 +20.75%
([+15.66%,+25.84%]). Fast mixed async-versus-sync useful WRITE throughput
was +0.01% (CI [-2.40%,+2.43%]) and lower WRITE requests changed by +35.2
(CI [-6.1,+76.5]), so that comparison is inconclusive. In the fast mixed raw
comparison, async wrote 15.26 versus 24.28 MB/s to the lower device and issued
804.6 versus 12301 lower WRITE requests, while useful WRITE throughput was
22.20 versus 24.28 MB/s. This confirms lower traffic for this synthetic
workload, alongside a useful-throughput loss; it does not show a universal
throughput win over raw storage.

Fast sequential adjacent-range READ coalescing reduced lower requests 28.5%
(paired 95% CI [-34.3%,-22.7%]); p99 changed -1.3% (CI [-29.3%,+26.6%]),
which does not establish a latency effect. The separate heavy-CPU/low-RAM
qualification remains open before release qualification of the async default.
Physical media, active system swap and endurance remain outside the authorized
qualification scope.

## Documentation

- [VISION.md](VISION.md): product objective and non-negotiable constraints.
- [ROADMAP.md](ROADMAP.md): current work queue only.
- [coding_standards.md](coding_standards.md): production engineering rules.
- [testing_standards.md](testing_standards.md): required qualification and evidence.
- [compile.md](compile.md): build/install/test interface and artifacts.
- [benchmark.md](benchmark.md): benchmark design, metrics and interpretation.

Historical transcripts, rejected designs and old operator procedures are intentionally absent from current documentation; use immutable Git history when forensic provenance is required.
