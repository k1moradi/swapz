# Round041 — verbatim GitHub worker reports and checkpoints

The following are the complete original worker GitHub issue-comment bodies, including historical queue-time statements and recorded failures, preserved without editing. The Agent1 round report separately verifies later exact-source CI; do not retroactively convert an earlier queued claim into a pass. Source: https://github.com/k1moradi/swapz/issues/158 . Archived 2026-11-19 UTC.

---

## Original GitHub comment 7004983057

**Original permalink:** https://github.com/k1moradi/swapz/issues/158#issuecomment-7004983057

message: AGENT3_CI_STATUS_CHECKPOINT
round: "041"
worker: 3
status: PUBLISHED_SOURCE_EXACT_SHA_NATIVE_ARM64_PASS_OTHER_NEW_HOST_ORIGINAL_KBUILD_QUEUED_NO_REPORT_READY_YET
frozen_task_sha: 2c24b369f767567e8834c3ae1a524848073ececa
published_source_sha: ca5c20b6b32614fd40db6f461692ff43d0a9b2ee
published_source_parent: e6d564e048fb421415745b57d572ee9eeca3c0df
main_only_expected_head_nonforce_fast_forward: YES
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: NO_GO_DISABLED
forced_raw_bypass: DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN

**Agent3 Round041 checkpoint; NOT REPORT_READY yet.** Six-path implementation source+CI published to sole main as exact 1-parent expected-head nonforce FF [`ca5c20b6`](https://github.com/k1moradi/swapz/commit/ca5c20b6b32614fd40db6f461692ff43d0a9b2ee), parent peer Agent2 `e6d564e0`; remote SHA/parents/all 6 files read back. After Agent2 published first, Agent3 reconciled whole 1.27MB canonical standards by preserving **the complete Agent2 latest standards bytes as the exact prefix** and appending a distinct substantial Round041 Agent3 section. No Agent2 original composer/KUnit/CI/evidence modified. Six files: real `src/kernel/dm-target.c`, new `tests/runtime/native/fixtures/round041-dm-target-host.c`, new `tests/tools/round041-dm-target-verify.py`, new `.github/workflows/phase-a-zswap-dm-target-interval-negative.yml`, new `docs/handoff/zswapz/round041/agent3-evidence.md`, complete `docs/testing_standards.md`. New default-OFF guard `SWAPZ_ROUND041_DM_TARGET_INTERVAL_MAP_NONAUTHORITY_TEST` behind all Round030–040 flags; actual source extracts product `swapz_backing_data_sector`, Round040 copied-source and Round038 dictionary-free LZ4 CRC32C/independent original 4096 STORE SHA. NEW 3x48=144 fake postheader interval/table/GC/teardown/source area+nonlinear sector adversarial permutations plus all inherited Round040 tests; C witness NEVER admits positive live source-to-DM authority even on equal synthetic fields, and only observes maps (no real I/O or real ACK). No module insertion or physical device.

**Actual CURRENT exact-SHA new CI [#44494782614](https://github.com/k1moradi/swapz/actions/runs/44494782614)** at checkpoint: native arm64 default/prior-guard compile-only job `135459074539` COMPLETED SUCCESS; original-same-kernel-DM host GCC+Clang ASan UBSan and true pristine original `CONFIG_ZSWAP=y` full vmlinux/modules/Module.symvers unique GPL provider + default/full guarded DM same-KDIR modpost job `135459074249` QUEUED; x86 module job `135459074509` QUEUED; repository policy job `135459074508` QUEUED. **No remaining queued job claimed PASS, no first new genuine failure observed YET.** Additional new exact SHA native/policy/aggregator #44494782118, product x86/ARM #44494782471 still queued/in-progress; monitor first real errors independently. Source-only mock, original genuine STORE/pressure unrun, `SOURCE_MAPPED_AUTHENTICATED=0`; release NO_GO unchanged.

---

## Original GitHub comment 7004989457

**Original permalink:** https://github.com/k1moradi/swapz/issues/158#issuecomment-7004989457

message: AGENT2_CI_STATUS_CHECKPOINT
round: "041"
worker: 2
status: SOURCE_PUBLISHED_FIRST_REAL_HOST_MARKER_FAILURE_CORRECTED_NEW_EXACT_SOURCE_CI_QUEUED_NOT_REPORT_READY
frozen_task_sha: 2c24b369f767567e8834c3ae1a524848073ececa
initial_published_sha: e6d564e048fb421415745b57d572ee9eeca3c0df
initial_parent: 2c24b369f767567e8834c3ae1a524848073ececa
corrected_published_sha: c9e73862ef95384832fad85b59eaf09646f59fd7
corrected_parent: ca5c20b6b32614fd40db6f461692ff43d0a9b2ee
original_upstream_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
expected_actual_original_c_kunit: prior41_plus5_equals46
original_store_executed: NO_SYNTHETIC_INPUTS_ONLY
original_sector_to_dm_authority: NO_AUTHORITY
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: NO_GO_DISABLED
forced_raw_bypass: DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN

Agent2 original Linux implementation [`e6d564e048fb421415745b57d572ee9eeca3c0df`](https://github.com/k1moradi/swapz/commit/e6d564e048fb421415745b57d572ee9eeca3c0df): direct sole main one-parent NONFORCE expected-head FF from exact frozen task SHA; 7 changed files: original source compositor `tests/tools/stage-pinned-linux-zswap-composed.py`, existing original host source tests `tests/runtime/native/pinned-linux-zswap-composed-source-test.py`, new `tests/runtime/native/fixtures/round041-original-sector-domain-host.c`, new `tests/tools/round041-original-sector-verify.py`, new original genuine UML/x86 y/n/GPL matched DM `.github/workflows/phase-a-zswap-original-sector-domain.yml`, own `docs/handoff/zswapz/round041/agent2-evidence.md`, complete full canonical >1.2MiB `docs/testing_standards.md` byte preserved and substantively appended SAME source+CI commit. Adds original DEFAULT-UNDEFINED `SWAPZ_ROUND041_ORIGINAL_SECTOR_TO_DM_NONAUTHORITY_TEST` nested 025..040+KUnit original `mm/page_io.c` source. New private actual original `swapz_round041_original_mm_sector_domain_probe` independently acquires genuine current original `get_swap_device(original_slot)`, checks real ORIGINAL typed full swap entry + current epoch/source area bdev + nonlinear `swap_folio_sector` + correct full 4096 source BIO, PUTS REAL area ref once on every acquired path BEFORE async submission, then private pure source-only negative `swapz_round041_sector_domain_refuse` refuses any alleged current DM target relative 8-sector interval/map+GC ref even with mock all-positive flags. Five distinct new original C KUnit manually seeded synthetic negative cases: nonlinear original swapfile sector != typed offset*8 and downstream relative, same numerical sector different source bdev/current DM target, original typed slot/area ABA/epoch, prepopulated one bvec `bi_vcnt==0` and checked u64 page/interval overflow, wrong partition/GC/teardown. Actual prior original KUnit **41/41** source baseline preserved but NEW 46/46 NOT YET EXECUTED at this checkpoint. Old v1 copied GPL layout and ordinary RAW original uncompressed full 4096 unchanged, no positive DM authority. Own T0–T5 source/locks/refs/mapping gap: https://github.com/k1moradi/swapz/blob/e6d564e048fb421415745b57d572ee9eeca3c0df/docs/handoff/zswapz/round041/agent2-evidence.md.

**FIRST genuine exact-source CI failure preserved HISTORICAL RED**, original workflow [#44494454539](https://github.com/k1moradi/swapz/actions/runs/44494454539), genuine original UML job `135457984511` COMPLETED FAILURE in host-source sanitizer step, exit=1: BOTH actual original source-extracted C GCC and Clang strictly Werror/ASan+UBSan compiled+ran successfully, output `ROUND041_REAL_ORIGINAL_SECTOR_DOMAIN_EXTRACTED_C_HOST_PASS`, but existing strict generic `compile_and_run` requires marker prefix `ROUND031_REAL_`, causing `AssertionError: 'ROUND031_REAL_' not found ...` for both. New adversarial independent source JSON+KTAP 041 and previous 040/039 host checks PASS, previous 20 original C host tests PASS. **Genuine original 46-case Linux boot/KUnit NEVER RUN IN THAT FAILED JOB**, no fake pass. The separate original full x86 y/n/unique GPL/matched DM job `135457984877` at initial SHA was still IN_PROGRESS at last check; no false completed qualification.

**Minimal strict correction PUBLISHED preserving peer:** [`c9e73862ef95384832fad85b59eaf09646f59fd7`](https://github.com/k1moradi/swapz/commit/c9e73862ef95384832fad85b59eaf09646f59fd7) exact one-parent NONFORCE FF on latest independent Agent3 `ca5c20b6b32614fd40db6f461692ff43d0a9b2ee`; ONLY 3 Agent2-owned/shared paths: original host fixture one-line marker now `ROUND031_REAL_ROUND041_ORIGINAL_SECTOR_DOMAIN_EXTRACTED_C_HOST_PASS`, own evidence preserves first RED and diagnosis, whole canonical testing standards preserved INCLUDING Agent3's substantive own Round041 section with SECOND independent substantive source/fixture-correction same-commit appendix. No source compositor C, production DM C/ABI, warnings, sanitizer, fake refs or KUnit altered/relaxed.

**Exact corrected SHA NEW runs:** [genuine original #44495255829](https://github.com/k1moradi/swapz/actions/runs/44495255829) UML job `135460689020` and original x86 y/n full true GPL+matched DM job `135460689422` last checked QUEUED, both **NOT_RUN**; [corrected native/policy #44495255808](https://github.com/k1moradi/swapz/actions/runs/44495255808) all exact-SHA jobs last checked QUEUED. DO NOT mark these PASS until actual authenticated job completion; formal `REPORT_READY` will separately describe real current outcomes. Old failure stays historical RED; source current 46 KUnit and original full y/n remain PENDING.

Safety remains `PHASE_A=BLOCKED SOURCE_MAPPED_AUTHENTICATED=0 ORIGINAL_STORE_EXECUTED=NO_SYNTHETIC_INPUTS_ONLY`, no verified current original allocation-incarnation to downstream live DM target interval/map+GC ref, `DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED FORCED_RAW_BYPASS=DISABLED`, no loaded production or physical. zswap ALONE bounded compressed RAM and NATURAL original MM eviction, swapz ONLY valid SWAPSPACE2 disk backing packed extent compression+GC, ordinary original upper RAW FULL UNCOMPRESSED 4096. Entire FIRST 4096 SWAPSPACE2 physical header/signature/UUID and partition table untouched. NO privileged module/swapoff/swapon/mkswap/null_blk/mapper/pressure/physical/reboot.

---

## Original GitHub comment 7005133696

**Original permalink:** https://github.com/k1moradi/swapz/issues/158#issuecomment-7005133696

message: REPORT_READY
round: "041"
worker: 2
status: SOURCE_PUBLISHED_GENUINE_BOOTED_ORIGINAL_46_OF_46_PASS_GCC_CLANG_ASAN_UBSAN_PASS_FULL_ORIGINAL_X86_Y_N_AND_NATIVE_QUEUED_OR_RUNNING_LIVE_NO_GO
frozen_task_sha: 2c24b369f767567e8834c3ae1a524848073ececa
initial_source_sha: e6d564e048fb421415745b57d572ee9eeca3c0df
initial_source_parent: 2c24b369f767567e8834c3ae1a524848073ececa
corrected_source_sha: c9e73862ef95384832fad85b59eaf09646f59fd7
corrected_source_parent: ca5c20b6b32614fd40db6f461692ff43d0a9b2ee
latest_verified_main_descendant: c543f24839c79897d816cb19146a9406dca1c54f
original_upstream_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
branch: main
remote_branches: [main]
original_store_executed: NO_SYNTHETIC_INPUTS_ONLY
original_sector_to_dm_authority: NO_AUTHORITY
source_mapped_authenticated: 0
phase_a: BLOCKED
direct_compressed_handoff: NO_GO_DISABLED
forced_raw_bypass: DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN

**TWO verified sole-main direct non-force expected-head, exactly one-parent FF publications, no branches/PRs/forks/worktrees/force:**
1. [Initial original-sector-domain implementation `e6d564e048fb421415745b57d572ee9eeca3c0df`](https://github.com/k1moradi/swapz/commit/e6d564e048fb421415745b57d572ee9eeca3c0df) parent **EXACT frozen** `2c24b369f767567e8834c3ae1a524848073ececa`; **7 changed paths:** `tests/tools/stage-pinned-linux-zswap-composed.py`, `tests/runtime/native/pinned-linux-zswap-composed-source-test.py`, NEW `tests/runtime/native/fixtures/round041-original-sector-domain-host.c`, NEW `tests/tools/round041-original-sector-verify.py`, NEW `.github/workflows/phase-a-zswap-original-sector-domain.yml`, NEW `docs/handoff/zswapz/round041/agent2-evidence.md`, COMPLETE whole prior >1.2MiB `docs/testing_standards.md` preserved byte for byte and substantive same-commit source/CI standards appendix.
2. [Minimal first CI failure corrective `c9e73862ef95384832fad85b59eaf09646f59fd7`](https://github.com/k1moradi/swapz/commit/c9e73862ef95384832fad85b59eaf09646f59fd7) one-parent **fresh peer `ca5c20b6b32614fd40db6f461692ff43d0a9b2ee`**, preserves ALL Agent3 product DM and his standards. **3 own/shared changed paths:** `tests/runtime/native/fixtures/round041-original-sector-domain-host.c` single output-marker change, `docs/handoff/zswapz/round041/agent2-evidence.md` original failure correction note, full canonical `docs/testing_standards.md` byte-preserves ALL prior/peer and adds SECOND substantive uniquely titled same-C-fixture-commit strict host contract section. At REPORT_READY latest `main` is `c543f24839c79897d816cb19146a9406dca1c54f`, 1-ahead/0-behind from own corrected source; latest peer changes only his own verifier/fixture/evidence plus shared standards. No original pinned Linux upstream files or original source C public v1 ABI changed by correction.

**Original actual source 3-sector/identity domains, FIRST MISSING AUTHORITY:** Original `mm/swapfile.c::get_swap_device(original_slot)` `get_swap_device_info` acquires real `percpu_ref_tryget_live(&si->users)`, a SCOPED current original swap AREA ref, not an async original allocated slot-incarnation ref. Domain A original `swp_entry_t.val` is full packed TYPE+PAGE offset, not a 512-sector LBA. Domain B original `swap_folio_sector(folio)` maps `offset_to_swap_extent(sis,swp_offset)`, `se->start_block+(offset-se->start_page)`, then shifts by `PAGE_SHIFT-9` to actual possibly NONLINEAR original SWAP AREA bdev sector; `swp_offset=37` can have original source LBA=4096 vs naïve `37*8=296`. Domain C current DM target relative `ti->begin/len` plus actual table `ti->private`, target mapped relative sector/extent generation/GC/teardown is NOT visible or ref-pinned by original MM, even when mocked relative sector number equals original absolute sector. Missing FIRST real API is a coherent REF-SAFE original current allocated slot INCARNATION+live area bdev/nonlinear-sector lease JOINED to correct CURRENT downstream DM target table instance+relative 8-sector interval+map/GC/teardown generation ref across original BIO clone/split/reissue/late endio/swapoff. An original copied LZ4 BIO owned bytes ref proves only bytes lifetime; original `put_swap_device` drops every temporary area ref BEFORE async completion, so no source→DM live mapping credential.

New DEFAULT-UNDEFINED ORIGINAL-only `SWAPZ_ROUND041_ORIGINAL_SECTOR_TO_DM_NONAUTHORITY_TEST` nested all old 025/028/030/031/032/034/035/036/037/038/040 and `CONFIG_KUNIT`; actual immutable pristine ORIGINAL `mm/page_io.c::swapz_round041_original_mm_sector_domain_probe` C is source-composed after old original 040 C. It independently acquires genuine original `get_swap_device(original_slot)`, checks real original active `swap_info_struct`, bdev, original full typed slot+current epoch, real nonlinear `swap_folio_sector`, actual exact source 4096 REQ_SWAP WRITE with one PREPOPULATED bvec `bi_vcnt==0` and original sealed BIO owner UNDER the real scoped ref, then always performs its OWN matching `put_swap_device(active_area)` **EXACTLY ONCE BEFORE** private pure `swapz_round041_sector_domain_refuse()`. No bdev/area pointer is dereferenced after the put, no transient ref escapes. Private negative C uses checked full u64 typed-offset*8 and target begin+len/page span (no sector overlap/wrap), SOURCE original identity/bdev/physical sector separately from MOCK target identity/relative sector/current fake map+GC refs, refuses with `-ESTALE/-ERANGE/-EOPNOTSUPP` even if all falsely asserted current refs and 4096 source/target numerical sectors match; **NO positive authorizer/export/DM mutation/IO/ACK** and original normal RAW stays UNCOMPRESSED FULL 4096. Five DISTINCT original private C KUnit synthetic scenarios: nonlinear original swapfile sector vs typed-page offset and DM relative sector; same numeric source/target sector different source bdev/target; original type+offset/slot epoch/area generation swapoff ABA/post-put; correct one prepopulated bvec `bi_vcnt==0` and end-exclusive target interval/u64 overflow/misalignment, wrong 2048 geometry; different original partition, stale GC, teardown and even forged all-true lease flags. All fixtures MOCK original slot/target data; NO real zswap STORE/eviction, no active swapoff, no real loaded target. See [T0..T5 original source proof and exact first missing ref](https://github.com/k1moradi/swapz/blob/c9e73862ef95384832fad85b59eaf09646f59fd7/docs/handoff/zswapz/round041/agent2-evidence.md).

**Historical FIRST GENUINE CI RED — must remain red:** [original exact source #44494454539](https://github.com/k1moradi/swapz/actions/runs/44494454539) old UML job `135457984511` COMPLETE FAILURE at source extracted sanitizer/host step, before new KUnit boot: both GCC and Clang actually compiled and EXECUTED exact source C with ASan/UBSan but host success marker `ROUND041_REAL_ORIGINAL_SECTOR_DOMAIN_EXTRACTED_C_HOST_PASS` lacked preexisting required `ROUND031_REAL_` prefix, so strict original `compile_and_run` raised `AssertionError: 'ROUND031_REAL_' not found ...` for BOTH new compiler subtests; older 20 original source tests and all 041/040/039 hostile verifiers passed; **new 46 C kernel cases NOT_RUN** in this RED job. No warnings suppressed or status spoofed. Correction changed ONLY the fixture marker to `ROUND031_REAL_ROUND041_ORIGINAL_SECTOR_DOMAIN_EXTRACTED_C_HOST_PASS`, preserved generic original host contract/actual C execution.

**EXACT CORRECTED SHA genuinely booted original Linux U(M)L+source sanitizer: PASS:** [corrected original workflow #44495255829](https://github.com/k1moradi/swapz/actions/runs/44495255829) genuine original `CONFIG_ZSWAP=y CONFIG_KUNIT=y` UML job `135460689020` **COMPLETED SUCCESS**, REAL pristine original `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` ten-source Git SHA manifest `ROUND041_ORIGINAL_10_FILE_MANIFEST_SECTOR_DOMAIN_PASS` verified, original extracted strict **GCC AND Clang `-Wall -Wextra -Wshadow -Wconversion -Werror` ASan+UBSan** executed, **22/22** original source host regressions, new independent 041 and prior hostile JSON+KTAP source verifier tests PASS. REAL booted original kernel JSON + KTAP independent original 40/38/37/36/35/34 nested verifier confirms **41 old + FIVE NEW = 46/46 genuinely executed original C KUnit PASS**, not compiled-only or synthetic kernel log: `ROUND041_REAL_ORIGINAL_UML_RETURN=0` and `ROUND041_REAL_ORIGINAL_UML_KUNIT_PASS original_baseline=41 new_sector_domain=5 total=46`. Original output `ORIGINAL_STORE_EXECUTED=NO_SYNTHETIC_INPUTS_ONLY ORIGINAL_SECTOR_TO_DM_AUTHORITY=NO_AUTHORITY SOURCE_MAPPED_AUTHENTICATED=0 MM_PRESSURE_EVICTION=NOT_RUN PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED`.

**ACTUAL SOURCE REMAINING QUALIFICATION NOT YET GREEN AT REPORT:** At exact corrected source `c9e738...`, independent true original **BOTH** x86 `CONFIG_ZSWAP=y/n` FULL `vmlinux/modules/Module.symvers`, unique real original GPL `swapz_ci_bio_snapshot_lz4_v1` provider, independent original external `round032-bio-probe.ko`, matched actual production `dm-swapz.ko` SAME pristine original KDIR W=1/-Werror modpost/ELF/vermagic job `135460689422` of workflow #44495255829 was **IN_PROGRESS** in actual full Kbuild at final checkpoint; **NOT A PASS OR A SOURCE FAILURE**. Initial first published source full original x86 job `135457984877` of older #44494454539 likewise still IN_PROGRESS; never substitute it for corrected exact SHA. Exact corrected source native repository-policy/regression [#44495255808](https://github.com/k1moradi/swapz/actions/runs/44495255808), six primary jobs and exact-SHA aggregation last checked QUEUED; **NOT GREEN until completed**. This formal message is `REPORT_READY` of PUBLISHED SOURCE and genuinely qualified original 46 KUnit/host sanitizer, **not** a full original GPL/DM or final cross-CI qualification claim. Any later completed real verdict can be documented in a separate factual addendum; first genuine new failure must trigger minimal owner source correction with another full same-C/CI-commit substantive canonical standards update, never retroactive old RED relabeling.

**ABSOLUTE SAFETY NO_GO:** Only original Linux zswap controls bounded compressed RAM and NATURAL kernel MM-pressure eviction; swapz exclusively existing VALID SWAPSPACE2 disk 4/8/16KiB afterheader packed compression/GC with NO competing RAM reclaim. Original normal upper `RAW_4096` ALWAYS ORIGINAL FULL UNCOMPRESSED 4096. Future already-STORED dictionary-free original LZ4 is DISTINCT bounded volatile immutable copied source payload and can only use existing RAW LOWER-I/O staging/zero padding after TRUE ORIGINAL allocated slot/current bdev/nonlinear source sector & live DM target mapped logical interval/GC lease; real durable lower WRITE→one atomic current map publish→EXACT ONE genuine upper ACK and later lower READ/full original STORE SHA. Physical existing FIRST ENTIRE 4096 bytes SWAPSPACE2 signature/header/UUID and partition table IMMUTABLE; no persistent new format. `SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED FORCED_RAW_BYPASS=DISABLED LOADED_PRODUCTION=NOT_RUN PHYSICAL_SWAPSPACE2=NOT_RUN`. No privileged module/swapon/swapoff/mkswap/null_blk/mapper/host or guest pressure/physical device/reboot or owner hardware tests performed.

---

## Original GitHub comment 7005267287

**Original permalink:** https://github.com/k1moradi/swapz/issues/158#issuecomment-7005267287

message: AGENT3_CI_STATUS_CHECKPOINT
round: "041"
worker: 3
status: INITIAL_GENUINE_HOST_SOURCE_COMPOSER_RED_EXPLICIT_SOURCE_CORRECTION_PUBLISHED_NEW_CI_QUEUED_NOT_REPORT_READY
frozen_task_sha: 2c24b369f767567e8834c3ae1a524848073ececa
first_source_sha: ca5c20b6b32614fd40db6f461692ff43d0a9b2ee
first_source_parent: e6d564e048fb421415745b57d572ee9eeca3c0df
first_fixture_correction_sha: c543f24839c79897d816cb19146a9406dca1c54f
first_fixture_correction_parent: c9e73862ef95384832fad85b59eaf09646f59fd7
explicit_guard_correction_sha: 860db1d21e7a555557446bc243c2ed4d148e6bd7
explicit_guard_correction_parent: c543f24839c79897d816cb19146a9406dca1c54f
phase_a: BLOCKED
source_mapped_authenticated: 0
forced_raw_bypass: DISABLED
direct_compressed_handoff: NO_GO_DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN

**First genuine hosted CI failure retained RED, no fabricated compiler stage:** [initial exact source #44494782614](https://github.com/k1moradi/swapz/actions/runs/44494782614) job `135459074249` completed FAILED at source-extraction contract before any GCC or Clang compiler execution: `AssertionError: Round041 actual DM source check missing: source_slot_epoch` in `tests/tools/round041-dm-target-verify.py:89`, output exit 1. Root cause: Round041 C called actual old `swapz_round040_dm_same_source` containing epoch/STORE identity comparison, but new Round041 own source literal contract required their *explicit* Round041 presence. Original full pristine Linux GPL Kbuild in that job **NOT_RUN**, rather than failed. Same initial SHA native ARM64 job `135459074539` **COMPLETED SUCCESS**; other initial SHA jobs queued/not counted PASS.

**Independent corrections published direct sole main** each exactly one parent, fresh HEAD `force:false expected_sha:HEAD`, no branch/PR/fork/worktree/force: first fixture corrective `c543f248...` parent peer Agent2 `c9e73862...` makes 1/2/4 bitfield assignments strict -Wconversion compliant, adds old callback ticket/ABA, now 3×50=150 explicit hostile cases; last product guarded C-only corrective `860db1d21e7a555557446bc243c2ed4d148e6bd7` parent `c543f248...` explicitly rejects zero `current_source->source_slot_epoch` and `current_source->stored_entry_identity` BEFORE previous Round040 complete source comparator. **No production/live API or positive source/DM authority.** Each correction includes unique new substantial own same-commit full canonical `docs/testing_standards.md` append and own evidence update; Agent2 original Linux/CI read-only peer work preserved. Initial Agent3 changed six paths; first correction four paths (host fixture, verifier, evidence, standards); latest correction three (DM source C, evidence, standards).

**Fresh exact corrected source CI** [Round041 original-same-kernel DM #44497383268](https://github.com/k1moradi/swapz/actions/runs/44497383268) jobs `135467941065` true source-host GCC+Clang ASan/UBSan and original full ZSWAP=y genuine GPL default/all-through-041 DM strict same-KDIR modpost; `135467941158` native ARM64, `135467941482` native x86_64, `135467941301` repository policy: **all QUEUED at this checkpoint, none counted PASS**. Exact source further native/policy/aggregate #44497383339, x86/ARM default production #44497383162, debug/static #44497383087 QUEUED. Historical first RED remains linked; pending stages are NOT_RUN/QUEUED, no new proven GCC/Clang or pinned original Kbuild success on final SHA yet. All source-only fake I/O, true original accepted STORE/pressure, real map/ACK/physical NOT_RUN, Phase A/live handoff NO_GO.

---

## Original GitHub comment 7005346783

**Original permalink:** https://github.com/k1moradi/swapz/issues/158#issuecomment-7005346783

message: REPORT_READY
round: "041"
worker: 3
status: SOURCE_IMPLEMENTED_PUBLISHED_CI_QUALIFICATION_INCOMPLETE_QUEUED_NO_PRODUCTION_GO
frozen_task_sha: 2c24b369f767567e8834c3ae1a524848073ececa
initial_source_sha: ca5c20b6b32614fd40db6f461692ff43d0a9b2ee
initial_source_parent: e6d564e048fb421415745b57d572ee9eeca3c0df
first_correction_sha: c543f24839c79897d816cb19146a9406dca1c54f
first_correction_parent: c9e73862ef95384832fad85b59eaf09646f59fd7
final_explicit_source_correction_sha: 860db1d21e7a555557446bc243c2ed4d148e6bd7
final_explicit_source_correction_parent: c543f24839c79897d816cb19146a9406dca1c54f
branch: main
source_mapped_authenticated: 0
phase_a: BLOCKED
forced_raw_bypass: DISABLED
direct_compressed_handoff: NO_GO_DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN

**Agent3 Round041 REPORT_READY (engineering source published; full CI NOT YET QUALIFIED — no green claim).** Sole main remote readback EXACT final source commit [`860db1d21e7a555557446bc243c2ed4d148e6bd7`](https://github.com/k1moradi/swapz/commit/860db1d21e7a555557446bc243c2ed4d148e6bd7), one parent `c543f24839c79897d816cb19146a9406dca1c54f`. Three one-parent latest-HEAD nonforce `force:false expected_sha:HEAD` source commits: [initial `ca5c20b6`](https://github.com/k1moradi/swapz/commit/ca5c20b6b32614fd40db6f461692ff43d0a9b2ee) on independent Agent2 first source parent `e6d564e0`; [fixture and ABA correction `c543f248`](https://github.com/k1moradi/swapz/commit/c543f24839c79897d816cb19146a9406dca1c54f), parent independent Agent2 corrective `c9e73862ef95384832fad85b59eaf09646f59fd7`; [actual C guard corrective `860db1d2`](https://github.com/k1moradi/swapz/commit/860db1d21e7a555557446bc243c2ed4d148e6bd7), parent `c543f248`. All published directly to existing ONLY `main` with exact one parent/expected-head non-force FF readback, no branches, PRs, force or peer original-source edits. Whole canonical >1.2MB `docs/testing_standards.md` retains all peer and previous bytes, uniquely appends substantially new Agent3 sections IN EACH source/CI-changing commit.

**Cumulative six owned paths:** real `src/kernel/dm-target.c` (new strictly default undefined nested through Round040 `SWAPZ_ROUND041_DM_TARGET_INTERVAL_MAP_NONAUTHORITY_TEST`), new `tests/runtime/native/fixtures/round041-dm-target-host.c`, new `tests/tools/round041-dm-target-verify.py`, new `.github/workflows/phase-a-zswap-dm-target-interval-negative.yml`, new `docs/handoff/zswapz/round041/agent3-evidence.md`, shared complete `docs/testing_standards.md`. First commit changes all six; next changes fixture/verifier/evidence/standards (four); last C/evidence/standards (three). Exact final guarded C blob `e28d995a71728f927247c2099bf3c7262c3ea093`; final full standards blob `11478086c718d5fc0b3bc829d7e9a0403ed81b5b`.

**Actual DM source audit:** product `swapz_ctr` original `ti->private` lifecycle and `ti->len`, `swapz_map` actual `bio->bi_iter.bi_sector` target 8-sector logical page (does not use original packed swp_entry type/offset as sector), and `swapz_dtr` drain/free/NULL; actual `swapz_backing_data_sector` afterheader physical lower sector/bad-page holes, read-only real `authority.maps[page]` generation/GC/extent. New C helper `swapz_round041_dm_target_interval_refuse` explicitly checks original full swp slot, allocator epoch/STORE ID, independent 4096 SHA/LZ4 compressed CRC via Round040 source comparison, scoped original bdev/nonlinear sector, target begin/len, relative 8×512-byte logical mapping, table/teardown/ticket identity, current map generation/extent owner/GC. **Even all fake values matching return `-EOPNOTSUPP`** because no authentic original slot allocation and current live DM table/target/dtr lease. New host checks 3×50=150 deterministic distinct 4/8/16KiB tests including target nonzero begin/out-of-interval/overflow, original area bdev/sector mismatch, stale map+GC, teardown pointer/epoch ABA, old callback ticket, header boundary, independent inherited Round038 full 4096 SHA dictionary-free LZ4/CRC and inherited all Round040. Fake entire initial SWAPSPACE2 4096 header sentinel unchanged, mock map/4096 output/ACK unchanged, zero real lower calls, default production path untouched.

**First GENUINE failed source CI:** historical initial [#44494782614](https://github.com/k1moradi/swapz/actions/runs/44494782614) original-same-kernel-dm job `135459074249` COMPLETED FAILURE **before compilers** on verifier source contract `AssertionError: Round041 actual DM source check missing: source_slot_epoch` at `round041-dm-target-verify.py:89`, exit1. Prior actual Round040 `swapz_round040_dm_same_source` checked original epoch/STORE ID indirectly; final corrected actual C explicitly checks current `source_slot_epoch` and `stored_entry_identity` (both nonzero) while retaining the full comparator. Original GCC/Clang sanitizers and original pinned Linux Kbuild in this FIRST failed job **NOT_RUN**. Initial exact source native ARM64 default/prior guard `135459074539` COMPLETED SUCCESS; other initial jobs not counted successful. The separate fixture corrective also makes exact `struct swapz_map::extent_blocks:3` assignment strict Wconversion-compliant with literal legal 1/2/4 and adds missing callback ticket ABA; no warnings suppressed. Original first RED preserved, not waived.

**FRESH FINAL EXACT SOURCE CI CURRENT STATUS — NOT COMPLETE:** [new DM source/host/original kernel #44497383268](https://github.com/k1moradi/swapz/actions/runs/44497383268): job `135467941065` actual source-extracted GCC+Clang strict `-Wall -Wextra -Wconversion -Wshadow -Werror` ASan+UBSan + true pinned pristine original `CONFIG_ZSWAP=y` FULL `vmlinux/modules/Module.symvers` genuine unique original GPL external provider and matched DEFAULT/full Round041 actual `dm-swapz.ko` SAME ORIGINAL KDIR W=1/-Werror strict modpost/ELF/vermagic **QUEUED**; native ARM64 `135467941158` **QUEUED**; native x86_64 `135467941482` **QUEUED**; repository policy `135467941301` **QUEUED**. Do NOT substitute old Round040 PASS, initial ARM PASS, or fake symvers; **no new final SHA source compiler/sanitizer or full original kernel PASS proven yet**. Further exact final SHA [native/policy/aggregate #44497383339](https://github.com/k1moradi/swapz/actions/runs/44497383339), [product x86/ARM #44497383162](https://github.com/k1moradi/swapz/actions/runs/44497383162), [private debug/static #44497383087](https://github.com/k1moradi/swapz/actions/runs/44497383087): QUEUED at final status check. Any future genuine failures must remain original RED and require new same-commit standards corrective; this report **is source handoff, not final CI release qualification**.

**Independent Agent2 source evidence (NOT Agent3):** [#44495255829](https://github.com/k1moradi/swapz/actions/runs/44495255829) original genuine BOOTED `CONFIG_ZSWAP=y` UML original C KUnit job `135460689020` COMPLETED SUCCESS: old 41 + 5 newly kernel-executed original sector-domain negatives = **46/46** `ROUND041_REAL_ORIGINAL_UML_KUNIT_PASS original_baseline=41 new_sector_domain=5 total=46`. Inputs synthetic: `ORIGINAL_STORE_EXECUTED=NO_SYNTHETIC_INPUTS_ONLY`, no actual MM pressure. Agent2 original full x86 y/n GPL/matched DM job `135460689422` IN_PROGRESS at check; no pass claimed.

**Production blockers:** original active current MM allocation-slot incarnation ref after original area `put_swap_device` across clone/split/late endio, valid original active swaparea bdev and nonlinear physical sector→current DM table target/relative logical interval+table/GC/extent/dtr lifetime ref, true original MM-pressure previously accepted STORE+eviction, distinct authenticated LZ4 lower-I/O representation, genuine durable lower WRITE→exactly one authoritative current map publication→exactly one REAL upper `bio_endio`, genuine disk lower READ full ORIGINAL 4096 SHA, loaded/physical SWAPSPACE2/crash safety and performance all UNPROVEN/NOT_RUN. Linux zswap only bounded compressed RAM and natural MM-pressure eviction, swapz only valid SWAPSPACE2 disk compression/GC, NO competing reclaim. Ordinary RAW_4096 original uncompressed 4096 always. Entire physical first 4096 SWAPSPACE2 header/signature/UUID and partition table IMMUTABLE, no privileged/disk/owner hardware tested. **PHASE A BLOCKED; SOURCE_MAPPED_AUTHENTICATED=0; DIRECT_COMPRESSED_HANDOFF and FORCED_RAW DISABLED; LOADED_PRODUCTION=NOT_RUN PHYSICAL_SWAPSPACE2=NOT_RUN**.
