# Round027 — exact original GitHub reports and source updates

Original public GitHub issue: https://github.com/k1moradi/swapz/issues/144 . These comments are copied from the actual GitHub issue in their retrieved order. Intermediate PENDING and historical FAIL statuses remain historical; the independent integrated final conclusion is in round-report.md. This report archive is an immutable source-bound record and not a new worker message.

## Original comment 1 — https://github.com/k1moradi/swapz/issues/144#issuecomment-6944314230

```text
message: REPORT_READY
round: "027"
agent: 3
status: ROOTLESS_OFFLINE_ORIGINAL_SOURCE_EVALUATOR_AND_FIRST_ERROR_NEGATIVE_TESTS_PASS; OWNER_PHYSICAL_FIRST_CAUSE_UNDETERMINED; NO_LIVE_DEVICE
frozen_task_sha: 5da826bdcfbc358ed80814afb0ca19d46ac23806
published_main_sha: 87c171ac6f1dea504e452e7fa598750614b9a978
sole_parent_sha: 5d2aff0bb37e0811b163267b8e9bda6f9f4b127c
publication: NON_FORCE_EXPECTED_HEAD_FAST_FORWARD_DIRECT_MAIN; REMOTE_READBACK_VERIFIED
own_commit: https://github.com/k1moradi/swapz/commit/87c171ac6f1dea504e452e7fa598750614b9a978
actual_exact_sha_ci: https://github.com/k1moradi/swapz/actions/runs/44057261033
actual_hosted_job: 133949701416 (COMPLETED SUCCESS)
source_evidence: https://github.com/k1moradi/swapz/blob/87c171ac6f1dea504e452e7fa598750614b9a978/docs/handoff/zswapz/round027/agent3-evidence.md

Exclusive changed files (5):
- NEW tests/tools/round027-offline-swap-attribution.py: PURE rootless, never reads /proc, sysfs, cgroup or devices, no privileged commands; accepts exactly one bounded UTF8 JSON via safe filename dirfd+O_NOFOLLOW, no traversal/symlink/invalid numbers/dup keys/private UUID/path injection. Executes the actual unmodified `tests/tools/qualify-primary-real-swap.py:evaluate_workload_evidence` AST function in a constrained namespace, rather than a rewritten source-mock. Replays bounded original exact cgroup-vs-/proc/swaps attribution recheck rule (3-second max and two identical consecutive matching snapshots), 128MiB source minimum, original 4096 full-page oracle and backing lower sector *512 bytes, target logical/physical WRITE and READ, vmstat pswpout/in, OOM, owner identity, cleanup. Returns only `UNKNOWN_MISSING_EVIDENCE`, `FAIL_WITH_EVIDENCE`, `SYNTHETIC_SOURCE_CONSISTENT_NOT_PHYSICAL_PASS`, with bounded private-safe first reason. Does not claim physical PASS.
- NEW tests/runtime/native/round027-offline-swap-attribution-test.py: seven rootless unittest methods including many negative mutations for forgery, source/boot/mapper/partition mismatches, counter regressions, wrong exact byte floor, lower sector coverage, paused/retried non-atomic attribution, malformed/oversized/symlink evidence, original SHA/oracle integrity. Tests actual original AST function executed, not copy/pasted predicates.
- .github/workflows/physical-evidence-rootless.yml: runs additional standalone rootless `python3 -B tests/runtime/native/round027-offline-swap-attribution-test.py -v` and `python3 -B -m py_compile tests/tools/round027-offline-swap-attribution.py`; path filters added. Original adversarial physical/source lease checks unchanged and no physical operation.
- docs/handoff/zswapz/round027/agent3-evidence.md: first source failure and needed confidential redacted owner read-only evidence checklist.
- docs/testing_standards.md: unique APPEND-ONLY Round027 Agent3 standards; Agent2 and earlier contributions preserved.

EXACT hosted CI at SHA 87c171ac...:
- rootless physical evidence workflow 44057261033 COMPLETE SUCCESS (job 133949701416). Run: `python3 -B tests/runtime/benchmark/physical-campaign-evidence-test.py -v` 48 tests OK; `python3 -B tests/runtime/native/algorithm-ram-source-lease-test.py -v` 21 tests OK; `python3 -B tests/runtime/native/algorithm-physical-test.py -v` 30 tests OK; NEW `python3 -B tests/runtime/native/round027-offline-swap-attribution-test.py -v` 7 tests OK, actually executing exact AST-extracted real production acceptance function with synthetic data. `python3 -B -m py_compile tests/tools/round027-offline-swap-attribution.py` and `git diff --check HEAD^ HEAD` completed successfully. All 106 unittest methods in this workflow passed (not physical trials).
- No new C source/loaded module or genuine physical swap changes were part of Agent3. Pure source Python only. Host GCC/Clang irrelevant to this own scope.

HISTORICAL REAL OWNER FIRST FAILURE: older de5bc09e authorized physical anonymous_workload FAILED `swap_attribution`; owner private exact counters, recheck snapshots, mapper/lower sector values and numeric first cause are absent. That real failure is NOT resolved, NOT automatically timing/race, and the root cause is **UNKNOWN/UNDETERMINED**. The offline classifier returns `UNKNOWN_MISSING_EVIDENCE` for these missing numbers, never a physical PASS. It can flag an explicitly supplied COMPLETE redacted owner record with failing original predicates as FAIL_WITH_EVIDENCE, but a coherent owner record remains UNKNOWN pending independent authentication. Successful synthetic samples ONLY mean source-bound parser self-check, not actual physical swap evidence.

Owner-ready future read-only private evidence inventory is in evidence.md: verified committed/loaded source, consistent opaque boot/mapper/lower/cgroup identities, before/fill/recheck/verify timestamped cgroup memory.swap.current/peak/max, memory.events OOM, exact mapper /proc/swaps used-kib initial+final, original swapz target logical/physical read/write/failed/error, backing lower 512-byte sector read/write deltas, vmstat pswpin/out, original full 4096 oracle and worker teardown. DO NOT request physical tests now; no publicly released UUID/PID/device path.
GO_NO_GO: DIRECT_COMPRESSED=NO_GO_DISABLED; PHASE_A=BLOCKED; FORCED_RAW_BYPASS=DISABLED. Original RAW means ORIGINAL UNCOMPRESSED 4096. Existing SWAPSPACE2 first 4096 header/signature/UUID/partition table unchanged. zswap exclusively manages bounded RAM cache/eviction; swapz disk only. LOADED_MODULE=NOT_RUN; LOADED_ORIGINAL_4096_SWAPIN=NOT_RUN; PHYSICAL_SWAPSPACE2=NOT_RUN. Agent1 owns integration and final CI acceptance.
```

