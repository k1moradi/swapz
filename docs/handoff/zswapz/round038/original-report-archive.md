# Round038 — verbatim original Agent2 and Agent3 REPORT_READY comment archive

[Official Round038 #155](https://github.com/k1moradi/swapz/issues/155). The **three original worker REPORT_READY bodies below are preserved verbatim** including reported provisional QUEUED/IN_PROGRESS status, exact source SHA/parent, original first failure and NO_GO. The separately [verified later exact CI/accountable report](round-report.md) provides only factual later completed-job updates, never rewrites the original comments or failed CI histories.

## Original REPORT_READY 1: https://github.com/k1moradi/swapz/issues/155#issuecomment-6980416168

~~~~text
message: REPORT_READY
round: "038"
worker: 2
status: SOURCE_IMPLEMENTED_CORRECTED_ORIGINAL_EXACT_SOURCE_CI_QUEUED_LIVE_NO_GO
frozen_task_sha: a41b0936c60c8b8b2cb461edf32a6f86958b1fe3
original_upstream_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
initial_source_sha: 23c35673bc4cddfe999f852d347acb7e143efc10
initial_source_parent: a41b0936c60c8b8b2cb461edf32a6f86958b1fe3
corrected_source_sha: dfda7fca93d338e705ac48dcb41288130ac13389
corrected_source_parent: 734b27ba9585c842a37c166f5ef629b2516c8556
original_store_executed_by_kunit: NO_SYNTHETIC_INPUTS_ONLY
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: NO_GO_DISABLED
forced_raw_bypass: DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN

**Agent2 fully guarded real-original source + independent hosted tests published to sole `main`, no branches/PRs/force/peer overwrite.** Initial [source commit `23c35673`](https://github.com/k1moradi/swapz/commit/23c35673bc4cddfe999f852d347acb7e143efc10) exact frozen parent changed **7 paths**: `tests/tools/stage-pinned-linux-zswap-composed.py`; `tests/runtime/native/pinned-linux-zswap-composed-source-test.py`; new `tests/runtime/native/fixtures/round038-original-store-provenance-host.c`; new `tests/tools/round038-original-store-provenance-verify.py`; new `.github/workflows/phase-a-zswap-original-store-bio-provenance.yml`; own `docs/handoff/zswapz/round038/agent2-evidence.md`; full `docs/testing_standards.md` with original substantial same-commit worker-specific appendix (whole >1MiB preserved). Separately [corrected source commit `dfda7fca`](https://github.com/k1moradi/swapz/commit/dfda7fca93d338e705ac48dcb41288130ac13389) parent **Agent3 published** `734b27ba9585c842a37c166f5ef629b2516c8556`, ONLY **4 Agent2 owned paths**: original composer, new source fixture, own evidence, full canonical standards separate substantial same-correction-commit appendix retaining peer's entire new standards and source. Both remote expected-head nonforce one-parent FF, latest remote/readback verified.

**Original source exact producer:** NEW undefined default `SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST` nested behind all original 025/028/030/031/032/034/035/036/037 and `CONFIG_KUNIT`, no added public symbol/v1 ABI. Previously real original `zswap_store_page` binds locked ORIGINAL 4096-byte folio `sha256(original_page, PAGE_SIZE,...)`, full typed `swp_entry_t.val`, current allocator slot epoch and monotone STORE identity precompression. NEW original `zswap_compress` guarded observation captures exact `~crc32c(~0U,dst,dlen)` from authentic dictionary-free LZ4 compressed output **right after genuine `zs_obj_write` and before original compressor mutex release**, 1..3568, no recompress, extra allocation or default hot path. New real `xa_store` accepted-site probe detects current original entry and leaves source authority NO_GO. At original pinned `zswap_writeback_entry` locked folio and `xa_load(tree,offset)==entry` current, original bounded zsmalloc SG copy computes independent CRC32C and now verifies equality with STORED original compressor CRC before constructing the independently BIO-owned copied value; mismatch drops COPY, original decompressed uncompressed 4096 WRITE always goes through unchanged. Original BIO owns refs until uninit/clone/split/abort, previous original MM area ref only scoped; cannot pin allocator incarnation/current DM map/generation/GC over async completions.

**New test scope:** Actual original-C new KUnit suite `swapz_round038_original_store_provenance_no_authority` **FIVE negative stimulus cases** for old STORE same swp type/offset epoch/identity ABA, CRC bitflip/independent full original STORE SHA mismatch, compressed length 0/3569 wrong codec/full length, invalidated/replaced entry or stale owner/folio lock/malformed BIO, forged positive current slot+DM GC refs and unchanged source. Prior 31 source cases retained => NEW workflow requires **36 uniquely executed genuine booted original Linux `CONFIG_ZSWAP=y` KUnit with independently verified JSON + KTAP**, no compiled-only/skips. Host strict source-extracted GCC and Clang ASan+UBSan and hostile evidence self-tests; authentic pristine ten-file SHA staging; separate full ORIGINAL x86 `CONFIG_ZSWAP=y/n` complete `vmlinux/modules/Module.symvers`, original GPL independent `round032-bio-probe.ko` and matched real `dm-swapz.ko` strict modpost/vermagic, exact-source repository-policy and CI census. The KUnit positive-shaped inputs are SYNTHETIC, **not actual accepted zswap STORE+natural memory-pressure eviction**; `ORIGINAL_STORE_EXECUTED=NO`, no fabricated live source token.

**FIRST GENUINE initial-source failures (retain historical RED, no waiver):** [initial original workflow #44315936135](https://github.com/k1moradi/swapz/actions/runs/44315936135), UML job `134841922942` **FAILED before new kernel boot/KUnit**, after BOTH GCC+Clang successfully compiled and ran actual extracted original C under -Werror/ASan+UBSan: first source regression `AssertionError: 'ROUND031_REAL_' not found in 'ROUND038_ORIGINAL_STORE_PROVENANCE_EXTRACTED_C_HOST_PASS\n'` (shared original extracted-C harness expects the `ROUND031_REAL_` prefix). Corrected ONLY new fixture stdout marker to `ROUND031_REAL_ROUND038_ORIGINAL_STORE_PROVENANCE_EXTRACTED_C_HOST_PASS`; this was a TEST assertion, not C compile or KUnit failure. Separate full original x86 job `134841923935` **FAILED** at genuine `mm/zswap.c:992:55` strict original C compiler `implicit declaration of function 'crc32c' [-Werror=implicit-function-declaration]` followed by later `include/linux/crc32.h:82:5` conflicting CRC declaration, stage `enabled-original-guarded-zswap` code 2. Round030's CRC include was generated only near the later original `zswap_writeback_entry`, after new call in original earlier `zswap_compress`. Corrected by adding guarded `#include <linux/crc32c.h>` at TOP original mm/zswap.c BEFORE compressor, preserving older include and all warnings. Actual initial x86 full Kbuild+modpost and initial new 36 KUnit NOT qualified; both first failures remain RED.

**Corrected exact SHA CI as of report:** [new true original workflow #44316779722](https://github.com/k1moradi/swapz/actions/runs/44316779722), actual original 31+5 UML job `134844876053` and full original x86 y/n/GPL+matched DM job `134844876848` **QUEUED; no claim PASS**. [Exact-source native/policy #44316779239](https://github.com/k1moradi/swapz/actions/runs/44316779239), repo-policy job `134844875694` **QUEUED; no claim PASS**. The source-host extracted BOTH GCC/Clang successfully compiled and EXECUTED on first source but harness marker test failed; new corrected source must independently pass. Other current peer CI statuses independent; no retrospective source test reuse.

**Proof limit and absolute safety:** Original STORE-time CRC + original SHA/identity does NOT create an allocation-incarnation ref-safe lease from original MM area/bdev/nonlinear sector to correct current DM mapping/extent+GC through source BIO clones/splits, swapoff or late original completion; all live routing still `-EOPNOTSUPP`, `SOURCE_MAPPED_AUTHENTICATED=0`. No real loaded original MM-pressure STORE→eviction, real lower disk/upper ack or physical qualification. zswap alone bounded compressed RAM and pressure eviction; swapz only existing valid SWAPSPACE2 payload 4/8/16KiB disk extents/GC, no competing reclaim. Ordinary RAW is ALWAYS **original uncompressed full 4096 bytes**, copied zswap LZ4 would be distinct RAM-only source-tagged representation via RAW LOWER-I/O byte-staging only if separately authorized. First ENTIRE SWAPSPACE2 4096 header/signature/UUID and partition table immutable. `PHASE_A=BLOCKED`, `DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED`, `FORCED_RAW_BYPASS=DISABLED`, `LOADED_PRODUCTION=NOT_RUN`, `PHYSICAL_SWAPSPACE2=NOT_RUN`; NO privileged mkswap/swapon/swapoff/module load/mapper/null_blk/host pressure/physical tests.
~~~~

## Original REPORT_READY 2: https://github.com/k1moradi/swapz/issues/155#issuecomment-6980512439

~~~~text
message: REPORT_READY
round: "038"
worker: 3
status: SOURCE_PUBLISHED; INITIAL_CI_GENUINE_RED_DIAGNOSED_AND_CORRECTED; NEW_EXACT_SOURCE_CI_QUEUED; LIVE_NO_GO
frozen_task_sha: a41b0936c60c8b8b2cb461edf32a6f86958b1fe3
initial_agent3_sha: 734b27ba9585c842a37c166f5ef629b2516c8556
initial_agent3_parent: 23c35673bc4cddfe999f852d347acb7e143efc10
corrected_agent3_sha: ecec7d5b59c511beb5c232c5559f6f0fa3a52599
corrected_agent3_parent: dfda7fca93d338e705ac48dcb41288130ac13389
original_upstream_linux_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
phase_a: BLOCKED
source_mapped_authenticated: 0
forced_raw_bypass: DISABLED
direct_compressed_handoff: NO_GO_DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN

**Round038 Agent3 original fake lower READ source and later verifier correction directly published on sole main, single-parent non-force expected-head fast-forward with exact latest remote SHA readback.** Agent2 independent original-source commits, every peer byte and latest complete >1MiB standards preserved in both commits. No new branch/PR/fork/worktree/force.

Initial Agent3 [source commit 734b27ba](https://github.com/k1moradi/swapz/commit/734b27ba9585c842a37c166f5ef629b2516c8556), parent EXACT Agent2 first source 23c35673: SIX files:
- src/kernel/dm-target.c
- tests/runtime/native/fixtures/round038-dm-async-read-host.c
- tests/tools/round038-dm-async-read-verify.py
- .github/workflows/phase-a-zswap-dm-async-read-gc.yml
- docs/handoff/zswapz/round038/agent3-evidence.md
- docs/testing_standards.md (full canonical 1.19MiB preserved, Agent2 append + substantive new unique Agent3 same-source section)

Correction [ecec7d5b](https://github.com/k1moradi/swapz/commit/ecec7d5b59c511beb5c232c5559f6f0fa3a52599), parent EXACT Agent2 independent correction dfda7fca, TWO files: own tests/tools/round038-dm-async-read-verify.py and full peer-preserving docs/testing_standards.md with SECOND substantive unique same-verifier-change appendix.

**Actual first source CI** [#44316431468](https://github.com/k1moradi/swapz/actions/runs/44316431468): repository policy job 134843655743 COMPLETED SUCCESS, x86-64 actual native default/prior-guard module job 134843656538 COMPLETED SUCCESS, ARM64 actual native default/prior-guard module job 134843656541 COMPLETED SUCCESS. Genuine FIRST failure in original-same-kernel-dm job 134843656719 at NEW source-extracted host-verifier *before* GCC/Clang or any original kernel build: AssertionError "expected one Round037 real source fixture main" in tests/tools/round038-dm-async-read-verify.py; inherited Round030→037 compound source correctly includes TWO textual int main(void) occurrences, not one. This is a real test-composition error, NOT a production C compiler error or actual GPL modpost failure. First run remains immutable FAILED. Correction requires exactly two and renames only LAST entry with rsplit, preserving previous real source; eliminates a no-op guard check. No warning suppression.

**Fresh corrected-source CI** [#44317264201](https://github.com/k1moradi/swapz/actions/runs/44317264201), new repo-policy job 134846569266, new native x86-64 134846569637 and ARM64 134846569696, new original-same-kernel-dm 134846569796: ALL QUEUED at last actual GitHub observation; NOT CLAIMED PASS. This fresh original workflow must execute exact source-extracted gcc+clang strict -Wall -Wextra -Wconversion -Wshadow -Werror ASan+UBSan and true pristine original Linux CONFIG_ZSWAP=y full vmlinux/modules/Module.symvers unique GPL provider+default/guarded matching production DM W=1/-Werror strict modpost/ELF/vermagic. Any new first genuine failure must be recorded, and no previous workflow is substituted. Prior Round037 baseline original kernel CI was green but is NOT Round038 qualification.

**Source READ design:** actual production DM NEW undefined/default OFF SWAPZ_ROUND038_DM_ASYNC_READ_GC_TEST nested in previous Round037/036 source; Round037 actual copied owned LZ4 source, fake 4/8/16KiB postheader WRITE and private one hypothetical prior ACK; new READ snapshot captures full original type+offset, allocator slot epoch, original STORE identity/full independent 4096 SHA, source LZ4 CRC/codec/length, mock map owner/generation/GC/extent/target witness without any callback borrowing ctx/BIO/target/sidecar. Owner-serialized PREPARE/SUBMIT/FINISH/CANCEL and spinlocked separately scheduled FAKE lower READ callback/tombstone/ref with monotone ticket. Recheck current MOCK original source + actual DM GC/owner/target/slot/extent before and after lower read and immediately before copying any upper byte; validate read size, deterministic padding, CRC32C, original dictionary-free LZ4 EXACT 4096 and full original STORE SHA into scrubbed private buffers. Only after checks copy a full 4096 to a caller-owned MOCK upper buffer; never real map/disk/bio_endio. Fixture comprises inherited earlier exact C tests plus 3 × 45 hostile cases: GC before/after, remap, source same-offset type and epoch/STORE ID ABA, owner/teardown, callback positive/negative/short/replay, cancelled callback drain, A→B→A ticket refusal, malicious recomputed CRC but wrong independent SHA, dirty pad, sentinel unchanged, immutable first 4096 SWAPSPACE2 protected header.

**Truth boundary:** original zswap STORE provenance is not a live source→DM lease; fake lower memory image is not actual durable I/O, map, or real upper BIO ACK. Original genuinely pressure-evicted authenticated SOURCE_MAPPED_AUTHENTICATED=0, no claim of real disk read, live SRC, loaded/physical partition trial. zswap ONLY bounded compressed RAM/genuine pressure; swapz ONLY existing SWAPSPACE2 backing/extent+GC. Ordinary RAW_4096 means ORIGINAL full UNCOMPRESSED 4096 bytes and first physical SWAPSPACE2 header+UUID/signature/partition table immutable.

Fresh exact-source CI status addendum can follow as GitHub jobs complete; this comment's QUEUED observations are explicitly provisional.
~~~~

## Original REPORT_READY 3: https://github.com/k1moradi/swapz/issues/155#issuecomment-6981859326

~~~~text
message: REPORT_READY
round: "038"
worker: 3
status: CORRECTIVE_SOURCE_PUBLISHED_HOST_GCC_CLANG_SANITIZERS_PASS_ORIGINAL_KBUILD_IN_PROGRESS_LIVE_NO_GO
frozen_task_sha: a41b0936c60c8b8b2cb461edf32a6f86958b1fe3
published_sha: a15a5d119a0eda9b2dd6ba9a651bc791a9dfb18e
parent_sha: ecec7d5b59c511beb5c232c5559f6f0fa3a52599
original_upstream_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
phase_a: BLOCKED
source_mapped_authenticated: 0
forced_raw_bypass: DISABLED
direct_compressed_handoff: NO_GO_DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN

**Round038 Agent3 corrective source published directly to sole existing main**, single-parent nonforce `expected_sha=ecec7d5b` fast-forward and exact GitHub remote SHA/parent/all blob readback, preserving Agent2 source and complete prior+peer 1.209 MiB standards. No new branch, PR, fork, worktree or force.

**Three changed paths:**
- `tests/runtime/native/fixtures/round038-dm-async-read-host.c`: repair FAULT 35's synthetic outstanding reader lifetime by asserting **production sidecar teardown must return -EBUSY** with one fixture-owned reader, then draining exactly one reference and verifying successful teardown. Prior fake READ callback, genuine product-C extraction and 3 × 45 4/8/16KiB GC, source epoch/STORE-ID, type+offset, target, extent/replay/cancel, copied CRC/LZ4/original full 4096 SHA, atomic mock output, header-preservation cases unchanged.
- `docs/handoff/zswapz/round038/agent3-evidence.md`: accountable real-first-failure cause and corrected scope.
- `docs/testing_standards.md`: whole canonical >1MiB prior content and Agent2 appendix preserved, **new unique substantive same-commit Agent3 teardown-drain/first RED regression appendix**.

**Real first failure preserved (do not reclassify):** Previous corrected commit `ecec7d5b` [workflow #44317264201](https://github.com/k1moradi/swapz/actions/runs/44317264201) had original-same-kernel-DM job `134846569796` **FAILED**, though both GCC and Clang compiled actual source, their host executable aborted at fixture fault 35 on `swapz_round031_dm_forget_on_swapoff_or_teardown(&ctx, &sidecar) == 0`. This was a genuine test fixture reference drain omission, while production correctly refused teardown with readers. An even earlier `734b27ba` first RED was a source-composer two-main assertion. Neither historical failed run is marked PASS. Independent Agent2 KUnit/Kbuild RED is not changed or claimed by Agent3.

**FRESH source SHA CI #44326821024** at actual latest observation:
- `134880231228` repository-policy: **COMPLETED SUCCESS**
- `134880230524` native x86_64 default+older guarded true module: **COMPLETED SUCCESS**
- `134880231294` native ARM64 default+older guarded true module: **COMPLETED SUCCESS**
- `134880231581` original-same-kernel-DM: **IN_PROGRESS**, prerequisite install SUCCESS; GCC **and** Clang strict `-Wall -Wextra -Wconversion -Wshadow -Werror` ASan+UBSan actual DM source C with hostile 3 × 45 read/GC/ABA/output tests **STEP SUCCESS**; exact pristine original ten-file SHA composer stage **STEP SUCCESS**; actual `CONFIG_ZSWAP=y` full original vmlinux/modules/Module.symvers and matched default+guarded GPL strict same-original-KDIR modpost/vermagic **IN_PROGRESS, NOT YET QUALIFIED**. No claim of final whole-job PASS or Kbuild result until GitHub completes.
- Other full x86/ARM and exact-SHA aggregator actions triggered on the source SHA but remain separate qualification and must not be reported as PASS while in progress.

**Safety/limits:** Original zswap alone manages bounded compressed RAM and genuine memory-pressure eviction; swapz alone owns SWAPSPACE2 disk backing 4/8/16KiB extents and GC. Original ordinary RAW remains UNCOMPRESSED 4096 bytes. This fixture uses exclusively source-copied LZ4 PRIVATE fake lower RAM image and MOCK upper 4096 copy; no authenticated original MM allocator incarnation-to-current-DM-extent ref-safe lease, actual lower READ, durable write/map, real `bio_endio`, pressure eviction, physical partition, loaded module or privileged test. First entire physical 4096 SWAPSPACE2 header/signature/UUID and partition table immutable. `PHASE_A=BLOCKED`, `SOURCE_MAPPED_AUTHENTICATED=0`, direct compressed handoff/forced RAW bypass DISABLED, `LOADED_PRODUCTION=NOT_RUN`, `PHYSICAL_SWAPSPACE2=NOT_RUN`.
~~~~

