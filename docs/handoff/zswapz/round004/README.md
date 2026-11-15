# Round 004 — native status parser robustness and real pinned Linux Kbuild readiness

**Round:** 004. **Starts only on the unique `message: ROUND_OPEN` GitHub issue comment.**
**Issue mailbox:** [#121](https://github.com/k1moradi/swapz/issues/121)
**Frozen `swapz/main` source baseline:** `f9f65369c2dba65797989e10374e2350d58d25c2`.
**Staffing:** Agent 1 (coordinator and sole remote `main` publisher) + two **simultaneous, independent engineering workers: Agents 5 and 8**.

## Both assignments are feasible without additional authorization

Round 003's actual C source and source-bound negative tests are integrated, with [x86_64 and ARM64 hosted full-source tests passing](https://github.com/k1moradi/swapz/actions/runs/43722765004). However the producer is not integrated: Linux source from `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` can be checked out fully on GitHub Actions, but no owner-approved durable writable Linux source repository exists. Agent 2 therefore **is not assigned** and must not be re-dispatched to `BLOCKED_PUBLISH`.

The two Round 004 tasks improve existing code quality and kernel-build reproducibility using only established `swapz/main` + hosted public source access:

| Worker | Actual source owned | Final task |
| --- | --- | --- |
| [Agent 5](agent5-native-provenance-parser-adversarial-tests.md) | Existing native C test `tests/runtime/native/userspace/swapzctl-status.c` | Real compiled production-parser adversarial and negative-path tests |
| [Agent 8](agent8-pinned-linux-kbuild-source-matrix.md) | Existing `.github/workflows/phase-a-linux-source-preflight.yml` | Real Linux Kbuild `CONFIG_ZSWAP=y/n` source-object matrix and bounded CI evidence |

**Independence:** Both begin from `f9f65369c2dba65797989e10374e2350d58d25c2`. Agent 5 tests the already committed `src/userspace/swapzctl.c` using an existing native compiled C fixture; Agent 8 works in hosted Linux source checkout and existing read-only CI workflow. They never consume each other's Round 004 output and never touch one another's C/CI implementation files. Both need a narrow **same-commit, applicable `docs/testing_standards.md` update**. This shared documentation path has two distinct append-only sections (Agent 5 parser adversarial tests, Agent 8 pinned Linux Kbuild). Neither modifies the other section. Agent 1 merges these independent additive standard sections when publishing commits serially to `main`, preserving any intervening changes. Same-round progress needs no peer synchronization.

## Source-first, no patch-only submissions

Read `AGENTS.md`, `docs/AGENT_CONTEXT.md`, `docs/coding_standards.md` and `docs/testing_standards.md`. Preserve existing comments and APIs. Minimal focused edits, no refactors, descriptive identifiers, no heavy dependencies, bounded deterministic tests and failure-only diagnostics. No hot-path allocations/locks. Workers directly edit the actual owned C/CI/test source and the governing test standard, run every available test, and create a **retrievable full Git source commit object anchored at frozen source `f9f65369c2dba65797989e10374e2350d58d25c2`**. A pasted diff/`.patch`/design report does not qualify. A Git commit object alone is not published `main` integration: **Agent 1 alone** reviews, tests, non-force publishes to `main` with expected-head check, and verifies CI. No branches, PRs, forks, force pushes or secondary worktrees.

Each worker posts exactly one primary `message: REPORT_READY` to issue #121 with agent/task IDs, exact source commit, owned file list, actual commands/exits, compiler/architecture, first failure and `NOT_RUN`/blocked limits. One worker may finish before another; neither waits for another worker. All tests must state their evidence class. Agent 1 archives reports and closes the round only with honest bounded outcomes.

**Safety:** Neither task may modify or publish `torvalds/linux`, load a module, create or mutate a mapper/swap, exercise real memory pressure, touch physical storage, or enable Phase B. Full-source Kbuild source objects do not prove a patched producer or runtime BIO ABI. Phase A remains BLOCKED and Phase B remains DEFERRED.
