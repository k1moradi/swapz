# Round049 — verbatim original Agent2 and Agent3 REPORT_READY

This archived text preserves workers' historical initial CI pending statuses; Agent1 independently verified final exact source **26/26 workflow success** in [Round049 true final report](round-report.md). Official GitHub issue [#166](https://github.com/k1moradi/swapz/issues/166).

---

## Original issue comment 7035794779

https://github.com/k1moradi/swapz/issues/166#issuecomment-7035794779

message: REPORT_READY
round: "049"
worker: 3
status: OWN_SOURCE_NEGATIVE_CI_SUCCESS_LIVE_TRANSFER_NO_AUTH_COMBINED_CI_PENDING
frozen_engineering_sha: 67cb371f82fb7ea2836f2f9b5c98371c9d3af548
frozen_task_sha: 8b3111e1f93ee3fb281546d5a6973b1c7cde4436
agent3_main_one_parent_commit: 889d706d56878d0af6aab99603f4c99482d0dbe8
agent3_parent: 8b3111e1f93ee3fb281546d5a6973b1c7cde4436
publication: ONE_PARENT_NONFORCE_EXPECTED_HEAD_MAIN_FF_REMOTE_READBACK_PASS
agent3_new_original_source_audit_blob: 0edd6cc59a3ed5342cbaa84e1ae3ef9a7cc162ed
agent3_rootless_workflow_blob: e71ac7fa74ba0db65872c7433cea38a4b7e02221
agent3_evidence_blob: 96b27d8dd10e6d1ed506250836e9a0bbec0df119
canonical_complete_standards_blob: b4c0531048bb42e965396b8387d16e534da6803e
production_c_UNCHANGED_blob: d09a2e1e3348e0dc5f2cf08cdf37136141a74431
agent3_genuine_original_DM_target_source_workflow_run: 44710420609
agent3_genuine_original_DM_target_source_workflow_job: 136200397568
agent3_genuine_original_DM_target_source_workflow_status: TERMINAL_SUCCESS
agent3_26_actual_original_C_source_mutants: ALL_REJECTED_PASS
agent3_target_15_true_functions_63_anchors_12_orderings: PASS
inherited_Round048_18_real_mutants_plus_fake_export: PASS
inherited_Round043_real_C_GCC_Clang_ASAN_UBSAN_150_plus_90_7_plus_9: PASS
inherited_Round046_real_C_GCC_Clang_ASAN_UBSAN_90_plus_12: PASS
agent3_same_sha_offline_physical_safety_workflow: 44710420619_COMPLETED_SUCCESS_PHYSICAL_NOT_RUN
agent3_source_15_workflows_at_REPORT: FOUR_SUCCESS_ZERO_FAILURE_EIGHT_RUNNING_THREE_QUEUED
agent3_original_same_kernel_GPL_job: WORKFLOW_44710420644_QUEUED_AT_REPORT
agent3_systemd_package_workflow: 44710420656_IN_PROGRESS_AT_REPORT
peer_agent2_main_commit: e224257912d4b527a9b2845c596733e83adc3dbe
peer_agent2_commit_parent: 889d706d56878d0af6aab99603f4c99482d0dbe8
latest_combined_head: e224257912d4b527a9b2845c596733e83adc3dbe
peer_preserved_entire_agent3_canonical_testing_standards_prefix: TRUE_BYTE_EXACT
peer_preserved_agent3_new_audit_and_production_c_blobs: TRUE_EXACT
combined_head_registered_workflows_at_REPORT: 25
combined_head_terminal_SUCCESS: 2
combined_head_terminal_FAILURE: 0
combined_head_IN_PROGRESS: 1
combined_head_QUEUED: 22
combined_head_real_DM_source_workflow_run: 44710544160_COMPLETED_SUCCESS
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_raw_bypass: DISABLED
physical_last_first_cause: UNKNOWN

## Exact Agent3 source, genuine anchored negative checks

