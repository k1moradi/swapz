# CLAUDE.md — Agent bootstrap

At the start of **every task**, read [AGENTS.md](AGENTS.md) and [README.md](README.md), [VISION.md](VISION.md), [coding_standards.md](docs/coding_standards.md), [testing_standards.md](docs/testing_standards.md), [compile.md](docs/compile.md), and [benchmark.md](docs/benchmark.md).
They govern the project; historical instructions do not override them.

**Only `main`**, no branches without explicit owner permission. More than
50% ongoing development effort on the Linux kernel module's **C code**.
All generated binaries/bytecode go in reused `~/swapz/build/`.
Update one of the four standards with every implementation commit,
preserve real test failures, and never reboot/touch active swap or physical
media. README and VISION remain the project entry and acceptance criteria.

Document placement, archiving and active tasks: [docs/INDEX.md](docs/INDEX.md),
[docs/DOCUMENTATION_GUIDELINES.md](docs/DOCUMENTATION_GUIDELINES.md),
and [docs/TODO.md](docs/TODO.md). Agent files must not duplicate policy.
