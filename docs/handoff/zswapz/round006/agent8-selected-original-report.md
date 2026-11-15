message: REPORT_READY
round: "006"
agent: 8
task_id: agent8-pinned-linux-clang-config-build
status: SOURCE_READY_PENDING_COORDINATOR_CI
source_sha: 47a793c1480556c075f23ecbe13a5b465d616916
task_commit_sha: 1f0a90621d1ade5ee1d115bc5d96c72c38e8f2f9
source_commit_sha: 528a0616363732cc4ec0d975728ea8ba44e1bab7
source_commit_url: https://github.com/k1moradi/swapz/commit/528a0616363732cc4ec0d975728ea8ba44e1bab7
source_parent_sha: 47a793c1480556c075f23ecbe13a5b465d616916
modified_files:
  - .github/workflows/phase-a-linux-source-preflight.yml
  - docs/testing_standards.md
evidence_class: rootless-source-validation
qualification: BLOCKED_CI_PENDING_COORDINATOR
tests:
  - command: "python3: PyYAML safe_load of the extracted complete added job under jobs:"
    exit_code: 0
  - command: "bash -n for all three added run: scripts extracted from the YAML job"
    exit_code: 0
  - command: "python3: independent/no-needs, bounded runtime, original GCC job preserved, no trailing whitespace checks"
    exit_code: 0
  - command: "bash -c extracted Kbuild script with LLVM_SUFFIX=invalid in a disposable temporary directory"
    exit_code: 2
    expected: "invalid-settings refusal and first_failure_phase=verify_prerequisites"
  - command: "bash -c extracted Kbuild script with LLVM_SUFFIX=-18 but missing local clang-18 executable"
    exit_code: 1
    expected: "missing-toolchain refusal and first_failure_phase=verify_prerequisites"
  - command: "GitHub compare 47a793c1...528a0616 and fetch source commit/file blobs"
    exit_code: 0
  - command: "GitHub Actions pinned Linux CONFIG_ZSWAP=y/n LLVM source object build"
    exit_code: NOT_RUN
blocking_findings:
  - "No local full pinned Linux source checkout and no clang-18 toolchain; real LLVM Kbuild cannot be claimed from static validation."
  - "Unreferenced source commit does not trigger GitHub Actions; Agent 1 alone publishes to main and validates the exact integrated SHA."
  - "No matched patched MM producer, loaded module, actual stored-entry zswap writeback or byte-exact mapper readback."
next_round_recommendations:
  - "Agent 1 integrate the owned workflow addition and uniquely titled standards appendix, alongside Agent 7's independent changes without overwriting either."
  - "Inspect independent LLVM job's enabled/disabled manifest and real full-source output after an exact-SHA hosted run, even if GCC linked-module job fails."
  - "Keep Phase A and Phase B blocked until separate authenticated MM/BIO/DM and safety gates complete."

# Agent 8 — Round 006 independent LLVM/Clang pinned-source implementation

**Outcome:** Actual tracked-file code committed as an unreferenced, retrievable Git source object. **Not a real Linux Clang Kbuild PASS.** Agent 8 did not update remote main, create a branch/PR/worktree/fork, modify Agent 7's fixture, or operate a mapper, kernel, swap device or physical backing.

## Source identity and exact scope

