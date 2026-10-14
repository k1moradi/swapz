# AGENTS.md — Mandatory swapz agent entry point

This file applies to ChatGPT, Codex, Claude, Copilot and all coding agents.
It is a **bootstrap**, not a seventh independent source of engineering policy.

## Read these six documents before EVERY task, from current `main`

1. [README.md](README.md) — project entry point and status
2. [VISION.md](VISION.md) — actual lower-I/O success criterion
3. [coding_standards.md](coding_standards.md) — Git, kernel C, invariants, safety
4. [testing_standards.md](testing_standards.md) — qualification and test contracts
5. [compile.md](compile.md) — Make/Kbuild, one reused `~/swapz/build/`
6. [benchmark.md](benchmark.md) — identical off/V3 data and real measurements

**Documentation:** Keep new plans and reports under
[docs/](docs/README.md); follow
[documentation guidelines](docs/DOCUMENTATION_GUIDELINES.md)
and track the active V3 work in [docs/TODO.md](docs/TODO.md).
Root agent instructions are pointers, not additional policy.
Historic unchecked V2.2 tasks are not current V3 requirements.

**Only `main`:** no new branches, branch-backed worktrees or draft PRs
unless the repository owner explicitly authorizes an exception. Never
discard another agent's work with reset --hard, broad restore, clean or
force-push. Commit small reviewed changes directly on main.

**Kernel-C-first:** devote strictly **more than 50% of ongoing development
engineering effort** to implementing, reviewing, debugging or profiling
the actual production Linux **kernel module in C**. Python, shell and
separately compiled C++ tests are supporting tools, not kernel code.

**One build root:** all generated compiled artifacts and Python bytecode
reside in the reused `~/swapz/build/` directory, with semantic subfolders.

**Every implementation prompt:** state the VISION hypothesis or correctness
benefit, run goal-aligned tests at the exact HEAD, and update a relevant
one of the four engineering standards **in the same commit** with the
new learning, real PASS/FAIL/BLOCKED, limitations and follow-up. Update
README for user-facing changes and VISION if acceptance criteria change.

**Host safety:** never reboot, `swapoff`, `swapon`, touch active
`/dev/sdb1` or `/swapfile`, physical/unowned storage, or unrelated DM.
V3 is the active default *development* build, but stays experimental and null_blk-only; V2.2 is retired from active benchmarks.

The [archived Codex worklog](docs/archive/v2.2/CODEX_VALIDATION.md),
[legacy V2.1 testing plan](docs/archive/v2.1/TESTING.md),
[dated production readiness ledger](docs/PRODUCTION_READINESS.md),
[active V3 roadmap](docs/ROADMAP.md), archived scripts and old PRs
provide versioned details, **not competing current policy**.
The root `CODEX_VALIDATION.md` is a current agent bootstrap,
not the former historical worklog. Follow these six documents if old instructions
conflict about branches, build output, testing, or safety.
