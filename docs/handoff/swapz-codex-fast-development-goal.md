# CODEX — SWAPZ FAST-DEVELOPMENT, PHYSICAL-CORRECTNESS & PRODUCTION-READINESS MISSION

**Revision 4 — 2026-11-13 | `k1moradi/swapz` | Two physical Linux hosts | Evidence-first, rapid engineering**

> **Execute the next safe engineering step; do not just produce plans.** Work against the actual current checkout/source and original repo contracts. Resolve the **first current, reproducible blocker** with a minimal diff and focused rootless regression. Use exact-source CI and the shortest adequate source-bound development gate. Avoid repeating an expensive full `make test` or the 45-minute real-swap attempt just to verify a test fixture. Do not manufacture qualifications, remove safeguards, or alter a live physical swap device without a **separate, explicit, operator-reviewed physical-run authorization for the exact host and selected partition**.
>
> **This document replaces the uploaded 2026-11-10 revision 3 mission**, including its outdated top priority (a historical READ-coalescing failure), old host/PARTUUID assumptions, standing permission for physical swap operations, broad automatic test repetition, and unconditional instruction to keep swapz after PASS. The user's November 13 follow-up explicitly authorizes **updating technical and safety requirements** in light of this conversation. Preserve the genuine invariants; replace obsolete procedures. A user's preference for a final operational disposition is **not permission to execute a new device mutation**.

## A. Immediate situation and objective

The engineering objective is reliable, reversible, source-bound **ordinary, non-hibernation Linux swapping** through swapz on a positively authenticated existing swap partition. Production readiness requires actual byte-exact swap-out and swap-in, correct lower-I/O attribution, clean memory-pressure and error behavior, reliable rollback, immutable original swap header, full-capacity and boot/lifecycle evidence, and verified current source/artifact identity. A passing native test or a development physical smoke is not production acceptance.

### Most recent verified evidence (historical once `main` advances)

- As of **2026-11-13**, both `x86-64-lubuntu` and `Inspiron1564Linux` independently pulled source through commit **`1eb69671a4b5a1ae2837be2e582bcf9b1acaf7ce`** and passed `tests/runtime/native/rootless-attribution-test.py`: **54/54 PASS on each host, twice**. The failing `test_terminal_oracle_rejects_foreign_class` assertion was corrected to inspect **sanitized relay-owned marker lines**, not the intentionally preserved raw child stderr. A private child traceback containing `test_group` must not become a public authenticated `test` identity; the public marker remains `test=unavailable reason=nonzero_exit` for foreign classes. Preserve **both** stream fidelity and fail-closed classification.
- Lubuntu also passed **43/43 terminal-oracle rootless tests** and **3/3 pressure-progress tests** at the then-tested source. The earlier `KeyError: 'device_major_int'` came from an incomplete synthetic readiness manifest, not evidence of a production data-path defect; the test fixture now provides the validated device identity and verifies that sampling receives the correct major/minor. Preserve actual production identity checks.
- The five GitHub Actions workflow groups for **`1eb69671`** were reported **SUCCESS**: native kernel-C project-goal regressions, rootless physical-evidence adversarial audit, private kernel/static contracts, experimental production-C qualification and systemd/package. **Recheck exact-source CI when `main` changes**; no previous green SHA qualifies later code.
- The latest authenticated **Lubuntu real physical swap trial** reached actual Linux anonymous-memory workload execution, then correctly failed its safety stop during **`fill`** after a roughly **45-minute** physical stage. The five-second memory PSI window measured `stalled_usec=4,496,092`, `window_usec=5,066,476`, `limit_usec=4,306,505`: about **88.7%**, above the frozen **85%** limit. This is **`reason=memory_pressure`**, not a completed or byte-exact real-swap PASS.
- At that first pressure failure the selected test cgroup had **128 MiB resident** (its configured cap), **33.4 MiB swap**, **83 memory.max events**, while host `MemAvailable` was **12,051 MiB**. Swapz's sampled `failed=0` and `error=0` do not establish completed round-trip integrity. Lower-write completion-service EWMA was approximately **30.9 ms**: suggestive, **not proof** of device-only hardware latency or swapz causation. Cgroup I/O PSI totals are cumulative and cannot be compared to an unmatched five-second memory PSI window.
- The failed run reported all five relevant recovery/cleanup checks PASS; later `swapon --show` displayed Lubuntu's original `/dev/sda4` **active, 16 GiB, 0B used**, and current `/proc/pressure/memory` avg10/60/300 = 0. Those are *point-in-time* observations, not standing authorization or proof the next run will be safe.
- The pressure-diagnostics implementation added best-effort approximately one-second counter snapshots within the observed PSI window: dedicated cgroup CPU/I/O PSI; exact-mapper physical WRITE, submitted bytes, completed upper WRITEs and worker wall time; lower-device WRITE sectors/requests; actual sampled-window duration; current round; elapsed total-workload and phase time. Strict relay/parser allowlists, null-for-unknown semantics and focused rootless regression exist. **Do not break the existing authenticated diagnostic schema, redaction or the first-error/secondary-cleanup distinction.**
- Root-generated **`test_results.json`** is explicitly exempt from the **non-report-source worktree cleanliness check** at the current physical source gate, including when modified or staged. Every other staged, unstaged or untracked source change remains blocked. **A generated report exception is not official five-stage source qualification** and does not turn an old report into PASS.

