# swapz

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands; the sole owner-approved exception is the development decision loop `make fast_test`, which never qualifies a source, never writes or publishes `test_results.json` and never replaces `make test`. Private scripts and CI jobs are implementation details, not operator interfaces.

swapz is an experimental Linux Device Mapper target that compresses and packs 4KiB logical pages into 4/8/16KiB SWZ physical extents. Ordinary compression uses LZ4. **Main compression requirement:** every emulated-device test and benchmark runs the production stack with delta64 rescue enabled, the `DELTA64_SHUF8` 8-byte byte-plane shuffle (byte shuffle, confirmed by the owner as the requirement; not a bit-level bitshuffle), and LZ4. A scalar sampled classifier runs before ordinary LZ4; high-score pages may run delta64 + shuffle + LZ4 first and directly adopt a sufficiently small candidate, while lower-score pages retain the ordinary-LZ4 packing-cliff route. Delta64-off is not a supported emulated-device benchmark, plot series, or performance comparison. The module-level disable switch remains only as a debugging/compatibility escape hatch and does not qualify an emulated-device result. The project exists to reduce independently measured lower-device READ and WRITE bytes and requests for the same byte-exact logical workload without sacrificing mapping correctness, ordering, integrity, bounded resource use, or acceptable read latency.

There is one product. The active product source is under `src/`; test-only code is under `tests/`; maintained documentation is under `docs/`; packaging support is under `packaging/`. Historical implementations and rejected experiments belong in Git history, not dormant source trees.

## Product identity and version

The immutable product identities and unversioned SWZ format are specified above.

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

