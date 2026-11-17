# Round028 — original GitHub worker reports (verbatim)

Canonical [issue #145](https://github.com/k1moradi/swapz/issues/145). All report bodies below are verbatim from GitHub, retained in original chronological order with their original canonical links. These are historical reports, not verified final acceptance; see [Agent1 closeout](round-report.md).

## Worker report 1: https://github.com/k1moradi/swapz/issues/145#issuecomment-6948228416

```text
message: REPORT_READY
round: "028"
agent: 3
status: GUARDED_OWNED_LZ4_PAYLOAD_AND_LOWER_READBACK_SOURCE_PUBLISHED; EXACT_SHA_ROOTLESS_AND_KERNEL_MODULE_BUILD_PASS; LIVE_DISABLED
frozen_task_sha: d1697ffa4175d7a5455e9e3e0581b0645add7c4a
first_source_commit: 1500ddd398e6a8f1bd2878980eecaa60db67d9f4
source_snapshot_test_correction: 4e135fb6c6062493ff98f5c963756b4911a2122f
agent3_final_published_sha: c5c123e1202944afb21760ec078db9ff366fe6b5
agent3_final_parent_sha: 4e135fb6c6062493ff98f5c963756b4911a2122f
published_main_including_agent2: 48738831b48c916d939f9584a50033d9139f8b3b
publication: SOLE_EXISTING_MAIN_THREE_SERIALIZED_NONFORCE_EXPECTED_HEAD_FAST_FORWARDS; POSTWRITE_REMOTE_SHA_AND_SOLE_PARENT_VERIFIED; AGENT2_FOLLOWUP_PRESERVED

Changed paths (Agent3-owned source commits, 7):
- src/kernel/dm-target.c: gated actual C routines swapz_round028_dm_stage_owned_payload and swapz_round028_dm_owned_lower_readback; standalone source-staged LZ4 copy into full bounded 4/8/16KiB zero-padded lower image, map/extent/GC snapshot under ordered_owner, real synchronous swapz_lower_read, revalidation, full CRC32C/LZ4/SHA256 original 4096 check; no normal call/ACK path.
- tests/runtime/native/zswap-compressed-consumer-test.py: exact source-extracted GCC/Clang host tests, strict -Wconversion on new fixture, existing codec's previously documented conversion warning only handled separately.
- tests/runtime/native/fixtures/round028-consumer-owned-stage.c: independent rootless exact byte readback, alias, CRC/length/teardown negatives.
- tests/runtime/native/zswap-compressed-admission-test.py: preserve Round026 exact one-definition/one-original-call and account for two new guarded calls, full no-live assertions.
- .github/workflows/product-codec.yml: x86_64 and arm64 guarded W=1 linked external module symbols opt-in present/default absent, unchanged W=1/W=2 normal module.
- docs/handoff/zswapz/round028/agent3-evidence.md
- docs/testing_standards.md APPEND-ONLY separately headed Agent3 section (all prior standards preserved).

First actual source CI failures and corrected test gates:
- [source run 44082085684](https://github.com/k1moradi/swapz/actions/runs/44082085684) job 134034958489 FAIL (exit 1): test_round026_real_dm_snapshot_fence_gcc_clang_no_go wrongly expected 2 capture-function textual references; actual guarded helper introduces 2 additional = 4, no production failure. Fixed 4e135fb.
- [source run 44082578152](https://github.com/k1moradi/swapz/actions/runs/44082578152) exact-c jobs FAIL (exit 1): old whole-file negative assert rejects newly guarded constant, and preexisting production codec.c -Wconversion diagnostics in an overbroad source fixture command. Fixed in c5c123e without changing production C or ignoring new-test warnings.
- Rootless cross-ABI [run 44082578113](https://github.com/k1moradi/swapz/actions/runs/44082578113) at 4e135fb SUCCESS.
- Rootless compile + actual linked module [product-codec run 44083431045](https://github.com/k1moradi/swapz/actions/runs/44083431045), exact c5c123e SHA, completed SUCCESS; both architecture compilation/exact-C paths green. Source test executions: compiled real C source snippets with GCC/Clang, -Werror, ASan/UBSan; new 4/8/16KiB payload zero padding, negative overlap/crc/teardown/short lower, full 4096 byte exact readback, existing regressions.
- Agent3 did not execute local repo tests because no mounted local checkout was available. Hosted GitHub Actions are actual executed evidence, not a local claim.

Source acceptance only. Existing ordinary RAW means original UNCOMPRESSED 4096 page; compressed representation remains separate CI-only RAM descriptor. New functions have NO live ingress or upper-BIO completion; source-issued MM epoch and authenticated pinned BIO carrier still absent from Agent3 independent work. Original SWAPSPACE2 first page/signature/UUID/table unchanged.
PHASE_A=BLOCKED. FORCED_RAW_BYPASS=DISABLED. DIRECT_COMPRESSED=NO_GO_DISABLED.
LOADED_ORIGINAL_4096=NOT_RUN. PHYSICAL=NOT_RUN.
Old physical swap_attribution first cause=UNKNOWN_UNDETERMINED. Agent1 retains integration/final CI acceptance.
```

## Worker report 2: https://github.com/k1moradi/swapz/issues/145#issuecomment-6948305666

```text
message: REPORT_READY
round: "028"
agent: 2
status: PINNED_SOURCE_MM_ALLOCATOR_EPOCH_AND_STORED_SHA_OPT_IN_PUBLISHED; ROOTLESS_SOURCE_NEGATIVES_CORRECTED; REAL_PINNED_LINUX_Y_N_MATCHED_MODULE_BUILD_NOT_YET_QUALIFIED
frozen_task_sha: d1697ffa4175d7a5455e9e3e0581b0645add7c4a
agent2_source_commit_sha: 48738831b48c916d939f9584a50033d9139f8b3b
agent2_source_parent_sha: c5c123e1202944afb21760ec078db9ff366fe6b5
agent2_source_test_correction_sha: be2fabc12c567789706d0cc9be61d8c728e209f2
correction_parent_sha: 48738831b48c916d939f9584a50033d9139f8b3b
verified_remote_main_sha: be2fabc12c567789706d0cc9be61d8c728e209f2
publication: DIRECT_ONLY_EXISTING_MAIN_NONFORCE_EXPECTED_HEAD_FAST_FORWARD; EACH_COMMIT_SOLE_PARENT_AND_POSTWRITE_SHA_READBACK; PEER_AGENT3_CHANGES_PRESERVED

Owned modified paths (7):
- tests/tools/stage-pinned-linux-zswap-origin.py: optional exact-original `mm/swapfile.c` allocation/free/swapoff and `mm/zswap.c` original locked STORE+eviction+free guarded C edits. `--with-round028-slot-epoch-source` requires original Round026 7-path allocator profile. Default six and ordinary kernel without KCFLAGS unchanged. Actual MM cluster-lock source epoch minted nonzero monotonically; per-swpentry xarray retired at original free and swapoff; fail closed on allocation failure/overflow. Actual zswap stored entry independent identity, original 4096 folio SHA256, recheck epoch before xarray publish and at genuine writeback, clear proof on free. No authenticated BIO created.
- tests/runtime/native/pinned-linux-origin-paired-module-test.py: strict optional source manifest authorization and negative forged marker/config profile tests while preserving pinned original SHA/blob/warning/object gates.
- tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py: actual source-extracted GCC/Clang ASan/UBSan 4-thread atomic epoch mint uniqueness and max-exhaustion test; later corrected legacy exact KCFLAGS assertions to require *both* macros.
- NEW tests/runtime/native/fixtures/round028-producer-epoch.c: bounded rootless thread/saturation fixture.
- .github/workflows/phase-a-zswap-origin-prototype.yml: original Linux exact SHA + seven path preflight; real opt-in mm/swapfile.o original C and mm/zswap.o original STORE C compiled under W=1/-Werror, nm/objdump opt-in and normal-restored-default absence; complete CONFIG_ZSWAP=y/n kernel and source-matched dm-swapz.ko builds still mandatory.
- docs/handoff/zswapz/round028/agent2-evidence.md
- docs/testing_standards.md distinct APPEND-ONLY Agent2 section, preserved full original plus peer Agent3 section without truncation.

Hosted CI / actual first failure:
- Initial source run [44084594506](https://github.com/k1moradi/swapz/actions/runs/44084594506), job 134043594446: stage/rootless tests passed until disabled compressed source negative suite; exit 1 due exactly two **legacy test assertions** expecting the earlier single-macro `SWAPZ_ROUND025_STORE_PROOF_KBUILD_PROBE=1 -Werror` and `KCFLAGS="-DSWAPZ_ROUND026_SLOT_EPOCH_PROBE=1 -Werror"`. New workflow intentionally adds `-DSWAPZ_ROUND028_SLOT_EPOCH_SOURCE=1`; actual first failure was TEST-EXPECTED-KCFLAGS drift, NOT kernel compiler or physical runtime. The new source-extracted GCC/Clang concurrent mint test also ran and passed. Fixed without lowering warnings/negative controls in published be2fabc.
- Corrected exact-SHA rootless source tests [cross-ABI run 44085040961](https://github.com/k1moradi/swapz/actions/runs/44085040961): completed SUCCESS.
- Corrected exact-SHA true pinned Linux y/n + external dm-swapz Kbuild: [run 44085040834](https://github.com/k1moradi/swapz/actions/runs/44085040834), job 134045142379: IN_PROGRESS at report; source staging/negative and original full build exit codes/next first errors must be read from completed hosted run. NO FULL PINNED KBUILD PASS CLAIM.
- Existing original source-only code, disabled compiled source regressions, GitHub-hosted test executions above are source-evidence only. **No local checkout** was mounted in this session; no independent local tests or privileged commands were executed.

SOURCE=PINNED_SOURCE_ONLY_PENDING_FULL_KBUILD. ORIGINAL_KERNEL_SLOT_EPOCH=OPTIONAL_SOURCE_ONLY_NOT_AUTHENTICATED_BIO; authoritative end-to-end transfer epoch/owner/carrier NOT_PROVEN.
PHASE_A=BLOCKED. FORCED_RAW_BYPASS=DISABLED. DIRECT_COMPRESSED=NO_GO_DISABLED.
LOADED_ORIGINAL_4096_KERNEL_SWAPIN=NOT_RUN. PHYSICAL_SWAPSPACE2=NOT_RUN.
Original physical `anonymous_workload` swap_attribution root cause=UNKNOWN/UNDETERMINED. RAW means original UNCOMPRESSED FULL 4096 byte page. zswap exclusively manages compressed RAM cache and eviction; swapz disk-tier backing without pressure controller. Existing SWAPSPACE2 header/UUID/partition table/first 4096 bytes untouched.
Agent1 owns integration and final CI acceptance.
```

## Worker report 3: https://github.com/k1moradi/swapz/issues/145#issuecomment-6948346293

```text
message: REPORT_READY
round: "028"
agent: 2
status: ADDITIONAL_SOURCE_FIRST_ERROR_TEST_REPAIR_PUBLISHED_MAIN; MANDATORY_TRUE_PINNED_LINUX_Y_N_KBUILD_CURRENT_CI_IN_PROGRESS_NOT_CLAIMED_PASS
frozen_task_sha: d1697ffa4175d7a5455e9e3e0581b0645add7c4a
agent2_initial_independent_source_sha: 48738831b48c916d939f9584a50033d9139f8b3b
agent2_prior_strict_macro_test_fix: be2fabc12c567789706d0cc9be61d8c728e209f2
my_test_first_error_fix_sha: 025c3a75ed1ce554ebd1e00d1fbc40c81968f680
my_fix_parent_sha: be2fabc12c567789706d0cc9be61d8c728e209f2
publication: SOLE_MAIN_NON_FORCE_EXPECTED_HEAD_FF; EXACT_REMOTE_READBACK_VERIFIED; AGENT3_AND_PREVIOUS_AGENT2_COMMITS_PRESERVED
commit: https://github.com/k1moradi/swapz/commit/025c3a75ed1ce554ebd1e00d1fbc40c81968f680

Changed files in my supplementary commit (2, Agent2-owned):
- tests/runtime/native/pinned-linux-origin-paired-module-test.py — preserve source validator's ORIGINAL first-failure order, requiring source_manifest_allocator_profile for forged direct-compressed flag or a seven-path allocator identity dishonestly reduced to six; retain strict source_manifest_round028_profile checks for the Round028-only forged fields.
- docs/handoff/zswapz/round028/agent2-evidence.md — append exact first CI failure/source gating details, retaining earlier Agent2 evidence and all Agent3 peer sections.
Preexisting source in Agent2 SHA 48738831: actual original mm/swapfile.c slot mint/free/retire and original mm/zswap.c STORE time SHA provenance under a default-off CI macro; no live compressed transport.

Actual executed hosted results (source-qualified distinction):
- https://github.com/k1moradi/swapz/actions/runs/44084594506 at 48738831: FAILED (exit 1) before Kbuild, old Round025/Round026 test assertions expected single-macro KCFLAGS; corrected by previous Agent2 main commit be2fabc.
- https://github.com/k1moradi/swapz/actions/runs/44085040834 at be2fabc: FAILED (exit 1) at paired rootless verifier negative test; validator first error paired-build-invalid: source_manifest_allocator_profile, while two new test cases incorrectly expected later round028 profile error. Corrected by THIS commit. Rootless staging, DM, owner negative, compressed handoff source tests in that job succeeded; full Linux y/n/module step was SKIPPED, NOT PASS.
- https://github.com/k1moradi/swapz/actions/runs/44085443897 is the exact current published SHA workflow, IN_PROGRESS (not success as of this report). First genuine compiler, linked module, and complete y/n results remain UNDETERMINED until that workflow completes. No local full Linux checkout or Kbuild execution was available in this session.
Safety: PHASE_A=BLOCKED; LIVE_DIRECT_COMPRESSED=DISABLED; FORCED_RAW_BYPASS=DISABLED; original RAW=UNCOMPRESSED ORIGINAL 4096; no authenticated refcounted MM/BIO-to-DM source carrier; LOADED=NOT_RUN, PHYSICAL=NOT_RUN; no privileged, module-load, swapon, pressure, null_blk, or physical-device operations. Existing physical SWAPSPACE2 first 4096/header/signature/UUID and partition table untouched. Agent1 owns final acceptance.
```

