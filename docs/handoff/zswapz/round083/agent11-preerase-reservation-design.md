# Round083 Agent11 — original MM pre-erase reservation and selected DM handoff

**Design-only, unapplied.** Inspected product 039d67757a7a432a4751fa025f5922e786fbf38b (parent 78af69394400417fa06fd515ba046e07b161cd8e), original Linux c339f4010dea8b0d754f84ace70cd1b089878ef8. Independent of Agent5's eventual on-disk geometry: assume a consumer capable of accepting an immutable original stream of at most M bytes, with M=3568 today as a validation ceiling only (production import inactive); M=4095 is a separately proposed capacity, not an enabled value.

**Decision:** GO for a future separately authorized, disabled-by-default integration prototype with a bounded optional sideband and ordinary full-page fallback; NO-GO for production import, bypassing decompression, replacing ordinary BIO, direct submit to an early DM pointer, or total accepted BIO queue cap. No existing production interface proves the required end-to-end identity. This document specifies that missing seam, not a claim that it already exists.

## 1. Actual source trace and trust boundary

Original immutable source links below refer to Linux c339f4010dea8b0d754f84ace70cd1b089878ef8; product links refer to 039d67757a7a432a4751fa025f5922e786fbf38b. Blob IDs were obtained from connector reads of the named immutable files. No kernel execution or compiler check in this round.

