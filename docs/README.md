# swapz

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands; the sole owner-approved exception is the development decision loop `make fast_test`, which never qualifies a source, never writes or publishes `test_results.json` and never replaces `make test`. Private scripts and CI jobs are implementation details, not operator interfaces.

swapz is an experimental Linux Device Mapper target that compresses and packs 4KiB logical pages into 4/8/16KiB SWZ physical extents. Ordinary compression uses LZ4. The experimental page-local delta64 rescue is off by default (`delta64_rescue=0`); when explicitly enabled, a scalar sampled classifier runs before ordinary LZ4, high-score pages may run delta64 plus the rescue LZ4 first and directly adopt a sufficiently small candidate, and lower-score pages retain the ordinary-LZ4 packing-cliff route. The project exists to reduce independently measured lower-device READ and WRITE bytes and requests for the same byte-exact logical workload without sacrificing mapping correctness, ordering, integrity, bounded resource use, or acceptable read latency.

There is one product. The active product source is under `src/`; test-only code is under `tests/`; maintained documentation is under `docs/`; packaging support is under `packaging/`. Historical implementations and rejected experiments belong in Git history, not dormant source trees.

## Product identity and version

Public identities are immutable: `swapz`, `dm-swapz.ko`, `dm_swapz`, target `swapz`, alias `dm-swapz`, and the administrative utility `swapzctl`. SWZ describes the current on-disk format only and is intentionally unversioned while no incompatible deployed format exists.

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

The root Make interface is exactly `make`, `make install`, `make uninstall`, `make test` and the development-only `make fast_test`. `make fast_test` builds the working tree (dirty trees allowed), runs the window-policy native checks and a single-pair subset of the owned null_blk matrix, and prints one raw-versus-swapz table; optional `SCENARIOS=fast-mixed,fast-w8` and `REPEAT=n` select scenarios and repeats. Its numbers are unpaired single observations for development decisions only. Installation never activates swap. Official loaded qualification remains limited to positively owned RAM-backed `null_blk`. Physical backing is disabled by default; the implementation can attach only when `allow_physical_backing=1` and block 0 contains a valid matching SWAPZ authorization header created by the conservative `swapzctl format <blockdev>` command. That formatter writes block 0 and refuses non-block devices, busy devices, and nonzero unrecognized headers. This safety gate does not itself qualify physical media or authorize active system swap, reboot, `swapon`, `swapoff`, force removal, or unrelated block devices.

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

The latest successful standard owner matrix tested source
`174d42eb7135899d4bc0acb22ea82f5be1317f5f`, passed all five stages, and
published report-only commit
`edab5b87344b33f95b2152dab5efbc39fdb0b1a0`. This qualifies the complete
owned-RAM `null_blk` matrix for that exact source. Current `main` has since
advanced through settled-control cleanup, so a fresh complete `make test` is
required before current HEAD can be called the qualified baseline.

The qualified positive-fixture delta64 rescue A/B exercised 4096 direct
predictor-first adoptions that skipped ordinary LZ4. Lower WRITE bytes fell
27.04% and useful WRITE throughput rose 5.15%; lower-request and p99 intervals
overlapped zero. This is controlled positive-content evidence, not
representative swap evidence, so `delta64_rescue=0` remains the production
default.

Adjacent-range READ coalescing remains default-on. Fast sequential confirmation
reduced lower READ requests 17.53% and p99 5.43%, while the useful-throughput
interval overlapped zero. Serial-depth confirmation reduced requests 20.75%,
reduced p99 12.24%, and increased useful throughput 16.61%, with all three
intervals excluding zero. Production coalescing is fixed at an eight-block
maximum span.

Current source fixes ordinary LZ4 at acceleration one, delta64 preparation at
one producer lane, and lower-WRITE submission at one immutable run; the retired
runtime tuning selectors are absent, and the old depth-two write allocation/
append path has been removed. Loaded correctness still covers GC relocation,
whole-segment discard, packed placement and byte-exact readback. Low-RAM/
heavy-CPU behavior, realistic long-run churn, actual kernel swap, physical-media
behavior and endurance remain open qualification gates.

## Documentation

- [VISION.md](VISION.md): product objective and non-negotiable constraints.
- [ROADMAP.md](ROADMAP.md): active work plus the canonical optimization decision
  memory. Use its evidence table before proposing an experiment.
- [coding_standards.md](coding_standards.md): current production invariants, not
  experiment chronology.
- [testing_standards.md](testing_standards.md): current qualification contract,
  not a history of retired A/B protocols.
- [compile.md](compile.md): build/install/test interface and artifacts.
- [benchmark.md](benchmark.md): current benchmark methodology, interpretation and
  only the minimum settled evidence needed to avoid repeating a test.

A settled idea should have one compact record in the ROADMAP evidence table:
**decision, evidence anchor when useful, and the condition that would justify
reopening it**. Do not duplicate the full experiment story across documents.
Detailed trial narratives and superseded procedures belong in immutable Git
history and report commits.
