# Round050 ORIGINAL worker GitHub REPORT_READY comments and Agent2 source-CI addendum — verbatim (historical statuses)

Original Round050 [issue #167](https://github.com/k1moradi/swapz/issues/167). Retain worker original language/first errors and initial queued statuses verbatim below; independent final [Agent1 exact source 3 green/1 policy RED closeout](round-report.md) supersedes earlier interim CI checkpoints. Do not count initial pending as green.

---

## Worker original comment 7037878483

https://github.com/k1moradi/swapz/issues/167#issuecomment-7037878483

message: REPORT_READY
round: "050"
worker: 2
status: PUBLISHED_ROOTLESS_PRISTINE_ORIGINAL_DEFERRED_COUNTED_SLOT_SOURCE_NEGATIVE_NO_AUTH_NEW_SHA_CI_RUNNING_NOT_ALL_GREEN
frozen_engineering_sha: e224257912d4b527a9b2845c596733e83adc3dbe
frozen_full_task_sha: 42399b214b43dfe71020e0440dac04157b7e527f
agent2_exact_published_main_commit: 03bb7087bfd16a544c1156ae1135310d84c5bdc9
exact_one_parent: 42399b214b43dfe71020e0440dac04157b7e527f
original_linux_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
new_original_source_audit_blob: 9bbf8a39911652d089b29831ccd5730f65b6d139
new_source_workflow_blob: 8b9ae9c6ef58e1f19509b539653f2432976ac111
new_evidence_blob: 811833297a66c412cbac3589bafcdb466d0d15ae
complete_standards_blob: c55dc3f66aaaba7e1455ed4de8df3fbd8ce32511
complete_previous_standards_bytes_preserved_byte_exact_prefix: 1384785
new_meaningful_standards_appendix_bytes: 4275
genuine_original_57_registered_c_kunit_preserved: YES_NO_NEW_FAKE_CASES
new_original_exact_source_hostile_mutations: 16_FUNCTION_SCOPED_NONVACUOUS
inherited_round047_hostiles: 18
inherited_round048_hostiles: 16
inherited_round049_hostile_original_C_source: 12
inherited_round049_JSON_KTAP_hostile_verifier: 23
real_original_uml_and_y_n_x86_gpl_dm_run: 44723994718
new_original_uml_real_c_kunit_job: 136246667930
new_original_x86_y_n_full_matched_gpl_dm_job: 136246667337
new_source_ci_registered_workflows_at_checkpoint: 16
new_source_ci_terminal_success_at_checkpoint: 2
new_source_ci_failure_at_checkpoint: 0
new_source_ci_running_at_checkpoint: 8
new_source_ci_queued_at_checkpoint: 6
current_first_real_ci_error: NONE_OBSERVED_NEW_SOURCE_CI_INCOMPLETE
local_repo_checkout_status: NO_LOCAL_GITHUB_DNS_UNAVAILABLE_GITHUB_CONNECTED_IMMUTABLE_SOURCE_PREFLIGHT
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_raw_bypass: DISABLED

**Agent2 source and publication:** [exact one-parent direct main nonforce expected-head FF commit 03bb7087bfd16a544c1156ae1135310d84c5bdc9](https://github.com/k1moradi/swapz/commit/03bb7087bfd16a544c1156ae1135310d84c5bdc9), sole parent full frozen Round050 task 42399b214b43dfe71020e0440dac04157b7e527f. Remote main readback identical, exactly four OWN files changed: new `tests/tools/round050-original-deferred-slot-source-audit.py`, original-source workflow, `docs/handoff/zswapz/round050/agent2-evidence.md`, and meaningful `docs/testing_standards.md` appendix. No production C, original composer or Agent3 target C changes; no branch/PR/fork/worktree/force. Complete preexisting 1,384,785 standards bytes (including Agent1 whitespace correction and all peer prior changes) are an unchanged exact prefix, 4,275 owned bytes appended. GitHub exact diff confirms 0 deletions, zero newly added trailing whitespace.

**FIRST genuine missing original counted-slot async ownership guarantee:** The actual pinned original `mm/swapfile.c::folio_dup_swap(folio,NULL)` only ACQUIRES a count from a current locked swapcache folio; Round049 genuine original guarded synchronous `folio_dup_swap`→`folio_put_swap` leaves ZERO extra ref after source helper returns, both new genuine original C KUnit cases tested invalid folios, NOT a positive real count. `folio_put_swap` needs the SAME locked current folio and cannot safely run after swapcache removal/folio unlock. `swap_put_entries_direct(entry,nr)` is VOID, requires genuinely pre-owned protected direct count, tries new `get_swap_device` area users with `percpu_ref_tryget_live`, and warns+RETURNS with NO COUNT PUT if area unavailable, so a copied type/offset/epoch/SHA is no release ownership guarantee.

**Precise swapoff vs hidden async count:** ORIGINAL `SYSCALL_DEFINE1(swapoff)` calls `try_to_unuse` BEFORE `percpu_ref_kill(&p->users)`, RCU/users wait, original extent/table teardown and swap-type reuse. `try_to_unuse` drains shmem, page-table refs, live swapcache folios and **retries while `swap_usage_in_pages(si)` remains nonzero**. A hypothetical extra **hidden/untracked** external counted ref with no independent guaranteed callback/abort put may keep `swap_usage` nonzero but be unobservable to original `unuse_mm`/swapcache walker, causing continued retries or `-EINTR` swapoff failure. Do NOT claim live area inevitably gets killed while a valid outstanding counted slot still exists: that would misstate the true ordering. The first required but nonexistent protocol is an ACTUALLY OWNED counted current incarnation transferred to a bounded callback whose release is guaranteed exactly once on success/error/abort/reissue/swapoff and cannot depend on a drain waiting for itself. No such acquisition/transfer/callback put exists in original `mm/zswap.c::zswap_writeback_entry` or `mm/page_io.c::end_swap_bio_write`. Original area get is put before original STORED xarray recheck/decompress/erase/free and before ordinary full uncompressed 4096 original BIO. External copied original sector/bdev cannot prove current DM table/GC/dtr target-relative eight-sector lease.

**True rootless negative evidence:** New source tool checks seven exact pristine immutable ORIGINAL Git blobs, old six plus private `mm/swap.h` sha `d5bf21f517dceae58eb94fb0ce5f4e1fdc679409`. Original actual C `try_to_unuse` retry on hidden counted slot, `swapoff` unuse-before-users-kill order, `get_swap_device_info` live-tryget, direct put void/refuse, real original folio locked dup/put and atomic extended-table rollback, folio invalidation/recycled slot and original BIO callback no external source count put all verified in named functions. 16 independently changed hostile mutations inside named pristine original C functions are checked each for exactly-one original target and rejection. The immutable GitHub original C preflight confirmed 16/16 unique anchors; source CI runs 16 full Python hostile `--self-test` in ORIGINAL pristine checkout BEFORE composing source in BOTH true pinned original Linux UML and x86 jobs, preserving entire previous negative audit.

**Exact new-SHA CI is NOT green yet:** [true pinned original UML 57 real C JSON+KTAP and real full original x86 ZSWAP=y/n unique GPL provider/probe matched dm-swapz.ko same ORIGINAL KDIR #44723994718](https://github.com/k1moradi/swapz/actions/runs/44723994718) UML [job 136246667930](https://github.com/k1moradi/swapz/actions/runs/44723994718/job/136246667930) in progress at runner setup; x86 [job 136246667337](https://github.com/k1moradi/swapz/actions/runs/44723994718/job/136246667337) in progress installing original prerequisites. Exactly 16 current source workflows registered, **2 SUCCESS, 0 FAILURE, 8 IN PROGRESS, 6 QUEUED** at checkpoint; strict inherited original C GCC/Clang Werror ASan+UBSan, production original matched GPL, x86/ARM native/policy, package/systemd and physical OFFLINE still pending. No first *new-SHA* compiler/sanitizer/KUnit error observed; ancestor Round049 26/26 and 57/57 PASS at e2242579 cannot be reported as same-source green. Original system immutable 57 C cases (55+2) preserved; intentionally **NO FAKE NEW C KUNIT** from synthetic held token because no genuine live counted slot or safe deferred source owner is available without prohibited live pressure.

**Boundary remains NO GO:** Original real full RAW_4096 always ORIGINAL UNCOMPRESSED 4096, Linux zswap solely bounded compressed RAM with native MM natural pressure eviction, swapz solely valid preformatted SWAPSPACE2 DISK 4/8/16KiB compressed packing/GC, no competing reclaim scheduler. Future distinct privately tagged authentic STORED dictionary-free LZ4 lower I/O remains DISABLED pending actual counted source slot STORED identity/CRC/full original 4096 SHA and original backing bdev NONLINEAR absolute sector→current real live DM table/GC/dtr target-relative eight-sector owned mapping + durable lower WRITE→one current authoritative map→ONE true original upper BIO ACK→full original SHA-verified READ. Entire physical FIRST 4096 SWAPSPACE2 header/signature/UUID and partition table immutable. Previous physical owner `make test` producer_refused first private cause UNKNOWN, owner recovery reported only; NO make test/fast_test, privilege, loaded/physical swap/real memory pressure, swapoff/on/mkswap/DM/null_blk/reboot. `SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED FORCED_RAW_BYPASS=DISABLED`.

---

## Worker original comment 7037902939

https://github.com/k1moradi/swapz/issues/167#issuecomment-7037902939

message: AGENT2_ROUND050_EXACT_SOURCE_CI_ADDENDUM
round: "050"
worker: 2
source_sha: 03bb7087bfd16a544c1156ae1135310d84c5bdc9
parent_sha: 42399b214b43dfe71020e0440dac04157b7e527f
source_auth: 0
phase_a: BLOCKED

**True new-source first stage verified:** In actual [original Linux #44723994718](https://github.com/k1moradi/swapz/actions/runs/44723994718), true UML [job 136246667930](https://github.com/k1moradi/swapz/actions/runs/44723994718/job/136246667930) steps **"Real original source-extracted GCC Clang ASan UBSan and verifier hostile cases"** and **"Stage exact pristine original Linux source and SHA-verify ten files"** both have completed SUCCESS. Its new 7-Git-blob Round050 `--self-test` containing 16 genuinely changed function-scoped original swapoff/hidden-ref source mutations runs in the first of those steps, and all inherited original source hostile + real extracted sanitizer tests remain in place. Actual x86 [job 136246667337](https://github.com/k1moradi/swapz/actions/runs/44723994718/job/136246667337) step **"Stage exact original source and validate all manifest SHA256"** completed SUCCESS; that real pinned original Linux staging step executes the new 16-hostile source audit before original C composition. Therefore original pristine negative source/test/manifest staging PASSED on exactly 03bb7087, not merely a manually guessed source anchor.

**Not yet green:** genuine actual original CONFIG_ZSWAP=y UML full **57/57 booted KUnit JSON AND KTAP** and BOTH original x86 CONFIG_ZSWAP=y/n full vmlinux/modules/Module.symvers unique original GPL provider/probe and real same-original-KDIR dm-swapz.ko strict W=1/-Werror were **IN PROGRESS** at this checkpoint, not reported as PASS. GitHub head-SHA check registered exactly **16 workflows: 4 SUCCESS, 0 FAILURE, 12 IN PROGRESS**; no first new-SHA compiler/sanitizer/kernel error observed. The previous engineering 26/26 and 57/57 belong only to e2242579.

**No runtime change/auth:** 57 C cases unchanged; NO new fake original acquisition/retained count KUnit, NO DM source admission, no original live pressure/physical or privilege. First blocker remains original try_to_unuse pre-percpu_ref_kill hidden counted slot drain with no independently guaranteed callback/abort exactly-once put owner, and void swap_put_entries_direct never authorizes a copied slot. SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED FORCED_RAW_BYPASS=DISABLED; upper RAW_4096 is original full UNCOMPRESSED 4096.

---

## Worker original comment 7038253901

https://github.com/k1moradi/swapz/issues/167#issuecomment-7038253901

message: REPORT_READY
round: "050"
worker: 3
status: REAL_EXTRACTED_PRODUCTION_C_GCC_CLANG_159x2_AND_22x2_HOSTILES_TERMINAL_SUCCESS_FULL_NEW_SHA_KERNEL_GPL_AND_REPO_CI_PENDING
frozen_engineering_sha: e224257912d4b527a9b2845c596733e83adc3dbe
frozen_task_sha: 42399b214b43dfe71020e0440dac04157b7e527f
final_own_and_current_main_sha: d98aa016682275fa9f18fd9debd6553870a8a5a2
final_parent: 7bdc32a0e135b7890b44ea777a38be2b05af869f
direct_main: ONE_PARENT_EXPECTED_HEAD_NONFORCE_FAST_FORWARDS_ONLY_NO_BRANCHES_PRS_FORCE
agent2_parent_commit: 03bb7087bfd16a544c1156ae1135310d84c5bdc9
agent2_parent: 42399b214b43dfe71020e0440dac04157b7e527f
agent3_initial_engineering_commit: e13d01e7bd2f98e49c7cef022bf527036547975d
agent3_initial_parent: 03bb7087bfd16a544c1156ae1135310d84c5bdc9
agent3_first_source_verifier_fix: 72a25cea78a85692797dc60fd3bbee2ff0ff25a4
agent3_first_fix_parent: e13d01e7bd2f98e49c7cef022bf527036547975d
agent3_original_gpl_guard_verifier_fix: 7bdc32a0e135b7890b44ea777a38be2b05af869f
agent3_original_gpl_guard_fix_parent: 72a25cea78a85692797dc60fd3bbee2ff0ff25a4
agent3_strict_host_annotation_and_mutant_execution_fix: d98aa016682275fa9f18fd9debd6553870a8a5a2
agent3_strict_host_fix_parent: 7bdc32a0e135b7890b44ea777a38be2b05af869f
product_actual_C_blob: ba24b895833389fcd29a312b544a69ff158312dc
actual_extracted_host_fixture_blob: 02042f6f13abe59b1904f6fd9643f638c5eb568d
strict_real_C_verifier_blob: c08581700f336e08974c2f09649d432c25eec8b0
original_DM_rootless_workflow_blob: bf6d07a0be75d4ddddab6a4159eebcab3963c04d
agent3_source_evidence_blob: 495f8d808f6a18342306a4868e475b65d0b3fddf
whole_peer_plus_existing_testing_standards_append_only_blob: 2647454836901d630d5f853255149b22d36e127b
original_round033_guard_scope_verifier_blob: 5358a583c03f9a28d17d193fdfddfb60bcf14d02
new_SOURCE_exact_rootless_workflow: 44726291945
new_SOURCE_exact_rootless_job: 136254442277
new_SOURCE_exact_rootless_status: COMPLETED_SUCCESS
new_SOURCE_exact_gcc_strict_ASAN_UBSAN_159_real_C_negatives: PASS
new_SOURCE_exact_clang_strict_ASAN_UBSAN_159_real_C_negatives: PASS
new_SOURCE_exact_22_actual_C_guard_mutants_rejected_by_validator: PASS
new_SOURCE_exact_22_actual_C_guard_mutant_binaries_each_GCC_AND_Clang: 44_RUNTIME_FIRST_CASE_ORACLES_REJECTED_PASS
inherited_Round048_18_real_source_mutants_and_fabricated_export: PASS
inherited_Round049_26_source_mutants: PASS
inherited_Round043_150_plus_90_original_product_C_GCC_Clang_ASAN_UBSAN_7_plus_9_source_mutants: PASS
inherited_Round046_90_original_product_C_GCC_Clang_ASAN_UBSAN_12_source_mutants: PASS
new_SOURCE_exact_workflows_at_report: FOUR_REGISTERED_ONE_TERMINAL_SUCCESS_ZERO_FAILURE_ONE_RUNNING_TWO_QUEUED
new_SOURCE_genuine_full_original_57_KUnit_and_original_both_x86_y_n_matched_GPL_DM: NOT_YET_TERMINALLY_VERIFIED_AT_NEW_SHA
new_SOURCE_systemd_package_workflow: 44726291947_IN_PROGRESS
new_SOURCE_native_kernel_workflow: 44726292045_QUEUED
new_SOURCE_production_C_workflow: 44726291950_QUEUED
physical: NOT_RUN
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: DISABLED
forced_raw_bypass: DISABLED

## Actual Agent3 implementation and real C results

Independent own direct-main initial engineering commit [e13d01e7bd2f98e49c7cef022bf527036547975d](https://github.com/k1moradi/swapz/commit/e13d01e7bd2f98e49c7cef022bf527036547975d) after peer Agent2 one-parent 03bb7087, then transparent minimal corrective one-parent commits [72a25cea](https://github.com/k1moradi/swapz/commit/72a25cea78a85692797dc60fd3bbee2ff0ff25a4), [7bdc32a0](https://github.com/k1moradi/swapz/commit/7bdc32a0e135b7890b44ea777a38be2b05af869f), final [d98aa016](https://github.com/k1moradi/swapz/commit/d98aa016682275fa9f18fd9debd6553870a8a5a2). Every publication expected remote head, one parent, nonforce fast-forward on **only main**, no branches/PR. Preserved Agent2 original MM source audit and workflow, 57 original genuine C KUnit cases, all earlier tests and full 1.38 MB testing standards byte-for-byte as inherited prefix then unique substantive Round050 appendix, Agent1 one-byte standards hygiene fix preserved.

Actual production `src/kernel/dm-target.c` adds only DEFAULT-UNDEFINED `#if defined(SWAPZ_ROUND050_DM_ONE_SHOT_NEGATIVE_TEST)` observed C regions and bounded stack-only scalar `swapz_round050_dm_pending_report`. Without macro, original normal source is byte-identical to previous product after two guarded additions removed. Optional actual `swapz_map` call runs synchronously only after original true eight-sector geometry gate, before per-BIO initialization, with **both synthetic reports NULL and return ignored**. Actual `swapz_round050_dm_one_shot_refuse` uses read-only genuine `struct dm_target`, `struct swapz_dm`, `struct bio` and current ctx pointers; rejects closed/dtr, stale target/ctx/authority, incorrect source absolute vs current target-relative 8-sector domain, table/callback/GC/map ABA, malformed 1/2/4-block extents/compressed length/CRC, duplicate clone ACK and lower callback, non-durable lower bytes, absent/duplicate map. Even with apparently matching fake live MM/DM/durable tickets it **unconditionally returns -EOPNOTSUPP**; never initiates actual I/O, map, GC or ACK, no external ABI/lock/hotpath/reclaim change. This does not prevent external post-free UAF; such callback is forbidden without an actual owner.

New `tests/tools/round050-dm-one-shot-real-c-verify.py` verifies 42 unique real source anchors/11 order predicates and extracts actual product guard C and exact real `swapz_map` callsite into `tests/runtime/native/fixtures/round050-dm-one-shot-host.c`. Actual [rootless CI #44726291945 job 136254442277](https://github.com/k1moradi/swapz/actions/runs/44726291945/job/136254442277) terminal **SUCCESS**, exact log:
`ROUND050_REAL_PRODUCT_ONE_SHOT_22_HOSTILE_SOURCE_MUTANTS_REJECTED_PASS`;
`ROUND050_REAL_PRODUCT_ONE_SHOT_GCC_STRICT_ASAN_UBSAN_PASS`;
`ROUND050_REAL_PRODUCT_ONE_SHOT_CLANG_STRICT_ASAN_UBSAN_PASS`;
`ROUND050_REAL_PRODUCT_22_HOSTILE_C_BINARIES_GCC_CLANG_REJECTED_PASS`.
Both real GCC and Clang `-std=gnu11 -Wall -Wextra -Wconversion -Wshadow -Werror -fsanitize=address,undefined -fno-sanitize-recover=all` compile and RUN **159** negative C cases per compiler: 53 fault classes across 1/2/4 original 4096-byte extent blocks. Both compile each of **22 distinct actual mutated original production C helpers** and assert their true C first exact-negative oracle fails: 44 separately compiled HOSTILE sanitizer executables. The final test counter requires precisely 2 compiler baselines + 44 actual hostiles before PASS marker. Pinned original source [Round048 18 hostile+fake GPL export], Round049 26 original target hostile, original Round043 GCC+Clang old 150+90 and 7+9, Round046 real GCC+Clang 90+12 ALL additionally passed on exact d98 SHA in SAME workflow. There is no physical device, original source ref/lease, actual durable lower WRITE, authoritative map or real original ACK in this synthetic host.

## Transparent historical first errors and exact fixes

Initial own SHA e13d01e, new Round050 step #44724883126 job 136249655285 **RED first**: genuine original production C `swapz_gc_relocate_one` is `static int`, while the new verifier mistakenly expected `static void`. Fixed ONLY the verifier C source signature in one-parent commit 72a25cea, preserving original test count.

Second old inherited [Round033 real original GPL source #44724883248 job 136249656021](https://github.com/k1moradi/swapz/actions/runs/44724883248/job/136249656021) at e13d01e failed preexisting brittle false-positive `AssertionError: unprotected original GPL symbol`: source already contained EXACTLY TWO legitimate separately **guarded** original GPL v1 snapshot calls (original Round033 helper and nested Round043 original live observer), while the older verifier counted one and falsely labelled the second unguarded. Corrected in 7bdc32a0 to require exactly one in each actual guarded source region and **reject any third/unprotected use**; did not remove symbol tests/guards/positive detection or production source. This was not new runtime use or a kernel symbol leak.

Third actual rootless [#44725104404 job 136250402842](https://github.com/k1moradi/swapz/actions/runs/44725104404/job/136250402842) at 72a25cea **RED first GCC error:** `static __used noinline int` extracted actual product C but host shim supplied `__used` and lacked original kernel `noinline` annotation; Clang same missing noinline. Fixed host-only macro in final d98aa016 and fixed test harness misleading PASS print: new counters refuse to claim 44 hostile C executions unless ALL 44 actually compiled and passed the strict first-failing oracle. No production path, ABI, safety gate, or original test was weakened. **First real error on corrected exact d98 rootless source tests: NONE**; see terminal SUCCESS and actual GCC/Clang logs. This transparent chain is why previous SHA RED must not be reported green.

**Entire new exact source CI NOT ALL GREEN YET.** At report GET head_sha=d98aa016... GitHub registered **4** workflows: true new source extracted DM rootless **1 terminal success**, Systemd/package #44726291947 IN PROGRESS, native #44726292045 QUEUED, experimental C #44726291950 QUEUED; zero terminal failure. The genuine original pristine Linux booted **57/57** independent JSON+KTAP and original x86 **BOTH ZSWAP=y/n full vmlinux/modules/Module.symvers** unique GPL provider and true same-original-KDIR matched `dm-swapz.ko` W=1/-Werror passed at FROZEN ENGINEERING e224257... 26/26 only; **NOT yet verified on corrected new d98 SHA**. GitHub workflow throttling/registering and pending original builds cannot be called SUCCESS. If full new-source CI fails, first actual new source-log error must be investigated; no false final all-green.

## Codec and first missing genuine owner

Original pinned upstream Linux `mm/zswap.c` STORED entry uses runtime selected `crypto_acomp` tfm_name and can hold raw PAGE_SIZE 4096 or compressed length up to <4096; actual swapz volatile `src/kernel/codec.h` caps `SWAPZ_MAX_COMPRESSED` at **3568** and defines `SWAPZ_ENCODING_LZ4=0` with other delta64/shuf8 predictors. Real current swapz decoder uses `LZ4_decompress_safe` only on matching plain LZ4 map encoding, others transform the bytes. Original zswap compressor name, block/framing/dictionary, length, CRC, map codec and full 4096 decoded SHA are not automatically compatible. No STORED LZ4 bytes may be staged in current compressed disk map merely by copying original compressed buffer; length >3568, raw original 4096, codec mismatch fail. Ordinary RAW_4096 remains full original uncompressed 4096.

First absent **true independently held original current counted type+offset swap-slot allocation-incarnation owner retained beyond original locked-folio return**, and independent CURRENT DM table/target/GC/dtr live lease spanning callback/reload, plus durable lower WRITE→one current map→ONE genuine original upper ACK→later full original 4096 decoded SHA READ. No artificial `EXPORT_SYMBOL_GPL(dm_get_live_table)`, no scalar pointer/ticket/SHA treated as owner. Zswap only bounded compressed RAM with natural Linux MM pressure eviction; swapz only valid initialized SWAPSPACE2 DISK payload compression 4/8/16KiB and GC, no competing reclaim. Entire first physical 4096 SWAPSPACE2 header/signature/UUID and partition table IMMUTABLE, no on-media sidecars. Old owner physical `producer_refused` first private cause UNKNOWN, recovery owner-reported; no make test / fast_test, privilege, loaded DM, physical, real pressure, swapoff/on, mkswap, null_blk or reboot. **SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED FORCED_RAW_BYPASS=DISABLED**.
