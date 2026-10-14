# Copilot instructions for swapz

**Read and obey [../AGENTS.md](../AGENTS.md) before changing source.**
The repository has **one branch only: `main`**.

1. **Never create/push a branch, branch-backed worktree or pull request**
   unless the user explicitly asks for an exception. Work directly on
   `main` with small, tested commits. Do not force-push, reset --hard,
   restore the entire worktree, or discard other agents' changes.
2. **C/C++ first:** Spend most engineering effort on production
   `kernel/dm-swapz.c`, `kernel/extent-v3/*.c` and directly executing
   C/C++ regression tests. Diagnose and fix concrete kernel I/O, LZ4,
   mapping-authority, GC, concurrency, completion and request-economics
   problems. Avoid replacing that work with new Python mock frameworks
   or extensive report-only changes.
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
