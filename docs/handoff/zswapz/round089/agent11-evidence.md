# Round089 Agent11 — broker claim/revoke and bounded MM producer

**IN_PROGRESS_HOST_ONLY_NO_GO_LIVE**. [Assignment](https://github.com/k1moradi/swapz/blob/0c893ee7a3ffc158d747c11c96b67fcf0b3efa15/docs/handoff/zswapz/round089/agent11-broker-route-memory-p0.md), baseline db9252db73721a768be912965ad4402e332039e8. [Initial source](https://github.com/k1moradi/swapz/commit/c808093639d8dc77dad76cb38f0a327d0fe304fd), sole parent 50da7608c7f2a461126824e916dbc37c5585098d; [corrected source](https://github.com/k1moradi/swapz/commit/63412e4f2fb6f74cb02996947aca48acf047391c), sole parent ef05181f8e7e248df2daa3549be87af58153fa99. Both verified fresh expected-head nonforce main FF, disjoint owned files, append-only standards exact prior blobs recreated. No same-round peer dependency. Local git ls-remote DNS failure exit128, no local execution claimed.

## Actual source changes
Actual broker common one-attempt trylock claim and narrow queue-lock adapter; only that claim permitted under selected incoming queue lock. The broker lock sections contain local state/credits and key comparisons only, no external callbacks/waits/other locks/allocations. Seal drops lock before copy/CRC. No reverse acquisition in broker implementation. Claim, O(1) revoke, close serialize on same broker lock, so stale epoch cannot claim after revoke linearizes; existing immutable views and leases remain until final put. Retain before queue lock, put outside it. Actual target must prove origin/selected clone and current epoch/generation under queue lock, order target invalidation with it and infallibly link once before unlock. Native target lock graph unqualified. Independent move-only capability validates broker session/epoch/closing, increments capability_refs with overflow guard, consumes after revoke; close returns EBUSY without waiting on outstanding refs or capabilities; destroy requires both zero and external entrant quiescence. Provider registration RCU + process-context mutex, callbacks value-only and nonblocking, no raw target pointer escape or broker calls, target locks released before return, owner pins callback code and broker through unregister/grace and outstanding capability. No provider registered: default hard refusal.

[Unapplied MM patch](https://github.com/k1moradi/swapz/blob/63412e4f2fb6f74cb02996947aca48acf047391c/tests/tools/round089-original-mm-carrier.patch), 29 hunks, six original files plus guarded header. R088 patch immutable for Agent10. 120B full key replaced by 8B nonwrap cookie; 64 preallocated replaceable source-only records; one CAS per cell, collision/contention/stale lookup declines; no route fields stored per entry. Capture gated on exact compressor, native order0/full-page geometry, route eligibility and acquired cell before CRC/SHA. No provider means no hash, no sequence increment or sparse access. Initial route eligibility lacked codec/length; corrected source passes both to eligibility and eviction lookup so normal M3568 can reject oversized streams before hashing; M4095 experimental separately admitted only. Provider policy not yet integrated. No expensive hash while SG pinned. Original native decode, preerase, one BIO and full-page fallback preserved; original ctx/sio sole owner, generic BIO borrow invalidation unchanged, deferred ticket and capability put before carrier reuse, one optional static carrier slot not a production BIO cap. No active Kbuild or original upstream mutation.

## RAM/CPU bound
Nominal 112B per entry saved (93.33% of prior 120B); 8/4096=0.1953125% logical, 8/64=12.5% compressed, worst nominal 8/1=800% for one-byte payload. At 1,048,576 entries 8 MiB vs 120 MiB, saving 112 MiB before fixed/slab overhead. Source-derived x86_64 entry layout estimate 48→56 instead of 168; actual kernel sizeof/slab unknown. Initial measured host record72 cookie8 cap24 carrier4176 broker160. Estimated kernel cell80 (record+atomic+alignment) ×64=5120 plus one carrier ≈4176 =9296 fixed before counters, provider mutex/work, allocator and existing broker arrays. Bounded cache sacrifices hit rate. CPU bound per eligible store CRC ≤4095B + SHA4096B; eviction SG copy and broker copy/CRC of length + SHA4096B, no recompression; no actual CPU or hit-rate measurement. No hash on missing/ineligible route or cell contention, except route can change after an eligible snapshot; fallback then. Original MM alone natural eviction.

## CI and first cause
Initial [exact job](https://github.com/k1moradi/swapz/actions/runs/45577454771/job/139078805896) SUCCESS: canonical clean SHA/real push-before/diff check/repository policy, 15 pristine and seven staged pins, duplicate reject/reverse-check passed. Actual GCC700 + Clang700 strict Werror ASan/UBSan, 32 races each, GCC2 claims/30 declines, Clang3/29. [Artifact](https://github.com/k1moradi/swapz/actions/runs/45577454771/artifacts/15004009556) 1210B sha256 a58f6e42fd50487a52b3e39dadfe5542eb2b9000b90e9106a943727beb560dc0, metadata bound to initial SHA, archive not independently extracted. First test error none. Corrected [exact job](https://github.com/k1moradi/swapz/actions/runs/45577781770/job/139079883750) queued/pending. Corrected compiler counts pending; predicted postimages checked against exact original preimages by connector; no corrected PASS claimed.  No semantic mutants/native compile/link/run. R087 native6 and R088 host63+63 historical only. Initial automatic census10, corrected9; no manual dispatch, unchanged rerun, cancellation, VM qualification, physical mutation or polling automation. Inherited automatic lanes not qualified here, A9 owns routing.

## Exact pins
- src/kernel/zswap-original-ticket.c 66df826d86dde1bbd5e1967daa0e62517b58ac8d
- src/kernel/zswap-original-ticket.h 2f850b53708c8142ee95d330192c9db1f9ae9418
- tests/tools/round089-original-mm-carrier.patch 059d1bf29cf4990e22a2f608d5d552abeec3a8d1
- tests/tools/round089-original-mm-carrier-verify.py dce6b2417ea33b598eaf00accf7888730b2e4a54
- tests/runtime/native/fixtures/round089-original-mm-carrier.c bc01d5f7b41e16ab3748e9350d715e85887e91cd
- .github/workflows/phase-a-round089-original-mm-carrier-host-noauth.yml 71e8ad808de269e6122396b59694ecd78192590c
- src/kernel/codec.c d920dcaac6f2b7de1334d4133770bd649719c66d
- src/kernel/codec.h e89d316b9cf49f82df0b77648c1be1731607987d
- src/kernel/Makefile ed6e19ae28a84a4a3e92117812adc445d5c2e8e5
Original Linux pristine c339f4010dea8b0d754f84ace70cd1b089878ef8:
- mm/zswap.c ae19e301fced7e357a4c7587dfdd6abb890b9163
- mm/page_io.c c6824fcd483e0aa2c412e14dae0d2a356b17c373
- include/linux/swap_ops.h 57ac6c703f685883d3a15ebc1a5c7f6c298deb1b
- include/linux/blk_types.h 0cc09b975d8ffbd45ca3dc47533a71f8e8164de6
- include/linux/bio.h 7a794ce723b84b2a148f8f9beccf057b266e8ac9
- block/bio.c b0fcc69de653524479e3b328aa29a37e97945b84
- mm/zsmalloc.c 7ef80e0da6267661cea4d48a4a615444724782e7
- mm/swapfile.c 254ce86fa923e6b5f1fefda88c39315c4cc00642
- mm/swap.h d5bf21f517dceae58eb94fb0ce5f4e1fdc679409
- include/linux/swap.h 4f686709d71f005dc43b2f751012b5f61d6b007a
- include/linux/bvec.h b63914ff56e33df302055fabf2a84ba490bc8d2c
- include/linux/blkdev.h 2d5c30823aab9be31d881be1de8ae60feb7a5c57
- include/linux/workqueue.h c8a36423cb3465ba8c00735b2ca152eb7122a97a
- include/crypto/acompress.h 5d5358dfab73458fc4bc345fe00650e938fe36c6
- include/crypto/sha2.h 22fbc37ae840796ecbafd5eadf23373e51741f9e
Corrected staged postimages (predicted):
- mm/zswap.c 8bf7e885376c5ef521adf40b1ec736e062067bff
- mm/page_io.c 0b0fe917fa3af5deaef8263274edffbf1a62eedb
- include/linux/swap_ops.h a39a1921daf6f272e9812eb63b1aa64fec96c57f
- include/linux/blk_types.h 0bf866c1571fe6b4d2e49d01b1b2c87fcf2cf04c
- include/linux/bio.h f4c5f1730514cf1816ffd5e9787562439dfae236
- block/bio.c 3ba0e12a96ba3235eb909e3b3dd0be44657c6f6e
- include/linux/swapz_mm_carrier.h 72100483b42a59db8f522d3f2f4ee10d4f856550

GO dormant review only, NO-GO live. Actual route provider/selected clone and atomic queue/route ordering, real kernel compile/link and native lifecycle/lockdep, provider/module lifetime and destroy quiescence, actual slab/CPU/hit rate/peak RAM and lower durability/upper ACK remain blockers. AUTH=0 Phase A BLOCKED, direct compressed handoff/forced RAW/import OFF. 20B map and protected SWAPSPACE2 unchanged. Ordinary RAW_4096 full original page. No owner-side physical test requested.


## Agent1 independent reconciliation
Corrected exact job 139079883750 terminal SUCCESS, artifact15006885910 independently extracted: 15 pristine/7 postimage pins, GCC700 checks 32 races (9 claims/23 declines), Clang700 checks 32 races (3/29), source72 cookie8 cap24 carrier4176 broker160 host bytes. 1400 checks/64 races corrected source; native/full kernel not run. Actual registration/provider/selected-clone lifetime remains unproven. R090 producer-side lifecycle and memory effectiveness only, no repeat unchanged.
