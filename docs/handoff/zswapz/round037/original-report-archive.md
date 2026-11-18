# Round037 — original workers' REPORT_READY and status addendum, retained verbatim

[Issue #154](https://github.com/k1moradi/swapz/issues/154), original worker reports unedited below, including the historical first genuine failures and initial PENDING/QUEUED CI observations. See [Agent1 closeout](round-report.md) for **independently reverified LATER** completed CI. No historical run has been relabeled or rewritten.

## Original GitHub issue comment 1 — https://github.com/k1moradi/swapz/issues/154#issuecomment-6977953018

~~~~text
message: REPORT_READY
round: "037"
worker: 2
status: SOURCE_PUBLISHED_FIRST_ORIGINAL_RED_CORRECTED_NEW_EXACT_SOURCE_CI_QUEUED
frozen_task_sha: 3069e67a0a00679f79ae6729fddacdfeae22a4bd
original_source_sha: 58b6fad7df7bf0c1e1d4d6d34836c9d045dbf213
original_source_parent: 3069e67a0a00679f79ae6729fddacdfeae22a4bd
corrected_source_sha: 523e2f7422cb98554f2482018a20239f3137784d
corrected_source_parent: e58a98bbd9032eaf1c294e7030f6a8257d17ffcf
original_linux_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
phase_a: BLOCKED
source_mapped_authenticated: 0
forced_raw_bypass: DISABLED
direct_compressed_handoff: NO_GO_DISABLED
loaded_production: NOT_RUN
physical_swapspace2: NOT_RUN

**Agent2 real original Linux source implementation published on sole `main`, one-parent non-force expected-head fast-forward and SHA readback.** [Initial source commit `58b6fad7`](https://github.com/k1moradi/swapz/commit/58b6fad7df7bf0c1e1d4d6d34836c9d045dbf213) parent exact frozen task; 7 files: `tests/tools/stage-pinned-linux-zswap-composed.py`, `tests/runtime/native/pinned-linux-zswap-composed-source-test.py`, NEW `tests/runtime/native/fixtures/round037-original-mm-scope-host.c`, NEW `tests/tools/round037-original-mm-lifetime-verify.py`, NEW `.github/workflows/phase-a-zswap-original-mm-lifetime-owner.yml`, own `docs/handoff/zswapz/round037/agent2-evidence.md`, complete original >1MiB `docs/testing_standards.md` with distinct substantive same-commit appendix. Corrected [`523e2f74`](https://github.com/k1moradi/swapz/commit/523e2f7422cb98554f2482018a20239f3137784d) parent exact peer Agent3 source `e58a98bb...`, 4 Agent2-owned changed paths: composer, original source test, own evidence, full canonical standards fresh second substantive same-commit appendix preserving Agent3 and earlier text. No additional branch, PR, worktree, fork, force, peer overwrite or default source enablement.

**Original C source semantics:** New default-undefined `SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST` under previous original 025/028/030/031/032/034/035/036 + CONFIG_KUNIT guards. Generated ACTUAL original `mm/page_io.c` synchronous scoped probe obtains real `get_swap_device(original_slot)` ref BEFORE allocator epoch reads, checks true original sealed owner, typed full swp entry/slot epoch and true nonlinear `swap_folio_sector` and 4096 SWAP REQ_OP_WRITE one prepopulated bvec, repeats transient epoch check, detaches ref once and calls `put_swap_device` before async source BIO submit. Private original probe is `static noinline` for strict machine-code CI witness, never exported and never live-authenticates. Four new genuine original KUnit C **synthetic stimulus** cases cover epoch ABA, changed area/new bdev/swapoff and nonlinear/header geometry, clone/split/late BIO endio and old owner, once-only detach/ref cleanup. Earlier original 27 preserved; new verifier requires 31/31 distinct **actually booted kernel** cases; a source mock cannot be called genuine active MM pressure eviction.

**Initial exact-source first red (preserved):** [Round037 original #44298558558](https://github.com/k1moradi/swapz/actions/runs/44298558558), UML job `134781912996` FAILED before kernel KUnit execution at native Python source inspection `AssertionError: 'submit_bio(' unexpectedly found`: a retained original C comment describing unchanged upstream submission triggered overly broad text assertion. ACTUAL extracted original helper GCC+Clang -Werror ASan+UBSan had PASS before this assertion. Fixed by stripping C comments for executable forbidden-call test; no real I/O call introduced. Full original x86 y/n job `134781913327` FAILED after guarded original source C compilation passed, first terminal `Actual original Round037 scoped MM owner machine code absent` (`enabled-original-guarded-zswap`, exit 3), because static private probe was inlined and omitted from `nm`. Corrected only private CI-gated function `static noinline`, retaining kernel strict warnings and normal WRITE. Both original jobs are historical RED, **31 new original KUnit NOT_RUN** on initial SHA. Old Round034 historic policy RED unaffected.

**Corrected exact-source test status at report:** [new original Round037 workflow #44299424509](https://github.com/k1moradi/swapz/actions/runs/44299424509), UML job `134784946658` and genuine original full `CONFIG_ZSWAP=y/n` vmlinux/modules/Module.symvers+GPL independent `round032-bio-probe.ko` and matched actual `dm-swapz.ko` job `134784946158`, **QUEUED**; NO claim that 31/31 original KUnit, correct-source original y/n, or module modpost has passed. New exact-source native + repository-policy [#44299424640](https://github.com/k1moradi/swapz/actions/runs/44299424640), policy job `134784947181` **QUEUED**. First source exact repository-policy [#44298558256](https://github.com/k1moradi/swapz/actions/runs/44298558256) job `134781907853` PASSED, but cannot substitute for corrected-source policy. Original 10-file upstream manifest strict check and both GCC+Clang ASan/UBSan actually ran on first source. No owner-host privileged or physical testing.

**No authorization:** Current original swap-area users percpu_ref only fences swapoff inside synchronous source scope; allocator epoch cluster lock also transient, does not pin original currently allocated slot incarnation; no combined original active area+bdev/sector + source BIO owner + exact downstream DM target map/GC generation lease across clone/split/abort/late original endio/swapoff. Source returns `-EOPNOTSUPP` even for matching or forged positive mock lease flags. `SOURCE_MAPPED_AUTHENTICATED=0`, no genuine active pressure eviction, no real lower write/map publication/ACK, `PHASE_A=BLOCKED`. zswap ONLY bounded compressed RAM and genuine MM-pressure eviction; swapz ONLY valid SWAPSPACE2 disk tier packing/GC. Ordinary RAW stays **original UNCOMPRESSED full 4096 bytes**; first ENTIRE 4096-byte SWAPSPACE2 signature/header/UUID and partition table immutable. No privileged, loaded production, actual swapoff/swapon, mkswap, null_blk/mapper or physical tests.
~~~~

## Original GitHub issue comment 2 — https://github.com/k1moradi/swapz/issues/154#issuecomment-6978047090

~~~~text
message: REPORT_READY
round: "037"
agent: 3
status: GUARDED_DM_ASYNC_SOURCE_PUBLISHED; CI_RUNNING; NO_RUNTIME_ADMISSION
frozen_task_sha: 3069e67a0a00679f79ae6729fddacdfeae22a4bd
initial_agent3_commit: e58a98bbd9032eaf1c294e7030f6a8257d17ffcf
initial_parent: 58b6fad7df7bf0c1e1d4d6d34836c9d045dbf213
corrected_agent3_source_commit: 1860899305d301e85b4d5f70e7d780079664820e
corrected_parent: 523e2f7422cb98554f2482018a20239f3137784d
direct_main: one-parent non-force expected-head fast-forward, exact remote SHA readback, peer changes and full canonical testing standards preserved; NO branch/PR/fork/worktree/force.

Initial commit paths (6):
- src/kernel/dm-target.c
- tests/runtime/native/fixtures/round037-dm-async-lower-host.c
- tests/tools/round037-dm-async-verify.py
- .github/workflows/phase-a-zswap-dm-async-lower-lifetime.yml
- docs/handoff/zswapz/round037/agent3-evidence.md
- docs/testing_standards.md (full >1 MiB original plus Agent2 append plus distinct Agent3 substantive same-source appendix, blob checked)
Corrective commit paths (4): same actual production DM C, same Round037 fixture, own evidence, complete canonical standards with ANOTHER distinct substantive same-source appendix; other Agent2 original compositor/CI/source files untouched.

Actual increment: original source-compiled production DM guarded default-off nested SWAPZ_ROUND037_DM_ASYNC_LOWER_LIFETIME_TEST, independently caller-owned private spinlock mailbox/ticket/ref and copied prior original GPL BIO LZ4 v1 original 4096 SHA, 4/8/16KiB post-header lower stage/image. PREPARED -> FAKE_WRITE_IN_FLIGHT (preparer releases ordered_owner) -> separate POSIX host-thread fake lower callback with NO ctx/source BIO/target/sidecar pointers -> ordered-owner current map/GC/source slot/store epoch/extent/owner/teardown revalidation -> ONLY PRIVATE mock publication and one HYPOTHETICAL ack. Callback cancellation can precede late delivery even after mock teardown; old callback reference holds caller-owned mailbox lifetime until drain, reissue blocked while outstanding, duplicate and old ticket rejected. No simultaneous target map mutation and no lock held during fake lower transfer. Actual old source Round036 exact CRC32C/dictionary-free LZ4 decode EXACT 4096 full original SHA/padding check reused. Host outputs/publication unchanged on failure, owned bytes scrubbed. Corrective commit hardens strictly increasing ticket against A->B->A ABA and normalizes all nonzero fake lower error (including positive) to -EIO; explicit new regression faults.

New independent CI run at initial exact SHA: https://github.com/k1moradi/swapz/actions/runs/44299241771
- native x86_64 job 134784290221: COMPLETED SUCCESS, real production default/prior guarded HWE-linked module W1/-Werror (NOT original GPL ABI qualification).
- native arm64 job 134784290666: COMPLETED SUCCESS, real production default/prior guarded HWE-linked module W1/-Werror.
- repository-policy job 134784290999: COMPLETED SUCCESS, exact original new standards.
- original-same-kernel-dm job 134784290721: still IN_PROGRESS as of this comment, host actual source-extracted GCC + Clang strict -Wconversion/-Wshadow/-Werror ASan+UBSan step COMPLETED SUCCESS, pristine original ten-file SHA staging COMPLETED SUCCESS, true pinned original CONFIG_ZSWAP=y vmlinux/modules/Module.symvers and both matched original GPL dm-swapz.ko modpost CURRENTLY RUNNING, NOT YET PASS. Original upstream pinned torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8.
Corrected exact latest Agent3 CI run: https://github.com/k1moradi/swapz/actions/runs/44300316387; jobs repository-policy 134788034314, native x86_64 134788034652, native arm64 134788034817, original-same-kernel-dm 134788034803 initially QUEUED, no claim of pass until each finishes. Related source-C product exact x86/arm run https://github.com/k1moradi/swapz/actions/runs/44299241248 compile-only jobs 134784289239, 134784289541 COMPLETED SUCCESS at initial SHA; exact-C jobs pending at time checked.

First genuine failures: NO Round037 Agent3 new strict compiler/host/physical failure observed as of this REPORT_READY; all still-running or queued steps explicitly remain NOT COMPLETE. Preserve historical genuine Round036 fixture -Wshadow/-Werror first failure #44284588089 as RED (and prior original current-macro error #44284080575), not retroactively PASS. A first error in the new corrected original compiler/Kbuild, DM modpost, host sanitizer or policy must be recorded and repaired by another distinct same-commit complete standards append, NOT suppressed.

SOURCE_MAPPED_AUTHENTICATED=0; PHASE_A=BLOCKED; FORCED_RAW_BYPASS=DISABLED; DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED; LOADED_PRODUCTION=NOT_RUN; PHYSICAL_SWAPSPACE2=NOT_RUN; REAL_UPPER_ACK=0; REAL_LOWER_WRITE=0; REAL_MAP_PUBLISH=0. Source/DM active original MM slot/bdev/sector and allocator epoch lifetime through real IO/GC remains UNPROVEN. zswap alone controls bounded compressed RAM and MM pressure; swapz ONLY existing valid SWAPSPACE2 disk packing/GC, ordinary RAW_4096 is original UNCOMPRESSED 4096, protected physical first entire 4096 plus partition table untouched; no privileged/physical/host hardware/mkswap/swapon/swapoff/loaded/pressure testing.
~~~~

## Original GitHub issue comment 3 — https://github.com/k1moradi/swapz/issues/154#issuecomment-6978011129

~~~~text
message: CI_STATUS_ADDENDUM
round: "037"
worker: 2
report_ready: https://github.com/k1moradi/swapz/issues/154#issuecomment-6977953018
corrected_source_sha: 523e2f7422cb98554f2482018a20239f3137784d
corrected_source_parent: e58a98bbd9032eaf1c294e7030f6a8257d17ffcf

Correction source verification update: exact corrected-source [native run #44299424640](https://github.com/k1moradi/swapz/actions/runs/44299424640), **repository-policy job `134784947181` COMPLETED SUCCESS** with source-specific substantive same-commit canonical testing-standards check; **rootless source-contract job `134784947553` COMPLETED SUCCESS**. Other native jobs were still queued when read, not claimed. New original genuine source [workflow #44299424509](https://github.com/k1moradi/swapz/actions/runs/44299424509) full original x86 `CONFIG_ZSWAP=y/n` vmlinux/modules/Module.symvers/GPL probe/matched DM job `134784946158` **IN_PROGRESS at actual original Kbuild**, new actual original booted UML prior27+new4 JSON/KTAP job `134784946658` **QUEUED**, so 31/31 new KUnit and current source real original full y/n **NOT YET VERIFIED PASS**. The initial jobs `134781912996` and `134781913327` at `58b6fad7...` stay historical FAILs with first exact diagnostics already in REPORT_READY. `SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`, no direct handoff/forced RAW, loaded or physical tests.
~~~~

