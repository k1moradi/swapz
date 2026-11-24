# Round084 Agent11 — disabled bounded original ticket broker

**QUEUED — actual implementation published, compiler qualification pending.** Assignment `1f8b9b89006af6cd8ad895239a023772b694cc36`, parent `be84039bd108020c083ef1a929722ca6afe7f74f`. Exact source [`f7df9058c7291d15b6159b6bbe95e8a845113bf4`](https://github.com/k1moradi/swapz/commit/f7df9058c7291d15b6159b6bbe95e8a845113bf4), single parent `3ef350588cec0e9d1364f80a94bea33e498144ad`. [Run 45395569647](https://github.com/k1moradi/swapz/actions/runs/45395569647), [job 138450309370](https://github.com/k1moradi/swapz/actions/runs/45395569647/job/138450309370), queued at observation. First CI error: none reported yet. GCC 0/32, Clang 0/32 confirmed compiled and executed; both baselines pending. No local C execution claimed. This is not a PASS report.

## Implementation and ownership

New opt-in `src/kernel/zswap-original-ticket.h/.c` (ACTIVE=0, no ordinary Kbuild wiring). Caller allocates aligned contiguous payload, typed metadata and free-index arrays with exact checked multiplication, summed footprint and nonoverlap. Reservation takes one trylock; independently checks ticket count and compressed-byte credit before allocating a free index. Count and bytes charged atomically; explicit stride 3584 or4096 at M3568/4095. No allocation, callback or credit waiting. Existing pinned codec CRC implementation reused, ordinary cap/map unchanged. Seal verifies exact byte length and CRC on independently copied bytes; exclusive producer lease pins slot while copy/CRC occurs outside lock. Copy failure/cancel must be followed by caller put; no early credit recycling. Read view is valid only through held lease; output unchanged on view failure. Source and route value identity includes session/area, store seq, slot/type, profile/version/representation, SHA256 and CRC, target/table epoch and DM logical/generation. Caller supplies all test credentials; no real source authority.

Move-only lease contract (caller cannot manufacture refs by struct copying); explicit retain, clear lease on successful put, generation and session checks, overflow fail closed. Claim is a one-shot state transition under trylock, not actual selected clone admission. O(1) lazy epoch revocation, close blocks new reservations/retains/claims; existing sealed refs remain readable and charged until final put. Close returns -EBUSY while live slots, does not free arrays or wait for deferred carriers. Destroy requires external quiescence of every API entrant and zero retained refs; no safe destruction from arbitrary concurrent callers is claimed. Host uses pthread mutex; kernel irqsave spin adapter proposed but not compiled or qualified this round. No external locks allowed across broker API. Real carrier/selected DM atomic enqueue seam, global broker lifetime and allocator overhead still need integration proof.

## Preflight and test plan

Connector checked immutable task parent, product/original pin metadata, all 32 distinct mutation anchors against exact new broker blob, and verified source commit single parent. Standards appended in same commit with byte-exact old prefix round-tripped to identical blob (five added lines, zero deleted). Remote actual checkout, full original/product hash, real git diff --check and repository policy execute before compilation. Initial packaging script failed syntax before writes; next exceeded connector per-call tool limit before ref update; split publication recovered. Workflow-specific runs endpoint refused by connector, exact repository run listing recovered actual queued run. These are tool/prepublication errors, not compiler failures. First source access error NONE.

Fixture calls actual broker code and pinned CRC: M3568/4095, exact footprint/sizeof output, separate count/byte exhaustion, alignment/nonoverlap, raw4096 rejection, zero/invalid typed profile, immutable copy, short/CRC failures, generation ABA and exhaustion, reference overflow, duplicate claim/put, trylock contention, stale route and barrier-ordered revoke/close/last put. Verifier compiles actual baseline and each of 32 single-source mutations separately using strict C23/C2x GCC/Clang ASan+UBSan, requires explicit behavioral exit77/FIRST_ERROR, not compiler or sanitizer failures. No test results asserted until actual job evidence. Actual host sizeof pending; payload capacity N*stride, metadata N*sizeof(slot), indices N*sizeof(u32), broker sizeof plus unknown allocator overhead. Not a production cap or measured complete memory budget.

## Immutable pins

Original Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`:
- mm/zswap.c `ae19e301fced7e357a4c7587dfdd6abb890b9163`
- mm/zsmalloc.c `7ef80e0da6267661cea4d48a4a615444724782e7`
- drivers/md/dm.c `1881d86111fb2e655893ad898cf21b88f0e4e7f3`

Product:
- src/kernel/codec.h `e89d316b9cf49f82df0b77648c1be1731607987d`
- src/kernel/codec.c `d920dcaac6f2b7de1334d4133770bd649719c66d`
- src/kernel/authority.h `3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031`
- src/kernel/dm-target.c `f1cab252cd990190646c82da81378d1563475826`
- src/kernel/Makefile `ed6e19ae28a84a4a3e92117812adc445d5c2e8e5`

New exclusive files:
- [src/kernel/zswap-original-ticket.h](https://github.com/k1moradi/swapz/blob/f7df9058c7291d15b6159b6bbe95e8a845113bf4/src/kernel/zswap-original-ticket.h) `b772cc28755a68719f4dcdabefeefe57b5efea67`
- [src/kernel/zswap-original-ticket.c](https://github.com/k1moradi/swapz/blob/f7df9058c7291d15b6159b6bbe95e8a845113bf4/src/kernel/zswap-original-ticket.c) `dcea7cbc40094fed2997d6704c712ac47aa164a1`
- [tests/runtime/native/fixtures/round084-original-ticket.c](https://github.com/k1moradi/swapz/blob/f7df9058c7291d15b6159b6bbe95e8a845113bf4/tests/runtime/native/fixtures/round084-original-ticket.c) `c866418fc6e70438743c29d56c22116127a71951`
- [tests/tools/round084-original-ticket-verify.py](https://github.com/k1moradi/swapz/blob/f7df9058c7291d15b6159b6bbe95e8a845113bf4/tests/tools/round084-original-ticket-verify.py) `448703b4907c1e4caadc9810fd4f23dcd147e089`
- [.github/workflows/phase-a-round084-original-ticket-host-noauth.yml](https://github.com/k1moradi/swapz/blob/f7df9058c7291d15b6159b6bbe95e8a845113bf4/.github/workflows/phase-a-round084-original-ticket-host-noauth.yml) `37cf34899bd258eaebf12e952de778f55df052f4`

No normal product C/H modifications, native build, physical operation, additional reclaim, production BIO cap or unsafe REQUEUE. Historical qualification preserved, no peer dependency or workflow reruns. Linux MM/zswap alone owns natural eviction; swapz disk packing/GC only. RAW_4096 full original uncompressed page. SOURCE_MAPPED_AUTHENTICATED=0, PHASE_A=BLOCKED, direct/forced RAW/import OFF.
