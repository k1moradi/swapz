message: REPORT_READY
round: "007"
agent: 3
task_id: agent3-pinned-gcc-linked-module-qualification-repair
status: SOURCE_READY_PENDING_COORDINATOR_CI
source_commit_sha: 22e88839459f3d8ccc4d7db6669bc57372a236bd
source_commit_url: https://github.com/k1moradi/swapz/commit/22e88839459f3d8ccc4d7db6669bc57372a236bd
source_baseline_sha: 45a3e8e911e447d9807f786ca33e14eac99374f8
task_commit_sha: c12aa8d15fb573994fe6039b80eda182a8c8dbfd
linux_source_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
workflow_blob_sha: 29043e4f701be62fd3877e7a7525dcd1e501ffef
testing_standards_blob_sha: eb7533a3cb6e985cd858d7db78d1b7bfa431841d
changed_files:
  - .github/workflows/phase-a-linux-source-preflight.yml
  - docs/testing_standards.md
evidence_class: retrievable-source-commit + rootless-structural-and-shell-gate
phase_a: BLOCKED
phase_b: DISABLED
remote_main_updated: false

# Agent 3 — final Round 007 GCC pinned-Linux external-module export-table repair

**Actual source commit:** https://github.com/k1moradi/swapz/commit/22e88839459f3d8ccc4d7db6669bc57372a236bd

## Verified first original failure and exact upstream build contract

The original [hosted GCC workflow run 43735000163](https://github.com/k1moradi/swapz/actions/runs/43735000163), job `132875529570`, exited **FAIL** after a successful same-tree `make ... vmlinux`: `Full pinned kernel export table missing; no qualified external module link`. The prior workflow did not actually call the in-tree `modules` target.

I inspected the exact frozen upstream [Linux 7.3 source at `c339f401...`](https://github.com/torvalds/linux/tree/c339f4010dea8b0d754f84ace70cd1b089878ef8), including `Makefile` and `scripts/Makefile.modpost`. `vmlinux` invokes `modpost` for the built-in output; a separate `modules` target exercises `KBUILD_MODULES` / `modules.order`, causing combined `Module.symvers` generation. `modules_prepare` alone is expressly insufficient to make the full export table.

## Actual edited source and scope

The existing `.github/workflows/phase-a-linux-source-preflight.yml` GCC job now executes, after its successful `vmlinux` phase and **before** its fail-closed `Module.symvers` validation:

```bash
run_logged kernel_export_modules make -s -C linux-upstream "O=$build_dir" CC=gcc \
  "-j$KBUILD_JOBS" "W=$KBUILD_WARNING_LEVEL" modules || exit $?
```

This adds only **five workflow lines (zero removed)**, including three comments; no new workflow or production C changes. It uses the same exact Linux checkout/config/compiler, bounded `-j4` and `W=1`, existing `run_logged` command/exit/first-failure manifest handling, and existing `always()` small artifact upload. A failed modules command cannot fall through to a false PASS. The existing missing/empty export-table guard, table hash, real source-staged external module Kbuild, nonempty `dm-swapz.ko` check, module warning count, source SHA checks and ZSWAP=y/n directories are retained. **The independent LLVM/Clang job is byte-for-byte identical** to the frozen baseline (whole job suffix comparison). There is one independent, uniquely titled, **24-line append-only** `Round 007 pinned GCC external-module export-table repair` section in `docs/testing_standards.md`.

**GitHub commit verification:** fetched commit has exactly one parent `45a3e8e911e447d9807f786ca33e14eac99374f8`; comparison shows one new commit, exactly the two owned paths; workflow blob `29043e4f701be62fd3877e7a7525dcd1e501ffef`; standard blob `eb7533a3cb6e985cd858d7db78d1b7bfa431841d`. Its real unified diff has no added trailing-whitespace lines. No branch/PR/fork/worktree was created; remote `main` was not advanced.

## Actually executed tests, commands and results

1. **Rootless source-coupled assertions against exact frozen GitHub workflow blob `96d0b93ca4f590e89bdff07ee44af211bf63cb4a`:** 12/12 PASS in connector-side JavaScript. Checked unique insertion, exact GCC prefix/suffix unchanged, entire LLVM job unchanged, `vmlinux`→`modules`→`verify_kernel_symvers` order, mandatory `Module.symvers` and nonempty `.ko` checks preserved, actual `swapz_module_kbuild`, artifact handling, no `KBUILD_MODPOST_WARN` or `KBUILD_MODPOST_NOFINAL` bypass and no unrelated changes. Modified workflow source committed/retrieved exactly.
2. **Local Bash syntax on the exact inserted `run_logged kernel_export_modules ... modules || exit $?` lines plus faithfully copied run-logged and symbol-table gate context:** `bash -n` **exit 0**.
3. **Rootless isolated GNU Make gate test:** Python 3 subprocess with a temporary `Makefile`, using the production command shape `make -s -C <temporary linux-upstream> O=<temporary build> CC=gcc -j4 W=1 modules` and no kernel/device operations:
   - Genuine nonempty mock-produced export text: exit **0**, manifest command/exit recorded and SHA-256 generated.
   - Missing `Module.symvers`: exit **1**, fail-closed, no success hash.
   - Make recipe error `exit 37`: GNU Make propagates actual process exit **2**, recorded `kernel_export_modules_exit_code=2`, no false success.
   - `bash -n` on the complete standalone test shell snippet: exit **0**. **4/4 rootless shell checks PASS**.
4. **Commit/diff/source-identity checks:** GitHub REST commit and compare **PASS** (one parent, two owned files); source-blob re-fetch **PASS**; added-line whitespace scan **PASS**.

**NOT_RUN:** full YAML parse and whole embedded workflow shell parse in a materialized local swapz checkout; full `git diff --check` in a local checkout; real pinned `CONFIG_ZSWAP=y/n` `make modules`; actual `Module.symvers` output; `dm-swapz.ko` compilation, modpost and linking; exact integrated hosted CI. This source-object commit is unreferenced by `main`, so no workflow was triggered for it. The mock tests are **not Linux Kbuild evidence**.

## First failure and coordinator integration

**First historical, confirmed hosted fatal error:** missing combined `Module.symvers` after successful `vmlinux` at run `43735000163`. **New hosted first failure:** UNKNOWN until the exact integrated run. The added `make modules` may reveal a new real kernel or swapz ABI/compiler error; it must remain visible and be addressed only from actual CI evidence, not suppressed.

Agent 1 should incorporate this retrievable source commit onto current `main` without overwriting Agent 6's separate tests or testing-standard appendix, then run the existing GitHub preflight at the exact integrated commit. Require both GCC ZSWAP profiles to pass the actual `kernel_export_modules`, nonempty kernel export-table and linked `dm-swapz.ko` checks before claiming compilation success. Independent LLVM object-only CI is unchanged.

**Engineering outcome:** real source repair committed, rootless checks PASS, **`SOURCE_READY_PENDING_COORDINATOR_CI`**, not full linked-module PASS. Stock Linux lacks the authenticated stored-entry origin producer; no kernel module load, mapper, active swap/reclaim, physical media or Phase B bypass operations occurred. Phase A **BLOCKED**, Phase B **DISABLED**.
