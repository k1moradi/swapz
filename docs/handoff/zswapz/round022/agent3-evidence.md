# Round 022 Agent 3 — compressed zswap import decoder evidence

Official source: https://github.com/k1moradi/swapz/issues/139#issuecomment-6925368056
Architecture: docs/handoff/zswapz/architecture-requirements.md

The new unreferenced src/kernel/zswap-import-codec.h models a distinct
volatile-RAM imported LZ4 v1 representation, not an ordinary 4096 RAW page
or the current synthetic provenance BIO bit. It requires authentic immutable
previously-stored eviction, source identity, store generation, slot/generation
and GC identity, 1..3568 compressed bytes, CRC32C, original full 4096 SHA256,
and durable commit/one independent ACK before separately authenticated READ.
The real block LZ4 decoder writes to caller-owned 4096 scratch and only
copies to output after exact decompressed length, independent SHA256 and
optional independently retained full-page memcmp. The output is unchanged
on rejection; no I/O, ACK, buffer allocation or durable metadata is performed.

The compiler-executed C fixture links true production src/kernel/codec.c
CRC32C with liblz4 and OpenSSL SHA256; cases reject missing/invalid codec,
CRC32-vs-CRC32C, bit flip, bad SHA, wrong version/dictionary/size/slot,
store-generation ABA, GC relocation, lower I/O short/error, upper ACK
count 0/2, missing owned copy, teardown, overlapping output/scratch and
LZ4 frame treated as a block. Python source guard ensures no DM integration.
Existing RAW_4096, SWAPSPACE2 header/UUID, physical partition and production
DM paths are unchanged. No alternate pressure controller is introduced.

This is SOURCE_ONLY and cannot authenticate a real booted modified Linux,
true zswap stored page eviction, loaded matching module, RAM-only owner or
Linux 4096-byte swap-in. The independent original digest remains a future
store-time producer responsibility. Phase A BLOCKED, forced RAW bypass
DISABLED, compressed handoff DISABLED; LOADED_STORED_ENTRY=NOT_RUN,
4096_KERNEL_READBACK=NOT_RUN, PHYSICAL=NOT_RUN.
