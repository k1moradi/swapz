# Round053 Agent4 — codec strict conversion first-red repair, rootless C oracle (no auth)

This document records the Round053 **source changes**, not a preemptive green
qualification. The earlier Round052 source
`c6f2bc783d29aa06ee59034cda3888ebd2c0683f` failed its first real codec
CI at [workflow 44843580853](https://github.com/k1moradi/swapz/actions/runs/44843580853),
job `136657717841`, during `baseline/gcc/compile`: `-Werror=conversion`
on unsigned-long `sizeof(struct swapz_header)` or `sizeof(header)` to
`swapz_u32` in actual `src/kernel/codec.c`. **No original baseline or
mutant binary had executed there; 96 host patterns and 13 hostile modifications
were only defined.** Treat that as first compiler RED, not codec evidence.

## Narrow source-safe correction

A compile-time assertion bounds a maximal eight-bit record count's header
plus records to at most `SWAPZ_BLOCK_BYTES=4096`. Explicit `swapz_u32`
conversions are applied to individual fixed metadata sizes in actual product
codec source only after that width proof. Payload CRC32C, retained volatile
metadata, 4/8/16 KiB payload image, LZ4/delta64/shuf8 routes,
`SWAPZ_MAX_COMPRESSED=3568` and normal uncompressed `RAW_4096` are
unchanged. This requires genuine original matched kernel-DM Kbuild rechecks
if triggered; a rootless C host build does not qualify module behavior.

The existing original-source extraction runner continues to verify pristine
`torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`, extract
**exact** `crypto/lz4.c::__lz4_compress_crypto`, bind its raw-block
compressor to **host liblz4**, and compile actual product `codec.c`
under GCC and Clang GNU11 `-Wall -Wextra -Wconversion -Wshadow -Werror`
with ASan+UBSan. Only the preexisting original upstream wrapper has a
narrow isolated `-Wsign-conversion` exception; the product does not.
Its 96 deterministic pages require byte-for-byte decoded 4096 plus SHA-256
and compressed CRC32C, zero-padding/payload-only 4/8/16KiB, frame/dictionary,
selected-non-LZ4 and >3568 refusal, and full original 4096-byte RAW fallback.

**New width/overflow hostile fixture cases:** rejected 65535-byte RAM
metadata length must not mutate a separate scratch block; maximal u8
`record_count=255` computes 4096 without narrowing/wrapping, and its
16-byte snapshot mismatch must refuse before touching scratch. The
metadata CRC validator must also refuse the malformed 255-count header.
The mutant checker now accepts only **compiled and executed** altered
actual-codec C binaries exiting 1 through the named `CHECK` assertion;
compiler failure, signal, ASan/UBSan diagnostic and unrelated crash are
not counted as mutant kills. The first failure remains explicit.

## Evidence and safety boundaries

The dedicated workflow is `.github/workflows/phase-a-zswap-round052-codec-interop-noauth.yml`.
Its repository checkout must include first-parent history so
`git diff --check HEAD^ HEAD` is meaningful. Terminal exact-source
GCC/Clang results, 13x2 hostile executions, current kernel C builds
and workflow IDs must be checked on the published source SHA; these
were **NOT PASS** merely from authoring this patch.

The pinned Kconfig default is LZO, and the selected crypto_acomp pool is
runtime-writable; host raw LZ4 is strictly `HOST_RAW_LZ4_SUBSET`, not a
running kernel STORED source-byte witness. Any unknown codec, framing,
dictionary, over-3568 length, CRC, 4096 decode or SHA mismatch refuses
separately tagged hypothetical lower staging, falling back to original
full uncompressed 4096 normal upper RAW. There is no independently retained
live source typed-counted slot, pre-unuse cancel/drain, current live DM
target/table/map/GC/dtr lease, durable lower write, exactly-one map/ACK or
verified real read. `SOURCE_MAPPED_AUTHENTICATED=0`,
`PHASE_A=BLOCKED`, `DIRECT_COMPRESSED_HANDOFF=DISABLED`,
`FORCED_RAW_BYPASS=DISABLED`. Zswap remains bounded RAM under natural
Linux MM eviction; swapz remains a valid SWAPSPACE2 disk payload-only
compression and GC tier. Entire first physical 4096 SWAPSPACE2 header,
UUID/signature and partition table are immutable. No owner `make test`,
`make fast_test`, privileges, module load, physical swap, actual MM
pressure or device activation is authorized.
