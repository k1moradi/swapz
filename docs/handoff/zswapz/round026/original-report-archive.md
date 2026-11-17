# Round026 — verbatim original worker reports, source and first-failure updates

The following five comment bodies are preserved exactly as retrieved from GitHub issue #143. Historical PENDING claims are historical; final workflow conclusions and first-failure triage are independently checked in the Round026 accountable report.

## Agent2 allocator REPORT_READY

Original: https://github.com/k1moradi/swapz/issues/143#issuecomment-6943063020

message: REPORT_READY
round: "026"
agent: 2
status: SOURCE_PUBLISHED_MAIN; ORIGINAL_ALLOCATOR_EPOCH_NO_GO; HOSTED_REAL_KBUILD_RUNNING
frozen_task_sha: 3219d1b6d9eb43c27778e72836c6b7627d845650
frozen_engineering_sha: 0dfcd58b2a993d04de50256ae9e49577718d3e99
published_main_sha: d46bcdb426de75d0ad30dbc58359c6eb3b51764a
sole_parent_sha: 4a08e782a33f827e50eb7cf51b98c285b2aeebb9
publication: NON_FORCE_EXPECTED_HEAD_FAST_FORWARD_VERIFIED
commit: https://github.com/k1moradi/swapz/commit/d46bcdb426de75d0ad30dbc58359c6eb3b51764a
evidence: https://github.com/k1moradi/swapz/blob/d46bcdb426de75d0ad30dbc58359c6eb3b51764a/docs/handoff/zswapz/round026/agent2-evidence.md
source_ci: https://github.com/k1moradi/swapz/actions/runs/44048517348
job: 133920135140
GO_NO_GO: NO_GO
LIVE_COMPRESSED: DISABLED
AUTHENTIC_SLOT_ALLOCATION_EPOCH: ABSENT
SOURCE_4096_SHA: CI_ONLY_TEMPORARY_WITNESS_NOT_PERSISTED
LOADED_4096: NOT_RUN
PHYSICAL: NOT_RUN
PHASE_A: BLOCKED
FORCED_RAW_BYPASS: DISABLED
DIRECT_COMPRESSED_HANDOFF: DISABLED

### Source-authenticated finding and feasible narrow alternative
Exact original upstream `torvalds/linux` c339f4010dea8b0d754f84ace70cd1b089878ef8, `mm/swapfile.c` Git blob `254ce86fa923e6b5f1fefda88c39315c4cc00642`. Under `ci->lock`, original `__swap_cluster_alloc_entries()` uses `__swap_cache_add_folio` (or hibernation count) and `swap_range_alloc`; original `__swap_cluster_free_entries()` under same cluster lock sets original table entries to `null_to_swp_tb()` then runs `swap_range_free()` -> `zswap_invalidate()`. The same `swp_entry_t` / table bit-pattern may be reallocated. `swap_cluster_info`, `swap_info_struct`, `get_swap_device()` percpu-ref, slot reference counts, zswap entry, pool and zpool handle carry NO independently allocator-minted per-allocation generation. Same slot and xarray pointer/old zswap proof are NOT ABA-safe cross-BIO authority. `swap_info[type]` is reused after swapoff/swapon; a per-type local counter restarting at zero or a timestamp would also be unsafe. Round025 independently source-compiled temporary SHA256 over genuine original locked folio, but real STORE does not own an epoch bound to that digest.

Smallest safe future design (NOT ACTIVATED): a non-resetting nonzero original MM allocation epoch, minted under `ci->lock` at successful `__swap_cluster_alloc_entries` for every allocated slot (including large folios and hibernation), stored in a bounded authenticated source lookup until final free, retired under ci lock before NULL/reuse and propagated into original STORE SHA and separately owned versioned BIO/DM sideband. Must handle capacity/atomic allocation failures, swapoff/type reuse, source folio lock order and genuine allocator counter overflow (`U64_MAX` -> fail closed, never zero or wrap). The installed kernel has no such per-slot map, issuer, acquire/bind API or authenticated lifetime bridge; adding local helper `atomic64_inc` is NOT a real slot proof. Therefore **NO_GO**, regardless of compiler PASS.

