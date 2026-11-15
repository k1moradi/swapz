# Round 001 — independent baseline and negative-path preparation

**Issue:** [#118 — concurrent mailbox](https://github.com/k1moradi/swapz/issues/118)  
**Status rule:** This round is *not executable* until Agent 1 posts `message: ROUND_OPEN` with the exact task-commit SHA. Issue creation and presence of these files alone are insufficient.  
**Frozen source baseline:** `c128ac32374a753a0b27ae0ebec67693355b1b55` (verified ancestor of the task-publication parent).  
**Input window:** Repository and historical coordination contracts already available when the round opens; no new peer result from this round is a prerequisite.  
**Expected result:** Seven accountable reports; not a green Phase A qualification.

## Pre-existing inputs

- [AGENTS.md](../../../../AGENTS.md), [AGENT_CONTEXT.md](../../../AGENT_CONTEXT.md), [VISION.md](../../../VISION.md), [compile](../../../compile.md), [benchmark](../../../benchmark.md), [ROADMAP](../../../ROADMAP.md) and existing source at the frozen baseline.
- Existing [origin coordination issue #116](https://github.com/k1moradi/swapz/issues/116) and [independent audit #117](https://github.com/k1moradi/swapz/issues/117), **as historical context**, not another Round 001 agent's output.
- The proposed Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8` provenance carrier is *source-reviewed only* and **not** a target-kernel choice. The prior Ubuntu `7.0.0-43-generic` CI header is *existing-module compile evidence only*. No positive producer/consumer candidate has been source-qualified.

## Tasks: seven independent workers

| Agent | Independent task | Frozen task file | Coordinator archive filename |
| --- | --- | --- | --- |
| 2 | Kernel options and source/config compatibility | [agent2-target-kernel-audit.md](agent2-target-kernel-audit.md) | `agent2-target-kernel-audit-report.md` |
| 3 | Real stock-header fallback/compile boundary | [agent3-stock-kernel-fallback.md](agent3-stock-kernel-fallback.md) | `agent3-stock-kernel-fallback-report.md` |
| 4 | Commit-side counter and reader contract | [agent4-accounting-contract.md](agent4-accounting-contract.md) | `agent4-accounting-contract-report.md` |
| 5 | Independent BIO ABI/clone/split mismatch audit | [agent5-bio-abi-safety.md](agent5-bio-abi-safety.md) | `agent5-bio-abi-safety-report.md` |
| 6 | Production-source negative-path fixtures | [agent6-phase-a-negative-tests.md](agent6-phase-a-negative-tests.md) | `agent6-phase-a-negative-tests-report.md` |
| 7 | Rootless passive collector/parser validation | [agent7-passive-collector-validation.md](agent7-passive-collector-validation.md) | `agent7-passive-collector-validation-report.md` |
| 8 | Exact build environment and CI provenance matrix | [agent8-kernel-build-matrix.md](agent8-kernel-build-matrix.md) | `agent8-kernel-build-matrix-report.md` |

**Cross-round dependency gate:** none of these tasks may require the Round 001 kernel recommendation, Agent 4 counter decision, Agent 5 verdict or any other same-round report. Positive-origin producers, linked consumer and loaded writeback move to **Round 002 or later** after Agent 1 pins one supported kernel and approves interfaces. Reports may conclude `BLOCKED` for unavailable build trees/host permission. They must still document verifiable work.

## Common acceptance and safety

All agents must report full SHA, exact source/command/exit code or `NOT_RUN`, evidence class and self-imposed scope. Agent 1 archives original report comment links and checks content hashes. No branches, PRs, secondary worktrees, forks, concurrent direct-main writers, unaudited kernel patching, privileged mapping, swapoff/swapon, null_blk insertion, active workloads, physical backing writes or production RAW bypass are authorized by this round. Phase A remains observability-only, default-unknown and zero behavior changes; Phase B remains separately gated. Production acceptance remains BLOCKED until actual matched producer/BIO/DM tests and real zswap writeback on an owner-qualified test target.
