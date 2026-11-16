# Round 019 — verbatim original GitHub worker reports

These texts are preserved exactly from GitHub comments. Worker self-report and rootless suites alone cannot constitute genuine loaded/physical device evidence.

## [Agent 2 original REPORT_READY](https://github.com/k1moradi/swapz/issues/136#issuecomment-6920881186)

message: REPORT_READY
round: "019"
agent: 2
status: PUBLISHED_MAIN_SOURCE_READY_PENDING_EXACT_HOSTED_KUNIT
published_source_sha: 01edd17eed37efa312523324b1210efdd46be144
parent_sha: aed19172d3676896a53cb7857fe330242771023a
initial_round019_source_commit: aed19172d3676896a53cb7857fe330242771023a
initial_parent_sha: bcd88049f4b75c404b999d31ddc5816bcf8da839
branch: main
publication: NON_FORCE_EXPECTED_HEAD_FAST_FORWARD_VERIFIED
commit_url: https://github.com/k1moradi/swapz/commit/01edd17eed37efa312523324b1210efdd46be144
exact_hosted_kunit: https://github.com/k1moradi/swapz/actions/runs/43897628379

Agent 2's two sequential direct-main source commits cumulatively change ONLY:
- .github/workflows/phase-a-zswap-origin-kunit.yml
- tests/runtime/native/pinned-linux-zswap-origin-stage-test.py
- docs/handoff/zswapz/round019/agent2-evidence.md
- docs/testing_standards.md (distinct append-only Round 019 Agent 2 section; peer sections preserved)

Historical *first real failure*: https://github.com/k1moradi/swapz/actions/runs/43876402555 , original artifact https://github.com/k1moradi/swapz/actions/runs/43876402555/artifacts/14230122902. In enabled modified pinned Linux c339f4010dea8b0d754f84ace70cd1b089878ef8, actual compiled four object identities/digests, real `uml_kunit_exit=0`, `verify_uml_config_exit=0` preceded `result=FAIL first_failure_phase=capture_real_tap first_failure_exit=1`. No enabled TAP transcript was preserved; the five actual case outcomes remain UNKNOWN. Disabled profile was never executed. This was not an authenticated 5/5 PASS. Confirmed source cause: `run_checked` redirects each command to the same `$RUNNER_TEMP/origin-kunit-command.log` with `>`, and the succeeding config verifier truncates the just-run UML `--raw_output` stream before old `capture_real_tap` reads it.

Source implementation:
- Immediately after exit-zero genuine `run_checked uml_kunit` and before `run_checked verify_uml_config`, require the shared log is a nonempty regular non-symlink ≤8MiB; require a fresh nonexisting non-symlink per-profile `$evidence/$profile-kunit-output.log`.
- Copy exactly the original UML command's output bytes with `(umask 077; set -C; cat -- "$log" > "$captured")` (no-clobber exclusive creation); verify destination regular/non-symlink, nonempty ≤8MiB; store SHA-256 in the profile manifest and restrict permissions to 0400.
- Only then invoke effective config verification; after it may overwrite the *shared* log, re-verify the unchanged owned TAP bytes and SHA-256 as `phase=verify_captured_tap_identity`, before executing the ORIGINAL strict `--verify-kunit-tap "$captured"`. The final paired verifier independently reads TAP bytes, checks per-profile SHA, refuses identical/reused transcripts, wrong profile, object drift and forged PASS.
- No source modification to producer Linux, BIO, DM, codec, phase gates or existing strict five-case parser. Separate CONFIG_ZSWAP=y/n UML builds, real 4/3 object inventory, effective CGROUPS=n and conditional BLK_CGROUP, independent config/kernel/TAP hashes retained. Case labels required by original parser: `swap_bio_origin_authentication_test`, `swap_bio_origin_reset_reuse_reissue_test`, `swap_bio_origin_clone_test`, `swap_bio_origin_split_test`, `swap_bio_origin_merge_reject_test`.