Completed `make test` runs replace root `test_results.json` with one sanitized,
plain UTF-8 PASS/FAIL/BLOCKED/INCOMPLETE report and publish ordinary non-force fast-forward
report commits on `main`. Prior evidence remains in Git history. A report-only
commit is not new production source: `tested_commit_sha` identifies the nearest
non-report code ancestor. Publication accepts concurrent advances only when
they descend from the exact tested source; it never reverts newer source bytes.
See [the test/report contract](compile.md#build).

Loaded host CPU/PSI samples include background activity; see the
[benchmark context](benchmark.md#cpu-and-host-load-context) before comparison.

## Current evidence

Use the generated evidence artifacts directly instead of copying volatile
commit IDs, stage timings, host counters, or readiness flags into this compact
navigation document.

- [`test_results.json`](../test_results.json): latest published owner `make test`
  evidence; interpret `overall`, source, stages and exact artifact hashes together.
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

## Evidence boundaries and failure triage

Read the current [test report](../test_results.json) before acting: bind
`source_sha`/`tested_commit_sha`, qualification scope, the stages actually
recorded and `qualified_artifacts` to the **same** source. A complete PASS
requires all five official stages; fail-fast FAIL/BLOCKED reports may contain
fewer. Required CI must also PASS for that source; neither CI alone, a
report-only commit, a dirty build, nor an older qualified source admits a newer
`main`. The
[production status](production-status.json) is a timestamped read-only
observation; [handoff readiness](handoff/production-readiness.json) is
explicitly **historical**, not a live release verdict.

| Evidence gate | A PASS establishes only | Never infer |
| :--- | :--- | :--- |
| Native/rootless and source-bound CI | The contracts actually exercised on that source | Loaded kernel, real swap, physical SD or boot |
| Positively owned loaded `null_blk` | Loaded RAM-backed byte-oracle, GC, pressure and service checks actually run | Physical behavior, anonymous swap-in, cold boot |
| Authorized physical SD | Separately completed full-capacity incompressible RAM/geometry, anonymous swap, physical GC/churn and lifecycle gates | A skipped gate, NAND lifetime, boot or hibernation |
| Owner-observed next boot | The durable verifier's matching boot ID, source, PARTUUID/parent, mapper and services | Recovery of pre-crash swap pages or hibernation |

### Diagnose the first record

Start with the report's `overall`. If `stages[]` contains a non-`PASS`
item, use the first one and record `name`, optional `failed_phase` and
`diagnostic`, and `exit_code`. If every recorded stage is `PASS` but
`overall` is not, inspect the current runner's post-stage gates:
`benchmarks.verdicts.{overall,reason}`,
`benchmarks.write_saturation.{overall,reason}`, and
`qualified_artifacts.{status,reason}`. Then trace that gate to the producer's
**earliest failed phase and original numeric errno**, when emitted; a downstream
exception must not replace that diagnostic. Inspect retained journal/backup
state and observed ownership **read-only** before selecting the safe recovery
action below. The primary lifecycle emits `PRIMARY_PREPARE`, `PRIMARY_START`,
`PRIMARY_STOP` and `PRIMARY_RECOVER` with `phase` and `errno` on
many execution failures; `PRIMARY_PREPARE` additionally reports `claim=none`
or `claim=retained` after its ownership decision. Other operations may not
emit a claim: inspect durable state and live identity **read-only**, never
infer that a failed operation released a mapper, module or partition lock.

`BLOCKED` means a prerequisite or safe admission is not established;
`UNAVAILABLE` means an observation is missing or cannot be trusted;
`FAIL`/`FAILED` identifies a failed check or operation, not automatic
permission to retry. A missing value is not zero, an absent mapper is not
proof of an unowned partition, and a `PASS` from mocks is not a host PASS.
Keep logs privacy-safe: phase, errno, counts, booleans, sanitized identities
and hashes suffice. Do not capture swap-page contents, representative fixture
bytes, signing private keys or unredacted unrelated host data.

**Illustrative only — synthesized failures, not completed qualifications:**

```text
PRIMARY_PREPARE=FAILED phase=partition-lock-close errno=5 error=Input/output error claim=retained target_unchanged=true
PRIMARY_START=FAILED phase=swapon errno=16 error=Device or resource busy
```

The first sample explicitly retains the claim; the second does **not** state
whether the mapper is still live. Preserve recovery files and inspect the
exact selected device, `/proc/swaps`, mapper and journal before any action.

Durable primary stages are `READY` (prepared), `STARTING` (activation pending),
`ACTIVE` (recorded live), `STOPPING` (drain/teardown pending),
`RECOVERING` (reconciliation pending), `RESTORED` (owned resources restored),
`DISABLING` (pre-activation cleanup), `COMPLETE` (finalized) and
`RECOVERY_REQUIRED` (interrupted/uncertain). These are **journal claims**:
verify the observed mapper, swap, header and module before treating a stage
as completion or permitting cleanup.

| First failure / operation | Read-only prerequisite and safe response |
| :--- | :--- |
| Build, W=1/W=2, signature or native contracts | Read first compiler/assertion error, current source, running-kernel headers and [signing boundary](compile.md#secure-boot-module-signing). A missing `sudo -n`, key or load permission is BLOCKED, not a verified module. |
| Qualification or package install | Compare tested source, current CI, module/CLI/oracle digests and DKMS ownership. [Installation](compile.md#packaging) admits qualified bytes; it never repairs stale qualification by rebuilding. |
| Package upgrade/uninstall/recover | Read the retained journal's **durable** phase, operation and snapshot hashes; refuse ambiguous files, DKMS state or owners. [Transactional packaging](compile.md#packaging) requires explicit recovery, not deleting a journal/marker or activating a partial install. |
| Primary plan/prepare/start | The read-only `swapzctl primary plan` exposes selector, geometry, original header, recovery storage, mount/swap inventories, module provenance and authorization checks. Protect the exact PARTUUID **and physical parent**, recovery filesystem and source-bound token. Prepare/start remain runtime-locked until qualified. Do not interpret an available `/dev/sda1` path as identity. A clean process-leader mount inventory cannot rule out a selected-partition or physical-parent mount held only by a non-leader thread: verify the [cross-thread namespace regression](https://github.com/k1moradi/swapz/issues/94) passes on the exact source before claiming safe admission. |
| Primary stop/recover | Use normal swapoff and only exact-owned teardown. A failed drain or unknown `READY`/`STARTING`/`ACTIVE`/`STOPPING`/`RECOVERING`/`RECOVERY_REQUIRED` record retains evidence; do not force-remove, clear the header, re-enable raw swap or unload a module with users. See [lifecycle safety](AGENT_CONTEXT.md#standing-owner-authorization). |
| Development-only card preflight / byte oracle | An exact `unclaimed_null_blk` BLOCKED from `make fast_test` is an owned-RAM preflight outcome, **not** an SD-card test; only that specific environmental block may admit the private development smoke. `PHYSICAL_DEVELOPMENT_SMOKE=PASS` proves a source-bound 16 MiB mapper direct-I/O round-trip with the original header restored and Linux swap still inactive, **not** real swap, full physical acceptance or boot. See [the development-only contract](testing_standards.md#development-only-card-backed-data-path-smoke). |
| Loaded RAM or physical admission | Distinguish ID36 `MemAvailable`/PSI/cgroup pressure from byte mismatches. A loaded `null_blk` proof is not anonymous-page swap, full-capacity RAM, physical GC/churn or cold READ evidence. Recheck mounts, active swap aliases, protected parent, exact-size SWZ header and `allow_physical_backing=1` **without mutation**. Follow the [frozen physical protocol](benchmark.md#physical-media-and-workload-validity). |
| Runtime health or cold-boot evidence | Read the latest `SWAPZ_RUNTIME_HEALTH=` journal result and the persisted boot verifier observation. `DEGRADED`/INCOMPLETE can mean telemetry missing, not confirmed target failure; only a separate **owner-initiated** reboot can establish cold-boot PASS. Never reboot as Codex; [hibernation stays unsupported](handoff/systemd-runtime-health.md#hibernation-and-resume-boundary). |
| Plot history `NOT UPDATED` | Check the renderer's local diagnostic log and [per-host history selection](benchmark.md#automatic-plots-for-each-computer); optional Matplotlib failure cannot change the source-pinned test verdict. |

For card-smoke failures, start with the original process exit and explicit
producer marker; preflight `BLOCKED` alone is not an executed card oracle. When
the helper emits `PHYSICAL_RESULTS=`, inspect its private per-run `results.json`
and durable `state.json` together. Bind the result's `evidence_class`,
`source_commit_sha`, `helper_git_sha`, `artifact_sha256` and `partuuid` to
the state's source/helper identity and full partition/physical-parent identity.
For an oracle attempt, use the first non-`PASS` `physical_oracle_phases[]`
record and preserve its `phase`, `status`, `return_code` and bounded captured
diagnostics. For setup or recovery failures, preserve the helper exit,
`final_recovery_state`/`recovery_error` and the durable state stage (including
`stage_before_recovery` when present). Numeric errno is authoritative only when
the producer emitted it; never synthesize one from exception text. A
`RECOVERY_REQUIRED` marker means preserve that state and stop; review live
ownership and header/swap state read-only before exact-owned recovery, never
force-remove or rerun to replace the failed attempt. Rootless `build/tests/rootless-failure.*/diagnostic.log` is private. For
stderr-pre-captured stages it retains bounded child diagnostics plus attribution.
For direct phases Bash initially creates attribution only; the official runner
may append bounded first-error or contextual evidence from its merged stage
output to that same owned log after failure. `run-tests.py` publishes only
sanitized summaries, not private tracebacks, and may truncate `log=` mid-path.
Treat `failed_phase`, `exit_code`, and `signals` as localization; consult the
complete locally retained log when available. Do not infer a missing traceback,
guess a truncated path, publish private data or escalate rootless failure into
loaded/physical cleanup.

For safe startup/stop/recovery policy use [AGENT_CONTEXT](AGENT_CONTEXT.md),
for package journal ownership use [compile](compile.md#packaging), and for
qualification/negative storage-admission limits use
[benchmark](benchmark.md#physical-media-and-workload-validity). The old
[/dev/sda4 trial](live-swap-trial-recovery.md) is historical evidence only,
never authority for the current dedicated card.

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
- [handoff/README.md](handoff/README.md): index separating active supplementary
  handoff references, historical evidence, abandoned/rejected experiments and
  deferred optimization research.
- [compile.md](compile.md): build/install/test interface and artifacts.
- [benchmark.md](benchmark.md): current benchmark methodology and qualification
  interpretation; source-pinned experiment narratives are archived under
  [historical benchmark experiments](handoff/historical-benchmark-experiment-memory.md).

For settled ideas, keep the decision, evidence anchor and reopen condition in
[ROADMAP](ROADMAP.md#optimization-evidence-table); detailed narratives remain
in historical handoff records and Git history.

Follow the [64K-token documentation working-set contract](AGENT_CONTEXT.md#documentation-working-set-contract)
and reread the active compact references after documentation changes.
