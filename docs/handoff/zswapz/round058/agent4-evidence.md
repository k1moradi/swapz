# Round058 Agent4 — original LZO1X/LZ4 independent imported read

Official [ROUND_OPEN #175](https://github.com/k1moradi/swapz/issues/175#issuecomment-7062413356).
Frozen engineering `383d2b4e5b1b5a31b2f785f99f88241b2d08bce5`,
task docs `ffc15247418f4566a3230f55af99de96744f9741`.
All source is dormant/test-only; the real native source/DM target/lower BIO
data-path is **not** wired and receives NO authorization.

## Existing source and actual first-error evidence

At the frozen engineering SHA, Round057 original LZO codec-profile
[run #44901784808](https://github.com/k1moradi/swapz/actions/runs/44901784808)
is **terminal SUCCESS**. Independent original decoder
[run #44901784715](https://github.com/k1moradi/swapz/actions/runs/44901784715),
job `136839022753`, is **terminal FAILURE**. Actual first error:
`gcc/baseline/compile/original-lzo-compressor` original
`lib/lzo/lzo1x_compress.c:105:6` `#error "missing endian definition"`.
The host-only Round057 decoder shim omitted `__LITTLE_ENDIAN` despite
the actual pinned little-endian ABI. The narrow fix requires a compiler
host-endian assertion and the original `__LITTLE_ENDIAN` declaration,
without altering Linux C, sanitizer diagnostics or product compiler flags.

## New actual source change

The existing dormant `src/kernel/zswap-import-codec.h` already verifies
its original raw-LZ4 profile. Extend the same function (no new product
entry point) to dispatch a separately tagged dictionary-free original
LZO1X v1 profile. The LZO branch calls actual pinned original
`lib/lzo/lzo1x_decompress_safe.c` directly, not the product LZ4
decoder or a retired zswap crypto_acomp transform. The original
`crypto/lzo.c` wrapper is verified as invoking exactly that same
function and original compressor. Reject nonzero decoder status,
including `LZO_E_INPUT_NOT_CONSUMED`, or incomplete 4096 output.

Existing source checksum and immutable-only-output gates remain:
1..3568 payload bytes; matching own RAM-side map/slot/generation/GC
witness (test-only, **not** real lease); exact lower payload length,
zero dictionary, codec/version, producer flags, compressed CRC32C,
independent decoded-original SHA256, no aliasing, and final whole
4096-byte memcpy only after every check. The decoder requires an
actual independently held kernel module/owner lifetime through
target teardown, GC and readers before future activation; the
present symbol-call and test-only authority cannot supply this proof.

New rootless original-source-C fixture runs both original Linux LZO
compressor/decompressor, raw LZ4, real `src/kernel/codec.c` CRC,
full SHA via OpenSSL and eight byte-unaligned buffer offsets.
The independent driver checks the pristine Linux commit and six
exact original Git blobs, uses Linux-native warnings only for
untouched upstream units while keeping strict product/fixture
warnings, GCC+Clang ASan/UBSan, and seven separately compiled
and **executed** imported-read semantic mutants per compiler.
The dedicated main-only workflow reports a bounded first error.
All actual fresh exact-commit CI statuses must be cited after
GitHub Actions completes; source publication alone is NOT PASS.

## Safety and release gate

`SWAPZ_ZSWAP_IMPORT_ACTIVE=0`, `SOURCE_MAPPED_AUTHENTICATED=0`,
`PHASE_A=BLOCKED`, `DIRECT_COMPRESSED_HANDOFF=DISABLED`,
`FORCED_RAW_BYPASS=DISABLED`. Normal `RAW_4096` is
the entire ORIGINAL UNCOMPRESSED 4096 bytes. No physical first
4096-byte SWAPSPACE2 header, UUID/signature or partition table
changes. No owner make/fast tests, actual pressure, loaded kernel,
DM activation, physical swap, privileged operations or
independently authenticated production transfer.
