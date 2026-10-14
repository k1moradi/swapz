# Codex validation — agent entry point

**Current instructions, not a new policy source.** Before every Codex task, read
[AGENTS.md](AGENTS.md), [README.md](README.md), [VISION.md](VISION.md),
[coding_standards.md](coding_standards.md),
[testing_standards.md](testing_standards.md), [compile.md](compile.md),
and [benchmark.md](benchmark.md), all from current `main`.

Work only on `main` unless the owner explicitly authorizes otherwise.
Never touch existing system swap, physical/unowned storage, or reboot.
Use `~/swapz/build/` and test actual V3 production kernel C before
drawing conclusions. Rootless success is not a loaded-kernel benchmark.
A code change must update the relevant governing standard in that commit.

**Historical Codex/V2.2 tester instructions and evidence** are preserved in
[docs/archive/v2.2/CODEX_VALIDATION.md](docs/archive/v2.2/CODEX_VALIDATION.md).
They are NOT current authorization, testing requirements, or a three-arm
V2.2 performance mandate. The only active comparison is off versus V3
under [benchmark.md](benchmark.md). See [documentation guidelines](docs/DOCUMENTATION_GUIDELINES.md).
