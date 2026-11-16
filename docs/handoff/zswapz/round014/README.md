# Round 014 — FINAL independent main-only engineering tasks

**Coordination:** [issue #131](https://github.com/k1moradi/swapz/issues/131). This task is legally executable only after one unique `message: ROUND_OPEN` comment with the **final task-publication commit SHA** and frozen code source below. Neither a draft issue nor a standalone prompt link starts work.

**Frozen actual engineering source:** `7b25f9c7734b82780f6a55021d4ac64ed5b194b6` (canonical sole remote `main` before task publication). **Exactly TWO workers excluding Agent 1: Agent 2 and Agent 4.** Start simultaneously, do not wait for other agent, another CI run, or a new physical host. Produce real source-controlled Git commits with sole parent `7b25f9c7734b82780f6a55021d4ac64ed5b194b6` without creating a branch, PR, fork or extra worktree; only Agent 1 advances shared remote `main` serially with non-force expected-head verification.

- [Agent 2 full prompt](agent2-kunit-uml-config-diagnostic-and-case-gate.md) — independently correct verified **real KUnit effective UML configuration refusal** without changing whether a failure is a failure.
- [Agent 4 full prompt](agent4-native-make-interface-rootless-failure.md) — independently diagnose and repair exact-source **rootless Make interface regression**, preserving Make CLI and safety.

### Zero peer dependencies and code scope

| Agent | Exclusive source/CI paths | Additive documentation |
| --- | --- | --- |
| Agent 2 | `.github/workflows/phase-a-zswap-origin-kunit.yml`, `tests/runtime/native/pinned-linux-zswap-origin-stage-test.py`, optionally a **new** adjacent `tests/runtime/native/pinned-linux-kunit-uml-config-test.py` if necessary | Only `## Round 014 — Agent 2 effective UML Kconfig...` in `docs/testing_standards.md` |
| Agent 4 | `tests/runtime/native/make-interface-test.py`, `tests/tools/product_goals.py` **only if first failure proves required**, `.github/workflows/project-goals.yml` **only if diagnostic path requires** | Only `## Round 014 — Agent 4 Make interface...` in `docs/testing_standards.md` |

The code/CI paths are disjoint. Both worker filesets must include a **meaningful, non-whitespace same-commit testing-standard section** per repository policy. Both independently append new, distinctly titled, standalone documentation blocks to the same original `docs/testing_standards.md` from the frozen parent. **They do not wait or share source changes; Agent 1 reconciles the two append-only blocks deterministically after serial source integration**. Never overwrite the other section or pretend these are non-overlapping path edits.

### Concrete evidence and safety

[Round 013 accountable source closeout](../round013/round-report.md): 2/2 official source commits integrated on `main`, Agent 6 `a2d12f3d→fb2c925e`, Agent 7 `181e007a→c3a26a12`. Exact `c3a26a` hosted production-C x86_64/ARM64 [#43821180590](https://github.com/k1moradi/swapz/actions/runs/43821180590) **PASS**, rootless physical evidence [#43821180658](https://github.com/k1moradi/swapz/actions/runs/43821180658) **PASS**, but native project-goal [#43821180667](https://github.com/k1moradi/swapz/actions/runs/43821180667) **FAIL** specifically in make-interface native/rootless tests while policy/source checks PASS. The owner made further descendant changes to RAM source-lease/physical tests, preserved; neither round-014 worker may revert them.

Host-backed modified source/KUnit [#43811904846](https://github.com/k1moradi/swapz/actions/runs/43811904846) [artifact #14200877458](https://github.com/k1moradi/swapz/actions/runs/43811904846/artifacts/14200877458): enabled y-profile `defconfig`, scripts, olddefconfig, prep, modified BIO/KUnit/zswap objects all built with exit=0, and UML `kunit.py` exited 0; however **`first_failure_phase=verify_uml_config`, `first_failure_exit=1`**, so execution of five unique passing cases in both profiles was *not* proven. Actual mismatch needs bounded option-by-option evidence. No assertion of real KUnit PASS.

Hosted matched modified Linux `CONFIG_ZSWAP=y/n` and linked `dm-swapz.ko` [#43812229446](https://github.com/k1moradi/swapz/actions/runs/43812229446) **PASS on its earlier exact source SHA**, not loaded matched zswap provenance runtime. No prior rootless or compile outcome qualifies real stored-entry authenticated MM→BIO→DM writeback and 4096-byte exact readback.

**All workers:** read `AGENTS.md`, `docs/AGENT_CONTEXT.md`, `docs/coding_standards.md`, `docs/testing_standards.md`. Make only actual minimal owned source changes and executable negative tests, preserve existing comments. Verify nonzero failure paths, concurrency/ownership and artifact boundaries, fixed PAGE_SIZE and Kconfig identities. No sudo, kernel module load, physical/swap/mapper/reclaim/IO operations, test fixture device I/O, direct `main` push or new remote branch/PR. Source must be committed and retrievable; submit a new post-open `message: REPORT_READY` on issue #131 with exact Git SHA, sole parent, owned paths, commands and measured exit status, source-bound mutation counts, first error and NOT_RUN limits. Agent 1 alone archives original reports SHA-256 and integrates in order. **Phase A BLOCKED; Phase B RAW bypass DISABLED.**
