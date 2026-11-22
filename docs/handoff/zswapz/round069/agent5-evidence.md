# Round069 Agent 5 — joined ORIGINAL Linux BIO and REAL source-bound authority (NO_AUTH)

Official [ROUND_OPEN issue #186](https://github.com/k1moradi/swapz/issues/186),
last frozen engineering `f98d00a8fa95ee2bb9df3270bf6262d5d6b040e0`,
task/docs exact `111a833fc05e08bac259b4470504eeea9d8e9adb`.
Full shared+individual prompt, Round068 independent report and original
worker archive read. Agent 3 owns original zswap STORED XArray, Agent 4 owns
original decoder-owner; no new peer code or APIs required.

## Genuine integration source identity

The rootless native KUnit source is appended under the
`SWAPZ_ROUND069_ORIGINAL_BIO_AUTHORITY_JOIN_KUNIT` **undefined by default**
guard to pristine original pinned
`torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`
`block/bio.c` in an ephemeral test workspace only. Three original Linux
Git blobs for original `block/bio.c`, `include/linux/bio.h`,
`include/linux/blk_types.h` are verified before any modification.
Test stager copies byte-identical FULL REAL product
`src/kernel/authority.c`, `authority.h`, `codec.c`, `codec.h`,
`gc-cost.h` into an isolated original native test include directory,
with per-file original Git blob pins and SHA256 staged postimages. The
real product `authority.c` and `codec.c` are directly included in
the SAME original `block/bio.c` translation unit; no mock transition
function, copied allocator, fake 20B mapping or external product module.
The nested dormant Round066/067/068 source flags are enabled ONLY in the
rootless test compiler invocation; ordinary product imports remain zero
by default. No changes to Agent 3 original zswap/DM or Agent 4 codec
decoder-owner, nor kernel Makefile or production on-media metadata.

Four genuinely native ORIGINAL kernel cases use actual
`bio_alloc`, `bio_add_page`, `bio_for_each_segment`,
`kmap_local_page`, original `bio_endio`, REQ_OP_WRITE,
REQ_FUA, REQ_OP_FLUSH|REQ_PREFLUSH, and REQ_OP_READ against a
separate 4 MiB bounded RAM fake lower (physical sector zero/first
4096 SWAPSPACE2 sentinel 0x5c). Every BIO has owned 4096-byte
page/bvecs surviving both lower I/O and owner completion. The true
original `bio_endio` callback captures sector, op/FUA/flush bits,
exact length and a monotonic token, and ONLY queues a work item;
the work item acquires a sleepable mutex then invokes REAL
`swapz_import_lower_end_write/flush/read` from the directly linked
source, mutating actual `swapz_stage` reservation,
`live_records`/extent-class accounting, native-codec-tagged
920-byte fixed 8-record pool and exact retained-reader GC pin.
No sleeping authority call occurs directly in IRQ-sensitive endio.
Internal `REQ_ALLOC_CACHE` that original `bio_alloc` might append
is masked from normalized owner opf, retaining exact issued
READ/WRITE/FLUSH/FUA/PREFLUSH flags.

Native original `lzo1x_1_compress` or original
`LZ4_compress_default` supplies already-compressed source bytes for
a separate ORIGINAL codec tag; test source scratch is overwritten
AFTER real BIO bvec pages copied it, demonstrating independent
lower-buffer ownership. Original kernel CRC32C and SHA256 functions
seal exact payload integrity and full 4096-byte uncompressed original
digest. Actual linked authority C enforces complete native lower
WRITE+modeled FUA or post-WRITE separate flush-before-visibility,
checks compressed CRC32C and zero padding across 4/8/16KiB data-only
extents and physically counted reservations. Complete actual kernel
READ callback retains pin during real bvec memory transfer, invokes
source-exact `swapz_import_disk_read_pinned`, CRC/padding and reader
put, then independently native LZO1X/LZ4 decodes EXACT 4096 original
bytes and SHA256/byte-equality compares. Old physical live extent
is retained while GC writer writes replacement 4-block extent,
and released only after old native READ completion consumes the last
pin. Short 13-byte partial lower write conservatively abandons
extent, duplicate callback refuses ESTALE, pending close drains
and refuses publication. There is no upper BIO or upper ACK.

## Genuine independent test gates, not fake kernel proof

* Strict hosted GCC and Clang source-linked real authority.c+codec.c
  Round068 seven native-original LZO1X/LZ4 cases and **14 genuinely
  compiled and executed changed real-C semantic mutants per compiler**,
  with real negative close/FUA/short/GC source anchors; strict
  `-Wall -Wextra -Wconversion -Wshadow -Werror` ASan/UBSan.
  Compiler failures, sanitizer crashes, timeouts or inert mutations
  never count as semantic kills. The new runner checks five pinned
  actual product Git blobs and exact native endio/authority C include
  bindings before compiler mutants; these STATIC checks are NOT native
  runtime qualifications.
* Fresh rootless pinned-original Linux KUnit compiled AND EXECUTED
  `swapz_round069_joined_native_authority_bio` with 4 exact JSON+KTAP
  cases, zero skips/failures/crashes/errors. This is the first intended
  genuinely joined execution, not the Round068 separate two jobs.
* Round068/067/066/059/057 exact-source regressions and canonical
  first-parent testing standards remain owned by their existing CI
  on `main`, not canceled, duplicated or invented. Exact run/job
  terminal status and first errors are reported on official #186.

## Strict no-go

Memory-backed lower WRITE/FUA/flush and completion are a TEST MODEL
even when the actual kernel BIO and actual production C owner execute.
No `submit_bio`, genuine `block_device`, media durability,
original MM xarray/swpentry/slot lease, first/selected native DM target,
decoder owner proven across real source-pool death, real authoritatively
published imported map or exact one native upper ACK. Imported
`*_ACTIVE=0`, `SOURCE_MAPPED_AUTHENTICATED=0`,
`PHASE_A=BLOCKED`, direct compressed handoff and forced RAW bypass
DISABLED. Ordinary `RAW_4096` is entire ORIGINAL UNCOMPRESSED 4096
bytes, not compressed original LZO1X/LZ4. Linux MM alone controls
compressed zswap RAM and natural eviction; swapz disk compression,
packing and GC only, never early reclaim. SWAPSPACE2 first physical
4096 header/signature/UUID and partition table protected. No owner
make fast_test/test, privileged, loaded, physical, actual pressure,
swapoff/mkswap/repartition.

**Source SHA and CI outcomes:** recorded as an issue comment only after
publication/inspection. PENDING or failed native compile remains
PROGRESS, not purported fully joined REPORT_READY.
