# AGENTS.md — Mandatory swapz agent entry point

**Immutable naming policy (read before every prompt):** The project is `swapz`;
the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the
Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`.
**Never rename or version-suffix these public identities** (for example to
`swapz3`, `dm-swapz3`, or any other replacement). Enforce the same names
in production kernel C, Kbuild/DKMS, DM tables, test harnesses, benchmarks,
CI and documentation, before every agent change. Version numbers belong in
release metadata and source paths, not the project/module/target name. Keep
`SWZ3` as the distinct V3 on-disk format; the separate safe `swapz3ctl`
utility does not rename the project or module.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. This single public entry point runs native production-C/source/safety checks, W=1/W=2 builds, owned RAM-backed loaded correctness, and counterbalanced off/V3 throughput trials. It must report BLOCKED (nonzero) when noninteractive administrator permission or safe isolated devices are unavailable, never skip required loaded work while claiming a full PASS. **Do not create, publish, recommend, or document alternative test commands** (including additional Make goals, directly executed test scripts, one-off Python test invocations, and manually invoked loaded-device or benchmark helpers). Private implementation scripts/sub-Make targets and CI jobs may orchestrate individual stages internally, but are not supported operator interfaces; rootless-only CI success is explicitly partial.


This file applies to ChatGPT, Codex, Claude, Copilot and all coding agents.
It is a **bootstrap**, not a seventh independent source of engineering policy.

## Non-negotiable owner Make API

**Exactly four public root Make commands, with no exceptions or aliases:**
`make -j2` builds the V3 kernel module and supported safe binary in
parallel; `make install` installs its versioned DKMS package and binary
to appropriate system locations, without loading or activating swap;
`make uninstall` reverses only that owned installation; and
`make test` runs native C, source/fixture/safety contracts,
W=1/W=2 kernel compilation, **then actual loaded owned-RAM smoke and
counterbalanced rate-limited off/V3 benchmark pairs**. No interactive
sudo is attempted: an ordinary user needs previously authorized
noninteractive privilege, otherwise the command exits BLOCKED (nonzero)
rather than misreporting a complete test. All previously exposed root targets such as
`verify`, `run`, `deploy`, `v3`, `clean`, `bench-*`
and `test-*` are **removed and must not be reintroduced**.
Internal Kbuild/native-suite targets do not count as public root commands.
Rootless CI runs `tools/test-rootless.sh` without device access; its PASS
is not loaded-device evidence. The full `make test` must never silently
skip a privileged qualification or prompt for a password: it reports
BLOCKED if safe owned RAM devices or noninteractive privilege are unavailable.

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
[active V3 roadmap](docs/ROADMAP.md); follow
[documentation guidelines](docs/coding_standards.md)
and track the active V3 work in [docs/ROADMAP.md](docs/ROADMAP.md).
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

The [historical Codex worklog](https://github.com/k1moradi/swapz/blob/abbdbce277938f3678a640af93ef066394b44606/docs/archive/v2.2/CODEX_VALIDATION.md),
[legacy V2.1 testing plan](https://github.com/k1moradi/swapz/blob/efc6a8b34c26f46419996578100b54841aa5c84c/docs/archive/v2.1/TESTING.md),
[current testing and release gates](docs/testing_standards.md),
[active V3 roadmap](docs/ROADMAP.md), archived scripts and old PRs
provide versioned details, **not competing current policy**.
The root `CODEX_VALIDATION.md` is a current agent bootstrap,
not the former historical worklog. Follow these six documents if old instructions
conflict about branches, build output, testing, or safety.

## Owner hold on installation until production safety

The owner will not execute `make install` or `make uninstall` before production-safety qualification. Keep their package semantics correct through rootless fake-DKMS lifecycle tests, but never run privileged installation, unloading, swap activation or uninstall on the owner's host without explicit future authorization. Install the read-only V3 `swapz3ctl`, not the V2 `swapzctl`; keep AUTOINSTALL disabled and preserve the exact four-command Make API. CI's mock package success is not a claim of system DKMS compatibility or production safety.

The root Makefile must reject explicitly invoked `make all` and multiple goals, even though `all` is the internal default recipe used by `make -j2`. Enforce this alongside the exact four-command policy in rootless tests and CI.
