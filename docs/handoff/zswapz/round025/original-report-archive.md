# Round025 — complete original worker reports and source updates, verbatim

These eight comments are exact bodies from the official issue #142. Historical statements of pending CI are left intact. Current final-SHA results are independently verified in the accountable integration report, not inferred from the original report timestamps.

## Agent2 STORE REPORT_READY — original https://github.com/k1moradi/swapz/issues/142#issuecomment-6942105245

message: REPORT_READY
round: "025"
agent: 2
status: SOURCE_PUBLISHED_MAIN; EXACT_SOURCE_KBUILD_RUNNING; TRUE_STORE_EPOCH_UNAVAILABLE
task_publication_sha: 7c3b087e8af3a428b2703902653140ed4c9e7a5f
frozen_engineering_source_sha: c2469a86107f632dc795f4957113234f5bac62f6
published_main_sha: 0058efbac906d46b39e9eae87c70de85a5dc1188
sole_parent_sha: 59a743c9ac62d0d1d95c964acef87cf8649bf788
publication: NON_FORCE_EXPECTED_HEAD_FAST_FORWARD_AND_REMOTE_READBACK_VERIFIED
source_commit: https://github.com/k1moradi/swapz/commit/0058efbac906d46b39e9eae87c70de85a5dc1188
source_evidence: https://github.com/k1moradi/swapz/blob/0058efbac906d46b39e9eae87c70de85a5dc1188/docs/handoff/zswapz/round025/agent2-evidence.md
source_workflow: https://github.com/k1moradi/swapz/actions/runs/44041788797
kunit_workflow: https://github.com/k1moradi/swapz/actions/runs/44041788761
LIVE_STORED: NOT_RUN
STORE_SLOT_EPOCH: UNAVAILABLE
LOADED_4096: NOT_RUN
PHYSICAL: NOT_RUN
DIRECT_COMPRESSED: DISABLED
PHASE_A: BLOCKED
FORCED_RAW_BYPASS: DISABLED