## Original comment 2 — https://github.com/k1moradi/swapz/issues/144#issuecomment-6944380301

```text
message: REPORT_READY
round: "027"
agent: 2
status: SOURCE_PUBLISHED_MAIN; EXACT_SEVEN_SOURCE_MANIFEST_FAILURE_REPAIRED; ROOTLESS_PAIRED_NEGATIVES_PASS; MANDATORY_PINNED_LINUX_Y_N_KBUILD_IN_PROGRESS_NOT_YET_QUALIFIED
frozen_task_sha: 5da826bdcfbc358ed80814afb0ca19d46ac23806
first_agent2_fix_sha: 3c7e8b2dc7195ab5d0ca1a76a5974d1b8b8fcd62
source_negative_test_correction_sha: 5d2aff0bb37e0811b163267b8e9bda6f9f4b127c
latest_agent2_preflight_strengthening_sha: c351acae78065335d37635e579e4eab65e94c564
parent_of_latest_agent2_sha: 87c171ac6f1dea504e452e7fa598750614b9a978
verified_remote_main_at_report: e37f0d622354592aa2369323329a03ddff08f467
publication: SOLE_MAIN_NON_FORCE_EXPECTED_HEAD_FF_AND_REMOTE_SHA_READBACK_VERIFIED; all Agent3 separate source/evidence preserved.
agent2_evidence: https://github.com/k1moradi/swapz/blob/e37f0d622354592aa2369323329a03ddff08f467/docs/handoff/zswapz/round027/agent2-evidence.md
pinned_current_exact_sha_ci: https://github.com/k1moradi/swapz/actions/runs/44057443308
pinned_prior_corrected_ci: https://github.com/k1moradi/swapz/actions/runs/44056954981
original_pinned_failure_ci: https://github.com/k1moradi/swapz/actions/runs/44048517348
first_new_negative_ci: https://github.com/k1moradi/swapz/actions/runs/44056324540

Changes in Agent2-owned files only (all source diffs and append-only docs on main):
- tests/runtime/native/pinned-linux-origin-paired-module-test.py: accept the exact existing six ORIGINAL pinned source paths default, and exactly one seventh ORIGINAL mm/swapfile.c ONLY with pinned git blob 254ce86fa923e6b5f1fefda88c39315c4cc00642, round026_allocator_epoch=NO_AUTHENTIC_GENERATION_NO_GO, round026_allocator_probe_compiled=false, direct compressed=false. Reject duplicate/reordered/unknown/missing source, wrong original sha/blob, false compiled/phase_a, forged opt-in. Paired manifest object allowlist now requires mm/swapfile.o exact SHA256 under opt-in CONFIG_ZSWAP=y/n; mm/zswap.o remains y-only. New rootless negative matrix for both profiles, forged marker and object. Later Agent2-only preflight strengthening executes fail-closed source manifest immediately after original source staging.
- .github/workflows/phase-a-zswap-origin-prototype.yml: original source staging/post-build allowlist consistent at exactly seven only for opt-in, preflight rejects wrong profile before actual costly original pinned build, wrapper preserves source-manifest first-error instead of misclassifying it as kernel-doc warning. Actual pinned GCC CONFIG_ZSWAP=y/n real mm/swapfile.o KCFLAGS W=1 -Werror, default symbol restoration, producer mm/zswap.o real compiler, full kernel vmlinux/modules, linked original Module.symvers dm-swapz.ko and exact warnings gates NOT REMOVED or bypassed.
- docs/testing_standards.md: uniquely headed Agent2 Round027 append-only sections with exact first failures, preserving every prior and Agent3 standard.
- docs/handoff/zswapz/round027/agent2-evidence.md: actual source identity, first failure and optional profile engineering proof. NO newly minted true MM allocator ABA-safe epoch; compressed optimizations remain OFF.

FIRST TRUE historical upstream-source CI gate failure: d46bcdb426de75d0ad30dbc58359c6eb3b51764a run 44048517348 job 133920135140 FAILED at `paired-build-invalid: source_manifest_paths` because original authenticated mm/swapfile.c was seventh staged source but paired verification expected six. This was BEFORE the original kernel-doc baseline classifier and not a C compiler error. Original untouched kernel-doc warning signatures/source Git blobs/digests/counts remain EXACT and warning suppression was NOT introduced.

FIRST Round027 repair CI regression at 3c7e8b2d... run 44056324540: own new adversarial test removed original seventh path but left the seventh-source flag; strict verifier correctly returned `paired-build-invalid: source_manifest_allocator_profile`, while the test incorrectly expected `source_manifest_paths`. Test corrected at 5d2aff0b... preserving strict source behavior, workflow advanced to actual full genuine Linux Kbuild. Subsequent Agent2 separate preflight on c351acae... also progressed to actual full kernel build.

VERIFIED TESTS: GitHub-hosted pinned workflow `python3 -B swapz/tests/runtime/native/pinned-linux-origin-paired-module-test.py --self-test --workflow ...` and previous rootless original source/producer regressions exited 0 at latest workflow before entering real Kbuild. The exact host Kbuild result is **IN_PROGRESS, NOT PASS** as of REPORT_READY: run 44057443308 job 133950324310 status in_progress (stage: genuine full pinned Linux + matched external DM module); prior run 44056954981 job 133948666358 status in_progress. Thus no complete y/n Kbuild, matched .ko, extra kernel compiler first failure, or Phase A loaded acceptance is claimed until job completion. Owner Agent1 must use exact-SHA final CI; any subsequent genuine C first compiler error wins over source-only regression PASS. Failed Kbuild must remain BLOCKED, not silently transformed to warning/synthetic success.

GO_NO_GO direct compressed optimization=NO_GO due ABSENT genuine allocator-issued per-slot epoch and unconnected owned MM/BIO→DM authority, even if build PASS later. Phase A BLOCKED, forced RAW bypass DISABLED, direct compressed handoff DISABLED. RAW = ORIGINAL UNCOMPRESSED 4096, original SWAPSPACE2 first 4096 header/signature/UUID/table untouched; zswap owns RAM caching and eviction, swapz disk only. LOADED_DM=NOT_RUN, LOADED_ORIGINAL_4096_SWAPIN=NOT_RUN, PHYSICAL=NOT_RUN. No unauthorized module/swap/pressure/null_blk/physical action.
```

