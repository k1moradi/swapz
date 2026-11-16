# Round 018 — original GitHub worker reports and intermediate Agent 4 source update

Worker assertions and original GitHub text are archived verbatim. Do not infer loaded kernel/physical PASS or extrapolate any tests not executed.

## [Agent 4 intermediate first-cause/source update](https://github.com/k1moradi/swapz/issues/135#issuecomment-6917785273)

message: SOURCE_UPDATE
round: "018"
agent: 4
task_id: agent4-physical-workload-producer-refusal
source_sha: cf49aec222c474a4b59ca06b8757ee7e2e177789
physical: NOT_RUN
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED

Owner supplied the previously unavailable retained private stage log for tested `9ecb5cc650cc9be9f4efe2bf38c9e3c91f620fa0`. Exact first failure: `swap slots did not return to baseline within the bounded release timeout` from `tests/tools/qualify-primary-real-swap.py::_wait_for_round_release`, not generic `producer_refused`. The failing release gate requires dedicated cgroup `memory.swap.current == 0` AND mapper `/proc/swaps Used` exactly at the authenticated fixed baseline within 30 s. Evidence does not reveal which counter stayed high or why. Owner reported COMPLETE ordinary swap restoration and preserved header; no new physical run was authorized or performed.

Published narrow direct-main non-force fast-forward [cf49aec](https://github.com/k1moradi/swapz/commit/cf49aec222c474a4b59ca06b8757ee7e2e177789) (parent `37de56d2`): source-defined `swap_slot_release` reason, last independent identity-free cgroup/mapper accounting snapshots, first-cause-preserving exception chaining, strict official marker parse and automatic safe console output, rootless negatives, and separate Round 018 Agent 4 testing standards. No change to 30 s deadline, fixed baseline, byte oracle, ownership, PSI/OOM, device I/O or recovery. No kernel/codec modifications.

Hosted exact-commit [rootless physical adversarial audit](https://github.com/k1moradi/swapz/actions/runs/43875822125) PASS; [native/rootless CI](https://github.com/k1moradi/swapz/actions/runs/43875822004), [static](https://github.com/k1moradi/swapz/actions/runs/43875822078), [systemd/package](https://github.com/k1moradi/swapz/actions/runs/43875822021), and [production C](https://github.com/k1moradi/swapz/actions/runs/43875822020) were still in progress as checked. **This is a source update, not final REPORT_READY or physical qualification.**

---

## [Agent 2 full REPORT_READY](https://github.com/k1moradi/swapz/issues/135#issuecomment-6917857728)

message: REPORT_READY
round: "018"
agent: 2
status: SOURCE_PUBLISHED_MAIN; HOSTED_PINNED_KUNIT_IN_PROGRESS; PHASE_A_BLOCKED
published_source_sha: d623a3c156ff390299f32a6ca2b9891e944bb3d6
sole_parent: cf49aec222c474a4b59ca06b8757ee7e2e177789
publication: NON_FORCE_EXPECTED_HEAD_VERIFIED
main_commit: https://github.com/k1moradi/swapz/commit/d623a3c156ff390299f32a6ca2b9891e944bb3d6

Actual source-controlled Agent 2 change, independently rebased/reconciled after Agent4 published cf49aec222c474a4b59ca06b8757ee7e2e177789:
- tests/runtime/native/pinned-linux-kunit-uml-config-test.py
- .github/workflows/phase-a-zswap-origin-kunit.yml
- docs/handoff/zswapz/round018/agent2-evidence.md
- docs/testing_standards.md (unique append-only Round 018 Agent2 section, Agent4's preceding distinct section preserved)
GitHub diff confirms these FOUR changed paths and one parent on main. GitHub `update_ref(main,force=false,expected_sha=cf49aec...)` returned success; exact remote HEAD readback equals d623a3c..., no PR/branch/worktree/force update.

Original real first failure: pinned Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8` run https://github.com/k1moradi/swapz/actions/runs/43860358473 , job 133275255387, `verify_uml_config_exit=1`, first diagnostic `effective-CONFIG_BLK_CGROUP:expected=n:actual=MISSING`. The real enabled modified-object builds and UML kunit.py process returned 0; the strict five-case TAP check was NOT reached and disabled y/n profile was not completed. No claim of KUnit PASS.

Proven pinned dependency: `init/Kconfig` at exact pinned Linux commit opens `if CGROUPS` line 866, declares `config BLK_CGROUP` inside at line 921 with `depends on BLOCK` and `default n`, closes `endif # CGROUPS` at line 1203. Kconfig may legitimately suppress the BLK_CGROUP-disabled child from *effective* .config when `CONFIG_CGROUPS=n`. The `--request` remains obligated to explicitly disable BOTH CGROUPS and BLK_CGROUP; this does NOT generalize omission for any other required flag. No bypass of active y/m child/parent, duplicate/malformed config, wrong zswap profile or reused evidence.

Implementation: a single `verify_effective_config()` checks required options and permits ONLY the absent BLK_CGROUP child with effective CGROUPS=n. Used in both `check_config` and final `verify_pair`. Actual workflow removes stale `grep -Fxq '# CONFIG_BLK_CGROUP is not set' ...` and after Python's full gate retains a fail-only y/m-child guard; exact `CGROUPS=n` grep remains. Existing strict 3/4 compiled object SHA inventory, pinned Linux source hashes, distinct y/n Kconfig and five executed no-skip genuine TAP cases remain mandatory.
New Python source-controlled regressions: explicit/present and omitted child for both profiles; wrong/missing parent, wrong/omitted request, y/m child, missing required swap/zswap, malformed/duplicate/symlink/oversized; final paired-gate positive suppressed child and forged parent/child/swap with recomputed .config digest; workflow guard contract. Existing TAP skip/double-count and object-drift negatives retained.

Actually executed local tests/commands:
- `python -B /mnt/data/round018-agent2-local/source-extracted-gate-test.py` : EXIT 0, 4/4 unittest methods PASS; subtests cover y/n suppression, explicit disabled child, wrong parent, forced/missing child, required option suppression, duplicate/malformed/mixed-case. This is an ISOLATED source-extracted smoke harness, NOT full committed verifier execution or upstream KUnit.
- `python -B -m py_compile /mnt/data/round018-agent2-local/source-extracted-gate-test.py`: EXIT 0, isolated fixture only.
- `bash -n /mnt/data/round018-agent2-local/postgate.sh`: EXIT 0 (source-extracted Bash postgate).
- `bash .../postgate.sh .../suppressed.config`: EXIT 0; `bash .../postgate.sh .../activated.config`: EXIT 1 as required, y-child rejected.
- GitHub source-blob exact patch inspection: 214 added lines, 0 added-line trailing-whitespace, ahead-by=1/behind-by=0 and 4 owned paths. This is NOT a locally executed `git diff --check`.
- Full committed `python3 -B tests/runtime/native/pinned-linux-kunit-uml-config-test.py` and `python3 -B tests/runtime/native/pinned-linux-zswap-origin-stage-test.py`, full workflow YAML/Bash, `git diff --check`, pinned Linux Kbuild and real UML KUnit y/n: NOT_RUN locally (no local swapz main checkout; git ls-remote failed due github.com DNS in sandbox). The exact pushed GitHub Actions workflow itself invokes both rootless modules and y/n Kbuild/KUnit. Do not conflate extracted fixtures with their execution.
- Exact committed main SHA GitHub pinned KUnit run: https://github.com/k1moradi/swapz/actions/runs/43876402555 , job 133330487114, IN_PROGRESS (last observed step 'Install Kbuild/UML dependencies'). Neither 5 executed TAP cases for enabled nor disabled profile has yet been witnessed; `hosted_KUnit_y=IN_PROGRESS`, `hosted_KUnit_n=NOT_RUN`. Verify authoritative result from run artifact, and fix any new genuine first failure rather than bypass the verifier.

Safety: loaded authenticated zswap stored-entry MM→BIO→DM committed WRITE, exact original 4096-byte swap-in, host swap, physical backing and pressure tests all NOT_RUN/NOT_AUTHORIZED. Phase A BLOCKED; Phase B RAW bypass DISABLED; compressed direct handoff DISABLED; current swapz RAW means full original UNCOMPRESSED 4096-byte page. No peer wait, no live device actions.
MAIN_WRITE_LEASE_RELEASED


---

## [Agent 4 full REPORT_READY](https://github.com/k1moradi/swapz/issues/135#issuecomment-6917892870)

message: REPORT_READY
round: "018"
agent: 4
task_id: agent4-physical-workload-producer-refusal
status: SOURCE_PUBLISHED_PENDING_FULL_CI
published_main_sha: 0008e6499c808b7e20775effeaacf16b087a183f
commit_url: https://github.com/k1moradi/swapz/commit/0008e6499c808b7e20775effeaacf16b087a183f
parent_sha: d623a3c156ff390299f32a6ca2b9891e944bb3d6
original_physical_source_sha: 9ecb5cc650cc9be9f4efe2bf38c9e3c91f620fa0
task_publication_sha: 37de56d28af54003954d8b0214fd15baf397bf11
report_issue: https://github.com/k1moradi/swapz/issues/135
evidence_note: https://github.com/k1moradi/swapz/blob/0008e6499c808b7e20775effeaacf16b087a183f/docs/handoff/zswapz/round018/agent4-evidence.md
branch_policy: main only, no PR/branch/worktree/force
publication: GitHub Git Data commit + update_ref(main,force=false,expected_sha=d623a3c156ff390299f32a6ca2b9891e944bb3d6), verified readback main=0008e6499c808b7e20775effeaacf16b087a183f
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED
physical_trial: NOT_RUN

## Agent 4: actual source commit and first-cause findings

**Published current-main source:** [0008e6499c808b7e20775effeaacf16b087a183f](https://github.com/k1moradi/swapz/commit/0008e6499c808b7e20775effeaacf16b087a183f). Parent `d623a3c156ff390299f32a6ca2b9891e944bb3d6`; GitHub verified one-commit fast forward, correct ref on readback.

**Six actual committed files, no production kernel/codec/Makefile changes:**
1. `tests/tools/physical-swap-probe.py` (+136/-4): exact, <=768-character source-owned terminal oracle first-cause classifier; `oracle_child_exit`, `oracle_timeout`, `oracle_transport`, `oracle_protocol`, `oracle_cgroup_ownership`, `cgroup_swap_limit`, true producer-defined known OOM/READ/WRITE/data-integrity categories; optional event and bounded child exit; secondary cleanup errno does not overwrite missing original errno; unknown remains `producer_refused`.
2. `tests/tools/run-tests.py` (+49/-1): strict all-or-nothing optional `oracle` schema (only `expected_event` and signed bounded `child_exit`), exact phase/gate/reason, reject private extra fields and contradictory event/exit; safe human first-cause and no-rerun guidance while retaining original physical exit and 0600 private log. Preserve existing `swap_slot_release`/release and pressure validation.
3. `tests/runtime/native/physical-swap-probe-test.py` (+96): 20 source-bound positive/negative oracle/cgroup/IO/privacy scenarios, including code 1/2, -9, running timeout, signal, transport errno, malformed summary, unknown/private strings and secondary cleanup errno refusal. The initially missed contradictory `running` + `exited before` case is now committed.
4. `tests/runtime/native/test-report-test.py` (+112/-1): exact optional marker parsing, invalid/overflow/boolean/private-field rejection, private 0600 log retention, and synthetic official `make test` negative path preserving original nonzero exit and bounded console.
5. `docs/testing_standards.md` (+42): separately titled `Round 018 — Agent 4 terminal-oracle producer refusal extension`, appended without deleting either earlier Round 018 Agent4 slot-release block or Agent2 KUnit section.
6. `docs/handoff/zswapz/round018/agent4-evidence.md` (+25): this source-bound evidence and limitations.

**Reconciliation of concurrent `main`:** After task publication `37de56d2`, two legitimate changes landed: `cf49aec2` (Agent4 separate source-owned swap-slot release timer diagnosis, affected some same files) and `d623a3c1` (Agent2 KUnit config and standards). I rebuilt the unpublished tree atop **d623a3c1**, explicitly retained the source/readouts/release schema/tests from `cf49aec2`, appended a distinct testing-standard section atop Agent2's addition, and performed a single non-force expected-head update. Neither prior published commit was rewritten or overwritten.

### Measured rootless tests and first failure

- `git ls-remote https://github.com/k1moradi/swapz.git HEAD` in local container: **exit 128**, DNS resolution of github.com unavailable. No full local repository checkout was available. GitHub connector successfully created/read back exact Git blobs/tree/commit/ref.
- `python3 -B /mnt/data/swapz-agent4-round018/oracle_first_cause_excerpt_test.py -v` initial implementation: **exit 1**. First negative showed a logical misclassification: `child_exit=running` paired with producer text `exited before ORACLE_WAITING=` was accepted as transport. This was **corrected** by requiring a real integer child status for source-defined `exited before` and committed as a negative fixture.
- Rerun after fix of **self-contained exact-pattern excerpt**, NOT full imported production module: **exit 0**; 2 unittest methods / 26 positive and negative subcases (14 positive, 12 invalid). Excerpt SHA-256 `54d2686a658228127465c83e4cfc035a5216a8e2c4ac9ae10b13d9c59421db06`.
- `python3 -m py_compile /mnt/data/swapz-agent4-round018/oracle_first_cause_excerpt_test.py`: **exit 0** (excerpt-only syntax).
- GitHub compare `d623a3c1...0008e649`: **ahead=1**, exactly six permitted paths, +460 Git-added lines and zero added trailing whitespace. This is source diff inspection, **not** local `git diff --check` on the complete checkout.
- Exact **full Python syntax, rootless** `python3 -B tests/runtime/native/physical-swap-probe-test.py -v`, `python3 -B tests/runtime/native/primary-real-swap-test.py -v`, `python3 -B tests/runtime/native/test-report-test.py -v`, `git diff --check` in the real checkout, exact integrated hosted CI: **NOT_RUN / pending qualification**. These claims must not be upgraded to native-suite PASS until exact source checks run.
- `make test`, loaded module, cgroup pressure, mapper, kernel swap, ordinary partition, `mkswap`, `swapon`, `swapoff` or any physical trial: **NOT_RUN**, deliberately prohibited by the assignment.

### Distinction between verified mapping gap and unknown owner error

The owner's previous source `9ecb5cc6` reported physical FAIL after 171.19 seconds at `anonymous_workload/bounded_primary_workload/producer_refused`; reported normal recovery restored original SWAPSPACE2 and ordinary swap. **The actual host first exception, code path and errno are unknown because private root-only evidence was not supplied.** An observed worker status 1/2/-signal does not prove an OOM, codec issue, zswap kernel bug, page corruption or correct 4096-byte readback. The new classifier only recovers source-defined reason/child status when its anchored exact envelope is present; arbitrary stderr is never promoted and original failure/cleanup stays nonzero.

**Agent1 acceptance gate:** Run full three relevant rootless Python fixture suites plus source-bound CI and local `git diff --check` on integrated main, reviewing this source and previous published slot-release/KUnit changes. Keep result RED if first source-owned assertion fails. No further owner physical attempt until prior private first-cause evidence/recovery is independently reviewed.

No branches, PRs, worktrees, force-pushes, installed modules or device mutations. Phase A BLOCKED, Phase B RAW and direct compressed bypass DISABLED; current swapz RAW remains the original uncompressed 4096-byte page.

