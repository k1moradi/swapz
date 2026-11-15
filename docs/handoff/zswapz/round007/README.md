# Round 007 — DRAFT: genuine pinned GCC module-build repair and evidence integrity

**Status: PREPARING — NOT OPEN.** Only the unique `message: ROUND_OPEN` on [issue #124](https://github.com/k1moradi/swapz/issues/124) after Round 006 is formally closed authorizes workers to start.
**Provisional planning source:** `79bb7c0c8bdf055eaeecf81c0fa291d167bd0e61`. Agent 1 must revalidate the final source baseline and publish a final frozen task commit before opening.
**Staffing:** Agent 1 (coordinator, not a worker) + **two independent workers: Agents 3 and 6**.
**Purpose:** implement actual, bounded changes that need no patched Linux source, Linux repo permissions, loaded module or privileged devices.

## Existing, source-grounded failures and inputs

Round 005 source was integrated, but its [real pinned Linux GCC external-module run #43735000163](https://github.com/k1moradi/swapz/actions/runs/43735000163) failed: **`Full pinned kernel export table missing; no qualified external module link`** after the workflow's `vmlinux` command. Both profiles were NOT qualified. The [Round 005 Native rootless run #43735000085](https://github.com/k1moradi/swapz/actions/runs/43735000085) completed **PASS**. The confirmed GCC failure is a valid, existing target for a worker; no speculative failure needs to be invented.

Round 006 issue [#123](https://github.com/k1moradi/swapz/issues/123) remains OPEN: Agent 8's independent LLVM source implementation has been integrated but its hosted LLVM check is pending; Agent 7's original C source delivery has NOT arrived. These are **prior-round coordinator gates**; neither proposed Round 007 engineering task consumes Agent 7's new source, its report, or Round 006 LLVM execution output. **Do not open Round 007 until Round 006 is accounted for.**

## Proposed independent source-edit assignments

| Worker | Exclusive implementation source | Actual code deliverable |
| --- | --- | --- |
| [Agent 3](agent3-pinned-gcc-linked-module-qualification-repair.md) | Existing `.github/workflows/phase-a-linux-source-preflight.yml` (GCC job only) | Diagnose and fix first failed Kbuild export-table phase; obtain full real `dm-swapz.ko` y/n linked-module evidence on hosted CI, preserving independent LLVM job |
| [Agent 6](agent6-pinned-preflight-evidence-contract-tests.md) | New `tests/runtime/native/pinned-linux-preflight-evidence-test.py`, existing `.github/workflows/product-codec.yml` | Executable rootless adversarial manifest acceptance tests, wired into source-contract CI without touching the GCC or LLVM build workflow |

Each worker adds a **separately named append-only** applicable section to `docs/testing_standards.md` in the same source commit. This is their only shared path. Agent 1 serially merges both sections without overwriting other history; no worker relies on another's same-round output. The worker tasks depend on already committed pre-round sources only.

## Execution discipline after actual ROUND_OPEN

Workers must read `AGENTS.md`, `docs/AGENT_CONTEXT.md`, `docs/coding_standards.md` and `docs/testing_standards.md`. Edit **actual tracked YAML/Python source**, run real available syntax, source-contract and failure tests, and produce a **retrievable actual Git tree/commit** parented to the authoritative *final* frozen source. Not an issue-only diff, a patch-only artifact or an invented build PASS. If a worker cannot run hosted CI before its source is integrated, its report must say `SOURCE_READY_PENDING_COORDINATOR_CI`.

Only Agent 1 may update remote `swapz/main`, with non-force expected-head fast-forward and verified new source commits. No forks, branches, PRs, secondary worktrees or force pushes. Both workers may edit disjoint files **in parallel immediately after `ROUND_OPEN`**, without waiting for each other. Each posts one primary `message: REPORT_READY` to issue #124 with actual source commit SHA, commands/exits, first failed phase, evidence class and limitations. Agent 1 reviews real code, merges standards, runs hosted CI, archives verbatim reports with hashes and closes the round only with accountable outcomes.

**Evidence boundary:** A linked stock-header module is not a patched/authenticated upstream zswap stored-entry BIO origin producer. No kernel load, real swap/mapper, reclaim, device or physical testing. **Phase A BLOCKED; Phase B RAW bypass DISABLED.**
