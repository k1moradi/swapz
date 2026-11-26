# Agent2 — native per-BIO observation contract (R094)

Immutable engineering reference efd77858cd20650213559ceb9cb4d0362db32ea5;
original Linux c339f4010dea8b0d754f84ace70cd1b089878ef8.
This is a proposed offline **observation-only** v1 profile, not a producer
implementation, authorization, trace interface, or disk format. No kernel
code, trace activation, device access, or ordinary helper changes. A3/A11
can review the requirements independently; no same-round peer input used.
A future producer must be separately reviewed, source-bound and qualified.
The frozen sources cannot emit this complete stream today.

## Wire and safety contract

One UTF-8 JSON document, stdin only; explicit expected canonical scope
SHA-256 passed as the sole CLI argument, obtained independently of the
capture (caller-supplied, not an authenticated trust root). Canonical scope
serialization is ASCII JSON with sorted keys and no spaces. Exact fields
throughout; reject duplicate JSON keys, invalid constants, malformed,
truncated or oversized input, unknown fields, noninteger/bool numeric
substitutes, wrap/range violations and lost/overflow records. Max 4 MiB,
8192 events, 1024 distinct operations, 4096 selected logical pages.
One target and route incarnation per stream, initially empty generation
zero, nonzero logical range (page zero excluded). No aggregate inference.

Envelope: schema swapz-native-bio-observation-v1, scope, initial
(empty=true,generation=0), events, footer
(records,last_id,lost=0,overflow=false,truncated=false). Scope: source
(product SHA), linux_source, mapping_source (frozen reference SHA),
kernel_sha256, module_sha256, workload_sha256, run_nonce, target (opaque
128-bit identifiers), session, epoch, target_epoch, registration_epoch,
first_logical, page_count, profile=M3568. Future source claims must match
the separately supplied scope digest; this does not establish that the
actual producer or captured binary matches the claim. Re-review source map
on producer changes. M4095 and unrelated routes are not accepted.

Each event has id (contiguous 1..N, no wrap), scope_sha256, event, op
(nonzero opaque integer transaction ID), key, data. Key is stable across
one operation: descriptor, bio (selected clone), original (original BIO),
logical, swap_type, slot (offset), area_epoch, store, generation. Three
distinct, nonreused opaque per-run 128-bit identifiers; GC uses retained
source record provenance, not a second BIO. Never serialize pointers,
pointer hashes, actual device IDs, host identifiers, page contents or
addresses. Allocate opaque identifiers independently of addresses; lifetime
and actual identity must be established at the producer. A hash-shaped
string alone cannot prove that its producer followed this rule. Parser emits
only fixed reasons, record ordinals, counts and immutable mapping reference.

Payload tuple: tag=90 (0x5a), codec=1 LZ4 or 2 LZO1X, version=1,
dictionary=0, length=1..3568, decoded_length=4096, sha256 of exact
compressed bytes, page_sha256 of the independent original full page.
Ordinary RAW_4096 is tag/codec/version/dictionary=0, length=decoded_length
4096, both digests identical. It is **not** compressed bytes. Lower
requested/completed length is 4096 (one dedicated extent), distinct from
compressed length. Extent, lower request and pin IDs are opaque nonreused
per-run tokens, not sectors or addresses. Lower status normalized 0..255
(0 success), never an errno silently coerced to zero.

## State and observation rules

The parser is a conservative bounded profile, with accepted operations in
one FIFO, no overlapping operations for one logical page, no reusing
extent IDs, no multi-page DISCARD or ordinary compressed/zero fallback
claim. For future native traces outside this profile, BLOCK rather than
approximate. The frozen contract does not require changing product scheduling
to satisfy this observational subset. The profile serializes final release
before next operation progresses; asynchronous deferred releases that do
not fit must be handled by a later reviewed extension, not reordered by
the collector. Producer observes actual sequence; never sorts events to
create a passing history.

- evict: capture exact natural-MM preerase retained bytes and independent
  original-page oracle; bind to actual original BIO and accepted descriptor
  via opaque IDs, emit once the correlation is available, before accept.
  accept: actual FIFO ownership, operation typed_write / typed_read /
  overwrite / discard, raw_sha256 non-null only for ordinary overwrite.
  Non-accepted MM refusals are outside this profile. No inferred origin
  from counters or decoded equality.
- reserve: exact monotonically increasing credit and selected extent.
  claim: exact same credit, once at ordered head; refuse only before claim;
  cancel only refused reserved never-issued verified tail (tail_verified),
  no sequence rewind. fallback after refusal and completed cancellation
  only, ordinary full-page RAW fixture subset, not forced RAW.
- lower_submit: exact lower/extent/requested_bytes/payload_length/
  payload_sha256; lower_complete: same lower ID, completed_bytes, status
  and observed payload_sha256 (null on failed/short transfer). A lower
  write's digest records the actual buffer, not an inferred readback.
  Successful write requires actual full completion then successful flush
  (status), then publish (extent, full payload, generation, gc_epoch).
  Any short/error/flush failure blocks success, requires issued extent
  quarantine (extent), no fallback or publish. This profile requires
  explicit flush even if a future FUA-only producer could prove durability.
- typed_read: pin (pin, extent, gc_epoch) current authoritative typed
  record, actual lower read and exact compressed digest, oracle
  (decoded_bytes, compared_bytes, decoded_sha256, expected_sha256,
  byte_equal, decoder_status), successful pin_release (pin,status)
  before ACK. Independent full-page oracle must compare all 4096 bytes;
  digest equality alone is not a byte-oracle observation. Failed decoder,
  wrong digest, short read or incomplete comparison cannot ACK success.
