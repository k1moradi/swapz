
# Round062 original worker-authored GitHub issue report archive

Original [Round062 issue #179](https://github.com/k1moradi/swapz/issues/179), unique [ROUND_OPEN comment7068946304](https://github.com/k1moradi/swapz/issues/179#issuecomment-7068946304). EXACTLY FOUR original worker comments below, sorted by posted issue order; retain original body with trailing whitespace normalized and each immutable comment permalink. These worker reports are not independent exact-source GitHub CI; see the [Agent1 native LZ4 ELF real first error](https://github.com/k1moradi/swapz/issues/179#issuecomment-7071566403).

---

## Original worker report 1: [comment 7071226304](https://github.com/k1moradi/swapz/issues/179#issuecomment-7071226304)

message: AGENT5_ROUND062_PROGRESS_SOURCE_PUBLISHED
round: "062"
agent: 5
status: PROGRESS_EXACT_SOURCE_CI_PENDING
source_sha: 264808cce02b6a44fb1d0b855dfeae34682e328e
source_parent: cd8b6e9fa1349289b381dc5472765d133322bd55
publication: MAIN_ONLY_ONE_PARENT_FRESH_EXPECTED_HEAD_NONFORCE_FAST_FORWARD_READBACK_VERIFIED
changed_paths:
  - tests/tools/round061-product-mutant-workspace-verify.py
  - docs/handoff/zswapz/round062/agent5-evidence.md
  - docs/testing_standards.md
standards: ENTIRE_OLD_AND_PEER_PREFIX_BYTE_IDENTICAL_APPEND_ONLY
actual_original_first_error: https://github.com/k1moradi/swapz/actions/runs/44945987536/job/136973284092 AssertionError ROUND061_MUTANT_WORKSPACE_FIRST_ERROR mutant escaped compiler-owned directory
root_cause: MUTATED_HEADER_IS_ALREADY_A_MUTANT_DIRECTORY_WHILE_MUTATED_C_IS_FILE; OLD_ORACLE_WRONGLY_CALLED_PARENT_ON_BOTH
repair: TYPE_CORRECT_FILE_VS_DIRECTORY_WITH_EXISTENCE_AND_RESOLVED_OWNERSHIP_CHECKS; THREE_EXPLICIT_ESCAPED_HEADER_SOURCE_SYMLINK_NEGATIVES; BOUNDED_SAFE_FIRST_ERROR_WITH_PRIVATE_0600_DETAILS
local_rootless_isolated_smoke: PASS 20_POSITIVE_MUTATED_C_AND_HEADER_TYPES; 3_ESCAPE_NEGATIVES; PRIVATE_DIR_0700_FILE_0600_AND_SYMLINK_REFUSAL
local_actual_repository_C: NOT_RUN_NO_LOCAL_CHECKOUT_GITHUB_DNS_UNAVAILABLE
production_authority_c_codec_c_runner: UNCHANGED_REAL_GCC_CLANG_WERROR_ASAN_UBSAN_AND_5_CHANGED_SOURCE_C_MUTANTS_EACH_MANDATORY_CI
old_round059_inherited_product: 44945987562/job136973283990 TERMINAL_SUCCESS_AT_PREVIOUS_SOURCE_ONLY
current_round057_standalone_ci: PENDING_EXACT_SOURCE_STATUS
current_round059_inherited_ci: PENDING_EXACT_SOURCE_STATUS
REPORT_READY: WITHHELD_UNTIL_BOTH_TERMINAL
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_RAW_bypass: DISABLED
normal_RAW_4096: FULL_ORIGINAL_UNCOMPRESSED_4096
physical_swapspace2_first_4096_partition_table: UNCHANGED
owner_make_privileged_loaded_physical_pressure: NOT_RUN

No authentic original native STORED-to-current-DM lease, imported durable lower write/map/upper ACK/read, live pinned decoder reference or production release is claimed. Original Linux MM alone manages compressed RAM natural eviction. The workspace-only mock regression is NOT counted as real C qualification; inspect actual new hosted jobs and first errors.


---

## Original worker report 2: [comment 7071238639](https://github.com/k1moradi/swapz/issues/179#issuecomment-7071238639)

**Agent 3 — Round062 independent cross-layer source + current DM result: `BLOCKED_MISSING_UPSTREAM_MM_TO_DM_LEASE` / NO-GO. No source patch or fabricated positive handoff.**

**Actual audit inputs.** Official Round062 frozen task `cd8b6e9fa1349289b381dc5472765d133322bd55`, previous real engineering `0593173cad62192bb89f5ba37c6a993e7bafd0d7`, original upstream `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`. At final recheck sole `main=264808cce02b6a44fb1d0b855dfeae34682e328e` (parent frozen task `cd8b6e9...`), actual `src/kernel/dm-target.c` Git blob `038bf7c34fcccb6d2b1cb7a0b409ba30028a471c` and original source composer `tests/tools/round058-original-stored-bio-chain.py` blob `0828f0c1dc0352f29d788fe73c7d3596d0b2bd56` unchanged. No Agent3 commit, no branch/PR/worktree; no peer changes overwritten.

**Earliest missing real upstream kernel carrier.**
1. **Native original STORED before erase:** pinned pristine [`mm/zswap.c`](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zswap.c#L1005-L1095), `zswap_writeback_entry()`: allocates/locks folio and validates `entry == xa_load(tree, offset)` (1047–1051), `zswap_decompress(entry, folio)` (1053), then `xa_erase` (1058) and `zswap_entry_free(entry)` (1064), **BEFORE** `__swap_writeout(&ctx, folio); swap_write_submit(&ctx);` (1085–1086). `zswap_entry_free()` releases zsmalloc handle/pool reference (777–794). Without an independently copied, retained original STORED source BEFORE that free, DM cannot retrieve authentic original compressed bytes.
2. **Pristine MM→BIO ABI absent:** pinned [`include/linux/swap_ops.h`](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/include/linux/swap_ops.h#L17-L20) `struct swap_io_ctx` contains only `sio` and `sis`, **no retained compressed-source handle**. [`mm/page_io.c`](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/page_io.c#L596-L623) constructs ordinary `struct bio` on `sio->bvecs` for the full uncompressed folio, then `end_swap_bio_write` releases BIO and `swap_iocb` (538–549). [`include/linux/blk_types.h`](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/include/linux/blk_types.h#L210) has no `bi_swapz_ci_sideband`; [`block/bio.c:__bio_clone`](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/block/bio.c#L876-L907) clones iterator and **borrows** `bi_io_vec` (documented in `bio_alloc_clone` 912–932) but transfers **no original compressed-source ref**. `swap_io_ctx` does not reach current DM with original `swp_entry_t` allocation generation and independent codec authority.
3. **Original test-only staged source does NOT cure ABI:** `tests/tools/round056-original-preerase-module.py` has a guarded bounded owned zsmalloc SG copy after original successful decompress and before erase (`swapz_round056_mm_bio_create`). `stage-pinned-linux-zswap-composed.py` adds opt-in `SWAPZ_ROUND031_MM_BIO_SOURCE`/`SWAPZ_ROUND025_SIDEBAND_CI_ONLY` fields and moves `ctx->swapz_round031_owned` into original page_io BIO, with guarded clone ref tests. `round058-original-stored-bio-chain.cfrag` explicitly proves only synchronous **original source observation**, not downstream target ownership. This is a modified CI-only original kernel, **not** the pristine pinned exported default ABI, and neither source C/KUnit nor a GPL export establishes a live accepted DM lease.
4. **DM clone/current accepted target:** pinned [`drivers/md/dm.c`](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/drivers/md/dm.c#L571-L605) allocates `bio_alloc_clone` for `dm_io` and [lines 1438–1456](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/drivers/md/dm.c#L1438-L1456) **frees the current target clone on `DM_MAPIO_REQUEUE`**; [`dm_submit_bio` 2074–2102](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/drivers/md/dm.c#L2074-L2102) obtains current table through `dm_get_live_table` and releases its SRCU read-side lease before return. Product [`src/kernel/dm-target.c`](https://github.com/k1moradi/swapz/blob/cd8b6e9fa1349289b381dc5472765d133322bd55/src/kernel/dm-target.c#L13852-L14150) `swapz_map` has target-relative 8-sector and `dm_per_bio_data` ownership, but **never reads `bi_swapz_ci_sideband`**, has no retained original zswap source handle or independently mapped `swp_entry_t` incarnation, and rejects admission when not accepting. Real `swapz_complete` (2198–2241) releases prepared data before one upper `bio_endio`, `swapz_end_io` (2360–2388) fail-closes after target failure; `swapz_drain`/dtr (14150–14368) quiesce ownership. These current DM lifetimes do not magically authenticate an external original compressed buffer. Even test-only `swapz_round033_dm_try_live_original_bio_v1` returns `-EOPNOTSUPP` (4694–4699). Matching pointer, sector, epoch, SHA or map-length values cannot defeat target/slot ABA.

**Minimum real upstream-to-product interface / no implemented positive path:** original zswap owner must snapshot **exact real selected original LZO1X/LZ4 codec+driver/version, no dictionary, immutable owned 1..3568 compressed bytes, compressed CRC32C and independent original decoded full 4096 SHA256** while `xa_load`, original swp entry/incarnation, live locked folio and source pool still agree. A **new upstream-owned, reference-counted BIO provenance API** must transfer this private handle into `swap_io_ctx`→embedded `swap_iocb` BIO and each DM clone with balanced get/put on clone completion, `DM_MAPIO_REQUEUE`, errors, and original BIO cleanup. It must authenticate swp type/offset + live swap area/extent/block device/slot-generation against the **currently accepted** DM target under a retained table/current target ref and 8-sector target-relative mapping, not a scalar ticket. DM must transfer the accepted reference into per-BIO descriptor, bound it across ordered worker, lower I/O, terminal `end_io`, suspend/dtr; reissue requires **fresh** current target/generation validation. Selected original codec decoder/module lifetime needs independent pin past pool destruction. Genuine compressed lower WRITE/flush FUA success, authoritative volatile map/GC reader pins, exactly one **real** upper ACK and exact independently decoded 4096 READ are separate still-missing correctness gates. Any failed acquisition/teardown must release private refs, wipe buffers and keep ordinary full uncompressed RAW fallback. Do not add shrinker/pressure controller.

**Executed rootless checks / limitations:** Direct read-only cross-file source assertions on the fetched **real pinned upstream C and current product**: 21/21 contract properties PASS (an initially too-short source window in the audit's terminal check was corrected and retested against exact lines 2198–2241). Five source-text negative controls PASS after fixing an oracle that initially matched a duplicate preprocessor guard; **these are static structural checks, not compiled/executed C semantic-mutant binaries, not UML KUnit or x86 kernel GPL Kbuild**. Repository clone was attempted rootlessly but failed before checkout with first environment error `fatal: unable to access 'https://github.com/k1moradi/swapz.git/': Could not resolve host: github.com`; no new local GCC/Clang or genuine native-original tests were possible. Previously verified **historical only** original KUnit/GPL [run 44928389631](https://github.com/k1moradi/swapz/actions/runs/44928389631) and DM GCC/Clang semantic mutants + original y/n GPL [run 44928482594](https://github.com/k1moradi/swapz/actions/runs/44928482594) do not qualify a new interface or authorize live imported I/O. **No new Agent3 CI run/commit exists** because unsupported native ABI must not be replaced with a mock or vanity diff; no fresh-source success claimed.

**Decision:** `BLOCKED_MISSING_UPSTREAM_MM_TO_DM_LEASE`; `SOURCE_MAPPED_AUTHENTICATED=0`; `PHASE_A=BLOCKED`; `DIRECT_COMPRESSED_HANDOFF=DISABLED`; `FORCED_RAW_BYPASS=DISABLED`. Ordinary `RAW_4096` still full ORIGINAL UNCOMPRESSED 4096. Native MM alone controls compressed RAM/natural eviction; swapz solely disk payload/GC; volatile 20-byte mapping and 4/8/16KiB padded extents unchanged. SWAPSPACE2 physical first 4096-byte header/UUID/signature and parent partition table untouched. No owner Make, loaded, privilege, device, physical swap, or artificial pressure tests. This is an **exact missing kernel interface report**, not `REPORT_READY` or end-to-end AUTH.


---

## Original worker report 3: [comment 7071239345](https://github.com/k1moradi/swapz/issues/179#issuecomment-7071239345)

message: AGENT4_ROUND062_PROGRESS_SOURCE_PUBLISHED
round: "062"
agent: 4
official_round_open: 7068946304
status: PROGRESS_EXACT_NEW_NATIVE_CI_PENDING_NOT_REPORT_READY
published_source_sha: 95f046e52a4d7976cf27c0676c12ce61fd09a570
published_parent_sha: 264808cce02b6a44fb1d0b855dfeae34682e328e
publication: MAIN_ONLY_EXPECTED_HEAD_ONE_PARENT_NONFORCE_FAST_FORWARD_VERIFIED
intervening_peer_main_commit: 264808cce02b6a44fb1d0b855dfeae34682e328e
peer_testing_standards_full_prefix_bytes_preserved: YES_1539779_CHARACTERS
own_testing_standards_added: 3080_CHARACTERS_APPEND_ONLY
changed_paths:
  - tests/tools/round061-original-kbuild-host-deps-verify.py
  - docs/testing_standards.md
  - docs/handoff/zswapz/round062/agent4-evidence.md
published_helper_git_blob: 6b89a112ae697d9d9e4ef6ac49506ece4f76cdaa
local_helper_git_blob: 6b89a112ae697d9d9e4ef6ac49506ece4f76cdaa
original_pristine_linux_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
original_11_source_git_blobs: PRESERVED
prior_ci_run: https://github.com/k1moradi/swapz/actions/runs/44945987651
prior_original_source_host: job136973284607 TERMINAL_SUCCESS
prior_original_native_zswap_n: job136975869586 TERMINAL_FAILURE
prior_original_native_zswap_y: job136975869644 TERMINAL_FAILURE
prior_both_real_first_errors: "ROUND061_DECODER_FIRST_ERROR clang real libelf compile/link failed"
root_cause_locally_reproduced: "clang -Werror rejects unnecessary -x none after last stdin source: [-Werror,-Wunused-command-line-argument]; gcc tolerates it"
narrow_fix: "Remove only redundant -x none; preserve full strict GCC/Clang flags, real elf.h gelf.h libelf.h -lelf compile/link/execute, original defconfig vmlinux modules Module.symvers and positive/negative modpost"
local_exact_published_helper_self_test: PASS actual_gcc_clang_compile_link_execute=2_AND_2 original_clang_negative=1 missing_elf_gelf_libelf_negative=3
local_missing_gelf_real_preflight: EXPECTED_FAIL_EXIT_3 (LOCAL_ENVIRONMENT_NO_LIBELF_DEV_NOT_KERNEL_PROOF)
new_exact_source_decoder_ci: https://github.com/k1moradi/swapz/actions/runs/44964399878
new_exact_ci_at_initial_inspection: source-host job137030049616 QUEUED; native_y_n NOT_YET_SCHEDULED
real_native_full_vmlinux_modules_symvers_positive_negative_modpost: STILL_UNVERIFIED_AT_THIS_CHECKPOINT
external_selected_decoder_loaded_ref_surviving_zswap_pool_teardown: NOT_TESTED_NOT_AUTHENTICATED
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_raw_bypass: DISABLED
ordinary_raw_4096: FULL_ORIGINAL_UNCOMPRESSED_PAGE
owner_make_privileged_loaded_physical_pressure: NOT_RUN_NOT_AUTHORIZED

No original Linux kernel native or genuine positive/negative GPL modpost success claimed until new exact-source jobs finish. No branch, PR, fork, worktree, merge, force or module load.


---

## Original worker report 4: [comment 7071242010](https://github.com/k1moradi/swapz/issues/179#issuecomment-7071242010)

message: AGENT5_ROUND062_REPORT_READY_SCOPED
round: "062"
agent: 5
status: REPORT_READY_SCOPED_PRODUCT_TEST_ORACLE_ONLY_NOT_RELEASE
source_sha: 264808cce02b6a44fb1d0b855dfeae34682e328e
source_parent: cd8b6e9fa1349289b381dc5472765d133322bd55
publication: SOLE_MAIN_FRESH_EXPECTED_SHA_ONE_PARENT_NONFORCE_FF_REMOTE_READBACK_VERIFIED
later_peer_main: 95f046e52a4d7976cf27c0676c12ce61fd09a570
later_peer_relation: DESCENDS_BY_ONE_COMMIT_NO_OVERWRITE
source_test: tests/tools/round061-product-mutant-workspace-verify.py
source_runner: tests/tools/round057-transaction-product.py UNCHANGED
other_changed: docs/handoff/zswapz/round062/agent5-evidence.md,docs/testing_standards.md
standards: ENTIRE_PRIOR_AND_PEER_PREFIX_PRESERVED_BYTE_IDENTICAL_SAME_COMMIT_NEW_RULES
original_first_error: https://github.com/k1moradi/swapz/actions/runs/44945987536/job/136973284092
original_first_error_text: "AssertionError: ROUND061_MUTANT_WORKSPACE_FIRST_ERROR mutant escaped compiler-owned directory"
original_cause: ALTERED_HEADER_IS_DIRECTORY_VS_ALTERED_SOURCE_IS_FILE_ORACLE_INCORRECT_PARENT
repair: CORRECT_TYPE_AWARE_EXISTING_HEADER_DIRECTORY_AND_SOURCE_FILE; RESOLVED_COMPILER_OWNERSHIP; TRUE_ESCAPED_SOURCE_ESCAPED_HEADER_AND_SYMLINK_NEGATIVE; PRIVATE_MODE_0600_EVIDENCE_OWNER_0700; BOUNDED_TRACEBACK_FREE_FIRST_ERROR
source_exact_round057_run: https://github.com/k1moradi/swapz/actions/runs/44964336818
source_exact_round057_job: 137029846018
source_exact_round057_status: COMPLETED_SUCCESS
round057_real_GCC_Clang: FULL_ACTUAL_LINKED_AUTHORITY_C_CODEC_C_STRICT_WALL_WEXTRA_WCONVERSION_WSHADOW_WERROR_ASAN_UBSAN_BASELINES_PASS
round057_semantic_mutants: GCC_5_OF_5_COMPILED_EXECUTED_SEMANTIC_KILLS_PASS_CLANG_5_OF_5_COMPILED_EXECUTED_SEMANTIC_KILLS_PASS
round057_private_workspace_negative: PASS compiler_workspaces=2 numbered_mutants=10 baseline_and_mutant_runs=12 escape_negatives=3 host_path_leak=NO private_mode=0600
round057_canonical_repository_first_parent_policy: SUCCESS
source_exact_round059_run: https://github.com/k1moradi/swapz/actions/runs/44964336868
source_exact_round059_job: 137029846355
source_exact_round059_status: COMPLETED_SUCCESS
round059_inherited_generic_lz4: 2_REAL_GCC_CLANG_BASELINES_AND_10_EXECUTED_SOURCE_MUTANTS_PASS
round059_hostile_first_error_privacy: BOTH_COMPILERS_MODE_0600_PRIVATE_NO_HOST_PATH_PASS
round059_inherited_product_GCC_Clang: REAL_AUTHORITY_C_CODEC_C_LINKED_5_OF_5_ACTUAL_SEMANTIC_MUTANTS_EACH_PASS
first_new_ci_error: NONE_IN_OWN_TWO_TERMINAL_JOBS
local_rootless_isolated_smoke: 20_POSITIVE_TYPE_CASES_3_ESCAPE_NEGATIVES_0600_0700_PRIVATE_SYMLINK_REFUSAL_PASS
local_full_repo_checkout: NOT_AVAILABLE_GITHUB_DNS_BLOCKED; REAL_SOURCE_TESTS_EXECUTED_IN_EXACT_SOURCE_HOSTED_GITHUB_CI
owner_make_privileged_loaded_physical_pressure: NOT_RUN
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_RAW_bypass: DISABLED
normal_RAW_4096: FULL_ORIGINAL_UNCOMPRESSED_4096
physical_SWAPSAPCE2_HEADER_AND_PARTITION_TABLE: UNCHANGED

Original first cause is now restored in the original standalone workflow without relaxing warnings, source identity, canonical first-parent Git policy or any semantic mutant. The inherited Round059 workflow ALSO terminated SUCCESS at the same exact source SHA. No native original STORED folio/BIO→current accepted DM source authentication, independently pinned loaded original decoder, actual durable imported lower compressed I/O, authoritative GC/read/ACK or physical production release is implied. Linux MM exclusively controls compressed RAM and natural pressure eviction; swapz disk packing/GC only. Agent5 scoped tester fix is REPORT_READY; overall Phase A remains BLOCKED.
