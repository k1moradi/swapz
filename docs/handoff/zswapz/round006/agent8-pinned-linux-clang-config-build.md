# Agent 8 — Round 006: independent LLVM/Clang pinned Linux source Kbuild matrix

**Task ID:** `agent8-pinned-linux-clang-config-build`
**Round mailbox:** https://github.com/k1moradi/swapz/issues/123
**Frozen `swapz/main`:** `47a793c1480556c075f23ecbe13a5b465d616916`.
**Read-only upstream:** `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`.
**Start:** immediately after unique Round 006 `ROUND_OPEN`, **in parallel with Agent 7**. No same-round dependency.

## Real source ownership and known working base

Edit actual existing workflow `.github/workflows/phase-a-linux-source-preflight.yml` plus an **additive, uniquely titled** `Round 006 independent pinned Linux Clang source Kbuild` section in `docs/testing_standards.md`. Agent 7 separately owns native C fixture and its own standards appendix; do not modify or consume it.

The existing workflow already verifies a [complete pinned public Linux source checkout](https://github.com/k1moradi/swapz/actions/runs/43726191654) and compiles real `CONFIG_ZSWAP=y/n` GCC swap/BIO objects. Round 005 expanded the existing GCC job to attempt an external `dm-swapz.ko` link; its own long-running job was **not yet qualified** at Round 005 closeout. **Your new Clang check must be an independent parallel GitHub Actions job**, not a command appended after the existing GCC external-module step. A failure in that GCC job may NOT skip your LLVM object-build proof.

## Actual CI workflow changes and acceptance

1. Add a bounded *separate job* in the existing workflow. Fetch the **exact full public Linux** revision with `actions/checkout@v4`, read-only token permissions, clean-source and required-file checks; do not vendor, patch, fork, push or modify the upstream tree.
2. In disposable runner, use pinned `clang`/`ld.lld`/LLVM toolchain identity from installed packages and Linux's own `LLVM=1` Kbuild (or exact equivalent supported by pinned tree). Install only bounded host build dependencies on runner, no installation/loading of kernel/module. Make separate out-of-tree `O=` configurations for **`CONFIG_SWAP=y` and `CONFIG_ZSWAP=y/n`**, verifying *effective* settings and `CONFIG_CC_IS_CLANG=y`; fail on Kconfig fallback.
3. Execute real targeted pinned source `mm/page_io.o`, `block/bio.o` under both profiles, and `mm/zswap.o` only when enabled. Use warning level `W=1`, bounded concurrency, accurate compiler+config/source hashes, non-empty object checks, original source cleanliness after build and per-profile first-failure manifests. Mark successful only when commands really exit zero. Do **not** require `vmlinux`, `Module.symvers` or prior GCC external-module success; those belong to separate bounded qualification.
4. Preserve existing GCC module-check workflow and artifact behavior, avoiding ABI renames. Keep new result as independent `LLVM_STOCK_SOURCE_OBJECT_KBUILD`, never authenticated producer, patched carrier, matched runtime ABI, KUnit, loaded or physical Phase A PASS. Upload only concise text evidence on failures too, and do not suppress a Clang/LLVM warning or error to produce green.
5. Check YAML syntax and embedded Bash parse/control paths when available, then commit actual workflow and standards. Since unreferenced commits do not trigger GitHub Actions, correctly report `SOURCE_READY_PENDING_COORDINATOR_CI` until Agent 1 publishes and a **real hosted exact-SHA run** completes. Preserve first failure evidence if LLVM version/kernel API differs.

## Source commit and GitHub report

Edit real files, create a retrievable Git tree/commit with parent `47a793c1480556c075f23ecbe13a5b465d616916` containing your full YAML source and distinct additive testing standard. **Do not update remote `main`**, create branch, PR, fork or worktree, or generate only a patch. Agent 1 is sole publisher and serially merges both appendices. Do not wait for Agent 7.

Submit one `message: REPORT_READY` in https://github.com/k1moradi/swapz/issues/123 with `round: "006"`, `agent: 8`, task ID, source object, actual tests/exits and evidence class. No kernel loading, mapper/swap or physical operation; Phase A still BLOCKED and Phase B disabled.