Historical reports, README snapshots and the old prompt's Nov 10 READ-coalescing failure may inform investigation but **are no longer the first live priority**. Do not spend a new 20+ minute suite on coalescing or Git credentials without a *fresh exact-source* failure requiring it. Do not automatically infer that no new failures exist; inspect current CI and only rerun the smallest test if evidence has changed.

### Host distinction — never combine evidence across devices

| Host | Observed selected swap target (REVERIFY) | Critical scope |
|---|---|---|
| **`x86-64-lubuntu`** | `/dev/sda4`, observed PARTUUID `7fb9401d-04`, 16 GiB | Root `/dev/sda3` **shares the physical parent `/dev/sda`**. Shared-root authorization is required; inspect `/etc/swapz/primary-root-parent-scope` and the manager's live fingerprint without writing or inventing it. This is the host with the observed memory-PSI real-swap stop. |
| **`Inspiron1564Linux`** | `/dev/sda1`, observed PARTUUID `f13428f6-01`, **124,787,884,032 bytes** (~116.2 GiB) | Root `/dev/sdb6` is on another disk. An **unrelated active `/swapfile` must remain untouched**. Never globally deactivate or repurpose swap. |

The **old uploaded mission claimed** that `7fb9401d-04` necessarily belonged only to a retired different host. That assertion conflicts with the later live-host context in this conversation. Treat the value above as the **latest owner-observed selector, not as trusted admission**: *recompute and compare* live PARTUUID, major:minor, parent, device topology, exact size, signature, holders and selected swap before any run. The same string in an old archive is neither a disqualification nor proof of identity. If target identity is ambiguous, **STOP before mutation**. Do not transpose a host's source test, partition digest, recovery status or consent to another host.

## B. Precedence, boundaries and autonomy

1. Read **current `AGENTS.md`, `docs/AGENT_CONTEXT.md`, `docs/VISION.md`, `docs/README.md`, applicable `docs/context.md`, `docs/coding_standards.md`, `docs/testing_standards.md`, `docs/ROADMAP.md`, `docs/production-acceptance.json` and actual source** before editing relevant code. Read targeted sections; do not spend time repeatedly loading 10,000-line documents when a narrow source contract suffices. Use exact-revision code, not recollection of an old copy.
2. Higher-level device safety, explicit current operator decisions and trusted source-defined admission have precedence over an old autonomous-mission instruction. Current Codex implementation **may autonomously investigate, edit, unit-test, run source-bound rootless/synthetic checks, coordinate Git/CI and publish reviewed minimal commits**. It **must not independently initiate new `swapoff`, real partition WRITEs/DISCARD, swapon onto a newly created mapper, normal-swap reconfiguration, privileged physical `run`, or default-swap installation** merely because the mission says to keep going.
3. **Physical mutation remains PAUSED until separate explicit consent** naming the physical host, exact by-PARTUUID target, geometry/scope, action, one-use ownership/review and intended rollback. A `plan`, source/build PASS, user's high-level desire for production readiness, or standing *post-PASS keep preference* is **not** that authorization. If a script requires additional canonical per-device one-use approval, honor it too; a chat instruction cannot waive it. Reauthorization is required for a materially different device, scope, action or new trial.
4. Recovery of a *currently active, truly owned and endangered transaction* must follow the existing verified recovery contract; if an operation would endanger live pages or lacks independent authority, STOP and report `RECOVERY=BLOCKED`. Do not infer a right to use destructive recovery commands from an old prompt. Preserve existing ordinary swap on both hosts when no owned mutation is in progress.
5. **Fast progress** means do all immediately safe engineering work rather than turn every phase into a clarification loop. Ask the user only for the **indispensable physical mutation authorization**, a truly missing secret/credential they alone can supply, or an indispensable safety-sensitive choice. No duplicate questions about facts already supplied.
6. Existing code, review record and scripts control the exact mechanics. Do not manually `swapoff -a`, `swapon -a`, call `mkswap` on the raw device, `wipefs`, write a raw header, kill a foreign process, force-remove a live mapper, bypass secure boot, alter root/boot/EFI, rewrite partition tables or invent a backup/recovery device. Never run an old destructive command because it appeared in a prior mission.

