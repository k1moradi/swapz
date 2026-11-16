# zswapz round index

The current execution state is controlled by the issue's exact `ROUND_OPEN` / closing comments, not inferred from `main` activity or historical CI. A task commit freezes instructions; report commits archive outcomes.

| Round | Source baseline | Issue | Task package | Engineering gate |
| --- | --- | --- | --- | --- |
| [001](round001/README.md) | `c128ac32374a753a0b27ae0ebec67693355b1b55` | [#118](https://github.com/k1moradi/swapz/issues/118) | Seven independent rootless/source-audit tasks; execute only after an issue `ROUND_OPEN` comment | Phase A BLOCKED; Phase B DEFERRED |

Round 001 complete: 7/7 GitHub reports archived and indexed in [round-report.md](round001/round-report.md). Phase A remains BLOCKED; Phase B DEFERRED.

Round 001 workers: Agent 2 kernel options, 3 stock-kernel fallback, 4 accounting, 5 BIO ABI safety, 6 negative-path source tests, 7 passive collector, 8 build matrix. Agent 1 is coordinator and sole canonical publisher. All `*-report.md` files and `round-report.md` are created at collection/close, not placeholders counted as tests.

## Round 002 — CLOSED / PARTIAL

| Round | Frozen swapz baseline | Coordination issue | Concurrent workers | Gate |
| --- | --- | --- | --- | --- |
| [002](round002/README.md) | `f11e8795f44f15fecc6b2b200c0b1a9e4eaeb364` | [#119](https://github.com/k1moradi/swapz/issues/119) | Agent 2 kernel-producer code patch; Agent 3 passive DM-consumer code patch | Phase A BLOCKED; Phase B DEFERRED |

Round 002 **was opened** by the verified [`ROUND_OPEN` comment](https://github.com/k1moradi/swapz/issues/119#issuecomment-6892929007) at task commit `b949018a8f0461a5886eeaf0da4a1130c62dcf23`. [Coordinator execution dispatch](https://github.com/k1moradi/swapz/issues/119#issuecomment-6893439451) corrects any misrouted Round 003 instructions. Both Agents 2 and 3 must **edit real source files**, not submit patch text as the deliverable. [Source-edit correction](round002/source-edit-correction.md) supersedes conflicting task text: Agent 3 is exclusive `swapz/main` code publisher and must report its verified commit to #119; Agent 2 edits the separate pinned Linux source checkout and must identify its actual persisted code revision or a concrete publication blocker. Round 003 is drafted in issue #120 but has NOT received ROUND_OPEN.

**Round 002 closeout (2026-11-15):** 2/2 accountable reports archived in [round-report.md](round002/round-report.md), and issue #119 closed for reporting. Agent 3 published real passive consumer source (bounded PASS); Agent 2 remained BLOCKED_PUBLISH with no committed Linux producer. Phase A BLOCKED, Phase B DEFERRED.

## Round 003 — CLOSED / SOURCE-INTEGRATED, PHASE A STILL BLOCKED

| Round | Frozen swapz source | Coordination issue | Workers | Milestone |
| --- | --- | --- | --- | --- |
| [003](round003/README.md) | `15b98edef5d8b4e401d8c5e2c9a4d7a012100ff7` | [#120](https://github.com/k1moradi/swapz/issues/120) | Agent 4 existing swapzctl provenance reader; Agent 6 existing DM source-bound regression tests | Phase A BLOCKED; Phase B DEFERRED |

The [authoritative `ROUND_OPEN`](https://github.com/k1moradi/swapz/issues/120#issuecomment-6895221177) froze Round 003 at task commit `5d5ca4ecc6c456ce97c68cebba063bfb996f884e`. Original Agent 4/6 reports are archived verbatim in [round-report.md](round003/round-report.md). Agent 1 integrated the actual source into `main` at `db82db4230473a9b386eb286733b365703944a90` and `431c9218eb2eb4905ca16c1f8c6d0928096dba83`, then provided the [full-source multi-architecture CI hook](https://github.com/k1moradi/swapz/commit/bd56936ef22d71529f2864ff2eb7de1781bb0f34). Agent 2's Linux producer remains blocked by missing authorized durable source repository. Agent 3's pre-opening report is historical, not a Round 003 completion. Phase A BLOCKED, Phase B DEFERRED.

## Round 004 — CLOSED / source-integrated and CI-verified, Phase A BLOCKED

| Round | Frozen swapz source | Issue | Agents (2 workers) | Gate |
| --- | --- | --- | --- | --- |
| [004](round004/README.md) | `f9f65369c2dba65797989e10374e2350d58d25c2` | [#121](https://github.com/k1moradi/swapz/issues/121) | Agent 5 native compiled parser adversarial tests; Agent 8 full pinned Linux `CONFIG_ZSWAP=y/n` Kbuild CI | Source-bound/CI improvement; Phase A BLOCKED, Phase B DEFERRED |

Worker tasks can execute simultaneously against the frozen input. Agent 1 is the sole canonical `main` writer, merges independently additive governing-standard updates and archives original reports. GitHub issue #121's unique `ROUND_OPEN` is the authoritative start, not this index entry. Agent 2's modified Linux producer is **not** assigned without an owner-authorized writable Linux source repository. **Round 004 closeout:** [report](round004/round-report.md); issue [#121](https://github.com/k1moradi/swapz/issues/121) closed after Agent 1 verified actual source integration `275187fa53d8c00200093cf1d56a9ba806e5bd2c` and [hosted pinned Linux CONFIG_ZSWAP=y/n Kbuild #43726191654](https://github.com/k1moradi/swapz/actions/runs/43726191654), [native rootless #43726191538](https://github.com/k1moradi/swapz/actions/runs/43726191538), and [exact-C #43726191553](https://github.com/k1moradi/swapz/actions/runs/43726191553) **PASS**. Phase A BLOCKED; Phase B DEFERRED.

## Round 005 — CLOSED (source integrated, bounded CI; full native/module jobs pending)

| Round | Frozen source | Coordination issue | Agents (2 workers) | Milestone |
| --- | --- | --- | --- | --- |
| [005](round005/README.md) | `8bdc02de109aa3df65b6f0d0c22d13a04703e9e4` | [#122](https://github.com/k1moradi/swapz/issues/122) | Agent 3 pinned-stock-Linux compile of actual swapz module; Agent 5 native double-INFO provenance race/atomic-output tests | Compile and rootless safety only, Phase A BLOCKED, Phase B DEFERRED |

The sole authoritative `ROUND_OPEN` comment in issue #122 is the worker execution start. Both workers use pre-round sources and run simultaneously; Agent 1 integrates source, merges independent additive standards and verifies actual hosted CI. No upstream Linux producer branch, fork, additional repo or owner decision is needed for these two *bounded* tasks. Neither proves authenticated live zswap stored-entry writeback. [Round 005 closeout](round005/round-report.md) records both real integration commits, archived originals and exact-source CI status; #122 closed with full native and linked-module jobs still pending, no artificial PASS.

## Round 006 — CLOSED_INCOMPLETE (Agent 8 integrated; Agent 7 NOT_DELIVERED)

| Round | Frozen swapz source | Issue | Independent workers | Evidence scope |
| --- | --- | --- | --- | --- |
| [006](round006/README.md) | `47a793c1480556c075f23ecbe13a5b465d616916` | [#123](https://github.com/k1moradi/swapz/issues/123) | Agent 7 production-linked fake-DM observer fault-atomicity stress; Agent 8 independent pinned stock Linux LLVM/Clang ZSWAP object Kbuild | Native rootless and unchanged public Linux only; Phase A BLOCKED, Phase B DEFERRED |

Agent 1 alone serially integrates worker source commits and tests them in CI. The **unique `ROUND_OPEN`** comment in issue #123 defines the frozen task publication SHA. The full Linux upstream producer is unassigned because it still has no owner-approved durable writable kernel-source repository. Round 005's unfinished native and full GCC module jobs remain an Agent 1 follow-up, not a Round 006 agent prerequisite. [Accountable Round 006 closeout](round006/round-report.md): original 2-worker plan, only Agent 8 delivered and passed independent LLVM source-object CI; Agent 7 did not supply code/report and is retained as unfulfilled backlog. Closed as incomplete, not PASS. Round 007 can advance independently after a new frozen task/opening.

## Round 007 — CLOSED_SOURCE_INTEGRATED (CI still partly in progress)

| Round | Provisional planning source | Issue | Proposed independent workers | Start gate |
| --- | --- | --- | --- | --- |
| [007](round007/FINAL.md) | `45a3e8e911e447d9807f786ca33e14eac99374f8` | [#124](https://github.com/k1moradi/swapz/issues/124) | Agent 3 known `Module.symvers` linked-module CI repair; Agent 6 executable CI evidence integrity negatives | Round 006 CLOSED_INCOMPLETE; final task SHA published; unique `ROUND_OPEN` is execution authority |

The [final task package](round007/FINAL.md) supersedes the preserved historical DRAFT prompts without retroactively authorizing Agent 6's pre-opening report. Round 006 was explicitly [CLOSED_INCOMPLETE](round006/round-report.md): Agent 8 LLVM build PASS, Agent 7 NOT_DELIVERED. Both Round 007 agents start simultaneously from frozen `45a3e8e911e447d9807f786ca33e14eac99374f8` only after the unique `ROUND_OPEN` in #124. No peer result or upstream writable Linux source repository is required. [Accountable round report](round007/round-report.md): both workers' actual source is integrated, cross-worker evidence-stage contract reconciled, original reports archived, first hosted checks PASS, full GCC and exact-C pending. Phase A remains BLOCKED.

## Round 008 — CLOSED_SOURCE_INTEGRATED_CI_FAILED (2/2 delivered; GCC linked-module FAIL)

| Round | Frozen source baseline | Issue | Workers (excluding Agent 1) | Evidence limit |
| --- | --- | --- | --- | --- |
| [008](round008/README.md) | `af334b3408b9a660fc7f4b15d82d8e5a9e6374bb` | [#125](https://github.com/k1moradi/swapz/issues/125) | Agent 4 compiled real-reader multi-target failure atomicity; Agent 8 real pinned Linux in-run artifact integrity verifier | Fake DM/rootless and stock Linux only; Phase A BLOCKED, Phase B DISABLED |

Round 007 [source closeout](round007/round-report.md) accounts for both real source commits and keeps full GCC Kbuild pending. Round 006 Agent 7 undelivered native source work has been **reassigned to Agent 4**, not falsely marked complete. The unique `ROUND_OPEN` issue #125 comment with exact task commit is the only worker execution authority. Both jobs run independently from the pre-round source, with Agent 1 alone integrating source and merging distinct additive standards.

[Round 008 accountable closeout](round008/round-report.md) records actual Agent 4 and Agent 8 source integrations; real native/rootless and production-C GitHub CI PASSED; pinned Linux LLVM source-object Kbuild PASSED; pinned GCC `dm-swapz.ko` failed on missing `SWAPZ_BUILD_SOURCE_CLEAN_STRING` at `dm-target.c:71`. [#125](https://github.com/k1moradi/swapz/issues/125) is administratively closed **without a full qualification PASS**; the explicit failure becomes next-round targeted engineering, not an unreported release regression. Phase A BLOCKED; Phase B DISABLED.

## Round 009 — CLOSED_SOURCE_INTEGRATED_CI_PENDING (2/2 sources, Kbuild pending)

| Round | Frozen source | Issue | Exactly two parallel agents excluding coordinator | Start condition |
| --- | --- | --- | --- | --- |
| [009](round009/README.md) | `4063b88422dd62b1d4b1a990f0cfe9961e73277c` | [#126](https://github.com/k1moradi/swapz/issues/126) | [Agent 3 real GCC build-info bug fix](round009/agent3-pinned-gcc-build-info-fix.md) and [Agent 2 modified pinned Linux MM/BIO origin source staging](round009/agent2-real-linux-provenance-source-staging.md) | Final task SHA verified on main and unique `ROUND_OPEN` in #126 |

Round 008 [closed accurately](round008/round-report.md): both real worker sources integrated and native/production-C passed, separate LLVM source-object Kbuild passed, GCC linked-module failed at a genuine generated build-info macro error. Round 009's GCC repair and real upstream Linux producer prototype are independent by file and test ownership; only coordinator Agent 1 publishes `main` and verifies hosted results. The MM/BIO prototype uses a disposable full source checkout and records **actual modified Linux source bytes**, not a separate writable upstream repository or standalone patch. Phase A remains BLOCKED and Phase B disabled.

[Round 009 accountable closeout](round009/round-report.md) archives both complete worker sources and actual serial main integrations `7ff6a5b5` and `1db78aba`, with original source reports preserved byte-for-byte and SHA-256 at [archive](round009/original-report-archive.md). The actual [pinned GCC Kbuild #43790416873](https://github.com/k1moradi/swapz/actions/runs/43790416873) and [modified Linux MM/BIO Kbuild #43790479509](https://github.com/k1moradi/swapz/actions/runs/43790479509) were still IN_PROGRESS at closeout and must not be described as PASS. Phase A BLOCKED; Phase B DISABLED.

[Round 009 late hosted evidence](round009/late-ci-results.md): source-exact modified Linux `CONFIG_ZSWAP=y/n` object Kbuild **PASS** [run #43790479509](https://github.com/k1moradi/swapz/actions/runs/43790479509), true stage and object compilation of modified pinned Linux. Native/stock GCC linked module remained independently gated; no matched kernel+consumer or loaded runtime PASS. Phase A BLOCKED; Phase B DISABLED.

## Round 010 — CLOSED_SOURCE_INTEGRATED_CI_RECHECK_PENDING (2/2 real sources, matched Kbuild pending)

| Round | Frozen source | Coordination issue | Concurrent workers excluding Agent 1 | Qualification bound |
| --- | --- | --- | --- | --- |
| [010](round010/README.md) | `4f88c81dcba4ee09d32f067e7353664a821ba986` | [#127](https://github.com/k1moradi/swapz/issues/127) | [Agent 5 actual producer lifecycle/split/clone source hardening](round010/agent5-real-bio-origin-lifecycle-regressions.md); [Agent 8 matched patched Linux plus real dm-swapz.ko CI](round010/agent8-matched-patched-linux-swapz-module-kbuild.md) | Independent source work; no same-round dependency; Phase A BLOCKED, Phase B disabled |

Round 009 [source closeout](round009/round-report.md), [late actual pinned modified Linux Kbuild PASS](round009/late-ci-results.md) and original report hashes are preserved. No result on a linked matched module, booted kernel or actual zswap writeback is assumed as a precondition. The issue #127 unique `ROUND_OPEN` marker names the final task-publication SHA and is the only authority to start. Both workers edit actual existing committed source and implement/test independently; Agent 1 alone publishes `main` and verifies hosted source. No upstream writable fork/repository or privileged device operations required.

[Round 010 coordinator closeout](round010/round-report.md) records both worker source integrations, Agent 5's corrected commit supersession, [original worker report SHA-256 archive](round010/original-report-archive.md), the first actual 20-case hosted rootless test failure and coordinator's source-only assertion fix `ca8f0874`. Matched patched Linux/DM linked-module qualification remains pending on [#43793863015](https://github.com/k1moradi/swapz/actions/runs/43793863015); Phase A BLOCKED and Phase B DISABLED. Repository still has historic divergent branches; only coordinator-approved source is integrated, no open PRs.

## Round 011 — CLOSED_SOURCE_INTEGRATED_CI_PENDING (2/2 real commits)

| Round | Frozen source | Issue | Independent workers excluding Agent 1 | Status |
| --- | --- | --- | --- | --- |
| [011](round011/README.md) | `b9ec668aa7fc7d497d33bf7174277de4de2750e4` | [#128](https://github.com/k1moradi/swapz/issues/128) | [Agent 2 actual pinned Linux KUnit source](round011/agent2-pinned-linux-bio-origin-kunit.md); [Agent 6 executable producer→consumer ABI negative tests](round011/agent6-producer-consumer-origin-abi-contract.md) | Publish final tasks, then one ROUND_OPEN; both start simultaneously without same-round prerequisites |

Round 010 is [source closed](round010/round-report.md) with actual first matched-CI rootless failure and coordinator repair `ca8f0874`. Next tasks have no cross-worker overlap, no future hosted CI acceptance precondition and work from a single frozen `main` source. Historical 65 remote non-main branches require separate backup-backed cleanup; neither task may delete references. Phase A BLOCKED and Phase B DISABLED.

[Round 011 accountable closeout](round011/round-report.md) integrates both real worker sources `18c184cc` (Agent 6) and `49765143` (Agent 2) on only `main`, with [original REPORT_READY bodies and SHA-256 archive](round011/original-report-archive.md). Real new KUnit and patched matched module GitHub workflows are in progress; do not claim PASS. Prior kernel-export warning first failure [#43793863015](https://github.com/k1moradi/swapz/actions/runs/43793863015) is retained. Live branch inventory now shows exactly `main`, with zero open PRs. Phase A BLOCKED; Phase B DISABLED.

## Round 012 — CLOSED_SOURCE_INTEGRATED_CI_RECHECK_PENDING (2/2 actual worker commits)

[Round 012 joint authority and scope](round012/README.md); [Agent 3 real matched pinned Linux exporter W=1 warning gate](round012/agent3-matched-linux-kernel-doc-warning-gate.md); [Agent 5 real pinned Linux KUnit C API source hardening](round012/agent5-real-linux-bio-kunit-hardening.md). Source baseline 206ed300c52e563495a15fac21df9000fb38ecee, [coordination issue #129](https://github.com/k1moradi/swapz/issues/129), two workers excluding Agent 1, no same-round peer requirements. Both create actual code commits with sole frozen parent, Agent 1 alone updates main; zero branches outside main, zero open PRs. [Round 011 closeout](round011/round-report.md) retains source and pending hosted CI. Phase A BLOCKED and Phase B DISABLED.

[Round 012 accountable closeout](round012/round-report.md) integrates Agent 3 at `dad2bc3c` and Agent 5 at `76f45fca` onto sole `main`, with [verbatim REPORT_READY bodies and SHA-256](round012/original-report-archive.md). Initial exact source KUnit [#43811465222](https://github.com/k1moradi/swapz/actions/runs/43811465222) and matched module [#43811465194](https://github.com/k1moradi/swapz/actions/runs/43811465194) were **FAIL at rootless source-test contract before Kbuild**; initial production-C [#43811465375](https://github.com/k1moradi/swapz/actions/runs/43811465375) failed source ABI stale 12-vs-13 count. Agent 1 test-only commits `dbfdf7d1`, `bff7963e`, `a11c02bc` correct that source-test alignment; their exact-source hosted CI is pending, no final PASS assumed. Owner RAM log has physical NOT_RUN on source_advanced_after_ram; no physical failure/PASS inferred. Phase A BLOCKED; Phase B disabled; main-only repo, 0 PRs.

[Round 012 later exact-CI evidence](round012/late-ci-results.md): matched source #43811904786 FAIL due first/last verifier ordering, coordinator test-only fix `46290980` on main; production-C #43811904940 FAIL due legitimate retained Linux swap_ops.h staging anchor misclassified by older ABI test. Strict source tests require new exact-source execution; no physical or Phase A PASS. This is subsequent evidence, not a rewrite of the first closeout checkpoint.

## Round 013 — FINAL frozen independent main-only engineering (unique ROUND_OPEN required)

[Joint final task contract](round013/README.md) and [issue #130](https://github.com/k1moradi/swapz/issues/130). Frozen engineering source `2be15cb171a6a4e15453520512df8ebf779e6f3d`, exactly 2 workers excluding Agent 1: [Agent 6 actual pinned Linux producer→consumer ABI source test repair](round013/agent6-source-bound-producer-consumer-abi-regression.md) and [Agent 7 RAM source-lease/physical NON-ADMISSION real regression tests](round013/agent7-ram-source-lease-and-physical-nonadmission.md). Both start after one authoritative ROUND_OPEN and are simultaneously independently executable, disjoint files and no peer or CI prerequisites. Agent 1 is sole serial remote main writer; no extra refs or PRs. [Round 012 source closeout](round012/round-report.md) and [later exact CI failures](round012/late-ci-results.md) are preserved, no new KUnit/matched module/physical PASS inferred. Phase A BLOCKED, Phase B disabled.

## Round 013 — CLOSED_SOURCE_INTEGRATED_EXACT_CI_PARTIAL

[Accountable Agent 1 source report](round013/round-report.md), [original worker REPORT_READY bodies and SHA-256](round013/original-report-archive.md), [official close](https://github.com/k1moradi/swapz/issues/130#issuecomment-6909918710). 2/2 nominated actual worker sources integrated onto main, Agent6 `fb2c925e`, Agent7 `c3a26a12`. Integrated production C and rootless physical evidence PASS, native rootless Make interface FAIL on `c3a26a`, prior KUnit UML effective config mismatch. One remote main, zero PRs, Phase A blocked, Phase B off.

## Round 014 — FINAL frozen independent main-only tasks (unique ROUND_OPEN required)

[Joint task ownership](round014/README.md) and [issue #131](https://github.com/k1moradi/swapz/issues/131). Frozen source `7b25f9c7734b82780f6a55021d4ac64ed5b194b6`; 2 independent workers excluding Agent 1: [Agent 2 patched Linux UML KUnit effective Kconfig gate](round014/agent2-kunit-uml-config-diagnostic-and-case-gate.md) and [Agent 4 source-bound rootless Make interface first failure](round014/agent4-native-make-interface-rootless-failure.md). Actual code/CI paths disjoint, testing standards same file but two distinct independently additive blocks reconciled by coordinator. No worker branches, PRs, worktrees or remote-main pushes; Agent 1 serially integrates. Both start simultaneously after one verified ROUND_OPEN without peer/CI prerequisite. Phase A blocked, Phase B disabled.

## Round 014 — accountable source integration and pending hosted verification

[Source-integrated closeout](round014/round-report.md): 2/2 original frozen-parent real code commits integrated on sole main, Agent 2 `0b7b10d1→bc44b80e`, Agent 4 `2593159e→2e8169fa`, [verbatim reports + SHA256](round014/original-report-archive.md), Agent 2 and 4 unique standards cochanges both preserved. Current physical-source and private static CI PASS, production-C/project goals/KUnit in progress at initial checkpoint; no Linux KUnit five-case y/n PASS inferred. User priority is cooperative zswap compressed-payload writeback preserving RAM zswap bytes, but current swapz RAW is full uncompressed 4096 bytes; genuine direct compressed handoff requires separate codec/length/lifetime/readback contract. Next parallel actual code/source tasks will be independent producer/consumer/scheduler groundwork, default disabled. Phase A BLOCKED; Phase B disabled.

## Round 015 — FINAL frozen independent producer/consumer/scheduler source groundwork (unique ROUND_OPEN required)

[Issue #132](https://github.com/k1moradi/swapz/issues/132), [joint handoff contract](round015/README.md). Source baseline `6d5b40198cfac271e100986fd8bd7637abf40541`; exactly **3** workers excluding Agent 1: [Agent 2 optional pinned zswap compressed payload producer](round015/agent2-optional-pinned-zswap-compressed-producer.md), [Agent 3 swapz kernel guarded codec/readback consumer](round015/agent3-swapz-guarded-compressed-consumer.md), [Agent 7 cooperative zswap–swapz CPU/device/pressure schedule](round015/agent7-zswap-swapz-cooperative-scheduling.md). All start simultaneously after one official ROUND_OPEN, no same-round code/dependency overlap; distinct test/coding standards append-only sections are Agent1-reconciled. User's ideal compressed zswap RAM to SWAP via swapz is Stage D, **not** current RAW (uncompressed 4KiB); versioned separate codec/representation/CRC/lifetime/4096 decode proof needed. This round produces actual guarded source implementation and native tests but must not enable direct handoff or Phase B by default. Phase A BLOCKED; Phase B disabled.

## Round 015 — source integrated, exact-source CI review underway

[Round 015 integrated source report](round015/round-report.md), [verbatim worker reports](round015/original-report-archive.md), and [official issue #132](https://github.com/k1moradi/swapz/issues/132). All 3 source commits integrated on single remote main at f716a5162a098742ec4bf7ab17b6a6a977bb75d4; 10 source/doc/CI paths changed, independent testing-standard sections reconciled. Rootless/static CI passed at first check; native, production-C, matched Linux Kbuild and real KUnit statuses are tracked in the report. Source integration is not loaded stored-entry proof. Phase A BLOCKED, Phase B and direct compressed handoff DISABLED.

## Round 016 — PREPARING, no worker started

[Coordination issue #133](https://github.com/k1moradi/swapz/issues/133) and [joint task contract](round016/README.md). Frozen source candidate f716a5162a098742ec4bf7ab17b6a6a977bb75d4. Exactly **2** next workers, Agent 2 [real KUnit UML manifest first failure](round016/agent2-pinned-kunit-manifest-fix.md) and Agent 3 [real DM provenance and matched-module qualification](round016/agent3-dm-origin-qualification.md). Their source/workflow/test ownership is disjoint; distinct standards sections reconciled by Agent 1. [Short notification DRAFT](round016/notification.md). No ROUND_OPEN until prior engineering CI/accountable outcomes are verified; publication alone never starts any AI session.

## Round 015 — CLOSED_SOURCE_INTEGRATED_CI_PARTIAL_KUNIT_FAIL

[Final integrated source and CI report](round015/round-report.md); [original Agent 2/3/7 reports](round015/original-report-archive.md); [issue #132](https://github.com/k1moradi/swapz/issues/132). All 3 worker source commits integrated at f716a5162a098742ec4bf7ab17b6a6a977bb75d4, and original evidence preserved. Four source/rootless/package CI runs PASS; actual KUnit y/n evidence-manifest parser FAIL; native and actual matched modified-Linux module runs still IN_PROGRESS at historical closeout and must be followed up. No KUnit five-case proof, real loaded writeback or actual 4096-byte readback; Phase A BLOCKED; Phase B RAW and compressed direct handoff DISABLED.

## Round 016 — source dispatch authorization pending unique ROUND_OPEN

[Issue #133](https://github.com/k1moradi/swapz/issues/133), [Agent 2 exact KUnit manifest parser engineering](round016/agent2-pinned-kunit-manifest-fix.md), [Agent 3 DM observational provenance and paired module engineering](round016/agent3-dm-origin-qualification.md), and [draft short worker notification](round016/notification.md). Frozen independent engineering source f716a5162a098742ec4bf7ab17b6a6a977bb75d4, 2 workers excluding Agent 1, all code paths disjoint. Agent 7 not staffed. Single remote main writer; no PRs or alternate branches. Pending CI cannot be fabricated as PASS; late first failures must be assessed by Agent 1.

## Round 016 — CLOSED_SOURCE_INTEGRATED_CI_PARTIAL_KUNIT_CONFIG_FAIL

[Final source and first-failure report](round016/round-report.md), [verbatim Agent 2+3 reports](round016/original-report-archive.md), [issue #133](https://github.com/k1moradi/swapz/issues/133). Both true worker source commits integrated on main at [b26c42d1ea7524a78747eafc431e35a1d1e94d35](https://github.com/k1moradi/swapz/commit/b26c42d1ea7524a78747eafc431e35a1d1e94d35), preserving concurrent independent main changes. Source/static rootless and production C PASS. Actual pinned KUnit #43842886936 FAIL at `verify_uml_config malformed-config-entry` after valid typed object inventory and UML command exit 0; y/n five-case TAP NOT VERIFIED; matched module/native/package PENDING at source close. Phase A BLOCKED; Phase B RAW and compressed direct handoff DISABLED.

## Round 017 — two direct-main implementation tasks, official ROUND_OPEN required

[Issue #134](https://github.com/k1moradi/swapz/issues/134); [joint ownership & safe main workflow](round017/README.md); [Agent 2 reproducible real UML config-parser first failure](round017/agent2-kunit-config-evidence.md); [Agent 3 executable DM origin+4096 owned-RAM readback qualification](round017/agent3-dm-owned-ram-readback.md); [short worker notification](round017/notification.md). Two independent workers excluding Agent 1, zero peer dependencies, all agents use ONLY local/remote main and non-force fast-forward publication with reconciliation of unpublished changes. Disjoint source and per-agent evidence paths. Round 017 establishes Phase A prerequisites; no compressed RAW reinterpretation or scheduling competition with zswap.

## Round 017 — CLOSED_SOURCE_INTEGRATED_ROOTLESS_CI_PASS_KUNIT_FAIL_OWNER_PHYSICAL_FAIL

[Accountable Agent 1 source/CI/owner-test report](round017/round-report.md), [original Agent 2/3 reports](round017/original-report-archive.md), [official issue #134](https://github.com/k1moradi/swapz/issues/134). Two real Round017 direct-main worker source commits `f7d754e1022c6f64dd986c8ba248bb86d43e35ef` and `cd5a18fb44b61a38676806414f8ffe00b9543b9a` preserved; current 9ecb5cc rootless/static/native/package/production-C CI PASS. Real pinned KUnit #43860358473 FAIL: effective CONFIG_BLK_CGROUP=n omitted under disabled CGROUPS; y/n five-case TAP not proven. Owner local `make test` on exact source 9ecb5cc: RAM 5/5 PASS, authorized physical anonymous-workload `producer_refused` FAIL with underlying first cause unavailable in attached console, cleanup/recovery reported PASS. Phase A BLOCKED, Phase B and direct handoff DISABLED. No production/physical qualification claimed.

## Round 018 — two first-failure source engineering tasks, unique ROUND_OPEN required

[Issue #135](https://github.com/k1moradi/swapz/issues/135), [joint direct-main and ownership contract](round018/README.md), [Agent 2 real pinned KUnit BLK_CGROUP missing dependent-symbol gate](round018/agent2-pinned-kunit-cgroup-dependency.md), [Agent 4 physical anonymous workload producer first-cause diagnostic executable fix](round018/agent4-physical-workload-producer-refusal.md), [ready notification text](round018/notification.md). Two workers excluding Agent 1, disjoint code ownership, no peer waits, main-only non-force publication, mandatory independent append-only standards co-changes. No new physical run before actual private first-cause review; no assumption that compressed zswap bytes are current RAW.

## Round 018 — CLOSED_SOURCE_INTEGRATED_CI_5PASS_KUNIT_TAP_CAPTURE_FAIL_PHYSICAL_SLOT_RELEASE_UNQUALIFIED

[Agent1 source/CI/owner trial closeout](round018/round-report.md); [verbatim original worker reports](round018/original-report-archive.md); [issue #135](https://github.com/k1moradi/swapz/issues/135). Main-only worker chain cf49aec (Agent4 slot timeout), d623a3c (Agent2 Kconfig dependency), 0008e649 (Agent4 terminal oracle); final exact-source native/rootless/static/productionC/package 5/5 workflows PASS. Actual pinned Linux KUnit #43876402555 FAIL with first phase `capture_real_tap` because later `run_checked verify_uml_config` overwrites shared `$log`; config and four object SHA checks PASS, five-case y/n TAP NOT VERIFIED. Owner-authorized local older-source physical trial FAIL at 30s swap-slot release baseline; first textual error now known, which counter remained nonzero/why UNKNOWN, recovery reported complete. No new device trial or genuine loaded zswap-origin READ. Phase A BLOCKED; Phase B RAW/compressed direct handoff DISABLED.

## Round 019 — two independent main-only source/test tasks, official ROUND_OPEN required

[Issue #136](https://github.com/k1moradi/swapz/issues/136), [joint source/workflow contract](round019/README.md), [Agent2 authentic UML KUnit TAP lifetime](round019/agent2-authentic-uml-tap-capture.md), [Agent4 fail-closed swap-slot release accounting](round019/agent4-swap-slot-release-lifetime.md), [short worker notification](round019/notification.md). Exactly 2 workers excluding Agent1, disjoint implementation, concurrent main-only non-force publication, preserve all standards appendices. No physical swap run required/authorized. zswap compressed RAM remains separate from swapz storage; do not reinterpret full uncompressed 4096 RAW as compressed zswap payload.

## Round 019 — CLOSED_SOURCE_KUNIT_Y_N_5_CASE_PASS_MATCHED_MODULE_BUILD_PASS_RUNTIME_BLOCKED

[Verified Agent1 report](round019/round-report.md), [original worker REPORT_READY bodies](round019/original-report-archive.md), [issue #136](https://github.com/k1moradi/swapz/issues/136). Actual main worker chain aed19172 → 01edd17 → 5a54657. Exact real pinned-Linux BIO KUnit #43897628379 on 01edd17: both distinct CONFIG_ZSWAP=y/n UML profiles five real unique no-skip cases PASS each (10 accepted executions total), full source/config/object SHA checks and final pair PASS. Exact matched module build #43897628284 PASS, build only. Final 5a54657 five rootless/source/native/package CI runs PASS. Actual stored zswap entry eviction to loaded DM and byte-exact 4096 Linux swap-in NOT_RUN. Owner physical slot-release original 30s timeout underlying cause unknown; new reporting physical NOT_RUN. Phase A BLOCKED; Phase B RAW/direct compressed DISABLED.

## Round 020 — two disjoint direct-main genuine stored origin and readback tasks, official ROUND_OPEN required

[Issue #137](https://github.com/k1moradi/swapz/issues/137), [joint safe main-only contract](round020/README.md), [Agent2 original zswap stored-entry producer causality](round020/agent2-stored-entry-producer-causality.md), [Agent3 matched loaded-DM/4096-byte owned RAM readback qualification](round020/agent3-matched-loaded-ram-readback.md), [short simultaneous-start notification](round020/notification.md). Exactly 2 workers excluding Agent1; distinct producer vs consumer source/testing, no peer waits or device requirement to start, append independent standards sections, non-force main fast-forward only, zero PRs/branches. No compression/RAW changes before actual authenticated loaded readback.

## Round020 — CLOSED_SOURCE_INTEGRATED_CI_PASS_NEW_OWNER_PHYSICAL_SWAP_ATTRIBUTION_FAIL

[Agent1 accountable source/CI/owner-log report](round020/round-report.md), [original Agent2 and Agent3 reports](round020/original-report-archive.md), [official issue #137](https://github.com/k1moradi/swapz/issues/137). One-branch main-only worker commits c023ecbf (exact pinned producer function body compiler-executed fixtures, all seven source-linked CI PASS including real pinned Linux y/n KUnit and matched module build) and c7399664 (loaded candidate read-only refusal, exact-one upper success, all six exact SHA CI PASS); no loaded real compressed stored-entry to DM/writeback/4096 swap-in. NEW user local make test on ownerSource de5bc09e80484c60d003e860732ecb736a6c2f0b: 5/5 RAM algorithm PASS; authorized physical trial FAIL phase anonymous_workload check bounded_primary_workload reason swap_attribution; owner reports recovery COMPLETE, real counters/private log unknown and distinct from earlier slot-release timeout. Phase A BLOCKED and Phase B RAW/direct compressed DISABLED.

## Round021 — two independent main-only source tasks, official ROUND_OPEN required

[Issue #138](https://github.com/k1moradi/swapz/issues/138), [joint source/ownership/safety](round021/README.md), [Agent4 actual cgroup-vs-mapper attribution first-failure source test](round021/agent4-exact-swap-attribution-first-cause.md), [Agent3 independently authenticated read-only loaded kernel/DM/4096 readback evidence](round021/agent3-boot-module-owned-ram-proof.md), [copyable start notification](round021/notification.md). Exactly 2 workers excluding Agent1, disjoint executable files and peer-independent starts, separate append-only testing standards sections, only main non-force FF, zero branches/PR. make fast_test is null_blk development profiling requiring sudo, not direct physical swap attribution validation; use targeted rootless first. Do not re-run owner physical without first-cause and recovery review.

## Round021 — CLOSED_SOURCE_INTEGRATED_5_CI_SUCCESS_ONE_LINKED_BUILD_RUNNING_RUNTIME_BLOCKED

[Accountable report](round021/round-report.md), [original 3 worker reports](round021/original-report-archive.md), [issue #138](https://github.com/k1moradi/swapz/issues/138). Worker main chain 8a4485d (Agent4 report parser fix), 72e50d6 (Agent4 guarded physical attribution source hardening), bac045b (Agent3 fixed-path read-only boot/module negative evidence). Exact native/production-C/package/private/rootless five final engineering source CI SUCCESS, modified pinned Linux plus matched module Kbuild CI #43923726108 IN_PROGRESS at frozen closeout poll; do not claim its completion. Owner physical source older de5bc09e: 5/5 RAM stage PASS, physical FAIL swap_attribution, original private counters UNKNOWN and recovery reported COMPLETE; no rerun. Physical/loaded zswap-to-DM original 4096 readback NOT_RUN. Phase A BLOCKED, Phase B forced RAW bypass and direct compressed transport DISABLED.

## Approved zswap+swapz SWAPSPACE2 cooperation contract (November 16, 2026)

[Owner-approved architectural requirements](architecture-requirements.md): small configurable zswap compressed-RAM cache retains useful pages until kernel eviction. Genuine stored zswap compressed LZ4 bytes should pass unchanged to a distinctly tagged, RAM-described compressed SWAPSPACE2 backing payload with matching swapz decompression to original full 4096 on disk read. Ordinary pages use swapz fast LZ4/delta64/SHUF8 and RAW original 4096 fallback. Existing RAW never means compressed, must not be reinterpreted. Existing valid SWAPSPACE2 partition original 4096 header, UUID/table preserved, metadata all volatile RAM, physical payload-only. Real loaded proof and codec ownership/integrity needed before activation; disabled prototypes remain disabled.

## Round022 — two parallel independent compressed-tier producer/consumer source tracks, official ROUND_OPEN required

[Issue #139](https://github.com/k1moradi/swapz/issues/139), [joint disjoint ownership/main-only contract](round022/README.md), [Agent2 pinned zswap compressed producer](round022/agent2-compressed-zswap-producer.md), [Agent3 swapz distinct compressed LZ4 decoder and 4096 readback](round022/agent3-compressed-swapz-consumer.md), [short notification](round022/notification.md). Exactly 2 workers excluding Agent1; direct-only main non-force expected-head FF, append own different testing standards sections, neither needs peer or owner device to start. No `make test` or `make fast_test` required from owner for source-only Round022; targeted rootless C/Python first.