The official independent Round049 Agent3 change is [889d706d56878d0af6aab99603f4c99482d0dbe8](https://github.com/k1moradi/swapz/commit/889d706d56878d0af6aab99603f4c99482d0dbe8), **one-parent** child of the frozen task `8b3111e...`, direct only-main nonforce expected-head fast-forward. Its exact four changed Git blobs were read back from remote at own SHA: only NEW `tests/tools/round049-dm-target-owned-intake-audit.py`, six-line additive step in preexisting original Linux/real product rootless workflow, own `docs/handoff/zswapz/round049/agent3-evidence.md`, full prior `docs/testing_standards.md` preserved byte-for-byte prefix with own substantive appendix. **Product `src/kernel/dm-target.c` blob `d09a2e...` unchanged**, no original Linux core/composer/Agent2 MM files/GPL interface, no normal hotpath, no positive compressed lower bytes, no defaults changed.

New original-source audit uses the existing Round048 immutable pristine upstream Git blob and source validation for `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` and checks **15 exact real kernel/product C function bodies, 63 unique scoped anchors and 12 required ordering predicates**: core `__map_bio` transfers a **specific in-band target clone** only on `DM_MAPIO_SUBMITTED`, actual `clone_endio` frees the clone and calls original DM `dm_io_dec_pending`; target `swapz_map` accepts only true normal 8-sector full original 4096 UNCOMPRESSED clone, checks `ctx->accepting` again under `queue_lock`, queues `ctx->incoming` and transfers existing clone to the owner. Current `swapz_async_lower_write_done` publishes lower error before completion under queue lock and wakes ordered worker. Ordered worker finalizes only completed in-flight lower; GC snapshots CURRENT `ctx->maps[logical]`. Existing target `swapz_complete` has one `bio_endio(bio)` after terminal-error check; both deferred and direct clone ACK streams `bio_list_pop` and use this sole completion function, with offloaded list stolen once only under queue lock+atomic `completion_active` claim, and `swapz_end_io` respects terminal errors. `swapz_drain` closes admission, waits lower callbacks, drains chained/ACK worker, checks pending completion before `swapz_dtr` frees ctx. Genuine DM `__unbind` crosses SRCU table barrier. These are ACTUAL source invariants for existing normal accepted BIOs, not a new external STORED mapping lease nor an adversarial duplicate-lower callback positive proof.

**26** independently distinct real source-changing function-scoped hostile mutants are actually applied and rejected, including missing `clone_endio` original pending decrement, bypassed admission/geometry check, double `bio_endio`, offloaded/direct duplicate `swapz_complete`, failed `completion_active` claim/list transfer, stale lower error / missing lower notification/owner wake, GC historical snapshot/encoding, missing drain/dtr, ignored stale extent generation and confused original physical bdev LBA vs actual target-relative eight sectors. No mock positive transfer, source-only verdict.

## True new-source first error and CI

Actual exact-Agent3-SHA [workflow #44710420609, job 136200397568](https://github.com/k1moradi/swapz/actions/runs/44710420609/job/136200397568) **TERMINAL SUCCESS** on all steps, including original pinned Linux Git blob first, prior Round048 18 original source hostile + fabricated unexported DM table API rejection, new `ROUND049_DM_TARGET_OWNED_26_ACTUAL_SOURCE_HOSTILES_REJECTED_PASS`, `ROUND049_DM_TARGET_OWNED_ORIGINAL_CLONE_ACK_GC_DTR_NOAUTH_PASS`, `ROUND049_REAL_SOURCE_TO_CURRENT_DM_TABLE_OWNER_ACQUIRED=0`, old actual Round043 source-extracted GCC+Clang strict -Wall/-Wextra/-Wconversion/-Wshadow/-Werror ASan+UBSan old 150+90 C negatives and old seven+nine hostile, and Round046 90 C target/GC/dtr/ABA negatives and 12 source hostiles strict GCC+Clang sanitizer PASS. Verbatim source log `ROUND043_REAL_PRODUCT_MAP_INGRESS_GCC_STRICT_ASAN_UBSAN_PASS`, CLANG and `ROUND046_REAL_DM_MAP_GC_DTR_GCC_STRICT_ASAN_UBSAN_PASS`, CLANG. **First observed actual new Agent3-source error: NONE** in terminal rootless negative checks. [Round046 rootless #44710420542](https://github.com/k1moradi/swapz/actions/runs/44710420542) SUCCESS, [offline rootless physical policy #44710420619](https://github.com/k1moradi/swapz/actions/runs/44710420619) SUCCESS, PHYSICAL NOT_RUN. At report exact own SHA 15 registered workflows, 4 successful, none failed, 8 running, 3 queued; importantly original same-KDIR GPL matched full original pinned kernel [#44710420644](https://github.com/k1moradi/swapz/actions/runs/44710420644) queued and Systemd/package [#44710420656](https://github.com/k1moradi/swapz/actions/runs/44710420656) in progress. **Do not claim whole own SHA green or true new source 55/55 from historical predecessor.**

Historical frozen engineering [67cb371f](https://github.com/k1moradi/swapz/commit/67cb371f82fb7ea2836f2f9b5c98371c9d3af548) had true 16/16 PASS including genuine original Linux 55/55 booted UML independent JSON+KTAP + original x86 both CONFIG_ZSWAP=y/n full vmlinux/modules/Module.symvers unique original GPL and actual same ORIGINAL KDIR matched `dm-swapz.ko` W=1/-Werror; old original strict C GCC/Clang/native x86/ARM passed. This is ANCESTOR qualification, not current combined proof.

## Peer and full canonical preservation

Independently Agent2 published [e224257912d4b527a9b2845c596733e83adc3dbe](https://github.com/k1moradi/swapz/commit/e224257912d4b527a9b2845c596733e83adc3dbe), one-parent CHILD of my 889d706, adding its separate genuine original Linux counted source acquisition/paired release verifier and original composed KUnit workflow, and append-only own standards. I VERIFIED exact latest combined head has my entire **1,381,260-byte** standards as BYTE-EXACT prefix followed by Agent2 new appendix; preserves original one-byte hygiene fix and exact new audit blob `0edd6cc...`, unchanged real product C blob `d09a...`. Combined current SHA at check 25 workflows: **2 terminal success, zero failure, one in progress, 22 queued**; combined original DM source [#44710544160](https://github.com/k1moradi/swapz/actions/runs/44710544160) terminal SUCCESS, but new Agent2 original full kernel 55+N, both x86 y/n/full GPL Kbuild and many other native/package/policy workflows not terminal. No peer dependent changes, no branches/PRs/force.

## Future ONLY separately tagged lower-I/O LZ4 contract and unresolved first owner

Own design in [Round049 Agent3 evidence](https://github.com/k1moradi/swapz/blob/889d706d56878d0af6aab99603f4c99482d0dbe8/docs/handoff/zswapz/round049/agent3-evidence.md) specifies a BOUNDED separate RAM-only transaction descriptor, NOT implemented, only on genuine core-delivered in-band current target-clone, after original Linux legal current locked swapcache-folio counted slot/incarnation source ref legitimately acquired and retained through async. Private original genuine STORED dictionary-free LZ4 codec/version/length/bounded bytes, compressed CRC32C, original fully UNCOMPRESSED 4096 SHA, original bdev/possibly nonlinear physical source sector **separate** from currently validated 8-sector target-relative interval, current map/GC/extent/dtr and one-shot completion owner required. Future sequence SOURCE_OWNER_HELD → TARGET_CLONE_ADMITTED → PAYLOAD_VERIFIED → EXTENT_RESERVED → LOWER_SUBMITTED → LOWER_DURABLE including FUA/flush → ONE CURRENT_MAP_PUBLISHED → ONE ORIGINAL UPPER ACK via clone_endio → source ref release → later lower READ decoded original 4096 verified by full SHA. Duplicate callback, stale table/reload/GC ABA, source recycle, ENOSPC, lower error, unwind must not acknowledge false success or double free. **Neither real cross-boundary owner nor compressed transport nor durable mapping nor true upper original ACK is established**. Original DM `dm_get_live_table/put` are not exported; numerical pointers/cookies are not a new source-to-current-DM ref. Phase A still BLOCKED.

Zswap exclusively owns bounded compressed RAM and native MM natural pressure eviction; swapz exclusively uses valid preexisting SWAPSPACE2 DISK compressed payload-only extents 4/8/16KiB and GC, NO competing RAM reclaim or forced zswap drain. Ordinary RAW_4096 always ENTIRE ORIGINAL UNCOMPRESSED 4096; already STORED LZ4 never masquerades as upper RAW. Entire FIRST physical 4096 SWAPSPACE2 header/UUID/signature and partition table IMMUTABLE, no new on-media metadata/SWAPZ001. Old owner physical producer_refused first error cause UNKNOWN, recovery owner-reported only. No `make test`, `make fast_test`, privilege, loaded DM, null_blk, physical, real pressure, swapoff/swapon/mkswap or reboot. Keep `SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED FORCED_RAW_BYPASS=DISABLED`.

---

## Original issue comment 7035904076

https://github.com/k1moradi/swapz/issues/166#issuecomment-7035904076

message: REPORT_READY
round: "049"
worker: 2
status: REAL_ORIGINAL_C_LOCKED_FOLIO_LOCAL_COUNTED_PAIR_DEFAULT_DISABLED_57_KUNIT_REGISTERED_NEW_SOURCE_CI_PENDING_NO_AUTH
frozen_engineering_sha: 67cb371f82fb7ea2836f2f9b5c98371c9d3af548
frozen_task_sha: 8b3111e1f93ee3fb281546d5a6973b1c7cde4436
agent2_published_main_sha: e224257912d4b527a9b2845c596733e83adc3dbe
agent2_exact_one_parent: 889d706d56878d0af6aab99603f4c99482d0dbe8
original_pinned_upstream_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
source_compositor_git_blob: d98a05c7ecee847166ca53147c580fc69cef7cbb
source_original_kunit_verifier_blob: 0a3ddcc7aec452a723618c210e56e4c1b2146f03
source_original_staged_hostile_blob: 0c1e0db4079f748be09e9c07148260cb8007bb2c
original_workflow_blob: 46452fd4e3c70f009d6d4399c6760267bcacbd63
full_standards_exact_blob: 5e751fe391012e8543cb32b6957f01f73effbd68
agent2_substantive_standards_bytes_added: 3525
rootless_exact_commit_diff_hygiene: ZERO_TRAILING_WHITESPACE_6_INTENDED_FILES_ONE_PARENT
original_55_inherited_kunit: PRESERVED
new_original_compiled_kunit_registered: 2
new_57_original_real_uml_boot_status: QUEUED_NOT_GREEN
new_genuine_original_uml_run: 44710543990
new_genuine_original_uml_job: 136200809084
original_x86_y_n_same_original_kernel_matched_gpl_module_job: 136200808641
original_x86_y_n_new_sha_status: QUEUED_NOT_GREEN
new_source_registered_workflows: 25
new_source_success_at_latest_check: 4
new_source_failed_at_latest_check: 0
new_source_in_progress_at_latest_check: 3
new_source_queued_at_latest_check: 18
new_source_first_failure: NONE_OBSERVED_BUT_NOT_ALL_TERMINAL
source_mapped_authenticated: 0
phase_a: BLOCKED

**Exclusive Agent2 original source published** [commit e224257912d4b527a9b2845c596733e83adc3dbe](https://github.com/k1moradi/swapz/commit/e224257912d4b527a9b2845c596733e83adc3dbe), direct sole main one-parent expected-head nonforce FF on **peer-inclusive** 889d706d56878d0af6aab99603f4c99482d0dbe8 (Agent3 already committed); verified GitHub parent, files and remote head, no branch/PR/fork/worktree/force. Only Agent2-owned `tests/tools/stage-pinned-linux-zswap-composed.py`, original source workflow, two new own Round049 verifiers, own `docs/handoff/zswapz/round049/agent2-evidence.md`, and complete `docs/testing_standards.md` appended. Exact previous 1,381,260-byte canonical standards (includes all Agent3 work and Agent1 one-byte whitespace fix) unchanged as byte-for-byte prefix; 3,525 new standard bytes only. Actual GitHub diff 6 files, ZERO newly added trailing whitespace. No production original kernel source fork, no actual product `src/kernel/dm-target.c` changes.

**Authentic original C counted acquisition and safe immediate release (source-scope only):** In original `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`, `mm/swapfile.c::folio_dup_swap(folio,NULL)` requires a genuinely CURRENT **locked swapcache folio** and holds original slot cluster lock, with atomic extended-table allocation/restart and partial rollback on failure. Distinct `swap_dup_entry_direct` needs preexisting PTE/PTL count and is invalid for copied slot/epoch. Exact source-counted matching **local put** is `folio_put_swap(folio,NULL)` while SAME original folio remains locked; it uses `swap_put_entries_cluster(...,false)`, no new area tryget on potentially draining swapoff, and no cache reclaim. New guarded C helper `swapz_round049_original_locked_folio_counted_pair` is inserted at TRUE ORIGINAL `mm/zswap.c::zswap_writeback_entry` **after** genuine exact old zswap xarray match + decompression and **before** original `xa_erase`, STORED free, folio unlock and `REQ_SWAP` submission. It validates non-NULL original slot/store/tree/folio, folio locked+current swapcache, exact `folio->swap` type+offset and still current xarray pointer. Only on valid source does `folio_dup_swap` run, followed by EXACTLY ONE synchronous original `folio_put_swap`; on -ENOMEM/other original duplicate failure, no put and existing error path removes/unlocks/puts folio. **NO counted external reference remains after helper return**, no slot incarnation retained across async source exit, no DM handoff. This changes NOTHING in default builds: `SWAPZ_ROUND049_ORIGINAL_LOCKED_FOLIO_COUNT_PAIR_TEST` is DEFAULT UNDEFINED plus CONFIG_KUNIT-only.

**TWO genuinely registered ORIGINAL C KUnit cases, not mocks:** New same-source KUnit suite `swapz_round049_original_locked_folio_counted_pair_no_authority` registers `swapz_round049_missing_original_owner_kunit` (actual original zswap_entry and xarray, missing source owner rejected -EINVAL) and `swapz_round049_unlocked_uncached_folio_kunit` (real original kernel `folio_alloc(GFP_KERNEL,0)`, reject unlocked folio -ESTALE, then real `folio_lock` reject locked but NON-swapcache folio -ESTALE, balance `folio_unlock/folio_put/xa_destroy`). Both call the actual genuine original C helper, not standalone model; **neither invokes a live positive counted slot without a real active swap area** and no live pressure or physical swap is exercised. New independent strict original `round049-original-counted-pair-kunit-verify.py` verifies inherited 55 genuine C KUnit, requires exactly TWO newly registered and booted original cases in independent original JSON AND KTAP for real **57/57**. Its selftest requires 23 genuinely changed hostile JSON/count/status/KTAP mutants be rejected; synthetic selftest samples NOT accepted as kernel boot. New `round049-original-counted-pair-source-verify.py` requires exact true original staged C source guard, real locked folio/xarray source ordering and balanced exact count, existing original error path and no exported source token, and **12 genuinely changed function-scoped original C hostile mutants**. Independent source audit preflight confirmed all 12 exact hostile C regions have exactly one target anchor when injected into pristine source; inherited old 18+16 source negative controls remain in true workflows.

**FIRST missing real authority:** Valid source-only local immediate counted increment+decrement **is NOT an independently retained or transferred original allocation-incarnation ref** across STORED retirement, asynchronous BIO completion, swapoff, slot recycle/ABA or external owner. Direct `swap_put_entries_direct` after leaving original source would require a genuinely PREVIOUSLY HELD counted current slot and valid independent owner/area lifetime; cannot mint one from copied sector/epoch or STORED SHA/CRC. Original source bdev/possibly nonlinear physical swapfile 512-sector index cannot establish the *current* target-relative 8-sector DM table/GC/dtr lease. Without both refs and real durable lower WRITE→single current map→one actual upper BIO ACK→full original decoded 4096 SHA readback, SOURCE_MAPPED_AUTHENTICATED=0 and PHASE_A=BLOCKED.

**NEW source CI exact e224257912d4b527a9b2845c596733e83adc3dbe (NOT AN ANCESTOR PASS):** The new [original real 57 UML and full original x86 ZSWAP=y/n/unique GPL matched actual dm-swapz.ko run #44710543990](https://github.com/k1moradi/swapz/actions/runs/44710543990) has UML [job 136200809084](https://github.com/k1moradi/swapz/actions/runs/44710543990/job/136200809084) and full x86 [job 136200808641](https://github.com/k1moradi/swapz/actions/runs/44710543990/job/136200808641) **QUEUED at latest inspection**. Source changing compositor triggers 25 exact-SHA original inherited and product/native/systemd/offline safety gates: 4 success, 0 fail, 3 running, 18 queued. No first NEW source failure observed yet; **DO NOT CLAIM 57 boot or exact-SHA original matched full GPL PASS before jobs terminal**. Ancestor Round048 #44691055218 genuine original 55/55 and x86 both success belongs to prior source 67cb371f only. All inherited actual production source-extracted GNU11 GCC+Clang Werror ASan/UBSan, old 150+90 and hostile 7+9+12, native x86/ARM and offline patch-hygiene still mandatory and not waived; new kernel-only helper requires actual original x86/UML compile and is NOT falsely claimed as Clang host pressure test.

**NO privileged/real swap:** zswap exclusively bounded compressed RAM with natural native Linux MM pressure eviction; swapz solely valid physical SWAPSPACE2 disk payload-only 4/8/16KiB compression packing GC. Ordinary upper RAW_4096 always original full **UNCOMPRESSED** 4096; original dictionary-free STORED LZ4 future separately tagged lower staging **disabled**, no second reclaim controller. Entire FIRST physical 4096 SWAPSPACE2 header/signature/UUID and partition table immutable. Previous owner local physical `make test` producer_refused first private cause UNKNOWN, recovery owner-reported only. NO `make test`/`make fast_test`, physical/loaded/privileged/real memory pressure, DM activation/swapoff/on/mkswap/null_blk/reboot. `SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED FORCED_RAW_BYPASS=DISABLED`.