- **Frozen source parent:** [47a793c1480556c075f23ecbe13a5b465d616916](https://github.com/k1moradi/swapz/commit/47a793c1480556c075f23ecbe13a5b465d616916)
- **New retrievable source commit:** [528a0616363732cc4ec0d975728ea8ba44e1bab7](https://github.com/k1moradi/swapz/commit/528a0616363732cc4ec0d975728ea8ba44e1bab7).
- **Upstream Linux:** unchanged, read-only torvalds/linux commit `c339f4010dea8b0d754f84ace70cd1b089878ef8`.
- GitHub compared new commit against its frozen parent: **exactly 2 modified paths**, 232 added workflow lines and 53 added testing-standards lines; **zero deletions**. The original `pinned-upstream-checkout` GCC/linked-module job remains unchanged. The new `pinned-upstream-clang-objects` job is independent: no `needs` relationship and its own runner, checkout, temporary build directories, failure manifests and always-upload artifact.

## Implemented behavior

1. **Read-only complete Linux checkout:** `actions/checkout@v4` at the exact upstream SHA, depth 1, `persist-credentials: false`, common read-only `contents: read` permissions; checks the actual SHA, clean original source tree, >=50,000 tracked files and required real Linux sources.
2. **Toolchain identity:** installs Ubuntu `clang-18`, `lld-18` and `llvm-18` plus bounded Linux host prerequisites; verifies required version-suffixed executables, records exact package versions, `clang-18` and `ld.lld-18` version lines and SHA-256 of both binaries. Invokes actual kernel Make with `LLVM=-18`, not GCC fallback. This pins the tool major; runner package revisions are recorded rather than falsely claimed bit-for-bit static.
3. **Two effective configurations:** fresh separate `O=` directories; `defconfig`, Linux's own `scripts/config`, `olddefconfig`; refuses any fallback away from `CONFIG_SWAP=y`, requested `CONFIG_ZSWAP=y/n` or `CONFIG_CC_IS_CLANG=y`. Rechecks compiled auto.conf and compiler text after `prepare`.
4. **Actual LLVM Kbuild targets:** bounded `-j4 W=1` compile of `mm/page_io.o block/bio.o` for both profiles, plus `mm/zswap.o` only for enabled; rejects missing/empty required objects or disabled profile unexpectedly producing `mm/zswap.o`; records exact shell-escaped commands and exits, config SHA-256, per-object SHA-256 and clean-source status.
5. **Truthful failure evidence:** per-profile text files initialized as NOT_RUN before checkout, preserved through `if: always()` with no large build artifacts. The first unsuccessful command or warning is reported with phase and exit; only the last 25 output lines are printed when a failure occurs. Compiler warnings are not suppressed or silently treated as clean PASS; the job fails conservatively if observed. The build never requests `vmlinux`, `Module.symvers`, external module linking, kernel installation/loading, KUnit, active swap or physical devices.

The change therefore provides a separately executing **`LLVM_STOCK_SOURCE_OBJECT_KBUILD`** qualification lane and cannot inherit a false PASS from the original GCC job.

## Tests actually run (local, NOT hosted Linux Kbuild)

| Check | Exact input / command class | Result |
|---|---|---|
| YAML parser | `yaml.safe_load("jobs:\n" + added_job_text)` using PyYAML 6.0.3 | **PASS** |
| Shell syntax | `bash -n` separately on all **3** added `run:` blocks | **PASS** |
| Structural assertions | No `needs`, 45-minute timeout, independent checkout+upload, `CONFIG_CC_IS_CLANG=y`, bounded `LLVM=-18 W=1 -j4`, required targets and zero added trailing-whitespace lines | **PASS** |
| Negative setting | Disposable `bash -c` of added source script with `LLVM_SUFFIX=invalid` | **Expected refusal, exit 2**; first-failure manifest checked |
| Negative missing toolchain | Same script with `LLVM_SUFFIX=-18` but unavailable local `clang-18` | **Expected refusal, exit 1**; first-failure manifest checked |
| Committed source verification | GitHub commit fetch, compare, fetch both blobs and validate added job/appendix | **PASS**; both bytes retrievable |
| Actual Clang/Linux object build | Runner checkout and Kbuild for both effective profiles | **NOT_RUN**, needs Agent 1's direct-main publication and hosted CI |

The local environment cannot fetch the upstream Linux source tree or install/use the pinned LLVM-18 toolchain. No linked artifact, KUnit, CONFIG_ZSWAP kernel object, hosted YAML run, loaded module or physical measurement has been manufactured as a success claim.

## Coordinator integration handoff

**Agent 1 should merge only these exact two owned changes:** the added independent `pinned-upstream-clang-objects` job and the uniquely titled `Round 006 independent pinned Linux Clang source Kbuild` section. Integrate the independently owned Agent 7 appendix without dropping either; preserve the unchanged original GCC job and published round source provenance. Then trigger the actual workflow by a focused permitted direct-main update, inspect real y/n artifacts and first failure before assigning any LLVM compile PASS. If GCC's lengthy `vmlinux`/external-module job fails, the new Clang job must still execute and return its own qualified outcome. It is an object-only, **stock Linux** test, not a patched BIO carrier or production module qualification.

**Release:** Phase A remains BLOCKED pending authenticated Linux stored-entry writeback through MM/BIO/DM and exact readback. Phase B RAW bypass remains DISABLED.