Executed checks (actual results and important distinction):
- `bash -n /mnt/data/round019-agent2-local/actual-capture-excerpt.sh` EXIT 0; `bash -n /mnt/data/round019-agent2-local/actual-verify-excerpt.sh` EXIT 0 (source-extracted bounded Bash stages, NOT the complete workflow shell).
- `python3 -B -m unittest -v /mnt/data/round019-agent2-local/test_authentic_capture.py` EXIT 0: four methods PASS; two distinct profile filename captures; byte-for-byte preservation after shared log reuse; missing/empty/symlink/stale/oversize refusals; output post-capture SHA drift refusal; no synthetic KUnit PASS assertion. This is a local SOURCE-EXTRACTED execution harness, NOT exact imported committed source Python suite.
- `python3 -B -m py_compile /mnt/data/round019-agent2-local/test_authentic_capture.py` EXIT 0 (source-extracted fixture syntax only).
- GitHub Git diff inspection: exactly four owned files, 231 added lines, 0 added-line trailing-whitespace. No locally executed `git diff --check` because sandbox cannot resolve github.com and full checkout unavailable.
- GitHub direct-main `update_ref(branch=main,force=false,expected_sha=bcd88049...)` SUCCESS for the original commit, followed by another non-force expected-head fast-forward to 01edd17eed37efa312523324b1210efdd46be144, sole parent aed19172d3676896a53cb7857fe330242771023a; exact remote ref readback verified. No branch/PR/fork/worktree.
- Original exact-SHA hosted CI https://github.com/k1moradi/swapz/actions/runs/43897211201 FAILED in source-contract rootless tests before modified kernel execution. Corrected exact-SHA hosted CI https://github.com/k1moradi/swapz/actions/runs/43897628379 is IN_PROGRESS: both real enabled/disabled modified Kbuild and five-case KUnit TAP verification NOT_VERIFIED. The workflow itself invokes full committed `python3 -B swapz/tests/runtime/native/pinned-linux-zswap-origin-stage-test.py` and `python3 -B swapz/tests/runtime/native/pinned-linux-kunit-uml-config-test.py` before Linux staging; no fabricated local PASS.
- Original exact-SHA `Native kernel-C project-goal regressions` https://github.com/k1moradi/swapz/actions/runs/43897211307: repository policy, rootless production-readiness and rootless source-contract completed SUCCESS at last observation; new exact-SHA CI for 01edd17eed37efa312523324b1210efdd46be144 is https://github.com/k1moradi/swapz/actions/runs/43897628362, in progress.

Actual five-case TAP statuses:
enabled: authentication=NOT_VERIFIED, reset/reuse/reissue=NOT_VERIFIED, clone=NOT_VERIFIED, split=NOT_VERIFIED, mixed-origin merge reject=NOT_VERIFIED. KUnit case outcome remains UNKNOWN until source-linked TAP transcript passes.
disabled: all five=NOT_RUN/NOT_VERIFIED; profile execution pending exact-SHA hosted CI.
Neither kernel process exit nor synthetic output proves five-case success.

Qualification boundaries: loaded authentic pinned zswap stored-entry MM→BIO→DM WRITE=NOT_RUN; true byte-exact original uncompressed 4096-byte swap-in=NOT_RUN; owner physical trial=NOT_RUN; no system swap, physical devices, mapper, module insertion or memory-pressure actions. Phase A BLOCKED, Phase B RAW bypass DISABLED, direct compressed handoff DISABLED. Current swapz RAW is uncompressed original 4096-byte page.

ROUND019 source-linked first new CI failure and tested correction:
- On initial commit aed19172d3676896a53cb7857fe330242771023a, actual workflow run https://github.com/k1moradi/swapz/actions/runs/43897211201 job 133403912605 FAILED at `run_checked rootless`, before full pinned Linux source staging. Exact committed Python test suite: 33 methods executed, 32 PASS, 1 FAIL; `test_round019_workflow_capture_negative_mutations` expected ValueError when deleting `[[ "$(wc -c < "$log")" -le 8388608 ]]` but original source contract did not require it. Other 32, including actual Bash-executed new capture and immutable-drift regressions, passed in GitHub hosted runner. First actual CI error was `AssertionError: ValueError not raised`; not a KUnit TAP or Linux compilation result.
- Follow-up actual main commit 01edd17eed37efa312523324b1210efdd46be144, parent aed19172d3676896a53cb7857fe330242771023a, changes `pinned-linux-zswap-origin-stage-test.py`, Agent2 evidence note, and standards note. Source contract now explicitly requires exactly ONE input 8MiB bound and TWO destination 8MiB bounds, and negative tests remove either. Bash capture implementation and five-case KUnit acceptance are unchanged. Published by non-force expected-head update with exact HEAD readback.
- After follow-up, `python3 -B -m unittest -q /mnt/data/round019-agent2-local/test_authentic_capture.py` EXIT 0 (4/4) and Bash snippets syntax EXIT 0; GitHub source diff has zero added-line trailing whitespace. The local checks remain source-extracted fixtures only. Exact follow-up hosted KUnit https://github.com/k1moradi/swapz/actions/runs/43897628379 is IN_PROGRESS at report update, so genuine enabled=NOT_VERIFIED and disabled=NOT_VERIFIED.

