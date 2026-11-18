# Round032 verbatim original worker REPORT_READY archive

Source [issue #149](https://github.com/k1moradi/swapz/issues/149). Reports are archived verbatim and preserve provisional states/first failures. **The final provider full original Linux CI ran after Agent2's last REPORT_READY and FAILED. Do not interpret the older report's IN_PROGRESS as the final result.** Authoritative independent Agent1 first-failure details are in [round-report](round-report.md).

## REPORT_READY worker 1 — https://github.com/k1moradi/swapz/issues/149#issuecomment-6959915062

```text
message: REPORT_READY
round: "032"
agent: 3
frozen_task_sha: 5d93c9a1c01632355f2d68eb2fb1377978fb122c
task: guarded-real-production-DM-copied-v1-source-view-validation
result: ACTUAL_SOURCE_C_HOST_GCC_CLANG_ASAN_UBSAN_AND_X86_ARM_REAL_MODULE_W1_W2_PASS_4_OF_4
source_changing_commit: e0ce699ff874000cfb4ac6dee412159ac91da38d
source_commit_parent: 5d93c9a1c01632355f2d68eb2fb1377978fb122c
evidence_exact_CI_closeout_commit: 87aff131bd7ac147b0cfa0e3a03a24756106bd00
evidence_closeout_parent: c15efa281c14b8f452e0bf9a1d109bfe02512449
remote_main_last_verified: 87aff131bd7ac147b0cfa0e3a03a24756106bd00
branch: main
publication: EXPECTED_HEAD_NONFORCE_SINGLE_PARENT_FAST_FORWARD_WITH_READBACK; PEER_AGENT2_COMMIT_PRESERVED; NO_PR_BRANCH_FORK_WORKTREE_FORCE

Source-changing commit e0ce699ff874000cfb4ac6dee412159ac91da38d modified:
1. src/kernel/dm-target.c: actual guarded Round032 source C with new undefined-by-default SWAPZ_ROUND032_DM_LZ4_VIEW_VALIDATE_TEST *plus* existing Round031/Round030/Round028/Round024 guards. Frozen v1 copied VALUE-ONLY layout: u64 full original swp_entry_t.val source_swap_entry, MM slot epoch and stored-entry identity, u32 CRC32C, u16 exact 1..3568 compressed_length/decoded_length=4096, stored dictionary-free LZ4 v1 codec/version and genuine STORE SHA256[32] field (no pointers/media metadata). Actual synchronous original REQ_OP_WRITE|REQ_SWAP exact 8 sectors/4096 with 1 nonmerged complete original BIO vector and scalar provenance only NECESSARY, page>0, target capacity, original full swap entry != DM-relative page numeric inference, source epoch/stored identity/nonzero SHA, copied owned compressed bytes CRC32C and no alias; existing current ordered_owner, bounded Round031 source LZ4 sidecar owner token, exactly one hypothetical prior ACK, map generation, GC/inflight, physical extent-sequence and authentic *current authority* map comparison. Tests check first/second independently owned copy and untouched destination on every rejection. No source type or live slot-incarnation authority available in ordinary stock HWE; `swapz_round032_dm_try_accept_owned_view_v1` returns -EOPNOTSUPP even if all mechanical checks pass. No imported Agent2 future original BIO GPL export; ordinary default struct swapz_dm, 20-byte map, upper BIO, lower I/O and module ABI untouched.
2. tests/runtime/native/zswap-compressed-consumer-test.py: inject exact Round030/031/032 actual production C source bodies into one translation unit with source-only fake BIO/lower/authority boundary; GCC+Clang -Wall -Wextra -Wconversion -Wshadow -Werror ASan/UBSan positive mechanical and hostile negative tests; no new C warning suppressions.
3. NEW tests/runtime/native/fixtures/round032-dm-owned-view-host.c: positive source-candidate mechanical copied bytes, true live EOPNOTSUPP, wrong packed swap slot vs DM page, zero/mismatched epoch/stored identity, CRC32C bitflip/incorrect full SHA, codec/ZSTD/version/size/dict, ordinary RAW/READ/DISCARD/flush/multiseg/offset/short/target-out-of-bounds/protected header, stale sequence/generation/GC/token/duplicate hypothetical ACK, missing BIO owner, alias/capacity, double teardown and unchanged destination on every failure, plus preserved real Round031 guarded 4/8/16KiB lower source test.
4. .github/workflows/product-codec.yml: preserved existing default/module and prior FOUR macro source mode, separate NEW fifth-macro Round032 real `dm-swapz.ko` kernel-header build W=1/W=2 for x86_64 and ARM64, independent true nm symbol present under guard ONLY, absent in default and earlier four-macro image.
5. docs/handoff/zswapz/round032/agent3-evidence.md: exact boundaries, host tests and source-vs-loaded classification; subsequent exact job result appended in docs-only closeout SHA 87aff131bd7ac147b0cfa0e3a03a24756106bd00 preserving peer.
6. docs/testing_standards.md: complete >1MiB SHA-verified old standard (1,083,963 bytes), every prior byte preserved, unique substantive Round032 Agent3 3,988-character appended section in SAME original source-changing commit e0ce699ff874000cfb4ac6dee412159ac91da38d. Peer Agent2's later separately headed standards appended under its own commit; both retained.

ACTUAL exact source SHA e0ce699ff874000cfb4ac6dee412159ac91da38d GitHub Actions [run #44167743707](https://github.com/k1moradi/swapz/actions/runs/44167743707) status=completed conclusion=success, 4/4 real jobs SUCCESS:
- Real compile-only x86_64 job 134338227366: SUCCESS, original normal W=1/W=2 and existing Round031 four-macro, NEW Round032 five-macro W=1 and W=2 true external kernel dm-swapz.ko and nm symbol checks.
- Real compile-only ARM64 job 134338227528: SUCCESS, same independent real guarded/normal object construction and W=1/W=2.
- Exact source-C x86_64 job 134338227700: SUCCESS, full native regression plus NEW `test_round032_real_dm_frozen_v1_candidate_source_gcc_clang` compiled and executed with BOTH GCC and Clang ASan+UBSan strict Wconversion/Wshadow Werror, true C extracted from src/kernel/dm-target.c.
- Exact source-C ARM64 job 134338227790: SUCCESS, same source-extracted strict GCC+Clang compiled tests.
First source compiler error, first regression failure: **NONE** in the initial exact e0ce699 source-changing commit; no fix required. Both source-extracted jobs' actual logs contain the new Round032 executed test and completed test suite. All jobs are SOURCE-CI ONLY; no loaded or physical tests.
Same source/evidence published directly to existing sole remote main, source commit single parent frozen task; follow-up evidence-only one-parent nonforce expected-head commit after Agent2's unrelated published file changes; no Agent2 owned source edited.

CRITICAL REMAINING NO-GO: Verified original Linux MM full swp_entry TYPE/OFFSET API + allocator incarnation and original BIO GPL copy-out provider not linked into ordinary HWE DM, nor genuine original same-kernel end-to-end MM zswap stored LZ4 source transported to loaded DM. The positive host candidate is explicitly UNTRUSTED mechanical proof. Original zswap admission still unconditional -EOPNOTSUPP, ordinary REQ_SWAP upper BIO remains original uncompressed 4096, no direct compressed lower WRITE, map publish or upper bio_endio/ACK connected. Existing RAW_4096 original uncompressed full page, future already-stored LZ4 only via separate authenticated volatile ownership with verified exact 4096 readback, zswap alone owns bounded compressed RAM caching and pressure eviction, swapz exclusively SWAPSPACE2 disk tier/packing/GC, no duplicate pressure reclaim.
PHASE_A=BLOCKED; FORCED_RAW_BYPASS=DISABLED; DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED; LOADED_KERNEL=NOT_RUN; PHYSICAL_SWAPSPACE2=NOT_RUN; ORIGINAL_PHYSICAL_FIRST_ATTRIBUTION=UNKNOWN. Protected physical SWAPSPACE2 first full 4096 header/signature/UUID, partition table unchanged, only post-header lower payload+zeros, no on-media metadata or crash-resume claim. No module insertion, mkswap/swapon/swapoff, mapper/null_blk or privileged/physical device, memory pressure, owner make test/fast_test or reboot.

Agent2 has an independent original pinned Linux provider implementation, full CONFIG_ZSWAP=y/n original Kbuild + external probe/UML CI and its own REPORT_READY obligation. Agent1 is owner of final joint acceptance and loaded/hardware gate.
```

## REPORT_READY worker 2 — https://github.com/k1moradi/swapz/issues/149#issuecomment-6960013334

```text
message: REPORT_READY
round: "032"
agent: 2
task: genuine-original-pinned-linux-bio-readonly-source-LZ4-owned-v1-copy-out-gpl-export-and-same-kernel-probe
status: PUBLISHED_PINNED_ORIGINAL_SOURCE; GCC_CLANG_ASAN_UBSAN_AND_SOURCE_MANIFEST_PASS; ORIGINAL_FULL_KERNEL_Y_N_MATCHED_DM_AND_MODPOST_PROBE_IN_PROGRESS; BOOTED_REAL_UML_KUNIT_11_OF_11_SUCCESS
frozen_task_sha: 5d93c9a1c01632355f2d68eb2fb1377978fb122c
original_linux_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
round031_predecessor_complete_CI_run: https://github.com/k1moradi/swapz/actions/runs/44136719185
first_published_agent2_sha: c15efa281c14b8f452e0bf9a1d109bfe02512449
first_published_agent2_parent_preserving_peer: e0ce699ff874000cfb4ac6dee412159ac91da38d
latest_published_agent2_SHA: 4f17d5c9530a225bb7d45727828ba312ad1f6c60
latest_published_agent2_parent_and_peer_doc_preserved_SHA: 87aff131bd7ac147b0cfa0e3a03a24756106bd00
latest_agent2_commit_url: https://github.com/k1moradi/swapz/commit/4f17d5c9530a225bb7d45727828ba312ad1f6c60
publication: EXISTING_MAIN_ONLY_SINGLE_PARENT_NONFORCE_EXPECTED_HEAD_FAST_FORWARDS_WITH_REMOTE_SHA_READBACK_NO_BRANCH_PR_FORK_WORKTREE_FORCE

Original source C paths changed by Agent2 (initial plus fixture correction):
- tests/tools/stage-pinned-linux-zswap-composed.py: exact unmodified torvalds original source Git blobs and complete clean checkout, preserved both prior original MM and BIO stagers read-only; strict disjoint same-preimage composition and full original manifest. Source-generates true original include/linux/bio.h v1 VALUE struct (no pointers), original block/bio.c sealed owner constructor + EXPORT_SYMBOL_GPL(swapz_ci_bio_snapshot_lz4_v1), and true original mm/zswap.c frozen full swp_entry_t.val under locked folio/xarray+epoch and STORE SHA, writing slot into owner BEFORE first reference publication. Old original BIO constructor source-compatible for legacy 11 KUnit, zero source slot always refuses new v1 snapshot. Original block/page IO submits only original UNCOMPRESSED 4096.
- tests/runtime/native/pinned-linux-zswap-composed-source-test.py: strict original source generation + full originally pinned Git blobs, adversarial original same-tree C source extraction into independent GCC+Clang -Werror -Wconversion -Wshadow ASan/UBSan host tests; checks v1 no-pointer layout, source origin, real CRC32C, SHA, source slot/codec/epoch and failure preserving BOTH caller outputs.
- NEW tests/runtime/native/fixtures/round032-bio-copy-view-host.c: injects actual emitted source C from original block/bio.c, tests true stored dictionary-free LZ4 and decoded exact original 4096 SHA, source buffer modified after owner publication, repeat copy, short capacity/no writes, CRC32C mismatch/IEEE mismatch, wrong BIO operation/size, clone/multi-source, missing MM source slot/epoch/stored identity, wrong codec/version, invalid length, aliasing, after uninit and refcount balanced. Corrected exact source-only macro flags used by original C. Fake BIO boundary is host-only, not live source authentication.
- NEW tests/runtime/native/fixtures/round032-bio-probe.c: minimal independent GPL module actually includes original <linux/bio.h>, calls export and is compiled/modposted against SAME patched full kernel original Module.symvers; NOT loaded.
- .github/workflows/phase-a-zswap-composed-source.yml: EXACT original full CONFIG_ZSWAP=y/n W=1/-Werror original modified C, default symbol absence and opt-in nm+objdump, original complete vmlinux/modules/Module.symvers with vmlinux GPL symbol, strict independent GPL external modpost without KBUILD_MODPOST_WARN and source-linked dm-swapz.ko, separately booted exact original UML owner BIO KUnit 11/11 JSON+KTAP. No modified torvalds/linux HEAD.
- docs/handoff/zswapz/round032/agent2-evidence.md and docs/testing_standards.md: full prior SHA-verified >1MiB standards retained byte-for-byte, including peer Agent3 Round032 substantive section; initial and corrective commits EACH include own applicable same-source-commit original standards updates.

First actual strict GCC/Clang failure, no warning suppression:
INITIAL c15efa281c14b8f452e0bf9a1d109bfe02512449 [hosted original-source run 44168124032](https://github.com/k1moradi/swapz/actions/runs/44168124032) job 134339576852 exited 1 at source-extracted GCC/Clang test. First original C fixture diagnostic: `struct swapz_ci_owned_payload has no member named source_swap_entry`; then undeclared source-only constructor and exported accessor; cause the source-injecting C HOST fixture did not set the three explicit NEW and previous original source macro gates, so real C deliberately compiled source-only functions away. GCC/Clang -Werror correctly refused. Minimal fix in published 4f17d5c9 defines exact full three required macro flags in host fixture, does not alter original compiler warnings or fake exported symbol; also fixes legacy-constructor negative vector to use actual saved LZ4 bytes so its refusal is solely missing MM-authenticated full swap slot. Existing original source and previous KUnit unchanged.
Initial c15efa2 same exact original source [UML job 134339576178](https://github.com/k1moradi/swapz/actions/runs/44168124032) independently COMPLETED SUCCESS real original UML booted BIO 11/11 JSON+KTAP, despite separate source-extracted host failure. No falsely merged overall run success.
CORRECTED 4f17d5c9530a225bb7d45727828ba312ad1f6c60 [exact hosted run 44168876688](https://github.com/k1moradi/swapz/actions/runs/44168876688): true original C source-extracted strict GCC and Clang ASan+UBSan test step SUCCESS, exact original same-clean-upstream-tree source composition/manifest SUCCESS, job 134342259183 IN_PROGRESS for full CONFIG_ZSWAP=y/n original linked Kbuild and independent GPL export modpost probe/matched external DM source; job 134342258299 COMPLETED SUCCESS for REAL original pinned 11/11 booted UML with original JSON+KTAP verification. Full y/n plus the distinct strict GPL external modpost probe remain IN_PROGRESS and are not yet VERIFIED PASS.

Real C lifetime: new original immutable flexible-array source slot set before refcount publication; view is distinct value-only no pointer, copied owner bytes 1..3568 with canonical CRC32C, genuine original full 4096 SHA from original MM STORE, epoch and identity. Accessor under stable caller-owned original parent BIO takes synchronous temporary owner ref, checks exact original REQ_OP_WRITE|REQ_SWAP 4096/8 sector, original manually populated bvec/bi_vcnt==0, no clone, typed true MM source slot and owned checksum/codec, no output/source alias, no partial outputs on error; all refs release. No unlocked pointer acquisition, no live compressed BIO or DM admission.

Safety and outstanding: PHASE_A=BLOCKED; DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED; FORCED_RAW_BYPASS=DISABLED; SOURCE_TO_LIVE_DM=NOT_AUTHENTICATED; LOADED_KERNEL=NOT_RUN; PHYSICAL_SWAPSPACE2=NOT_RUN; original RAW always ORIGINAL UNCOMPRESSED FULL 4096. zswap owns small bounded compressed RAM pressure and eviction, swapz disk backing/GC only; original SWAPSPACE2 first 4096 header/signature/UUID and physical partition table never modified. No privileged, loaded, mkswap/swapon/swapoff, mapper/null_blk, physical, pressure or owner hardware tests. Agent1 retains final accountable qualification; no kernel/GPL modpost PASS claim until exact job finishes.
```