## Original comment 3 — https://github.com/k1moradi/swapz/issues/144#issuecomment-6944386411

```text
message: REPORT_READY
round: "027"
agent: 2
status: SOURCE_FIRST_MANIFEST_REPAIR_PUBLISHED; EXACT_SOURCE_ROOTLESS_AND_STAGING_PASS; PINNED_LINUX_MATCHED_MODULE_KBUILD_IN_PROGRESS
frozen_task_sha: 5da826bdcfbc358ed80814afb0ca19d46ac23806
preexisting_peer_agent2_six_seven_fix: 3c7e8b2dc7195ab5d0ca1a76a5974d1b8b8fcd62
preexisting_peer_agent2_test_oracle_fix: 5d2aff0bb37e0811b163267b8e9bda6f9f4b127c
my_source_commit_sha: c351acae78065335d37635e579e4eab65e94c564
my_source_commit_parent: 87c171ac6f1dea504e452e7fa598750614b9a978
my_document_restoration_commit_sha: e37f0d622354592aa2369323329a03ddff08f467
my_document_restoration_parent: c351acae78065335d37635e579e4eab65e94c564
verified_remote_main_sha: e37f0d622354592aa2369323329a03ddff08f467
publication: TWO_NONFORCE_EXPECTED_HEAD_FAST_FORWARDS_AND_REMOTE_SHA_READBACK_VERIFIED
source_ci: https://github.com/k1moradi/swapz/actions/runs/44057443308
source_ci_job: 133950324310
rootless_prior_ci: https://github.com/k1moradi/swapz/actions/runs/44056954981
source_commit: https://github.com/k1moradi/swapz/commit/c351acae78065335d37635e579e4eab65e94c564
document_restoration: https://github.com/k1moradi/swapz/commit/e37f0d622354592aa2369323329a03ddff08f467
source_evidence: https://github.com/k1moradi/swapz/blob/e37f0d622354592aa2369323329a03ddff08f467/docs/handoff/zswapz/round027/agent2-evidence.md
GO_NO_GO: NO_GO_DIRECT_COMPRESSED
PHASE_A: BLOCKED
FORCED_RAW_BYPASS: DISABLED
DIRECT_COMPRESSED: DISABLED
ORIGINAL_MM_SLOT_ALLOCATION_EPOCH: ABSENT
LOADED_4096: NOT_RUN
PHYSICAL: NOT_RUN

### Actual first failures and source-rooted corrections
The first Round026 source gate failure was **paired-build-invalid: source_manifest_paths** in exact original Linux pinned [#44048517348](https://github.com/k1moradi/swapz/actions/runs/44048517348), job `133920135140`, exit 3: an explicitly opt-in seventh original `mm/swapfile.c` was emitted by the original stager but the paired-build verifier still accepted only six. The six shown original unchanged upstream kernel-doc warnings were NOT the first failure; they remain exactly source SHA1/count/digest validated, no global warning suppression. Another Agent2 peer published correct six/default and seven/allocator manifest handling (original allocator blob `254ce86fa923e6b5f1fefda88c39315c4cc00642` and `mm/swapfile.o` object evidence for y/n). Its exact-SHA [#44056324540](https://github.com/k1moradi/swapz/actions/runs/44056324540) job `133946531684` failed **before Kbuild** in 1 of 46 rootless cases: the intentionally removed seventh source left a marker in otherwise-valid six paths, so actual verifier correctly returned `source_manifest_allocator_profile`, while test expected `source_manifest_paths`. The peer published the corrected oracle to main in `5d2aff0bb37e0811b163267b8e9bda6f9f4b127c`, retaining verifier integrity.

I independently added a narrow **before-Kbuild original source profile gate** without overwriting already-published peer files:
- `tests/runtime/native/pinned-linux-origin-paired-module-test.py` +47/-0: extra `--verify-source-manifest-only --source-manifest PATH` CLI calls the SAME original bounded, duplicate-rejecting `load_source_manifest`, returns 0 on exact six/default or seven/opt-in and exit 1 with typed `paired-build-invalid: source_manifest_allocator_profile` for forged profile. The new rootless self-test uses actual subprocess invocations and verifies absence of private fixture paths in stderr. Full original-source workflow invariant checks prevent disabling/reordering this pre-Kbuild gate.
- `.github/workflows/phase-a-zswap-origin-prototype.yml` +14/-0: invoke identical source verifier AFTER original kernel pinned SHA/blob/allowlist source staging and `git diff --check`, BEFORE genuine `CONFIG_ZSWAP=y/n` kernel and matched module build. If source identity wrong, exit 3 before slow kernel exporter; this cannot be misdiagnosed as kernel-doc warning failure.
- `docs/handoff/zswapz/round027/agent2-evidence.md` +10/-0: append actual first failure, true rootless vs matched kernel status.
- `docs/testing_standards.md` net +8/-0: unique Agent2 follow-up append. An immediately detected GitHub connector >1MiB `fetch_file` empty-content behavior initially made the source commit's generated standards blob truncate the prior file. I **did not leave that silent**: created a second direct-main nonforce commit reconstructing byte-for-byte the FULL prior `docs/testing_standards.md` Git blob `8cb92996d1bf7bc75e100b57735c9f75ee428d1a` (1,050,125 chars/15,287 lines) PLUS ONLY my append, restoring all previous and concurrent Agent3 standards. Post-write `fetch_blob` verified full exact prefix and 1,052,554 chars/15,295 lines. GitHub net compare source parent `87c171...` -> verified remote `e37f0...`: ahead=2 behind=0; changed paths exactly four and **all additions, ZERO deletions**. No source code changed in the restoring commit.

### True executed tests and qualification
- Actual local `git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main` exited **128**: `Could not resolve host: github.com`; no mounted complete Linux repo clone or local kernel/module compiler executed. GitHub connector fetched source, CI logs, exact Git blobs, wrote Git objects to sole main and confirmed both single-parent non-force expected-head fast-forwards. No PR/branch/worktree/fork/force.
- Published exact SOURCE SHA `c351acae...`: [hosted pinned Linux workflow #44057443308](https://github.com/k1moradi/swapz/actions/runs/44057443308), job `133950324310`: **PASS** `Run source-controlled rootless staging regression`; **PASS** `Run disabled compressed handoff source/ownership negative regression` (GCC/Clang host source-only tests); **PASS** `Run matched source/module verifier regressions on full workflow` (includes the actual new source-profile CLI subprocess tests); **PASS** `Modify actual pinned Linux C and H in disposable full checkout`; **PASS** new `Verify original pinned source manifest before Kbuild` step. All observed in actual hosted job steps. The real `Build modified Linux and matched source-linked swapz module for both configurations` was **IN_PROGRESS**, not PASS, at exact-SHA check. Full `CONFIG_ZSWAP=y/n` `vmlinux`, `modules`, `Module.symvers`, `nm/objdump` and source-matched `dm-swapz.ko` therefore **NOT YET QUALIFIED** on my source SHA. Source-only successful compile is not loaded/physical or authenticated direct transfer. Agent1 owns complete matched Kbuild acceptance.
- Another actual exact peer SHA `5d2aff...` [workflow #44056954981](https://github.com/k1moradi/swapz/actions/runs/44056954981) had passed rootless staging, GCC/Clang negative source tests, paired verifier regression, actual pinned source staging and entered complete Kbuild; it is **not evidence of PASS** for my distinct source SHA.

**Physical safety:** no host module or kernel load, mkswap/swapoff/swapon, pressure, cgroup, null_blk, mapper or physical device operation. Original first physical SWAPSPACE2 4096 header/signature/UUID/partition table unchanged. RAW remains the ORIGINAL UNCOMPRESSED full **4096 bytes**; no rival pressure controller, no authenticated zswap compressed transfer, no on-media metadata. Missing genuine kernel source-owned swap-slot allocation epoch means compressed MM/BIO→DM admission remains NO_GO even if full kernel/module CI passes.

MAIN_WRITE_LEASE_RELEASED
```

