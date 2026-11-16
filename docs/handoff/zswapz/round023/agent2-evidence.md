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

## Additional Agent2 source hardening — store-time allocation identity

The original published Round023 Agent2 typed carrier and no-ABI publish
refusal are preserved without replacement. A subsequent independent source
inspection of exact pinned `zswap_store_page()` established an additional
negative boundary: the stored-entry proof previously captured source entry,
slot, generation, codec and original SHA, but not the *actual published zpool
allocation identity*. A pointer and caller-supplied generation can be reused
with a different handle, compressed extent length or resolved pool. The
compile-disabled `zswap_swapz_stored_proof` now snapshots
`stored_pool`, `stored_handle`, and `stored_length` only after the
source-only original folio/xarray identity check, and capture requires all
three to match the still-stored entry after first validating bounds.
The exact helper remains `#if 0`; it does **not** pretend that a caller
can furnish an authenticated kernel slot allocation epoch.

The executable `fixtures/round023-producer-proof-identity.c` source fragment
is included by the existing `pinned-linux-zswap-compressed-handoff-test.py`
GCC/Clang test **after the actual staged disabled C function bodies**.
It rejects old handle, changed 1..3568 compressed length, forged proof handle,
forged proof length, wrong pool pointer, xarray slot ABA and wrong
generation. Only a correct source-only copy may transition to SUBMITTED and
form a borrowed typed snapshot. Even all-true forged clone/split/retry/origin
claims return `-EOPNOTSUPP`, and the owner error completion releases
exactly once. The existing host test that intentionally varies compressed
size now obtains a fresh *fixture-only* stored proof for the changed payload;
old proof reuse is explicitly rejected, not silently accepted. The existing
already-published C carrier and its tests remain intact.

**Actual local commands and limits:** this runtime has no local checkout,
and `git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main`
exited **128** (`Could not resolve host: github.com`). An independently
written source-equivalent sanity harness (NOT the exact staged kernel C)
was compiled and executed:
`gcc -std=c11 -O1 -g -Wall -Wextra -Wconversion -Wshadow -Werror
-fsanitize=address,undefined -fno-sanitize-recover=all -pthread
/mnt/data/round023_agent2/carrier_source_equivalent.c -o
/mnt/data/round023_agent2/carrier-gcc && ASAN_OPTIONS=detect_leaks=1
/mnt/data/round023_agent2/carrier-gcc`: **compile 0, run 0**.
Identical `clang` invocation/output `carrier-clang`: **compile 0, run 0**
(GCC 14.2, Clang 17). The harness checks genuine Castagnoli
`~crc32c(~0U,...)` vector, typed owner copy, ABA handle/length/pool/
generation rejections, forced rejection of clone/split/merge/reissue,
forged origin, corrupt payload, and no real epoch authority.
Three deliberately mutated equivalent C variants (forged real slot epoch,
skipped CRC, bypassed clone self-identity) each compiled GCC **0**
and failed its assertions with SIGABRT **-6** (expected refusal);
the first test-runner script itself exited **1** due to an overly strict
duplicate-string guard and was corrected to target only the first occurrence,
then reran **0**. Independent Python original-page 4096-byte SHA256 was
`d67c656e01756650d77717b0839985a056ec28ffe174601d690fc407a2ceffca`,
exit **0**.

**Exact committed Python original-suite, full source KUnit y/n, Kbuild, and
git diff --check are NOT_RUN locally** due unavailable checkout. The
repository's real source-linked hosted workflow is the next authoritative
check for the precise staged C/host fixture; do not upgrade equivalent C
or historical 5/5 pinned KUnit to loaded-kernel qualification.
`STORED_ENTRY_LIVE=NOT_RUN`, `4096_READBACK=NOT_RUN`,
`PHYSICAL=NOT_RUN`. `PHASE_A=BLOCKED`;
`COMPRESSED_TRANSFER=DISABLED`; Phase B forced RAW bypass DISABLED.
Existing current RAW still equals the original UNCOMPRESSED 4096 bytes.
The SWAPSPACE2 protected first 4096 header/UUID/table was never accessed
or changed; no module, swap, pressure, null_blk or physical operations.
