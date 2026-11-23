# Round071 Agent6 — independent zswap ↔ swapz cooperative natural-pressure scheduling policy

**State:** start only after authoritative `message: ROUND_OPEN` on [issue #188](https://github.com/k1moradi/swapz/issues/188). No dependency on new code/results from Agents2/3/4/5. Use currently committed `main` scheduling source tests and frozen contract. No physical swap, privileged kernel, loaded modules or real memory pressure.

## Objective

Independently make the **cooperation invariant** executable and quantitatively auditable: Linux MM/zswap alone decides RAM compressed-page residency, reclamation and naturally selected STORED eviction; swapz never adds a competing shrinker, additional reclaim timer or direct zswap pool pressure. At a future authenticated original eviction, copy bounded original compressed bytes while original owner/codec is live, defer lower submission on already-owned bounded work without holding MM locks, and send the original compressed representation **without decompression or recompression** through a distinctly tagged volatile pass-through disk allocation that preserves exact original LZO1X/raw LZ4 decoder identity. Existing `RAW_4096` is a conventional 4096-byte **uncompressed** fallback and must not silently receive compressed bytes. Track safe bounded pending capacity, transient allocation failure, reader/GC pin, writeback backpressure, codec retirement and lower FUA failure; fail closed and preserve ordinary fallback without pushing additional reclaim into zswap.

Using the existing published `tests/runtime/native/fixtures/round052-natural-pressure-scheduling.c`, `round054-natural-mm-coalescing.c`, `src/kernel/zswap-direct-handoff.h` and `zswap-import-codec.h` **read-only**, create disjoint deterministic host-only source-linked scheduling negative controls with counters: exactly one MM natural eviction decision, no swapz secondary page-selection decisions, no double compression, first error propagation, no DMA or long blocking under locks, no overwritten upper ACK and FIFO/fairness under bursty 4/8/16KiB extent demand. Test both LZO1X and LZ4 original codec identities, default flags OFF, bounded bytes and backpressure. This is a contract/performance simulation, NOT pressure benchmark or source authentication, and must say so.

**Exclusive new paths**:
- `tests/runtime/native/fixtures/round071-natural-pressure-cooperation.c`
- `tests/tools/round071-natural-pressure-cooperation-verify.py`
- `.github/workflows/phase-a-round071-natural-pressure-cooperation-noauth.yml`
- `docs/handoff/zswapz/round071/agent6-evidence.md`

Prefer **no production source changes**; if a concrete source bug is found, post exact reproduction to #188 for Agent1 ownership rather than editing peer files. GCC+Clang strict source-linked ASan/UBSan executable positive and compiled/executed mutated C negative controls, deterministic repeat/edge tests; cost counters for copies/recompression/reclaim calls/upper ACK are test-only. Append same-commit canonical testing standards, non-force fresh expected-head main-only one-parent commit, first-error and limitations to #188.