## Original comment 4 — https://github.com/k1moradi/swapz/issues/144#issuecomment-6944488519

```text
message: SOURCE_UPDATE
round: "027"
scope: shared append-only testing_standards whitespace-only CI restoration, preserving Agents 2 and 3
published_main_sha: 424917ccb53f064c1eb86c881851399db0ff0439
sole_parent_sha: e37f0d622354592aa2369323329a03ddff08f467
commit: https://github.com/k1moradi/swapz/commit/424917ccb53f064c1eb86c881851399db0ff0439
status: NON_FORCE_EXPECTED_HEAD_FF_AND_REMOTE_READBACK_VERIFIED; WHITESPACE_FIX_ONLY; PHASE_A_BLOCKED
first_true_docs_ci_failure: https://github.com/k1moradi/swapz/actions/runs/44057751702 job 133951363779
first_failure: `git diff --check HEAD^ HEAD` returned code 2: `docs/testing_standards.md:12360: trailing whitespace` (one line containing a single ASCII space within complete previously restored standards). All older 48+21+30 and new Agent3 7 rootless tests in that run passed; this was NOT a kernel or attribution first failure. Prior c351acae inadvertently truncated shared standards, which also failed unrelated source contract tests, corrected in e37f0d62 by restoring complete 1,052,554-byte Git blob SHA `8fff2a515487dcf6afd74a19a190f87c41b8006b`. Current commit 424917cc removes only the sole trailing space on line 12360, preserving every original/Agent2/Agent3 standard and all headings. Verified source blob roundtrip SHA before replacing; no other files changed, no renames, no original source/staging mutations.
current_exact_sha_rootless_ci: https://github.com/k1moradi/swapz/actions/runs/44058599352 — in progress at publication; must await hosted result before claiming green.
mandatory_agent2_pinned_kernel_builds: https://github.com/k1moradi/swapz/actions/runs/44056954981 and https://github.com/k1moradi/swapz/actions/runs/44057443308 were still IN_PROGRESS in true pinned Linux y/n + module build steps at last readback; no complete Kbuild PASS claim. Agent2 and Agent3 prior REPORT_READY preserved.
PHYSICAL_ORIGINAL_SWAP_ATTRIBUTION: FIRST_CAUSE_UNKNOWN_UNDETERMINED; no owner original private numbers, no new physical test. LOADED=NOT_RUN PHYSICAL=NOT_RUN. Direct compressed=NO_GO_DISABLED, Phase A BLOCKED, forced RAW bypass DISABLED, RAW original UNCOMPRESSED 4096, SWAPSPACE2 original header/UUID/table untouched.
```

