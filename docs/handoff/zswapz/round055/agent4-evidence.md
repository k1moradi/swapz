# Round055 Agent4 — verified exact-source codec PASS; different-codec read contract (design only, NO AUTH)

## Decision and actual qualification

**NO_CHANGE to production, fixtures or workflows.** The Round054 comparison-only
`size_t expected_bytes` correction in actual
[src/kernel/codec.c](https://github.com/k1moradi/swapz/blob/31adfb7ff57cc5c061304beae749b485d093130b/src/kernel/codec.c)
is already correct. No new compiler warning bypass, gratuitous source changes,
test-count inflation or new decoder dependency is warranted.

Frozen engineering `31adfb7ff57cc5c061304beae749b485d093130b`, verified sole parent
`d52ac8d12a8f4de5c60d68731f4b2e93fd59240d`. The old real
[GCC failure 44851393073/job 136683323930](https://github.com/k1moradi/swapz/actions/runs/44851393073/job/136683323930)
was the second size_t sizeof(record) promotion in swapz_attach_extent_metadata.
That was an earlier SHA; it is not current RED.

**Independently observed terminal SUCCESS** at the *exact repaired engineering
SHA*, [workflow 44882508681 / job 136780657456](https://github.com/k1moradi/swapz/actions/runs/44882508681/job/136780657456).
I retrieved the actual job log and the runner source, not merely the workflow
conclusion. It checked out original `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`, and executed
the runner's exact clean-HEAD and original-source-anchor gates. Both GCC
(Ubuntu package 13) and Clang (Ubuntu package 18) compiled actual product
codec.c with GNU11 -Wall -Wextra -Wconversion -Wshadow -Werror,
-fno-omit-frame-pointer, -fsanitize=address,undefined and
-fno-sanitize-recover=all, plus the exact extracted upstream
__lz4_compress_crypto body bridged to host liblz4. The existing narrow
upstream-wrapper-only signedness diagnostic exception remains; product
warnings were not suppressed. Both base executions emitted:

    baseline/gcc/C-execution: ROUND052_HOST_RAW_LZ4_SUBSET_PASS seed_cases=96 assertions=52776 source_authenticated=0 physical_io=0
    baseline/clang/C-execution: ROUND052_HOST_RAW_LZ4_SUBSET_PASS seed_cases=96 assertions=52776 source_authenticated=0 physical_io=0

Each compiler also logged all 13 real function-scoped changed product C
mutants killed: extent-invalid-class, append-3568-cap, append-unknown-encoding,
append-over-capacity, seal-empty, seal-cursor, seal-zero-padding,
read-3568-cap, read-unknown-encoding, read-outside-payload, read-no-generation,
read-crc-invert, crc32c-implementation. The actual runner requires successful
compile before execution; only exit 1 with the semantic CHECK marker, no
ASan/UBSan/LeakSanitizer diagnostic or unrelated crash, counts as killed.
This exercises 96 deterministic patterns, full decoded byte/SHA identity,
CRC32C, 3568/3569 limits, metadata length/detach/attach refusals and payload-only
zero padding; it is not a physical read/write.

    ROUND052_CODEC_C_PASS baseline=2 real_source_mutants=26 host_subset=ONLY pinned_original_wrapper=COMPILED live_crypto_acomp_runtime=NOT_RUN source_authenticated=0

First codec error at repaired SHA: **none in terminal log**. No claim of
new local execution; this is actual remote rootless CI. At evidence
inspection, this SHA had 18 workflows: 4 completed success, 2 in progress,
12 queued; [native policy/project goals 44882508824](https://github.com/k1moradi/swapz/actions/runs/44882508824)
and [applicable matched original GPL module example 44882508663](https://github.com/k1moradi/swapz/actions/runs/44882508663)
were queued; [package 44882508814](https://github.com/k1moradi/swapz/actions/runs/44882508814)
was in progress. No all-green or current matched x86 y/n / original 66 UML
boot assertion follows. Later status checks belong in issue #172. This
Round055 document-only delivery does not requalify a later peer source SHA.

## Original source audit: why the decoder must outlive the zswap pool

The immutable original [mm/zswap.c](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zswap.c)
is decisive (blob ae19e301fced7e357a4c7587dfdd6abb890b9163).
Lines 100–110 select the writable compressor parameter. Lines 154–218 give
each pool a tfm_name, per-CPU acomp_ctx and percpu_ref; each entry has
swpentry, length, pool_idx, handle, objcg and LRU (not a durable algorithm
version or framing field). The entry pins its pool only while alive.
zswap_compressor_param_set (565–640) publishes a different current pool
and kills the old current reference; pool IDs may eventually be reused.
zswap_entry_free (777–785) frees the zsmalloc object and puts the pool
reference. Pool empty/release/destroy (406–448) remove the ID and free
per-CPU crypto transforms, zsmalloc pool and object. Never store pool_idx,
raw pool/tfm pointer, current compressor parameter, or zsmalloc handle as
a durable-to-read codec identifier.

acomp_ctx_alloc (822) resolves crypto_alloc_acomp_node(pool->tfm_name,0,0,node):
the chosen implementation is not established by the current user-visible name
alone. Use actual selected driver/format evidence, not a global label.
zswap_compress (856–936) calls crypto_wait_req, uses req->dlen and stores
actual bytes via zs_obj_write; errors or dlen >= PAGE_SIZE can instead store
the **uncompressed** PAGE_SIZE folio. Do not import that as compressed.
zswap_decompress (939–987) holds the pool's per-CPU context mutex and
zsmalloc SG lifetime, copies length == PAGE_SIZE directly, otherwise sets
the input length and output PAGE_SIZE, waits for crypto_acomp_decompress,
then requires success and dlen == PAGE_SIZE. Never keep its borrowed SG
addresses after zs_obj_read_sg_end.

Critically zswap_writeback_entry (1038–1086) secures the locked swapcache
folio, confirms the current xarray entry, decodes into that folio, erases
the entry and frees it, then marks the folio up-to-date and initiates
__swap_writeout/swap_write_submit. Ordinary subsequent disk reads have no
reason to retain that entry or decoder. A future optional source snapshot
must be copied under real source ownership BEFORE erase/free, not recovered
from a numeric cookie after writeback. Keep the ordinary full folio route
and its real error/order/lifetime semantics. Whether a genuine original
BIO-owned snapshot can carry the copied bytes without an independent hidden
swap count is a separate source/DM ownership problem, not solved here.

The pinned [mm/Kconfig](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/Kconfig#L60-L123)
defaults to LZO, with deflate, 842, LZ4, LZ4HC, ZSTD selections; the module
parameter can also request available crypto_acomp implementations.
[crypto/acompress.c](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/crypto/acompress.c)
bridges scomp and allocates named transforms. Actual source-specific framing:

| Selected implementation verified at source | Actual wrapper behavior at pin | Candidate policy |
| --- | --- | --- |
| lz4-scomp | [crypto/lz4.c](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/crypto/lz4.c) LZ4_compress_default and LZ4_decompress_safe, raw block | First feasible byte-format subset; existing host CI only, no live driver/owner qualification |
| lzo-scomp | [crypto/lzo.c](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/crypto/lzo.c) lzo1x_1_compress_safe and lzo1x_decompress_safe | Requires independent exact LZO1X stream contract, bounded decoder, terminal tests and real ownership; not LZ4 |
| lz4hc-scomp | [crypto/lz4hc.c](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/crypto/lz4hc.c) LZ4_compress_HC and same LZ4_decompress_safe | Potential same raw block format; separately verify selected implementation and framing before allowlisting; no HC execution claim |
| zstd | [crypto/zstd.c](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/crypto/zstd.c) independent stream/context/workspace with max window log 18 in this implementation | NO_GO until exact frame/window/dictionary/input consumption and decoder memory bound proven |
| 842, deflate, other driver, unknown format/version/dictionary | Not qualified here | Reject optional import; never reinterpret by name |

## Three policies and a minimal viable subset

1. **Existing full original uncompressed 4096 upper RAW** remains the only
   authorized source transport. Swapz may compress independently or store
   the raw full page under its existing policy. No changed default.
2. A future separately tagged immutable copy of actual source raw
   dictionary-free LZ4 block, 1..3568 bytes, could use existing bounded
   LZ4 decode and extent packing, avoiding second compression. Require
   source implementation/format profile, independent original page digest,
   exact decode, actual ownership and all lifecycle tests, not merely the
   same codec name or a recognizable prefix. Never label incoming STORED
   bytes RAW or apply inverse predictor to them. Retain full normal upper
   BIO until commit/abort; no production integration now.
3. A future opaque original codec-specific **lower** payload can avoid a
   second compression even if distinct from swapz LZ4, only with a verified
   immutable codec+format-version profile and decoder retained by the
   target, not the original entry. Begin with LZ4 only to bound scope.
   No new dependency or broad generic crypto-by-name auto-loader accepted
   in this round. LZO is plausible but not qualified. Optional import
   refuses >3568 even when <4096; current cap, record maximum 64, 1/2/4
   blocks, checksums, offsets and zero padding all stay unchanged. Larger
   incompressible payloads use original uncompressed 4096 path.

## Volatile mapping and decoder design (not implemented ABI)

Inspect [authority.h](https://github.com/k1moradi/swapz/blob/31adfb7ff57cc5c061304beae749b485d093130b/src/kernel/authority.h#L58-L139):
the actual swapz_map is **20 bytes**, asserted at compile time. It stores
start_block, generation, offset/raw CRC union, compressed CRC, length,
packed record_index and state bits. record_index high bits already encode
predictors; swapz_map_encoding returns LZ4 if delta64 flag absent. Adding a
new raw codec enum alone silently misclassifies it. authority.c
swapz_bind_compressed_record and publication only accept three current
encodings; codec.c swapz_encoding_valid likewise. Existing tx records
already carry bounded offsets, length, crc and encoding. No spare bit
reuse without auditing every equality/validation/cache/GC path. No
modification to authority.h or these fields in Round055.

Existing disabled [zswap-import-codec.h](https://github.com/k1moradi/swapz/blob/31adfb7ff57cc5c061304beae749b485d093130b/src/kernel/zswap-import-codec.h)
defines an immutable record with representation/version/codec/dictionary,
generation, STORED identities, CRC and original SHA, plus explicit
read-authority and disjoint scratch/output check. It only accepts LZ4
and models lower/ACK equality; [zswap-import-admission.h](https://github.com/k1moradi/swapz/blob/31adfb7ff57cc5c061304beae749b485d093130b/src/kernel/zswap-import-admission.h)
swapz_zswap_admission_try_live always returns -EOPNOTSUPP;
[zswap-direct-handoff.h](https://github.com/k1moradi/swapz/blob/31adfb7ff57cc5c061304beae749b485d093130b/src/kernel/zswap-direct-handoff.h)
is disabled too. Reuse these design constraints rather than add another
parallel transaction/batcher. Host scalar identities and count fields
are not actual ownership. No new source ABI proposed for immediate use.

Suggested future layout:
- Keep normal map 20 bytes, map encoding semantics unchanged. A distinct
  imported representation discriminator must unambiguously select imported
  RAM metadata. A separate bounded preallocated indexed sidecar keyed by
  current logical/generation/session is one candidate; exact in-map marker
  and all validation need review. Never infer it from a decoder failure
  or absent sidecar. A marked map with missing/ambiguous sidecar is EIO,
  not ordinary LZ4. If no safe compact discriminator, NO_GO until reviewed.
- Authoritative immutable map fields already convey extent, offset, length,
  compressed CRC and record index. Additional imported record needs stable
  format profile ID/version, dictionary profile (none initially), fixed
  decoded length 4096, independent full original SHA256, map generation
  and target session identity, plus lifecycle/reference state. Source slot
  incarnation, selected implementation identity, source bdev/sector and
  current DM acceptance must be validated separately at ingress and bound
  to the transaction; numeric values alone are not references. Retain
  independently authorized identity for as long as the associated mapping
  can be read, or prove why it can retire at commit; never dereference
  obsolete original pointers. Reserve descriptor capacity before write.
- A small per-target immutable decoder allowlist defines exact byte
  semantics, version and bounds. Pin each supported decoder implementation
  (and required module/crypto transform lifetime) before import acceptance;
  hold until all live imported mappings and in-flight reads/GC retire.
  Only bounded process-context request and decoder workspace pools, not
  per-map transforms or zswap pool references. Never allocate/resolve new
  algorithms in pressure/read paths. If unsupported/unavailable/workspace
  cap exceeded, refuse BEFORE commit. Do not unload decoder while referenced.
  No kernel dependency introduced now. LZ4 candidate uses already available
  kernel safe decoder; future LZO requires separate availability/lifetime
  qualification; asynchronous crypto requires wait/callback ownership.
- Size planning only: existing 20-byte maps = 5 MiB per GiB of logical
  4KiB pages, excluding other authority arrays. A 32-byte SHA on every
  page alone adds 8 MiB/GiB, a 4-byte dense index adds 1 MiB/GiB. Avoid
  expanding every map or pinning old zswap pools. Illustrative 64-byte
  imported-only descriptor budget times 4096 live/staged/retiring slots =
  256 KiB before lookup/allocator/decoder metadata; if a separate 2x
  preallocated lookup table uses 8-byte entries, add 64 KiB. Those are
  budget examples, NOT measured struct sizes/proposed actual limit. Account
  all staged/in-flight/obsolete readers, alignment, actual sizeof, checked
  multiplication, live imported count, registry contexts and worst-case
  scratch. A normal path fallback is required at the hard cap; no
  reclamation of live descriptors, waiting for MM pressure or unbounded
  heap expansion. Select cap once per target setup and report honest costs.
- Actual serial DM read has 4096-byte compressed+decoded scratch; parallel
  read slots have 4096-byte compressed scratch and distinct output pages,
  optional predictor scratch, plus 16KiB engine scratch for extent reads.
  Reuse existing owned scratch if capacity/no alias proven. LZ4/LZO-style
  synchronous safe decoders need bounded input and full 4096 output; any
  extra independent decoder workspace must be preallocated and accounted
  per concurrent reader, not per page. For initial LZ4 no new predictor
  or streaming history. Do not silently serialize parallel ordinary reads
  or charge large zstd workspace to every map.

## Read, publication, GC, teardown and error semantics

Actual [engine.c:2034–2197](https://github.com/k1moradi/swapz/blob/31adfb7ff57cc5c061304beae749b485d093130b/src/kernel/engine.c#L2034-L2197)
swapz_engine_read_page snapshots current map, checks valid nonraw
1/2/4-block geometry, bounds/cap/segment, reads resident payload range,
calls swapz_read_authoritative_payload against current authority, then
copies compressed bytes and returns verified CRC. Cached extent bytes are
not independent mapping authority. Actual [dm-target.c:10840–11012](https://github.com/k1moradi/swapz/blob/31adfb7ff57cc5c061304beae749b485d093130b/src/kernel/dm-target.c#L10840-L11012)
swapz_read AND swapz_read_slot_run directly LZ4-decode to full output or
predictor scratch and inverse transform; exact output length required.
Both paths need explicit exhaustive dispatch for any future imported
profile, including unknown rejection; neither currently dispatches other
codecs or verifies an imported full-page SHA. An import sidecar must never
route into default inverse delta branch.

Future single ordered-owner transaction, no duplicate batcher:
1. Under actual current source allocation/BIO and accepted current DM
   target/table ownership, snapshot original bytes and compression profile
   while upstream entry alive. Independent SHA256 from original full 4096
   locked page, compressed CRC, lengths and safe decode vs full-page
   identity before admitting. Preserve full ordinary upper BIO unchanged.
   Authenticate real bdev/sector mapping and target-relative eight-sector
   page, not numeric coincidence.
2. Reserve bounded descriptor/decoder and existing lower extent allocation.
   Copy compressed payload-only (1..3568 bytes) with zero padding using
   existing 4/8/16KiB packing/GC. A real durable lower WRITE must succeed
   under the reviewed persistence contract (ordinary completion alone
   must not be assumed power-loss persistence). Commit exactly one
   authoritative mapping plus sidecar atomically under ordered ownership;
   revalidate current generation/table/lifecycle after callbacks. Only
   then one genuine original upper ACK. No ACK from fabricated receipt.
3. For a later READ, mutually consistent current map/sidecar/session/
   generation snapshot held until completion; source pool can be gone.
   Verify extent geometry, complete expected compressed payload/read
   length, live map, validated CRC, supported profile and dictionary
   absence; dispatch to pinned safe decoder with strict output cap and
   format-specific complete-input consumption (reject truncated/concatenated/
   over-window/trailing data if profile disallows). Require exactly 4096
   output and SHA-256 equal to stored original independent digest; during
   qualification compare all original bytes. Copy to upper BIO only on
   success; exactly one genuine read completion. CRC or SHA do not confer
   authorization. A prefix/magic heuristic alone is not framing proof.
4. Actual [dm-target.c:8730–8771](https://github.com/k1moradi/swapz/blob/31adfb7ff57cc5c061304beae749b485d093130b/src/kernel/dm-target.c#L8730-L8771)
   swapz_gc_relocate_one snapshots map, reads current compressed bytes,
   passes verified CRC, length and encoding to gc_pending;
   swapz_gc_flush (8582–8607) writes window through existing engine.
   Therefore existing GC can already relocate a compressed payload without
   recompression, but only existing encoding is carried. Any future
   imported move must additionally transfer stable profile+digest+valid
   sidecar identity with exactly one new authoritative physical location
   under existing map/GC protocol; if generation changes, bind new key
   atomically and keep old readers pinned until drain. Preserve decoded
   page identity, checksum, counts and zero padding, no new decoder chosen
   during relocation. On GC/write failure keep old authoritative map and
   old decoder; release only unpublished staged record. No free/reuse
   block or descriptor until real references/IO drained.
5. Before optional commit, if validation/admission/lifetime/framing fails,
   discard optional attempt and use **complete original uncompressed 4096**
   normal route if still owned and safely ordered; no double ACK. After
   committed source retirement, a corrupt/supported-but-failing read has
   no magically available original page: fail EIO/EBADMSG with unchanged
   upper output, propagate through ordinary error/completion path, never
   fabricate zeros or reinterpret compressed bytes as RAW. On cancellation,
   swapoff/teardown close admission and drain callbacks/readers/GC, retire
   mappings exactly once, free sidecars then decoder owners. No hidden
   source ref that deadlocks pre-unuse, no persistent recovery assumed
   from volatile metadata after target/session loss. Real durable write
   remains necessary for the currently valid session; not a claim of
   crash-recoverable swap layout.

## Future evidence gates (requirements only, not executed now)

Reuse existing strict host tests; add targeted cases only when real future
decoder/ownership implementation exists: pinned exact LZO/LZ4HC source
producer vs selected decoder full 4096 byte+SHA across all admitted
profiles; length 0/3568/3569/4096, truncated/overlong/framed/external
dictionary/wrong-profile and valid compressed CRC but wrong original SHA;
pool switch/free/ID reuse before real read (old payload still correct under
independent decoder); two simultaneous codecs, serial and grouped read,
pinned decoder unavailable or attempted unload, hard metadata/scratch cap
and fail-before-mutation. Actual GC partial failure/roll-forward and ABA,
stale/duplicate callback, cancellation and teardown drain, atomic map/tag
publish and durable write failure; source/DM authentic ownership is its own
positive gate. Mutants remove real checks, compile and execute under both
strict sanitized compilers; no count padding or synthetic positive claim.
Original full kernel KUnit, matched original KDIR GPL dm and native
x86/ARM/policy/package/physical-safety gates remain required when triggered.

**Final no-go for compressed staging today:** SOURCE_MAPPED_AUTHENTICATED=0,
PHASE_A=BLOCKED, DIRECT_COMPRESSED_HANDOFF=DISABLED,
FORCED_RAW_BYPASS=DISABLED. Native Linux MM alone drives bounded zswap RAM
eviction; swapz owns valid SWAPSPACE2 disk compression/packing/GC. No second
reclaim, forced drain, new physical format or persistent metadata. Protect
the entire first physical 4096-byte SWAPSPACE2 header/signature/UUID and
parent partition table. No owner make test, make fast_test, privilege,
module load, device activation, actual pressure or physical-swap experiment.