### Published six-file Agent2 scope, peer-safe
GitHub compare parent..published commit reports **ahead=1 behind=0**:
- `tests/tools/stage-pinned-linux-zswap-origin.py` (+161/-6): only explicit `--with-round026-allocator-epoch-probe` adds original hashed `mm/swapfile.c` as seventh source; pinned source anchors and git preimage, source lifecycle (actual allocation/invalidation/free) verified. The CI-only `swapz_round026_allocator_epoch_probe` pins `get_swap_device`, locks `swap_cluster_lock`, checks `cluster_table_is_alloced` and original `__swap_table_get`, rejects NULL/bad as stale, always rejects apparently current allocation `-EOPNOTSUPP`, unlocks/releases exactly once, and **never mints epoch or calls production STORE/BIO**. Default stager remains six files and unmodified original runtime source.
- `tests/runtime/native/fixtures/round026-producer-swap-slot-epoch.c` (new 152 lines): compiles the exact source C with controlled fake table, checks current→free→same-slot reallocation with IDENTICAL table bits still NO_GO, invalid/missing table, error/NULL device, repeated calls and lock/device reference balance. This is supplemental host code and does NOT assert a real epoch.
- `tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py` (+75): GCC/Clang original extracted C compilation under `-std=gnu11 -O1 -g -Wall -Wextra -Wconversion -Wshadow -Werror -fsanitize=address,undefined -fno-sanitize-recover=all -pthread`, native negative runtime and source mutation guards (macro bypass, missing spinlock/ref release, fabricated success/epoch and unsafe table checks). Preserves all previous Round023–025 and original SHA source tests.
- `.github/workflows/phase-a-zswap-origin-prototype.yml` (+47/-4): exact original Linux pinned SHA, new source profile manifest `NO_AUTHENTIC_GENERATION_NO_GO`, allowlist 7 paths and `git diff --check`, genuine default `mm/swapfile.o` built for **both CONFIG_ZSWAP=y/n** with absent probe symbol, enabled profile explicit `make -s -C linux "O=$build_dir" CC=gcc "-j$KBUILD_JOBS" W=1 KCFLAGS="-DSWAPZ_ROUND026_SLOT_EPOCH_PROBE=1 -Werror" mm/swapfile.o`, `nm`/ `objdump` real emitted machine code, restore default `KCFLAGS=-Werror` and verify absent; original Round024/25 `mm/zswap.o`, full pinned Linux `vmlinux/modules/Module.symvers`, and matched external `dm-swapz.ko` Kbuild unchanged. No host module loaded.
- `docs/handoff/zswapz/round026/agent2-evidence.md` (new, 28 lines): exact allocator/free/source identity, first blockers, memory/epoch future cost, test/qualification truth and NO_GO.
- `docs/testing_standards.md` (+86 only), distinct Round026 Agent2 appendix preserving ALL prior and concurrent Agent3/Agent4 additions. No Agent3 DM or Agent4 sideband files touched.

