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
- `docs/`: maintained documentation, including clearly labeled historical records under `docs/handoff/`.
- `packaging/`: install/uninstall packaging logic.
- `.github/workflows/product-codec.yml`: production-C and Kbuild qualification.
- `.github/workflows/project-goals.yml`: project-goal, rootless and governance qualification.

No legacy, recall, NBD, pressure, alternate-module, or historical-model subsystem is part of the working tree. Git history is the archive.

## Supported commands

The root Make interface is exactly `make`, `make install`, `make uninstall`, `make test` and the development-only `make fast_test`. `make fast_test` builds the working tree (dirty trees allowed), runs native/replay checks and three raw-versus-swapz pairs per default owned-`null_blk` scenario, and prints development tables; optional `SCENARIOS=fast-mixed,fast-w8` and `REPEAT=n` select scenarios and repeats. Every emulated scenario uses the production delta64 + `DELTA64_SHUF8` + LZ4 stack; there is no delta64-off development benchmark. Its noise-screened results are development observations only, not an exact-source qualification or the paired confidence-interval evidence required by `make test`. Installation consumes only the exact artifacts already qualified by `make test`; it does not rebuild or re-sign them, and it never loads the module, creates a mapper, or activates swap. Generic loaded qualification remains positively owned RAM-backed `null_blk`. Physical backing is disabled by default and still requires the explicit module opt-in plus a matching SWZ authorization header. The current dedicated SD-card production mission has standing owner authorization for bounded destructive/live-swap work as defined in [AGENT_CONTEXT.md](AGENT_CONTEXT.md); that standing authority does not permit reboot, force removal, device substitution or unrelated block-device mutation.

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

Use the generated evidence artifacts directly instead of copying volatile
commit IDs, stage timings, host counters, or readiness flags into this compact
navigation document.

- [`test_results.json`](../test_results.json) is the canonical latest published
  owner `make test` report. Read its `overall`, `tested_commit_sha`,
  qualification scope, stage results, and qualified-artifact hashes together.
  A PASS for an older source does not qualify a newer `main`, and a report-only
  commit is evidence publication rather than a new production source revision.
- [`production-status.json`](production-status.json) is a timestamped,
  source-bound snapshot of read-only host observations, current CI observations,
  and open production gates. It is not a live monitor or a qualification result;
  use its capture timestamp and source SHA when interpreting it.
- [`handoff/production-readiness.json`](handoff/production-readiness.json) is
  explicitly marked `snapshot_kind: HISTORICAL` and `SNAPSHOT_CURRENT: NO`.
  Its `updated_at_utc` and repository SHAs document a past host observation,
  **not** current synchronization or production readiness. Never let its
  historical fields override current source, policy, or test evidence.
- [`production-acceptance.json`](production-acceptance.json) is the canonical
  quantitative physical-acceptance policy consumed by the physical evaluators.
  Candidate geometry or capacity in a snapshot is not a production PASS until
  the required full-capacity, incompressible-data, lifecycle, churn, and
  physical evidence actually passes.

Current target identity, standing authorization, lifecycle execution policy,
and production-readiness definitions live in
[AGENT_CONTEXT.md](AGENT_CONTEXT.md). Historical `/dev/sda4` physical and
live-swap evidence is preserved separately and must not be read as instructions
for the current dedicated SD card.

## Documentation

- [AGENTS.md](../AGENTS.md): mandatory Codex/agent instructions; ONLY
  `main`, no new branches, no PRs, and fast-forward-only direct publishing.
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
- [handoff/old-host-physical-and-live-swap-evidence.md](handoff/old-host-physical-and-live-swap-evidence.md): historical `/dev/sda4` physical/capacity/live-swap evidence and transitional primary-manager implementation notes; not current policy.
- [compile.md](compile.md): build/install/test interface and artifacts.
- [benchmark.md](benchmark.md): current benchmark methodology, interpretation and
  only the minimum settled evidence needed to avoid repeating a test.

A settled idea should have one compact record in the ROADMAP evidence table:
**decision, evidence anchor when useful, and the condition that would justify
reopening it**. Do not duplicate the full experiment story across documents.
Detailed trial narratives and superseded procedures remain in clearly labeled
historical handoff records, Git history, and report commits—not active policy.

Agents must keep documentation at or below 25% of the 256K context window
(64K tokens). Keep AGENT_CONTEXT, VISION and README resident; retrieve only
relevant sections of the long ROADMAP/coding/testing/context references. Reload
the compact set after every sync that changes documentation.