### Exact source scope
A separate Agent3 and Agent4 had already published on sole main before this commit. I independently reconciled only my unpublished Agent2 source with their append-only standards, with NO branches, PRs, forks, worktrees, force or rewrite. The single-parent GitHub Git Data API expected-head `update_ref(main, expected_sha=59a743c9ac62d0d1d95c964acef87cf8649bf788, force=false)` returned success. Readback of remote `main` was EXACTLY `0058efbac906d46b39e9eae87c70de85a5dc1188`. GitHub compare parent..commit `ahead_by=1 behind_by=0`, six **exclusively Agent2 owned/append-only** paths:
- `tests/tools/stage-pinned-linux-zswap-origin.py` (+164/-5): source-identical Round025 original STORE SHA256 C function behind `SWAPZ_ROUND025_STORE_PROOF_KBUILD_PROBE` and exclusive `--with-round025-store-proof-probe` conjunction with preexisting Round024 pinned compile probe; original full Linux pinned upstream checkout/blobs and source hash/slice validation retained; deliberate negative epoch, bounded temporary owner, map/sha256/unmap, zeroize/free. No runtime caller or valid compressed publish.
- `tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py` (+94): executable GCC/Clang strict ASan/UBSan compile of actual staged C, real libcrypto original SHA256, independent Python 4096 digest and adversarial source/identity/ownership checks.
- `tests/runtime/native/fixtures/round025-producer-store-proof.c` (new, 213 lines): exact-source host C environment with OpenSSL SHA256, independent original digest `d67c656e01756650d77717b0839985a056ec28ffe174601d690fc407a2ceffca`; owner allocated/scrubbed/freed twice, map/unmap, allocator failure, null/unlocked/non-swapcache source, invalid folio index, xarray ABA, slot/handle/length/pool/ZSTD mismatch, all-true still `-EOPNOTSUPP`. Host types are synthetic; this does not establish a genuinely loaded STORE.
- `.github/workflows/phase-a-zswap-origin-prototype.yml` (+41/-5): stages pinned exact original Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8` with both compiled CI-only source probes and validates explicit `TEMPORARY_SHA_SNAPSHOT_NO_SLOT_EPOCH`/direct handoff=false manifest. Existing genuine GCC default `CONFIG_ZSWAP=y` object must omit both probe symbols; Round024 opt-in preserved; genuine GCC `W=1 KCFLAGS="-DSWAPZ_ROUND025_STORE_PROOF_KBUILD_PROBE=1 -Werror" mm/zswap.o` must emit exactly the new function in `nm` and `objdump` machine code, then default object restored with `KCFLAGS=-Werror`, both symbols absent. Existing whole modified Linux y/n Kbuild, complete Module.symvers, matched dm-swapz.ko and separate BIO KUnit remain unchanged.
- `docs/handoff/zswapz/round025/agent2-evidence.md` (new): original function, crypto API, original folio, swap slot reuse/invalidate/pool lifetime and honest limitation, commands/status.
- `docs/testing_standards.md` (+86 only): uniquely titled Round025 Agent2 standard appended to **latest peer-preserving** existing ~1 MiB source; all Agent3/4 sections preserved.

### Actual source-authentic feasibility findings
Exact pinned `zswap_store_page()` receives folio/index under folio lock, compresses with `zswap_compress()` using original folio, sets `pool_idx`, xarray-publishes, frees old entry, pins pool and initializes the new source entry/LRU. `include/crypto/sha2.h` declares genuine `sha256(...,SHA256_DIGEST_SIZE)` (32 bytes); `kmap_local_folio` can map the original 4096 plaintext before it is lost. Thus a bounded original SHA can in principle be captured at true store. But real upstream `zswap_entry` has NO independently MM swap allocator-issued slot reuse generation or persistent original plaintext digest. `swap_range_free()` calls `zswap_invalidate()`, replacement frees old entry and swapoff tears down drained xarrays; an authenticated owner must hook genuine slot allocation/reuse/invalidation with ref/lifetime. This round intentionally DOES NOT connect a fake epoch to runtime. It allocates one temporary zeroed bounded witness (32 original SHA + metadata) in a source-only unused helper, computes SHA over exact original 4096, unmaps, scrubs the complete owner and frees once, then unconditionally returns negative due unavailable epoch. No permanent per-entry memory/CPU cost, no pressure/reclaim policy or clone/split-aware compressed BIO.

### Actual tests and first failures (NOT inflated)
- Local command `git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main`: **EXIT 128**, first local failure `Could not resolve host: github.com`; no mounted local clone or full pinned Linux checkout. Actual local toolchain `gcc (Debian 14.2.0-19)`, `clang version 17.0.0`, OpenSSL header/libcrypto present; toolchain detection is NOT a compiled-source PASS.
- GitHub connector exact original source inspections executed for `mm/zswap.c`, `include/crypto/sha2.h`, `include/linux/highmem.h` and `mm/swapfile.c` at upstream exact SHA; exact source blob review verifies staged function, 4096 hash, 32 digest, source-only guard, bounded single `kzalloc`, one `memzero_explicit` and `kfree`, source validator forbids success result, default tool unchanged. **STATIC SOURCE REVIEW PASS** (not Kbuild).
- Local exact `python3 -B tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py`, `python3 -B tests/runtime/native/pinned-linux-zswap-origin-stage-test.py`, `git diff --check` on full checkout, strict original-source GCC/Clang+ASan/UBSan, actual pinned `CONFIG_ZSWAP=y/n` `mm/zswap.o`/vmlinux/module Kbuild and source BIO KUnit: **NOT_RUN LOCALLY** due unavailable checkout. The source-controlled tests and exact commands are committed for GitHub-hosted execution, not fabricated as local results.
- Exact committed SHA triggered [pinned real source workflow #44041788797](https://github.com/k1moradi/swapz/actions/runs/44041788797), and [BIO KUnit #44041788761](https://github.com/k1moradi/swapz/actions/runs/44041788761). At this report observation, pinned source job `133897849028` **IN_PROGRESS, cloning exact full upstream Linux**, so its strict GCC/Clang C and real matched Linux Kbuild results are **PENDING, NOT PASS**. Any future exact compiler/API failure is a real BLOCKER, not to be suppressed. The first **engineering blocker already demonstrated by original source** is missing authenticated MM slot allocation epoch, not an unresolved alternative CRC or original folio pointer.
- No loaded kernel zswap STORE, swapin or physical operations run. No loader, `mkswap`, `swapon`, `swapoff`, `null_blk`, cgroup pressure, dm operations or root hardware.

**Safety:** existing valid SWAPSPACE2 first 4096-byte header/UUID/signature/partition table completely untouched, on-media remains payload+zero padding only, metadata RAM-only. RAW is ORIGINAL **UNCOMPRESSED** 4096 bytes; future zswap compressed LZ4 requires distinct RAM-tagged representation and authenticated slot+epoch/owner+decoder before any admission. Normal `zswap_decompress` -> original full 4096 `REQ_SWAP` WRITE remains active. `PHASE_A=BLOCKED`; `FORCED_RAW_BYPASS=DISABLED`; `DIRECT_COMPRESSED=DISABLED`.
MAIN_WRITE_LEASE_RELEASED

---

## Agent2 source staging update — original https://github.com/k1moradi/swapz/issues/142#issuecomment-6942114257

message: SOURCE_UPDATE
round: "025"
agent: 2
published_sha: 0058efbac906d46b39e9eae87c70de85a5dc1188
status: EXACT_HOSTED_ROOTLESS_STAGING_AND_GCC_CLANG_OWNERSHIP_PASS; REAL_PINNED_LINUX_AND_MATCHED_MODULE_KBUILD_IN_PROGRESS
source_ci: https://github.com/k1moradi/swapz/actions/runs/44041788797
source_job: 133897849028
STORE_SLOT_EPOCH: UNAVAILABLE
LIVE_STORED: NOT_RUN
LOADED_4096: NOT_RUN
PHYSICAL: NOT_RUN
DIRECT_COMPRESSED: DISABLED
PHASE_A: BLOCKED

New exact-SHA hosted evidence, supplementing REPORT_READY #6942105245: `Run source-controlled rootless staging regression` completed **SUCCESS**; `Run disabled compressed handoff source/ownership negative regression` completed **SUCCESS** (the existing actual staged kernel-C GCC/Clang strict ASan/UBSan test now includes Round025 exact-source original 4096 SHA256/OpenSSL + bounded allocation/zeroization and missing slot reuse epoch refusal); `Modify actual pinned Linux C and H in disposable full checkout` completed **SUCCESS**, including original pinned source/blob checks and `git diff --check`. The separately authoritative step `Build modified Linux and matched source-linked swapz module for both configurations` was **IN_PROGRESS** at this observation; do not claim true Round025 `mm/zswap.o` `nm`/`objdump`, matched `CONFIG_ZSWAP=y/n`, complete `vmlinux/modules` or `dm-swapz.ko` PASS until that step completes. Genuine loaded zswap STORE original 4096 SHA/epoch and physical SWAPSPACE2 have **NOT_RUN**. No authorization/status change.

---

## Agent3 DM REPORT_READY — original https://github.com/k1moradi/swapz/issues/142#issuecomment-6942176087

message: REPORT_READY
round: "025"
agent: 3
status: SOURCE_PUBLISHED_MAIN; GENUINE_DM_MODULE_KBUILD_X86_64_ARM64_PASS; ORIGINAL_SOURCE_GCC_CLANG_NEGATIVE_PASS; LOADED_NOT_RUN
task_publication_sha: 7c3b087e8af3a428b2703902653140ed4c9e7a5f
published_source_sha: 5d314cb5b55170bc38437e3031b85e5326017c51
initial_source_sha: 382ef9fbe06a6f2a6ced726300ca7364e862e7ad
source_commit: https://github.com/k1moradi/swapz/commit/382ef9fbe06a6f2a6ced726300ca7364e862e7ad
tested_correction: https://github.com/k1moradi/swapz/commit/5d314cb5b55170bc38437e3031b85e5326017c51
publication: non-force expected-head direct main fast-forward, pre/post checked, peer Agent2/4 commits preserved
remote_main_containing_source_at_report: 6278c684dd15cc1be407f3393589de0a520e0b0e
phase_a: BLOCKED
phase_b_forced_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED
LOADED=NOT_RUN
LOADED_4096=NOT_RUN
PHYSICAL=NOT_RUN
LIVE_COMPRESSED=DISABLED

Exclusive changed files (initial commit and correction):
- src/kernel/dm-target.c — compile-only Round025 function reads the REAL worker-owned ctx->authority.maps[logical] generation/valid/raw/payload_length/CRC and read-only checks 4096 upper WRITE, purported DM GC epoch, durable transaction phase, lower byte count, ACK zero and teardown, always refuses -EOPNOTSUPP/-ESTALE even for apparently matching descriptors. No new runtime call site or mapping/upper completion mutation.
- tests/runtime/native/zswap-compressed-admission-test.py — executable *source-extracted* exact C negative test; strict GCC/Clang -Wall -Wextra -Wconversion -Wshadow -Werror -fsanitize=address,undefined -fno-sanitize-recover=all; source assertions also preserve original Round024 gate.
- tests/runtime/native/fixtures/round025-consumer-dm-authority.c — adversarial invalid generation, stale GC, short/failed lower WRITE, wrong upper size, duplicate/early upper ACK, teardown, raw-versus-import identity, length/CRC mismatch, invalid mapping/source, all refusal.
- .github/workflows/product-codec.yml — exact module x86-64+ARM64 isolated real external Kbuild probe, require `nm -a dm-target.o` emission of Round025 function and Round024 probe; existing W=1/W=2/normal module builds preserved.
- docs/testing_standards.md — unique Agent3 Round025 section; append-only first test regression/correction, preserving all preceding and Agent2/Agent4 peer sections.
- docs/handoff/zswapz/round025/agent3-evidence.md — authority limitations and exact first-failure record.

Actual exact-SHA tests and recorded results:
1. https://github.com/k1moradi/swapz/actions/runs/44042160086 at final source 5d314cb5: COMPLETED SUCCESS, job 133899067114. Commands include `python3 -B tests/runtime/native/zswap-compressed-cross-abi-frozen-test.py -v`, `python3 -B tests/runtime/native/zswap-compressed-cross-abi-test.py -v`, and `python3 -B tests/runtime/native/zswap-compressed-admission-test.py -v`; logs show `test_round025_real_dm_authority_source_compiler_negative ... ok`, 4/4 admission tests PASS. The new test compiles the literal extracted source body with GCC and Clang strict flags, ASan/UBSan, and executes the 4096/GC/ACK negations; no invented enabled consumer.
2. https://github.com/k1moradi/swapz/actions/runs/44042160083 at same exact SHA: compile-only arm64 job 133899067136 COMPLETE SUCCESS and x86_64 job 133899067362 COMPLETE SUCCESS. Both actually ran external module Kbuild of dm-swapz.ko with isolated `KCFLAGS=-DSWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE=1` profile, `nm -a build/kernel/round024-dm-ingress/dm-target.o | grep -q swapz_round025_dm_authority_kbuild_probe`, and logs printed `ROUND025_DM_AUTHORITY_ACTUAL_MODULE_KBUILD_COMPILED_DEFAULT_OFF` and `COMPILE_ONLY_NO_MODULE_INSERTION`. Broad exact-c jobs were still running at report time: NOT CLAIMED AS PASS.
3. Initial exact-SHA 382ef9fb workflows 44041248021 and 44041248220 FAILED before source C compile due to my test assertions: expected one opt-in guard but correctly found two (`AssertionError: 2 != 1`) and extractor had double-escaped newline resulting in `AssertionError: 0 != 1`. Corrected only owned test/append-only evidence at 5d314cb5 and retested as above. No original compiler/API error was observed in actual x86_64/ARM64 Kbuild at tested SHA; first source regression and its correction are documented, not hidden.

The real DM engine uses serial `swapz_engine_complete_batched_run` for lower completion -> RAM map publication, then ordered owner upper ACK; transaction mock integers/GC epoch, source slot or `bi_swap_origin` scalar are NOT authenticated compressed MM/BIO ownership. Agent2 source STORE epoch and Agent4 BIO lifetime remain independently unintegrated; no joint ABI, no loaded readback, no physical swap. Current RAW is ORIGINAL UNCOMPRESSED full 4096 bytes and future LZ4 compressed requires separate record + real decoder. SWAPSPACE2 protected first 4096 header/signature/UUID/partition table unchanged, RAM metadata only. Agent1 owns final exact-SHA integrated CI acceptance.

---

## Agent3 corrected exact CI — original https://github.com/k1moradi/swapz/issues/142#issuecomment-6942184411

message: SOURCE_UPDATE
round: "025"
agent: 3
published_sha: 5d314cb5b55170bc38437e3031b85e5326017c51
status: EXACT_SHA_PRODUCTION_C_WORKFLOW_ALL_4_JOBS_SUCCESS; GENUINE_DM_MODULE_KBUILD_X86_64_ARM64_PASS; ORIGINAL_SOURCE_GCC_CLANG_ASAN_UBSAN_PASS
report_ready: https://github.com/k1moradi/swapz/issues/142#issuecomment-6942176087
exact_source_workflow: https://github.com/k1moradi/swapz/actions/runs/44042160083
exact_source_cross_abi: https://github.com/k1moradi/swapz/actions/runs/44042160086

Supplement to REPORT_READY: The previously-running entire `Experimental swapz production C qualification` run 44042160083 at 5d314cb5 has now COMPLETED **SUCCESS**, all four jobs EXIT=0:
- x86_64 exact-c job 133899067411 SUCCESS
- ARM64 exact-c job 133899067426 SUCCESS
- x86_64 real external dm-swapz.ko module compile-only job 133899067362 SUCCESS
- ARM64 real external dm-swapz.ko module compile-only job 133899067136 SUCCESS

The new guarded `swapz_round025_dm_authority_kbuild_probe` emitted in real `dm-target.o` was checked by `nm` on both architectures; logs printed `ROUND025_DM_AUTHORITY_ACTUAL_MODULE_KBUILD_COMPILED_DEFAULT_OFF`. The independent cross-ABI source-extracted strict GCC/Clang + ASan/UBSan native negative test suite 44042160086 also completed SUCCESS. First initial source assertion failure at 382ef9fb was corrected and is retained in original REPORT_READY; no new compiler or linked API failure at 5d314cb5.

Remote main has subsequently advanced non-force with independent Agent4 source commit 6278c684dd15cc1be407f3393589de0a520e0b0e; exact Agent3 tested 5d314cb5 remains ancestor. Source and real build success do NOT qualify loaded kernel or physical backing. LOADED=NOT_RUN, KERNEL_4096=NOT_RUN, PHYSICAL=NOT_RUN. PHASE_A=BLOCKED, PHASE_B_FORCED_RAW_BYPASS=DISABLED, DIRECT_COMPRESSED=DISABLED. RAW original uncompressed 4096, SWAPSPACE2 first header/UUID/table untouched; Agent1 retains integration acceptance.

---

## Agent4 BIO source report — original https://github.com/k1moradi/swapz/issues/142#issuecomment-6942210126

message: REPORT_READY
round: "025"
agent: 4
status: SOURCE_PUBLISHED_MAIN; REAL_PINNED_LINUX_BIO_KBUILD_CONFIG_ZSWAP_Y_N_KUNIT_COMPILE_PASS; LIVE_SIDEBAND_DISABLED
task_publication_sha: 7c3b087e8af3a428b2703902653140ed4c9e7a5f
initial_source_sha: 59a743c9ac62d0d1d95c964acef87cf8649bf788
latest_agent4_source_sha: 6278c684dd15cc1be407f3393589de0a520e0b0e
latest_source_url: https://github.com/k1moradi/swapz/commit/6278c684dd15cc1be407f3393589de0a520e0b0e
initial_source_url: https://github.com/k1moradi/swapz/commit/59a743c9ac62d0d1d95c964acef87cf8649bf788
publication: NON_FORCE_EXPECTED_HEAD_FAST_FORWARD_MAIN; strict sole-parent peer ancestry preserved
exact_genuine_kbuild: https://github.com/k1moradi/swapz/actions/runs/44042265384
exact_pinned_linux_source: c339f4010dea8b0d754f84ace70cd1b089878ef8
LIVE_CARRIER=DISABLED
LOADED_ORIGINAL_4096=NOT_RUN
KUNIT_RUNTIME_EXECUTION=NOT_RUN
PHYSICAL_SWAPSPACE2=NOT_RUN
PHASE_A=BLOCKED
PHASE_B_FORCED_RAW_BYPASS=DISABLED
DIRECT_COMPRESSED_HANDOFF=DISABLED

Exclusive Agent4-owned changed files across both commits:
- NEW tests/tools/stage-pinned-linux-zswap-sideband.py: exact original SHA preflight and anchored CI-only staging of **only** original include/linux/blk_types.h and block/bio.c. New guarded owned typed compressed-data descriptor reference with source-owned immutable copied payload, defensive reference counts, cleanup on uninit/reset/reissue, clone ownership, always-reject admission and merge; no production path.
- NEW tests/runtime/native/pinned-linux-zswap-sideband-test.py: original pinned BIO lifecycle/anchor checks and GCC/Clang -Wall/-Wextra/-Wconversion/-Wshadow/-Werror with ASan/UBSan native owned-reference negative tests; mismatch preimage refusal. Subsequent extension also checks real bio_split C source and KUnit case emitted.
- NEW tests/runtime/native/fixtures/round025-sideband-host.c: independent ownership/clone/split/retry stale-drop, malformed codec/digest/size, caller-ref and no-live-admission host negative cases, NOT genuine Linux MM-to-DM transfer.
- NEW .github/workflows/phase-a-zswap-sideband.yml: real complete pinned original Linux checkout and GCC compile of block/bio.o for CONFIG_ZSWAP=y/n + CONFIG_KUNIT=y using KCFLAGS=-DSWAPZ_ROUND025_SIDEBAND_CI_ONLY, nm symbol verification and no module/device insert.
- NEW docs/handoff/zswapz/round025/agent4-evidence.md: precise source limitations, owners and first failure.
- docs/testing_standards.md: uniquely titled Agent4 Round025 section and additive subsequent split extension; all prior comments and Agent2/3 additions preserved.

Exact executed test evidence:
1. https://github.com/k1moradi/swapz/actions/runs/44041682956 at initial source 59a743c9: COMPLETED SUCCESS, job 133897506909, all 5 native source tests PASS; GCC and Clang sanitized C ownership fixture PASS, exact original Linux blob/anchors PASS, and two real original pinned Linux GCC CONFIG_ZSWAP=y/n builds of `block/bio.o` with CONFIG_KUNIT=y PASS, emitted KUnit suite compiled symbol. First observed compiler error: NONE.
2. https://github.com/k1moradi/swapz/actions/runs/44042265384 at final source 6278c684: COMPLETED SUCCESS, job 133899413239. `python3 -B swapz/tests/runtime/native/pinned-linux-zswap-sideband-test.py -v` 5/5 PASS, including GCC/Clang strict sanitizers and source verification. `python3 -B swapz/tests/tools/stage-pinned-linux-zswap-sideband.py --linux-root linux` exact pinned blobs=2, git diff --check PASS. Real original Linux Kbuild using `make -s -C linux O=<profile> CC=gcc KCFLAGS=-DSWAPZ_ROUND025_SIDEBAND_CI_ONLY block/bio.o` with both CONFIG_ZSWAP=y and CONFIG_ZSWAP=n and CONFIG_KUNIT=y PASS. Logs print `PINNED_BIO_GCC_CONFIG_ZSWAP_enabled_KUNIT_COMPILE=PASS` and `PINNED_BIO_GCC_CONFIG_ZSWAP_disabled_KUNIT_COMPILE=PASS`. The newly added source KUnit case calls actual pinned `bio_split`, checks 2048/2048 split, cloned ownership and cleanup; its compile proof does NOT mean KUnit cases booted or executed.
3. Two source commits are in single-parent non-force published main ancestry with Agent2/3 commits untouched. No local GitHub CLI clone/Kbuild was run; genuine hosted Linux object compilation supplies the evidence.

First source/API blocker, still unresolved for live transfer: pinned `struct bio.bi_private` is owned by endio/chaining; `__bio_clone` copies bvec and iterator, not compressed source descriptor; `bio_reset` calls bio_uninit and clears fields before `BIO_RESET_BYTES`, while reissue/reuse has independent lifetime rules. An independently owned source store epoch, original-page digest and authenticated BIO→DM transport do not yet exist. The CI-only BIO field and reference helpers are NOT integrated into live clone/merge/DM or ordinary 4096 REQ_SWAP, and a normal upper BIO may not silently carry compressed-sized payload.

Existing zswap manages its own RAM eviction; no competing pressure loop. RAW remains original **uncompressed 4096**; a future zswap-compressed record is distinct RAM-tagged LZ4 and requires true trusted decoder. SWAPSPACE2 original first 4096 header/signature/UUID/partition table untouched, on-media record metadata forbidden. No loaded kernel, privilege, swap, RAM pressure, null_blk or physical IO was performed. Agent1 owns integration and exact-SHA closeout.

---

## Agent4 capacity-guard update — original https://github.com/k1moradi/swapz/issues/142#issuecomment-6942224145

message: SOURCE_UPDATE
round: "025"
agent: 4
previous_report: https://github.com/k1moradi/swapz/issues/142#issuecomment-6942210126
new_published_sha: 0dfcd58b2a993d04de50256ae9e49577718d3e99
sole_parent_sha: 6278c684dd15cc1be407f3393589de0a520e0b0e
publication: nonforce expected-head direct-main fast-forward; intervening Agent2/3 commits preserved
status: SOURCE_OWNED_ALLOCATION_CAPACITY_BOUND_COMMITTED; EXACT_SHA_GENUINE_KBUILD_PENDING
exact_source_workflow: https://github.com/k1moradi/swapz/actions/runs/44042667994
LIVE_CARRIER: DISABLED
LOADED_4096: NOT_RUN
PHYSICAL: NOT_RUN
PHASE_A: BLOCKED
PHASE_B_FORCED_RAW_BYPASS: DISABLED
DIRECT_COMPRESSED: DISABLED

After the previously reported full PASS at 6278c684, an independent Agent4-only follow-up was published at 0dfcd58b. It tightens the CI-only descriptor to reject claimed compressed lengths exceeding the smaller immutable owned-copy capacity even if the claimed length is within the global 1..3568 bound. Updated exclusive paths: tests/tools/stage-pinned-linux-zswap-sideband.py, tests/runtime/native/pinned-linux-zswap-sideband-test.py, tests/runtime/native/fixtures/round025-sideband-host.c, docs/handoff/zswapz/round025/agent4-evidence.md, and append-only docs/testing_standards.md. No production MM/BIO/DM call sites, no kernel pressure/mapper, and no SWAPSPACE2 changes.

Exact 0dfcd58b pinned Linux/KUnit compile workflow 44042667994 was IN_PROGRESS at observation. It is **NOT YET A COMPILER PASS**; prior source 6278c684 Kbuild PASS does not automatically certify this follow-up. First actual compiler/API failure for 0dfcd58b: NOT YET OBSERVED (running). No privileged operations. Original RAW remains uncompressed full 4096, SWAPSPACE2 first header/signature/UUID/table unchanged.

---

## Agent4 final REPORT_READY — original https://github.com/k1moradi/swapz/issues/142#issuecomment-6942225329

message: REPORT_READY
round: "025"
agent: 4
status: PUBLISHED_MAIN_SOURCE_ONLY_PINNED_BIO_BOUNDED_OWNERSHIP; FINAL_EXACT_SHA_CI_IN_PROGRESS_AT_REPORT
published_main_sha: 0dfcd58b2a993d04de50256ae9e49577718d3e99
published_main_url: https://github.com/k1moradi/swapz/commit/0dfcd58b2a993d04de50256ae9e49577718d3e99
expected_parent_sha: 6278c684dd15cc1be407f3393589de0a520e0b0e
main_postwrite_readback: VERIFIED
publication: NON_FORCE_EXPECTED_HEAD_FAST_FORWARD_DIRECT_MAIN
source_compile_verified_prior_sha: 6278c684dd15cc1be407f3393589de0a520e0b0e
source_compile_prior_workflow: https://github.com/k1moradi/swapz/actions/runs/44042265384
source_compile_initial_workflow: https://github.com/k1moradi/swapz/actions/runs/44041682956
final_exact_sha_workflow: https://github.com/k1moradi/swapz/actions/runs/44042667994
final_exact_sha_conclusion_at_report: IN_PROGRESS_NOT_CLAIMED
first_compiler_error_prior_full_SOURCE_ONLY: NONE
actual_booted_kunit: NOT_RUN
live_compressed_mm_bio_dm: DISABLED
loaded_original_4096_swapin: NOT_RUN
physical_swapspace2: NOT_RUN
phase_a: BLOCKED
phase_b_forced_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED

Agent4 committed source chain, exclusively on sole main, preserving previous Agent3 and Agent2 published head/standards and all source changes:
1. 59a743c9ac62d0d1d95c964acef87cf8649bf788 parent 382ef9fb — new pinned-BIO stager, strict original Git blob/anchor checking, CI-only typed refcount model, new GCC+Clang ASan/UBSan Python/C fixture, new real-Linux CONFIG_ZSWAP=y/n KUnit compiler workflow, distinct Agent4 testing standards and evidence note.
2. 6278c684dd15cc1be407f3393589de0a520e0b0e parent 5d314cb5 — reconcile latest main preserving Agent2/3 sections; add genuine pinned bio_split() KUnit source case verifying full 4096 upper BIO split to two 2048-byte BIOs, correctly counted ownership, split clone release, fail-closed merge and no leak.
3. 0dfcd58b2a993d04de50256ae9e49577718d3e99 parent 6278c684 — explicit <=3568 allocation-capacity guard BEFORE CRC: reject claimed compressed length 3000 on separately owned 8-byte buffer, zero/invalid owned_capacity; KUnit and GCC/Clang sanitizer negative regressions, append-only standards and evidence.

Final owned file set:
tests/tools/stage-pinned-linux-zswap-sideband.py
tests/runtime/native/pinned-linux-zswap-sideband-test.py
tests/runtime/native/fixtures/round025-sideband-host.c
.github/workflows/phase-a-zswap-sideband.yml
docs/testing_standards.md
docs/handoff/zswapz/round025/agent4-evidence.md

TRUE original source first unsupported ABI: pinned Linux c339f4010dea8b0d754f84ace70cd1b089878ef8 struct bio has bi_private reserved for end-I/O/chain, and no independently owned compressed sideband; __bio_clone copies bi_io_vec + iterator, not compressed payload; bio_reset calls bio_uninit/clears BIO_RESET_BYTES, bio_reuse preserves unrelated bi_private, bio_prepare_reissue retains BIO without source-slot epoch revalidation; clone/split/merge/DM source-identity and generation transport cannot be sourced. One ordinary 4096-byte REQ_SWAP BIO may not carry variable-size zswap LZ4 bytes. An actual refcounted CI-only typed field can compile, but the original kernel supplies no authenticated swap-slot allocation epoch/store-time digest plus DM generation/GC/ACK mapping, and clone/split of a full page has no independently authenticated subrecord representation. ALL live compressed admissions deliberately always return -EOPNOTSUPP. This precise source/API blocker remains even after compiler test PASS.

ACTUALLY EXECUTED in GitHub Actions on original published SHA 59a743... and split SHA 6278... (each dedicated workflow COMPLETED SUCCESS):
- python3 -B swapz/tests/runtime/native/pinned-linux-zswap-sideband-test.py -v with ROUND025_PINNED_LINUX pointing to full exact checked-out Linux: 5/5 PASS; real GCC+Clang -Wall/-Wextra/-Werror/-Wconversion/-Wshadow plus ASan/UBSan C host fixtures PASS. Host clone/split mocks are separate supplemental evidence.
- python3 -B swapz/tests/tools/stage-pinned-linux-zswap-sideband.py --linux-root linux -> EXIT 0 with exact original stock blobs 0cc09b975d8ffbd45ca3dc47533a71f8e8164de6 and b0fcc69de653524479e3b328aa29a37e97945b84, exact two modified upstream files.
- git -C linux diff --check -> EXIT 0.
- make -s -C linux O=<build> CC=gcc defconfig, scripts/config --enable KUNIT and CONFIG_ZSWAP=y/n, olddefconfig, prepare, then make -s -j2 -C linux O=<build> CC=gcc KCFLAGS=-DSWAPZ_ROUND025_SIDEBAND_CI_ONLY block/bio.o -> EXIT 0 for enabled and disabled profiles; nm confirms real KUnit suite in both compiled pinned BIO objects. KUnit runtime NOT_EXECUTED.
- Published GitHub Git diff inspection: 0 newly added trailing-whitespace findings. Full local checkout and git diff --check were NOT_RUN locally because this container's git ls-remote could not resolve github.com. Do NOT claim a local kernel build.
- The FINAL capacity-guard revision's identical exact-SHA hosted source/Kbuild workflow 44042667994 is IN_PROGRESS at this comment; Agent1 owns its exact SHA review. No fabricated final pass.

No additional remote branches, PRs, forks, worktrees, force-push, module load, host swap, pressure, null_blk, mapper or physical operation. Existing RAW remains the ORIGINAL UNCOMPRESSED full 4096 bytes. The SWAPSPACE2 first 4096-byte header/signature/UUID and partition table remain unchanged; no production disk metadata/payload layout modified. Zswap continues to own its configurable RAM eviction; swapz remains backing tier without competing pressure control. Agent1 owns exact SHA CI review/round closeout.

FINAL EXACT-SHA SOURCE CI UPDATE (same published commit, no additional edits):
https://github.com/k1moradi/swapz/actions/runs/44042667994 at 0dfcd58b2a993d04de50256ae9e49577718d3e99 -> COMPLETED SUCCESS.
Actual hosted commands/results: python3 -B swapz/tests/runtime/native/pinned-linux-zswap-sideband-test.py (5/5 PASS; GCC+Clang ASan/UBSan), exact upstream Linux blob staging (EXIT 0, two files), git -C linux diff --check (EXIT 0), and actual pinned GCC/KUnit block/bio.o compiling under CONFIG_ZSWAP=y AND CONFIG_ZSWAP=n (both PASS, nm suite verified). The final owned-capacity guard now has exact published-source compiler/sanitizer evidence; first compiler/runtime failure NONE. No booted KUnit execution, no live MM/BIO/DM compressed transfer, loaded original 4096 swapin, or physical device test; all remain NOT_RUN/DISABLED as above. Agent1 retains overall integration closeout.

---

## Agent4 final CI update — original https://github.com/k1moradi/swapz/issues/142#issuecomment-6942235281

message: SOURCE_UPDATE
round: "025"
agent: 4
tested_final_source_sha: 0dfcd58b2a993d04de50256ae9e49577718d3e99
status: EXACT_SHA_ROOTLESS_GCC_CLANG_ASAN_UBSAN_AND_REAL_PINNED_BIO_GCC_KBUILD_Y_N_KUNIT_COMPILE_PASS
previous_report_ready: https://github.com/k1moradi/swapz/issues/142#issuecomment-6942210126
earlier_followup: https://github.com/k1moradi/swapz/issues/142#issuecomment-6942224145
exact_source_workflow: https://github.com/k1moradi/swapz/actions/runs/44042667994

The follow-up immutable-owned-copy capacity guard has now passed its own exact committed-source GitHub Actions run 44042667994, job 133900751944, **COMPLETED SUCCESS / EXIT 0**, after the previous update reported it IN_PROGRESS:
- `python3 -B swapz/tests/runtime/native/pinned-linux-zswap-sideband-test.py -v`: 5/5 PASS, including strict GCC and Clang ASan/UBSan C negative fixture and actual pinned source anchor/immutability checks.
- Exact upstream two Git blob verification and staged `git diff --check`: PASS; log `ROUND025_SIDEBAND_STAGED_CI_ONLY exact_pinned_blobs=2`.
- Actual pinned Linux `make -s -C linux O=<separate-config> CC=gcc KCFLAGS=-DSWAPZ_ROUND025_SIDEBAND_CI_ONLY block/bio.o` with CONFIG_KUNIT=y and separately CONFIG_ZSWAP=y and CONFIG_ZSWAP=n: both PASS; `nm` symbol checks PASS; logs `PINNED_BIO_GCC_CONFIG_ZSWAP_enabled_KUNIT_COMPILE=PASS` and `PINNED_BIO_GCC_CONFIG_ZSWAP_disabled_KUNIT_COMPILE=PASS`.
First exact-source compiler/Kbuild failure at 0dfcd58b: NONE OBSERVED. KUnit cases were COMPILED, not boot-executed. Original 4096 upper BIO and RAW unchanged; source refcount helpers remain default-off, source slot epoch/DM sideband untrusted, LIVE_CARRIER=DISABLED. LOADED=NOT_RUN, PHYSICAL=NOT_RUN, PHASE_A=BLOCKED; forced RAW bypass and direct compressed handoff DISABLED.
