# Round056 Agent4 — independent original LZO1X stable decoder-profile executable (default OFF)

## Scope, invariants and exact-source contract

Frozen engineering `1484efd1324feda5a8871e1a2c015393b3d1a435` and
task `7056741b12eac407314151a8f38e45e77a505603`; official #173.
No new producer/DM ABI; no changes to product codec, authority.h 20-byte
map, DM, production scheduler, original Linux, real pressure, real device or
ordinary upper BIO. All work is test-only; source authentication remains 0,
Phase A BLOCKED, compressed handoff and forced RAW bypass disabled.
The normal `RAW_4096` always contains the *complete original uncompressed*
4096-byte page. The first entire physical 4096-byte SWAPSPACE2 header,
signature, UUID and parent partition table remain immutable.

The already repaired raw LZ4/product codec suite is independent:
[exact engineering-source Round052 host codec CI](https://github.com/k1moradi/swapz/actions/runs/44885212599)
was observed TERMINAL SUCCESS at frozen engineering SHA, containing pinned
actual original LZ4 wrapper + real swapz codec.c, GCC/Clang host ASan/UBSan
96 full-page cases (52776 assertions per compiler) and 13 real C mutants
per compiler. Do not count this as a new live original compressor test
or as a duplicate 96 cases in Round056. The pinned original 66 original
KUnit and both matched GPL DM original x86 ZSWAP=y/n had separately succeeded
at ancestor `d52ac8d12a8f4de5c60d68731f4b2e93fd59240d`,
[workflow 44882263788](https://github.com/k1moradi/swapz/actions/runs/44882263788);
not rerun by this codec-only change.

## New independently compiled C experiment

Added `tests/runtime/native/fixtures/round056-codec-profile.c`, source
`tests/tools/round056-codec-profile-verify.py` and isolated no-auth CI
`.github/workflows/round056-codec-profile-noauth.yml`. All are test-only;
none are included by production Kbuild. The workflow requires `main`,
full local first-parent checkout, Git diff whitespace verification, clean
both checkouts, exact `GITHUB_SHA` and exact pristine original
`torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` plus the following **per-file Git blob SHA
admission** (not a stand-in function):
- `crypto/lzo.c`: `d43242b24b4e831e7e0d26f38d2f263877d5748e`
- `include/linux/lzo.h`: `4d30e3624acd237290dbfeaefdb9c710e4f85f56`
- `lib/lzo/lzo1x_compress.c`: `01586af2347f5e2f8c8528b94e02622fc8b262c8`
- `lib/lzo/lzo1x_compress_safe.c`: `371c9f849492814afed88a443acb2262dcf35dfe`
- `lib/lzo/lzo1x_decompress_safe.c`: `318abb82c63d2c27c0d5497b7cf4e21d87d13154`
- `lib/lzo/lzodefs.h`: `b60851fcf6ce54b57e87d04e917deaa2b6cf62cc`

The test uses the exact original `crypto/lzo.c::__lzo_compress` and
`__lzo_decompress` function bodies, extracted byte-for-byte and executed
with real immutable `lib/lzo/lzo1x_compress_safe.c` (which itself includes
original `lzo1x_compress.c`) and original
`lib/lzo/lzo1x_decompress_safe.c`. No liblzo2 stand-in, retyped
compressor or fabricated in-memory fake decoder. Required host shim supplies
only minimal linux/module.h, kernel.h, unaligned.h and original lzo.h plus
stddef.h; the source is compiled directly from clean pinned checkout.
Conservative non-unaligned optimized original code path is used; x86
little-endian host is verified. Original unmodified lib/lzo is compiled
with its Linux-native `-Wall -Wextra -Werror` policy; actual product
`codec.c` and the test-only profile are separately compiled with
GNU11 `-Wall -Wextra -Wshadow -Wconversion -Werror`, ASan/UBSan
`-fno-sanitize-recover=all`. Only the verbatim original crypto/lzo.c
wrapper has a narrow scoped `-Wconversion` diagnostic exception for its
existing size_t to u32 dlen API assignment; no project warning bypass.
Both compiler subprocesses must have zero baseline stderr and no sanitizer
report. Actual original C mutated *input-not-consumed* branch is compiled,
run and expected to fail a named semantic CHECK, never count a crash,
compile error or sanitizer event as a mutation kill.

The candidate stable profiles in the test-only function are explicit
`PROFILE_LZ4_V1` and `PROFILE_LZO1X_V0`, with distinct expected
selected driver ID. Driver ID is MOCK input, **not source proof**; real
running zswap may choose another implementation. Separate imported-only
test descriptor is 60 bytes (verified by `_Static_assert`), contains
codec/profile/format version/dictionary-free ID, 1..3568 compressed bytes,
full original decoded count 4096, CRC32C and independent original SHA256.
No pointer to an original zswap pool, transform or zsmalloc entry. Caller
owns disjoint 4096-byte decode scratch and 4096-byte output and the
immutable compressed input; no allocation or ownership transfer in decoder.
The 16384-byte aligned LZO1X workspace is needed ONLY by host original
compressor, not retained by disk decoding. Normal 20-byte mapping unchanged;
this 60-byte descriptor is not an activated production on-map layout.

For 49 deterministic 4096-byte full-page producer patterns, both exact
LZO wrapper and host raw LZ4 compressor produce candidate compressed
payloads; only output <=3568 is eligible. Every admitted page must have
exact 4096-byte decoder output matching independently SHA256-authenticated
original bytes and full-page memcmp. CRC corruption, SHA-only mutation,
unknown driver, dictionary nonzero, version mismatch, length 3569 and
original LZO trailing byte must return the specified errno and leave
all 4096 caller output bytes unchanged; input/output/scratch overlap is
rejected. Pinned original `lzo1x_decompress_safe` returns
`LZO_E_INPUT_NOT_CONSUMED` if trailing bytes follow the compressed
end-of-stream marker. This is distinct from a name-based LZO guess.
The runner defines five actual mutated test-only decoder function bodies
(CRC, full SHA, unknown codec, 3568 cap and wrong dispatch) plus one changed
pinned original LZO decoder source branch, each compiled and executed by
GCC and Clang and expected to reach `ROUND056_CODEC_FIRST_ERROR line=`
under unchanged fixture checks.

**CI outcome:** Do not mark PASS or claim rootless compilation until the
exact new commit's new workflow has completed terminal with true job logs.
The tests above describe executable gates, not pre-execution results.
On any first compiler or sanitizer error, report actual job/line;
a failed original source adaptation is NO_GO for LZO, not permission to
switch to a different library or remove strict checks. Old LZ4 pass remains
true at its exact source only.

## Kernel read/lifetime boundary

The pinned [original mm/zswap.c](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zswap.c)
holds the compression pool through a STORED entry; compressor can change at
runtime; original `zswap_writeback_entry` decodes, erases and frees STORED
entry before original ordinary full-page IO. The target cannot reuse a
retired original pool or its index as read-time decoder authority. A
future authorized lower compressed staging must copy bytes *before* erase
under actual original BIO/locked folio lifetime, record actual selected
implementation/version/dictionary and independent full-page digest, and
hold stable swapz-owned decoder profile/metadata until map/GC/reads/dtr
retire. The test-only profile is valid byte-compatibility evidence
**only** if the real upstream selected driver/format is independently
authenticated and genuine source and accepted target ownership exist.
No source BIO, clone, pre-erase snapshot, current DM lease, durable lower
write, mapping, real single ACK or full-page physical readback is
established by this fixture. Actual source-side integration is owned by
Agents2/3, volatile map/GC by Agent5; this agent does not depend on their
same-round prototypes.

Precommit unknown codec/driver/version, dictionary, LZO alternative stream,
trailing input, >3568, CRC/SHA, source or decoder lifetime failure ->
use the original complete uncompressed 4096-byte ordinary route only
while it is still held and can be completed correctly. After authentic
commit, corrupted disk read MUST return EIO/EBADMSG, never pretend an
original uncompressed fallback page exists, never ACK twice or overwrite
upper output. No per-map crypto transform, no runtime pool pinning or
read-path module resolution; decoder availability must be independently
pinned through all mappings/GC/readers or explicitly refuse. No new
decoder dependency is introduced into production now.

**Release decision:** SOURCE_MAPPED_AUTHENTICATED=0, PHASE_A=BLOCKED,
DIRECT_COMPRESSED_HANDOFF=DISABLED, FORCED_RAW_BYPASS=DISABLED. Existing
natural Linux MM pressure is the sole bounded zswap RAM eviction driver;
swapz packs disk extents and GC only. No new RAM reclaim, owner make test,
make fast_test, privilege, loaded module, physical swap or real-pressure test.
