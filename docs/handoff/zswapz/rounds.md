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

## Round 007 — FINAL frozen worker prompts (start only after ROUND_OPEN)

| Round | Provisional planning source | Issue | Proposed independent workers | Start gate |
| --- | --- | --- | --- | --- |
| [007](round007/FINAL.md) | `45a3e8e911e447d9807f786ca33e14eac99374f8` | [#124](https://github.com/k1moradi/swapz/issues/124) | Agent 3 known `Module.symvers` linked-module CI repair; Agent 6 executable CI evidence integrity negatives | Round 006 CLOSED_INCOMPLETE; final task SHA published; unique `ROUND_OPEN` is execution authority |

The [final task package](round007/FINAL.md) supersedes the preserved historical DRAFT prompts without retroactively authorizing Agent 6's pre-opening report. Round 006 was explicitly [CLOSED_INCOMPLETE](round006/round-report.md): Agent 8 LLVM build PASS, Agent 7 NOT_DELIVERED. Both Round 007 agents start simultaneously from frozen `45a3e8e911e447d9807f786ca33e14eac99374f8` only after the unique `ROUND_OPEN` in #124. No peer result or upstream writable Linux source repository is required.
