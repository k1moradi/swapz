# Round036 — exact original worker REPORT_READY and CI addendum archive

[Official Round036 issue #153](https://github.com/k1moradi/swapz/issues/153). Each archived body below is retained **verbatim**, including its provisional statuses, historic first failed runs and reported pending jobs. The [Agent1 independently verified accountable closeout](round-report.md) supersedes only provisional status with genuinely completed exact-SHA run/job evidence. No source/error attribution or history rewritten.

## Original report 1 — https://github.com/k1moradi/swapz/issues/153#issuecomment-6975869778

~~~~text
message: REPORT_READY
round: "036"
worker: 3
status: SOURCE_PUBLISHED_HOST_SANITIZERS_POLICY_PASS_ORIGINAL_FULL_KERNEL_STILL_RUNNING
frozen_task_sha: 3ed9ea0cadd0d33ee58cd940c8d35e143f8ee5b8
source_sha: 6ae53698270a82fb62aa86e9f486435f85d8a53c
source_parent: 3b3425d6dd19f5910967078c9b80b01fd48676a1
corrective_sha: f3fcef562fda1c0bc30356d14d02b362aa786984
corrective_parent: 9d89fd371d98d6fb292c95f38641a7c1aa4d9755
branch: main
publication: one-parent expected-head force=false fast-forward and exact remote SHA readback verified for BOTH commits; concurrent Agent2 first published and all peer edits/complete standards retained
phase_a: BLOCKED
source_mapped_authenticated: 0
forced_raw_bypass: DISABLED
direct_compressed_handoff: NO_GO_DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN

**Agent 3 independently implemented actual guarded production DM C**, no Agent2 Round036 source dependency. Initial source commit [6ae5369](https://github.com/k1moradi/swapz/commit/6ae53698270a82fb62aa86e9f486435f85d8a53c) atop Agent2 main parent 3b3425d, then exact minimal corrective commit [f3fcef5](https://github.com/k1moradi/swapz/commit/f3fcef562fda1c0bc30356d14d02b362aa786984) atop next Agent2 parent 9d89fd3, both main-only, one parent, nonforce expected-head and SHA/peer-history readback. No branches/PR/forks/worktrees/force.

**Initial changed paths (6):**
- src/kernel/dm-target.c (real guarded Round036 C source, 501-line completely default-off new section);
- tests/runtime/native/fixtures/round036-dm-two-phase-host.c (actual-source adversarial 4/8/16KiB fixture);
- tests/tools/round036-dm-two-phase-verify.py (actual Round030/031/033/034/035 source composition + new real production DM C extraction; GCC/Clang strict -Wall -Wextra -Wconversion -Wshadow -Werror ASan/UBSan);
- .github/workflows/phase-a-zswap-dm-two-phase-ledger.yml (independent immutable pinned ORIGINAL Linux source SHA composer, genuine CONFIG_ZSWAP=y full original Kbuild/Module.symvers+same-KDIR default/all-guarded W=1 -Werror dm-swapz.ko actual modpost/strong exact GPL import/vermagic checks);
- docs/handoff/zswapz/round036/agent3-evidence.md;
- docs/testing_standards.md (entire full canonical >1MiB retained, Agent2 independent append retained, own substantial unique same-source-C/workflow commit section).

**Corrective changed paths (3):** new Round036 host C fixture, own evidence, full docs/testing_standards.md with additional unique substantive same-source-commit Round036 gcc/clang warning correction section. Preserved every previous and concurrent Agent2 standards byte, SHA checked before and after append. No suppression or compiler flag weakening.

**Exact first genuine failure preserved:** [initial 6ae5369 independent Round036 run #44284588089](https://github.com/k1moradi/swapz/actions/runs/44284588089) job **134733837457 FAILED** at source-extracted host GCC AND Clang strict compilation before sanitizer execution: local new reuse fixture variable 'scratch' shadowed existing embedded original Round030 fixture global 'scratch' under -Wshadow -Werror. Original full Linux kernel phase was NOT reached on that failed job. Initial same-run repository-policy job **134733837869 PASS**. Corrective f3fcef5 renamed ONLY this callback-local variable and its use to 'callback_decode_scratch'; real production C unchanged, all original comments and ABI preserved.

**Fresh corrected exact-SHA CI:** [run #44285224865](https://github.com/k1moradi/swapz/actions/runs/44285224865), repository-policy job **134736034183 COMPLETED SUCCESS**; original-same-kernel-dm job **134736034843 IN_PROGRESS**. Its GCC AND Clang strict source-extracted ASan/UBSan host execution step **COMPLETED SUCCESS**, including hosted actual production DM-C 4/8/16KiB original dictionary-free LZ4 payload stage, separate fake full completion/readback, compressed CRC32C, exact original STORE SHA 4096 decode, mock source epoch/STORE ID, DM map/owner/GC/fake callback token ABA, cancellation, read-before-completion, short/error/teardown, zero-padding/header protection, stable ledger late-callback reissue and ONCE *hypothetical* ACK. Next pristine original ten-source SHA manifest/composer step also COMPLETED SUCCESS. Job currently executing **true original pinned CONFIG_ZSWAP=y vmlinux/modules/Module.symvers and actual default+fully guarded same-original-KDIR dm-swapz.ko W=1/-Werror GPL modpost/vermagic**. This kernel/link step is NOT reported as PASS while IN_PROGRESS; pending exact job is separate from older Round035 genuine modpost successes. New Agent3 workflow does not run an additional booted original UML/KUnit; old Round035 original 21/21 are historical only, not new evidence.

**Production-C independent evidence:** [initial code SHA x86_64/ARM64 production-C #44284590435](https://github.com/k1moradi/swapz/actions/runs/44284590435) all **4/4 COMPLETED SUCCESS** (both architectures compile-only + exact-C), unaffected by fixture-only correction. Corrective-SHA fresh [#44285224834](https://github.com/k1moradi/swapz/actions/runs/44285224834) ARM64 compile-only **COMPLETED SUCCESS**; other independent jobs queued or pending at report time, not claimed PASS.

**Exact state machine and no-go:** NEW undefined-by-default nested 'SWAPZ_ROUND036_DM_TRANSACTION_PHASE_TEST' in actual src/kernel/dm-target.c uses private copied immutable original v1 full packed real swp type+offset, source epoch, stored identity, compressed CRC and full independent original 4096 STORE SHA, prior real DM map, token/generation/GC/extent+sidecar; PREPARED→FAKE_WRITE_IN_FLIGHT→fake completed READ full post-header 4/8/16KiB zero-padded extent→real production-LZ4 4096 full SHA checked→current MOCK source/DM authority recheck under ordered_owner→SIMULATED private COW metadata→exact ONE hypothetical ACK. Separate transitions never hold mutex across outstanding async simulation. Caller owns stable private slot and buffers until fake callbacks quiesce; retired old cookie refuses late callbacks; private bytes scrubbed. NO true lower dm_io, SWAPSPACE2 physical write, original production map, actual bio_endio/upper ACK, actual pinned real storage allocator, or original live swapz_map hook. Prior Round035 fake ACK-before-read path unchanged and independently tested; this new path demonstrates simulated ordering only.

**SOURCE_MAPPED_AUTHENTICATED=0**, because no actual original current swap area→correct DM mapped bdev/nonlinear sector/current allocator slot incarnation REF pinned through original MM BIO async lifetime, DM map publication and GC; a mock observer with matching packed entry/type/offset is NOT original MM authority. The fake memory copy is NOT durable lower completion and does not allow real direct compressed import. zswap alone owns small bounded compressed RAM and genuine Linux MM pressure-driven eviction; swapz solely handles existing SWAPSPACE2 disk tier compression/packing/GC without competing RAM reclaim. Ordinary RAW_4096 is original full *uncompressed* 4096; future original stored LZ4 can reuse RAW lower-IO mechanics only with separately proven real source/DM/durable fences. First ENTIRE physical 4096-byte SWAPSPACE2 header/signature/UUID and partition table IMMUTABLE. No privileged, loaded-production, physical partition, actual pressure, mkswap/swapon/swapoff/reboot tests. PHASE_A=BLOCKED, forced RAW bypass/direct compressed disabled.
~~~~

## Original report 2 — https://github.com/k1moradi/swapz/issues/153#issuecomment-6975906914

~~~~text
message: REPORT_READY
round: "036"
worker: 2
status: REAL_ORIGINAL_LINUX_ZSWAP_Y_UML_27_27_EXECUTED_PASS__SOURCE_LIFETIME_NO_AUTHORITY__FULL_X86_Y_N_IN_PROGRESS
frozen_task_sha: 3ed9ea0cadd0d33ee58cd940c8d35e143f8ee5b8
first_source_sha: 3b3425d6dd19f5910967078c9b80b01fd48676a1
first_source_parent: 3ed9ea0cadd0d33ee58cd940c8d35e143f8ee5b8
corrected_source_sha: 9d89fd371d98d6fb292c95f38641a7c1aa4d9755
corrected_source_parent: 6ae53698270a82fb62aa86e9f486435f85d8a53c
evidence_sha: f94e4a87efb87f4ca540b9e1bcba61f420b904d5
evidence_parent: f3fcef562fda1c0bc30356d14d02b362aa786984
original_upstream: torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8

**Agent2 source publication and exact paths.** The original [initial commit `3b3425d6dd19f5910967078c9b80b01fd48676a1`](https://github.com/k1moradi/swapz/commit/3b3425d6dd19f5910967078c9b80b01fd48676a1) changes exactly seven Agent2-owned paths: `tests/tools/stage-pinned-linux-zswap-composed.py` (source-generated genuine pinned original `mm/page_io.c` lifetime audit and actual MM dispatch hook), `tests/runtime/native/pinned-linux-zswap-composed-source-test.py`, NEW `tests/runtime/native/fixtures/round036-original-route-lifetime-host.c`, NEW `tests/tools/round036-original-route-lifetime-verify.py`, NEW `.github/workflows/phase-a-zswap-original-route-lifetime.yml`, own `docs/handoff/zswapz/round036/agent2-evidence.md`, and **complete >1MiB canonical `docs/testing_standards.md` with substantive applicable same-source/CI-commit append**. All previous original Linux independent stagers and Agent3 exclusive DM files unmodified. New opt-in `SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST`, undefined by default, is behind prior Round025/028/030/031/032/034/035 flags **and `CONFIG_KUNIT`**. It does not alter original live original 4096-byte uncompressed WRITE, public frozen copied v1 ABI, GPL export, or any production mapping. Corrective [source commit `9d89fd371d98d6fb292c95f38641a7c1aa4d9755`](https://github.com/k1moradi/swapz/commit/9d89fd371d98d6fb292c95f38641a7c1aa4d9755), **parent peer Agent3 `6ae53698270a82fb62aa86e9f486435f85d8a53c`**, changes only composer, host source regression, own evidence and **separately substantive same-commit full standards appendix**. Peer Agent3 code and *every prior+peer standards byte* SHA preserved. Both source publications were direct existing sole `main`, one parent, `expected_sha`, `force:false`, verified new remote SHA+parent readback; no branch/PR/fork/worktree/force. A final [docs-only evidence commit `f94e4a87efb87f4ca540b9e1bcba61f420b904d5`](https://github.com/k1moradi/swapz/commit/f94e4a87efb87f4ca540b9e1bcba61f420b904d5) with parent `f3fcef562fda1c0bc30356d14d02b362aa786984` records actual CI results without altering source/workflow or Agent3 code.

**Genuine original Linux KUnit PASS, exact source bound.** [Round036 run #44284937700](https://github.com/k1moradi/swapz/actions/runs/44284937700), original UML job **`134735050467` completed SUCCESS**, code **`9d89fd371d98d6fb292c95f38641a7c1aa4d9755`**, pinned original Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`. Clean original source 10/10 SHA256 Git-original manifest stage PASS; **source-extracted actual original `mm/page_io.c` lifetime C GCC and Clang `-Wall -Wextra -Wshadow -Wconversion -Werror` ASan+UBSan executable host test PASS**, hostile JSON+KTAP verifier self-tests PASS. Real original `kunit.py run --arch=um` actually compiled, booted and ran effective `CONFIG_ZSWAP=y`, `CONFIG_SWAP=y`, `CONFIG_KUNIT=y`, LZ4 and SHA256; original booted kernel JSON **AND KTAP** independent strict verdict: **original 21 preserved (11 BIO+6 original-v1+4 Round035 MM route) + six new Round036 original C lifetime negatives = 27/27 PASS**, zero failure/skip/error/crash and no duplicate/missing tests. Exact genuine output:
```
ROUND036_REAL_ORIGINAL_UML_RETURN=0
ROUND036_REAL_ORIGINAL_UML_KUNIT_PASS original_baseline=21 new_lifetime=6 total=27
ORIGINAL_ROUTE_LIFETIME=NO_AUTHORITY SOURCE_MAPPED_AUTHENTICATED=0 MM_PRESSURE_EVICTION=NOT_RUN PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED
```
[Original executed kernel JSON, KTAP, original source manifest and sanitizer proof artifact #14417529682](https://github.com/k1moradi/swapz/actions/runs/44284937700/artifacts/14417529682).

**Latest source repository-policy PASS.** [Native CI #44284937930](https://github.com/k1moradi/swapz/actions/runs/44284937930) repository-policy job **`134735050971` completed SUCCESS** on exact corrected source SHA. Initial source [native policy #44284080064](https://github.com/k1moradi/swapz/actions/runs/44284080064), job `134732079173` also PASS. Neither a docs-only repair nor retroactive exception: historical Round034 missing-standards [#44267408145](https://github.com/k1moradi/swapz/actions/runs/44267408145) remains genuinely **FAILED**. Other native jobs queued/running at last inspection are not counted as aggregate PASS.

**First real error accurately retained:** [Initial original kernel CI #44284080575](https://github.com/k1moradi/swapz/actions/runs/44284080575) under initial SHA `3b3425d6...`: original UML job **`134732319362` FAILED**, strict kernel C compiler first error `mm/page_io.c:977:16: error: function declaration isn’t a prototype [-Werror=strict-prototypes]` because source-only variable `struct swapz_round036_route_lifetime current = {}` expanded original kernel macro `current`→`get_current()`, followed by initializer and lvalue errors. Separate original x86 y/n job **`134732301971` FAILED** at `enabled-original-guarded-objects` on **the same real C source error**. Initial original KUnit27 NOT_RUN, full original x86 y/n NOT_QUALIFIED on that SHA. Minimal correction changes only guarded local to descriptive `consumer_sample` and adds source assertion; no warning suppression. Original failure artifacts: [UML #14418557318](https://github.com/k1moradi/swapz/actions/runs/44284080575/artifacts/14418557318), [full-x86 #14417369387](https://github.com/k1moradi/swapz/actions/runs/44284080575/artifacts/14417369387). Preserve both original failed jobs and their first error.

**Outstanding independent full original x86 Kbuild:** [Fresh corrected-source original run #44284937700](https://github.com/k1moradi/swapz/actions/runs/44284937700), x86 job **`134735049887` IN_PROGRESS** at actual original Linux `CONFIG_ZSWAP=y/n` `vmlinux`, `modules`, `Module.symvers`, independent original GPL `round032-bio-probe.ko` strict modpost and matching original-release `dm-swapz.ko` steps. No two-profile full kernel/modpost PASS is claimed until actual job completes, and prior Round035 kernel evidence is not substituted.

**Exact original MM ref/lifetime / NO_AUTHORITY:** In original `mm/zswap.c::zswap_writeback_entry`, original `get_swap_device` ref is returned after swapcache allocation before zswap xarray decompress and actual original `__swap_writeout`; that function calls `folio_start_writeback`, **`folio_unlock` BEFORE `swap_add_folio`**. At genuine original `swap_bdev_submit_write`, source-only original get/put protects original swap area for **one synchronous scope** and `swapz_round028_slot_epoch` locks only its current MM slot read; original `swap_folio_sector` uses true potentially nonlinear original rb-tree extents, not `swp_offset*8`. A stamped original BIO sideband may be separately refcounted until original `end_swap_bio_write` invokes `bio_uninit` followed by `folio_end_writeback` and frees `swap_iocb`, but that owner ref alone cannot freeze original slot allocator incarnation or later DM target/GC generation across async completion/clone/split, swapoff/swapon or map rotation. Actual original C six KUnit tests exercise synthetic same packed slot/new epoch ABA, same source type/new bdev swapoff, nonlinear sector/protected header0/overflow, target remap+GC generation, clone/split/half-page and unlock/writeback, and duplicate terminal no-lease. The original kernel provides **no ref-safe shared live current `swap_info` bdev+allocator epoch+source typed slot+exact DM target and GC generation lease** across the later DM map/ACK transaction. Even matching original source snapshots or fabricated true lease flags must **return `-EOPNOTSUPP`, never a transferable authority**. No new GPL symbol, new public v1 field, lower I/O or real ACK, no successful compressed ingress. This real UML KUnit uses synthetic inputs and does NOT execute original MM genuine memory-pressure STORE→eviction, loaded production dm-swapz, swapoff/swapon, lower durability or physical test.

**Safety:** `SOURCE_MAPPED_AUTHENTICATED=0`; `PHASE_A=BLOCKED`; `FORCED_RAW_BYPASS=DISABLED`; `DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED`; `ORIGINAL_MM_PRESSURE_EVICTION=NOT_RUN`; `LOADED_PRODUCTION=NOT_RUN`; `PHYSICAL_SWAPSPACE2=NOT_RUN`. Linux zswap alone manages bounded compressed RAM and genuine MM pressure eviction; swapz remains exclusively valid SWAPSPACE2 disk tier, 4/8/16KiB extent packing and RAM-only GC. Ordinary RAW always exactly **original uncompressed 4096 bytes**, never stored LZ4 alias. No privileged tests, production module loading, physical media write, swapoff/swapon/reboot; immutable first entire SWAPSPACE2 4096 header/signature/UUID and partition table protected.
~~~~

## Original report 3 — https://github.com/k1moradi/swapz/issues/153#issuecomment-6976373209

~~~~text
message: CI_STATUS_ADDENDUM
round: "036"
worker: 2
verified_existing_report: https://github.com/k1moradi/swapz/issues/153#issuecomment-6975906914
frozen_task_sha: 3ed9ea0cadd0d33ee58cd940c8d35e143f8ee5b8
agent2_source_sha: 9d89fd371d98d6fb292c95f38641a7c1aa4d9755
agent2_source_parent: 6ae53698270a82fb62aa86e9f486435f85d8a53c
main_readback_sha: f94e4a87efb87f4ca540b9e1bcba61f420b904d5
new_source_commit_in_this_verification: NONE
phase_a: BLOCKED

Independent re-read of existing published Agent2 evidence and live GitHub jobs: actual corrected source [original Linux workflow #44284937700](https://github.com/k1moradi/swapz/actions/runs/44284937700) job `134735050467` **SUCCESS**, original pinned booted `CONFIG_ZSWAP=y` UML independently verified **27/27** (baseline 21 plus six Round036 actual original-C KUnit), original source-extracted GCC+Clang -Werror ASan+UBSan and ten-file manifest PASS. Exact-source [repository policy #44284937930](https://github.com/k1moradi/swapz/actions/runs/44284937930) job `134735050971` **SUCCESS**. **NOT YET PASS:** full original x86 `CONFIG_ZSWAP=y/n` vmlinux/modules/Module.symvers/GPL probe/matched DM job `134735049887` remains **IN_PROGRESS**, so cannot claim real full two-profile Kbuild success. An independent native-workflow [exact-SHA aggregation job `134744076731`](https://github.com/k1moradi/swapz/actions/runs/44284937930) is **FAILED** with exact first observed diagnostic `CI_NOT_QUALIFIED tested_sha=9d89fd... phase=exact-sha-census gate=conclusion-job required=current-gate-in-progress observed=unexpected-status`; do not conflate it with the successful repository-policy job or silently waive it. Source first genuine original GCC macro collision at prior SHA `3b3425d...` remains historical RED and documented in existing Agent2 report.

Source current swap area/slot allocator epoch + nonlinear source-sector + downstream active DM mapping/GC ref lifetime is **NO_AUTHORITY** through async BIO/clone/split/swapoff, even with synchronous mechanical identity checks: `SOURCE_MAPPED_AUTHENTICATED=0`, source fails closed with `-EOPNOTSUPP`. No new changes, branches, PRs, force, privileged/loaded-production/pressure/physical-device tests in this verification. `FORCED_RAW_BYPASS=DISABLED`; `DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED`; ordinary RAW remains original uncompressed 4096 bytes; first entire SWAPSPACE2 4096 header/UUID/signature and partition table untouched.
~~~~

