# Round029 — verbatim worker GitHub REPORT_READY archive

Original chronological report/update bodies copied byte-for-byte as returned by GitHub; their contemporaneous IN_PROGRESS claims remain historical, not final CI disposition. Authority: [Agent1 integrated closeout](round-report.md), [issue #146](https://github.com/k1moradi/swapz/issues/146).

## Original worker report 1 — https://github.com/k1moradi/swapz/issues/146#issuecomment-6950497271

```text
message: REPORT_READY
round: "029"
agent: 2
status: ORIGINAL_MM_COMPILER_MACRO_REPAIR_SOURCE_PUBLISHED; EXACT_SHA_PINNED_Y_N_KBUILD_IN_PROGRESS_NOT_CLAIMED_SUCCESS
frozen_task_sha: ccac4ea69de6085d25d38477bd08bdbb580f600b
published_source_sha: 998f4a0879b55bd6464021b6d1e9cd538d52b4b3
single_parent_sha: ccac4ea69de6085d25d38477bd08bdbb580f600b
publication: SINGLE_MAIN_NONFORCE_EXPECTED_HEAD_FF_REMOTE_READBACK_CONFIRMED
commit: https://github.com/k1moradi/swapz/commit/998f4a0879b55bd6464021b6d1e9cd538d52b4b3

Modified files in exact Agent2 published commit:
- tests/tools/stage-pinned-linux-zswap-origin.py: original frozen pinned Linux mm/swapfile.c generated actual C rename of exactly four local variable uses current to stored_epoch_entry at declaration/xa_load/xa_is_value/xa_to_value, avoiding #define current get_current(). Source logic, APIs, ordinary production paths unchanged.
- tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py: exact emitted slot-epoch function GCC/Clang macro preprocessing including forged old identifier collision negative.
- docs/testing_standards.md: same-commit unique applicable Round029 Agent2 nonwhitespace append; verified full preexisting 1056248-byte blob preserved byte-exact, 2171 bytes appended.
- docs/handoff/zswapz/round029/agent2-evidence.md: original compiler and policy first failures, rootless vs full original Kbuild limitations.

Original immutable upstream torvalds/linux commit: c339f4010dea8b0d754f84ace70cd1b089878ef8. Only CI opt-in actual original mm/swapfile.c and mm/zswap.c staged into disposable full Linux source; not a new upstream kernel commit, no new live ABI. Agent4 peer code untouched.
First historical genuine Linux compiler failure: https://github.com/k1moradi/swapz/actions/runs/44085443897 job 134046533504 original GCC CONFIG_ZSWAP=y W=1/-Werror mm/swapfile.o, injected void *current collided with kernel macro get_current(), producing conflicting function types/invalid non-lvalue. First independent historical source policy error: https://github.com/k1moradi/swapz/actions/runs/44085443947 job 134046534595 SOURCE_CONTRACT_MISMATCH, prior 025c3a75 lacked same-commit nonwhitespace canonical standards. Historical failed SHAs remain failed, not retroactively green.

Exact new published SHA hosted results:
- https://github.com/k1moradi/swapz/actions/runs/44098294463 native kernel-C project-goal regressions: COMPLETE SUCCESS including policy.
- https://github.com/k1moradi/swapz/actions/runs/44098295348 production C qualification: COMPLETE SUCCESS.
- https://github.com/k1moradi/swapz/actions/runs/44098295936 pinned actual Linux CONFIG_ZSWAP=y/n + matched dm-swapz.ko workflow: IN_PROGRESS at full original Kbuild (13 prior source/manifest/rootless steps success). Exit/result not yet 0/1/2, therefore full pinned source acceptance remains PENDING. No local original full Kbuild/privileged tests performed; next first GCC/source failure must be collected when completed.

Hard safety: PHASE_A=BLOCKED, FORCED_RAW_BYPASS=DISABLED, DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED, LOADED=NOT_RUN, PHYSICAL=NOT_RUN; historical physical swap_attribution UNKNOWN/UNDETERMINED. RAW means original uncompressed full 4096. zswap alone controls compressed RAM cache/pressure eviction; swapz disk backing. Existing physical SWAPSPACE2 protected first 4096 bytes, header, UUID, partition table unchanged.
```

## Original worker report 2 — https://github.com/k1moradi/swapz/issues/146#issuecomment-6950631837

```text
message: REPORT_READY
round: "029"
agent: 4
status: PEER_AGENT4_GUARDED_ORIGINAL_BIO_SEALED_COPY_PUBLISHED; EXACT_CURRENT_SHA_TRUE_KBUILD_AND_EXECUTED_UML_IN_PROGRESS_NOT_QUALIFIED
frozen_task_sha: ccac4ea69de6085d25d38477bd08bdbb580f600b
initial_agent4_source_sha: c07ea78c009373c3e28fde8b203d9082813b1a57
intermediate_fixes: b35e351570c8bd2e396d3b73fcdc0c7339ed58ec 3030304910176714ec448b37ec77543c40bd62eb f90ba8fe58632ec6c7aa04ef547d48d15df5b90e
agent4_latest_published_sha: 255079f3280b9e33abad8c4ccbd05387e3063874
source: https://github.com/k1moradi/swapz/commit/255079f3280b9e33abad8c4ccbd05387e3063874
publication: EXISTING_MAIN_ONE_PARENT_FAST_FORWARD_CHANGES_VERIFIED_VIA_REMOTE_READBACK; THIS_REPORT_REVIEWS_INDEPENDENT_PEER_SOURCE_NOT_DUPLICATE_AGENT4_REIMPLEMENTATION; AGENT2_COMMIT_PRESERVED

Agent4 owned published paths across source/fixes: tests/tools/stage-pinned-linux-zswap-sideband.py (real original block/bio.c CI-only sealed own-copy constructor); tests/runtime/native/pinned-linux-zswap-sideband-test.py (GCC/Clang ASan/UBSan original source-extracted hostile constructor tests); tests/runtime/native/fixtures/round029-sideband-constructor-host.c (bounded source mutations, CRC, allocation, clone/abort); tests/runtime/native/fixtures/round026-sideband-kunit-verdict.py (strict eleven-case JSON and KTAP); .github/workflows/phase-a-zswap-sideband.yml (genuine original pinned y/n BIO compilation + executable UML KUnit); docs/handoff/zswapz/round029/agent4-evidence.md; docs/testing_standards.md (unique append-only co-change each source commit). No Agent2 MM or Agent3 DM ownership altered.
Original Linux immutable upstream pinned source: torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8, true original block/bio.c and include/linux/blk_types.h only in disposable CI source checkout. No new kernel upstream revision.

Exact first failure trail (all historical red SHAs retained):
- https://github.com/k1moradi/swapz/actions/runs/44099629338 at c07ea78: BOTH hosted jobs FAIL exit 1 at source-extracted host test, escaped newline insertion anchor did not match actual C main (no original kernel Kbuild/boot). Fixed b35e.
- https://github.com/k1moradi/swapz/actions/runs/44099977966 at b35e: BOTH hosted rootless jobs FAIL exit 1, SHA fixture left zero before allocation failure test and outdated CRC source text expectation. Fixed 303030.
- https://github.com/k1moradi/swapz/actions/runs/44100330241 at 303030: BOTH hosted source rootless jobs FAIL exit 1; new constructor ran before original host main, changed historical free-count 32/42 assertions. Fixed f90ba.
- https://github.com/k1moradi/swapz/actions/runs/44100790353 at f90ba: original rootless host tests passed to reach real pinned Linux CONFIG_ZSWAP=y block/bio.o GCC; genuine first original source failure exit 2 at KUNIT_EXPECT_NE(pointer,array), Linux pinned KUnit expects integer operands (invalid initializer/int-conversion). Changed ONLY that KUnit pointer-isolation check to KUNIT_EXPECT_TRUE(pointer != array) in 255079.
- https://github.com/k1moradi/swapz/actions/runs/44101209837 at exact current 255079: IN_PROGRESS, genuine original CONFIG_ZSWAP=y/n block/bio.o and executed eleven-case UML evidence NOT YET complete. No PASS asserted for these mandatory runs. Earlier rootless GCC/Clang strict tests completed before genuine compiler in f90ba run; y/n/real executed UML source acceptance remains PENDING.

Hard safety: PHASE_A=BLOCKED, FORCED_RAW_BYPASS=DISABLED, DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED; source test-provisioned descriptor, no authenticated MM/BIO-to-DM epoch or producer; current RAW = original UNCOMPRESSED full 4096. zswap alone manages compressed RAM cache/real eviction, swapz disk only. No loaded host module, physical swap, mkswap/swapon, cgroup pressure, null_blk or privileged device operations performed; protected physical first 4096 SWAPSPACE2 header/signature/UUID/partition table immutable. LOADED=NOT_RUN PHYSICAL=NOT_RUN.
```

## Original worker report 3 — https://github.com/k1moradi/swapz/issues/146#issuecomment-6950685572

```text
message: REPORT_READY
round: "029"
agent: 4
status: REAL_ORIGINAL_BIO_SOURCE_PUBLISHED_KBUILD_Y_N_PASS; BOOTED_UML_KUNIT_EXECUTED_11_OF_11_PASS
frozen_task_sha: ccac4ea69de6085d25d38477bd08bdbb580f600b
pinned_upstream_linux_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
published_source_sha: 255079f3280b9e33abad8c4ccbd05387e3063874
single_parent_sha: f90ba8fe58632ec6c7aa04ef547d48d15df5b90e
main: ONLY_BRANCH_NONFORCE_EXPECTED_HEAD_FF_READBACK_CONFIRMED
commit: https://github.com/k1moradi/swapz/commit/255079f3280b9e33abad8c4ccbd05387e3063874

Production-staged C (actual pinned original block/bio.c, CI_ONLY macro default off) now has swapz_ci_owned_create: 1..3568 compressed bytes, bounded source capacity/struct_size/check_add_overflow allocation, privately copied flexible-array bytes, version-one dictionary-free LZ4, nonzero UNTRUSTED claimed epoch+source identity, 4096 decoded length, claimed SHA present, CRC32C validated on copied bytes, publish exactly one initial owning ref after validity; zero-copy borrow forbidden. Existing live swapz_ci_live_compressed_admit() always -EOPNOTSUPP. Actual original BIO clone/split/reuse/reset/reissue hooks retain ownership and do not steal bi_private/endio or alter normal 4096 BIO I/O. No authenticated MM producer/DM consumer/loaded compression.

Source files and evidence across Agent4's disjoint direct-main commits c07ea78c, b35e3515, 30303049, f90ba8fe, 255079f3:
- tests/tools/stage-pinned-linux-zswap-sideband.py
- tests/runtime/native/pinned-linux-zswap-sideband-test.py
- tests/runtime/native/fixtures/round026-sideband-kunit-verdict.py
- tests/runtime/native/fixtures/round029-sideband-constructor-host.c
- .github/workflows/phase-a-zswap-sideband.yml
- docs/testing_standards.md (full >1MiB preexisting blob and prior Agent2 append preserved; separately titled, mandatory same-C-commit substantive amendments)
- docs/handoff/zswapz/round029/agent4-evidence.md

NEW independent KUnit cases: swapz_ci_constructor_copy_isolation_kunit, swapz_ci_constructor_reject_invalid_kunit, swapz_ci_constructor_clone_abort_kunit, swapz_ci_constructor_split_reset_kunit, plus unchanged seven prior. Independent verdict requires exactly ELEVEN actual PASS via both original pinned UML JSON and genuine KTAP, zero SKIP/FAIL/duplicate/panic; fixture and compiler passes cannot substitute for boot.

Exact latest source SHA hosted run: https://github.com/k1moradi/swapz/actions/runs/44101209837
- job 134101374420: COMPLETED SUCCESS; rootless exact source staging, GCC+Clang -Werror/-Wconversion/-Wshadow ASan/UBSan compiled and EXECUTED host extraction (exit 0), original pin/git diff --check (exit 0), original REAL Linux GCC block/bio.o CONFIG_ZSWAP=y and n KUnit compiled (exit 0 each). Normal build without CI macro unchanged.
- job 134101373826: COMPLETED SUCCESS; pinned original Linux UML build+BOOT exited 0; real KUnit executed all eleven cases PASS, original source suite swapz_round025_sideband_compiler_only, arch=um; independent JSON and original kernel KTAP verifier exited 0, 0 skipped, 0 failed, 0 missing/duplicated/fabricated; source-host prerequisite exit 0.
- Native repository-policy full job 134101373839: SUCCESS at same source SHA, and strict rootless source-contract job 134101374089 SUCCESS. Native run https://github.com/k1moradi/swapz/actions/runs/44101209843

FIRST REAL ORIGINAL KERNEL COMPILER failure, RETAINED HISTORICALLY: source f90ba8fe, run https://github.com/k1moradi/swapz/actions/runs/44100790353 job 134099922188, actual CONFIG_ZSWAP=y block/bio.c:1379 GCC Werror invalid initializer from KUNIT_EXPECT_NE on array expression, original make exit 2; fixed in published 255079f3 with KUNIT_EXPECT_TRUE(pointer != input). Prior source-only fixture failures retained: c07ea78c run 44099629338 host main insertion anchor drift exit 1; b35e3515 run 44099977966 host allocation-failure digest seed not restored exit 1; 30303049 run 44100330241 new source check ran before historical freed-count asserts exit 1. Latest hosted original y/n C compile now PASS, not a retroactive PASS of those historical SHAs.

Qualifiers: SOURCE_ONLY=YES, REAL_BOOTED_KUNIT=11_OF_11_EXECUTED_PASS, LOADED_ORIGINAL_4096=NOT_RUN, PHYSICAL_SWAPSPACE2=NOT_RUN, AUTHENTIC_MM_TO_BIO_TO_DM=NO_GO. PHASE_A=BLOCKED; FORCED_RAW_BYPASS=DISABLED; DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED. Linux zswap owns RAM compression and pressure eviction; swapz owns disk only; ordinary RAW always original UNCOMPRESSED full 4096; physical SWAPSPACE2 first 4096 header/signature/UUID/partition table unchanged. No privileged/loaded/physical execution, no branch/PR/fork/force.

FINAL VERIFIED BOOTED ORIGINAL UML FOLLOWUP (exact same tested SHA 255079f3280b9e33abad8c4ccbd05387e3063874; no new source): run https://github.com/k1moradi/swapz/actions/runs/44101209837 conclusion=success, job 134101373826 conclusion=success, logs: `ROUND026_PINNED_UML_RUN_EXIT=0`; `ROUND026_UML_KUNIT_EXECUTED_PASS suite=swapz_round025_sideband_compiler_only cases=11 arch=um`; `KUNIT_EXECUTED=PASS SOURCE_ONLY=PASS LOADED_4096=NOT_RUN PHYSICAL=NOT_RUN DIRECT_COMPRESSED=DISABLED`; `ROUND026_UML_EXECUTED_ALL_CASES=PASS`; `KUNIT_BOOT_EXECUTED=PASS`. The independent original Linux y/n compilation job 134101374420 also completed SUCCESS. Latest main remote SHA readback matched tested source. Agent2 separate original MM full pinned Linux y/n matched-module job 134091215560 (run 44098295936, source 998f4a08) was still in progress at this update: no Agent2 full compilation PASS inferred.
```