MAIN_WRITE_LEASE_RELEASED

---

## [Agent 4 original REPORT_READY](https://github.com/k1moradi/swapz/issues/136#issuecomment-6920968771)

message: REPORT_READY
round: "019"
agent: 4
task_id: agent4-swap-slot-release-lifetime
status: PUBLISHED_MAIN_SOURCE_READY_PENDING_FULL_NATIVE_CI
published_main_sha: 5a54657b25f66269b90d22deca69abe2c2fc9501
source_commit_url: https://github.com/k1moradi/swapz/commit/5a54657b25f66269b90d22deca69abe2c2fc9501
sole_parent_sha: 01edd17eed37efa312523324b1210efdd46be144
task_publication_sha: bcd88049f4b75c404b999d31ddc5816bcf8da839
frozen_round018_engineering_sha: 0008e6499c808b7e20775effeaacf16b087a183f
historical_owner_physical_sha: 9ecb5cc650cc9be9f4efe2bf38c9e3c91f620fa0
branch: main
publication: GitHub Git Data + non-force update_ref(expected_sha=01edd17...,force=false); verified remote main readback=5a54657b25f66269b90d22deca69abe2c2fc9501
no_new_branch_or_pr: true
physical: NOT_RUN
loaded_genuine_zswap_bio_dm: NOT_RUN
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED
evidence_note: https://github.com/k1moradi/swapz/blob/5a54657b25f66269b90d22deca69abe2c2fc9501/docs/handoff/zswapz/round019/agent4-evidence.md

## Implemented actual source and tests

Eight **real committed** files (GitHub compare: one descendant commit, +764/-12 across all files; added-line whitespace inspection 0 errors):
- `tests/tools/qualify-primary-real-swap.py`: preserve exact original 30s conjunctive cgroup-zero and pinned mapper Used=baseline gate, immutable baseline and 50ms poll. Fail closed if an owned oracle PID still appears in the dedicated cgroup after the unchanged five-second cleanup bound or if membership cannot be read; prior implementation could return without positive worker-removal proof. On release timeout cache last and previous numeric sequential counter samples with elapsed usec from gate start, original baseline, round index and proven zero owned workers, classify observed finite states; keep old `release_observation` last-sample API. No new pressure, mkswap, swapon or recovery behavior.
- `tests/tools/physical-swap-probe.py`: independently validate and redact optional finite `release_lifetime`, preserve first-source-error vs secondary cleanup exceptions, route known worker teardown refusal through `oracle_cgroup_ownership`, retain previous `swap_slot_release` mapping.
- `tests/tools/run-tests.py`: strict optional release-lifetime schema; reject booleans, negative/overflow, non-monotonic/missing, stale beyond 30-second window, contradictory clean baseline, mismatched legacy `release`, wrong class, private extra fields, source/gate mismatch; show bounded class-specific **non-mutating** next step in official failed `make test` console without leaking raw errors. No fabricated PASS or overwritten first exit.
- `tests/runtime/native/primary-real-swap-test.py`: actual-source rootless test cases for simultaneous clean pair, cgroup-only, mapper-only, both-positive, inconsistent/oscillating pairs, no first sample, malformed/false counters, missing/below-baseline mapper, guard/PSI/OOM early stop, cleanup-before-release ordering, stuck/exited worker and unreadable cgroup refusal; legacy timer mock updated for the new initial monotonic timestamp.
- `tests/runtime/native/physical-swap-probe-test.py`: exact first-error-over-cleanup, multiple typed two-snapshot cases, redaction, unknown/error/overflow/negative booleans, no-sample marker.
- `tests/runtime/native/test-report-test.py`: exact JSON and class consistency, malformed/private mutations, synthetic official algorithm-tier physical FAIL with original exit **3** and mode-0600 private log path retained; no leaked private child stderr.
- `docs/testing_standards.md`: separate unique `Round 019 — Agent 4: swap-slot release lifetime and worker-teardown proof` appendix, appended to current main; preserved BOTH Agent2's initial Round019 TAP standard and Agent2's follow-up bounded-input addition.
- `docs/handoff/zswapz/round019/agent4-evidence.md`: tracked first cause, explicit test limits and non-mutating owner checklist.

## Actual historical first failure

On previous owner source `9ecb5cc...` the real first original exception is now identified by the owner as:

