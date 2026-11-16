# Round 023 Agent 2 — pinned Linux compressed carrier refusal

Official issue: https://github.com/k1moradi/swapz/issues/140#issuecomment-6928573299
Frozen baseline: dd08a3dbc8309da266f49f975b6733cd33a25a8d

This round retains every prior pinned original Linux source-staging,
KUnit (y/n), zswap provenance and ordinary REQ_SWAP 4096-byte path.
The genuine source still lacks original store-time generation and a
compression-aware MM/BIO/DM lifetime interface, so none may be invented
from a synthetic BIO origin bit, slot integer or xarray-address mock.

The new compile-disabled typed carrier is a source-only, explicitly
UNTRUSTED snapshot of one previously SUBMITTED, owned, immutable
LZ4-v1 payload: original slot and generation, bounded 1..3568 bytes,
original decoded 4096, canonical CRC32C, independent original-page
SHA256 and borrowed pointer whose source allocation outlives the view.
A sibling publish gate ALWAYS refuses (-EOPNOTSUPP) because no
source-verified clone/split/merge/retry references or active kernel
transport exist. Forging every source/transport claim still refuses.
The preexisting compressed fallback remains normal decompression to
original UNCOMPRESSED full 4096 then original REQ_SWAP WRITE.

The host fixture executes both new actual staged C helpers, including
a legitimate mock snapshot, all-true forged provenance, split/merge
violations, no premature owner release and exactly-once original
abort/finish. All new ABI work is #if 0 source-only; no kernel module,
RAM swap, physical device or memory pressure was touched. A source
test cannot replace actual controlled owner-loaded 4096 swap-in.
STORED_ENTRY_LIVE=NOT_RUN; LOADED_4096=NOT_RUN; PHYSICAL=NOT_RUN.
Phase A BLOCKED; Phase B forced RAW bypass DISABLED;
compressed handoff DISABLED. SWAPSPACE2 original header/UUID/table
unchanged and current RAW original uncompressed 4096.