## C. The established **FAST DEVELOPMENT PACE** (mandatory default)

**Aim to finish one evidence-backed fix in minutes rather than pay a full qualification cycle for each edit.** The critical path is rootless regression → focused commit → exact-SHA CI → read-only preflight → (separately authorized) bounded development physical trial → only then official production qualification when genuinely necessary.

### Shortest adequate verification ladder

| Situation | Required next action | Do NOT do yet |
|---|---|---|
| A single traceback/assertion exists | Run that exact `python3 -B tests/...-test.py -k <method>` or whole small file; examine original traceback | Full `make test`, full benchmark, physical swap trial |
| Code fixture/schema changed | Test the relevant **producer + relay + official parser** narrowly; include malformed fields, null reads, redaction and first-cause precedence where applicable | Blindly modify acceptance thresholds |
| Rootless fix tested and source clean | Commit minimal reviewed diff **with its same-commit applicable canonical standards**, publish non-force on `main`, check exact-source CI once | Expensive suites to re-prove an unchanged earlier PASS |
| Need development RAM/build evidence | Use the supported `make fast_test`/`RESUME=1` source-bound route; reuse existing validated checkpoints as allowed | `make test_full` or duplicated `make fast_test` just for ceremony |
| Considering physical selected swap | First run read-only host/device/plan/scope/recovery checks, capture result, then request **separate actual-run authorization** | Running `run --development-only --algorithm-real-swap` or hand-issued swapoff |
| Physical trial just hit PSI or cleanup stop | Preserve first-cause private evidence, confirm original selected swap/recovery and active module/mapper state, analyze **same-window deltas** | Repeat a 45-minute physical run without a new hypothesis/authorization |
| Stable source, CI green, bounded physical development PASS | Plan required official exact-source five-stage + `make test_full` and production physical criteria **once at a deliberate qualification milestone** | Promote a development smoke to production PASS |

**Do not force unnecessary long test repetition.** In particular, `tests/tools/physical-swap-probe.py`'s `current_development_evidence()` already invokes a source-bound **`make fast_test SCENARIOS=fast-mixed REPEAT=1 RESUME=1`** when its optional authenticated RAM evidence was not supplied. Do **not** tell the user to run that manually immediately before the same command, or run it twice. Do not create or submit forged `algorithm-ram-evidence`/nonce; the helper establishes a fresh run-bound nonce and verifies source/artifact bindings.

No `make test`, `make test_full`, kernel rebuild, physical WRITE or new privileged host test should run solely to make a **54-case rootless assertion** green. Keep all performance, loaded-RAM and release acceptance budgets intact; reserve official tests for impacted code paths/release readiness and use CI/source evidence to avoid needless host cycles.

### Working style

