# Codex validation — agent entry point

**Current instructions, not a new policy source.** Before every Codex task, read
[AGENTS.md](AGENTS.md), [README.md](README.md), [VISION.md](VISION.md),
[coding_standards.md](docs/coding_standards.md),
[testing_standards.md](docs/testing_standards.md), [compile.md](docs/compile.md),
and [benchmark.md](docs/benchmark.md), all from current `main`.

Work only on `main` unless the owner explicitly authorizes otherwise.
Never touch existing system swap, physical/unowned storage, or reboot.
Use `~/swapz/build/` and test actual V3 production kernel C before
drawing conclusions. Rootless success is not a loaded-kernel benchmark.
A code change must update the relevant governing standard in that commit.

**Historical Codex/V2.2 tester instructions and evidence** are preserved in
[the original historical worklog](https://github.com/k1moradi/swapz/blob/abbdbce277938f3678a640af93ef066394b44606/docs/archive/v2.2/CODEX_VALIDATION.md).
They are NOT current authorization, testing requirements, or a three-arm
V2.2 performance mandate. The only active comparison is off versus V3
under [benchmark.md](docs/benchmark.md). See [documentation guidelines](docs/DOCUMENTATION_GUIDELINES.md).

**Mandatory Make interface (CI enforced):** The only public
root commands are `make -j2`, `make install`,
`make uninstall`, and `make test`. Never introduce
aliases or an additional Make target. Install/cleanup
is DKMS-version-owned; it must never activate swap,
load the module or ship retired V2 `swapzctl`.
`make test` performs all native and safe owned-RAM
loaded benchmarks, failing closed without sudo or
freshly owned RAM-backed null_blk. See
[AGENTS.md](AGENTS.md) and [compile.md](docs/compile.md).
