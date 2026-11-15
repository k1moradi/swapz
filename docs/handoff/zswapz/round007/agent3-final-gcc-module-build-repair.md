# Agent 3 — FINAL Round 007: repair confirmed pinned GCC linked-module Kbuild defect

**Task ID:** `agent3-pinned-gcc-linked-module-qualification-repair`
**Source baseline:** `45a3e8e911e447d9807f786ca33e14eac99374f8`
**Issue mailbox:** https://github.com/k1moradi/swapz/issues/124
**START:** only on the authoritative final `ROUND_OPEN` issue comment; start **simultaneously with Agent 6**. No peer dependencies.

## Modify actual owned source

1. Own `.github/workflows/phase-a-linux-source-preflight.yml` **GCC job only**, plus a **distinct append-only** `Round 007 pinned GCC external-module export-table repair` section in `docs/testing_standards.md` in the same Git source commit. Preserve the independent `pinned-upstream-clang-objects` job and its evidence byte-for-byte behaviorally. Do not modify Agent 6's Python or product-codec workflow.
2. The real [GitHub Actions run #43735000163](https://github.com/k1moradi/swapz/actions/runs/43735000163), [artifact 14169614803](https://github.com/k1moradi/swapz/actions/runs/43735000163/artifacts/14169614803), failed at the first fatal `Full pinned kernel export table missing; no qualified external module link` **after** the existing `vmlinux` Kbuild target. Confirm the actual exact pinned Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8` Make/Kconfig path that produces `Module.symvers` (not `vmlinux` alone), before choosing the smallest correct repair.
3. Configure and build separately in exact `CONFIG_ZSWAP=y/n` out-of-tree `O=` directories with matching `CONFIG_SWAP=y`, `CONFIG_MODULES=y`, Device Mapper and LZ4 flags; enforce compiler identity and source SHA. Do not accept missing/empty export table, fake placeholder `.ko`, stale cross-profile outputs or skipped `modpost` as PASS. Preserve bounded `-j` and warning level, capture **first actual failed command**, exit status and per-profile config/source/module hashes into the existing retained artifact **even on failure**.
4. Complete actual Linux external-module Kbuild of `swapz/src/kernel` using the exact configuration's generated real export symbols and verify a nonempty `dm-swapz.ko` for **both** profiles. A `Module.symvers` file alone is not module-build PASS. If a new real module compilation/link error emerges, expose that first error and fix only if a narrow compatible change to the true module source is justified; co-update applicable coding standard. Do not suppress warnings, claim success after early exit or enable RAW bypass.
5. Run actual YAML parse and embedded Bash `bash -n`, structural/safe-failure assertions and exact-source checks. **Hosted real Linux compilation is `NOT_RUN` until coordinator publishes the source and the existing workflow runs**; do not infer PASS from local shell mocks. Record exact tools, commands, source commit, compiler version, outcomes and unqualified steps. The existing separate LLVM job must remain independently runnable if the GCC job fails again.

## Publication

Edit real source-controlled YAML and governing standard, create one retrievable Git source commit with parent **`45a3e8e911e447d9807f786ca33e14eac99374f8`**, no remote-main update, no branch/PR/fork/extra worktree. Post a single new `message: REPORT_READY` after the unique `ROUND_OPEN` to https://github.com/k1moradi/swapz/issues/124: `round: "007"`, `agent: 3`, task ID, new commit SHA, actual tests/exits, first failure and bounded evidence. Agent 1 serially integrates and verifies hosted CI. Start independently of Agent 6.

Safety: source-only/hosted build, no kernel loading, mapper/swap/reclaim, physical device or upstream Linux publication. **Phase A BLOCKED, Phase B disabled.**