- Find the first **authentic** failure before guessing a code cause. Rootless traceback ≠ kernel corruption; test fixture provenance ≠ selected device failure; source admission ≠ complete physical correctness; cleanup success ≠ workload PASS. Fix the narrowest legitimate cause, preserve existing tests/comments, and prefer a small git diff patch.
- Examples of recent rootless first causes: (a) synthetic readiness manifest lacked `device_major_int`/`device_minor_int`; correct **fixture**, do not make production identity optional; (b) foreign unittest class appeared in **raw relayed child stderr**, which is intentionally unsanitized; restrict **privacy assertions to relay-owned public markers**. Tests must continue to guard private data in the official report and **must not** authenticate foreign identity.
- Preserve source/test ABI names and public Make interfaces. Don't refactor or rename stable paths or helpers as a side effect. Prefer precise descriptive identifiers, DRY, cached invariants in hot paths, contiguous memory, checked geometry, RAII/ownership where relevant, no unnecessary dependencies. Production kernel remains **C under repo conventions**; user C++23 preferences apply only to actual C++ code and never override kernel C ABI, real-time/bio constraints or project standards.
- Keep fail-only, bounded privacy-safe console output. Leave full stderr and detailed traceback in the **existing private mode-0600 log** where applicable. Repaired diagnostics must preserve original errno/exit, primary failure vs cleanup failure, and authentic identity; optional telemetry errors return unknown/null and **never become a new workload refusal**.
- Do not publish private raw logs, host machine ID/DMI UUID, access tokens, secrets or memory bytes. A report-only change has different implications from source changes; explicitly track which SHA was built/tested and whether remote `main` advanced. A failed push is publication failure, **not algorithm failure**.

### Typical focused commands — run only when applicable

```bash
# Keep generated root test_results.json outside the *source cleanliness*
# check; still reject all other staged/unstaged/untracked modifications.
git status --short --untracked-files=all -- \
  . ':(top,exclude)test_results.json'

# Example: targeted rootless regressions. Commands are NOT a request to
# rerun them after their exact source has already passed.
python3 -B tests/runtime/native/rootless-attribution-test.py
python3 -B tests/runtime/native/primary-real-swap-oracle-terminal-test.py
python3 -B tests/runtime/native/primary-real-swap-test.py -k pressure_progress
python3 -B tests/runtime/native/physical-swap-probe-test.py \
  -k test_algorithm_memory_pressure_remains_first_cause_after_child_cleanup_timeout
python3 -B tests/runtime/native/test-report-test.py \
  -k test_pressure_observation_rejects_malformed_or_private_fields
```

When commands already passed at the exact currently tested source and were not affected by intervening changes, **do not run them again just to fill a checklist**. Their output is historical after the source changes; CI status must match the new SHA.

## D. Next actionable milestone, without physical mutation

1. Discover exact current `main`, canonical remote, working-tree status, source/CI SHA and any *active owned transaction*. Confirm ordinary swap still functions on the chosen host. No duplicate qualification runs while another source-bound session is active.
2. **If** exact-current CI has a fresh failure, reproduce **only its failing test**. Otherwise do not reopen already corrected `rootless-attribution` or readiness-fixture issues. Check the physically relevant helper and plan implementation at current source.
3. On **Lubuntu** (only after positively identifying it), inspect the existing **read-only** native manager `build/userspace/swapzctl primary plan`, `/proc/swaps` or `swapon --show`, selected partition major/minor/parent/header/holders and the protected shared-root-scope status. A `plan` is **not execution approval**. Record which plan gates pass/fail without printing protected scope internals.
4. If the traditional physical probe `plan` is used, distinguish its official source qualification from the development gate. `sudo python3 -I -B tests/tools/physical-swap-probe.py plan --device /dev/disk/by-partuuid/<LIVE_PARTUUID> --confirm-device /dev/disk/by-partuuid/<LIVE_PARTUUID>` is a **read-only planning/inventory path**, not a physical trial. It may create run-local bookkeeping. `SOURCE_GATE=BLOCKED` there may mean **missing official five-stage source-bound report**, even where the independent **development-only** path remains available. Do not modify report state or rerun all five stages just to make that plan line green.
5. The Lubuntu shared-root target must satisfy the independent root-owned `/etc/swapz/primary-root-parent-scope` check (canonical `schema=swapz-primary-shared-root-v1`, verified manager-computed `scope_sha256`, mode 0600, protected parent directory), selected root-parent exception and authentic `swapzctl primary plan` invariants. Neither Codex nor the user may fabricate/relax it. Failed checks remain BLOCKED.
6. When all read-only gates and source/build conditions are satisfied, produce a **compact run-specific authorization request** specifying host, exact live by-PARTUUID target, identity/geometry, shared-root implications, source/build SHA, expected selected-swap drain and post-data-area I/O, configured PSI stop, rollback and one-use approval requirements. **Stop there until explicit authorization.** Do not hide actual swapoff/write as a “preflight”.
7. After independently authorized physical execution and a real failure, inspect its source-bound **first private diagnostic** before running anything again. Distinguish fill/verify/release timing, the true sampled progress span, upper submissions/completions, lower device requests/sectors, cgroup CPU/I/O PSI and memory pressure, plus any actual kernel error. A PSI abort remains a correct safety result even when no swapz error counters rise. Preserve original ordinary-swap recovery.

