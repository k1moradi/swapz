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

## Round 003 — final independent worker tasks (start only at ROUND_OPEN)

| Round | Frozen swapz source | Coordination issue | Workers | Milestone |
| --- | --- | --- | --- | --- |
| [003](round003/README.md) | `15b98edef5d8b4e401d8c5e2c9a4d7a012100ff7` | [#120](https://github.com/k1moradi/swapz/issues/120) | Agent 4 existing swapzctl provenance reader; Agent 6 existing DM source-bound regression tests | Phase A BLOCKED; Phase B DEFERRED |

The authoritative `ROUND_OPEN` issue comment supplies the task-commit SHA. Earlier Round 003 draft tasks for Agents 2 and 3 were superseded **before opening**: no approved writable Linux source repo exists for Agent 2, and Agent 3's [pre-opening repair](https://github.com/k1moradi/swapz/issues/120#issuecomment-6894963968) is historical evidence, not a Round 003 completion. Both final workers can edit independent already committed swapz sources simultaneously; Agent 1 alone integrates verified source commits to `main` serially.
