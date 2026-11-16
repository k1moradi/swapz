# Agent 3 — Round 016 Phase A DM observational provenance and exact-once source qualification

Official issue: https://github.com/k1moradi/swapz/issues/133
Frozen source parent: f716a5162a098742ec4bf7ab17b6a6a977bb75d4. Start in parallel with Agent 2 only after official ROUND_OPEN. You own production changes to src/kernel/dm-target.c.

## Exclusive code ownership
- src/kernel/dm-target.c
- tests/runtime/native/zswap-origin-consumer-source-test.py
- tests/runtime/native/zswap-origin-producer-consumer-abi-test.py
- tests/runtime/native/pinned-linux-origin-paired-module-test.py
- .github/workflows/phase-a-zswap-origin-prototype.yml
- A narrowly scoped new C source-bound regression file in tests/runtime/native/ only if genuinely necessary
- Unique append-only Round 016 Agent 3 section in docs/testing_standards.md; add coding standard only if behavior contract changes

Do not edit Agent 2's KUnit workflow/verifier or pinned source stager. Use only frozen integrated published producer/consumer semantic origin ABI as your input; never depend on any Agent 2 Round 016 changes.

## Implement — source-level engineering
1. Strengthen the real production DM-side Phase A observation and its evidence as needed: source-authenticated WRITE + REQ_SWAP + exact single-page 4096-byte positive; default UNKNOWN for ordinary, rejection, requeue, READ, carrier absent, clones/mixed origins, stale/missing origin; exactly one foreground committed-write increment after real successful authority for each of the compressed/RAW/zero/async foreground completion paths. Keep this strictly observational: no compression decision, RAW scheduling, extent layout or completion timing changes.
2. Add executable source-bound negative regressions covering first failure, READ/requeue/error/GC/reset and double completion, not a copied fake C implementation. Prefer compile/exercise actual extracted pure C helper where feasible; preserve the existing original tests and comments. Avoid locks, allocations or extra hot-path scans. If the existing code already guarantees an invariant, demonstrate it with executable source test instead of gratuitous refactoring.
3. Extend the existing **matched pinned modified Linux + swapz module** verification only where a concrete evidence hole exists. Require actual modified Linux source SHA and blobs, generated headers, Kconfig y/n, Module.symvers, linked dm-swapz.ko SHA, module build source, and origin_carrier_compiled=1 for the modified y/n build. Do not call a module build a loaded-kernel test; report exact hosted evidence separately.
4. Test native source contract, producer→consumer semantic ABI, relevant Make/native suite, GCC/Clang high warnings/sanitizers where supported, YAML/shell syntax and git diff --check. Keep all established negative gates; do not weaken them merely to obtain green CI.
5. Do not connect Agent 2's guarded CRC32 compressed producer to Agent 3's CRC32C/expected-page-SHA readback descriptor. There is still no authenticated compressed carrier, matching real decoder or ownership transfer. Current swapz RAW is uncompressed 4096 bytes. Phase B and direct compressed handoff remain disabled.

## Completion evidence
A retrievable sole-parent source commit with actual owned C/test/CI changes as justified, exact source/headers/compiler/config/build identity, measured command exits and first failure. If a real loaded zswap entry writeback and 4096-byte readback were not run on a matching kernel/module, report NOT_RUN/BLOCKED, never PASS. Report on issue #133 exactly once with message REPORT_READY, round 016, agent 3, source SHA and original evidence links.
No branches/PRs/forks/worktrees and no remote-main writes; Agent 1 is sole serial integration writer.
