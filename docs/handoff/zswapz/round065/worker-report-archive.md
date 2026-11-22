# Round065 worker-authored original reports

[Issue #182](https://github.com/k1moradi/swapz/issues/182). Both complete original comments in issue order; trailing whitespace normalized. [Agent1 independent audit](https://github.com/k1moradi/swapz/issues/182#issuecomment-7076105288) supersedes pending statuses.

---

## [Original comment 7075761200](https://github.com/k1moradi/swapz/issues/182#issuecomment-7075761200)

message: AGENT4_ROUND065_PROVEN_LZ4_ELF_ORACLE_FALSE_REJECTION_CORRECTED
round: "065"
agent: 4
official_round_open_comment: 7075223683
status: PROGRESS_CORRECTED_EXACT_SOURCE_NATIVE_MATRIX_PENDING_NOT_REPORT_READY
source_commit: d4f2c8bce4dfa6da4f21aafe8f945e73bbd1851f
source_parent: 39f45aa1bb11774dd186f5cf4f873f1f2d4e9eeb
publication: MAIN_ONLY_FRESH_EXPECTED_HEAD_ONE_PARENT_NONFORCE_FF_VERIFIED
changed_paths:
  - tests/tools/round060-original-decoder-kbuild-verify.py
  - docs/handoff/zswapz/round065/agent4-evidence.md
  - docs/testing_standards.md
full_previous_and_peer_standards_prefix: VERIFIED_1559442_CHARACTERS
appendix_chars: 3520
verifier_exact_remote_blob: 65ce17b24c373a3ea17ece9f47199eed2ecc69f2
unchanged_real_product_decoder_header_blob: 0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6
native_fixture_diagnostic_inspector_workflow: UNCHANGED
original_pin: c339f4010dea8b0d754f84ace70cd1b089878ef8
prior_actual_diagnostic_run: https://github.com/k1moradi/swapz/actions/runs/44991824557
prior_actual_diagnostic_native_y: 137114479192 TERMINAL_FAILURE
prior_actual_diagnostic_native_n: 137114479171 TERMINAL_FAILURE
prior_integrated_diagnostic_run: https://github.com/k1moradi/swapz/actions/runs/44992035145
prior_integrated_native_y: 137117590339 TERMINAL_FAILURE
prior_integrated_native_n: 137117590349 TERMINAL_FAILURE
prior_all_four_actual_kbuild_defconfig_olddefconfig_vmlinux_modules_positive_GPL_modpost: PASS
prior_all_four_actual_first_error: "ROUND060_DECODER_FIRST_ERROR compiled module did not retain original decoder link LZ4_decompress_safe retained=lzo1x_decompress_safe,sha256 missing=LZ4_decompress_safe"
prior_all_four_native_results: "positive=1 diagnostics=0 missing_export_negative=0 omitted_branch_negative=0"
actual_native_preprocessing: "Both original codec tags compared; one LZ4_decompress_safe call and one lzo1x_decompress_safe call. SHA256 helper retained."
actual_native_compiler_cmd: "compile_only=1 werror=1 host_test_macro=0 source_header_dependency=1 original_lz4_header_dependency=1"
actual_native_provider: "Both configs LZO_DECOMPRESS=y LZ4_DECOMPRESS=y. Exact original same-kernel vmlinux LZO GPL-only and LZ4 ordinary export, SHA256 export."
actual_native_consumer_combined_final_LZ4: "undefined=1 text_relocations=1 defined=0 at all three stages, same for LZO1X and SHA256"
actual_product_crc: "defined in codec.o and final ELF; final not undefined"
prior_actual_missing_export_negative: "All four native jobs specifically rejected deliberate missing export at real original modpost"
prior_actual_omitted_source_branch_negative: "All four native jobs compiled actual independent mutated C module; LZ4 symbol and text relocation both absent, other selected references retained"
proven_root_cause: "run_checked() strips complete subprocess stdout, deleting first GNU nm record indentation. Legacy regex requires leading whitespace before U. Uppercase LZ4_decompress_safe sorts before the lowercase names. Real ELF baseline present but first-line parser returns false, not native decoder omission."
narrow_fix: "Exact two-field strong U record parsing on each line, complete selected symbol name required without requiring indentation. No deleted selected decoder or provider/GPL/modinfo/CRC/diagnostic/negative gates."
local_real_GCC_Clang_ELF_tests: PASS_6_ACTUAL_OBJECTS_BASELINE_OMISSION_LOOKALIKE_PER_COMPILER
local_old_regex_false_rejection: REPRODUCED_BOTH_COMPILERS
local_actual_exact_LZ4_relocation_readelf: PASS_BOTH_COMPILERS
local_4_actual_exact_symbol_negatives: PASS
local_3_non_strong_or_malformed_record_negatives: PASS
local_test_scope: STRUCTURAL_PARSER_NOT_NATIVE_KERNEL_OR_CODEC_EXECUTION
corrected_source_ci: https://github.com/k1moradi/swapz/actions/runs/44997018549
corrected_source_host_job: 137130130702 QUEUED
corrected_native_y_n_jobs: NOT_YET_SCHEDULED
corrected_all_four_native_gates_y_n: PENDING
existing_CI_cancellations_or_duplicate_reruns: NONE
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_RAW_bypass: DISABLED
ordinary_RAW_4096: FULL_ORIGINAL_UNCOMPRESSED_PAGE
owner_make_privileged_loaded_physical_actual_pressure: NOT_RUN_NOT_AUTHORIZED

**Root cause is established by actual native .cmd/preprocessing, per-object/final ELF and provider evidence plus direct local real GCC/Clang nm/readelf reproduction.** Both native diagnostic runs contradict the legacy false-positive failure message: the actual compiled module already retains the selected original LZ4 decoder. The original strict verifier’s stdout normalization and leading-whitespace requirement disagree on the first symbol. Corrected only the parser and added mandatory real ELF regression. All other qualification remains required, including genuine original GCC/Clang ASan/UBSan source-host ten executed codec mutants and independent positive/diagnostics/missing-export/actual-omitted-branch native results. Not REPORT_READY until the corrected exact native matrix is terminal green; no runtime decoder lifetime or release authorization. [Committed evidence](https://github.com/k1moradi/swapz/blob/d4f2c8bce4dfa6da4f21aafe8f945e73bbd1851f/docs/handoff/zswapz/round065/agent4-evidence.md).


---

## [Original comment 7075819395](https://github.com/k1moradi/swapz/issues/182#issuecomment-7075819395)

message: AGENT3_ROUND065_FIRST_NATIVE_DM_TABLE_INCARNATION_CANDIDATE_SOURCE_PUBLISHED
round: "065"
agent: 3
official_round_open_comment: 7075223683
status: PROGRESS_NEW_EXACT_NATIVE_CI_QUEUED_NOT_REPORT_READY
frozen_task_sha: 39f45aa1bb11774dd186f5cf4f873f1f2d4e9eeb
source_commit: 53e843489c0462382ce7400b7fd43f7ad24ef4aa
single_parent: d4f2c8bce4dfa6da4f21aafe8f945e73bbd1851f
publication: MAIN_ONLY_FRESH_EXPECTED_HEAD_ONE_PARENT_NONFORCE_FF_READBACK_VERIFIED
remote_file_blob_readback: 11_OF_11_MATCH
complete_previous_and_peer_standards_prefix: VERIFIED_1562962_CHARACTERS
standards_appended: 4786_CHARACTERS
previous_round064_actual_source: 57bf1f8a192bf5e3c5cc1f0bb813ed70acce1d6a
previous_exact_qualification: https://github.com/k1moradi/swapz/actions/runs/44992035073
previous_exact_source_host: 137114969412_TERMINAL_SUCCESS
previous_exact_original_71_KUnit: 137116704750_TERMINAL_SUCCESS
previous_exact_native_y: 137116704778_TERMINAL_SUCCESS
previous_exact_native_n: 137116704811_TERMINAL_SUCCESS
previous_own_native_first_error: NONE_4_OF_4_SUCCESS
current_product_DM_blob: f1cab252cd990190646c82da81378d1563475826
current_exact_tested_product_table_gate_blob: 55ee7e4e791fdf8248757df5260b494776468621
original_table_state_fragment_blob: d1f78ea4033c6919a81ea3468c9b984cd55a889a
original_table_owner_fragment_blob: d6b87cfae53f45165f8b265121566bc77a93ee59
original_dm_core_fragment_blob: 21e5b9ede34a6593c468d9988d835c5f737d1472
original_table_state_KUnit_fragment_blob: 49585e973f18373fad95af150761f170fe191f60
local_exact_host_blob: 7177c54b0025e31a45a2e86003fd051c51fa1bb2
local_exact_verifier_blob: 2c617ab190fc1118b0753fe968a282508c0c6d77
stager_blob: 825f932dc89d27a90f11c8f9ebc4a222f11c2cad
original_linux_pin: torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8
pristine_original_core_dm_c_blob: 1881d86111fb2e655893ad898cf21b88f0e4e7f3
pristine_original_core_dm_core_h_blob: a3b8ad6e1c42def591694cb304994c2b8d5ca301
staged_variant: EXPLICITLY_MODIFIED_TEST_ONLY
local_source_host_UID: 1000
GCC_and_Clang_strict_GNU11_ASAN_UBSAN: PASS_BOTH
local_scenarios: 24_OF_24_EACH_COMPILER
local_compiled_and_executed_changed_C_semantic_mutants: 23_OF_23_EACH_COMPILER
local_first_error: GCC_REVIVAL_MUTANT_SURVIVED_SEMANTIC_EXIT_0
first_error_resolution: CORRECTED_INEFFECTIVE_MUTANT_TO_REMOVE_ACTUAL_FINAL_REFUSAL_GATE_RERAN_BOTH_FULL_SUITES_PASS
local_initial_full_git_checkout_error: "Could not resolve host: github.com"
source_test_scope: REAL_NEW_STAGED_STATE_OWNER_CORE_C_AND_EXACT_ACTUAL_PRODUCT_TABLE_GATE_HOST_API_STUBS
native_anchor_checks: FOUR_ACTUAL_PINNED_CORE_ANCHORS_UNIQUE
stager_local_structural_anchor_snippet_controls: 4_OF_4_PLUS_DUPLICATE_REFUSAL_PASS_NOT_NATIVE
new_native_state_KUnit: ONE_ADDED_NOT_YET_EXECUTED
inherited_71_KUnit: QUALIFIED_AT_PRIOR_SHA_NEW_SOURCE_PENDING
current_workflow_blob: ac735685559ed1a045a36eb6679720ef48c4b158
current_exact_native_workflow: https://github.com/k1moradi/swapz/actions/runs/44997424299
current_exact_source_host: 137131360894_QUEUED
current_new_native_72_KUnit_and_x86_y_n_GPL: NOT_YET_SCHEDULED
current_native_first_error: NONE_OBSERVED_NATIVE_NOT_STARTED
actual_native_DM_dispatch_requeue_reload_drain_dtr_runtime: NOT_EXECUTED
old_native_CI_cancelled_or_manually_restarted: NONE
new_table_pin_or_long_lived_SRCU_or_extra_slot_count: NONE
table_incarnation: ACTUAL_DM_CORE_BIND_PUBLICATION_GENERATION_STORED_IN_EXISTING_ORIGINAL_OWNER_CANDIDATE
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_raw_bypass: DISABLED
ordinary_RAW_4096: WHOLE_ORIGINAL_UNCOMPRESSED_4096
owner_make_privileged_loaded_physical_actual_pressure: NOT_RUN_NOT_AUTHORIZED

**Concrete increment:** default-undefined Round065 stager verifies full previous composed manifest and two pinned pristine core blobs, then stages actual native dm.c/dm-core.h and original block/bio.c/include/linux/bio.h. Actual __bind issues nonreused positive generation (refuses permanently on exhaustion) before publishing table under suspend_lock/RCU. Original Round064 route binding records exact native parent BIO in existing privately owned sealed owner. First actual DM dispatch selection occurs in dm_submit_bio after suspended/deferred check, while native live map SRCU is held and before split/clone. Never-dispatched deferred I/O is unselected. Same original parent and same generation may revalidate; another generation or invalid route permanently refuses. The actual GPL core matcher in synchronous ->map checks genuine clone_endio, native dm_target_io/dm_io/orig_bio linkage, normal unsplit/nonduplicate clone, exact current selected target/mapper, sector and vector/sideband identity. Actual product candidate gate uses this native matcher after acquiring original ref and drops that ref on refusal before queue publication. Existing Round064 rejection and clear-before-put completion path unchanged. Genuine existing DM in-flight pending_io protocol owns native current target while accepted IO is outstanding; native suspend blocks dispatch and waits before rebind/destruction. No table pointer/reference or SRCU index held over I/O/suspend; only incarnation evidence in existing independently owned source ref. No new allocation/copy, counted slot or competing reclaim. Under no circumstance enable compressed IO or extra ACK.

**Limits:** synchronous native source code and host tests advance first selection, same-generation requeue and different-generation/ABA refusal. They do not execute whole native scheduling/reload/drain/dtr or prove across-module-unload generation lifetime. No full mapped AUTH. New 1 actual original state-transition KUnit (not live DM) scheduled separately after inherited 71 in same UML build; full staged x86 y/n actual provider+guarded/default product compile/GPL modulo unchanged old guards. Exact source C and host/verifier blobs match local executed bytes. Native job results pending; no claim previous scope proves new source. New workflow structurally checked (job/indentation/guard/heredoc) and registered. [Detailed evidence](https://github.com/k1moradi/swapz/blob/53e843489c0462382ce7400b7fd43f7ad24ef4aa/docs/handoff/zswapz/round065/agent3-evidence.md).

**Independent Agent4 cross-check:** its four exact terminal native diagnostic jobs at prior #44991824557 and integrated #44992035145 proved both real selected decoder text relocations in consumer/combined/final, both actual negatives passed, older positive verifier falsely rejected first nm record. Agent4's separate [report](https://github.com/k1moradi/swapz/issues/182#issuecomment-7075761200) and correction d4f2c8bce4dfa6da4f21aafe8f945e73bbd1851f preserved as sole direct-main parent. Corrected own run [44997018549](https://github.com/k1moradi/swapz/actions/runs/44997018549) source-host137130130702 terminal SUCCESS; native y137130618520 and n137130618554 IN_PROGRESS. No duplicate session, no own edit of Agent4 files, no cancellation or manual rerun. All gates remain NO_AUTH and BLOCKED.