Do not run `tests/tools/algorithm-physical.py` just to list options without inspecting current source: it can trigger pending-algorithm-trial recovery before inventory. Never present it as a harmless read-only listing command without verifying the actual current implementation.

## E. Physical-swap architecture and protected device lifecycle

- The actual raw selected partition remains ordinary `SWAPSPACE2` with **unchanged original 4096-byte first page**, valid UUID/signature, partition layout and bad-page geometry. Swapz's owned lower I/O is limited to its authenticated post-header data region **after the selected original swap has been safely drained**, with RAM-only mapping metadata. Only the **new virtual Device Mapper device** may receive `mkswap`; never `mkswap`/`wipefs`/`dd` raw-header restores on the real backing partition.
- Do not create unnecessary 16-GiB/116-GiB raw backup copies, a separate-parent recovery disk, a fallback swapfile, or persisted swapz RAM-metadata image. Source-defined same-boot protected `/run/swapz` runtime state, independent read-only header checks and ordinary raw-swap reactivation are the expected recovery model. Log retention is distinct from data-device metadata.
- Maintain exact ownership: authenticated by-PARTUUID selector, real block descriptors, partition/parent/root topology, parent holders and mount inventory, underlying sector range/bad-page translation, loaded mapper/module/source token and artifact digests. Recheck immediately before any mutation and before declaring normal stop/recovery. Honor swap-used/headroom, selected-swapoff deadlines, cgroup controls and one-use approvals.
- **Never globally disable swap.** Lubuntu's selected `/dev/sda4` is the only potential mutation target for its separately authorized trial. On Inspiron, the unrelated `/swapfile` stays active and untouched; the physical `/dev/sda1` is a separate independently reviewed target. No human-readable `/dev/sdaN` hint is authorization by itself.
- Do not reboot, panic, force unmap, force module unload, alter boot/root/EFI partitions, write raw swap headers, enable dual raw+mapper swap activators or alter `/etc/fstab`/systemd boot behavior without its own explicit authorized deployment scope. Production-default installation is a **distinct later consequential operation**, not implied by test permission.
- If normal safety-preserving cleanup of an already-owned trial is possible, verify raw swap/header/priority restored and no owned mapper/module/cgroup remains. If live pages cannot safely drain, preserve the exact active mapper/pages, report `RECOVERY=BLOCKED`, do not force success and do not falsely claim ordinary swap restored.
- The existing owner preference is **KEEP qualified swapz after ALL real production/host gates pass; otherwise ordinary raw swap should remain or be safely restored**. This is an *end-state preference only*. Do not automatically perform a new keep/install/restore mutation on the strength of this prompt alone.

## F. The memory-pressure failure: preserve its stop and improve *evidence*, not thresholds

The last Lubuntu trial stopped in the fill phase because memory PSI consumed ~**88.7%** of the sampled 5.066-second window, above the unchanged **85%-over-five-seconds** guard. Its cgroup intentionally runs a **384 MiB working set**, two concurrent workers, **128 MiB resident limit**, **384 MiB swap limit**. Host-wide `MemAvailable≈12 GiB` does **not** mean the isolated test cgroup has spare physical memory. `memory.events max=83` indicates repeated limit encounters; `cgroup_swap_bytes≈35,000,320` proves some swap activity, not completed minimum traffic. The reported lower WRITE EWMA of about **30.9 ms** includes completion/queue/scheduling wall time and must not be called an SSD/NAND service-time measurement.

The diagnostic field family is **best-effort and observational**: `progress_window_usec`, `cgroup_io_some_delta_usec`, `cgroup_io_full_delta_usec`, `cgroup_cpu_some_delta_usec`, `swapz_physical_write_delta`, `swapz_write_submitted_delta`, `swapz_write_completed_delta`, `swapz_worker_wall_delta_ns`, `lower_write_sectors_delta`, `lower_write_requests_delta`, `workload_elapsed_usec`, `phase_elapsed_usec`, `round_index`, plus original cumulative snapshot. Never claim a sampled delta spans the full PSI window if snapshots cover less. Never fabricate a zero when a reader was unavailable. Never conflate cgroup cumulative totals with window deltas.

