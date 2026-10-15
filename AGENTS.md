# AGENTS.md — Mandatory swapz agent entry point

This file applies to ChatGPT, Codex, Claude, Copilot and all coding agents.
It is a **bootstrap**, not a seventh independent source of engineering policy.

## Non-negotiable owner Make API

**Exactly four public root Make commands, with no exceptions or aliases:**
`make -j2` builds the V3 kernel module and supported safe binary in
parallel; `make install` installs its versioned DKMS package and binary
to appropriate system locations, without loading or activating swap;
`make uninstall` reverses only that owned installation; and
`make test` runs the full native, contract, loaded owned-RAM safety and
paired benchmark pipeline. All previously exposed root targets such as
`verify`, `run`, `deploy`, `v3`, `clean`, `bench-*`
and `test-*` are **removed and must not be reintroduced**.
Internal Kbuild/native-suite targets do not count as public root commands.
Tests that need privileges must block rather than silently skip them.

**Enforcement:** `tests/runtime/native/make-interface-test.py`
runs in the internal rootless script and in GitHub CI, checks the exact
four-target allowlist and safety boundaries, and rejects new aliases.
All AI agents must uphold that check and update this owner contract
whenever touching the build, installation, test or CI paths.
The obsolete V2 `swapzctl` must not be installed: it can call
`swapon` and `swapoff` on a backing device. V3 remains
experimental, DKMS `AUTOINSTALL="no"`, and installation does
not permit activation, physical devices or existing system swap.

## Read these six documents before EVERY task, from current `main`

1. [README.md](README.md) — project entry point and status
2. [VISION.md](VISION.md) — actual lower-I/O success criterion
3. [coding_standards.md](docs/coding_standards.md) — Git, kernel C, invariants, safety
4. [testing_standards.md](docs/testing_standards.md) — qualification and test contracts
5. [compile.md](docs/compile.md) — Make/Kbuild, one reused `~/swapz/build/`
6. [benchmark.md](docs/benchmark.md) — identical off/V3 data and real measurements

**Documentation:** Keep new plans and reports under
[docs/](docs/INDEX.md); follow
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

## Owner hold on installation until production safety

The owner will not execute `make install` or `make uninstall` before production-safety qualification. Keep their package semantics correct through rootless fake-DKMS lifecycle tests, but never run privileged installation, unloading, swap activation or uninstall on the owner's host without explicit future authorization. Install the read-only V3 `swapz3ctl`, not the V2 `swapzctl`; keep AUTOINSTALL disabled and preserve the exact four-command Make API. CI's mock package success is not a claim of system DKMS compatibility or production safety.

The root Makefile must reject explicitly invoked `make all` and multiple goals, even though `all` is the internal default recipe used by `make -j2`. Enforce this alongside the exact four-command policy in rootless tests and CI.