### Test commands/exit codes and first failure
1. `git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main` **exit 128**, first local infrastructure failure `Could not resolve host: github.com`. No mounted local project/full pinned Linux checkout, so local exact-source `git diff --check`, `make`, KUnit, native Python test **NOT_RUN**. Remote GitHub Git Data API used exclusively; `create_tree/create_commit/update_ref(branch=main, force=false, expected_sha=4a08e782a33f827e50eb7cf51b98c285b2aeebb9)` **success** and exact remote readback verified `d46bcdb426de75d0ad30dbc58359c6eb3b51764a`.
2. Connector exact original source fetch/read, optional source blob identity/guard token and host test/CI command static inspections: **PASS static original-source review**. The actual source text has lock/ref release once, default disabled macro, no `return 0`, no fabricated `source_slot_allocation_epoch`, no normal BIO submit, no page SHA hot-path alteration. Source inspection is not an executed compiler result.
3. Exact committed `python3 -B tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py` plus `python3 -B tests/runtime/native/pinned-linux-zswap-origin-stage-test.py`, GCC/Clang original C host fixtures, real pinned Linux `CONFIG_ZSWAP=y/n` Kbuild/matched module: **NOT_RUN LOCALLY**. [Exact-SHA pinned workflow #44048517348](https://github.com/k1moradi/swapz/actions/runs/44048517348) triggered immediately on commit and was **IN_PROGRESS** (GitHub job #133920135140 checking out full original Linux) at this report. Tests must be judged from its final exact-SHA steps and logs; **NO PASS is claimed before genuine GCC/Clang or kernel build actually completes**. KUnit executed proof belongs solely to Agent4 and is not a claimed Agent2 result.
4. **First engineering GO blocker independent of CI:** original allocator does not issue/store lifetime-safe per-allocation epochs under real ci lock. False positive with same slot/table bits after reuse is demonstrated by source and negative host fixture; until issuer+lookup+retirement and matching original STORE SHA/owned BIO/DM lifetime exist, direct compressed transfer is not acceptable. Any compiler error in the hosted run is a separate true first compilation failure.

**Owner safety:** zswap alone controls compressed cache eviction; no second swapz pressure scheduler. Current RAW is ORIGINAL UNCOMPRESSED 4096-byte page; future LZ4 bytes must be separately volatile tagged and safely decoded to original 4096 plus independent original SHA. SWAPSPACE2 existing first 4096 header/signature/UUID/partition table and all physical data untouched. No module, swap, pressure, null_blk, virtual/physical disk action; Phase A BLOCKED, forced RAW bypass DISABLED, direct compressed handoff DISABLED.

MAIN_WRITE_LEASE_RELEASED

---

## Agent3 DM REPORT_READY

Original: https://github.com/k1moradi/swapz/issues/143#issuecomment-6943071735

message: REPORT_READY
round: "026"
agent: 3
status: SOURCE_PUBLISHED_MAIN; EXACT_SHA_EXTERNAL_MODULE_X86_64_ARM64_ALL_4_PRODUCTION_C_JOBS_PASS; SOURCE_OWNED_READ_SNAPSHOT_FAIL_CLOSED_NO_GO
task_publication_sha: 3219d1b6d9eb43c27778e72836c6b7627d845650
engineering_baseline_sha: 0dfcd58b2a993d04de50256ae9e49577718d3e99
first_source_commit_sha: 2399d4184bfc51f760273a844d265d42e1873232
gate_test_correction_sha: 7a6f42a87637d37cc0646b576963d48148cf847f
final_agent3_compiled_source_sha: 2da978e708bf1261485b36a0b32d2b6a85f013f2
sole_parent_sha: 7a6f42a87637d37cc0646b576963d48148cf847f
publication: NON_FORCE_EXPECTED_HEAD_FAST_FORWARD_DIRECT_MAIN_AND_REMOTE_SHA_READBACK_VERIFIED
remote_main_containing_agent3_source_at_report: d46bcdb426de75d0ad30dbc58359c6eb3b51764a
agent3_commit: https://github.com/k1moradi/swapz/commit/2da978e708bf1261485b36a0b32d2b6a85f013f2
agent3_evidence: https://github.com/k1moradi/swapz/blob/2da978e708bf1261485b36a0b32d2b6a85f013f2/docs/handoff/zswapz/round026/agent3-evidence.md
exact_sha_genuine_module_and_host_workflow: https://github.com/k1moradi/swapz/actions/runs/44048202878
exact_sha_original_cross_abi_workflow: https://github.com/k1moradi/swapz/actions/runs/44048202908

Exclusive owned modified paths across 3 direct-main commits:
- src/kernel/dm-target.c: new no-call source-real actual `ctx->authority.maps[logical]` + `ctx->maps` identity, ordered_owner lockdep, segment/4/8/16KiB extent geometry/payload offset/length/CRC, `swapz_extent_sequence_lookup`, actual GC destination/victim/recovery read-only witness and stable revalidation; identical current DM generation is not enough if physical extent changes through GC. Always refuses untrusted compressed source; no active upper BIO endio or RAM mapping publication.
- tests/runtime/native/zswap-compressed-admission-test.py: exact C function extraction, two distinct GCC/Clang -std=gnu11 -O1 -g -Wall -Wextra -Wconversion -Wshadow -Werror -fsanitize=address,undefined -fno-sanitize-recover=all executions and negative mutations; preserve original source probes; regression against kernel macro collision.
- tests/runtime/native/fixtures/round026-consumer-dm-snapshot.c: exact-source adversarial overwritten generation, GC relocation with unchanged generation, stale physical sequence, modified payload CRC/offset/length, invalid upper 4096 READ/partial transfer/duplicate ACK/teardown/cancel; canary remains unchanged, even synthetic matching source fails closed.
- .github/workflows/product-codec.yml: x86_64 and ARM64 real W=1/W=2/normal external dm-swapz.ko Kbuild plus a separately compiled optional source-C probe: require both `nm -a` symbols `swapz_round026_dm_capture_read_snapshot` and `swapz_round026_dm_revalidate_and_refuse` in actual `dm-target.o`; original RT/RAW untouched.
- docs/testing_standards.md: uniquely headed append-only Agent3 Round026 tests, true first errors and correction; all peer additions preserved.
- docs/handoff/zswapz/round026/agent3-evidence.md: exact source ownership, failure, NO_GO and qualification levels.

Exact real compiler/test results at final agent3 SHA 2da978e708bf1261485b36a0b32d2b6a85f013f2:
- `Experimental swapz production C qualification` GitHub workflow run 44048202878 COMPLETED SUCCESS, all FOUR jobs:
  x86_64 exact-c 133919064241 PASS;
  ARM64 exact-c 133919063830 PASS;
  x86_64 real external module Kbuild 133919064317 PASS;
  ARM64 real external module Kbuild 133919064823 PASS.
- Both exact-c jobs genuinely ran `python3 -B tests/runtime/native/zswap-compressed-admission-test.py -v`: `test_round026_real_dm_snapshot_fence_gcc_clang_no_go ... ok` / 5 total admission tests OK on both runners. The added source test compiles and executes actual extracted dm-target.c code with GCC and Clang ASan/UBSan; source fixture is synthetic state, NOT a loaded kernel.
- Both real module jobs ran `make -s -C src/kernel KDIR=<selected verified runner headers> -j2 all W=1`, separate `SWAPZ_STAGE=... KCFLAGS=-DSWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE=1 W=1`, W=2 and normal real `dm-swapz.ko` modules; `nm -a .../dm-target.o | grep -q` both Round026 source-real symbols. Logs printed `ROUND026_DM_READ_SNAPSHOT_ACTUAL_MODULE_KBUILD_COMPILED_NO_LIVE` and `COMPILE_ONLY_NO_MODULE_INSERTION`. no privileged module load.
- Independent Round023 cross-ABI run 44048202908 COMPLETED SUCCESS. At report time other generic workflows may be in progress; not claimed as all-branch PASS.

FIRST ACTUAL FAILURE, NOT HIDDEN: At published 7a6f42a87637d37cc0646b576963d48148cf847f, source `current` local collided with actual kernel `#define current get_current()`; both x86_64 job 133918241398 and ARM64 job 133918241679 failed at dm-target.c:1331 under `-Werror=strict-prototypes`, workflow 44047953033 (round024_ingress Kbuild). Source-extracted host compiler did NOT model that macro. Follow-up 2da978 renamed local `current_snapshot`, added source guard against reintroduction, and real x86_64/ARM64 Kbuild + host tests passed. There was a prior test-only source-count update at 7a6f42a. Warnings were not suppressed.

AUTHORITY / GO-NO-GO: **NO_GO for any actual compressed MM/zswap→DM transfer**. This guard is only a read-only source-authentic local snapshot: no separately allocator-minted Linux swap-slot epoch, store-time SHA owner, refcounted authenticated compressed BIO carrier or source-to-DM bridge is available to Agent3. DM map generation and actual extent sequence are not Linux source slot generation, and the claimed GC epoch is not authority. Existing ordered lower durable foreground WRITE→RAM map publication→one upper ACK and normal decoder/READ remain untouched. An ordinary upper REQ_SWAP BIO always represents original 4096 bytes; RAW means ORIGINAL UNCOMPRESSED 4096. No new on-media identity/format, pressure scheduler or live compressed publish. Phase A BLOCKED; forced RAW bypass DISABLED; direct compressed handoff DISABLED. KUNIT_EXECUTED=NOT_APPLICABLE_TO_AGENT3, LOADED_MATCHED_DM=NOT_RUN, LOADED_ORIGINAL_4096_SWAPIN=NOT_RUN, PHYSICAL_SWAPSPACE2=NOT_RUN. Preserve original SWAPSPACE2 protected first 4096 signature/header/UUID and partition table. Agent1 remains owner of joint epoch/BIO/DM integration exact-SHA acceptance and round closeout.

---

## Agent2 exact-source CI update

Original: https://github.com/k1moradi/swapz/issues/143#issuecomment-6943085186

message: SOURCE_UPDATE
round: "026"
agent: 2
published_sha: d46bcdb426de75d0ad30dbc58359c6eb3b51764a
status: EXACT_HOSTED_GCC_CLANG_NEGATIVE_AND_PINNED_SOURCE_STAGE_PASS; REAL_KERNEL_MODULE_KBUILD_IN_PROGRESS; AUTHENTIC_ALLOCATOR_EPOCH_NO_GO
pinned_source_ci: https://github.com/k1moradi/swapz/actions/runs/44048517348
job: 133920135140
GO_NO_GO: NO_GO
LIVE_COMPRESSED: DISABLED
LOADED_4096: NOT_RUN
PHYSICAL: NOT_RUN
PHASE_A: BLOCKED

This supplements REPORT_READY #6943063020 with first exact-SHA GitHub Actions result: `Run source-controlled rootless staging regression` **COMPLETED SUCCESS**; `Run disabled compressed handoff source/ownership negative regression` **COMPLETED SUCCESS** (new exact pinned `mm/swapfile.c` allocator observer source injected into GCC/Clang strict ASan/UBSan host fixture and same-slot ABA refusal, not fabricated live generation); `Modify actual pinned Linux C and H in disposable full checkout` **COMPLETED SUCCESS** (original pinned source commit/blob, optional seven-path allowlist, manifest NO_AUTHENTIC_GENERATION_NO_GO, git diff --check). The step `Build modified Linux and matched source-linked swapz module for both configurations` is **IN_PROGRESS** at this check, so actual GCC `mm/swapfile.o` opt-in/restore `nm`/`objdump`, complete y/n `vmlinux/modules` and matched `dm-swapz.ko` are **NOT YET QUALIFIED**. Agent1 owns final exact-SHA CI acceptance and GO/NO_GO integration. Original source still lacks real allocator-issued per-slot generation; even future kernel compile PASS cannot authorize compressed transport. No loaded, privilege, swap, device or physical test performed.

---

## Original executed KUnit independent-verifier first-failure diagnosis

Original: https://github.com/k1moradi/swapz/issues/143#issuecomment-6943119652

message: SOURCE_FINDING
round: "026"
scope: Agent4 EXECUTED BIO KUnit first verifier failure (read-only diagnosis; no Agent4 files changed)
observed_source_sha: 4a08e782a33f827e50eb7cf51b98c285b2aeebb9
observed_workflow: https://github.com/k1moradi/swapz/actions/runs/44048321459
observed_job: 133919464901
first_workflow_failure: `ROUND026_UML_KUNIT_BLOCKED first_cause=missing_or_duplicate_kernel_case:swapz_ci_reuse_private_kunit` after real `kunit.py` EXIT=0, actual UML kernel boot, runner summary `swapz_round025_sideband_compiler_only (7 subtests)`, all seven `[PASSED]`, `Testing complete. Ran 7 tests: passed: 7`. Therefore UML KUnit **DID EXECUTE** but the dual-evidence validator refused; CI verdict is FAILURE pending correction, not synthetic PASS.

Precise pinned original kernel source/API cause:
`torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8/lib/kunit/test.c` lines 175-209 `kunit_print_ok_not_ok()` emits case KTAP via `kunit_log(..., "%*s%s %zd %s%s%s", ..., status, test_number, description, ...)`. For a passing real case it prints **`ok 6 swapz_ci_reuse_private_kunit` WITHOUT dash**. The current Agent4 strict oracle `tests/runtime/native/fixtures/round026-sideband-kunit-verdict.py` defines `KTAP_CASE = re.compile(r"^ok\s+[0-9]+\s+-\s+...")`, which incorrectly requires the optional `- ` delimiter. That yields zero recognized case lines; the first reported name varies because `CASES` is a frozenset. The genuine pinned `tools/testing/kunit/kunit_parser.py` explicitly uses `TEST_RESULT` regex with **optional** `(:?- )?` delimiter.

Suggested minimal safe Agent4-owned fix: accept only exact original kernel KTAP variants `ok N case` or `ok N - case`, retain exactly-once 7-case and JSON tree/status/count checks; add adversarial source-test cases for no-dash original pinned log, duplicates, SKIP, panic, absent case; re-run hosted exact-SHA real UML boot and require the independently verified JSON+raw KTAP case names. Do not loosen other source checks, claim original first fail was kernel panic, or treat prior runner exit 0 alone as qualification.

No source files modified in this diagnostic; Agent4 owns the verifier/workflow/evidence correction and its REPORT_READY. Phase A BLOCKED; direct compressed DISABLED; forced RAW bypass DISABLED; no host module/swap/pressure/device; RAW original UNCOMPRESSED 4096, SWAPSPACE2 protected header/UUID/partition table unchanged.

---

## Agent4 KUnit REPORT_READY and final successful exact-SHA update

Original: https://github.com/k1moradi/swapz/issues/143#issuecomment-6943231006

message: REPORT_READY
round: "026"
agent: 4
status: SOURCE_ONLY_PINNED_UML_EXECUTED_7_OF_7_UPSTREAM_KUNIT_PASS; INDEPENDENT_FINAL_VERIFIER_CI_IN_PROGRESS_AT_INITIAL_REPORT
published_main_sha: ce68d2ada7a9e5eb41d64fd30a20ab1ef036a11c
published_commit: https://github.com/k1moradi/swapz/commit/ce68d2ada7a9e5eb41d64fd30a20ab1ef036a11c
published_parent: d46bcdb426de75d0ad30dbc58359c6eb3b51764a
remote_main_postwrite_readback: VERIFIED_EXACT_SHA
publication_mode: NON_FORCE_EXPECTED_HEAD_SINGLE_PARENT_FAST_FORWARD_DIRECT_MAIN
initial_source_commit: 4a08e782a33f827e50eb7cf51b98c285b2aeebb9
initial_executed_workflow: https://github.com/k1moradi/swapz/actions/runs/44048321459
corrected_exact_sha_workflow: https://github.com/k1moradi/swapz/actions/runs/44049297152
corrected_exact_sha_conclusion_at_initial_report: IN_PROGRESS_NOT_CLAIMED
earlier_gcc_zswap_y_n_compile: PASS
actual_pinned_uml_linux_boot_and_upstream_7_case_kunit: EXECUTED_7_OF_7_PASS_INITIAL_SOURCE_SHA
independent_verifier_at_INITIAL_SHA: FAIL_CLOSED_KTAP_OPTIONAL_DASH_GRAMMAR
actual_loaded_host_kunit: NOT_RUN
loaded_original_4096_swapin: NOT_RUN
physical_swapspace2: NOT_RUN
live_compressed_mm_bio_dm: DISABLED
overall_mm_bio_dm_architecture_gate: NO_GO
phase_a: BLOCKED
forced_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED

Round026 Agent4 source-only owned changes across 2 non-force expected-head FF commits, preserving every Agent2/Agent3 intervening publication and each peer's append-only docs/testing_standards.md additions:
tests/tools/stage-pinned-linux-zswap-sideband.py
tests/runtime/native/pinned-linux-zswap-sideband-test.py
tests/runtime/native/fixtures/round026-sideband-kunit-verdict.py [new]
.github/workflows/phase-a-zswap-sideband.yml
docs/testing_standards.md [unique append-only Round026 Agent4 heading plus first-failure followup]
docs/handoff/zswapz/round026/agent4-evidence.md [new and append-only first error]

ACTUAL hosted commands under source exact SHA 4a08e782...:
python3 -B swapz/tests/runtime/native/fixtures/round026-sideband-kunit-verdict.py --self-test -> PASS; strict negative suite rejects missing, fake, skipped, duplicate, failed and panic test evidence.
python3 -B swapz/tests/runtime/native/pinned-linux-zswap-sideband-test.py -> PASS; GCC+Clang -Wall/-Wextra/-Werror/-Wconversion/-Wshadow -fsanitize=address,undefined source helper executable regressions.
python3 -B swapz/tests/tools/stage-pinned-linux-zswap-sideband.py --linux-root linux -> EXIT 0, exact pinned original Linux c339f4010dea8b0d754f84ace70cd1b089878ef8 and only two original sha1 checked files: include/linux/blk_types.h 0cc09b975d8ffbd45ca3dc47533a71f8e8164de6 / block/bio.c b0fcc69de653524479e3b328aa29a37e97945b84.
git -C linux diff --check -> EXIT 0.
make -s -C linux O=<build> CC=gcc ... KCFLAGS=-DSWAPZ_ROUND025_SIDEBAND_CI_ONLY block/bio.o -> PASS for BOTH CONFIG_ZSWAP=y and CONFIG_ZSWAP=n with CONFIG_KUNIT=y and nm verifies source suite (dedicated original-source compiler job 133919465232 SUCCESS).
python3 -B linux/tools/testing/kunit/kunit.py run --arch=um --build_dir=<temp> --kunitconfig=<CONFIG_KUNIT=y/CONFIG_BLOCK=y/CONFIG_SWAP=y/CONFIG_ZSWAP=n> --make_options=KCFLAGS=-DSWAPZ_ROUND025_SIDEBAND_CI_ONLY --jobs=2 --timeout=120 --json=<temp>.json swapz_round025_sideband_compiler_only -> EXIT 0 in hosted job 133919464901. THIS ACTUALLY BOOTED original pinned Linux UML and executed all seven real C KUnit cases. Upstream KUnit output:
[PASSED] swapz_ci_clone_lifetime_kunit
[PASSED] swapz_ci_split_lifetime_kunit
[PASSED] swapz_ci_reuse_and_abort_kunit
[PASSED] swapz_ci_reject_invalid_kunit
[PASSED] swapz_ci_invalid_clone_kunit
[PASSED] swapz_ci_reuse_private_kunit
[PASSED] swapz_ci_abort_dead_ref_kunit
Testing complete. Ran 7 tests: passed: 7; reported 0.060s executing after 114.818s build.

FIRST REAL OBSERVED FOLLOW-ON ERROR: The new independent JSON+kernel-log verifier initially returned exit 2 with first_cause=missing_or_duplicate_kernel_case:swapz_ci_reuse_private_kunit, causing overall initial workflow FAILURE despite upstream 7/7 KUnit PASS. Pinned upstream lib/kunit/test.c::kunit_print_ok_not_ok prints "%s %zd %s" (no hyphen) whereas initial verifier expected "ok N - case". Upstream tools/testing/kunit/kunit_parser.TEST_RESULT allows optional hyphen. This is strict third-party custom verifier grammar false negative, NOT a real kernel panic/refcount/ABI source failure. Fixed in second non-force main commit ce68d2ada7a9e5eb41d64fd30a20ab1ef036a11c: accept both original valid KTAP forms, update adversarial self-test sample to genuine original no-hyphen syntax; keep exact unique case names and pass statuses in parsed upstream JSON plus actual raw test.log, and bounded fail-only kernel case diagnostics. New exact-SHA hosted CI 44049297152 is running at this comment. NEVER claim new corrected exact-SHA runner PASS until verified.

GO/NO_GO: End-to-end compressed handoff is definitively NO_GO despite successful source-only KUnit boot, because original source lacks an allocator-authenticated swap-slot epoch joined to original zswap STORE SHA and no proven live, semantically safe split/clone/DM-sideband ingress with current logical mapping/generation, GC relocation and durable lower-write-before-one-upper-ACK/read fence. Neither typed CI-only owned copy nor synthetic first positive tokens can authorize. The only compiled test admission returns -EOPNOTSUPP; production macros undefined, no live carrier. Normal upper REQ_SWAP original UNCOMPRESSED 4096, original fallback, zswap-only RAM pressure controller and swapz backing tier unchanged.

No host module load/kernel mutation, swapoff/swapon/mkswap, null_blk, mapper, memory-pressure, RAM-device or physical SWAPSPACE2 operations; first original 4096 header/signature/UUID and partition table untouched. Local full Linux checkout unavailable due github.com DNS and no local kernel results claimed. Agent1 owns exact-SHA CI and round closeout.

FINAL EXACT-SHA CI VERIFIED — same published source SHA ce68d2ada7a9e5eb41d64fd30a20ab1ef036a11c (no new publication):
https://github.com/k1moradi/swapz/actions/runs/44049297152 -> status=completed, conclusion=SUCCESS; both jobs independently SUCCESS.
- Original pinned Linux UML was actually BOOTED again through source-controlled tools/testing/kunit/kunit.py run --arch=um (hosted rootless, CONFIG_KUNIT=y, CONFIG_SWAP=y, CONFIG_BLOCK=y, CONFIG_ZSWAP=n, opt-in CI macro only). Upstream seven C KUnit cases EXECUTED/PASS 7/7. The separate strict actual RAW kernel KTAP plus upstream KUnit JSON verdict PASS:
  ROUND026_UML_KUNIT_EXECUTED_PASS suite=swapz_round025_sideband_compiler_only cases=7 arch=um
  ROUND026_UML_EXECUTED_ALL_CASES=PASS
  SOURCE_ONLY=PASS KUNIT_BOOT_EXECUTED=PASS LOADED_4096=NOT_RUN PHYSICAL=NOT_RUN
  LIVE_COMPRESSED=DISABLED PHASE_A=BLOCKED PHASE_B=DISABLED
- Original source exact pinned blob stager succeeded and git -C linux diff --check was clean. Host GCC+Clang ASan/UBSan 7 native source tests PASS; strict fake-KTAP verifier self-test PASS.
- Independent original Linux kernel GCC block/bio.o Kbuild+KUnit suite symbol passed for both CONFIG_ZSWAP=y and CONFIG_ZSWAP=n; workflow logged PINNED_BIO_GCC_CONFIG_ZSWAP_enabled_KUNIT_COMPILE=PASS and ...disabled...=PASS.
- First observed initial runner failure on 44048321459 remains recorded as an actual custom verifier grammar false negative (hyphen expected vs source-actual no hyphen); corrected by the source-verified parser change and rerun. No outstanding compiler, boot or KUnit case first failure on final exact-SHA run.
- FINAL Round026 Agent4 subtrack: SOURCE_ONLY=PASS; KUNIT_COMPILED=PASS; KUNIT_UML_EXECUTED_7_OF_7=PASS. This is NOT loaded matching host zswap/swapz swap-in, NOT live compressed carrier and NOT physical SWAPSPACE2 success. End-to-end architectural GO gate remains NO_GO. Phase A BLOCKED, forced RAW bypass and direct compressed handoff DISABLED. Agent1 handles integration/round closeout.


---
