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

The five root goals are `make` (build), `make install` (admit qualified
artifacts), `make uninstall` (owned removal), `make test` (official
qualification), and `make fast_test` (development only). Installation
never rebuilds, re-signs, loads a module, creates a mapper, or activates
swap. See [the root Make API](compile.md#root-make-api).

`make fast_test` accepts dirty trees, runs native/replay checks and defaults
to three raw-versus-swapz repeats per owned-RAM `null_blk` scenario.
`make fast_test SCENARIOS=fast-mixed,fast-w8 REPEAT=3` narrows the loop.
It needs noninteractive privilege for owned-device work; its noise-screened
results are directional, not matched confidence-interval evidence. It
never qualifies a source or publishes `test_results.json`. Every emulated
scenario uses the fixed delta64 + `DELTA64_SHUF8` byte shuffle + LZ4 stack.

A native/rootless or CI PASS is **not** a loaded/physical PASS. Only
`make test` can qualify exact-source artifacts on positively owned RAM
backing; physical acceptance is a separate gate under the
[frozen policy](production-acceptance.json) and
[current device authorization](AGENT_CONTEXT.md). Non-`null_blk` backing
remains disabled by default and requires explicit `allow_physical_backing=1`
plus a valid exact-size SWZ authorization header. A full `make test` must
report BLOCKED (nonzero) when safe noninteractive loaded qualification is
unavailable.

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

## Evidence boundaries and failure triage

Treat **source qualification**, **host execution**, **physical acceptance**, and
**deployment observation** as separate gates. Read current
[`test_results.json`](../test_results.json) before citing a PASS or failure:
its `tested_commit_sha`, `qualification`, per-stage diagnostics and artifact
hashes must describe the **same** source. A historical PASS, report-only
publication commit, unqualified dirty build, or CI alone does not qualify
current `main`. The [read-only status snapshot](production-status.json) and
[historical readiness snapshot](handoff/production-readiness.json) are captured
observations, not live release verdicts.

| Evidence level | Proves when passing | Does not prove |
| :--- | :--- | :--- |
| Native/rootless (including CI) | The source contracts, mocked lifecycle/package failure paths and native-C regressions actually exercised by that run | Loaded kernel, real swap, SD card, reboot |
| Owned loaded `null_blk` | The loaded gates that actually PASS on a positively owned RAM-backed kernel target, including their byte-oracle/GC/pressure/service evidence | Physical media behavior, real-swap semantics or cold boot |
| Authorized physical SD card | Each individually completed exact-source/card-bound result: full-capacity RAM, real anonymous swap, physical service/GC or lifecycle evidence | Any physical gate that was not run, a successful reboot, or hibernation |
| Owner-observed cold boot | Persisted next-boot verifier outcome for the exact source, partition, module and mapper | Hibernation/resume (unsupported) or survival of pre-crash swap pages |

Find the **first failed phase**, not a presumed root cause from a downstream
symptom. These are safe diagnostic starting points, never bypass instructions:

| Failed phase / symptom | Likely evidence and fault domain | Next safe verification step |
| :--- | :--- | :--- |
| Build, signing or W=1/W=2 | Kbuild/compilation warnings, unavailable noninteractive `sudo -n`, Secure Boot key/signature rejection. **Source/build or environment/authorization**; the first error decides. | Inspect build diagnostics, running-kernel headers and [signing requirements](compile.md#secure-boot-module-signing); never load an unqualified artifact. |
| Native/rootless contracts FAIL | Compiler diagnostic, failing assertion or source/test interface mismatch. **Source/test**, but the first diagnostic may not prove the root cause. | Compare the report's source SHA and first error with the actual current symbol/header/test; do not treat an old report as a current failure. |
| Owned RAM stage BLOCKED on ID36 | `MemAvailable` below the 1 GiB pressure floor, cgroup/PSI gates or background load. **Host environment**, not a logical byte mismatch. | Read the captured counters; safely reduce unrelated load before authorized official qualification. Never manipulate unrelated swap as a workaround. |
| Owned RAM preflight or module load BLOCKED | `null_blk` ownership, `dmsetup`, privilege, vermagic, signature or module availability. **Environment/authorization** unless source diagnostics show otherwise. | Verify identities and logs read-only; do not seize another agent's device or force-load a foreign module. |
| Qualification or artifact admission refused | `SWAPZ_BUILD_SOURCE_CLEAN=0`, mismatched source/hashes, incomplete five-stage PASS. **Provenance/evidence**, not qualification. | Compare source ancestry, immutable build-info, report and installed digests; [install](compile.md#packaging) admits exact bytes rather than rebuilding. |
| Primary physical preflight/acceptance BLOCKED | PARTUUID/parent, mount/swap conflict, missing exact-size SWZ header, inactive `allow_physical_backing=1`, unmeasured peak RAM or incomplete physical campaign. **Identity/authorization/pending test**; inspect the actual failed check. | Check the protected selector and read-only inventory against [authorization](AGENT_CONTEXT.md#standing-owner-authorization) and the [physical protocol](benchmark.md#physical-media-and-workload-validity). Never mutate media just to diagnose. |
| Package upgrade/uninstall or primary recovery refused | Retained transaction journal/snapshot, DKMS/ownership/hash mismatch, active mapper or ambiguous state. **Deployment/recovery**, not permission to erase markers. | Preserve the failure record; read [transactional recovery](compile.md#packaging) and validate ownership/digests before an authorized recovery attempt. |
| Boot evidence absent/INCOMPLETE/FAIL | Missing owner-observed reboot, identity mismatch, degraded runtime health or unverifiable persistent observation. **Pending evidence or deployment**, not a rootless PASS. | Read the [boot/hibernation boundary](handoff/systemd-runtime-health.md) and durable verifier result; only the owner reboots. Hibernation remains unsupported. |
| History plots `NOT UPDATED` | Missing Matplotlib or renderer/history error. **Optional report visualization**, not a changed test verdict. | Check the local plot log and keep the original source-pinned report; see [plot policy](benchmark.md#automatic-plots-for-each-computer). |

Do not freeze one report's compiler symbol, blocker or inferred root cause into
this active guide. `test_results.json` may itself describe an older source, and
`production-status.json` is only a timestamped observation. Match source SHA,
phase and diagnostic before acting; keep superseded failure narratives in
source-bound reports, handoff history and Git history.

Historical [old-host physical and live-swap evidence](live-swap-trial-recovery.md)
is not current SD-card authorization or cold-boot proof. Current non-hibernation
deployment scope and retained package recovery are governed by
[AGENT_CONTEXT](AGENT_CONTEXT.md) and [compile](compile.md#packaging).

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
- [benchmark.md](benchmark.md): current benchmark methodology and qualification
  interpretation; source-pinned experiment narratives are archived under
  [historical benchmark experiments](handoff/historical-benchmark-experiment-memory.md).

A settled idea should have one compact record in the ROADMAP evidence table:
**decision, evidence anchor when useful, and the condition that would justify
reopening it**. Do not duplicate the full experiment story across documents.
Detailed trial narratives and superseded procedures remain in clearly labeled
historical handoff records, Git history, and report commits—not active policy.

Agents must keep documentation at or below 25% of the 256K context window
(64K tokens). Keep AGENT_CONTEXT, VISION and README resident; retrieve only
relevant sections of the long ROADMAP/coding/testing/context references. Reload
the compact set after every sync that changes documentation.
