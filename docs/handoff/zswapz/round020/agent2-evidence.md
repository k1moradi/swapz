# Round 020 — Agent 2: source-exact stored zswap entry to swap BIO causality

**Source base:** main task publication `de5bc09e80484c60d003e860732ecb736a6c2f0b`; upstream Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`; pinned `mm/zswap.c` Git blob `ae19e301fced7e357a4c7587dfdd6abb890b9163`. Official issue: https://github.com/k1moradi/swapz/issues/137.

## Authenticated source path and exactly what was tested

The real pinned `zswap_store_page()` calls `zswap_compress()` and publishes the stored entry to the swap-slot xarray, then retains its pool/objcg references, initializes `entry->swpentry`, marks it referenced and adds it to the LRU. A rejected compression or failed xarray publish has no valid new stored-entry writeback authority. The reclaim callback gives referenced entries a second chance, captures `swpentry` while holding the LRU lock, rotates the LRU item, drops the lock and calls `zswap_writeback_entry()`; this pointer is not dereferenced until the swapcache folio lock and xarray-pointer identity check prove the entry is still current.

In `zswap_writeback_entry()`, missing swap device/folio, recycled xarray entry, or unsuccessful `zswap_decompress()` all return without the source origin tag or submit. `zswap_decompress()` succeeds only with zero error and a full `PAGE_SIZE` result (or the separately handled incompressible full-page copy). After success the source erases the tree entry, releases its compressed zpool/pool/object accounting, marks the folio uptodate/dropbehind, assigns `ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK` and calls `__swap_writeout()` / `swap_write_submit()`. The existing staged `mm/page_io.c` takes the context origin only for WRITEs, refuses mixed-origin merges and submits `REQ_OP_WRITE | REQ_SWAP` with `bi_swap_origin`; `block/bio.c` reset/reissue/clone boundaries remain protected by the proven pinned BIO KUnit suite. A single original page is 4096 bytes; a merged BIO may contain multiple compatible pages, which is not a claim that every BIO extent equals 4096.

The new staging gate pins **four actual immutable producer C extents** (decompress, writeback with the sole origin insertion, LRU shrink callback, store admission) to exact Git-blob SHA-1 identities. It refuses reordered, removed, rewritten or duplicated authority. The original whole `mm/zswap.c` blob and staged anchor checks remain unchanged. Optional compressed prototype stays `#if 0`; the actual swapz RAW representation remains the **original uncompressed 4096-byte page**, never the prototype's compressed bytes. The research-only CRC32 producer lacks authenticated CRC32C/independent original-page SHA interoperability with a consumer.

An executable rootless fixture compiles the **actual pinned upstream `zswap_writeback_entry()` function with the exact staged origin insertion** plus the real staged `bio_is_zswap_stored_writeback()` predicate. All external kernel services (zswap decoder, locked folio, xarray, swap device and downstream submission) are explicitly mocked. It checks successful tag and an original-sized page, recycled identity, decompression failure, unavailable swap device, missing swapcache folio, malformed compressed size, forbidden READ/non-swap/origin claims, and retention of the first negative cause. Negative source mutations reject bypasses of admission, second-chance/identity/decompression and write submit, with no synthetic TAP or loaded-success claim.

## Actual isolated local measurements and limits

The local runtime could not `git ls-remote`/clone GitHub due DNS resolution of github.com; no full local main checkout was available. **Source-tested locally (not the new full repository Python suite):**

- `gcc -std=c11 -O1 -g -Wall -Wextra -Werror -Wconversion -Wshadow -fsanitize=undefined -fno-sanitize-recover=all /mnt/data/round020-agent2/causality.c -o /mnt/data/round020-agent2/c-gcc && /mnt/data/round020-agent2/c-gcc`: **exit 0**.
- Equivalent `clang` invocation with the same flags/input and separate executable: **exit 0**.
- Isolated negative mutation `if (!zswap_decompress)` to wrong polarity, compiled with GCC and same flags: compile exit 0, runtime **nonzero SIGABRT assertion** (expected refusal; no fake PASS).
- Isolated negative mutation of the authenticated source-origin assignment to zero, compiled with GCC and same flags: compile exit 0, runtime **nonzero SIGABRT assertion** (expected refusal).
- Original upstream source slices were fetched from the exact pinned GitHub revision; independent GitHub Git-blob hashing confirmed all four expected section IDs including staged writeback. This verifies exact section text, **not** kernel execution.
- Full committed `python3 -B tests/runtime/native/pinned-linux-zswap-stored-entry-producer-test.py`, existing staged Python suite, full checkout `git diff --check`, Kbuild/hosted KUnit and actual loaded-path proof: **NOT_RUN locally**. The committed existing stage-test invokes the new test on CI, and later exact-run evidence must be checked independently. Do not convert source-excerpt smoke into full-suite PASS.

## Evidence classes and first-failure boundary

Existing proven source baseline: [pinned UML KUnit y/n five distinct real no-skip PASS cases each](https://github.com/k1moradi/swapz/actions/runs/43897628379); [matched Linux/module source Kbuild PASS](https://github.com/k1moradi/swapz/actions/runs/43897628284). **GENUINE_EVICTION_LOADED=NOT_RUN**, `loaded_dm=NOT_RUN`, original 4096-byte loaded swap-in `NOT_RUN`, owner physical trial `NOT_RUN` this round. No newly observed live first failure can be attributed to zswap, swapz, or a physical disk. Real first blocker is the missing authenticated booted source-produced stored-entry → MM/BIO → loaded DM committed WRITE and independent byte-exact READ evidence.

**Phase A BLOCKED. Phase B forced RAW bypass DISABLED. Direct compressed handoff DISABLED.** No kernel load, memory pressure, cgroup, swap activation, partition or physical device mutations were made.
