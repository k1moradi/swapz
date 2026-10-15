# agent.md — Agent bootstrap

Before **every task**, read [AGENTS.md](AGENTS.md) and all six authoritative
documents: [README.md](README.md), [VISION.md](VISION.md), [coding_standards.md](docs/coding_standards.md), [testing_standards.md](docs/testing_standards.md), [compile.md](docs/compile.md), and [benchmark.md](docs/benchmark.md).

Only the existing `main` branch; strictly more than 50% of ongoing
development time on production **kernel C**; all compiled outputs within
one reused `~/swapz/build/`; never touch active swap or physical devices.
After each implementation, update a relevant one of the four standards
in the **same commit**, run automated goal-aligned tests, and report
exact SHA and remaining gaps. Do not invent additional policies here.

Use [docs/ROADMAP.md](docs/ROADMAP.md) and
[docs/coding_standards.md](docs/coding_standards.md)
for documentation routing; keep the current task queue in
[docs/ROADMAP.md](docs/ROADMAP.md), not in archival logs.

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
