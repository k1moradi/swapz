# Round 005 — independent actual-source Linux module and provenance snapshot qualification

**Status:** starts only after the unique `message: ROUND_OPEN` in [issue #122](https://github.com/k1moradi/swapz/issues/122).
**Frozen `swapz/main` source:** `8bdc02de109aa3df65b6f0d0c22d13a04703e9e4`.
**Team:** Agent 1 (coordinator and sole remote-main integrator), plus **exactly TWO workers (Agents 3 and 5)** starting simultaneously and independently.
**Phase A:** BLOCKED on a committed authenticated upstream Linux producer and matched runtime evidence; Phase B RAW bypass disabled.

## Established unblocked prerequisites

Round 004 [closed](https://github.com/k1moradi/swapz/issues/121) with real C/CI source integrated and [pinned full Linux `CONFIG_ZSWAP=y/n` Kbuild PASS](https://github.com/k1moradi/swapz/actions/runs/43726191654) at upstream commit `c339f4010dea8b0d754f84ace70cd1b089878ef8`. A verified hosted source checkout already exists as a repeatable CI job; local agent DNS limitations do **not** prevent submitting real workflow edits or the coordinator testing them. [Native rootless #43726191538](https://github.com/k1moradi/swapz/actions/runs/43726191538) also passed the compiled userspace status fixture.

Neither worker needs a new repository, owner account changes, a patched Linux producer, another worker's outcome, direct kernel install/load or physical devices. Both tasks use frozen pre-round sources and existing CI/fixture affordances.

## Exactly two independent implementation tasks

| Worker | Exclusive real implementation source | Engineering outcome |
| --- | --- | --- |
| [Agent 3](agent3-pinned-linux-consumer-module-kbuild.md) | `.github/workflows/phase-a-linux-source-preflight.yml` | Extend real pinned Linux source CI to compile the **actual swapz DM module source**, under each verified `CONFIG_ZSWAP=y/n` profile, with fail-first manifest and no module loading |
| [Agent 5](agent5-double-info-origin-snapshot-races.md) | `tests/runtime/native/userspace/swapzctl-status.c` | Add real compiled parser+two-snapshot reader **provenance** race/retry/atomic-output tests, not a second isolated 372-case parsing matrix |

Both add a distinct, named *append-only* section to `docs/testing_standards.md` in their own source commit. This is the only common path; the independent additions require no peer coordination and Agent 1 must append both onto the latest `main` in serialized commits, preserving all intervening standards. No worker edits another worker's section.

## Code publication and verification

Read `AGENTS.md`, `docs/AGENT_CONTEXT.md`, `docs/coding_standards.md`, `docs/testing_standards.md`, applicable `docs/compile.md`. Directly **edit actual tracked source-controlled code and tests**, preserve existing comments/APIs, make minimal changes, execute real available checks and create a **retrievable Git blob/tree/commit object** parented at frozen `8bdc02de109aa3df65b6f0d0c22d13a04703e9e4`. A GitHub issue diff, hypothetical code block, only a test plan or a new standalone patch file is not the source deliverable.

**Agent 1 alone may advance remote `main`**, using non-force fast-forward verified expected-head updates, source/standard co-changes and hosted CI. Workers work concurrently on disjoint implementation files, do not move refs, create branches, PRs, forks or secondary worktrees, and do not await another worker. Report source readiness and bounded test limits honestly: `SOURCE_READY_PENDING_COORDINATOR_CI` is allowed if real code is committed but the worker lacks local checkout, **not** hosted PASS. A source-object commit is not yet on `main`.

One primary `message: REPORT_READY` per worker in issue #122: agent/task IDs, actual commit SHA, source identity, changed paths, exact commands/exit codes, first failure and untested gates. Agent 1 inspects, serially integrates, verifies CI, archives original reports with source links and hashes, and closes only with accountable outcomes.

**Safety/evidence:** No Linux upstream publication, kernel install/boot, loaded module, real zswap reclaim, swap/mapper mutation, physical device operations or Phase B changes. Stock Linux + stock-header DM module compile is **not** a modified authenticated MM→BIO producer or positive origin proof. If existing pinned kernel APIs reveal a genuine build incompatibility, record first failure and make only a focused warranted kernel-consumer compatibility fix with same-commit coding standard, never silently substitute an easier Linux revision.
