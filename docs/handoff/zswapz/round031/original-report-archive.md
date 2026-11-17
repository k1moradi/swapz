# Round031 — verbatim two worker REPORT_READY comments

[Issue #148](https://github.com/k1moradi/swapz/issues/148). These reports are archived byte-for-byte from GitHub comment bodies; historical provisional in-progress statuses are NOT the final CI verdict. Read [Agent1 integrated acceptance](round-report.md) for independently verified completed job status.

## Original worker REPORT_READY 1 — https://github.com/k1moradi/swapz/issues/148#issuecomment-6955651992

```text
message: REPORT_READY
round: "031"
agent: 3
task: bounded-source-LZ4-per-logical-page-DM-volatile-sidecar-owner-lifecycle
status: EXACT_SHA_REAL_GUARDED_DM_C_GCC_CLANG_ASAN_UBSAN_AND_X86_ARM_MODULE_KBUILD_4_OF_4_PASS; NO_LIVE_SOURCE
frozen_task_sha: 99800e76550965f962da102ff9fbc9fe07f5c61b
agent3_initial_source_SHA: aed9a265c216ad5b96d7e25514a86c860944ef24
agent3_initial_parent: 99800e76550965f962da102ff9fbc9fe07f5c61b
agent3_strict_GCC_Clang_source_fix_SHA: 1367f82039755d55a1f990c2acbbfa2b3840f771
agent3_fix_parent_and_peer_Agent2_preserved_SHA: 3ee1ae3e1ec60ace13d70397e31273f68162a716
verified_remote_main_at_report: 1a3987e821aa5c5866832042ef94c44b6204e650
publication_protocol: EXISTING_MAIN_ONLY; SINGLE_PARENT_NONFORCE_EXPECTED_HEAD_FAST_FORWARDS_WITH_POSTWRITE_SHA_READBACK; RECONCILED_ON_PEER_HEAD_ADVANCE; NO_BRANCH_PR_FORK_WORKTREE_FORCE

Files changed by Agent3 (initial source + one scoped follow-up):
- src/kernel/dm-target.c — actual three-prior-gates plus new SWAPZ_ROUND031_DM_LZ4_SIDECAR_TEST fourth macro only. Under ordered_owner, bounded contiguous kvcalloc(logical_pages,sizeof(slot)) with checked multiplication and 16MiB cap, no ordinary struct swapz_map (20-byte) or default struct swapz_dm/normal BIO mutation. Each per-logical-page volatile source-LZ4 owner has original STORE full 4096 SHA, source slot epoch and stored identity, compressed length CRC32C, exact codec/version/tag, authoritative current DM map generation/extent sequence and monotonic nonzero owner token/once-only mock ACK. Real existing Round030 stage/bind, bounded padded 4/8/16KiB lower WRITE and optional FUA, swapz_finish COW map, and actual extent-sequence checks are reused. Round031 option defers ONLY the Round030 TEST hypothetical ACK until sidecar entry is published. Failed lower keeps previous token/authority; lower error handled/quarantined by real swapz_finish. Successful newer gen wipes old sensitive owner before new token publish. Token-scoped forget_on_overwrite, discard, abort, GC relocation and full swapoff/teardown are idempotent, stale-callback safe and zeroizing. Source read compares actual map and sequence, uses actual Round030/028 lower read CRC32C/LZ4/exact 4096 SHA, then final map/owner fence before copying independent verified scratch into the upper output. No upper bio_endio or normal live SOURCE_LZ4 hook.
- tests/runtime/native/zswap-compressed-consumer-test.py — extract exact NEW and Round030 production DM C source into host fixture; GCC and Clang -Wall -Wextra -Wconversion -Wshadow -Werror with ASan+UBSan, hostile ABI/epoch/GC/CRC/teardown and output-preservation negative cases; no source algorithm mock rewrite. Historical codec.c conversion warning treatment limited to that already-existing codec alone, not newly compiled C.
- tests/runtime/native/zswap-compressed-admission-test.py — strict fourth-macro source guard expectation while keeping the unconditional live admission refusal.
- NEW tests/runtime/native/fixtures/round031-dm-sidecar-host.c — original Round030 source extracted into same translation unit with new Round031 source, mock ONLY real lower/immutable-authority boundary; 4/8/16KiB byte placements/zero padding, FUA/one ACK, second newer COW with tokenABA, first rejected partial lower preserve older mapping/token, 4096 LZ4 CRC32C/SHA, corrupt lower bitflip, stale map on GC, duplicate ACK, allocation failure/overflow, double discard/abort/teardown and old read refusal.
- .github/workflows/product-codec.yml — actual default W=1/W=2 and opt-in quadruple-flag real linked dm-swapz.ko module for x86_64+arm64, nm presence for new actual C symbol only when all four guards are on, ordinary default absence, source-extracted native tests in both architecture jobs.
- docs/handoff/zswapz/round031/agent3-evidence.md — exact source intent, no-go classification, first genuine compiler failures and fix.
- docs/testing_standards.md — full SHA-verified >1MiB previous standard retained byte-for-byte with substantive unique ## Round031 Agent3 section in SAME original C source commit aed9a2; follow-up unchanged shared standards. Later published Agent2 appends are preserved.

First real failures and resolution:
1. Initial exact aed9a265c216ad5b96d7e25514a86c860944ef24 [product-codec run #44134917180](https://github.com/k1moradi/swapz/actions/runs/44134917180) completed FAILURE in the two exact-C jobs, while actual x86/ARM kernel-module Kbuild jobs SUCCESS. First GCC original error: conversion from unsigned conditional 0U:1U to swapz_u8 in new guarded deferred hypothetical-ACK source (Werror=conversion); followed by two new helper parameters lower_image shadowing host's lower_image global (Werror=shadow). Clang shadow checks also failed. Fixed without disabling warnings, renaming only new helper argument to owned_lower_image and using literal branch assignments to swapz_u8 in actual source, commit 1367f82039755d55a1f990c2acbbfa2b3840f771, parent 3ee1ae3e1ec60ace13d70397e31273f68162a716 (peer Agent2 code and docs preserved).
2. FINAL EXACT SOURCE SHA 1367f82039755d55a1f990c2acbbfa2b3840f771 [product-codec run #44136299249](https://github.com/k1moradi/swapz/actions/runs/44136299249): completed SUCCESS all four jobs: exact-c ARM64 134226637382 SUCCESS, exact-c x86_64 134226638215 SUCCESS, compile-only x86_64 134226638084 SUCCESS, compile-only ARM64 134226638304 SUCCESS. Exact production C source extracted GCC+Clang with strict conversion/shadow warnings plus ASan/UBSan ran rootlessly; real kernel headers compiled both default and guarded module variants, nm checks. No local original checkout existed in container (github.com DNS unavailable), so no local build pass is falsely claimed. Hosted source Kbuild and rootless compiled-C execution are the real test evidence.
3. Round030 Linux predecessor run #44120930434 job #134171742779 independently verified completed SUCCESS during Round031 initial readback. Agent2 same-round single composed MM+BIO Linux/KUnit acceptance is a separate peer qualification, NOT implied by Agent3 success.

Safety/limits:
- No genuine source-authenticated same-kernel MM to BIO to DM compressed producer ingress: the producer record in host fixtures is synthetic and NOT trustworthy for loaded acceptance, and SWAPZ live admission remains unconditional -EOPNOTSUPP. No actual upper BIO ACK or loaded module/physical swap tests; hypothetical ACK only after test RAM map/sidecar.
- zswap alone controls bounded compressed RAM caching and pressure-driven eviction, swapz only disk backing; no duplicate reclaim controller, no forced eviction. Existing RAW is ORIGINAL UNCOMPRESSED 4096. Future source-LZ4 would require distinct authenticated RAM metadata and actual exact 4096 readback.
- No device/mapper/nullblk, module load, swapon/swapoff/mkswap, physical partition, privilege or owner hardware, no reboot. SWAPSPACE2 protected header first full 4096 bytes, UUID, partition table untouched; only post-header actual lower mechanism in default-off source.
PHASE_A=BLOCKED; FORCED_RAW_BYPASS=DISABLED; DIRECT_COMPRESSED=NO_GO_DISABLED; LOADED_ORIGINAL_4096=NOT_RUN; PHYSICAL_SWAPSPACE2=NOT_RUN; HISTORICAL_PHYSICAL_ATTRIBUTION_CAUSE=UNKNOWN_UNDETERMINED.
Agent1 remains final integration and acceptance owner; Agent2 has independent staged MM+BIO source and its own exact-SHA Kbuild/UML CI/report duty.
```

## Original worker REPORT_READY 2 — https://github.com/k1moradi/swapz/issues/148#issuecomment-6955692962

```text
message: REPORT_READY
round: "031"
agent: 2
status: ACTUAL_ONE_TREE_PINNED_ORIGINAL_MM_BIO_C_SOURCE_PUBLISHED; GCC_CLANG_ASAN_UBSAN_AND_FULL_SOURCE_COMPOSITION_STAGING_VERIFIED_SUCCESS; BOOTED_ORIGINAL_COMPOSED_UML_KUNIT_11_OF_11_PASS;_CONFIG_ZSWAP_Y_N_FULL_LINKED_KBUILD_IN_PROGRESS_NOT_YET_QUALIFIED
frozen_task_sha: 99800e76550965f962da102ff9fbc9fe07f5c61b
original_upstream_kernel_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
mandatory_round030_verdict: SUCCESS, exact previous engineering SHA cde2fe3764b5f6e6657085c2c26c8383356247fe
mandatory_round030_success_url: https://github.com/k1moradi/swapz/actions/runs/44120930434
mandatory_round030_success_job: 134171742779
latest_published_agent2_sha: 1a3987e821aa5c5866832042ef94c44b6204e650
latest_published_agent2_parent_and_peer_Agent3_preserved_sha: 1367f82039755d55a1f990c2acbbfa2b3840f771
initial_agent2_sha: 942e1e02ecc878057dbea9e3ef58d2fce23123dd
first_agent2_correction_sha: 3ee1ae3e1ec60ace13d70397e31273f68162a716
agent2_commit: https://github.com/k1moradi/swapz/commit/1a3987e821aa5c5866832042ef94c44b6204e650
publication: EXISTING_MAIN_ONLY_SINGLE_PARENT_NONFORCE_EXPECTED_HEAD_FAST_FORWARDS_WITH_REMOTE_SHA_READBACK; NO_BRANCH_PR_FORK_WORKTREE_FORCE; NO_PEER_SOURCE_OVERWRITES

Source paths modified across Agent2 commits:
- NEW tests/tools/stage-pinned-linux-zswap-composed.py: original same upstream untouched Git blob verified, clean complete pinned checkout; independently renders two prior original pinned stagers in RAM, diff-hunk merges with exact-once and hard COMPOSE_CONFLICT on overlap/mixed/double mutations; preimage all-file plan before write; full source SHA manifest, rollback. Stage real modified original mm/zswap.c, mm/swapfile.c, mm/page_io.c, block/bio.c, include/linux/blk_types.h, include/linux/bio.h, include/linux/swap_ops.h, original KUnit block/Kconfig block/Makefile and block/swap-bio-origin-kunit.c. No sequential dirty-checkout stagers, unrelated or unpinned source.
- NEW tests/runtime/native/pinned-linux-zswap-composed-source-test.py: exact emitted C source-extracted GCC/Clang -Werror -Wconversion -Wshadow, ASan/UBSan, zsmalloc original LZ4, SHA, CRC32C, original epoch/stored identity and source boundary negatives; original mm/page_io 4096 single-folio BIO ownership/clone/refcount, source disjoint-mutation strict comparator and pinned preimage negative.
- NEW tests/runtime/native/fixtures/round031-composed-mm-owned-host.c and tests/runtime/native/fixtures/round031-composed-bio-transfer-host.c: source-injected actual original kernel C under host-only immutable-source/zsmalloc/allocator boundary mocks. The LZ4 vector is real compressed data, independently owned deep refcounted copy; no physical lower I/O.
- NEW .github/workflows/phase-a-zswap-composed-source.yml: one exact immutable original Linux tree, source manifest, full CONFIG_ZSWAP=y/n W=1/-Werror modified original objects and default-absence/opt-in nm+objdump, full actual vmlinux/modules/Module.symvers, same-built matched external dm-swapz.ko; separate original user-mode kernel boot KUnit 11/11 with original JSON+KTAP verifier. Exact-SHA jobs and return exits are evidence, no mock PASS.
- NEW docs/handoff/zswapz/round031/agent2-evidence.md, plus multiple unique nonwhitespace directly applicable same-source-commit append sections to complete SHA-verified >1MiB docs/testing_standards.md. ALL prior Agent3 and original standard bytes preserved.

Actual source contract: original mm/zswap.c true zswap_writeback_entry() after locked swapcache folio and xarray-entry match captures actual previously stored zsmalloc LZ4 source object of 1..3568 bytes, verifies authentic MM-minted nonzero slot epoch and original SHA from prior true locked STORE plus stored-entry identity, checks current pool/tree/epoch before+after, performs independent bounded owned copy+CRC32C and deep refcounted constructor into actual original BIO source; scrub intermediate. Source-only original swap_io_ctx owns initial ref until original mm/page_io.c swap_bdev_submit_write() transfers it to exactly one conventional 4096-byte BIO. BIO clone/split/reissue/abort/final uninit retain own independent refs; if absent/invalid/multi-folio, discard untransferred ref and preserve original decompression->UNCOMPRESSED FULL 4096 swap WRITE. No new live device-mapper authenticated source ingress, no early upper ACK, no use of 4096 upper BIO bytes for compressed payload.

REAL FIRST FAILURES, exit codes and remedies (historical runs remain FAIL):
1) Initial exact SHA 942e1e0 source extraction and composed original stage [run 44135736073](https://github.com/k1moradi/swapz/actions/runs/44135736073): original UML staging job 134224639027 FAILED exit 2 COMPOSE_CONFLICT:block/bio.c:owned-put-global, due valid static→nonstatic C declaration whose after substring was within original declaration. Host C source snippets GCC+Clang passed but test harness additionally expected wrong original preimage exception. 3ee1ae3 correction bounded duplicate discriminator without relaxing once-only source check; same-commit complete standards appendix.
2) Exact 3ee1ae3 [run 44136181797](https://github.com/k1moradi/swapz/actions/runs/44136181797): genuine actual original kernel mm/page_io.c both READ/WRITE contained the same former source anchor; correctly blocked with COMPOSE_CONFLICT:mm/page_io.c:bdev-single-4096-attachment, UML stage exit 2. Rootless host suite exit 1 includes that and negative wrong exception class; both actual source-extracted GCC/Clang ASAN/UBSAN C snippets ran successfully. Final 1a3987e8 uses exact original WRITE-only bi_swap_origin assignment preceding length, preventing READ mutation; native negative now expects actual ORIGIN.StagingError preimage mismatch. Same-source-commit substantive standards.
3) LATEST EXACT SHA 1a3987e821aa5c5866832042ef94c44b6204e650 [run 44136719185](https://github.com/k1moradi/swapz/actions/runs/44136719185): job 134228138236 passed true original full pinned checkout + BOTH GCC/Clang source-extracted ASan/UBSan and initial SAME-ORIGINAL-tree source stage+full manifest; currently IN_PROGRESS at 'Full original Linux y/n with exact source-only macro machine code and matched swapz.ko'. Independent original pinned same-composed-tree booted UML 11/11 KUnit job 134228138988 now COMPLETED SUCCESS: original Linux UML kernel was built and booted; the source-aware original BIO KUnit verifier independently authenticated original kernel JSON+KTAP 11/11. Full CONFIG_ZSWAP=y/n linked Kbuild job 134228138236 remains IN_PROGRESS and cannot yet be reported pass/fail; a genuine compiler/API first failure if any needs correction with same-source standards.

Hard safety: PHASE_A=BLOCKED; DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED; FORCED_RAW_BYPASS=DISABLED; LOADED_KERNEL=NOT_RUN; PHYSICAL_SWAPSPACE2=NOT_RUN. Current RAW means full ORIGINAL UNCOMPRESSED 4096. zswap alone controls RAM compressed-cache pressure eviction, swapz disk backing/packing/GC only. Existing SWAPSPACE2 first protected 4096 bytes/header/UUID/table untouched. No module load, swapon, swapoff, mkswap, null_blk, mapper, cgroup pressure, privileged/hardware tests. Source-only genuine original Kbuild != source-authenticated live DM transport.
```

