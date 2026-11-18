# Round034 — verbatim original agent reports

Source [issue #151](https://github.com/k1moradi/swapz/issues/151). Both original REPORT_READY bodies below are preserved **verbatim**. Some status values were provisional. The authoritative end-of-round evidence includes an independently discovered **RED current-head repository policy**, not reported by either agent, and Agent3 true original-kernel modpost still pending. See [accountable Agent1 closeout](round-report.md). These reports are not edited to change the historical statements.

## Original worker report 1 — https://github.com/k1moradi/swapz/issues/151#issuecomment-6973214337

~~~~text
message: REPORT_READY
round: "034"
agent: 3
status: REAL_GUARDED_SOURCE_C_AND_STRICT_GCC_CLANG_SANITIZER_PASS; X86_ARM_PRODUCT_C_4_OF_4_PASS; NEW_ORIGINAL_KERNEL_GPL_MODPOST_STILL_IN_PROGRESS_NOT_CLAIMED_PASS
frozen_task_sha: 311ac1073ab17abf4b3dd25dd8c359aea88cbefa
initial_source_changing_sha: 19e10c495d5d64123f667f193bc833618b9fd2d1
initial_parent_sha: 1453933e88ef1b43236231cfb60e6e3518fe3712
corrected_source_changing_sha: cc429362685e9f761114a073c146ac8b74f56492
corrected_parent_sha: cf0de1b5272f6bd78a6968b92c9fdad0f3b32867
evidence_exact_CI_report_sha: c074f734b47e31de11eea570f72bae1fc2a4cc12
evidence_report_parent_sha: abeb3294f476f47c3bfe34eac92f65ec4a0c5952
branch: main
publication: one-parent nonforce expected-head fast-forward with actual remote SHA and parent readback, all intervening Agent2 source/standards preserved. No new branch, PR, fork, worktree, force.

**Agent3 first source-changing commit modified 6 exact owned paths:**
1. src/kernel/dm-target.c: undefined-by-default SWAPZ_ROUND034_DM_SOURCE_SLOT_AUTHORITY_TEST nested behind ALL prior Round024/028/030/031/032/033 DM gates AND original pinned MM/BIO owner flags. The real Linux swapops.h is included only under new macro. Real new source C snap/prepare/try_auth functions under existing ordered_owner; genuine typed original swp_entry_t.val decoding via original swp_type(), swp_offset(), swp_entry() and MAX_SWAPFILES; no guessed offsets or equating original packed source entry with target page. Genuine original source BIO has single full 4096 bvec bi_vcnt==0; real original REQ_OP_WRITE|REQ_SWAP and origin necessary not sufficient; check exact 8 sectors, target geometry/page>0 protecting SWAPSPACE2 block0. Current owner token/GC/inflight/closed/reused sidecar/map generation/CRC/length/extent sequence checked before AND after synchronous original Round033 exact GPL-owned copied v1 helper. A historical already-published test map and hypothetical ACK can only REJECT stale, never authorize a new precommit write. Source copied independently bounded caller-owned value, provider byte copy and private scratch; source full original swp type/offset decoded and stored entry identity/slot epoch/original STORE full 4096 SHA/CRC32C/LZ4 validated. Aliases and output modification on negative return refused, private compressed source scratch wiped. Distinct mechanical-only SOURCE_COPY_MECHANICALLY_VALID is possible in host; SOURCE_MAPPED_AUTHENTICATED NEVER set (no genuine ref-safe exported current original swap_info → original bdev/nonlinear sector → specific DM target and allocator incarnation). Actual try_auth returns -EOPNOTSUPP even on fully mechanically consistent copied v1 and leaves final bytes untouched. Zero live compressed lower I/O, COW map publication or bio_endio/upper ACK, no normal swapz_map callsite, no default RAW behavior alteration.
2. NEW tests/runtime/native/fixtures/round034-dm-source-authority-host.c: exact Round033+Round034 source body hosted with fake ONLY original kernel swapops/BIO/DM authority boundary, real synthetic LZ4+CRC32C+original 4096 SHA; negative wrong original swp_type with identical offset, source epoch+stored ID, byte bitflip/CRC/SHA/ZSTD, length/codec, bvec/origin/WRITE/REQ_SWAP/header0/target-end, stale token/generation/GC/extent/duplicate historical ACK/late BIO and during-provider-copy map/owner ABA; check all output bytes unchanged on rejection and live never authorizes.
3. NEW tests/tools/round034-dm-source-authority-verify.py: source-EXTRACT original actual production Round033 and Round034 C (not parallel algorithm), guard coverage, original Linux symbol boundary, GCC AND Clang strict -Wall -Wextra -Wconversion -Wshadow -Werror ASan+UBSan source C positives/hostile negative and live EOPNOTSUPP. Historic codec.c-only exception isolated; no new C warning suppression.
4. NEW .github/workflows/phase-a-zswap-source-slot-authority.yml: independent exact pristine original torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8 checkout and 10 source postimage SHA-verified composer (READ ONLY), source strict GCC/Clang, true full original CONFIG_ZSWAP=y vmlinux/modules/Module.symvers and W=1/-Werror actual original BIO/MM, real default/NEW guarded production dm-swapz.ko from SAME original KDIR and strict genuine Module.symvers GPL modpost/nm -u/ELF/vermagic, nm ensure new only opt-in symbols present and default absent. No fake provider/KBUILD_MODPOST_WARN/loaded module.
5. NEW docs/handoff/zswapz/round034/agent3-evidence.md: code, CI and precise no-go. Appended first true diagnostics in correction and exact CI results in separate docs-only one-parent report commit.
6. docs/testing_standards.md: complete >1.11MiB old standards, all prior/Agent2 bytes preserved byte-for-byte with own substantial same-source-commit Round034 Agent3 actual source/negative/full original-kernel rules. Additional substantive first-failure appendix in SAME corrective source C commit.

**First true CI compiler failure, preserved RED:** [initial run #44265856915](https://github.com/k1moradi/swapz/actions/runs/44265856915), job 134670067169 COMPLETED FAILURE at original actual Round033+Round034 source-extracted GCC and Clang host, before original vmlinux/modpost: duplicate host fake of existing zswap-import-codec.h swapz_zswap_import_ranges_overlap with conflicting signature, host-only omitted sector_t kernel ABI typedef, unused int status, and one *actual new guarded production source C* passing size_t sidecar.allocated_bytes into u32 overlap helper -Wconversion. Corrected in source SHA cc429362685e9f761114a073c146ac8b74f56492: test fixture uses existing real codec overlap routine, uses mock-only uint64 sector_t, removed unused int; production validates sidecar bytes <= UINT32_MAX before explicit narrowing. Kept all strict Werror warnings ON and no API refactor. Original first red remains red.

**Corrected exact source SHA cc429362685e9f761114a073c146ac8b74f56492 actually executed CI:**
- [production-C run #44266449853](https://github.com/k1moradi/swapz/actions/runs/44266449853) COMPLETED SUCCESS all 4 real jobs: x86_64 native exact source C 134672061529 SUCCESS, ARM64 native 134672060971 SUCCESS, x86_64 real module compile 134672061545 SUCCESS, ARM64 real module compile 134672061455 SUCCESS. The ordinary HWE source does NOT enable original-only new opt-in.
- [NEW true pinned original kernel source+module run #44266449916](https://github.com/k1moradi/swapz/actions/runs/44266449916), job 134672061346: GCC+Clang -Werror ASan+UBSan actually executed exact production C and hostile source/slot negatives PASS; original pristine source composition/ten SHA manifest PASS; last check **IN_PROGRESS** inside full original CONFIG_ZSWAP=y vmlinux/modules/Module.symvers and genuine default+guarded dm-swapz.ko strict modpost step. NO original modpost PASS yet, no original kernel linker first error yet. PREVIOUS Round033 original same-kernel link PASS does NOT automatically certify the new Round034 macro; REPORT_READY is a truthful source-C report pending this one real module gate.

**Still original kernel current authority missing:** Read-only original swp_type()/swp_offset() decode is real and source-compiled in optional guarded module, but it is not original runtime swap_area to precise DM device+offset mapping proof, neither does copied original v1 slot_epoch prove the current allocated incarnation at write publication. No original source→loaded DM compressed handoff or exact 4096 readback. Agent2 independent original zswap-enabled booted UML source tests are NOT Agent3 results.

SAFETY: PHASE_A=BLOCKED; FORCED_RAW_BYPASS=DISABLED; DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED; LOADED_PRODUCTION=NOT_RUN; PHYSICAL_SWAPSPACE2=NOT_RUN; first historical physical error UNKNOWN. Original RAW_4096 is always FULL ORIGINAL UNCOMPRESSED 4096; future dictionary-free STORED zswap LZ4 only reuses RAW LOWER-I/O STAGING with separately tagged RAM metadata, authentic type+allocator epoch+stored ID, original STORE SHA and CRC32C, current DM map generation/GC, durable lower→once ACK and FULL 4096 verified LZ4 READ. Linux zswap alone manages bounded compressed RAM cache and true MM-pressure eviction; swapz disk SWAPSPACE2 tier/packing/GC only, no competitor reclaim. Immutable existing physical SWAPSPACE2 first 4096 header/signature/UUID and partition table; only post-header payload+deterministic zeros, bounded RAM metadata. NO module insertion, privilege, mkswap/swapon/swapoff, mapper/null_blk/physical/pressure/reboot.

~~~~

## Original worker report 2 — https://github.com/k1moradi/swapz/issues/151#issuecomment-6973251410

~~~~text
message: REPORT_READY
round: "034"
agent: 2
status: EXECUTED_GENUINE_PINNED_LINUX_CONFIG_ZSWAP_Y_UML_KUNIT_17_OF_17_PASS; ORIGINAL_MM_PRESSURE_EVICTION_NOT_RUN; PHASE_A_BLOCKED
frozen_task_sha: 311ac1073ab17abf4b3dd25dd8c359aea88cbefa
initial_source_changing_sha: 1453933e88ef1b43236231cfb60e6e3518fe3712
initial_source_parent_sha: 311ac1073ab17abf4b3dd25dd8c359aea88cbefa
corrected_original_C_source_sha: cf0de1b5272f6bd78a6968b92c9fdad0f3b32867
corrected_original_C_source_parent_sha: 19e10c495d5d64123f667f193bc833618b9fd2d1
final_verified_CI_head_sha: abeb3294f476f47c3bfe34eac92f65ec4a0c5952
final_verified_CI_head_parent_sha: a145aee6c861004642e5e8a74d416addb67793de
final_published_evidence_sha: d44b37565b77a6e833ffbf92bce85903a30ea096
final_evidence_parent_sha: c074f734b47e31de11eea570f72bae1fc2a4cc12
branch: main
publication: single-parent non-force expected-head fast-forward plus remote commit/SHA readback on every publication; peers' source and complete testing standards preserved; no branches, PRs, forks, force or worktrees.

**Exact Agent2-owned paths published:**
- `tests/tools/stage-pinned-linux-zswap-composed.py`: genuine upstream-original `block/bio.c` C extension under new undefined-by-default `SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST` plus existing original MM/BIO and KUnit gates, 6 new true original v1 test functions; no original upstream preimage changes or live default path.
- `tests/runtime/native/pinned-linux-zswap-composed-source-test.py`: source composition/case/opt-in gate regression.
- `tests/tools/round034-original-v1-kunit-verify.py`: independent exact 11+6 executed JSON AND KTAP verifier with adversarial fail-closed tests.
- `.github/workflows/phase-a-zswap-original-v1-kunit.yml`: original pinned torvalds/linux UML `CONFIG_ZSWAP=y` real kernel boot and original BIO C test execution, exact source SHA and Kconfig gating, strict source GCC/Clang ASan/UBSan, bounded evidence.
- `docs/handoff/zswapz/round034/agent2-evidence.md`: all first genuine CI failures, remediation, exact final passing job SHA/limitations.
- `docs/testing_standards.md`: full byte-preserving 1.1-MB+ canonical substantive same-source commit append and final verifiable evidence append, including Agent3 intervening content.

**Genuine executed PASS, NOT compile-only:** [Run #44266722765](https://github.com/k1moradi/swapz/actions/runs/44266722765), original UML job `134672971954`, *completed success* at exact tested head `abeb3294f476f47c3bfe34eac92f65ec4a0c5952`, genuine pinned original upstream Linux source `c339f4010dea8b0d754f84ace70cd1b089878ef8`. Strict source-extracted actual provider GCC+Clang, ASan/UBSan and 2 adversarial verifier selftests PASS; ten exact original source SHA256 composition PASS. Real original `kunit.py --arch=um` kernel build+boot returned 0 with effective `CONFIG_ZSWAP=y`, `CONFIG_SWAP=y`, `CONFIG_KUNIT=y`, actual LZ4 compression/decompression and SHA256 library. Real kernel JSON **and** KTAP independently verified old 11 + new 6 = **17/17 PASS**, zero failure/skip/crash/error/duplicates. Evidence [artifact #14410318002](https://github.com/k1moradi/swapz/actions/runs/44266722765/artifacts/14410318002) retains source ten-hash manifest, effective config/kernel/JSON/KTAP digests, actual original `test.log`, JSON, and bounded first-error transcripts. Real original 4096-copy output LZ4-decompressed and matched original 4096 SHA; original `bi_vcnt=0` prepopulated-bvec geometry, flags, epoch/source identity, bad codec/length/CRC, source/destination alias, immutable errors, clone/split/release were executed in actual original block/bio.c.

**First true red CI, immutable and not misreported as passes:** [#44265702441](https://github.com/k1moradi/swapz/actions/runs/44265702441) job `134669558702`: original composer `IndentationError` generated KUnit raw-string missing closing `"""`, no UML; [#44266065489](https://github.com/k1moradi/swapz/actions/runs/44266065489) job `134670776264`: original UML Kconfig refused direct hidden SHA256 library option and disabled BLK_CGROUP child, before boot; [#44266568169](https://github.com/k1moradi/swapz/actions/runs/44266568169): invalid workflow YAML, zero jobs. Fixed with separate expected-head commits; pass belongs exclusively to #44266722765. Historical original y/n composed GPL provider + original DM same-source modpost from Round033 remain separately evidenced; new full y/n job [#44266065630](https://github.com/k1moradi/swapz/actions/runs/44266065630) original 11/11 UML job completed success, full original y/n Kbuild job was still in progress when last checked (NOT claimed PASS).

**Limitations and safety:** Synthetic KUnit *producer stimulus* builds a real original sealed owner and real original BIO copy-out, but is NOT a genuine original MM zswap STORE or actual pressure-driven `zswap_writeback_entry` eviction. Full active type/offset→bdev→DM sector and current slot incarnation authority remain separately unproven by Agent2; neither sample `swp_entry_t.val` nor BIO source flag is a current physical mapping proof. `ORIGINAL_MM_PRESSURE_EVICTION=NOT_RUN`, `LIVE_CURRENT_SOURCE_TO_DM_MAPPING=NOT_PROVEN_BY_AGENT2`, `PHASE_A=BLOCKED`, `FORCED_RAW_BYPASS=DISABLED`, `DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED`, `LOADED_PRODUCTION_4096=NOT_RUN`, `PHYSICAL_SWAPSPACE2=NOT_RUN`. Original RAW means **original uncompressed 4096 bytes**; Linux zswap owns compressed RAM/eviction; swapz remains SWAPSPACE2 disk tier. No privileged kernel/device testing, loaded-production kernel, mkswap/swapoff, physical-device write or mutation of protected SWAPSPACE2 first 4096/UUID/partition table.
~~~~

