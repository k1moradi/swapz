# Round 007 — FINAL frozen parallel source tasks

**Authority:** only the unique `message: ROUND_OPEN` comment in [issue #124](https://github.com/k1moradi/swapz/issues/124) with the exact final task-commit SHA.
**Frozen `swapz/main` *SOURCE* baseline:** `45a3e8e911e447d9807f786ca33e14eac99374f8`.
**Assigned workers:** **Agent 3 and Agent 6**, exactly **two workers excluding Agent 1 coordinator**. Both should start **simultaneously and independently** after ROUND_OPEN. No same-round peer code, tests or handoffs are prerequisites.
**Coordinator:** Agent 1 is the only authorized remote `main` writer; no branches, forks, PRs, second worktrees, force pushes.

## Valid pre-opening inputs

[Round 006 issue #123](https://github.com/k1moradi/swapz/issues/123#issuecomment-6899217875) is **CLOSED_INCOMPLETE**. Agent 8's real independent Linux LLVM source Kbuild [PASSED](https://github.com/k1moradi/swapz/actions/runs/43743100361) and was integrated; Agent 7's source/report was **NOT_DELIVERED**, not counted PASS, and its native observer task remains separately recorded as unfulfilled backlog. The previous-round result is accountable and does not block either independent Round 007 task.

The existing [pinned GCC run #43735000163](https://github.com/k1moradi/swapz/actions/runs/43735000163) **FAILED** after `vmlinux`, with explicit `Full pinned kernel export table missing; no qualified external module link`. [Native rootless #43735000085](https://github.com/k1moradi/swapz/actions/runs/43735000085) PASSED. The public pinned Linux source checkout and separate LLVM Kbuild run already work without additional repositories or privilege grants.

A preliminary Agent 6 source object [`136e06f432370c93783dec93b59b56c56612fdef`](https://github.com/k1moradi/swapz/commit/136e06f432370c93783dec93b59b56c56612fdef), with [pre-opening report](https://github.com/k1moradi/swapz/issues/124#issuecomment-6899100424), was created **during PREPARING** from earlier provisional source `79bb7c0c8bdf055eaeecf81c0fa291d167bd0e61`. Those real source bytes are reusable candidate engineering material, **not a post-opening assignment completion**. Agent 6 must reconcile them with `45a3e8e911e447d9807f786ca33e14eac99374f8`, run actual tests on the final source, create a new retrievable commit with **parent exactly `45a3e8e911e447d9807f786ca33e14eac99374f8`**, and post a **fresh post-ROUND_OPEN report**. A duplicate comment or old SHA is insufficient. Agent 3 is independent and starts at the same time.

## Parallel ownership and acceptance

| Agent | One exclusive actual implementation surface | Actual engineering deliverable |
| --- | --- | --- |
| [Agent 3 — final prompt](agent3-final-gcc-module-build-repair.md) | Existing `.github/workflows/phase-a-linux-source-preflight.yml`: GCC job only | Repair real `Module.symvers` first failure and require honest linked `dm-swapz.ko` source/build evidence for both `CONFIG_ZSWAP=y/n` (hosted CI after coordinator integration) |
| [Agent 6 — final prompt](agent6-final-evidence-contract-tests.md) | New `tests/runtime/native/pinned-linux-preflight-evidence-test.py` plus existing `.github/workflows/product-codec.yml` | Actual executable Python offline manifest-claim adversarial tests and CI wiring; review/port the provisional source without silently treating earlier tests as the final revision |

Only `docs/testing_standards.md` is shared: **each worker appends a differently titled governing section** in its own source commit, without rewriting the other's section or depending on peer work. Agent 1 applies these two additions serially on current `main` and verifies no intervening history is lost. If Agent 3 must fix a *confirmed* module C source defect, record it and provide the smallest safe source+coding-standard co-change; no speculative edits.

## Source-first workflow, CI evidence and safety

Read `AGENTS.md`, `docs/AGENT_CONTEXT.md`, `docs/coding_standards.md` and `docs/testing_standards.md`. Edit **actual tracked C/Python/YAML sources**, preserve comments and public APIs, use deterministic bounded test inputs and fail-only diagnostics, and produce an **actual retrievable Git blob/tree/commit object parented to `45a3e8e911e447d9807f786ca33e14eac99374f8`**. A diff pasted into an issue, patch file, prose plan or synthetic-only PASS is not an acceptable engineering delivery. Neither worker moves remote refs. If unable to run hosted CI from an unreferenced source object, mark `SOURCE_READY_PENDING_COORDINATOR_CI`, **not** PASS.

Each worker posts one **new post-opening** `message: REPORT_READY` to issue #124 with `round: "007"`, agent/task ID, frozen source, real new source commit SHA, owned modified paths, actual tested commands and exits, first failure, evidence class and `NOT_RUN` boundaries. Agent 1 inspects source, integrates via non-force expected-head fast-forward, verifies exact-source CI, archives original reports with hashes, and closes only with accountable outcomes.

No upstream Linux modification, fork or publication; no kernel/module installation/loading, actual swap/reclaim, mapper or physical devices. A stock Linux linked module or offline manifest check is **not** an authenticated zswap stored-entry MM→BIO provenance producer or positive runtime writeback/readback. **Phase A BLOCKED, Phase B RAW bypass DISABLED.**
