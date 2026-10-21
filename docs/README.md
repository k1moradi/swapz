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

The latest attempted full run tested source
`3893bc2e7d015a6ea30ba543bfe8c2416b223129` and failed in Native and rootless
contracts after the module/helper build. Its report-only commit is
`1c33ea826f7151c544ab82463b3c5a21df952f72`; no loaded correctness or
performance stage ran. The sanitized report does not name the failing native
assertion. Source review found a packed append-only segment-edge path that can
return `-ENOSPC` despite free later segments; the fix and direct-C regression
are awaiting owner qualification. The last successful all-stage loaded run
before that failure tested source
`607678cfd5c3a362b2f71f32d33fb81929ec8eda` (report-only commit
`b0623ae0db7bf1dcfde040bb6b64197f370eec72`). Its bounded RAM qualification
passed all five stages, but it does not qualify the failed source or this
unrun fix. The older detailed owner evidence below remains useful historical
context, not the newest successful run.

Owner-loaded qualification of source `2fabd0dc4b3fe09b8e52e9a624e9452647229e09`
(report-only `92d6aa08b44ab7dd827636680584f8c9a313a89b`) passed all five
stages on positively owned RAM-backed `null_blk`.

The latest owner run keeps ID63's request-efficiency result but reopens its
fast-latency question. On SSD_EMULATED, adjacent exact-range coalescing reduced
sequential lower READ requests 20.0% with paired 95% CI [-24.4%,-15.5%] while
p99 increased 9.5% [1.7%,17.4%]. On SD_EMULATED it reduced sequential requests
41.1% and p99 37.8%, both decisively. Current source therefore removes rejected
pair cache-copy work and moves shared-cache absorption after upper completion;
ID63 remains enabled pending owner confirmation.

ID66 is also qualified. Multi-page DISCARD now performs zero-allocation
shared-extent liveness prevalidation by temporarily consuming and restoring the
exact validated `live_records` prefix before any mapping/generation commit.
Loaded GC/TRIM, suspend/resume and injected lower-WRITE/FLUSH failure evidence
remained byte-exact and fail-closed.

ID64 remains qualified with only a directional regression control. The prior
fast write-only QD8 +8.1% paired result was collected by the retired per-QD
wave dispatcher; it remains historical burst evidence only and no longer
qualifies sustained-QD throughput. Current source uses persistent lane-owned
write workers for that evidence. Physical media and active system swap remain
outside the authorized safety scope.

## Documentation

- [VISION.md](VISION.md): product objective and non-negotiable constraints.
- [ROADMAP.md](ROADMAP.md): current work queue only.
- [coding_standards.md](coding_standards.md): production engineering rules.
- [testing_standards.md](testing_standards.md): required qualification and evidence.
- [compile.md](compile.md): build/install/test interface and artifacts.
- [benchmark.md](benchmark.md): benchmark design, metrics and interpretation.

Historical transcripts, rejected designs and old operator procedures are intentionally absent from current documentation; use immutable Git history when forensic provenance is required.