The first diagnostic task on another authorized run is **causal discrimination**: (1) lower-device completion/queue latency, (2) swapz WRITE batching/ordered-worker progress, (3) constrained-cgroup reclaim and CPU/IO contention, (4) workload phase/progress timing, (5) unexpected genuine I/O or data-integrity failure. A memory-pressure guard trigger is a **failed trial** with a **successful safety stop**, not automatic corruption, nor a reason to disable worker ownership checks. Do not loosen the 85%/5-second threshold, swap limits, minimum traffic, timeouts, normal release, or byte verification to obtain a PASS. Do not repeat long trials merely to obtain a different random sample.

## G. The trusted test and release evidence ladder

Maintain exact meaning of the existing supported interfaces:

1. **Direct rootless/native/source fixtures**: fastest iteration for Python/C/Make/parser/authorization contracts. Not host physical evidence.
2. **`make fast_test`**: source-bound *development-only* RAM and selected loaded synthetic testing; `RESUME=1` is an opt-in reuse subject to validated source/artifact/stamp keys. It does not publish a canonical five-stage physical production PASS.
3. **`make test`**: official exact-source required algorithm/RAM/physical-admission reporting, with the current five-stage build/native/W=1/W=2/owned-RAM obligations. `INCOMPLETE` until authentic physical gate completion remains honest even after five RAM stages PASS. Do not edit top-level status or synthetic report to change that.
4. **`make test_full`**: separate integration, package/DKMS/systemd and RAM qualification; cannot replace actual media/real-swap evidence.
5. **`PHYSICAL_DEVELOPMENT_ONLY`**: specifically admitted, bounded real selected-partition test after separate consent. Positive exact lower WRITE/READ and Linux anonymous swap traffic, byte-oracle results and cleanup are scoped to the executed workload; never automatically production-qualified.
6. **Full physical production acceptance**: frozen source/run/target-qualified correctness, READ/WRITE, overwrite/reuse, GC and incompressible headroom, capacity/RAM, latency/CPU/PSI, fault and lifecycle acceptance under real host constraints. Do not promote an incompletely executed workload.
7. **Installed default and reboot**: only after separate authorized production deployment and exact installed source/artifacts, tested normal restore, healthy current active mapper and no dual swap; cold-boot observation requires an actual later **owner-initiated** boot. No autonomous reboot and no simulated cold-boot PASS.

Keep 4/8/16 KiB physical packing, LZ4 + delta64 rescue + `DELTA64_SHUF8`, RAW fallback, zero elision, CRC32C/generation authority, bounded RAM mapping/GC, ordered lower completion-before-publication, one upper BIO completion owner, failure atomicity and checked capacity. Preserve source ABI identities: module `dm-swapz.ko` (`dm_swapz`), Device Mapper target `swapz`, userspace tool `swapzctl`. Keep no on-media swapz metadata, no hibernation/resume support and original raw header immutability. No arbitrary tiny final mapper: full **safe** physical backing minus header/bad/GC/overflow/reserve is required for production.

For *unsafe* error injection use native production-C, sanitizers and owned RAM-backed `null_blk` models; do not corrupt live swap containing unknown application pages. Existing host `make test_full`/loaded tests must preserve correctness under concurrency, partial/failing I/O, DISCARD/flush/FUA, slot reuse, GC relocation, read-cache consistency, cancellation/retry, start/stop and IRQ/BIO lifetime races. Fail-only diagnostics should have original cause and safe cleanup disposition.

## H. Exact-source GitHub workflow, source/report ownership and concurrency

