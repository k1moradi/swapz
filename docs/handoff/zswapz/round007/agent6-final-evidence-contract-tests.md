# Agent 6 — FINAL Round 007: production-rootless Linux CI evidence claim negatives

**Task ID:** `agent6-pinned-preflight-evidence-contract-tests`
**Source baseline:** `45a3e8e911e447d9807f786ca33e14eac99374f8`
**Issue mailbox:** https://github.com/k1moradi/swapz/issues/124
**START:** only after the authoritative `ROUND_OPEN`; start **simultaneously with Agent 3**. No dependency on Agent 3's build changes or result.

## Reconcile real pre-opening candidate, then deliver fresh authorized source

An early implementation [`136e06f432370c93783dec93b59b56c56612fdef`](https://github.com/k1moradi/swapz/commit/136e06f432370c93783dec93b59b56c56612fdef) and [pre-opening issue report](https://github.com/k1moradi/swapz/issues/124#issuecomment-6899100424) exist, but were made under PREPARING from `79bb7c0c8bdf055eaeecf81c0fa291d167bd0e61`. They are **pre-opening, unqualified candidate material, NOT final task completion**. Re-inspect them and reconcile actual source bytes with the frozen `45a3e8e911e447d9807f786ca33e14eac99374f8`, without ignoring differences. Make a **new real source commit with parent exactly `45a3e8e911e447d9807f786ca33e14eac99374f8`** and a fresh **post-opening `REPORT_READY`**. No duplicate old comment, copied test results or diff-only report.

## Exclusive actual implementation source

1. Own `tests/runtime/native/pinned-linux-preflight-evidence-test.py` (real executable stdlib Python) and **existing** `.github/workflows/product-codec.yml` (add invocation to the existing full-source exact-C/source-contract job), plus a distinct, narrowly scoped additive `Round 007 pinned Linux evidence-contract negatives` section in `docs/testing_standards.md`. Do not edit Agent 3's pinned Linux preflight workflow; avoid any same-round dependence on new GCC manifest fields.
2. Implement/validate bounded deterministic **offline** key/value evidence grammar on the **pre-round schema**, covering UTF-8, duplicate/unknown claim-critical fields, negative/overflow module sizes, source SHA, actual effective `CONFIG_ZSWAP=y/n` and swapz identity, compiler/build command exits, module/export SHA-256, and false `result=PASS`. The GCC linked-module class requires nonzero canonical `module_bytes`, accurate module and `Module.symvers` hashes, all required successful stages and `module_linked=yes`. The LLVM object-only class may never imply a linked module. Distinguish the two profiles and evidence classes explicitly.
3. Preserve valid legacy/optional non-critical metadata without accepting contradictory claim-critical extensions. A valid self-made offline fixture is an **evidence grammar test, not verified host artifacts**; do not claim a forged SHA string authenticates an actual build. The real Linux module validation remains a separate hosted CI gate owned by Agent 1 after Agent 3's independent source integration.
4. Retest the **complete new frozen source**, including `python3 -B tests/runtime/native/pinned-linux-preflight-evidence-test.py -v`, `python3 -m py_compile`, exact committed file bytes and applicable full-source rootless tests if locally available. Record **measured** positive/negative case counts and exact Python version/exit statuses. The historical 50 negative/4 positive numbers from the pre-open candidate are **not** automatically requalified. Keep failure logging narrow and no network, large fixture, extra dependencies or privileged operations.
5. Make `.github/workflows/product-codec.yml` invoke the exact committed test source on both x86_64 and ARM64 under the already existing rootless source-contract stage. Preserve existing CI permissions, tools, public outputs and comments. Same-commit governing standard addition required. No product kernel/consumer hot-path changes.

## Commit/report rules

Create actual Git blob/tree/commit object parented at **`45a3e8e911e447d9807f786ca33e14eac99374f8`**, containing the real tested Python, existing workflow invocation and your independently additive testing standard (only). Do not update remote `main`, create PR/branch/fork/second worktree or await Agent 3. Post a fresh, **post-opening** `message: REPORT_READY` to https://github.com/k1moradi/swapz/issues/124, `round: "007"`, `agent: 6`, full task ID, real *new* source commit SHA, changed paths, actual tests/exits, counts and any `NOT_RUN` limits; distinguish previous report from new work. Agent 1 serially integrates source+standards and verifies actual hosted CI.

No Linux source modification, module/mapper/swap operation or physical device test; **Phase A BLOCKED, Phase B RAW bypass DISABLED**.
