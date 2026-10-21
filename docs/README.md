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

The latest full run tested source
`79c6bd9400ae7f95a2881634c0cb459167d486a3` and passed all five stages. Its
report-only commit is
`013893fa3edb5267bc288439379aa3d2498761ff`; qualification is limited to
positively owned RAM-backed `null_blk`. The packed-placement segment-edge fix
passed byte-exact loaded verification with zero internal holes and zero
hole-induced run splits.

The report supports enabling bounded asynchronous LZ4 preparation by default
while keeping K=1 and the current depth/backlog activation gate. In five
matched fast-model sustained-write pairs, async versus sync was neutral at QD4
(-0.07%, paired 95% CI [-0.44%,+0.30%]), and improved throughput at QD8
(+26.80%, [+22.01%,+31.59%]) and QD32 (+23.12%, [+16.92%,+29.32%]). Fast
mixed async versus sync was inconclusive: useful write throughput +0.51%
(CI [-2.20%,+3.22%]) and lower WRITE requests +4.24% (CI [-2.17%,+10.66%]).
On that fast mixed workload, async reduced lower WRITE bytes about 31.2% and
requests about 93.5% versus raw, while useful throughput was about 12.6% lower.
The result supports the narrow async/sync policy comparison; it does not show
a universal throughput win over raw storage.

ID63 retains its fast sequential request reduction (-24.15%, CI
[-29.39%,-18.92%]) but has an unresolved p99 regression (+8.68%, CI
[+0.008%,+17.34%]). Loaded GC/TRIM, suspend/resume and injected lower-WRITE/
FLUSH failure evidence passed byte-exact and fail-closed. Physical media,
active system swap and endurance remain outside the authorized qualification
scope. The alpha.24 async-default change requires its own full owner run.

## Documentation

- [VISION.md](VISION.md): product objective and non-negotiable constraints.
- [ROADMAP.md](ROADMAP.md): current work queue only.
- [coding_standards.md](coding_standards.md): production engineering rules.
- [testing_standards.md](testing_standards.md): required qualification and evidence.
- [compile.md](compile.md): build/install/test interface and artifacts.
- [benchmark.md](benchmark.md): benchmark design, metrics and interpretation.

Historical transcripts, rejected designs and old operator procedures are intentionally absent from current documentation; use immutable Git history when forensic provenance is required.