- Stay on canonical `main`; no PRs/extra worktrees/force pushes/history rewrites. Fetch and **fast-forward only at safe boundaries**; never pull/rebuild the source during a pinned test or active mapper transaction. Verify exact local/remote SHAs before starting an expensive run, and compare again after. Don't claim a past commit qualified a future one. If another agent advanced `main`, inspect its patch and tests rather than overwriting it or creating a conflicting duplicate fix.
- Publish a small **same-commit** production/test fix and applicable canonical standards with the repository's expected-head, nonforce path, after its focused tests. Preserve owner edits/untracked files. `test_results.json` is an intentional narrowly scoped cleanliness exception for physical source admission; its presence does **not** grant any broader dirty checkout exemption and is not by itself physical evidence.
- Check exact-source CI (not just the latest run for some other commit); green five workflows at `1eb69671` are a verified historical baseline. If CI reports a failure, inspect the **specific failed job/first fixture**; run its short rootless reproducer before editing code. Do not re-run rootless suites that already passed unaffected SHA solely because two hosts are available.
- `make test` source/report sync should be noninteractive, authenticated and bounded. Network/auth/push failure is reported separately from algorithm PASS/FAIL, with private evidence retained. No leaked tokens, altered global Git credentials, automatic git reset/stash or infinite retry. A report-only commit does not qualify another source revision; remote advancement after qualification is a freshness issue, not a reason to relabel historical result.
- Never implicitly commit **all** changed files in automation. An operator's requested `git add -A` shell one-liner is not a general Codex permission to stage secrets/unowned artifacts. Inspect diff/status and stage only reviewed code, tests, standards and intended report output; preserve owner work.
- Maintain a bounded integration plan. If current CI/source succeeds, **do not make speculative edits to get busy**. The next genuine gate is the host's read-only physical-plan/scope review and eventually an explicitly authorized bounded physical correctness run.

## I. Official first-cause reporting and strict privacy

At each failure, preserve the first causal stage, source SHA, class, expected/observed, original errno/exit or bounded counter, selected phase/round, cleanup/recovery and safe next action. Never let a later cleanup, log writer or Git push failure override the physical or test first cause. For a partial private raw traceback, keep the bytes in owner-only `build/tests` storage; do not spill machine IDs, source paths, arbitrary child stderr or raw memory into public JSON or console markers. Public relay fields require exact known schema, finite allowlists and class/method authentication.

The child stderr relay deliberately preserves the child's stderr **unchanged**. Privacy assertions apply to the **trusted rootless marker** and official aggregated report (not to the entire captured stderr stream). The previous `rootless-attribution-test.py` failure was an overbroad test expectation; do not “fix” it by censoring child stderr or weakening foreign-class classification. `test=unavailable` is correct when the only matching method belongs to an unexpected/foreign class.

Changes to diagnostics require source-bound rootless tests for missing optional telemetry, invalid/malformed values, duplicate/oversized/private fields, correct window-delta semantics, first failure precedence and original cleanup. Keep stdout/stderr semantics, file permissions and original exit codes. Make recipe shell variables/`$?` must be escaped correctly (`$$var`, `$$?`).

## J. Safe development-phase progress toward actual production

Once there is a **separately approved** real-swap trial, use only the verified existing development-mode helper and its exact source-bound builder/evidence path. After completing a single bounded trial:

- Confirm selected physical header and partition table were unchanged, exact owned mapper/module cleaned up, no foreign swap touched and original raw swap state restored if safely possible.
- Require positive Linux swap-out **and swap-in**, positive exact-mapper upper/lower WRITE **and READ**, byte-exact oracle over the required pages, repeatable slot reuse, no OOM or unresolved errors, and complete normal release before describing the trial as PASS. If it aborts on pressure or stalls during fill, it is FAIL with valuable diagnostics, not a successful real-swap test.
- Preserve original PSI stop, get same-window correlations, inspect time spent **before** the first five-second stop (the ~45-minute run duration is a separate performance/phase-time concern). Diagnose rather than immediately tuning memory caps, lowering workload demands or disabling controls.
- Only if bounded correctness is genuinely established should Codex propose the **next scoped** performance/GC/full-capacity/installation acceptance tests. Every physically consequential phase requires the relevant consent and protected native gate; don't generalize a development smoke or another host's green result.

### Final go/no-go requirements

`DEFAULT_SWAPZ_RECOMMENDATION=YES` and `CODE_PRODUCTION_READY=PASS` require all applicable **current-source, selected-host** native, rootless, official five-stage RAM, source-qualified physical, authentic real-swap READ/WRITE/byte correctness, memory/GC/latency/capacity, normal restore, production service, provenance and boot-plan evidence. A later real owner cold boot is still `NOT_OBSERVED` until it happens. Do not install/KEEP based solely on `make fast_test` or one bounded development physical trial. If any gate remains unqualified, answer `NO`/`NOT_YET` and preserve or safely restore ordinary original swap, reporting any uncertain recovery explicitly.

## K. Completion format — short, operational and precise

At meaningful milestones report the **verified** source and host, first failure, targeted tests, proof limits and one next safe action. Use `NOT_RUN`, `UNKNOWN`, `BLOCKED`, `INCOMPLETE` honestly; do not invent missing values.

