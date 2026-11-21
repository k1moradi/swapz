
# Round061 original source-owner issue reports

Original authoritative [Round061 issue #178](https://github.com/k1moradi/swapz/issues/178), unique official [ROUND_OPEN](https://github.com/k1moradi/swapz/issues/178#issuecomment-7068315045). Exactly six original agent-provided issue comments (Agents2,3,4,5,6 plus Agent5 CI follow-up) are preserved below chronologically, with their exact original comment IDs and GitHub permalinks. Only trailing whitespace/EOF normalized for clean Git. These are historical worker statements, NOT independent CI evidence; use immutable exact-source GitHub jobs and the [Agent1 independent raw-log checkpoint](https://github.com/k1moradi/swapz/issues/178#issuecomment-7068872784).


---

## Original worker report 1: [GitHub comment 7068695017](https://github.com/k1moradi/swapz/issues/178#issuecomment-7068695017)

message: AGENT2_ROUND061_SOURCE_OWNER_INVESTIGATION
round: "061"
worker: Agent2
status: BLOCKED_AUTHENTIC_SOURCE_TO_CURRENT_DM_LEASE_NOT_PROVEN
official_round_open: 7068315045
frozen_last_engineering_sha: ae9d91012846d8818162da69f8aba3a9cef1ae5e
frozen_task_main_sha: 46bdc9b08b1f4c55a446bf488589abce26d7427a
observed_main_head: 46bdc9b08b1f4c55a446bf488589abce26d7427a
new_main_commit: NONE
new_ci_run: NONE
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_RAW_bypass: DISABLED
original_kernel_pin: torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8
test_scope: READ_ONLY_ORIGINAL_SOURCE_INSPECTION_REUSING_VERIFIED_PREVIOUS_EXACT_RUN

**First missing actual ownership interface (NOT a reported original Linux correctness regression):**
1. Pristine original `mm/zswap.c:zswap_writeback_entry()` at pinned lines 1016–1058 takes the original swap device/locked swapcache folio and validates `entry == xa_load(tree, offset)` before decompression. Lines 1058–1086 then **erase the xarray entry, free the compressed zsmalloc entry, mark the full decoded folio uptodate, drop the standalone folio ref and start ordinary `__swap_writeout()/swap_write_submit()`**. Source-only Round056 guarded composer can copy bounded selected original LZ4 compressed bytes into an independently refcounted owner **before** erase, but no authentic current-target handoff is created.
2. Original `mm/page_io.c:__swap_writeout` (376–393) starts accounted PG_writeback and unlocks; `swap_bdev_submit_write` (596–623) builds the original embedded `swap_iocb` BIO with the *decoded original* 4096-byte folio, sector derived from source folio, and native `bio_init()` **bi_vcnt=0** despite the populated `sio->bvecs`. `end_swap_bio_write` (538–548) calls `bio_uninit` then `swap_write_end`, which ends folio writeback and frees the containing `swap_iocb` and its embedded bvec storage. Synchronous `submit_bio_wait` and async callback paths have different completion control, neither licenses an independent delayed compressed consumer.
3. Pristine `block/bio.c:__bio_clone` (876–902) copies the `bi_iter` and **aliases `bi_io_vec`**; original `bio_alloc_clone` docs (905–917) explicitly require clone release before the original bvec memory disappears. Pristine `drivers/md/dm.c:alloc_io` (571–605) creates this borrowed clone; `clone_endio` (1092–1149) frees the clone and decrements pending IO; `__dm_io_complete` (950–999) can requeue or complete the original BIO. This ordinary DM accounting is not a separately acquired, retained source-STORED/bvec/codec/current-table lease for a new compressed consumer.
4. Repository actual `round058-original-stored-bio-chain.cfrag` checks original folio swapcache, uptodate, PG_writeback, exact swap slot and SHA only **synchronously**, then returns 0 as source-only observation; original page_io stager explicitly discards that result via `(void)swapz_round058_source_bio_observe(bio)`. It does not attach a real current accepted `dm_per_bio_data` owner. Existing Round056 original clone ticket intentionally requires `bi_vcnt==1` and therefore refuses the actual original page_io BIO (`bi_vcnt==0`); KUnit asserts that refusal. It also models parent `bio_uninit` invalidating a child candidate despite still-equal borrowed vector pointers.
5. Actual production `src/kernel/dm-target.c` Round058 guarded `swapz_round058_dm_ingress_refuse` observes *current* target/sector/map and `BIO_CLONED` but returns `-EOPNOTSUPP` even for matching shape, as do terminal/endio; no original source-side owner is transferred. The source-stage zero-vcnt and current DM model's vcnt-one accepted shape are not interchangeable evidence. A same pointer, slot/SHA, cloned marker or this source-only guarded snapshot is not a lease.

**First unproven gate:** immutable original pre-erase selected-codec compressed payload owner + original live folio/swpentry **and original embedded bvec lifetime**, transferred with independent reference and per-accepted current target/table/SRCU/DM per-BIO ownership through split, requeue, terminal, upper ACK and dtr. Neither old model nor upstream BIO cloning provides this complete handoff. Decode/module lifetime after pool retirement, durable lower compressed WRITE/FUA, current map/GC/read pin, exactly one real ACK and independent original 4096 READ remain separately NO_GO. Ordinary `RAW_4096` remains full original uncompressed 4096; no competing MM shrinker, no new partition/device use.

**Existing exact-source, previously verified CI only (rechecked GitHub run status and bounded real job logs):**
- `647a34f970d3b97c2d2d938b5baaed2d8152a720` parent `ebd96466a12333e27da258f01c129c9f779ed23f`; [run 44928389631](https://github.com/k1moradi/swapz/actions/runs/44928389631) TERMINAL SUCCESS **3/3**. Job `136919419467`: original pinned 71 C UML KUnit JSON/KTAP, PASS; job `136919419710`: actual original C source GCC+Clang strict ASan+UBSan, 23 cases and ten compiled/executed semantic C mutants/compiler, PASS; job `136919419787`: pinned original x86 ZSWAP=y/n GPL + matched `dm-swapz.ko`, PASS. Job logs explicitly say `AUTH0` and `DM_LEASE=NOT_PROVEN`.
- Related distinct Agent3 product [run 44928482594](https://github.com/k1moradi/swapz/actions/runs/44928482594), source `36510427c83cba616238558abd1f576721aafa17`, terminal 3/3 SUCCESS in its bounded source/native DM scope; also not source-authenticated.

**This round:** no changed-source first-error demonstrated within Agent2's exclusive source files; deliberately **NO code patch / no standards append / no commit / no newly claimed CI** rather than invent a positive source ticket or duplicate old KUnit. Rootless local fresh kernel/host rerun unavailable in this session because no mounted repository checkout and direct Git remote DNS resolution returned `Could not resolve host: github.com`; the GitHub connector still permitted inspection of exact repository and pinned upstream C. This environmental limitation is not a product failure, and the above CI results are historical exact-SHA scoped evidence, not new 061 tests or release qualification.

No branch, PR, fork, worktree, force/merge publication; no owner Make, privilege, loaded kernel, physical device, swap activation or pressure tests. **REPORT_READY withheld; Agent2 bounded investigation ends BLOCKED pending a genuine source/current-target retained lease and new authentic test evidence.**


---

## Original worker report 2: [GitHub comment 7068701876](https://github.com/k1moradi/swapz/issues/178#issuecomment-7068701876)

message: AGENT4_ROUND061_PROGRESS_PUBLISHED
round: "061"
agent: 4
status: PROGRESS_EXACT_SOURCE_NATIVE_CI_NOT_TERMINAL
official_round_open: 7068315045
source_commit: fc46a155bd5b58c4d5d8b04ce84afb9267f547ad
source_parent: 46bdc9b08b1f4c55a446bf488589abce26d7427a
publication: SOLE_MAIN_FRESH_EXPECTED_HEAD_ONE_PARENT_NONFORCE_FF_READBACK_VERIFIED
changed_paths:
  - .github/workflows/phase-a-round060-original-decoder-gpl-noauth.yml
  - tests/tools/round061-original-kbuild-host-deps-verify.py
  - docs/testing_standards.md
old_full_standards_prefix_bytes_preserved: 1529508
new_standards_characters: 1532202
original_linux: torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8
original_linux_11_blobs: UNCHANGED
frozen_native_first_errors:
  - run44928802641 job136931827862: "ZSWAP=y original-vmlinux: fatal error: gelf.h: No such file or directory"
  - run44928802641 job136931827889: "ZSWAP=n original-vmlinux: fatal error: gelf.h: No such file or directory"
fix: "Ephemeral GitHub Ubuntu runner installs libelf-dev and original kernel bc/bison/flex and dependencies before build, checks elf.h+gelf.h+libelf.h, then actually compiles+links+executes libelf with both GCC and Clang; preserves pinned vmlinux/modules+matched GPL Module.symvers, genuine positive and deliberate missing-export NEGATIVE modpost."
local_rootless_regression: "Exact staged/published Git blob 5e37039f7e9b3bce6d25818dbe809dd0249c8648; python3 -B tests/tools/round061-original-kbuild-host-deps-verify.py self-test PASS. Real preflight on this limited environment correctly exits 3: missing development header gelf.h."
original_source_host_gcc_clang_asan_ubsan_ten_real_semantic_C_mutants: "Preserved in existing source-host job; NOT YET terminal at new exact SHA"
real_native_zswap_y_n_module_modpost: "NOT YET terminal; do not treat prior failed jobs as PASS"
remaining_native_decoder_loaded_reference_after_zswap_pool_death: NO_GO
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_RAW_bypass: DISABLED
raw_4096: FULL_ORIGINAL_UNCOMPRESSED_4096
owner_make_privileged_loaded_physical_pressure: NOT_RUN_NOT_AUTHORIZED

This is a scoped progress report, NOT release authorization and NOT REPORT_READY. Exact new-source workflow statuses/first errors will be added when observed.
Exact-source CI update:
  workflow: https://github.com/k1moradi/swapz/actions/runs/44945860474
  source_host: job136972898063 TERMINAL_SUCCESS
  source_pinned_11_linux_blobs: PASS
  original_symbol_config_negative_mutants: 7_OF_7_REJECTED
  missing_gelf_header_regression: PASS
  actual_gcc_clang_asan_ubsan_original_host: PASS
  actual_changed_source_mutants: 5_GCC_PLUS_5_CLANG_COMPILED_EXECUTED_REJECTED
  source_host_first_errors: NONE
  original_native_zswap_n: job136973571093 QUEUED_PENDING
  original_native_zswap_y: job136973571144 QUEUED_PENDING
  scope_status: PROGRESS_NOT_REPORT_READY


---

## Original worker report 3: [GitHub comment 7068706241](https://github.com/k1moradi/swapz/issues/178#issuecomment-7068706241)

**Agent3 — Round061 scoped NO_GO / evidence published (not REPORT_READY, not compressed-admission AUTH).**

- **Direct-main documentation commit:** [`fc8be3ff39cf5e09f36954ff1294be73e1c4cf41`](https://github.com/k1moradi/swapz/commit/fc8be3ff39cf5e09f36954ff1294be73e1c4cf41), **sole parent** `fc46a155bd5b58c4d5d8b04ce84afb9267f547ad`, freshly checked expected-head, `force=false`, successful non-force FF; remote `main` readback exact. Only changed file `docs/handoff/zswapz/round061/agent3-evidence.md`; `docs/testing_standards.md` unchanged byte-for-byte, Git blob `d0fb73857985eb4edebc393cb4623ed9f8bfc6b3`; no peer file overwritten.
- **Current production DM source:** `src/kernel/dm-target.c` blob `038bf7c34fcccb6d2b1cb7a0b409ba30028a471c`, unchanged from Agent3's corrected previously qualified source `36510427c83cba616238558abd1f576721aafa17`. Reviewed real `swapz_map` accepted per-BIO, REQUEUE/KILL, queue_lock, normal `swapz_raw_write` original 4096, `swapz_complete` sole upper `bio_endio` preparation release, actual `swapz_end_io`, `swapz_drain`/dtr and default-UNDEFINED Round058 capture/terminal/endio observer. 11 source-structure checks PASS (static only); no separate demonstrated new C defect to justify a default-path patch.
- **First missing source-to-DM proof:** current test-only observation of cloned BIO/bdev/bvec/target LEN/map pointer has no retained original live STORED folio+swp entry/slot incarnation, original page_io borrowed clone-to-current-target/SRCU tenure across requeue or target reload/pointer ABA, independent selected decoder/module ref after pool death, durable imported lower compressed WRITE+FUA, imported authoritative map/GC/read pin, one genuinely imported upper ACK plus fully decoded original 4096 read. It always returns `-EOPNOTSUPP`. Pointer and generation scalar rechecks are rejection filters, **not** AUTH.
- **Exact pre-existing source evidence, historical, NOT current whole-repo CI:** [run 44928482594](https://github.com/k1moradi/swapz/actions/runs/44928482594) at `36510427c83cba616238558abd1f576721aafa17`: source GCC+Clang strict sanitizer/15 compiled+executed semantic C mutants job `136919707582` SUCCESS; real original pinned x86 GPL ZSWAP=n job `136924372568` SUCCESS and ZSWAP=y job `136924372611` SUCCESS; all three terminal. These do **not** erase the separate current P0 workflows' failures.
- **New local executions:** no local GCC/Clang sanitizer, semantic-mutant, or native kernel execution claimed. First environment error before checkout: `fatal: unable to access 'https://github.com/k1moradi/swapz.git/': Could not resolve host: github.com`; no local source checkout available. No new hosted run was triggered by this documentation-only change, and no false green or new kernel proof is claimed.

**Decision:** `SOURCE_MAPPED_AUTHENTICATED=0`; `PHASE_A=BLOCKED`; direct compressed handoff and forced RAW bypass **DISABLED**. Normal `RAW_4096` remains the full original uncompressed page. Native Linux MM alone owns zswap RAM/pressure eviction; swapz solely disk packing/GC. Protected physical SWAPSPACE2 first 4096 bytes and parent partition table untouched. No owner Make, privileged, loaded, actual-pressure or physical-device test. See [complete Agent3 evidence](https://github.com/k1moradi/swapz/blob/fc8be3ff39cf5e09f36954ff1294be73e1c4cf41/docs/handoff/zswapz/round061/agent3-evidence.md).


---

## Original worker report 4: [GitHub comment 7068712230](https://github.com/k1moradi/swapz/issues/178#issuecomment-7068712230)

message: AGENT6_ROUND061_P0_SOURCE_PUBLISHED_PROGRESS
round: "061"
agent: 6
status: PROGRESS_EXACT_AUTHORITY_CI_QUEUED
source_commit: 089320a739f212527da89e4206d428e91e710b5b
one_parent_fresh_main: fc8be3ff39cf5e09f36954ff1294be73e1c4cf41
publication: FRESH_EXPECTED_HEAD_NONFORCE_FAST_FORWARD_MAIN_VERIFIED
source_changed:
  - .github/workflows/phase-a-round060-authority-conversion-noauth.yml
  - tests/tools/round061-authority-push-metadata-verify.py
  - docs/testing_standards.md
standards_prior_peer_blob: d0fb73857985eb4edebc393cb4623ed9f8bfc6b3
standards_new_blob: 244f27ccb101e37ccb5b51fa9e13c04efef172ee
standards_entire_prefix_preserved_chars: 1532202
standards_substantive_same_commit_append_chars: 2023
policy_checker_source_edited: NO
genuine_authority_compiler_mutants_step_preserved: GCC_CLANG_ASAN_UBSAN_10_REAL_CHANGED_SOURCE_C_MUTANTS
local_regression: 9_TEST_METHODS_PASS_10_SECONDS_REAL_TEMP_GIT
local_regression_policy: ENFORCEMENT_CORE_FROM_UNCHANGED_GITHUB_POLICY_SOURCE_RECONSTRUCTED_FOR_LOCAL_SMOKE
own_exact_GitHub_workflow: https://github.com/k1moradi/swapz/actions/runs/44945953451
own_exact_CI_initial_status: QUEUED_NOT_GREEN
prior_known_first_error: "SOURCE_CONTRACT_MISMATCH first_error=push base SHA unavailable or invalid"
new_source_first_error: NONE_AVAILABLE_UNTIL_EXACT_CI_RUN
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_RAW_bypass: DISABLED

Agent6 fixed only the independent Round060 authority workflow's missing event metadata: `SWAPZ_PUSH_BEFORE_SHA: ${{ github.event.before }}` directly from real push before, no fabricated parent and no `continue-on-error`. Full checkout, exact main/GITHUB_SHA, policy first-parent, applicable same-commit canonical standards and original linked GCC/Clang sanitizer+ten executed mutants retained. New rootless actual-Git ephemeral fixture runs the exact repository policy in CI against positive real first-parent co-changes and negative missing/empty/zero/malformed/unrelated bases, empty ranges, bad SHA, workflow-only missing standards, docs-only followup, plus manual nonpush mode. Local nine-case smoke passed with unchanged enforcement core mirrored for offline testing; the exact original full repository checker will be invoked by the hosted run. The single-parent direct-main expected-head CAS was verified after peers advanced; all prior standards retained as literal prefix, and three changed paths independently verified via GitHub compare. This source-only test repair grants no native source-to-DM lease, original decoder ownership, durable compressed handoff, release, physical test or RAW bypass. No owner Make, privileged, module loaded, physical-device or pressure test run. REPORT_READY withheld until exact authority workflow completes.


---

## Original worker report 5: [GitHub comment 7068717239](https://github.com/k1moradi/swapz/issues/178#issuecomment-7068717239)

message: AGENT5_ROUND061_PROGRESS_PUBLISHED
round: "061"
agent: 5
status: PROGRESS_EXACT_SOURCE_CI_QUEUED
source_sha: 0593173cad62192bb89f5ba37c6a993e7bafd0d7
source_parent: 089320a739f212527da89e4206d428e91e710b5b
publication: SOLE_MAIN_FRESH_EXPECTED_HEAD_ONE_PARENT_NONFORCE_FAST_FORWARD_READBACK_VERIFIED
changed_paths:
  - tests/tools/round057-transaction-product.py
  - tests/tools/round061-product-mutant-workspace-verify.py
  - .github/workflows/phase-a-round057-transaction-product-noauth.yml
  - docs/handoff/zswapz/round061/agent5-evidence.md
  - docs/testing_standards.md
standards: OLD_AND_PEER_PREFIX_BYTE_IDENTICAL_APPEND_ONLY_THIS_COMMIT
frozen_first_error_round057: 44928802841/job136920672682 FileExistsError mutant-0 after GCC 5/5 Clang baseline
frozen_first_error_round059: 44928802819/job136920673086 same FileExistsError mutant-0
correction: GCC_AND_CLANG_DISJOINT_BINARY_AND_MUTANT_0_TO_4_SCRATCH; SAFE_OSERROR_TIMEOUT_FIRST_ERROR; PRIVATE_0600_UNEXPECTED_OUTPUT; ORIGINAL_5_REAL_SOURCE_MUTANTS_PER_COMPILER_UNCHANGED
unit_regression: STUBS_C_SUBPROCESS_ONLY_TO_PROVE_REAL_RUNNER_SCRATCH_CONTROL_FLOW_NOT_A_C_QUALIFICATION
exact_source_round057_ci: https://github.com/k1moradi/swapz/actions/runs/44945987536 QUEUED
exact_source_round059_inherited_lz4_ci: https://github.com/k1moradi/swapz/actions/runs/44945987562 QUEUED
REPORT_READY: WITHHELD_UNTIL_BOTH_TERMINAL_REAL_LINKED_C_COMPILATION_MUTANTS_AND_FIRST_PARENT_POLICY
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_RAW_bypass: DISABLED
normal_RAW_4096: FULL_ORIGINAL_UNCOMPRESSED_4096
physical_swapspace2_first_4096_partition_table: UNCHANGED
owner_make_privileged_loaded_physical_pressure: NOT_RUN

Actual rootless GNU11 high-warning GCC/Clang ASan+UBSan product binary and all ten changed-source semantic mutant executions are enforced by the real existing runner in BOTH independent exact-source CI workflows, not inferred from workspace-only unit tests. Await terminal first errors; no compressed handoff or release.


---

## Original worker report 6: [GitHub comment 7068745426](https://github.com/k1moradi/swapz/issues/178#issuecomment-7068745426)

message: AGENT5_ROUND061_EXACT_CI_PROGRESS
round: "061"
agent: 5
source_sha: 0593173cad62192bb89f5ba37c6a993e7bafd0d7
source_parent: 089320a739f212527da89e4206d428e91e710b5b
round059_inherited_lz4_run: 44945987562
round059_job: 136973283990
round059_job_status: COMPLETED_SUCCESS
round059_actual_host_lz4: GCC_CLANG_BASELINE_SUCCESS_10_COMPILED_EXECUTED_SOURCE_MUTANTS_SUCCESS
round059_inherited_actual_product: GCC_AND_CLANG_REAL_LINKED_AUTHORITY_C_CODEC_C_ASAN_UBSAN_STRICT_WERROR_SUCCESS_5_OF_5_ACTUAL_SEMANTIC_MUTANTS_PER_COMPILER
round059_hostile_first_error: GCC_AND_CLANG_PRIVATE_0600_CLEAN_SOURCE_RELATIVE_PASS
round057_standalone_run: 44945987536
round057_job: 136973284092
round057_status_at_report: QUEUED_NOT_PASS
report_ready: WITHHELD_UNTIL_ROUND057_TERMINAL
prior_first_error: SHARED_MUTANT_0_FILE_EXISTS_FIXED_IN_ROUND059_NOW_VERIFIED_NO_COLLISION
safety: SOURCE_MAPPED_AUTHENTICATED_0_PHASE_A_BLOCKED_DIRECT_COMPRESSED_HANDOFF_DISABLED_FORCED_RAW_BYPASS_DISABLED
no_make_privileged_loaded_physical_pressure: YES

Raw exact job log https://github.com/k1moradi/swapz/actions/runs/44945987562/job/136973283990 records PASS gcc/clang actual linked production and PASS gcc/clang actual-source semantic mutants=5, no raw /tmp directory first error. Original Round057 independent exact-source job remains queued, not transferred green from inherited workflow.
