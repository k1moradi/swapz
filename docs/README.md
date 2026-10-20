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
`main`. The normal report commit is a direct child of the tested source. If
`main` advances during a long qualification run, publication may retry only
when the new remote head is a descendant of that exact tested source; the
report-only commit is then built on the newer main tree so no newer source is
reverted. Publication is always nonforce and bounded, and divergence still
fails closed. No report branch or PR is created, and normal diagnosis should
use the published file rather than requiring the owner to copy private
root-owned logs.

## Current evidence

Owner-loaded qualification of source `2fabd0dc4b3fe09b8e52e9a624e9452647229e09`
(report-only `92d6aa08b44ab7dd827636680584f8c9a313a89b`) passed all five
stages on positively owned RAM-backed `null_blk`.

ID65 is qualified: removing the refuted `swapz-read` helper preserved and
strengthened ID63. On SSD_EMULATED, adjacent exact-range coalescing reduced
sequential lower READ requests 24.1% with paired 95% CI [-27.7%,-20.5%] while
sequential p99 changed -3.6% with CI [-9.5%,+2.4%]. On SD_EMULATED it reduced
sequential requests 40.3% and p99 38.1%, both with decisive paired intervals.
The legacy helper CPU/status compatibility tokens remain zero.

ID66 is also qualified. Multi-page DISCARD now performs zero-allocation
shared-extent liveness prevalidation by temporarily consuming and restoring the
exact validated `live_records` prefix before any mapping/generation commit.
Loaded GC/TRIM, suspend/resume and injected lower-WRITE/FLUSH failure evidence
remained byte-exact and fail-closed.

ID64 remains qualified with only a directional regression control. Fast
write-only QD8 retains a confirmed K=1 async benefit of +8.1%, paired 95% CI
[+2.3%,+13.9%]. Physical media and active system swap remain outside the
authorized safety scope.

## Documentation

- [VISION.md](VISION.md): product objective and non-negotiable constraints.
- [ROADMAP.md](ROADMAP.md): current work queue only.
- [coding_standards.md](coding_standards.md): production engineering rules.
- [testing_standards.md](testing_standards.md): required qualification and evidence.
- [compile.md](compile.md): build/install/test interface and artifacts.
- [benchmark.md](benchmark.md): benchmark design, metrics and interpretation.

Historical transcripts, rejected designs and old operator procedures are intentionally absent from current documentation; use immutable Git history when forensic provenance is required.