- GC: gc_begin (old_extent,gc_epoch) current record key; pin, actual
  gc_read_submit (lower,extent,requested_bytes), gc_read_complete
  (lower,completed_bytes,status,payload_sha256), verified same bytes,
  distinct lower write/flush before publication with unchanged payload,
  map generation +1 and GC epoch +1 (both checked against wrap). Pin
  release then release; no upper ACK. Failed read prevents new allocation;
  issued failed write quarantines destination. Prior authority not replaced
  by a failed relocation. This is a dedicated single-extent profile, not
  proof of sustainable packing or capacity.
- overwrite: ordinary RAW fixture full-page lower+flush, newer generation
  publishes once. discard: current slot/store, generation +1, exact
  authoritative invalidation, no claim of lower TRIM. Subsequent stale
  typed reads refuse. ACK (status) exactly once per accepted upper BIO,
  success only after publication/read oracle/discard; release once after
  native completion and final descriptor/candidate debt retirement.
- cleanup last event (op=0,key=null): route_revoked, rcu_drained,
  worker_drained all true; caps,tickets,decoder_pins,reservations,
  pending_bios,live_maps zero; quarantined_extents equals observed issued
  failure debt. These are explicit producer observations (including target
  map teardown), not proof of safe physical cleanup. No new operation
  after observed failure; clean-format failure trace returns exit 2 with
  first event ordinal/category, as does inconsistent evidence. Valid
  observation-only fixture returns exit 0, never physical admission.

## Actual frozen source map — observations still missing

All line ranges below refer to immutable engineering freeze; patch hunk
numbers refer to repository patch text, not a claim of a running kernel.

| Event / source | Actual frozen boundary and missing proof |
| --- | --- |
| Natural eviction / retained bytes / original BIO | tests/tools/round091-original-mm-eviction.patch (94bb74549c54a614406b71f28a9e8e8c22527d6a) swapz_mm_eviction_key, swapz_mm_capture, swapz_mm_preerase (41,129,250); tests/tools/round089-original-mm-carrier.patch (059d1bf29cf4990e22a2f608d5d552abeec3a8d1) swapz_mm_read_source, swapz_mm_candidate_get, swapz_mm_preerase (185,233,246); R092 module-boundary patch (62db468c14f23b59e7adaae65a11dcb9969f02b3) retains provider/carrier and candidate pins. Missing source-bound nonpointer correlation, separate compressed SHA-256 and independent full-page oracle at natural preerase and original/clone lifetime. |
| Accepted descriptor and route | src/kernel/dm-target.c (27d3af6f4146bc62adfb091e0d4f1fbc9f1dd285) swapz_round090_candidate_get (14821), swapz_map (14885), retained under queue_lock and canonical incoming list_add_tail (15156–15160); accepted clone route checks at 12562–12615. Missing accepted-only IDs, target/session/table/registration identity and source key in a loss-detecting stream. |
| Reserve/claim/refuse/cancel | dm-target.c 12523–12543 and 12621–12710; swapz_round091_ordered_claim_permitted returns false at 12552–12555. src/kernel/zswap-original-ticket.c (7ba56c5ee602853c8d0717f23aad9efc69d111ea) reserve 158, seal 199, claim_under_queue_lock 309, cancel 382, put 404; src/kernel/zswap-original-storage.c (1f9030030f5d0fb3b06d0b0a159dd8aa6818f8dd) reserve 569, cancel 550, commit 544. Missing exact actual credit/descriptor/refusal/cancel observations. Hard gate remains false. |
| Lower completion / durability / publish | storage.c shared_commit 504–541 (actual write, completed count, flush, authority finish); src/kernel/zswap-original-storage-value.c (8f532824e9c63a6498d71fcb1ce4c35b18130f1e) callbacks 160–188, reserve/cancel/commit 234–262, adapter not integrated at freeze; dm-target.c swapz_kernel_lower_flush 3635 and swapz_issue_flush 3642. Missing request/buffer/completion identity at lower boundary, observed flush return and exact post-authority map publication, issued quarantine. |
| Typed read / GC | dm-target.c swapz_round091_read_original 11315–11375, swapz_gc_relocate_one 9173–9210; storage.c shared_read 619–645 and relocate 679–704 (actual read, CRC, padding, new generation and epoch); value adapter decode_pinned 330 and relocate 376. Missing actual lower read digest, pin IDs, independent full-page compare, source/destination GC association and generation/epoch publication. |
| Overwrite / discard / ACK | src/kernel/authority.c (14fe52cf4cf28f18568d3bf2b6ced449c9c182a3) map transition commit around 2644, swapz_discard_page 3034–3115; dm-target.c swapz_discard 11596, swapz_complete 2367–2432, release candidate 2342–2364. Missing ordered old/new generation, postcommit/debt IDs, actual final status at bio_endio, and deferred release completion. Counters at 12692–12696 are not per-BIO evidence. |
| Cleanup | dm-target.c swapz_dtr 15510 calls swapz_drain/free; broker close/destroy in ticket.c 450/465; storage.c close 706. Actual built-in owner and guarded setup absent at freeze; missing witnessed route revoke, RCU/worker/cap/ticket/decoder/debt drain and quarantine accounting. |

Future producer must capture bounded loss/truncation metadata and consistent
scope independent of record content. The capture is not physically or
cryptographically authenticated; source mapping must be rechecked against
actual pinned source, binary hashes, protected header/UUID/table, real
device ownership and workload before any separate admission review. None
is performed here. AUTH=0, Phase A BLOCKED, compressed handoff, forced RAW,
import OFF. Existing R093 aggregate parser and ordinary helper unchanged.