```text
HOST=<x86-64-lubuntu|Inspiron1564Linux|other-authenticated-host>
CURRENT_SOURCE_SHA=<sha>
ACTUAL_TESTED_SOURCE_SHA=<sha-or-NOT_RUN>
REMOTE_MAIN_SHA=<sha-or-UNKNOWN>
NON_REPORT_SOURCE_CLEAN=<YES|NO|UNKNOWN>
EXACT_SOURCE_CI=<PASS|FAIL|IN_PROGRESS|UNKNOWN>
FOCUSED_TESTS=<passed/total-and-suite-or-NOT_RUN>
FAST_DEVELOPMENT_EVIDENCE=<PASS|FAIL|REUSED|NOT_RUN|BLOCKED>
OFFICIAL_FIVE_STAGE_EVIDENCE=<PASS|FAIL|INCOMPLETE|NOT_RUN>
DEVICE_IDENTITY=<PASS|FAIL|BLOCKED|NOT_CHECKED>
SHARED_ROOT_SCOPE=<PASS|FAIL|NOT_APPLICABLE|NOT_CHECKED>
PHYSICAL_OPERATOR_AUTHORIZATION=<PRESENT|MISSING|INVALID>
PHYSICAL_WRITE=<NOT_PERFORMED|AUTHORIZED_EXECUTED|BLOCKED>
ALGORITHM_REAL_SWAP=<PASS|FAIL|NOT_RUN|BLOCKED|RECOVERY_REQUIRED>
MEMORY_PSI_STOP=<TRIGGERED|NOT_TRIGGERED|NOT_OBSERVED>
BYTE_EXACT_SWAP_OUT_IN=<PASS|FAIL|NOT_RUN>
FIRST_FAILURE=<authenticated-stage/cause-or-NONE>
RECOVERY=<VERIFIED_ORDINARY_SWAP|BLOCKED|NOT_RUN|UNKNOWN>
UNRELATED_SWAP_PRESERVED=<YES|NO|UNKNOWN>
PRODUCTION_DEFAULT_SWAPZ=<YES|NO|NOT_YET>
NEXT_SAFE_ACTION=<one-small-executable-step-or-authorization-request>
```

A first error with private evidence should include the **repository-relative** path to the owner-only log, not its contents. For a source-only task, a short diff summary and focused test results are enough; don't demand the full device status template when no device was touched.

## L. First instructions to Codex at the next session

1. **Load the current repository source and the exact latest result.** Both hosts have reported clean passing 54/54 rootless attribution at `1eb69671`, and five exact-SHA CI groups passed at that commit. Verify whether newer `main`/CI has advanced; *do not rerun* those tests unless newer changes affect them.
2. **Default to the development pace:** identify one live blocker; run only the smallest safe reproducer; make one minimal standards-paired patch; rerun only affected rootless/native tests; publish safely to `main`; inspect exact-source CI. Do not automatically run `make test`, full 20-minute RAM qualification or 45-minute physical trial after a fixture fix.
3. **The next useful host action is read-only:** examine Lubuntu `/dev/sda4`'s current original raw swap/parent, `swapzctl primary plan`, protected shared-root-scope and safe diagnostics. If source/current CI is green, do not invent a new software change just to keep coding. Be alert that the ordinary `physical-swap-probe.py plan` enforces **official source qualification** and may report official `SOURCE_GATE=BLOCKED` even where the distinct development path can later be admitted.
4. **Stop before real mutation.** Draft the exact host/device/run scope and obtain the user's independent explicit authorization. Do not interpret this mission as a permanent blanket permission or skip preflight. The second host or any changed scope requires its own decision.
5. Once approved and all current gates re-pass, run at most one bounded existing development physical correctness trial on the authenticated selected device; the helper generates necessary development `fast_test` source evidence itself when not supplied. Preserve full telemetry and original ordinary swap recovery, then diagnose the first failure rather than immediately retrying.
6. Only after actual validated real-swap byte correctness should the project advance to expensive complete production qualification and a separately scoped default deployment decision. Keep frozen performance/pressure/ownership/identity gates and all genuine safety features intact.

**Success is not a green-colored summary; it is a trustworthy source-bound correctness result, independently authorized physical behavior, and safe normal operation. Fast progress is obtained by eliminating redundant tests and bad triage, never by omitting mandatory evidence or weakening a physical guard.**
