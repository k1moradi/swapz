# swapz

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands; the sole owner-approved exception is the development decision loop `make fast_test`, which never qualifies a source, never writes or publishes `test_results.json` and never replaces `make test`. Private scripts and CI jobs are implementation details, not operator interfaces.

swapz is an experimental Linux Device Mapper target that compresses and packs 4KiB logical pages into 4/8/16KiB SWZ physical extents. Ordinary compression uses LZ4. **Main compression requirement:** every emulated-device test and benchmark runs the production stack with delta64 rescue enabled, the `DELTA64_SHUF8` 8-byte byte-plane shuffle (byte shuffle, confirmed by the owner as the requirement; not a bit-level bitshuffle), and LZ4. A scalar sampled classifier runs before ordinary LZ4; high-score pages may run delta64 + shuffle + LZ4 first and directly adopt a sufficiently small candidate, while lower-score pages retain the ordinary-LZ4 packing-cliff route. Delta64-off is not a supported emulated-device benchmark, plot series, or performance comparison. The module-level disable switch remains only as a debugging/compatibility escape hatch and does not qualify an emulated-device result. The project exists to reduce independently measured lower-device READ and WRITE bytes and requests for the same byte-exact logical workload without sacrificing mapping correctness, ordering, integrity, bounded resource use, or acceptable read latency.

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

The root Make interface is exactly `make`, `make install`, `make uninstall`, `make test` and the development-only `make fast_test`. `make fast_test` builds the working tree (dirty trees allowed), runs the window-policy native checks and a single-pair subset of the owned null_blk matrix, and prints one raw-versus-swapz table; optional `SCENARIOS=fast-mixed,fast-w8` and `REPEAT=n` select scenarios and repeats. Every emulated scenario uses the production delta64 + `DELTA64_SHUF8` + LZ4 stack; there is no delta64-off development benchmark. Its numbers are unpaired single observations for development decisions only. Installation currently never activates swap. Generic loaded qualification remains positively owned RAM-backed `null_blk`. Physical backing is disabled by default and still requires the explicit module opt-in plus a matching SWZ authorization header. The current dedicated SD-card production mission has standing owner authorization for bounded destructive/live-swap work as defined in [AGENT_CONTEXT.md](AGENT_CONTEXT.md); that standing authority does not permit reboot, force removal, device substitution or unrelated block-device mutation.

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

The latest complete owner `make test` passed all five stages for source
`acdeba452aa142c702bed40010c083276a692711`. It published report-only commit
`17ed3c639ce99708ee2bfbed7d979b35592c7a5a`; report SHA-256 is
`e82b4054fbc51daf7bc99f2b60cc1c41581530ac0c59283229b891cb6cb40651`.
Stage times were 22.474 s (build), 189.993 s (native/rootless), 18.180 s
(W=1), 14.141 s (W=2), and 1403.514 s (owned RAM, mixed/QD). Its scope is
`RAM_BACKED_NULL_BLK_ONLY`: it does not qualify physical SD, real Linux swap,
or full-card capacity. This report predates the current lifecycle coordinator
and kernel status change.

The run began below the ID36 1 GiB `MemAvailable` gate (926,752 KiB). The owner
reports closing programs to free memory and swap during the run. Later
read-only snapshots showed about 2.1 GiB available and more than 260 MiB of
swap free; the full run, including ID36, passed. This records host headroom
for that run and does not change the gate.

Current `main` is `a31661f887f1fa7a88efdfff5186a84672217950`, synchronized with
`origin/main`. The latest production source is the same commit; it includes the
primary lifecycle coordinator behind the disabled gate, bounded status
emission, portable little-endian delta64 semantics, deliberately unaligned
codec coverage, authority geometry/generation checks, drain-wakeup closure,
GC failure-recovery/high-occupancy coverage, and hardened standalone physical
formatter identity. Current head passed production-C CI run `41655643592` and
native project-goal CI run `41655643668`. The latest owner report still tests older source
`acdeba452aa142c702bed40010c083276a692711`, so a fresh exact-head `make test`
is pending.

