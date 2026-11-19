# Round040 — Agent1 preserved original workers' CI checkpoints and final REPORT_READY comments VERBATIM

Original official [issue #157](https://github.com/k1moradi/swapz/issues/157). Four ORIGINAL issue comments transcribed below with no edits, from Agent2 checkpoint, Agent2 REPORT_READY, Agent3 checkpoint and Agent3 REPORT_READY. Their earlier job statuses were provisional **as originally written**, even though Agent1's independent terminal verification later establishes full PASS. These worker bodies are NOT Agent1-authored or reclassified; later independently checked terminal result only in [full accountable closeout](round-report.md).

## 1. https://github.com/k1moradi/swapz/issues/157#issuecomment-6991421735

~~~~text
message: AGENT2_CI_STATUS_CHECKPOINT
round: "040"
worker: 2
status: PUBLISHED_GENUINE_ORIGINAL_41_OF_41_PASS_FULL_X86_Y_N_AND_EXACT_NATIVE_PENDING_NO_REPORT_READY_YET
frozen_task_sha: 262893d133e30cffda3e44c3beb1c648dcdd4aae
published_source_sha: ecf3c706a49d1a82ffdee607ca3f57d8e998f42f
published_source_parent: 262893d133e30cffda3e44c3beb1c648dcdd4aae
original_upstream_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
source_mapped_authenticated: 0
original_async_slot_lease: NO_AUTHORITY
original_store_executed: NO_SYNTHETIC_INPUTS_ONLY
phase_a: BLOCKED
direct_compressed_handoff: NO_GO_DISABLED
forced_raw_bypass: DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN

Agent2 independently published [one-parent sole-main non-force expected-head FF `ecf3c706a49d1a82ffdee607ca3f57d8e998f42f`](https://github.com/k1moradi/swapz/commit/ecf3c706a49d1a82ffdee607ca3f57d8e998f42f), exactly frozen parent `262893d133e30cffda3e44c3beb1c648dcdd4aae`, 7 files: `tests/tools/stage-pinned-linux-zswap-composed.py`, `tests/runtime/native/pinned-linux-zswap-composed-source-test.py`, NEW `tests/runtime/native/fixtures/round040-original-lease-host.c`, NEW `tests/tools/round040-original-lease-verify.py`, NEW `.github/workflows/phase-a-zswap-original-mm-async-lease-negative.yml`, NEW `docs/handoff/zswapz/round040/agent2-evidence.md`, complete full original >1MiB `docs/testing_standards.md` byte-preserved with substantive own same-C/CI-commit appendix. Agent3 independent latest `main` `c24b2361330a923db92a5993291fe29173da8b4c` is exactly ONE parent later than Agent2, only changes Agent3 own actual DM source/tests/workflow/evidence and appended its own canonical standards; Agent2 source preserved.

At genuine pristine `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`, original `mm/page_io.c` Round037 after genuine `get_swap_device(original_slot)` reference is put EXACTLY once before original asynchronous `submit_bio`. NEW original-only gated `SWAPZ_ROUND040_ORIGINAL_ASYNC_SLOT_LEASE_NEGATIVE_TEST` nested all prior 025/028/030/031/032/034/035/036/037/038+KUNIT, new original dispatch `swapz_round040_original_mm_post_put_lease_probe` acquires a SECOND genuine original `get_swap_device` ref, confirms area==ctx->sis, reads original full typed slot+current allocator epoch/current bdev/nonlinear `swap_folio_sector` and independently copied owned original BIO WHILE held, PUTS ITS OWN original area ref EXACTLY ONCE BEFORE negative asynchronous callback lease check. No refs/pointers escape, no production default changes or new export, no live source lease. Pure original-C `swapz_round040_async_lease_refuse` always `-EOPNOTSUPP` when mechanically matched, including forged positive current DM map/GC and original allocation ref flags. Five new original C **SYNTHETIC** KUnit cases cover after-put late original endio, slot/area-generation/swapoff ABA, clone/split/last-owner, canceled teardown/current DM GC unknown, bdev/nonlinear sector and full original 4096 geometry. The first unavailable lifetime mechanism is a transferable current original ALLOCATION INCARNATION reference plus current correct DM target/map/GC/teardown generation owner surviving all asynchronous clones/splits/late BIO completion; `percpu_ref_tryget_live` protects only original SWAP AREA until put.

**Actual exact-source original KUnit CI PASS:** [new workflow #44395078315](https://github.com/k1moradi/swapz/actions/runs/44395078315), original booted UML job `135122712573` **COMPLETED SUCCESS**, genuine original kernel `CONFIG_ZSWAP=y` **36 old + FIVE new = 41/41 ACTUALLY EXECUTED** KUnit original C with independent real kernel JSON+KTAP, exact original ten-file pristine SHA manifest, host GCC and Clang source-extracted Werror/-Wconversion/-Wshadow ASan+UBSan, **20/20** original host tests PASS and hostile 040/039 verifier self-tests PASS. Real exact log markers: `ROUND040_ORIGINAL_10_FILE_MANIFEST_ASYNC_LEASE_PASS`; `ROUND040_REAL_ORIGINAL_UML_RETURN=0`; `ROUND040_REAL_ORIGINAL_UML_KUNIT_PASS original_baseline=36 new_async_lease=5 total=41`; `ORIGINAL_STORE_EXECUTED=NO_SYNTHETIC_INPUTS_ONLY ORIGINAL_ASYNC_SLOT_LEASE=NO_AUTHORITY SOURCE_MAPPED_AUTHENTICATED=0 MM_PRESSURE_EVICTION=NOT_RUN PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED`.

**NOT YET COMPLETE at checkpoint:** independent exact-source original x86 `CONFIG_ZSWAP=y/n` full vmlinux/modules/Module.symvers genuine unique GPL external probe/same-original KDIR matched real `dm-swapz.ko` modpost/vermagic job `135122713220` is **IN_PROGRESS** in actual full build, not a PASS. [Exact same SHA native/policy #44395078461](https://github.com/k1moradi/swapz/actions/runs/44395078461) repository-policy job `135122715182` **COMPLETED SUCCESS**; other independent exact-SHA native jobs not yet all green. This is **NOT `REPORT_READY`**, no fabricated full kernel or native aggregation. New Round040 first failure: NONE observed at this completed UML/source-host checkpoint; historical first Round038 and Round039 RED remain RED, no retroactive relabeling.

**Safety:** zswap only bounded compressed RAM and genuine MM-pressure eviction; swapz only valid SWAPSPACE2 after-header disk extents/compression+GC; ordinary RAW unchanged UNCOMPRESSED full 4096. First ENTIRE 4096-byte SWAPSPACE2 signature/header/UUID and partition table untouched. `SOURCE_MAPPED_AUTHENTICATED=0`, `ORIGINAL_ASYNC_SLOT_LEASE=NO_AUTHORITY`, `PHASE_A=BLOCKED`, `DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED`, `FORCED_RAW_BYPASS=DISABLED`; no privileged/loaded/physical/pressure tests.
~~~~

## 2. https://github.com/k1moradi/swapz/issues/157#issuecomment-6991741104

~~~~text
message: REPORT_READY
round: "040"
worker: 2
status: SOURCE_IMPLEMENTED_PUBLISHED_ORIGINAL_41_OF_41_KUNIT_AND_NATIVE_7_OF_7_PASS_FULL_X86_Y_N_STILL_RUNNING_LIVE_NO_GO
frozen_task_sha: 262893d133e30cffda3e44c3beb1c648dcdd4aae
published_source_sha: ecf3c706a49d1a82ffdee607ca3f57d8e998f42f
published_source_parent: 262893d133e30cffda3e44c3beb1c648dcdd4aae
original_upstream_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
branch: main
published_main_method: expected-head one-parent non-force fast-forward
original_store_executed: NO_SYNTHETIC_INPUTS_ONLY
original_async_slot_lease: NO_AUTHORITY
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: NO_GO_DISABLED
forced_raw_bypass: DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN

**Agent2 published and verified** [commit `ecf3c706a49d1a82ffdee607ca3f57d8e998f42f`](https://github.com/k1moradi/swapz/commit/ecf3c706a49d1a82ffdee607ca3f57d8e998f42f) with **exactly ONE parent** frozen `262893d133e30cffda3e44c3beb1c648dcdd4aae` to sole existing remote `main` using NONFORCE expected-head FF; 1-ahead/0-behind and exact remote SHA+full standards blob verified. **Exactly seven changed paths:** `tests/tools/stage-pinned-linux-zswap-composed.py`; `tests/runtime/native/pinned-linux-zswap-composed-source-test.py`; NEW `tests/runtime/native/fixtures/round040-original-lease-host.c`; NEW `tests/tools/round040-original-lease-verify.py`; NEW `.github/workflows/phase-a-zswap-original-mm-async-lease-negative.yml`; NEW `docs/handoff/zswapz/round040/agent2-evidence.md`; full canonical `docs/testing_standards.md` (prior **1,234,952 bytes** preserved as complete SHA-authenticated prefix; substantive distinct applicable **same-source-commit** Round040 Agent2 11K-character standards appendix). Later Agent3 independently published current main `c24b2361330a923db92a5993291fe29173da8b4c`, **one descendant**, disjoint actual DM source/tests/workflow/evidence and separately appended own standards, no overwrite/branch/PR/force. Source original prior 36/36 and GPL v1 signature/layout unchanged.

**Original source-truth and first MISSING ref:** Exact pristine original `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`. Original `mm/swapfile.c::get_swap_device`/`get_swap_device_info` holds `percpu_ref_tryget_live(&si->users)` for the CURRENT SWAP AREA ONLY, after `put_swap_device` neither original allocated full typed `swp_entry_t.val` type+offset / allocator slot incarnation nor future area bdev/nonlinear `swap_folio_sector` is leased to any later clone/split/endio. The original cluster spinlock/slot epoch observation is momentary and original `__swap_writeout` unlocks folio before original `swap_bdev_submit_write`/async `submit_bio`. Prior original Round037 C probe obtains its genuine area ref and PUTS it ONCE BEFORE async submit; new default-undefined `SWAPZ_ROUND040_ORIGINAL_ASYNC_SLOT_LEASE_NEGATIVE_TEST` nested ALL 025/028/030/031/032/034/035/036/037/038 plus KUNIT, original `mm/page_io.c::swapz_round040_original_mm_post_put_lease_probe` runs AFTER the prior original put, acquires its OWN SECOND independently genuine `get_swap_device(original_slot)`, checks current `active_area == ctx->sis`, original `swp_type`, original allocator epoch, actual `active_area->bdev`, nonlinear `swap_folio_sector(folio)`, original genuine private BIO owner and exact upper BIO 4096 geometry WHILE held, and PUTS ITS OWN REAL area users ref **EXACTLY ONCE ON ALL paths** BEFORE a private pure C async negative check. Neither reference, pointer, source slot ref, copy or token escapes. A separately owned original BIO zsmalloc-copy ref survives copied byte lifecycle but **NOT** active original slot allocation incarnation/current DM map+extent gen/GC/teardown across original async completion. **FIRST MISSING API/LOCK** is an owned TRANSFERABLE current original swap ALLOCATION-INCARNATION lease plus coherent current actual DM target+map generation+GC/teardown ref across all clone/split/reissue/late BIO callbacks, not a per-area users percpu ref. Original `swapoff` kills users refs, synchronize_rcu, waits completion, destroys extents and later swapon may reuse same area/type+offset. Physical original swapfile sectors are NOT DM logical target sectors. Actual source KUnit cannot perform privileged true swapoff; source probe only observes current synchronous state and FAILS CLOSED `-EOPNOTSUPP` even on forged all-positive source/DM generation inputs. No new public original C GPL ABI/symbol/normal RAW changes; no default original hot-path work. See [own full T0..T5 source owner/ref table](https://github.com/k1moradi/swapz/blob/ecf3c706a49d1a82ffdee607ca3f57d8e998f42f/docs/handoff/zswapz/round040/agent2-evidence.md).

**Genuine ORIGINAL pinned Linux `CONFIG_ZSWAP=y` booted KUnit PASS:** [NEW true original #44395078315](https://github.com/k1moradi/swapz/actions/runs/44395078315) job `135122712573` **COMPLETED SUCCESS** exact source `ecf3c706...`. Original ten upstream Git-blob source SHA manifest staged and verified, original 039 hostile source guard regression passed, new 040 hostile independent JSON+KTAP self-tests PASS; real original-source-extracted GCC **AND** Clang `-Wall -Wextra -Wshadow -Wconversion -Werror` ASan+UBSan C executed, **20/20** original host regressions successful. Booted actual original UML `CONFIG_ZSWAP=y CONFIG_KUNIT=y` with independently checked actual original kernel JSON + KTAP **36 old + FIVE NEW = 41/41 actual original C KUnit executed PASS**; verbatim log `ROUND040_ORIGINAL_10_FILE_MANIFEST_ASYNC_LEASE_PASS`, `ROUND040_REAL_ORIGINAL_UML_RETURN=0`, `ROUND040_REAL_ORIGINAL_UML_KUNIT_PASS original_baseline=36 new_async_lease=5 total=41`, `ORIGINAL_STORE_EXECUTED=NO_SYNTHETIC_INPUTS_ONLY ORIGINAL_ASYNC_SLOT_LEASE=NO_AUTHORITY SOURCE_MAPPED_AUTHENTICATED=0 MM_PRESSURE_EVICTION=NOT_RUN PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED`. Five distinct synthetic old ref-after-put, new epoch/swapoff/area ABA, clone/split last-owner, canceled teardown/unknown target GC and original nonlinear bdev+full 4096 ordinary RAW geometry KUnit cases; these cases **DO NOT EXECUTE genuine natural original memory pressure STORE→eviction or active swapoff**.

**Exact same source native/repository-policy PASS:** [#44395078461](https://github.com/k1moradi/swapz/actions/runs/44395078461) all **7/7 completed SUCCESS**: native-rootless job `135122714589`, repository policy `135122715182`, rootless source-contract `135122715315`, production-readiness `135122715401`, primary-lifecycle audit `135122715502`, Make interface `135122715869`, exact-SHA CI aggregation `135132749608`. No policy/strict warning/KUnit verifier waiver.

**One separate source gate NOT YET QUALIFIED as of THIS report:** independent exact new SHA ORIGINAL real x86 **BOTH CONFIG_ZSWAP=y/n full `vmlinux/modules/Module.symvers`**, unique actual original GPL `swapz_ci_bio_snapshot_lz4_v1` provider, independent original external `round032-bio-probe.ko`, matched real same-original-KDIR `dm-swapz.ko` strict W=1/-Werror modpost/ELF/vermagic job `135122713220` in workflow #44395078315 is still **IN_PROGRESS** in `Actual original Linux vmlinux modules Module.symvers GPL probe and real matched DM`. **Do not count original x86 y/n/GPL/DM as PASS or failed; no completed log exists yet**. Agent2 will append separately grounded exact CI update if a real verdict becomes available. THIS REPORT IS SOURCE READY WITH FULL X86 QUALIFICATION PENDING, NOT LIVE GO. New Round040 first genuine failure observed through completed stages: **NONE**. Old Round038 wrong original symbol/CRC include and older Round039 first CI failures remain HISTORICAL RED, never erased/relabelled.

**Absolute safety:** zswap alone controls bounded compressed RAM and natural genuine MM-pressure eviction; swapz only existing valid SWAPSPACE2 afterheader 4/8/16KiB disk extent compression+GC, no competing reclaim. Ordinary RAW remains exact original UNCOMPRESSED full 4096, while eventual original already-STORED dictionary-free LZ4 would require a DISTINCT bounded volatile source-tagged copied representation and independently authenticated current source/DM ref with true durable lower WRITE→one map publish→ONE real upper ACK and later full original 4096 STORE SHA READ. Existing physical entire FIRST 4096 SWAPSPACE2 signature/header/UUID and partition table IMMUTABLE. `PHASE_A=BLOCKED`, `SOURCE_MAPPED_AUTHENTICATED=0`, `DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED`, `FORCED_RAW_BYPASS=DISABLED`, `LOADED_PRODUCTION=NOT_RUN`, `PHYSICAL_SWAPSPACE2=NOT_RUN`; no privileged original kernel module loading, mkswap/swapon/swapoff/null_blk/mapper, pressure, physical device or reboot.
~~~~

## 3. https://github.com/k1moradi/swapz/issues/157#issuecomment-6991829713

~~~~text
message: AGENT3_CI_STATUS_CHECKPOINT
round: "040"
worker: 3
status: PUBLISHED_SOURCE_AND_CORRECTIVE_FINAL_SHA_HOST_SANITIZERS_PASS_FULL_ORIGINAL_KBUILD_IN_PROGRESS_NO_REPORT_READY_YET
frozen_task_sha: 262893d133e30cffda3e44c3beb1c648dcdd4aae
initial_sha: c24b2361330a923db92a5993291fe29173da8b4c
initial_parent: ecf3c706a49d1a82ffdee607ca3f57d8e998f42f
final_sha: 0c8b5b1bd1f300e2b7bbe23653f66d13a4cd6858
final_parent: c24b2361330a923db92a5993291fe29173da8b4c
phase_a: BLOCKED
source_mapped_authenticated: 0
direct_compressed_handoff: NO_GO_DISABLED
forced_raw_bypass: DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN

**Agent3 implementation and correction published directly to existing sole main as two one-parent nonforce expected-SHA fast-forwards, with remote SHA, parents, all changed blobs and preserved Agent2 same-round files+complete >1MiB canonical standards readback.** Initial six owned paths: real `src/kernel/dm-target.c`, NEW `tests/runtime/native/fixtures/round040-dm-reissue-host.c`, NEW `tests/tools/round040-dm-reissue-verify.py`, NEW `.github/workflows/phase-a-zswap-dm-same-slot-reissue.yml`, own `docs/handoff/zswapz/round040/agent3-evidence.md`, full peer-preserving `docs/testing_standards.md`. Corrective final commit touches only new own host fixture, evidence and full peer-preserving standards with a distinct substantive same-source-commit appendix.

New test-only DEFAULT OFF `SWAPZ_ROUND040_DM_SAME_SLOT_REISSUE_CONCURRENCY_TEST` nests under previous actual original GPL/DM Round030–039 source gates. Actual inherited Round037 fake async private COPY/one HYPOTHETICAL ACK and Round039 source GC + Round038 fake async CRC/LZ4 full independently stored 4096 SHA read are mediated by two original STORED identities A/B with same full original swp type+offset but distinct allocation epoch/STORE id/original plaintext SHA/LZ4 compressed CRC. Old A callback cannot publish after B reissue or replace new mock map, no double hypothetical ACK, old READ cannot mutate 4096 mock output. Corrective final host adds explicit old epoch+STORE-ID alias rejection and a **REAL second source-extracted Round039 in-memory GC extent move after B's separate READ callback but before output**, forcing stale prior read refusal. Tests now 3 × 52 = 156 adversarial new cases plus inherited prior Round039/038.

**Actually observed completed CI:**
- INITIAL exact SHA [Round040 #44395420854](https://github.com/k1moradi/swapz/actions/runs/44395420854) **4/4 COMPLETED SUCCESS**: original-same-kernel-DM job `135123884754` successful real source GCC+Clang -Wall -Wextra -Wconversion -Wshadow -Werror ASan+UBSan; pristine original `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` exact 10 SHA compositor, genuine `CONFIG_ZSWAP=y` vmlinux/modules/Module.symvers unique GPL v1 original `swapz_ci_bio_snapshot_lz4_v1`, DEFAULT and ALL Round040 guarded actual `dm-swapz.ko` SAME-ORIGINAL-KDIR strict W=1/-Werror modpost/ELF/vermagic markers `ROUND033_GENUINE_SAME_ORIGINAL_KERNEL_MODULE_SYMVERS_GPL_MODPOST_PASS` and `ROUND040_TRUE_ORIGINAL_LINUX_DM_SAME_SLOT_REISSUE_MODULE_COMPILE_ONLY_PASS`. x86_64 `135123885167` SUCCESS, ARM64 `135123885425` SUCCESS, repository-policy `135123885478` SUCCESS. No failure on initial Round040 source SHA.
- FINAL corrected SHA [Round040 #44398276780](https://github.com/k1moradi/swapz/actions/runs/44398276780): original-same-kernel-DM `135134001986` **IN_PROGRESS**; fresh new source-extracted host **GCC AND Clang strict ASan+UBSan step SUCCESS** with 156 cases, pinned original ten-file SHA staging step **SUCCESS**; full original Linux vmlinux/modules/Module.symvers strict matched DM build **IN_PROGRESS**. New native x86_64, ARM64 and repository-policy jobs **QUEUED** at latest check. **NO FINAL WHOLE-RUN PASS CLAIM**; not yet `REPORT_READY`. Historical old Round038/039 first real red preserved, no reclassification.

Safety: ALL synthetic private memory fake lower WRITE/GC/READ, no genuine original MM pressure STORE/eviction, current source allocation-to-DM lease, physical/durable lower block, real current map, real upper bio_endio, loaded module, privileged host or physical swap. Normal RAW remains original UNCOMPRESSED 4096; original stored LZ4 remains distinct volatile source-tagged fake lower staging. Immutable first entire 4096 SWAPSPACE2 header/signature/UUID and partition table. `PHASE_A=BLOCKED`, direct compressed handoff and forced RAW bypass disabled, production/physical NOT_RUN.
~~~~

## 4. https://github.com/k1moradi/swapz/issues/157#issuecomment-7001920940

~~~~text
message: REPORT_READY
round: "040"
worker: 3
status: SOURCE_IMPLEMENTED_PUBLISHED_EXACT_SHA_ALL_4_OWN_DM_JOBS_PASS_PRODUCTION_NO_GO
frozen_task_sha: 262893d133e30cffda3e44c3beb1c648dcdd4aae
published_source_initial_sha: c24b2361330a923db92a5993291fe29173da8b4c
published_source_initial_parent: ecf3c706a49d1a82ffdee607ca3f57d8e998f42f
published_source_final_sha: 0c8b5b1bd1f300e2b7bbe23653f66d13a4cd6858
published_source_final_parent: c24b2361330a923db92a5993291fe29173da8b4c
branch: main
publication: TWO one-parent, expected-head NONFORCE fast-forwards; no branch/PR/force
source_mapped_authenticated: 0
phase_a: BLOCKED
forced_raw_bypass: DISABLED
direct_compressed_handoff: NO_GO_DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN
original_store_executed: NO_SYNTHETIC_INPUTS_ONLY

**Agent 3 Round040 REPORT_READY — verified exact final source.** Published [initial six-path source commit `c24b2361`](https://github.com/k1moradi/swapz/commit/c24b2361330a923db92a5993291fe29173da8b4c), parent Agent2's `ecf3c706a49d1a82ffdee607ca3f57d8e998f42f`, followed by [corrective final `0c8b5b1`](https://github.com/k1moradi/swapz/commit/0c8b5b1bd1f300e2b7bbe23653f66d13a4cd6858), parent `c24b2361`. Verified remote sole `main` HEAD equals final exact SHA; verified published Git tree 731 nontruncated entries and exact DM C blob `c2186fff8f8c89cd86612ed45f10f3f2708ccce7`, 562023 bytes, fixture blob `443c2a1adc5c82f3ad04827f331e021a12511759`, testing standards full canonical blob `cff8e5cc137b17b0b91755b8863e157ac69eb980`, 1,256,880 bytes. Peer's original composer/KUnit/workflow/evidence files preserved.

**All Agent3 changed files (union of two commits):**
- `src/kernel/dm-target.c` (+294 source C lines, default OFF nested Round040 guard);
- `tests/runtime/native/fixtures/round040-dm-reissue-host.c` (new hostile 156-case fixture; corrective second genuine B GC relocation after READ callback);
- `tests/tools/round040-dm-reissue-verify.py` (real C extraction + strict both-compiler sanitizer run);
- `.github/workflows/phase-a-zswap-dm-same-slot-reissue.yml` (original pinned Linux + original GPL matched DM Kbuild, native modules and policy);
- `docs/handoff/zswapz/round040/agent3-evidence.md`;
- `docs/testing_standards.md` (complete shared canonical file preserved with own substantive initial AND distinct corrective same-commit standards additions).

**Exact FINAL SHA [new guarded production DM CI run #44398276780](https://github.com/k1moradi/swapz/actions/runs/44398276780): 4/4 COMPLETED SUCCESS.** Job `135134001986` genuine source-extracted product C GCC and Clang strict `-Wall -Wextra -Wconversion -Wshadow -Werror` ASan+UBSan both executed PASS markers `ROUND040_REAL_DM_SAME_SLOT_GCC_STRICT_ASAN_UBSAN_PASS` and `ROUND040_REAL_DM_SAME_SLOT_CLANG_STRICT_ASAN_UBSAN_PASS`; also pinned original Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8` true `CONFIG_ZSWAP=y` full vmlinux/modules/Module.symvers, authentic single GPL provider, matched DEFAULT + FULL nested Round040 actual `dm-swapz.ko` SAME ORIGINAL KDIR `W=1/-Werror` strict modpost/ELF/vermagic PASS: `ROUND040_TRUE_ORIGINAL_LINUX_DM_SAME_SLOT_REISSUE_MODULE_COMPILE_ONLY_PASS`. Job `135134003021` native x86_64 actual default/prior guard module PASS; `135134002826` native ARM64 actual default/prior guard module PASS; `135134002678` repository exact source/standards PASS. Initial [#44395420854](https://github.com/k1moradi/swapz/actions/runs/44395420854) was ALSO 4/4 completed success. Corrective second publication added a genuinely completed second inherited source-extracted Round039 B GC move AFTER callback but BEFORE read output, rather than only synthetic generation increment. No FIRST NEW genuine Round040 Agent3 compiler/test failure observed; corrective was coverage hardening, not rewriting or excusing historic failures.

Further FINAL SHA [native/policy/exact aggregator #44398276877](https://github.com/k1moradi/swapz/actions/runs/44398276877) 7/7 COMPLETED SUCCESS incl job `135146455683` exact-SHA aggregator; [actual product x86/ARM #44398276433](https://github.com/k1moradi/swapz/actions/runs/44398276433) 4/4; [debug/static #44398276671](https://github.com/k1moradi/swapz/actions/runs/44398276671) 2/2; inherited exact SHA Round039 source [#44398276768](https://github.com/k1moradi/swapz/actions/runs/44398276768) 4/4. Historical genuine first failures stay RED and separately archived: Round039 incorrect `lower_error` field [#44371628566](https://github.com/k1moradi/swapz/actions/runs/44371628566), initial insufficient 8-block disjoint staging [#44372802821](https://github.com/k1moradi/swapz/actions/runs/44372802821), and original Round038 source/symbol diagnostics [#44316779722](https://github.com/k1moradi/swapz/actions/runs/44316779722) / [#44315936135](https://github.com/k1moradi/swapz/actions/runs/44315936135). No failure masked.

**Separate independent Agent2 original-kernel result (not Agent3 proof):** [#44395078315](https://github.com/k1moradi/swapz/actions/runs/44395078315) original BOOTED UML `CONFIG_ZSWAP=y` 41/41 actual original C KUnit (36 previous + 5 new synthetic), job `135122712573` success; full original x86 `CONFIG_ZSWAP=y/n` genuine GPL probe + same original DM modules job `135122713220` success, marker `ROUND040_REAL_PINNED_ORIGINAL_X86_Y_N_GPL_PROBE_AND_DM_MODULE_PASS`. `ORIGINAL_STORE_EXECUTED=NO`, `MM_PRESSURE_EVICTION=NOT_RUN`.

**Truth and safety:** two *synthetic* independent same ORIGINAL full type+offset source A/B records (different original epoch/STORE ID, original full 4096 SHA and copied STORED LZ4 CRC); 156 deterministic 4/8/16KiB hostile schedule/failure cases and inherited source-C CRC/LZ4/full 4096 SHA/afterheader zero pad, after-GC read output atomicity and callback last-ref scrub. Only test-owned RAM fake lower extents, mock current map and HYPOTHETICAL ACK, no live `swapz_map()`, lower device I/O, authoritative real map, real upper `bio_endio`, original-pressure genuine source STORE, original active area/DM target transfer authorization, module load, SWAPSPACE2 physical device or crash durability. First entire physical 4096-byte header/UUID/partition table must remain immutable. Ordinary RAW_4096 is uncompressed ORIGINAL full 4096; future STORED LZ4 needs DISTINCT authenticated lower-I/O representation, not RAW reinterpretation. zswap alone bounded RAM/natural MM eviction; swapz alone existing valid SWAPSPACE2 disk compression/GC. **Phase A BLOCKED, direct compressed/forced RAW DISABLED, source-to-DM live admission NO_GO.**
~~~~

