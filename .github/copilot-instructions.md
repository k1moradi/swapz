# Copilot instructions for swapz

**Read and obey [../AGENTS.md](../AGENTS.md) before changing source.**
The repository has **one branch only: `main`**.

1. **Never create/push a branch, branch-backed worktree or pull request**
   unless the user explicitly asks for an exception. Work directly on
   `main` with small, tested commits. Do not force-push, reset --hard,
   restore the entire worktree, or discard other agents' changes.
2. **Strict majority on the kernel module itself:** Spend **more
   than 50% of ongoing focused engineering time** developing, reviewing,
   debugging and profiling the actual production **kernel C** module:
   `kernel/dm-swapz.c`, `kernel/extent-v3/*.c`. Focus on BIO I/O,
   LZ4, GC, authority, concurrency, completion and lower-device request
   economics. C++ is appropriate for separately built native tests;
   it is not a Linux kernel module language. Do not count Python
   harness-building, documentation, or C++ test-only work as the kernel
   module development majority. Follow focused safety/correctness
   qualification even when it requires supporting tools.
3. Python/shell is allowed only when a thin, bounded, reproducible
   testing/fixture/CI script materially improves actual C/C++ validation.
4. Keep frozen V2.2 as the default build, V3 isolated and experimental;
   no physical backing, active swap, `swapoff`/`swapon` or reboot.
5. Measure verified identical 4KiB input/operation streams across
   off / V2.2 / V3, independent backing-device I/O bytes and requests,
   CPU and read p99. Report negative outcomes and unresolved gates.
6. Verify `main` checkout and preserve concurrent work before editing;
   run focused production-C, exact-source and build/safety CI and
   record exact commit SHA and results.

Old branch-oriented PR descriptions and historic validation instructions
are read-only provenance. `AGENTS.md` takes precedence.

**EVERY TASK:** Read current-main `VISION.md`, `V3_GOALS.md`,
`PRODUCTION_READINESS.md`, and `docs/BUILD_AND_TEST_CONVENTIONS.md`
at the start, and formulate the relevant project-goal correctness /
lower-I/O hypothesis. Reuse **only `~/swapz/build/`** for all compiled
artifacts and bytecode. Prefer reusable, behavior-named native-C test
suites; do not proliferate version-labeled test runners. After **every
implementation prompt** update relevant Markdown documentation in the
same commit, execute automated project-goal tests and report their
result. This is mandatory alongside the main-only / majority kernel C
rule, not a replacement for it.
