# Round 008 Agent 8 — in-run artifact integrity: accountable report

- **Source commit:** [`573f4d07648717e404f521f835d6fdbb8e7e2864`](https://github.com/k1moradi/swapz/commit/573f4d07648717e404f521f835d6fdbb8e7e2864), frozen parent `af334b3408b9a660fc7f4b15d82d8e5a9e6374bb`.
- **Original GitHub `REPORT_READY`:** [comment 6902863503](https://github.com/k1moradi/swapz/issues/125#issuecomment-6902863503); [verbatim body](agent8-original-report.txt), [SHA-256 archive](original-report-archive.md).
- **Owned actual code:** `tests/runtime/native/pinned-linux-artifact-integrity-test.py`, `.github/workflows/phase-a-linux-source-preflight.yml`, distinct `docs/testing_standards.md` appendix. Native offline 11/11 cases PASS as reported by worker.
- **Coordinator integration:** [`2b22016f7569aed1f9ba5863bbebd5ea99e898a5`](https://github.com/k1moradi/swapz/commit/2b22016f7569aed1f9ba5863bbebd5ea99e898a5).
- **Actual hosted verification:** [pinned Linux run #43773918173](https://github.com/k1moradi/swapz/actions/runs/43773918173): LLVM/Clang source-object job PASS, while GCC linked-module job FAILS earlier at `dm-target.c:71` due unresolved `SWAPZ_BUILD_SOURCE_CLEAN_STRING` in an independent generated header; **GCC verifier could not establish a linked artifact**.
- **Status:** `SOURCE_INTEGRATED_HOSTED_PARTIAL_GCC_FAIL`; no authenticated upstream zswap provenance production qualification.
