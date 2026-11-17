# Round030 — verbatim original worker GitHub reports

[Coordination issue #147](https://github.com/k1moradi/swapz/issues/147). Original REPORT_READY comments and historical provisional status text appear **verbatim** in reported chronological order; GitHub status at closeout is independently reviewed in [Agent1 report](round-report.md). No IN_PROGRESS assertion is relabeled PASS by archival copy.

## Original report 1 — https://github.com/k1moradi/swapz/issues/147#issuecomment-6953440402

```text
message: REPORT_READY
round: "030"
agent: 3
task: round030-agent3-dm-durable-compressed-record-commit
status: GUARDED_REAL_DM_ORDERED_COMPRESSED_LOWER_COMMIT_AND_4096_READBACK_SOURCE_PUBLISHED; EXACT_SOURCE_GCC_CLANG_ASAN_UBSAN_AND_X86_ARM_W1_W2_MODULE_KBUILD_PASS; LIVE_DISABLED
frozen_task_sha: 3636346987898b2d9cccf3bcf39b3914e79c051f
agent2_independent_preceding_main_sha: 7282b65cfeeb28c6b221f7dfcc3e587245a58e8b
agent3_initial_source_commit: 0eaca41cae54402881c0d770ff4ce65fee6c4196
agent3_initial_source_parent: 7282b65cfeeb28c6b221f7dfcc3e587245a58e8b
agent3_linux_macro_fix: 985d0a0caf453e602ff5d42449d3d96046cd3f9c
agent3_source_gate_fix: 89781334bd12631985ce7257d9f753af990dff9d
agent3_latest_own_source_fix: 21ef0d3f9f4f6fb0a9327de63c00c6018d466ebf
agent3_latest_own_parent: 4890db350e0cddb9aefc5f76ea9684ac992d95d8
publication: EXISTING_MAIN_ONLY; SERIALIZED_NONFORCE_EXPECTED_HEAD_FAST_FORWARDS; POSTWRITE_REMOTE_SHA_AND_SINGLE_PARENT_VERIFIED; PEER_AGENT2_CHANGES_AND_SHARED_STANDARDS_PRESERVED
no_branches_pr_worktrees_forks_force: TRUE

Agent3 modified files across owned commits:
- src/kernel/dm-target.c — three-compile-flag-gated actual production C bodies swapz_round030_dm_commit_owned_lz4 + swapz_round030_dm_read_owned_lz4, no normal caller. Requires ordered_owner, independent source-domain slot/generation/identity, bounded 1..3568 LZ4+CRC, 4/8/16KiB zero-padded complete lower image, generation/GC checks. Real swapz_stage/swapz_bind_compressed_record/swapz_mark_compressed_data_only -> real synchronous swapz_lower_write with optional prepublication FUA -> real swapz_finish -> current RAM map/extent-sequence revalidation -> ONLY hypothetical exactly-once ACK state. Staging failures call swapz_abort, lower failures call swapz_finish quarantine; no upper bio_endio(). Read checks volatile descriptor against current map and calls actual Round028 lower READ/GC fence, CRC32C/LZ4/exact full 4096 independent SHA before output copy. Source under all three flags SWAPZ_ROUND030_DM_COMPRESSED_COMMIT_TEST, SWAPZ_ROUND028_DM_OWNED_READBACK_TEST, SWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE. Linux current macro collision fixed by using current_mapping in opt-in source.
- tests/runtime/native/fixtures/round030-consumer-commit.c — exact extracted new real C function bodies with fake ONLY at lower / map-authority boundary, strict GCC+Clang Werror conversion/shadow + ASan/UBSan tests for 4/8/16KiB on-media data+zero padding, real LZ4 4096 SHA readback, FUA flag, duplicate commit, stale descriptor/generation, failed lower, stage ENOSPC, bad codec, CRC bitflip, teardown, output-not-mutated; mock authority cannot represent loaded device.
- tests/runtime/native/zswap-compressed-consumer-test.py — extracts exact source markers and compiles/executes with GCC & Clang -Wall -Wextra -Wconversion -Wshadow -Werror, ASan+UBSan, pre-existing codec.c conversion warnings isolated only for existing codec C (not new fixture).
- tests/runtime/native/zswap-compressed-admission-test.py — updated old two-macro expected production CI guard to strict three-macro check; unconditional swapz_zswap_admission_try_live -EOPNOTSUPP intact.
- .github/workflows/product-codec.yml — real default W=1/W=2 and explicit triple-flag opt-in linked DM module on x86_64/arm64; nm proves both new actual source function symbols PRESENT only opt-in and ABSENT default. Product ordinary module remains unchanged.
- docs/handoff/zswapz/round030/agent3-evidence.md — source/no-go, first failures and corrections.
- docs/testing_standards.md — append-only uniquely headed Round030 Agent3 testing contract in SAME source commit; full original >1MiB SHA-exact bytes + earlier published Agent2 Round030 appendix preserved, no replacement/truncation.

Actual failures and corrections:
1) [product-codec #44119135592](https://github.com/k1moradi/swapz/actions/runs/44119135592) exact 0eaca41, arm64/x86 opt-in W1 compile FAIL. First compiler diagnostic dm-target.c:3554 Werror strict-prototypes: Linux asm/current.h macro current mapped local const struct swapz_map *current to get_current(), also lvalue assignment. Fixed source pointer only in 985d0a0.
2) [product-codec #44119464700](https://github.com/k1moradi/swapz/actions/runs/44119464700) exact 985d: real kernel x86+ARM compile-only SUCCESS; native source test blocked by historical exact two-macro workflow string expectation. Fixed by requiring all three macros in 8978133.
3) [product-codec #44119844620](https://github.com/k1moradi/swapz/actions/runs/44119844620) exact 8978133: real kernel both arch SUCCESS; new source-extracted fake authority fixture strict compilation FAIL because static fake swapz_stage/open_segment_fits/bind/mark/finish/abort/sequence declarations conflicted with external real authority.h prototypes; GCC additionally -Wconversion on 3bit extent assignment and -Wshadow injected global finish_error. Fixed ONLY host fixture: matching external linkage, legal literal bitfield classes and renamed injected_finish_error in 21ef0d3.
4) FINAL EXACT AGENT3 OWN FIX SHA 21ef0d3f9f4f6fb0a9327de63c00c6018d466ebf: [product-codec run #44120591980](https://github.com/k1moradi/swapz/actions/runs/44120591980), ALL FOUR JOBS COMPLETED SUCCESS: exact-c x86 job 134170568584, exact-c ARM64 job 134170569201, compile-only x86 job 134170569064, compile-only ARM job 134170568930. Exact source-extracted Round030 C tested with BOTH GCC AND CLANG ASan/UBSan and new -Wconversion/-Wshadow/-Werror unchanged, full existing source/native/TSAN suites, actual external module W=1/W=2 and opt-in. No local checkout/tools could independently execute local builds; hosted completed GitHub logs are the actual build/test evidence.

Nonclaims/safety:
- This remains CI-ONLY an isolated source seam. Mock-created source slot/descriptor flags do not constitute authentic Linux MM/BIO->DM compressed provenance. Existing swapz_zswap_admission_try_live() unconditional -EOPNOTSUPP; no real live upper WRITE/READ BIO, no actual upper ACK, no loaded kernel or physical source verification. The hypothetical ACK is a test-state transition only.
- zswap alone owns bounded compressed RAM/cache and natural pressure eviction; swapz owns disk backing. Existing RAW is ORIGINAL UNCOMPRESSED FULL 4096 bytes; future compressed LZ4 only reuses lower-I/O machinery via a DISTINCT volatile RAM descriptor, never stored as RAW or on-media header.
- SWAPSPACE2 first 4096 bytes/signature/UUID/partition table untouched; lower locations only post-header. No privileged, loaded-kernel, mkswap, swapon/swapoff, nullblk, physical-device or owner hardware testing performed.
PHASE_A=BLOCKED; FORCED_RAW_BYPASS=DISABLED; DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED; LOADED=NOT_RUN; PHYSICAL=NOT_RUN; HISTORICAL_PHYSICAL_ROOT_CAUSE=UNKNOWN_UNDETERMINED.
Agent1 independently owns final integration and acceptance. Agent2 independent source/CI report is separately required.
```

## Original report 2 — https://github.com/k1moradi/swapz/issues/147#issuecomment-6953440642

```text
message: REPORT_READY
round: "030"
agent: 3
status: SOURCE_ONLY_ORIGINAL_DM_COMMIT_PUBLISHED; X86_64_AND_ARM64_HOSTED_EXACT_C_AND_MODULE_KBUILD_VERIFIED_SUCCESS; LIVE_COMPRESSED_NO_GO
frozen_task_sha: 3636346987898b2d9cccf3bcf39b3914e79c051f
latest_agent3_published_sha: 21ef0d3f9f4f6fb0a9327de63c00c6018d466ebf
original_agent3_source_sha: 0eaca41cae54402881c0d770ff4ce65fee6c4196
main_lineage: original Agent2 commit 7282b65cfeeb28c6b221f7dfcc3e587245a58e8b followed by independent Agent3 main-only source fixes, including 89781334bd12631985ce7257d9f753af990dff9d and 21ef0d3f9f4f6fb0a9327de63c00c6018d466ebf; later Agent2 corrections preserve all Agent3 commits. No branches/PRs/forks/worktrees or force.
latest_agent3_commit: https://github.com/k1moradi/swapz/commit/21ef0d3f9f4f6fb0a9327de63c00c6018d466ebf

Agent3 source file ownership and exact source-evidence paths across commits: src/kernel/dm-target.c; tests/runtime/native/zswap-compressed-consumer-test.py; tests/runtime/native/zswap-compressed-admission-test.py; tests/runtime/native/fixtures/round030-consumer-commit.c; .github/workflows/product-codec.yml; docs/handoff/zswapz/round030/agent3-evidence.md; complete same-code-commit append-only docs/testing_standards.md. The independently published peer Agent3 implementation was preserved as the accepted branchless source candidate; this report independently verifies its existing main publication, not a duplicate replacing peer implementation.

Actual guarded original dm-target.c: SWAPZ_ROUND030_DM_COMPRESSED_COMMIT_TEST plus SWAPZ_ROUND028_DM_OWNED_READBACK_TEST and SWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE; swapz_round030_dm_commit_owned_lz4 and swapz_round030_dm_read_owned_lz4. Source C invokes actual swapz_stage, compressed record bind+seal, payload-only deterministic zero-padded 4/8/16KiB lower-image source staging, swapz_lower_write with original prepublication FUA and complete physical write result, swapz_finish true RAM-only COW map publication, extent-sequence/GC witness recheck, hypothetical once-only ACK and guarded original lower READ CRC32C/LZ4/decode/original full 4096 STORE-SHA path. No ordinary upper BIO completion or live compressed transfer; source epoch/identity from caller still untrusted. No change to existing RAW_4096 definition or compact 20-byte swapz_map, no persistent metadata. Ordinary default build unaffected.

FIRST GENUINE ERRORS AND EXACT CORRECTED RESULT:
- Original first real Linux ARM kernel C Kbuild W=1 error at source 0eaca41: https://github.com/k1moradi/swapz/actions/runs/44119135592 job 134165335785 `current` kernel macro expanded to get_current() in DM guarded local source, compiler function-not-prototype / invalid lvalue. Corrected only local to current_mapping in subsequent peer source commit; no warning suppression. Historical FAIL persists.
- Additional first GCC/Clang strict original source-extracted host error at Agent3 SHA 897813: https://github.com/k1moradi/swapz/actions/runs/44119844620 jobs 134167860975 x86_64 and 134167861397 arm64: static host authority stub definitions conflicted with public real authority.h declarations plus global finish_error shadow and -Wconversion. No physical I/O. Next peer source/fixture correction 21ef0d3f aligned test stubs without relaxing real source warning policy.
- VERIFIED EXACT SHA 21ef0d3f https://github.com/k1moradi/swapz/actions/runs/44120591980 COMPLETED SUCCESS: ALL FOUR jobs exit 0, jobs 134170568584 (x86_64 exact-c), 134170569201 (arm64 exact-c), 134170569064 (x86_64 compile-only) and 134170568930 (arm64 compile-only). Real C module source compiles on x86_64 and arm64 and source-extracted GCC/Clang strict sanitizers execute; this is NOT a loaded kernel or an authenticated MM/BIO-to-DM carrier. The real portable mapping calls remain separately source-verified and compiled by Kbuild; host fixtures do not constitute physical device access.

NO-GO: PHASE_A=BLOCKED, DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED, FORCED_RAW_BYPASS=DISABLED, LOADED_KERNEL=NOT_RUN, PHYSICAL_SWAPSPACE2=NOT_RUN. Original RAW uncompressed full 4096; zswap alone compressed RAM cache and pressure eviction, swapz disk backing only; first protected 4096 SWAPSPACE2 signature/header/UUID and partition table unchanged. No module loads, swapon/mkswap, cgroup pressure, mapper, null_blk or privileged/physical tests.
```

## Original report 3 — https://github.com/k1moradi/swapz/issues/147#issuecomment-6953482967

```text
message: REPORT_READY
round: "030"
agent: 2
status: REAL_PINNED_MM_STORED_EVICTION_LZ4_C_SOURCE_PUBLISHED; ROOTLESS_SOURCE_STAGING_AND_GCC_CLANG_SANITIZERS_PASS; COMPLETE_Y_N_SOURCE_KBUILD_IN_PROGRESS_NOT_QUALIFIED
task_publication_frozen_sha: 3636346987898b2d9cccf3bcf39b3914e79c051f
initial_agent2_source_sha: 7282b65cfeeb28c6b221f7dfcc3e587245a58e8b
first_source_correction_sha: 4890db350e0cddb9aefc5f76ea9684ac992d95d8
latest_verified_agent2_source_sha: cde2fe3764b5f6e6657085c2c26c8383356247fe
latest_single_parent: 21ef0d3f9f4f6fb0a9327de63c00c6018d466ebf
publication: CURRENT_MAIN_ONLY_NONFORCE_EXPECTED_HEAD_FAST_FORWARD_SUCCESS_REMOTE_READBACK_EXACT_MATCH_AND_PEER_AGENT3_COMMITS_PRESERVED
source_commit: https://github.com/k1moradi/swapz/commit/cde2fe3764b5f6e6657085c2c26c8383356247fe

Agent2 original source ownership across source and corrective commits: tests/tools/stage-pinned-linux-zswap-origin.py, tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py, tests/runtime/native/fixtures/round030-producer-snapshot-host.c, .github/workflows/phase-a-zswap-origin-prototype.yml, docs/handoff/zswapz/round030/agent2-evidence.md, docs/testing_standards.md (unique applicable nonwhitespace SAME-COMMIT section at each source correction; whole verified >1MiB file and peer appendixes retained byte-exact). No DM Agent3 production/source ownership touched.

Actual frozen original torvalds/linux c339f4010dea8b0d754f84ace70cd1b089878ef8: strict whole-original Git blob checked for real mm/zswap.c and mm/swapfile.c; stager injects default-OFF source-only SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE alongside SWAPZ_ROUND028_SLOT_EPOCH_SOURCE. The REAL pinned zswap_writeback_entry() after locked swapcache folio and xarray current store check snapshots previously stored LZ4 bytes from actual zswap_pool -> zsmalloc SG object into bounded independent kmalloc flexible-array image. Verifies stored-entry identity, slot allocation epoch, 1..3568 size, actual lz4 compressor, original full-4096 SHA from STORE, entry/pool/xarray/epoch before/after, canonical CRC32C on owned compressed bytes, scrubs copy via kfree_sensitive, consumes observational proof only once. NEVER provides an authenticated BIO/DM handoff or skips original decompress->full UNCOMPRESSED 4096 swap WRITE. No Linux upstream branch/commit is created: changes only stage into disposable original checkout.

Genuine first failure trail and exact exits:
- Initial source 7282b65: https://github.com/k1moradi/swapz/actions/runs/44118731901 job 134163903087 FAILED exit 1 in rootless source-extracted GCC/Clang: mistakenly generated `struct swapz_pool` (incomplete, conflicting real original `struct zswap_pool`). Corrected in 4890db3 source, not retroactive PASS.
- Source 4890db3: https://github.com/k1moradi/swapz/actions/runs/44120252419 job 134169343567 source-extracted GCC/Clang ASan/UBSan plus staging test successful, but true original full pinned Linux checkout stager FAILED exit 1 `missing-or-duplicate-anchor:mm/zswap.c` since original Linux has TWO `if (!zswap_decompress(entry, folio))` sites. Corrected by pinning an exact UNIQUE real writeback error branch + xa_erase anchor at source cde2fe, without weakening original SHA/negative/manifest/warning gates; full Linux compile was SKIPPED on failing older SHA.
- Exact new corrected SHA cde2fe: https://github.com/k1moradi/swapz/actions/runs/44120930434 job 134171742779 currently IN_PROGRESS at 'Build modified Linux and matched source-linked swapz module for both configurations'. Previously COMPLETED SUCCESS (exit 0) steps: source-controlled rootless staging regression; original DM origin/once-only commit source regressions; disabled compressed source/ownership GCC+Clang ASan/UBSan fixture (real emitted C + real LZ4); matched source/module verifier regressions; actual original Linux C/H staging; strict original pinned source manifest. Genuine CONFIG_ZSWAP=y/n W=1/-Werror vmlinux/modules/Module.symvers and matched source-linked dm-swapz.ko still IN_PROGRESS, thus full pinned kernel qualification is NOT YET PASS or FAIL. No local full original Linux C compile/physical device activity performed in connector-only execution environment.

All original current kernel-doc/source warning allowlists and complete source-checker SHA gates remain strict. If new exact-SHA Kbuild fails, the next true source/compiler first error must be carried forward; do not assert completion or turn it into a source-only host PASS.

Hard NO-GO: PHASE_A=BLOCKED, FORCED_RAW_BYPASS=DISABLED, DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED, LOADED=NOT_RUN, PHYSICAL=NOT_RUN. Existing RAW always uncompressed full original 4096 bytes. Linux zswap exclusively owns small compressed RAM cache/pressure eviction; swapz has disk backing/GC, no competing reclaim. First 4096 bytes physical SWAPSPACE2 header/signature/UUID and partition table unchanged; no privileged module/device/swap/pressure/physical tests.
```