`swap slots did not return to baseline within the bounded release timeout`

Source `qualify-primary-real-swap.py::_wait_for_round_release`. **Underneath, whether cgroup swap charge, mapper Used, both or unsynchronized counters remained positive is UNKNOWN**: old first numerical samples were not supplied. Owner earlier reported complete recovery/restored ordinary swap/header/mapper/module; not revalidated here. The new terminal/release diagnostics have NOT been used in a real owner physical trial. No assertion of kernel, swapz codec, zswap producer, corruption or physical acceptance is justified. The exact 4KiB page oracle and positive I/O/PSI/cgroup OOM/ownership gates remain intact.

Distinct source-backed bug fixed: when child `poll()` returned but its PID remained in `cgroup.procs` beyond five seconds (or that membership read failed), original `_terminate_child` returned without positively proving worker removal; release could proceed. Updated source raises QualificationFailure and the surrounding cleanup error barrier prevents any release/PASS.

## Measured commands/results; do not upgrade excerpt to imported suite

Local DNS/checkout:
`git ls-remote https://github.com/k1moradi/swapz.git HEAD` — **exit 128**, `Could not resolve host: github.com`; no complete source checkout was mounted.

Isolated rootless source excerpts with mocked in-memory cgroup/mapper/worker data (NOT full repository imports):
1. `python3 -m py_compile /mnt/data/swapz-agent4-round019/slot_release_source_excerpt.py` — exit **0**.
2. `python3 -B /mnt/data/swapz-agent4-round019/slot_release_source_excerpt.py -v` — exit **0**, **4/4** methods, 6 two-sample class/subcases plus simultaneous zero, early guard/malformed and no-sample timeout. SHA256 `1d4b60b1ce9304d068f71785a58534494a6e4c5abcc7c4ab07b2487c4bcaf391`.
3. `python3 -m py_compile /mnt/data/swapz-agent4-round019/worker_teardown_source_excerpt.py` — exit **0**.
4. `python3 -B /mnt/data/swapz-agent4-round019/worker_teardown_source_excerpt.py -v` — exit **0**, **3/3** methods: retained PID, unreadable membership and unrelated worker. SHA256 `937552527b3b278767183de3aa56d27f67fab14d61602b732d69778ad426b9be`.
5. `python3 -m py_compile /mnt/data/swapz-agent4-round019/lifetime_report_source_excerpt.py` — exit **0**.
6. `python3 -B /mnt/data/swapz-agent4-round019/lifetime_report_source_excerpt.py -v` — exit **0**, **2/2** methods; six known classes/missing samples and 16 invalid/private cases. SHA256 `3da3efdbd45d7c97cb6f7b5f7e6d7356835a202827cae201e794d22e65dea14f`.

GitHub commit diff `01edd17...5a54657`: **ahead 1**, exactly 8 owned paths, no trailing whitespace in 764 added diff lines. GitHub sole parent/rebased Agent2 history verified; remote `main` readback equals actual source SHA.

**NOT_RUN locally**: complete source-imported `python3 -B tests/runtime/native/primary-real-swap-test.py -v`, `physical-swap-probe-test.py -v`, `test-report-test.py -v`, full Python production source import/py_compile, local `git diff --check` in real checkout. Do not claim these passed. At report time exact-SHA hosted CI runs were queued/in progress, not yet accepted; Agent1 should verify actual source rootless and CI failure attribution before round close. No authorized physical device, cgroup pressure, kernel load, module/mapper, swapon/swapoff/mkswap or physical Linux swap operation was performed.

## Non-mutating next owner checklist

Before ANY separately approved future physical trial, first review the retained mode-0600 first failure evidence, verify reported recovery COMPLETE and unchanged SWAPSPACE2 header/ordinary swap inventory with no retained mapper/module/owned cgroup. Inspect last/previous cgroup `memory.swap.current`, mapper `/proc/swaps Used KiB` vs immutable pinned baseline, `memory.events` oom/oom_kill, `memory.pressure full`, worker terminal exit/EOF and cleanup status. These non-atomic independent observations cannot attribute page ownership. Unknown or inaccessible evidence stays BLOCKED; this is NOT a request to rerun a physical trial. Existing RAW remains original uncompressed 4096-byte page, forced Phase B RAW and direct compressed handoff DISABLED.

No peer wait, no branch/PR/worktree, no force push or rewrite of Agent2's published history. Agent1 owns exact-SHA rootless/hosted CI acceptance and round closeout.

