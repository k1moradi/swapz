# Round063 original worker issue reports

[Issue #180](https://github.com/k1moradi/swapz/issues/180); original two worker comments, complete bodies, original issue order; trailing whitespace normalized. [Independent audit](https://github.com/k1moradi/swapz/issues/180#issuecomment-7074018251) supersedes pending statuses.

---

## [Original comment 7071974392](https://github.com/k1moradi/swapz/issues/180#issuecomment-7071974392)

message: AGENT4_ROUND063_PROGRESS_SOURCE_PUBLISHED
round: "063"
agent: 4
official_round_open_comment: 7071648146
status: PROGRESS_EXACT_NATIVE_Y_N_CI_PENDING_NOT_REPORT_READY
source_commit: 71591fecd829bf378e8d673c0586f0b01c475ca3
source_parent: 47538393a53accd2f19249ecb14d5ffdb0c5552b
publication: MAIN_ONLY_FRESH_EXPECTED_SHA_SINGLE_PARENT_NONFORCE_FF_VERIFIED
changed_paths:
  - tests/runtime/native/fixtures/round060-original-decoder-module.c
  - tests/tools/round060-original-decoder-kbuild-verify.py
  - docs/handoff/zswapz/round063/agent4-evidence.md
  - docs/testing_standards.md
standards_previous_complete_prefix_preserved: YES_1542859_CHARACTERS
same_commit_new_standards_chars: 3848
fixture_exact_remote_git_blob: eb5bede299f2f97cc15d94b88aea9fdf1b302e64
verifier_exact_remote_git_blob: 2cfccf90e6f048c2d2d4fab222d094c249a4be8a
original_linux_pin: torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8
original_11_linux_blobs: UNTOUCHED
prior_exact_run: https://github.com/k1moradi/swapz/actions/runs/44964399878
prior_source_host: job137030049616_TERMINAL_SUCCESS_ACTUAL_GCC_CLANG_ASAN_UBSAN_10_SOURCE_C_MUTANTS
prior_native_n: job137031209840_TERMINAL_FAILURE_AFTER_VMLINUX_MODULES_POSITIVE_GPL_MODPOST
prior_native_y: job137031209846_TERMINAL_FAILURE_AFTER_VMLINUX_MODULES_POSITIVE_GPL_MODPOST
prior_both_first_errors: "ROUND060_DECODER_FIRST_ERROR compiled module did not retain original decoder link LZ4_decompress_safe"
prior_negative_missing_export_actual_modpost: NOT_REACHED
source_evidence: "Original pinned include/linux/lz4.h declares real extern LZ4_decompress_safe; lib/lz4/lz4_decompress.c EXPORT_SYMBOL(LZ4_decompress_safe). Missing final .ko retained consumer ELF reference, not evidence original provider export missing."
narrow_fix: "Retain exact real swapz_zswap_import_decode wrapper via uncalled __used static function-pointer data relocation; independently root intentional missing-export negative source function; module_init still unconditionally -EOPNOTSUPP. Verifier requires actual nm -a root/function + real nm -u original LZO1X LZ4 sha256 and real product CRC, strict single missing-export modpost first cause."
rootless_local_compiler_mechanism_test: "GCC+Clang strict -Wall -Wextra -Wconversion -Wshadow -Werror -O2 actual C object compilation; nm -u observed separate external original_lzo/original_lz4 undefined and nm -a actual rooted data symbol. Structural test ONLY, not selected decoder native kernel proof."
new_exact_source_run: https://github.com/k1moradi/swapz/actions/runs/44969728833
new_source_host: job137046641405_IN_PROGRESS
new_original_native_zswap_y_n: NOT_YET_REACHED
true_pinned_native_positive_negative_both: UNVERIFIED_AT_THIS_CHECKPOINT
loaded_selected_decoder_module_ref_after_source_zswap_pool_teardown: NO_GO_NOT_TESTED
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_raw_bypass: DISABLED
ordinary_raw_4096: FULL_ORIGINAL_UNCOMPRESSED_4096
owner_make_privileged_loaded_physical_real_pressure: NOT_RUN_NOT_AUTHORIZED

Do not claim REPORT_READY, true live decoder reference, source-to-current-DM authentication or release.
Exact-source CI follow-up:
  decoder_workflow_run: 44969728833
  source_host_job: 137046641405 TERMINAL_SUCCESS
  original_pin_11_blobs: PASS
  seven_original_symbol_config_negative: PASS
  gcc_clang_strict_preflight: PASS
  original_host_gcc_clang_sanitizer_baselines: PASS
  genuinely_compiled_executed_changed_C_codec_mutants: 10_OF_10_PASS
  source_host_first_errors: NONE
  native_original_zswap_y: 137046914011 QUEUED
  native_original_zswap_n: 137046914055 QUEUED
  actual_new_native_positive_negative_modpost: PENDING
  worker_state: PROGRESS_NOT_REPORT_READY


---

## [Original comment 7072052176](https://github.com/k1moradi/swapz/issues/180#issuecomment-7072052176)

message: AGENT3_ROUND063_PROGRESS_REAL_CROSS_LAYER_OPT_IN_SOURCE_PUBLISHED
round: "063"
agent: 3
official_round_open_comment: 7071648146
state: PROGRESS_EXACT_NATIVE_CI_QUEUED_NO_PRODUCTION_AUTH
repository: k1moradi/swapz
original_linux_pin: torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8
original_pristine_pin_modified: NO
staged_original_kernel_variant: EXPLICITLY_MODIFIED_CI_ONLY_NOT_PRISTINE
native_stored_source: REAL_ORIGINAL_ROUND056_PREERASE_INDEPENDENT_SEALED_LZ4_COPY_REF
source_commit: dd382e27638955b4a25026dcb27e125677f02273
source_parent: 71591fecd829bf378e8d673c0586f0b01c475ca3
source_commit_peer_parent: AGENT4_COMMIT_PRESERVED
source_publication: MAIN_ONLY_FRESH_EXPECTED_SHA_ONE_PARENT_NONFORCE_FF_VERIFIED
workflow_first_failure_run: https://github.com/k1moradi/swapz/actions/runs/44970060484
workflow_first_failure: TERMINAL_FAILURE_ZERO_JOBS_INVALID_YAML
first_failure_cause: "Generator JavaScript String.replace interpreted shell-regex '$' followed by quote as special $' suffix replacement, duplicating actions/upload-artifact blocks within grep lines and causing YAML parse rejection."
first_failure_native_source_C_built: NO
first_failure_native_71_KUNIT_executed: NO
first_failure_native_x86_ZSWAP_y_n_GPL_executed: NO
narrow_repair_commit: 3e79823eb79fed85afb4e9a3ee67cc59835e68ed
narrow_repair_parent: dd382e27638955b4a25026dcb27e125677f02273
narrow_repair_paths:
  - .github/workflows/phase-a-round063-original-mm-dm-carrier-noauth.yml
  - docs/handoff/zswapz/round063/agent3-evidence.md
  - docs/testing_standards.md
narrow_repair_source_C_files_changed: NONE
narrow_repair_direct_main: FRESH_EXPECTED_SHA_ONE_PARENT_NONFORCE_FF_VERIFIED
narrow_repair_peer_and_full_testing_standards_prefix: PRESERVED
corrected_exact_source_ci: https://github.com/k1moradi/swapz/actions/runs/44970260225
corrected_ci_source_sha: 3e79823eb79fed85afb4e9a3ee67cc59835e68ed
corrected_ci_current_status: QUEUED_NOT_TERMINAL
corrected_ci_real_native_71_KUNIT_and_x86_y_n_GPL: PENDING_NOT_VERIFIED
local_rootless_GCC_14_2: PASS_GNU11_WALL_WEXTRA_WCONVERSION_WSHADOW_WERROR_ASAN_UBSAN
local_rootless_Clang_17: PASS_GNU11_WALL_WEXTRA_WCONVERSION_WSHADOW_WERROR_ASAN_UBSAN
same_original_C_helper_host_scenarios: 16_PASS
true_changed_original_C_semantic_mutants_compiled_and_executed: GCC_10_OF_10_PASS_CLANG_10_OF_10_PASS
source_ref_get_via_real_staged_original_block_bio: swapz_round063_original_dm_owner_get
source_ref_put_via_real_staged_original_block_bio: swapz_round063_original_dm_owner_put
actual_production_DM_acquisition: src/kernel/dm-target.c_swapz_map_dm_per_bio_data_BEFORE_incoming
actual_production_DM_requeue: RELEASES_DM_HELD_REF_AFTER_queue_lock_before_DM_MAPIO_REQUEUE_OR_KILL
actual_production_DM_accepted_lifetime: HELD_ACROSS_ORDERED_PROCESSING_RELEASE_BEFORE_REAL_bio_endio
production_DM_git_blob_at_source_commit: b12ca32330decb4e9c5eed2270e26614baf92f6a
original_composer_git_blob: 6ac1be7212981f0fde11f330ad024592f6f86efc
original_C_fixture_git_blob: ea44d981a00501b6956fb91fe4436475dde657e4
local_host_C_fixture_exact_git_blob_verified: 1ee19b366efa6bd05fc34cc87dc79134d092cecb
local_host_python_exact_git_blob_verified: b831e2fd114de7f30083ea896ea7f33eb4d8e3f6
current_source_authenticated: NO
actual_original_swp_entry_epoch_current_target_mapping_verified: NO
actual_loaded_original_decoder_ref_pinned: NO
actual_lower_compressed_WRITE_FUA: NO
actual_reader_GC_authoritative_map: NO
actual_compressed_upper_ACK: NO
actual_full_original_4096_READER_AFTER_GC: NO
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_RAW_bypass: DISABLED
import_active_flags: 0
ordinary_RAW_4096: WHOLE_ORIGINAL_UNCOMPRESSED_4096
native_MM_RAM_pressure_and_natural_eviction: LINUX_OWNED_ONLY
swapz_work: DISK_PACKING_COMPRESSION_GC_ONLY
existing_SWAPSPACE2_header_signature_uuid_and_parent_partition_table: UNTOUCHED
owner_make_privileged_loaded_physical_real_pressure: NOT_EXECUTED_NOT_AUTHORIZED

**Concrete engineering improvement beyond last audit:** the same opt-in, source-C-extracted original Linux owner getter makes a separately held ref to the real original Round056 preerase sealed compressed copy on a cloned original swap BIO; the current **real production** `swapz_map` carries that additional ref in `struct swapz_bio_ref` from accepted enqueue through terminal and cleans it on a concurrent pre-admission close/requeue. This is a test-gated **mechanical reference ownership** improvement, NOT proof of actual swp-to-current-DM table mapping, selected decoder lifetime, durable original compressed lower I/O, GC, readback or ACK. The product still runs ordinary uncompressed RAW fallback, never compressed-in-RAW. Source is guarded with four default-undefined build macros; ordinary production ABI/codepath remains unchanged.

**Prior failed first cause preserved, not hidden:** initial exact source #44970060484 got no jobs from corrupted YAML, not a kernel failure. One-parent fix 3e79823eb79fed85afb4e9a3ee67cc59835e68ed corrected the two injected suffix artifacts and original real CI now **registered** as #44970260225, currently QUEUED. No REPORT_READY until actual own source host, genuine original 71 UML KUnit, native original x86 ZSWAP=y/n full vmlinux/modules/GPL target symbol imports become TERMINAL and pass. Do not transfer historical previous sources' tests. See [Round063 Agent3 exact evidence](https://github.com/k1moradi/swapz/blob/3e79823eb79fed85afb4e9a3ee67cc59835e68ed/docs/handoff/zswapz/round063/agent3-evidence.md) and the two direct-main commits [source](https://github.com/k1moradi/swapz/commit/dd382e27638955b4a25026dcb27e125677f02273) / [workflow repair](https://github.com/k1moradi/swapz/commit/3e79823eb79fed85afb4e9a3ee67cc59835e68ed).
