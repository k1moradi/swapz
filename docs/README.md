# swapz

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

swapz is an experimental Linux Device Mapper target that compresses and packs 4KiB logical pages into 4/8/16KiB SWZ physical extents. Each page uses LZ4. The experimental page-local delta64 rescue is off by default (`delta64_rescue=0`); an explicitly enabled target may try it for a large or RAW baseline and stores it only when strictly smaller. The project exists to reduce independently measured lower-device READ and WRITE bytes and requests for the same byte-exact logical workload without sacrificing mapping correctness, ordering, integrity, bounded resource use, or acceptable read latency.

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
`5bdd040334ee0739e1663e98eef4c875a1c4629a`, passed all five stages, and
published report-only commit
`1df2e5a6d7c52682c2ac048310b0ed2f932a2791`. This qualifies the standard
owned-RAM matrix for that source only. Later metadata-locality work and the
reviewed preparation-array/default-off rescue changes remain owner-unqualified.

Five matched fast-model write pairs measured async/sync throughput changes:
QD4 +0.88% (95% CI [-0.59%,+2.34%]), QD8 +19.62%
([+15.02%,+24.22%]), QD32 +26.37% ([+21.31%,+31.43%]). QD8 lower WRITE
requests fell 16.19% while bytes rose 0.39%; QD32 requests rose 25.44% and
bytes rose 0.70%. Those four I/O intervals exclude zero. Fast mixed async/sync
throughput +1.27% ([-1.06%,+3.61%]) remains inconclusive.

All 14 mixed and 40 sustained-write sessions recorded zero delta64 classifier
passes, attempts and adoptions. Classification still consumed measured wall
time; it is not isolated CPU consumption. The reviewed policy therefore makes
`delta64_rescue=0` the default and allocates predictor scratch only when opted
in. The codec/GC encoding and native structured-corpus controls remain intact.

Fast QD32 whole-host CPU activity averaged 38.8% sync versus 53.8% async;
CPU PSI averaged 19.1% versus 25.9%. These include benchmark, kernel and
background work such as Codex. No idle-host control or code-specific CPU
attribution exists. Do not pool unlike host conditions or treat elapsed engine
timings as CPU time. K=1, activation thresholds and packing geometry remain
unchanged. Low-RAM/heavy-CPU, realistic churn, actual kernel swap and physical
endurance remain open qualification gates.

## Documentation

- [VISION.md](VISION.md): product objective and non-negotiable constraints.
- [ROADMAP.md](ROADMAP.md): current work queue only.
- [coding_standards.md](coding_standards.md): production engineering rules.
- [testing_standards.md](testing_standards.md): required qualification and evidence.
- [compile.md](compile.md): build/install/test interface and artifacts.
- [benchmark.md](benchmark.md): benchmark design, metrics and interpretation.

Historical transcripts, rejected designs and old operator procedures are intentionally absent from current documentation; use immutable Git history when forensic provenance is required.
