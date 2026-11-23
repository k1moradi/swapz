# Round081 Agent7 — strict original LZO1X dormant decoder host qualification

**Source commit status: PUBLISHED_PENDING_EXACT_SOURCE_CI.** This is an initial source-bearing commit report, not a compiler PASS. Immutable tested source SHA, parent, run/job and first genuine new error are filled by a separate evidence-only main commit after GitHub Actions reports the new attempt.

## Exact verified historical first failure and surgical repair

Old R080 source `4e801ebdc52718875935032867986feb2f2ed48b`, run [45273027725](https://github.com/k1moradi/swapz/actions/runs/45273027725), [job138037498047](https://github.com/k1moradi/swapz/actions/runs/45273027725/job/138037498047) **COMPLETED FAILURE**:
`tests/runtime/native/fixtures/round080-original-lzo1x-independent-decoder.c:103:19: error: unused variable 'shortened' [-Werror=unused-variable]`.
Verified from actual GitHub job log and source line. Existing full page `original_page` and 4095-page negative are generated correctly: negative outputs go to `corrupted` with `shortened_length`. The unused `unsigned char shortened[SWAPZ_BLOCK_BYTES];` is removed, a single 48-byte declaration, without modifying its dataflow, compiler flags, source/test expectations, or production files. Previous R080 actual GCC+Clang executed semantic mutants **ZERO**, positive original product decode unqualified.

New fixture whole Git blob: `fcfa14877f4e56918eb4e00cef874591880d7605`, old `53544db1ee33d973687eae26cd3910d90400278b`. Previous untouched verifier Git blob `881f063b42434446fcb6cd94d46153164b5184bf`, workflow `a2d62c735ba063ed2be52a573dd675eea8ac07df`. Both still enforce strict GCC/Clang C23/C2x -Werror ASan+UBSan and eighteen independently compiled/executed product C source semantic mutations per compiler.

## Source lock and scope

Upstream torvalds/linux pin `c339f4010dea8b0d754f84ace70cd1b089878ef8`, exact upstream blob `mm/zswap.c=ae19e301fced7e357a4c7587dfdd6abb890b9163`, `include/linux/lzo.h=4d30e3624acd237290dbfeaefdb9c710e4f85f56`, `lib/lzo/lzo1x_compress_safe.c=371c9f849492814afed88a443acb2262dcf35dfe`, `lib/lzo/lzo1x_decompress_safe.c=318abb82c63d2c27c0d5497b7cf4e21d87d13154`. Product whole blobs `zswap-import-codec.h=0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6`, `zswap-import-decoder-owner.c=8e0c8f4d2085af7f2e17df412f3a1af654063571`; all original Linux and product source READ ONLY. Original source LZO functions compiled with minimal documented host-ABI shim and the actual product independent owner and original-import decoder linked. Real original Linux KUnit/native `NOT_RUN`.

The test expects original-compatible genuine LZO1X compressed bytes with full 4096-byte decoded equality/digest, lease retained during old-reader/GC close, strict codec tag2 original LZO1X vs dormant direct tag2 ZSTD and tag1 original raw LZ4, CRC/SHA, 4095 short decode, trailing input `LZO_E_INPUT_NOT_CONSUMED`, version, slot/generation, lower read, stale, duplicate get/put, output unchanged, and original 3569-byte fail-close without truncating. All modeled witnesses are TEST ONLY, not authenticated live STORED/MM/selected DM or actual physical I/O/upper ACK.

## Actual CI vs expectations

Focused workflow: https://github.com/k1moradi/swapz/actions/workflows/phase-a-round080-original-lzo1x-independent-decoder-host-noauth.yml. New exact-source run/job: **NOT YET OBSERVED**. New GCC positive, Clang positive and 18 GCC+18 Clang independently compiled and executed semantic mutants: **PENDING**, zero *verified* until Actions executes. First new error **NONE REPORTED YET**. Source-task parent and exact CI identifiers must be appended after publication; do not silently count attempted, queued, compile-rejected or sanitizer-failed cases as PASS. No new original native build; do not interfere with Agent10 or Agent11.

## Frozen safety

Linux original MM/zswap exclusively controls compressed RAM/natural eviction. swapz owns only disk packing/GC, no second pressure reclaimer/recompression. Original compressed LZO1X/raw LZ4 future sideband requires selected authentic original STORED XArray/folio/slot/generation+DM, immutable preerase owned bytes and retained independent decoder, actual ordered lower durable FUA/flush before real exactly-once upper ACK. Ordinary RAW_4096 is **complete original UNCOMPRESSED 4096**. Current dormant import max3568 refuses 3569..4095 without truncation or substitution. Preserve first physical SWAPSPACE2 4096 and the exact 20-byte volatile mapping. `SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`, direct/forced RAW/import OFF; no loaded/swapon/physical/privileged/pressure tests.
