# Agent 3 — Round 007 DRAFT: repair real pinned GCC external-module Kbuild failure

**Task ID:** `agent3-pinned-gcc-linked-module-qualification-repair`
**Coordination mailbox:** https://github.com/k1moradi/swapz/issues/124
**Provisional source:** `79bb7c0c8bdf055eaeecf81c0fa291d167bd0e61` — use the actual source baseline published in the future `ROUND_OPEN`, not this draft SHA if they differ.
**START GATE: ROUND 007 IS NOT OPEN. DO NOT EXECUTE until its unique `ROUND_OPEN` on issue #124.** Once opened, start simultaneously with Agent 6.

## Own actual existing CI code

Exclusive implementation file: `.github/workflows/phase-a-linux-source-preflight.yml`, **GCC external-module job only**, plus your small uniquely titled additive `Round 007 pinned GCC external-module export-table qualification` section in `docs/testing_standards.md`. The independent LLVM/Clang job added in Round 006 must remain byte-for-byte behaviorally intact. Do not edit Agent 6's `tests/runtime/native/pinned-linux-preflight-evidence-test.py` or `.github/workflows/product-codec.yml`; do not edit upstream Linux or Agent 7's fixture.

## Real known failure; implement correct remedy, not a mock PASS

1. Start from actual [GCC full pinned-Linux run #43735000163](https://github.com/k1moradi/swapz/actions/runs/43735000163), failed step **`Compile real pinned Linux swap/BIO objects with CONFIG_ZSWAP=y/n`**, fatal first result **`Full pinned kernel export table missing; no qualified external module link`**, with [artifact 14169614803](https://github.com/k1moradi/swapz/actions/runs/43735000163/artifacts/14169614803). Reinspect job logs and manifest; distinguish kernel `vmlinux` success from `Module.symvers` generation and module-modpost export requirements. Do not guess that `vmlinux` alone produces the required table, silently skip the check, or mark a failed build PASS.
2. Make the **smallest tested YAML/shell source edit** to request the correct real pinned-tree Kbuild targets to generate a complete nonempty `Module.symvers` for the **same** kernel configuration, preserving existing Linux version SHA `c339f4010dea8b0d754f84ace70cd1b089878ef8`, `CONFIG_ZSWAP=y/n`, `CONFIG_MODULES=y`, DM/LZ4 flags, out-of-tree `O=` identity and independent isolated module stage.
3. Compile the actual `src/kernel` Device Mapper module through its existing staging Makefile using this exact export table, and verify a nonempty linked `dm-swapz.ko` for EACH profile. Reject missing symbol tables, fake `.ko`, ignored `modpost` exit, warnings masquerading as clean build, stale cross-profile objects, mismatched `.config` or wrong Linux/swapz source hash. Keep bounded resources and first-failure manifest **even on failure**.
4. If the corrected build exposes a **different real kernel ABI or source failure**, report that error precisely and do not conceal it with a permissive compiler flag; only a narrowly verified compatibility adjustment in the existing swapz module is permitted after proving the actual source defect, with a matching applicable coding standard. Do not change kernel ABI/helper names or add RAW bypass.
5. Validate YAML parser, embedded Bash `bash -n`, source-control and negative fail-closed tests that actually run. A hosted exact-integrated-commit run with both profile manifests and `dm-swapz.ko` build output verification is mandatory for full PASS; source-only static tests qualify only your committed code delivery. No new workflow file, fork, Linux tree copy, branch, PR or privileged host operation.

## Real committed source handoff

After authoritative `ROUND_OPEN`, edit actual code from its frozen source, create a retrievable Git source commit with the owned tracked YAML and your distinct testing-standard appendix, without updating remote `main`. Record exact compiler/jobs/config/commands/exits, first failure and `NOT_RUN` gates. Post one primary `message: REPORT_READY` to issue #124 with `round: "007"`, `agent: 3`, task ID, exact source SHA, changed paths and tests. Agent 1 alone integrates via non-force expected-head and verifies hosted CI.

No installed/loaded module, active mapper/swap/reclaim, physical operation or authenticated producer claim. Phase A BLOCKED; Phase B RAW disabled.