The normal build is not installed or loaded. Its current artifacts were built
before the source commit with `SWAPZ_BUILD_SOURCE_CLEAN=0`, so they are not
eligible for the primary plan. The latest read-only primary plan reports
`BLOCKED`; privileged execution remains disabled because exact artifact
provenance, owner qualification and lifecycle evidence are not satisfied.

At the read-only snapshot on 2026-11-03 14:40:24 UTC, the selected target was
the removable USB card partition `/dev/sda1` (8:1,
124,787,884,032 bytes, PARTUUID `f13428f6-01`, UUID
`8c6a02a2-20e9-4e31-869a-48ef7f6c990b`). At the latest read-only check it was
unmounted and inactive; the only active swap was the unrelated `/swapfile`
(227.1 MiB used), which was not touched. No swapz mapper was present, and no
physical-card write has been made. Host `MemAvailable` was 2,097,148 KiB and
swap free was 291,696 KiB.

The production manager and systemd generator select a drive through the
protected PARTUUID file and discover its current path, device number and
geometry at runtime. The current source allows unrelated host swap entries
while rejecting an active or ambiguous alias of the selected target. Prepared
start, normal stop, and standalone recovery are wired to durable run state and
module ownership. The execution gate remains disabled. Deterministic
interruption/owned-null_blk qualification, actual Linux swap, full-card memory
and capacity, physical churn, installation, and boot acceptance remain open.

The current host, target, build, CI, plan, and readiness-gate snapshot is
tracked in [handoff/production-readiness.json](handoff/production-readiness.json).
The geometry-derived logical capacity there is a candidate only; memory
feasibility, full-card correctness, and actual swap behavior remain
unqualified.

The qualified positive-fixture delta64 rescue A/B exercised 4096 direct
predictor-first adoptions that skipped ordinary LZ4. Lower WRITE bytes fell
27.04% and useful WRITE throughput rose 5.15%; lower-request and p99 intervals
overlapped zero. This is controlled positive-content evidence, not
representative swap evidence. By owner decision the production delta64 +
`DELTA64_SHUF8` + LZ4 stack is now a fixed main requirement for emulated
devices. Historical rescue-off evidence remains in Git history only; routine
qualification, development benchmarks and history plots no longer spend runs
on delta64 off/on comparison.

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

- [AGENT_CONTEXT.md](AGENT_CONTEXT.md): **always-loaded current operating
  context** — target identity, standing owner scope, autonomy rules, main-sync
  contract, documentation budget and production-ready completion criteria.
- [VISION.md](VISION.md): product objective and non-negotiable constraints.
- [ROADMAP.md](ROADMAP.md): active work plus the canonical optimization decision
  memory. Use its evidence table before proposing an experiment.
- [coding_standards.md](coding_standards.md): current production invariants, not
  experiment chronology.
- [testing_standards.md](testing_standards.md): current qualification contract,
  not a history of retired A/B protocols.
- [context.md](context.md): reusable Linux MM, folio, swap/zswap, BIO and SWZ
  technical context; implementation proposals and priorities stay in ROADMAP.
- [compile.md](compile.md): build/install/test interface and artifacts.
- [benchmark.md](benchmark.md): current benchmark methodology, interpretation and
  only the minimum settled evidence needed to avoid repeating a test.

A settled idea should have one compact record in the ROADMAP evidence table:
**decision, evidence anchor when useful, and the condition that would justify
reopening it**. Do not duplicate the full experiment story across documents.
Detailed trial narratives and superseded procedures belong in immutable Git
history and report commits.

Agents must keep documentation at or below 25% of the 256K context window
(64K tokens). Keep AGENT_CONTEXT, VISION and README resident; retrieve only
relevant sections of the long ROADMAP/coding/testing/context references. Reload
the compact set after every sync that changes documentation.
