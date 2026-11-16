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