| Source anchor | Source-proven behavior / implication |
| --- | --- |
| [mm/zswap.c:1122–1181](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zswap.c#L1122-L1181) | LRU callback copies swpentry and rotates before releasing LRU lock. Entry pointer may become stale; must not dereference before writeback's XArray validation. |
| [mm/zswap.c:1005–1051](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zswap.c#L1005-L1051) | get_swap_device returns NULL/error or live si; __swap_cache_alloc_folio uses existing GFP_KERNEL path; put at1024; locked folio subsequently protects slot and swapoff. Failed allocation or concurrent swapin returns original error. Same XArray entry pointer checked before dereference. |
| [mm/zswap.c:202–220,777–793](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zswap.c#L202-L220) | Stored entry has swpentry, length, pool_idx and handle, not a persistent unique store generation or selected compressor driver ID. Stored entry pins pool, free releases handle/pool/objcg. Never pass entry/handle/pool pointer to consumer. |
| [mm/zswap.c:822,870–935,1440–1498](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zswap.c#L870-L935) | Per-CPU crypto acomp allocated by pool compressor name, actual request runs under its mutex; on compression failure/zero/length>=PAGE_SIZE, stores full uncompressed page. zs_obj_write writes chosen bytes, entry length assigned. Pool name alone cannot certify producer driver/version. Capture exact allowlisted driver/profile at successful compression, not writeback from a different CPU's transform. |
| [mm/zswap.c:939–988](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zswap.c#L939-L988) and [mm/zsmalloc.c:1125–1185](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zsmalloc.c#L1125-L1185) | Actual SG read begin resolves handle under pool read lock, takes zspage migration read pin, releases pool lock and returns one or two SG entries; end releases zspage pin. Entry lifetime separately guaranteed by folio. Actual decompress holds acomp mutex and waits crypto; our optional copy must not extend SG pin across new slow work. |
| [mm/zswap.c:1053–1094](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zswap.c#L1053-L1094) | Original decode into locked folio, then erase and free, mark uptodate/dropbehind, drop extra folio ref, __swap_writeout and swap_write_submit. Failure before erase deletes temporary cache folio, unlocks and puts; original source is retained. No post-erase lookup can reconstruct authentic compressed bytes. |
| [mm/swapfile.c:311–342,1860–1928](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/swapfile.c#L311-L342) | Actual extent translation sector=(start_block + offset-start_page) << (PAGE_SHIFT-9). get/put pins swap device, but pre-get and post-put can race swapoff+swapon without another fence; locked cache folio is documented fence. Never assume sector=slot*8 for arbitrary swapfile or partition. |
| [mm/swapfile.c:3240–3288](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/swapfile.c#L3240-L3288) | swapoff try_to_unuse precedes kill users, synchronize_rcu, wait completion, destroy extents and zswap_swapoff. Do not introduce a new user ref held through a wait on swapoff itself. |
| [mm/page_io.c:338–393,501–515,596–623,699–707](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/page_io.c#L338-L393) | __swap_writeout starts PG_writeback then unlocks; swap_add_folio allocates existing GFP_NOIO sio and bvecs from full folio. bdev submit creates REQ_OP_WRITE|REQ_SWAP, actual translated sector; synchronous device waits and calls end; async sets existing endio. On failure swap_write_end redirties folio, clears reclaim, ends writeback. Preserve exactly those semantics and one sio disposal. |
| [block/blk-core.c:622–635,763–792,843–848](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/block/blk-core.c#L622-L635) | Partition remap adds start sector; nested submit may defer through current->bio_list, so submit return is not proof map ran synchronously. Initial scope excludes partitions, stacking, alternate swap_ops, multipage/merged/split requests. |
| [drivers/md/dm.c:2667–2705,684–702,2074–2102](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/drivers/md/dm.c#L2074-L2102) | dm_get_md pins mapped_device holder, NOT selected table/target. Actual DM submit gets live table under SRCU; suspended I/O queues normally. SRCU protects pointer during read-side, not future selection after unlock. Never hold SRCU across ordinary BIO submission, wait or worker ownership. |
| [drivers/md/dm-table.c:1565–1583](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/drivers/md/dm-table.c#L1565-L1583), [dm.c:1730–1769,613–654](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/drivers/md/dm.c#L1730-L1769) | Actual target chosen by interval and length, clone gets tio->ti and part0 bdev; splitting and flag handling occur before map. Final authority must be at actual selected clone, not early lookup or BIO flag alone. |
| [dm.c:2965–3054,2879–2890](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/drivers/md/dm.c#L2965-L3054), [dm-table.c:182–211](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/drivers/md/dm-table.c#L182-L211) | Suspend blocks new I/O, synchronizes SRCU, drains pending I/O; table swap requires suspended md; table destroy calls dtr then frees target/table. Early reservation cannot wait for late map while pinning old table through suspend. |
| [dm.c:1406–1461,903–942,1092–1148](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/drivers/md/dm.c#L1406-L1461) | SUBMITTED gives target ownership. KILL/REQUEUE frees clone and decrements pending; REQUEUE may become IOERR. Optional REQ_SWAP down() can sleep; target lacks NOWAIT. clone_endio handles target callback, releases semaphore and clone then original pending. |
| [product dm-target.c:2212–2266,14048–14139](https://github.com/k1moradi/swapz/blob/039d67757a7a432a4751fa025f5922e786fbf38b/src/kernel/dm-target.c#L2212-L2266) | Existing staged Round063/064/065 owner acquisition is conditional test-only. Checks actual target, whole mapper, zero begin, exact 8 sectors and current route; rejection puts ref before ordinary return. Useful insertion points but NOT deployed authority. |
| [product dm-target.c:13942–14286,2268–2348,14289–14365,14495–14504](https://github.com/k1moradi/swapz/blob/039d67757a7a432a4751fa025f5922e786fbf38b/src/kernel/dm-target.c#L13942-L14286) | Existing map validates one-page geometry and enqueues under queue_lock then SUBMITTED. Complete releases prep and ends BIO; deferred completion retains upper ownership; drain closes queue and waits workers/lower, dtr frees context. No total admitted BIO cap. |
| [product authority.c:3673–3715,4071–4105](https://github.com/k1moradi/swapz/blob/039d67757a7a432a4751fa025f5922e786fbf38b/src/kernel/authority.c#L3673-L3715) | Dormant private import authority is not ordinary map, GC or actual upper BIO; modeled receipt is not physical durability. Import-admission older mock try_live returns -EOPNOTSUPP. Existing decoder owner provides separately retained get/put/close, not source authentication. |

**Source identity gap:** actual current zswap entry has no independently unique monotonic store identity or actual producer codec ID; source pool index and entry address are reusable. Actual target selection occurs AFTER original source free. Existing ordinary BIO has full original page and no authenticated transfer object. Need both a pre-erase producer credential and an actual-clone claim; neither one alone is authority.

## 2. Chosen interface: optional two-phase ticket, not a second write path

Compare alternatives: (A) direct pre-erase I/O to an early selected DM pointer is NO-GO: bypasses real DM pending accounting, risks suspend SRCU/queue deadlock and cannot guarantee actual selected target. (B) global lookup by slot/sector/folio pointer at map is NO-GO: ABA, split/reissue/cross-device ambiguity. (C) recommended candidate: attach opaque typed ticket to the ordinary full-page writeout from original MM, explicitly propagate provenance through the actual core original-BIO/clone relationship, and claim only on the real selected target. Keep decompression and full-page BIO as fallback. Sideband carries original compressed bytes, not the BIO payload. No new direct MM-to-disk writer and no forced RAW. If conventional fallback uses normal swapz compression, that is not accepted-original recompression.

Future declarations (illustrative kernel C, NOT applied or compiled):
```c
struct original_ticket;             /* opaque refcounted broker slot */
struct original_route_cookie;       /* value, no borrowed target pointers */
struct original_consumer_caps {
    u32 max_payload_bytes;          /* <= 4095, current ceiling 3568 */
    u32 max_tickets;
    u64 max_copy_bytes;
};
/* Positive result is an optional reservation, no BIO acceptance. */
int original_try_reserve(const struct original_route_cookie *route,
                         u32 original_len, u8 codec, u8 version,
                         struct original_ticket **out);
int original_copy_and_seal(struct original_ticket *ticket,
                           const struct original_source_identity *source,
                           const struct scatterlist *sg, unsigned int nents);
/* Transfer to dedicated one-page sio before erase; no allocation here. */
void original_attach_move(struct swap_io_ctx *ctx,
                          struct original_ticket **ticket);
/* Called by DM core only for exact original BIO / whole current clone. */
struct original_ticket *original_clone_try_get(struct dm_target_io *tio);
/* Called at actual swapz incoming publication under queue_lock. */
bool original_claim_locked(struct swapz_dm *ctx, struct swapz_bio_ref *entry,
                           struct original_ticket **candidate);
/* Unclaimed cancel or release owner's one ref; never waits. */
void original_ticket_put(struct original_ticket **owner);
```

Contract: initialize outputs NULL. Return 0 with owned reservation only on success, otherwise -EOPNOTSUPP (feature/profile/device/geometry), -EMSGSIZE (length), -ENOSPC (credits), -EAGAIN (trylock contention/revoked route), -ESTALE (identity), -EBADMSG (integrity). Declines are optimization outcomes, **not returned to original shrinker as new errors**. No DM_MAPIO_REQUEUE for credit exhaustion. No spinning/retrying on optional contention. Fatal original decompression and native errors retain existing MM behavior. All ownership-taking APIs use explicit move/NULL; any failed claim leaves candidate with caller to put outside locks. Actual source code implementing these names is absent; do not link them until approved.

**Early route:** while validated locked order-0 folio pins swap area, require PAGE_SIZE=4096, normal block swap_ops, whole bdev equal to selected md part0, no partition, no layered target, target begin=0, one eligible registered consumer, checked interval/sector count=8 (subtract before compare), logical index within ctx capacity, exclude header/reserved logical page. Compute exact sector using existing extent helper. Use a short DM-core SRCU snapshot, not a saved SRCU index, to check current target registration/capability and copy immutable cookie {md instance epoch, active table epoch, target-instance epoch, bdev identity, begin,len, logical sector}. Do not trust dev_t alone, target name or function pointer alone; validate a registered type/instance. dm_get_md holder put immediately after snapshot; no pointer to md/table/ti/ctx survives snapshot. If safe nonblocking lookup/try-get cannot be built, decline. No external untyped bdev->private_data cast in MM.

**Independent broker lifetime:** preallocate a bounded global/session broker in sleepable setup, never from shrinker. Registration publishes only a value identity and refcounted independent broker capability, not a target pointer. Epochs must not wrap/reuse within session: disable optimization on exhaustion. Closing target revokes capability with release/acquire under broker state synchronization before table detach; all unclaimed tickets hold only broker slots, not target refs. Revocation marks them nonclaimable, but cannot recycle their bytes until last carrier ref drops. Broker memory/module stays alive until remaining holders put; target dtr never waits for unclaimed tickets or for BIOs deferred by DM suspend. On module unload, unregister entrypoints, synchronize readers then drain broker refs outside target/suspend/MM locks; if drain not proven, module removal refused or pinned, no forced free. This may temporarily retain bounded memory; it cannot stall ordinary progress. Global budget includes revoked sessions, not N per reload without a global cap.

**Source credential:** propose opt-in immutable {swap-area activation epoch, swp_type, offset, unique successful store sequence, typed producer codec/version, length, original-page digest}. Store sequence is generated in MM at original store while folio ownership valid, before XArray publication, never inferred from DM generation or object pointer. Need audit existing swap area init/teardown for epoch and folio-slot locking; if unavailable, refuse. Use per-stored-entry sequence (e.g. u64 monotonic allocator) rather than full second per-slot map; source authority must accompany actual folio transaction. Source token is created ONLY after existing XArray equality under locked folio; include original identity and source store seq from the now validated entry. Store exact producer algorithm driver/profile at compression while actual acomp context is selected, before publishing entry; raw, unknown, alternate provider, unsupported version/dictionary => no candidate. Capture original SHA256 at store (or separately verify equivalent original-source integrity seam; conservative first prototype requires store digest). Hash original full page while source folio is stable; no new crypto allocation or wait under spinlock/SG pin. SHA is integrity, not a substitute for trusted kernel ownership. No source pointer in exported ticket. Source/DM/GC epochs independent, never bit-cast or match by numeric coincidence.

**Reservation, copying and sealing:** after line1051 and before erase, use bounded try-reserve with length 1..M and strict length<4096, exact codec profile and early route. Reserve actual physical buffer slot plus ticket/byte credits atomically under one short broker trylock; no reclaim allocation or caller wait. Keep folio locked, use entry's existing pool pin and zsmalloc SG begin/end; copy exactly length using verified 1 or 2 SG spans (existing memcpy_from_sglist or bounded SG helper), no padding bytes treated as source. Check byte count, no alias, no arithmetic overflow. End SG read before slow CRC/SHA/independent decode; do not hold pool/XArray/SG/queue spinlocks over any new crypto or callback. No new acomp mutex needed for copy; original decompression unchanged. Seal only after exact source decode succeeds into original folio and stored digest matches it; verify compressed CRC and immutable input. Candidate decode/validation uses independent decoder, not pool transform, preferably worker before lower submission; any verification failure before claim can decline while full folio remains. Do not fabricate dormant read-authority/ACK fields to validate a not-yet-written record: factor a pure checked decode primitive out in a future consumer patch. Release SG on all exits; if copy failure, cancel ticket and run ordinary existing decode, erase/free/writeback; if original decode fails, cancel and original err path with source intact. No successor guarantee until locked folio valid.

**Carrier:** preallocate sideband slot alongside broker ticket, not a new allocation in ->map. Add optional typed pointer/ref to private swap_io_ctx/sio and explicit opt-in BIO field or equivalent core-managed extension, with init, clone, split, reset/uninit and terminal disposal hooks audited. Dedicated empty local ctx is already used by zswap_writeback_entry; require exactly one original 4096 folio and no merge. Move ticket into ctx before xa_erase only after valid full folio, then original erase/free/uptodate/dropbehind/folio_put/start_writeback/unlock. Ensure no extra folio reference changes dropbehind semantics. Original sio owns one carrier ref through synchronous/async completion; bio_uninit must detach according to one ownership rule, not duplicate sio release. Only actual original MM writer can create extension; clone cannot mint by copying arbitrary bi_private. Generic unsupported paths may strip/decline optimization safely while ordinary BIO intact; no transfer through partitions, stacked/remapped, split/partial or reissued clones. Reject scope mismatches at actual map; never look up ticket by sector, pointer, REQ_SWAP or flag alone. If BIO is blocked/deferred by suspend or current->bio_list, it retains bounded independent carrier until actual claim/refusal/endio. No reliance on task-local context or submit_bio returning after map.

**Actual selected claim:** in DM split processing at 1736/1769 use actual cio/ti (ci->bio and dm_io orig_bio relationship) under live table SRCU. Require whole origin unsplit exact one bvec/folio (offset 0), original op WRITE/REQ_SWAP, expected current part0 and sector 8-sector span, matching origin cookie and actual registered target/table epoch, exact source carrier token and one-shot eligibility. Explicit candidate ref retained before invoking map; DM core owns it until handed to actual target or dropped on KILL/REQUEUE/partial/refusal. Never call MM slot validators under queue_lock. In swapz_map, validate source/route outside queue_lock, then under existing lock recheck accepting/current epoch and one-shot token, claim and link same upper descriptor in incoming in one transaction. Lock ordering: choose queue_lock then nonblocking atomic ticket CAS (no broker lock under queue_lock); reservation cancellation/revocation must use compatible atomics, not reverse nested locks. Candidate on any miss removed/put outside lock; normal map proceeds once with original page. If target itself is terminal failed, retain existing native rejection, not a fabricated success. Claim only at actual enqueue; disable existing submitter compression/prep fast path for claimed stream and send to ordinary ordered owner with typed representation. Unclaimed slot remains ordinary. One actual clone, one acceptance, one completion; no second BIO.

## 3. Linearization and ownership

| State / point | Owner and protected resource | Permitted successor |
| --- | --- | --- |
| STORED | Original MM locked folio after XArray validation; source entry pins pool | reserve or ordinary |
| RESERVED | Producer holds broker slot+byte credits, no target BIO | copy or cancel |
| COPIED | Producer owns immutable bytes after SG end | seal or cancel |
| SEALED | Original decoded folio verified, producer source credential fixed | carrier move before erase or cancel |
| CARRIED | Original sio owns ticket ref; full page valid; original source may be erased | actual selected clone candidate or decline |
| CANDIDATE | DM core short-lived ref under actual table SRCU | atomic claim+enqueue, or put |
| CLAIMED | Existing upper descriptor owns ref; one outstanding upper debt; actual selected epoch frozen | ordered validation/write or terminal error |
| LOWER_INFLIGHT | Ordered transaction and callbacks own lower staging, independent decoder/GC lifetime | durable then publish, or fail |
| PUBLISHED | Current typed authoritative mapping owns decoder/profile and disk extent; source copy can be released once lower/validation readers done | once-only upper completion |
| ACKED/FAILED | Sole upper completion owner detaches ticket and prep before bio_endio; no access to clone private memory afterwards | broker final put when remaining refs zero |
| CANCELLED | No imported map or second write; stale carrier may still hold ref | final put, ordinary fallback if not claimed |

Ticket's atomic state (reserved/sealed/claimed/cancelled) governs claim, separate refcount governs lifetime. No reclaim of slot until last ref; release credits on final put exactly once under broker lock, never at list splice, defer or lower submission. State after claim tracked by existing ordered owner; completion gate CAS/serialized terminal transition before upper endio, actual DM core propagates clone status to original. A successful lower write is not itself an upper success. A failed lower callback must not become success on teardown. No pointer used after bio_endio may retire clone-local data.

Generation ordering: store credential frozen while MM owns folio; after erase do NOT demand live XArray still equal old entry. Validate explicit exact originating BIO/slot/folio transaction instead, plus current target route at actual claim. Preserve PG_writeback lifetime, standard swapcache/slot rules and normal ordered logical generation at target publish; ensure discard/overwrite/slot recycle cannot publish stale imported mapping. If stronger generation fence needed in actual kernel (especially invalidation during outstanding writeback), add a separately audited MM generation/slot-lifetime hook before any implementation GO. Do not hold source lock across lower I/O or artificially retain source folio beyond original writeback. No claimed imports visible until ordered commit; replacement/GC readers use current mapping generation and pin old representation/extent through last reader. Independent decoder lease through map lifetime and GC, not original zswap pool.

## 4. Lock/refcount and progress contract

| Context | Required ordering and prohibitions |
| --- | --- |
| zswap shrinker | LRU lock dropped before original writeback; existing locked folio validation. No added waiting or reclaim allocation, no cross-call into blocking target. |
| producer route | folio lock -> short DM SRCU snapshot -> release; no suspend_lock, no table/target refs carried, no submission while SRCU held. If lookup needs blocking, decline. |
| reserve/copy | broker trylock -> reserve -> unlock; then separate original pool read/zspage pin -> bounded copy -> end; no nested broker/SG/queue/XArray locks. Existing original decode can sleep in its own documented context, not a new wait. |
| actual clone | DM SRCU -> validate candidate (no MM spinlock under queue lock) -> queue_lock -> atomic claim + enqueue; release queue_lock before puts or worker work. No extra synchronous lower submission/wait in map. |
| ordered consumer | existing ordered owner handles validation, extent reservation, lower submission/durability, map/GC publication; do not wait for own callback while holding lock callback needs. Allocate all required scratch/transaction credit before accepting if consumer cannot guarantee bounded progress; else decline optimization. |
| teardown | revoke early registration, reject new claims; existing DM suspend crosses SRCU then drains admitted BIO; dtr drains lower/deferred/GC/decoder outside locks, never waits for unclaimed deferred carriers. Close independent decoder only after imported map/GC leases can retire; late get denied. |

Reservation credit cannot promise disk-space availability unless consumer explicitly reserves appropriate bounded staging/transaction capacity. Producer is not allowed to reserve actual disk space under MM/SG locks; abstract consumer must either furnish a preallocated credit promising a legal ordered path, or decline. Exhaustion fallback ordinary I/O uses existing DM semantics; no target cap, no waiting for ticket replenishment, no additional shrinker, no new timer. Existing normal DM throttle may sleep; no claim overall reclaim is wait-free. No additional dependency cycle introduced by early reservation because no live target pointer, no suspend wait, no hold across map, and exhaustion never blocks ordinary submission. **Actual forward progress remains unproven** until core carrier propagation and consumer staging/GC/ordered drains are exercised. Prefer asynchronous worker submission only, not inline ->map lower waiting (product comment at9777–9778 and original block nested submit behavior).

## 5. Explicit worst-case budget (not a discovered safe operating quota)

Let N = global max outstanding broker slots (reserved + carried + claimed + revoked but retained), M = per-slot byte ceiling, B = independent byte credit, C=sum reserved/owned lengths across all live slots. Require N and B before accepting a reservation; checked arithmetic C<=B, n<=N; use if len>B-C rather than unchecked C+len. Charge reservation length immediately, release exactly once at last put. Every held physical buffer counted even if bytes not yet copied. For fixed contiguous slots, S=ALIGN(M,A) and actual resident buffer capacity N*S regardless of C. Choose A=64 only as illustrative alignment, not measured kernel cacheline; 3568 -> S=3584, 4095 -> S=4096. For N=8 illustrative, B=N*M gives 28,544/32,760 logical bytes; resident copy array 28,672/32,768 bytes (28/32 KiB). At N=64: 228,352/262,080 logical bytes; allocated payload 229,376/262,144 bytes (224/256 KiB). Not a recommended production limit. Avoid physically contiguous high-order allocation under reclaim; setup may use virtually contiguous array or preallocated pages, fail setup closed, no fallback per-copy allocation. One slot per ticket, free index stack/bitmap, zero or scrub before reuse outside lock while slot reserved; no payload zero-init penalty on hot path except security/physical pad obligations.

Worst-case incremental RAM, in bytes:
```
M_total = N*S + N*sizeof(ticket_header) + sizeof(free_index[N])
        + broker/registration/session overhead (bounded R)
        + E*delta_zswap_entry_size + A_swap*delta_swap_area_size
        + Q*delta_carrier_fields + U*delta_dm_private_fields
        + W*scratch_bytes + K*transaction/staging_bytes
        + J*import_map_sidecar_bytes + G*old_reader_pin_bytes
        + allocator_rounding + any additional workqueue/module overhead
```
E is number of resident original entries carrying new immutable source fields, A_swap active areas; Q existing sio/BIO count, U accepted upper outstanding, W worker scratch concurrency, K independent lower transaction/staging count, J live imported logical records, G old-reader/GC snapshots. These are distinct quantities, not all bounded by N (particularly map lifetime J and ordinary BIOs U). Proposed original identity/digest adds at least u64 store sequence + 32-byte SHA256 + codec/version bytes = 42 semantic bytes per eligible entry if stored inline; actual struct padding/slab class may increase all entries even disabled, so prototype must measure and budget or use opt-in sparse metadata with its own allocation/cap and decline when absent. Do not allocate unbounded per-entry metadata; prefer compact fields, explicit budget and no failure of ordinary store. Existing ordinary map exactly20 bytes (authority.h static assert), no new per-slot generation table assumed. Existing prep capacity max64 and quantum64 are not upper debt cap. For conservative first prototype with W=1, separate 4096 scratch plus 4096 output =8192 bytes; can share existing scratch only after ownership/alias proof; K bounded by consumer reservation; 4/8/16KiB lower image cost 4096/8192/16384 each, plus independent BIO and allocator overhead. Persistent imported metadata and decoder owner/GC pins remain after ticket release and must have separate capacity. Exact kernel sizeof/slab rounding/real DM core depth unknown, measure on pinned config; do not claim exact RAM footprint or choose a numerical cap without owner review. Per-copy GFP_NOWAIT allocation would still fragment and fail unpredictably; preallocation avoids recursion and permits deterministic refusal.

## 6. Error and race matrix

| Case | Action / authoritative owner |
| --- | --- |
| swapin/invalidated/recycled before XArray check | Original return/error as pinned; no deref stale entry, no ticket. |
| source pool missing, bad generation/profile, length0 or >=4096, current 3569..4095 | Decline optimization; original decode/write or original decode failure. No truncation; length4096 is uncompressed. |
| no swap device / swapcache alloc error | Original -ENOENT / PTR_ERR and no copy. |
| credits exhausted or optional trylock fails | No wait, no retry; ordinary full-page path. |
| SG copy short/CRC/digest mismatch | Drop optional ticket; preserve source until ordinary decode succeeds; original decode error uses existing err. |
| original decode fails | cancel before erase, keep old source; original err unlock/put. |
| early target changes / suspend / route epoch mismatch | cancel or mark nonclaimable; ordinary same BIO, DM handles ordinary defer/error. No stale target deref. |
| merge/split/partial/requeue before actual acceptance | decline typed sideband, release candidate; original core retains normal disposal. Original carrier put at terminal; disable re-claim after any reissue. |
| consumer candidate validation fails before claim | normal page same clone; no independent lower submit. |
| failure after claim but before any lower work | first prototype terminal error on same clone (redirty by MM), no silent recompression of claimed original; optionally later prove precommit unclaim, not now. |
| lower allocation/WRITE/FUA/flush failure | abort unpublished new mapping; preserve prior mapping if valid, quarantine partial extent until safe; once-only error endio, native redirty/clear reclaim/end_writeback; no success receipt. |
| lower success but logical generation changed | reject stale publish, ordered abort/error; retire stage, never resurrect invalidated slot. |
| teardown/reload | close registry before detach, drain accepted paths and mapping/GC readers, unclaimed refs independent; no module free while callback/live refs remain. |
| duplicate callback / duplicate ACK | ordered terminal gate rejects second transition; no second endio or ref decrement; diagnostics fail-only. |
| successful import | exact original bytes, typed map publish only after physical lower write+FUA or successful flush covering write; then real upper clone endio once; independent decoder remains usable through old-reader GC lifetime. |

Fallback before claim is normal original writeout with intact full-page bytes, not a forced RAW route. After claim on real failure use same upper error path; original swap_write_end redirties, no extra writeback completion or stale source reinsertion. Normal swapoff and target failures may still fail ordinary writes; optimization cannot promise successful I/O against an unavailable device.

## 7. Minimal unapplied patch plan / insertion points

Reviewable pseudocode (names conceptual; not a buildable diff):
```c
/* mm/zswap.c: after same-entry check 1047–1051 */
ticket = original_try_prepare_copy(folio, entry, swpentry); /* optional */
/* existing decode remains unchanged */
if (!zswap_decompress(entry, folio)) {
    original_ticket_put(&ticket);
    ret = -EIO;
    goto err;
}
if (ticket && !original_verify_and_seal(ticket, folio))
    original_ticket_put(&ticket);
original_attach_move(&ctx, &ticket); /* cannot fail; ctx initially empty */
/* unchanged xa_erase, count, entry_free, uptodate, dropbehind,
 * folio_put, __swap_writeout, swap_write_submit */
```
1. mm/zswap.c zswap_compress 890–923 and store_page before1464: optional immutable exact producer profile/sequence/digest, audit folio and pool lifetime; mm/swapfile.c activation/teardown: non-reused area identity; no source metadata if feature disabled except explicitly measured struct delta. Before writeback erase only copy and seal; preserve native return paths. Add core broker stub returning -EOPNOTSUPP when disabled.
2. mm/page_io.c swap_add_folio338–374 and swap_bdev_submit_write596–623; swap_io_ctx/swap_iocb declarations (locate exact internal header before patch): move optional one-page carrier before start_writeback, prevent merge, attach to real original BIO before submit, handle synchronous/async completion, bio_uninit and every pre-submit rejection. No new folio ref across writeback. Audit bio clone/split/reset, error and requeue lifetime in block/bio.c and DM allocation path before writing C. Explicitly decline unsupported paths. Existing full-page payload unchanged.
3. drivers/md/dm.c: short registered capability snapshot API around live-table lookup; add non-reused md/table/target epoch binding and revoke when suspend/table change begins (including presuspend rollback and resume); no pointer persistence. In actual split/alloc_tio/__map_bio, validate exact unsplit original carrier and hand candidate into target callback using explicit core-managed reference; put on any reject/free_tio/requeue. No modifications to standard map return semantics. Do not acquire suspend mutex from reclaim.
4. Product dm-target.c: add optional candidate to existing per-bio private ownership only in real map and claim with incoming enqueue under queue_lock. Exclude claimed streams from ordinary prep/compress paths. Ordered worker routes typed input to abstract consumer; verify independently and reserve/write/publish in existing authority/GC domain. Complete/deferral/drain/dtr release according to terminal ownership; no new cap or timer. Preserve exact20-byte ordinary map, physical header and original codec namespace; Agent5's storage design reconciled by Agent1 later, not required for this producer plan.
5. New code remains default-off, fail-closed. Require explicit authorization before implementation, no applied diff in R083.

## 8. Verification and acceptance order

Next authorized round: source-lock exact pinned files and write focused rootless test-only seam for source credential and actual carrier/clone ownership. Exercise exact producer byte extraction and actual block/DM selection/ref transfers (not another abstract R082 debt suite). Directed positives: split SG copy and both codecs 1..M boundary semantics, one full-page BIO with one claim, current exact target; negatives: length0/3569/4095/4096 at M3568 and 4095 accepted only at independently validated future M, unsupported provider, stale store/area/table/target epoch, wrong bdev/partition/interval, allocation/credit failure, duplicate claim, clone split/requeue/teardown, failure before/after erase and terminal callback. Use strict GCC/Clang ASan+UBSan for executable fragments; later source-integrated native test must execute actual carrier and selected target lifecycle, including suspend while BIO is deferred, source slot reuse, failure redirty and reader retirement, with lockdep and appropriate sanitizer support. Measure kernel allocations and all overlapping budgets. Existing R080 Agent5 20+20 source-host and R082 Agent11 24+24 source-host and Agent10 native4/4 are historical evidence, not proof of this new seam. Do not repeat unchanged workflows in R083. Real authenticated original STORED selection, lower durable FUA/flush and exactly-once real upper ACK require separate authorized controlled qualification, not simulated receipts. No physical operation in this round.

**Minimum implementation order:** (1) disabled producer credential and exact source identity; (2) independent bounded broker with teardown-safe cancellation; (3) explicit ordinary BIO carrier plus actual DM selection/claim seam; (4) consumer geometry/typed authority/GC integration; (5) genuine error/forward-progress/lifetime tests; (6) owner-authorized physical qualification only after gates. If any of (1)–(4) fails proof, stay ordinary; no production import. Source auth0, Phase A BLOCKED, direct/forced RAW/import OFF.

## Immutable inspected blob manifest
Original Linux c339f4010dea8b0d754f84ace70cd1b089878ef8:
- mm/zswap.c — `ae19e301fced7e357a4c7587dfdd6abb890b9163`
- mm/zsmalloc.c — `7ef80e0da6267661cea4d48a4a615444724782e7`
- mm/page_io.c — `c6824fcd483e0aa2c412e14dae0d2a356b17c373`
- mm/swapfile.c — `254ce86fa923e6b5f1fefda88c39315c4cc00642`
- drivers/md/dm.c — `1881d86111fb2e655893ad898cf21b88f0e4e7f3`
- drivers/md/dm-table.c — `a483f49dd4ce6383ef66464707865187aa4cf51c`
- block/blk-core.c — `8836c7028568b08640d0a1c26fe908dd8ebead4f`
- include/linux/device-mapper.h — `cd4faaf5d4275c038d06ccef4da3d77430154388`
- include/linux/swap.h — `4f686709d71f005dc43b2f751012b5f61d6b007a`
- include/linux/bio.h — `7a794ce723b84b2a148f8f9beccf057b266e8ac9`
- include/linux/blk_types.h — `0cc09b975d8ffbd45ca3dc47533a71f8e8164de6`

Product 039d67757a7a432a4751fa025f5922e786fbf38b:
- src/kernel/dm-target.c — `f1cab252cd990190646c82da81378d1563475826`
- src/kernel/authority.c — `25bf2dbdc5a3af770d7027547a58254c1ba81265`
- src/kernel/authority.h — `3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031`
- src/kernel/codec.h — `e89d316b9cf49f82df0b77648c1be1731607987d`
- src/kernel/zswap-import-admission.h — `a411da35437cbf9a43c88083d830dc9280f108e8`
- src/kernel/zswap-import-codec.h — `0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6`
- src/kernel/zswap-import-decoder-owner.h — `e1b4b903567070e2307f7d05f8e48c14e0bb3768`
- src/kernel/zswap-import-decoder-owner.c — `8e0c8f4d2085af7f2e17df412f3a1af654063571`

First source access error: NONE. Blob IDs are immutable GitHub-returned identities; no independent local git hash/build claimed in this design round. CI=NOT_RUN_DESIGN_ONLY. No C/H, tests, workflow, or standards edits.
