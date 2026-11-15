# Agent 3 — Round 005: compile actual swapz module against pinned full Linux source

**Task ID:** `agent3-pinned-linux-consumer-module-kbuild`
**Round mailbox:** https://github.com/k1moradi/swapz/issues/122
**Frozen source SHA:** `8bdc02de109aa3df65b6f0d0c22d13a04703e9e4`
**Linux source:** `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`
**Start:** only after the unique Round 005 `ROUND_OPEN`; then begin **at the same time** as Agent 5 without waiting for it.

## Own actual CI source and no outside prerequisites

Own `.github/workflows/phase-a-linux-source-preflight.yml` plus an additive, specifically named `Round 005 matched-stock-Linux swapz module compile-only` section in `docs/testing_standards.md`. Do not edit the Agent 5 C fixture or its new standards section. The existing workflow already fetches the **full exact pinned public Linux source**, proves its clean SHA and compiles `mm/page_io.o` and `block/bio.o` under `CONFIG_ZSWAP=y/n`, plus `mm/zswap.o` when enabled. That real hosted run [#43726191654](https://github.com/k1moradi/swapz/actions/runs/43726191654) succeeded. Keep those gates and their evidence manifest; do **not** rebuild a new parallel workflow or vendor Linux into `swapz`.

## Required implementation

1. After successful existing source+Kconfig+MM/BIO object checks, extend **each** of the two independent out-of-tree Linux configurations to run actual Linux **external module Kbuild** of the current `swapz/src/kernel` Device Mapper module code, using the exact checked-out `linux-upstream` source and the corresponding `O=` build directory. Account for the existing `src/kernel/Makefile` staging/build-info contract, required `CONFIG_MODULES` and Device Mapper availability, and `modules_prepare` or other actual target prerequisites; verify effective config. Do not fake Kbuild by gcc-compiling snippets or using unrelated preinstalled headers.
2. Keep x86_64 hosted source build small: bounded `-j1..4`, specified `W=1` or `W=2`, source-derived compiler identity, fail-only logging and no unconditional suppressions. If the exact pinned Linux API exposes a real module compatibility failure, capture the first error, and if straightforward make a tightly scoped supported change in `src/kernel/dm-target.c` or the existing build metadata with a co-updated `docs/coding_standards.md`; do not modify that production source speculatively.
3. Separate **compile success** from warning-only, `modules_prepare` only, missing `Module.symvers` or unresolved external symbols. Verify the compiled `dm-swapz.ko` has a nonzero size and is sourced from the matching actual swapz files. A profile's PASS requires real completed Kbuild and no ignored exit code; do not treat an object-only build as a linked-module PASS.
4. Append per-profile bounded manifest fields for source SHA, swapz SHA, effective `CONFIG_ZSWAP` and DM/module flags, `.config` SHA-256, compiler, exact Kbuild command, exit code, output artifact size and error category. Retain upload **on failure**, extending the existing `phase-a-linux-source-preflight` artifact, without uploading the large kernel/module artifact or secrets.
5. No module loading, install, kernel boots, physical/real swap, DM activation, or positive BIO provenance claims. Stock Linux does not contain the proposed upstream authenticated origin helper. `origin_carrier_compiled=0` under stock headers is expected and remains UNKNOWN.

## Code/test/commit obligations

Directly edit and commit **actual source**; run local YAML/shell static/syntax tests and any reachable hosted equivalent. If you cannot run the hosted job from an unreferenced source object, submit the retrievable source commit and `SOURCE_READY_PENDING_COORDINATOR_CI`; Agent 1 integrates and triggers the existing push workflow. An inaccessible local Linux checkout does **not** preclude authoring and committing the real workflow. Do not mark Kbuild PASS until a hosted run for the exact integrated commit actually succeeds.

Source commit parent must be `8bdc02de109aa3df65b6f0d0c22d13a04703e9e4`; do not update remote `main`, create branches, forks, PRs or secondary worktrees. Change only your owned workflow, any rigorously necessary module compatibility source/build file, and your distinct canonical standard section. Real first-failure classification, `git diff --check` if a checkout exists, source identities and test exits required.

Post one primary `message: REPORT_READY` to issue #122 with `round: "005"`, `agent: 3`, task ID, source commit SHA, changed file identities, actual tests/exits, first failure, evidence class, missing qualification. No peer dependency. Phase A BLOCKED; Phase B disabled.