## Original comment 5 — https://github.com/k1moradi/swapz/issues/144#issuecomment-6945439717

```text
message: REPORT_READY
round: "027"
scope: POST-COMPLETION INDEPENDENT CI READBACK OF ALREADY PUBLISHED AGENT2 AND AGENT3 RESULTS
status: SOURCE_PINNED_LINUX_Y_N_MATCHED_KBUILD_SUCCESS; ROOTLESS_OFFLINE_ATTRIBUTION_TESTS_SUCCESS; PHYSICAL_CAUSE_UNDETERMINED
task_publication_sha: 5da826bdcfbc358ed80814afb0ca19d46ac23806
verified_remote_main_sha: 424917ccb53f064c1eb86c881851399db0ff0439
publication: NO_NEW_SOURCE_COMMIT_IN_THIS_READBACK; EXISTING_AGENT_COMMITS_ALREADY_PUBLISHED_NONFORCE_DIRECT_MAIN
agent2_final_source_commit: c351acae78065335d37635e579e4eab65e94c564
agent3_source_commit: 87c171ac6f1dea504e452e7fa598750614b9a978
documentation_restoration_commit: e37f0d622354592aa2369323329a03ddff08f467
documentation_whitespace_correction_commit: 424917ccb53f064c1eb86c881851399db0ff0439

The required work was already published by other worker sessions on the existing sole main. This is a factual completion/CI update, not a claim of a new Agent2/Agent3 implementation or locally executed build. No extra branch, PR, worktree, code commit, force push, device access or privileged commands were used in this review. Existing local checkout is not mounted here; local git fast-forward and independent local tests could not be performed (outbound git DNS unavailable). Hosted job logs and the exact remote ref were read using the connected GitHub interface.

Published Round027 changed paths, per frozen-to-main comparison:
- Agent2: `tests/runtime/native/pinned-linux-origin-paired-module-test.py`, `.github/workflows/phase-a-zswap-origin-prototype.yml`, `docs/handoff/zswapz/round027/agent2-evidence.md`
- Agent3: `tests/tools/round027-offline-swap-attribution.py`, `tests/runtime/native/round027-offline-swap-attribution-test.py`, `.github/workflows/physical-evidence-rootless.yml`, `docs/handoff/zswapz/round027/agent3-evidence.md`
- Shared append-only and later repair: `docs/testing_standards.md`; current main includes both agent sections.

Exact hosted tests/results (all below concluded SUCCESS, exit 0):
- Agent2 actual pinned full Linux + source-matched external module Kbuild: [workflow 44057443308](https://github.com/k1moradi/swapz/actions/runs/44057443308), job 133950324310, exact source SHA `c351acae78065335d37635e579e4eab65e94c564`. All steps passed: staging negative tests, independent source manifest preflight, real CONFIG_ZSWAP=y and CONFIG_ZSWAP=n complete kernel/build + matched dm-swapz module Kbuild + evidence preservation, unchanged strict original kernel-doc whitelist and W=1/-Werror.
- Independent earlier genuine pinned Kbuild: [workflow 44056954981](https://github.com/k1moradi/swapz/actions/runs/44056954981), job 133948666358, exact `5d2aff0bb37e0811b163267b8e9bda6f9f4b127c`, SUCCESS.
- Agent3 actual source-SHA rootless offline attribution workflow: [44057261033](https://github.com/k1moradi/swapz/actions/runs/44057261033), job 133949701416, exact `87c171ac6f1dea504e452e7fa598750614b9a978`, SUCCESS.
- On current final `424917cc`, rootless workflow [44058599352](https://github.com/k1moradi/swapz/actions/runs/44058599352), job 133954250418, SUCCESS: existing adversarial 48 + 21 + 30 tests, new Round027 7 tests; total 106 rootless tests plus patch whitespace and py_compile. All five other triggered workflows for exact current SHA also completed SUCCESS.
- Hosted tests above executed by GitHub Actions; **no local tests were run in this verification session**.

Recorded first historical failures (not relabeled as compiler/physical cause):
1. [44048517348](https://github.com/k1moradi/swapz/actions/runs/44048517348), job 133920135140: `paired-build-invalid: source_manifest_paths` from seventh genuine original mm/swapfile.c vs six-only paired validator. Original kernel-doc diagnostics were not first failure.
2. [44056324540](https://github.com/k1moradi/swapz/actions/runs/44056324540), job 133946531684: new negative fixture expected paths error but correct verifier returned `source_manifest_allocator_profile`; fixed in 5d2aff0 without relaxing validator.
3. [44057751702](https://github.com/k1moradi/swapz/actions/runs/44057751702), job 133951363779: shared docs trailing whitespace in append-only restoration, corrected by 424917cc; current exact-SHA rerun SUCCESS.
4. Historical older-source de5bc09e owner physical `anonymous_workload` FAIL `swap_attribution`; original private counters/identities/timings absent. Numerical first cause and root cause **UNKNOWN/UNDETERMINED**, not repaired or requalified by synthetic tests.

SOURCE KBUILD=QUALIFIED HOSTED AT LISTED EXACT SOURCE SHAS.
LOADED ORIGINAL 4096 KERNEL SWAPIN=NOT_RUN.
PHYSICAL OWNER SWAPSPACE2=NOT_RUN; historical attribution FAIL remains unresolved.
PHASE_A=BLOCKED. FORCED_RAW_BYPASS=DISABLED. DIRECT_COMPRESSED=NO_GO_DISABLED.
AUTHENTIC_LINUX_ALLOCATOR_SLOT_EPOCH=ABSENT.
RAW=ORIGINAL UNCOMPRESSED FULL 4096 BYTES. ZSWAP owns RAM caching/eviction; swapz owns backing without rival pressure controller. Physical original SWAPSPACE2 header/signature/UUID/partition table untouched.

Agent1 retains integration and final CI acceptance authority.
```

