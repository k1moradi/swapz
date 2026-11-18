# Round035 — original REPORT_READY comments, retained verbatim

From [issue #152](https://github.com/k1moradi/swapz/issues/152). Original worker reports are archived byte-for-byte below, including their provisional CI statements. The [Agent1 closeout](round-report.md) reports the subsequently verified completion of Agent3's true same-kernel modpost and the still-running Agent2 original y/n build. Preserve historical red runs and first diagnostics rather than rewriting worker records.

## Original worker report 1 — https://github.com/k1moradi/swapz/issues/152#issuecomment-6974471379

~~~~text
REPORT_READY — ROUND035 AGENT3 — SOURCE-ONLY GUARDED PREVIOUSLY-STORED LZ4 LOWER ROUNDTRIP

Frozen task: 96bd4ebf6c6a2adee5e105a8dd3eb2fb8cacc235.
Source publication: 6f9cc20a2fd773174af42d56c1b1af4bca8a1e60
parent: 867584e7d993bebaf2aca3ec092a2683347aa8b1 (Agent2 fast-forward preserved).
Source publication changed exactly:
- src/kernel/dm-target.c
- tests/runtime/native/fixtures/round035-dm-lower-host.c
- tests/tools/round035-dm-lower-verify.py
- .github/workflows/phase-a-zswap-owned-lz4-lower-roundtrip.yml
- docs/handoff/zswapz/round035/agent3-evidence.md
- docs/testing_standards.md (complete prior plus Agent2 section preserved).

Corrective publication: da0c3719f00b3512905cbe4c046404aee8270cc1
parent: 6512cf26caaf73765803e390ec9bb9bedf1fea1c (Agent2 concurrent change preserved).
Corrective changed exactly: tests/tools/round035-dm-lower-verify.py and docs/testing_standards.md (fresh substantive same-commit host entrypoint regression requirement).
Both publications used non-force expected-head fast-forward of main; no branch, PR, fork, worktree or history change.

FRESH CI on corrective SHA da0c3719...:
- run 44275719165, job 134703189558 repository-policy PASS.
- run 44275719165, job 134703189124 original-same-kernel-dm IN PROGRESS: original Linux checkout and prerequisites PASS; both GCC+Clang Werror ASan/UBSan real guarded production-C source-extracted owned-LZ4 fake lower/4096 SHA host test PASS; pristine exact pinned original Linux ten-file composer SHA stage PASS; full CONFIG_ZSWAP=y vmlinux/Module.symvers/default+guarded DM same-KDIR GPL modpost currently IN PROGRESS, not claimed PASS.
- run 44275719171 jobs 134703189520 x86_64 and 134703190098 ARM64 compile-only PASS; exact-c jobs 134703190133 and 134703190195 IN PROGRESS.
- run 44275719159 jobs 134703190228 Make interface, 134703190239 production readiness, 134703190335 lifecycle, 134703190483 repository policy, 134703190602 source contract PASS; native rootless 134703189749 IN PROGRESS.
- run 44275719207 rootless-contract 134703189854 PASS, sparse compile 134703190056 IN PROGRESS.
- run 44275719156 adversarial evidence 134703189042 PASS.
- run 44275719316 systemd/package 134703191937 IN PROGRESS.

FIRST GENUINE NEW FAIL preserved: SOURCE SHA 6f9cc20a... run 44275178629 job 134701367525 original-same-kernel-dm FAILED at exact host composer (before compiler). First cause tests/tools/round035-dm-lower-verify.py:152 'AssertionError: host-only boundary drift: int main(void)' because two nested main definitions were not distinguished. Corrected on da0c3719... by checking exactly two and renaming only the last Round031 main; its host compile/run subsequently PASS. Earlier run 44275178629 repository-policy job 134701367959 PASS. This new failure is not being relabeled as PASS or deleted.
Historical Round034 policy FAILED remains historical; previously pending same-kernel job 134672061346 separately finished SUCCESS; neither history nor rules changed.

Safety verdict: original GPL BIO source copy and original packed swp_type/swp_offset mechanically checkable only, NOT authenticated current MM swap area device/physical mapping/allocator epoch. SOURCE_MAPPED_AUTHENTICATED=0. Phase A BLOCKED. Forced RAW bypass DISABLED. Direct compressed handoff NO_GO_DISABLED. Existing RAW remains ORIGINAL UNCOMPRESSED 4096. Original zswap exclusively owns compressed RAM and genuine pressure eviction; swapz remains SWAPSPACE2 disk tier only. Media first 4096 SWAPSPACE2 signature/UUID/partition table untouched, no new on-media metadata; NO privileged, live module, physical device or loaded-production test. CI full kernel modpost pending; do not claim release qualification.
~~~~

## Original worker report 2 — https://github.com/k1moradi/swapz/issues/152#issuecomment-6974743038

~~~~text
message: REPORT_READY
round: "035"
agent: 2
status: EXECUTED_REAL_ORIGINAL_LINUX_CONFIG_ZSWAP_Y_UML_21_OF_21_KUNIT_PASS; SOURCE_ROUTE_NO_AUTHORITY; FULL_ORIGINAL_X86_Y_N_IN_PROGRESS_NOT_CLAIMED_PASS; PHASE_A_BLOCKED
frozen_task_sha: 96bd4ebf6c6a2adee5e105a8dd3eb2fb8cacc235
source_publication_sha: 867584e7d993bebaf2aca3ec092a2683347aa8b1
source_parent_sha: 96bd4ebf6c6a2adee5e105a8dd3eb2fb8cacc235
host_fixture_correction_sha: 6512cf26caaf73765803e390ec9bb9bedf1fea1c
workflow_source_grep_correction_sha: 0a08979278c7eda8a70b8bbc7927a59561def177
exact_CI_tested_SHA: 149fbd250b21b66bed2a20e3de83aaf165ce9da8
exact_CI_tested_parent_sha: 0a08979278c7eda8a70b8bbc7927a59561def177
evidence_publication_sha: 84fff6fddb0856d7f4192d5510aeafb4380d609b
evidence_parent_sha: 149fbd250b21b66bed2a20e3de83aaf165ce9da8
branch: main
publication: each one-parent expected-head non-force fast-forward independently readback SHA/parent; serialized across Agent3 intervening source, complete canonical testing standards peer-preserved; no PR/branch/fork/worktree/force.

**Exact Agent2 original source and CI file set (initial source commit, 7 paths):**
1. `tests/tools/stage-pinned-linux-zswap-composed.py`: guarded C in true pinned original `mm/page_io.c`, `mm/zswap.c`, `block/bio.c`, `include/linux/bio.h` and original `swap_io_ctx`. The new `SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST` is undefined-by-default and subordinate to actual original Round025/028/030/031/032/034 opt-in gates plus `CONFIG_KUNIT`, so normal kernel path unchanged.
2. `tests/runtime/native/pinned-linux-zswap-composed-source-test.py`: fail-closed generated source constraints and actual extracted-original C GCC/Clang/ASan/UBSan.
3. `tests/runtime/native/fixtures/round035-original-route-host.c`: hostile fake host slot/device/epoch geometry inputs; compiler output marker only after all real extracted C assertions.
4. `tests/tools/round035-original-route-verify.py`: strict real original Linux UML JSON + actual original kernel KTAP double verification, demands exactly old 11 BIO+6 original v1+4 new MM route negative cases, no duplicates/skips/errors/failures/panics/fabrications.
5. `.github/workflows/phase-a-zswap-original-mm-route-witness.yml`: original torvalds/Linux exact commit checkout, original 10-file SHA256 source composition, source-host strict GCC+Clang/ASan/UBSan, real original zswap-enabled UML, independent original full x86 `CONFIG_ZSWAP=y/n` vmlinux/modules/Module.symvers/original GPL probe + original-release DM module.
6. `docs/handoff/zswapz/round035/agent2-evidence.md`: original first true red, fixes, exact CI evidence and all NO_AUTHORITY limitations; exact post-CI docs-only evidence SHA noted above.
7. `docs/testing_standards.md`: each individual source/workflow-changing commit contains its own substantive non-whitespace applicability-specific canonical standards update with full exact 1.1-MB-plus prior bytes and intervening Agent3 standards retained. Repository-policy check **PASS**, but previous historical Round034 policy red intentionally unchanged.

**Executed genuine original Linux 21/21 KUnit PASS (not compiled-object proxy):** [run #44276814650](https://github.com/k1moradi/swapz/actions/runs/44276814650), original UML job `134706942776` **completed success**, source SHA `149fbd250b21b66bed2a20e3de83aaf165ce9da8`, pinned pristine original upstream `c339f4010dea8b0d754f84ace70cd1b089878ef8`. KUnit `--arch=um` actually built and booted with effective `CONFIG_ZSWAP=y`, `CONFIG_SWAP=y`, `CONFIG_KUNIT=y`, `CONFIG_CRYPTO_SHA256=y` selecting hidden `CONFIG_CRYPTO_LIB_SHA256=y`, actual original LZ4 compressor/decompressor. Real original kernel JSON AND KTAP independent verifier: **17 historical original BIO/v1 tests + 4 new original mm/page_io route negative tests = 21/21 executed PASS**, 0 skipped/failed/crashed/erroneous, exact case identities. Source-host extracted actual original C ran GCC+Clang strict compiler warnings ASan+UBSan, adversarial verifier 2/2, original ten-file source SHA manifest all PASS. Actual job stdout:
```
ROUND035_REAL_ORIGINAL_UML_RETURN=0
ROUND035_ORIGINAL_MM_ROUTE_GENUINE_UML_KUNIT_PASS old_v1=17 route_negative=4 total=21
ROUTING_AUTHORITY=NO_AUTHORITY ORIGINAL_MM_PRESSURE_EVICTION=NOT_RUN PHASE_A=BLOCKED DIRECT_COMPRESSED=DISABLED PHYSICAL=NOT_RUN
```
[Authentic kernel/KTAP/JSON/config/manifest artifact #14414169681](https://github.com/k1moradi/swapz/actions/runs/44276814650/artifacts/14414169681).

**Exact-head repository policy and other completed checks PASS:** [Native rootless #44276814613](https://github.com/k1moradi/swapz/actions/runs/44276814613), repository-policy job `134706942655` completed success; rootless primary lifecycle `134706942524`, source-contract `134706942557`, production-readiness `134706942728` and Make-interface `134706942768` completed success. Native rootless build job `134706942063` was still in progress when last checked, no claim of full CI aggregate PASS. Source host actual original original-GCC/Clang sanitizer and SHA manifest verified separately in successful original UML job.

**Full original x86 y/n Kbuild/modpost separately NOT_YET_VERIFIED:** [same run #44276814650](https://github.com/k1moradi/swapz/actions/runs/44276814650), original x86 build job `134706942237` remains IN_PROGRESS at `Actual original Linux vmlinux modules Module.symvers GPL probe and real matched DM`; do not assert success without true two-profile original vmlinux/modules/Module.symvers, independent original GPL importing probe, matched same-original-kernel `dm-swapz.ko` modpost and vermagic. Earlier three independent x86 jobs were also still running when last checked. This is remaining qualification not overridden by original UML 21/21 PASS.

**Preserve first genuine failures, do not rewrite or turn green:**
- [run #44274559631](https://github.com/k1moradi/swapz/actions/runs/44274559631), job `134699253460`: first source host wrapper rejection `AssertionError: 'ROUND031_REAL_' not found in ''`; real GCC/Clang source C executables ran but were silent. First KUnit NOT_RUN.
- [run #44275368732](https://github.com/k1moradi/swapz/actions/runs/44275368732), job `134702020456`: SHA-verified original composer produced all ten authentic blobs, but custom grep demanded formatted function + `ctx` on same line; false-negative source-gate failure. Original KUnit NOT_RUN.
- [run #44275956510](https://github.com/k1moradi/swapz/actions/runs/44275956510), job `134704000482`: original upstream `kunit_kernel.ConfigError: Specified kunitconfig (round035-evidence/real-original.kunitconfig) does not exist` due relative KUnit config path; original UML NOT_RUN. Narrow absolute request/JSON path fix qualified by subsequent genuine 21/21 run.
- Historical Round034 policy [run #44267408145](https://github.com/k1moradi/swapz/actions/runs/44267408145) job `134675270984` **failed** because earlier workflow-changing SHA lacked same-commit canonical testing-standards change; no history rewrite, waiver, force push, or docs-only retroactive repair.

**NO AUTHORITY and safety:** Original source-local typed slot `swp_type/swp_offset`, genuine `swapz_round028_slot_epoch`, actual `get_swap_device` area and `swap_folio_sector` original swapfile extents, independent original BIO owner, 4096 `REQ_OP_WRITE|REQ_SWAP`, original bdev and sector are tested. Yet original `__swap_writeout` unlocks folio before dispatch, and the swap percpu ref only pins for the synchronous check. No exported ref-safe slot incarnation + current type→active DM target/sector authority lasting through consumer and GC. Thus **even on valid local shape, original route witness deliberately returns `-EOPNOTSUPP`, not accepted compressed handoff**. Neither actual MM pressure-driven zswap STORE→eviction nor physical mapper traffic executed; all KUnit stimuli synthetic and source-only. `SOURCE_MAPPED_AUTHENTICATED=0`, `ORIGINAL_MM_PRESSURE_EVICTION=NOT_RUN`, `PHASE_A=BLOCKED`, `FORCED_RAW_BYPASS=DISABLED`, `DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED`, `LOADED_PRODUCTION=NOT_RUN`, `PHYSICAL_SWAPSPACE2=NOT_RUN`. RAW is the **ORIGINAL 4096 UNCOMPRESSED bytes**, never LZ4. Linux zswap only owns bounded compressed RAM and real pressure eviction, swapz owns SWAPSPACE2 disk tier; preserve first 4096 header/UUID/signature and partition table. No privileged, loaded-production-kernel or physical device tests.
~~~~

