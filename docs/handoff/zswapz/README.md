# zswapz — Round Protocol v1

This namespace is the durable, additive coordination ledger for the planned zswap-origin work in [swapz](../../../README.md). It is **not** a new product, source branch, test entry point, or deployment authorization. Preserve every existing file in `docs/handoff/`; prior evidence remains historical and source-bound.

**Current owner-approved target (2026-11-16):** [zswap + swapz SWAPSPACE2 compressed-tier cooperative requirements](architecture-requirements.md). This newer owner contract supersedes any historical wording that implies ordinary RAW can contain compressed bytes, that the physical SWAPSPACE2 header is rewritten, or that the source-level zswap-origin BIO flag already transports compressed data. Old Round002-specific writer examples below remain historical; each new official ROUND_OPEN freezes current **main-only, non-force expected-head** worker assignments and publication contract. Phase A BLOCKED, Phase B RAW bypass and direct compressed transfer DISABLED until actual loaded original 4096 readback.

## Authority and roles

Read [AGENTS.md](../../../AGENTS.md), [AGENT_CONTEXT.md](../../AGENT_CONTEXT.md), [VISION.md](../../VISION.md), [testing standards](../../testing_standards.md) and the [zswap roadmap](../../ROADMAP.md#mm-aware-storage-blueprint-zswap-collaboration-and-locality). These policies override any example below. Only `main` is a permissible swapz development branch. **No PRs, secondary worktrees, forks or feature branches.** At most **one designated writer for `swapz/main`** may publish at a time using rechecked, tested non-force fast-forward commits; the coordinator owns task/report archival outside the implementation writer's lease. The owner can authorize a different writer. In **Round 002 the owner has directed agents to edit code rather than generate patch artifacts**, so Agent 3 is the sole authorized swapz source-code publisher during its recorded writing lease; Agent 1 must not push while this lease is active. Agent 2 works independently in an external pinned upstream Linux source checkout and cannot publish to `torvalds/linux` without separate legitimate write authorization. Neither agent creates a branch/PR/fork/worktree. See [Round 002 source-edit correction](round002/source-edit-correction.md).

Agents report through **GitHub issue comments**, but implementation tasks must first **change the actual source tree, compile and test the modified code, and publish their source commit where authorized**. A pasted patch or status report is not an implementation deliverable. Main publishing is serialized by the single active writer, not prohibited for the assigned implementation author. Agent 3 retains sole authoring ownership of `src/kernel/dm-target.c` for any separately authorized production integration; Agent 4 proposes counter contracts, Agent 5 independently audits, Agent 6 tests, Agent 7 collects passive evidence, Agent 8 qualifies. A task file is a review/work assignment, not permission for kernel, mapper, swap, or physical operations.

## Immutable dependency-layer rule

**Every Round N task must be executable using inputs that existed before that round opened; it cannot require a result from any other Round N task.** The coordinator rejects tasks that violate this rule before publication. Source code and existing issue comments may be reviewed in parallel; later comments from peers are nonbinding optional context. Missing target kernel, credentials, hardware, headers or permission produce a useful `BLOCKED` report; workers do not wait on one another.

Each task fixes a full 40-character `baseline_sha`, an issue URL, a distinct `task_id`, sources, allowed local changes, objective, verifiable acceptance, evidence boundaries and report name. The round's immutable **task commit** is supplied by a later `ROUND_OPEN` comment; task files cannot contain their own Git commit hash. New `main` descendants do not silently change the round's source baseline.

## Open, execute, collect, archive

1. **Issue first.** Create one `[zswapz][roundNNN]` issue with `PREPARING — NOT OPEN FOR EXECUTION`, a fixed baseline and its task IDs. A duplicate issue is not created.
2. **Publish all inputs atomically.** Coordinator validates task independence, then commits protocol/index/round README/all prompts as one new descendant of canonical `main`, after checking the policy and current remote ref. Use non-force ref update and expected-head lease; stop if remote advances or refuses.
3. **Open only by comment.** Verify canonical `main` matches the task commit; post `message: ROUND_OPEN` with exact task commit SHA and a permalink to this index. No agent begins from a draft issue alone.
4. **Parallel execution.** Every worker uses the frozen source baseline and task, edits actual owned source files for implementation tasks, runs safe tests, and posts its full report in the round issue. Only the designated writer may publish to `swapz/main` while its lease is active; no concurrent pushes. Hardware/loaded/device work remains governed by separate technical gates, not by the ability to edit source. Each report begins with `message: REPORT_READY` and may declare task status `PASS`, `FAIL` or `BLOCKED`. A PASS is limited to its evidence class, never Phase A or deployment acceptance. If the report exceeds a comment limit, post numbered continuation comments with cross-links.
5. **Archive after code handoff.** The implementation writer releases the main-write lease after publishing/verifying its code commit (or reporting a concrete blocker); only then does the coordinator resume main publication. Coordinator verifies committed modified files, source identity, exact commands/exits, evidence scope and original issue-comment link. Publish one task-matched `*-report.md` per worker plus `round-report.md` in a serialized direct-main commit. Link original comments; preserve content and explain discrepancies, never invent a result. Close the issue only after all assigned tasks have an accountable outcome (including `FAIL`/`BLOCKED`).
6. **Advance dependencies.** A new round opens only after the prior integrated report identifies ready next-layer tasks. Completed task prompts and reports are immutable except additive, dated correction records; do not rewrite earlier findings.

## Report format and safety

The round issue accepts one completion message per agent with this header followed by the **complete Markdown report**:

```yaml
message: REPORT_READY
round: "001"
agent: 7
task_id: agent7-passive-collector-validation
status: PASS | FAIL | BLOCKED
source_sha: <40-character SHA>
modified_files: []
tests:
  - command: <exact command>
    exit_code: <integer or NOT_RUN>
evidence_class: source-review | rootless | loaded | physical
blocking_findings: []
next_round_recommendations: []
```

The report must link exact source commits and changed source files when applicable, and state host/kernel/config/source versions when relevant, first failure, PASS/NOT_RUN/BLOCKED distinctions, and limitations. A diff may be generated as a review aid but **does not replace edited, tested source**. The applicable `docs/coding_standards.md` change-discipline rule (working `main`, same-commit governing standard update, non-force push, SHA verification) takes precedence over older prompt wording. Do not post secrets, machine IDs, precise private device identity, raw host paths or sensitive logs. Do not rely on editable comments as immutable digests: archived reports record the comment permalink and a reproducible content SHA-256 plus archival date. Work only on authorized targets; no synthetic source-only test is a genuine zswap writeback.

**Current milestone:** observable, authenticated `ZSWAP_STORED_WRITEBACK` at the 4 KiB DM boundary with identical compression/authority and byte-exact readback. The exact kernel/BIO carrier is not approved or integrated. Phase B RAW bypass, Phase C performance promotion, and Phase D research remain out of scope. See [round index](rounds.md).
