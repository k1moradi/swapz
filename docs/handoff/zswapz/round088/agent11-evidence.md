# Round088 Agent11 — unapplied original MM pre-erase and BIO carrier candidate

**IN_PROGRESS — actual reviewable disabled staged patch published; rootless exact-source stage/host CI pending. NO-GO live integration/activation.** [Assignment](https://github.com/k1moradi/swapz/commit/dcb65dca9a3c2bd990aedb2829181d0c0e015ce2), sole parent `cf5a539913fd169fd71bac72c61bc355285a51f6`. [Source/test commit](https://github.com/k1moradi/swapz/commit/28527084a205d7465748af29f6f92dcba420c36e), sole parent `58e2182ca9b6fb940c22174274f07953795d602f`. [Run 45459276984](https://github.com/k1moradi/swapz/actions/runs/45459276984), [job 138677070938](https://github.com/k1moradi/swapz/actions/runs/45459276984/job/138677070938), in progress at observation (checkout; exact source and compiler steps not yet confirmed). First corrected CI error: none reported. GCC/Clang actual executed counts pending; no local host or kernel execution claimed.

## Actual patch, ownership and limits

[Unapplied Linux patch](https://github.com/k1moradi/swapz/blob/28527084a205d7465748af29f6f92dcba420c36e/tests/tools/round088-original-mm-carrier.patch) contains 29 exact original-source hunks: six modified files plus a new header, no external upstream publication, normal Kbuild or product C/H change. Undefined CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST guard, with opt-in exact existing broker/CRC include/link placement still a future build step. Original Linux pin c339f4010dea8b0d754f84ace70cd1b089878ef8. Source-derived actual placement:

- At successful actual zs_obj_write under existing acomp mutex, clear reused credential including raw fallback; capture exact selected acomp name+driver, nonwrap one-shot atomic store sequence, swap-area activation sequence, type/offset, exact length, compressed CRC and original full-page SHA256 before native XArray publication. Strict known LZ4/LZO1X only, PAGE_SIZE4096, length1..4095. Original entry reused metadata cleared; original failure paths unchanged.
- After native locked swapcache XArray identity and successful full-page decompression, before xa_erase, optional preerase validates slot/area/profile, exact order-0 folio, block swap ops and whole device, native swap_folio_sector. **Route provider deliberately hard-refuses** (no proven live provider, never fabricate target epoch/generation); future provider supplies only separate value-only route fields and independently pinned broker, never mutates source identity or holds target pointer. One nonblocking scratch carrier reservation; existing broker try-reserve, exact one/two-entry zsmalloc SG copy, end SG pin before new SHA/CRC seal, original full-page SHA verification. Copy/CRC/digest/refusal leaves intact native fallback; no new error/second BIO/reclaim.
- Producer moves sole carrier owner ctx -> original sio; dedicated one-bvec original block write only, decline merge/nonblock alternate path. Actual ordinary full-page BIO retained, borrowed carrier pointer separate from bi_private; original sio owns lease until native terminal. Explicit candidate_get checks exact originating full-page BIO device/sector/page/iterator/op/flags and retains existing immutable broker lease; actual selected clone/table proof is caller prerequisite, no foreign lock held, not authorization. Generic clone gets no view. Clear borrow at init/uninit/advance/set_dev/split/trim/chain/reissue/endio, reset/reuse transitively. No generic core broker put. Existing native error redirty/end_writeback and sio mempool_free kept; sole owner moved to static deferred release work, broker put outside foreign completion lock. No dtr wait for unclaimed carrier; static lifetime, future route-provider broker registration/destroy quiescence unresolved.
- One independent optional static carrier scratch slot (4096 bytes), not a production cap. Existing broker count/byte quotas unchanged. Proposed guarded per-entry credential uses whole ticket_key (prior x86_64 measured120 bytes); pointer added to ctx/sio/BIO, actual allocation overhead/new sizeof and total RAM bound not qualified. Static worker slot held until final owner put, quarantined on release error. No claim+enqueue API added, no Agent3 new API dependency. Existing broker foreign-lock prohibition unchanged. No selected-DM atomic enqueue proof, no durable/ACK claim.

## Exact-source qualification

[Verifier](https://github.com/k1moradi/swapz/blob/28527084a205d7465748af29f6f92dcba420c36e/tests/tools/round088-original-mm-carrier-verify.py) checks pinned pristine bytes and independently applies the actual unified patch to a disposable copy with git apply --unidiff-zero; compares exact seven postimage blobs, no other pinned inputs changed; duplicate refusal and reverse-check; actual source anchor/order checks for store/SG/writeback/sio/BIO terminal. Connector computed predicted exact postimages and checked 29 hunk preimages. An initial partial-line block/bio.c packaging anchor was rejected before any ref update, then regenerated. CI actual apply and compilation not yet observed.

[Host fixture](https://github.com/k1moradi/swapz/blob/28527084a205d7465748af29f6f92dcba420c36e/tests/runtime/native/fixtures/round088-original-mm-carrier.c) extracts exact actual staged header and profile/candidate functions with only kernel includes removed for explicit BIO ABI shim; strict GCC and Clang C23/C2x Werror ASan/UBSan against actual unchanged broker and codec. Exercises typed profiles, exclusive pointer moves, original geometry and malformed/reissued/cloned/remapped/absent borrow rejection, real retained lease/immutable bytes/credits across revoke and close. Host shim does not execute actual SG, store, BIO, workqueue or selected DM. Actual patched original kernel compile/link NOT_RUN; no VM/new native, no physical. No mutation count claimed.

## Immutable pins

Pristine original:
- mm/zswap.c `ae19e301fced7e357a4c7587dfdd6abb890b9163`
- mm/page_io.c `c6824fcd483e0aa2c412e14dae0d2a356b17c373`
- include/linux/swap_ops.h `57ac6c703f685883d3a15ebc1a5c7f6c298deb1b`
- include/linux/blk_types.h `0cc09b975d8ffbd45ca3dc47533a71f8e8164de6`
- include/linux/bio.h `7a794ce723b84b2a148f8f9beccf057b266e8ac9`
- block/bio.c `b0fcc69de653524479e3b328aa29a37e97945b84`
- mm/zsmalloc.c `7ef80e0da6267661cea4d48a4a615444724782e7`
- mm/swapfile.c `254ce86fa923e6b5f1fefda88c39315c4cc00642`
- mm/swap.h `d5bf21f517dceae58eb94fb0ce5f4e1fdc679409`
- include/linux/swap.h `4f686709d71f005dc43b2f751012b5f61d6b007a`
- include/linux/bvec.h `b63914ff56e33df302055fabf2a84ba490bc8d2c`
- include/linux/blkdev.h `2d5c30823aab9be31d881be1de8ae60feb7a5c57`
- include/linux/workqueue.h `c8a36423cb3465ba8c00735b2ca152eb7122a97a`
- include/crypto/acompress.h `5d5358dfab73458fc4bc345fe00650e938fe36c6`
- include/crypto/sha2.h `22fbc37ae840796ecbafd5eadf23373e51741f9e`

Predicted staged postimages:
- mm/zswap.c `e3caa72ca37a7a3cdb3ed51639d9507b22fe4e51`
- mm/page_io.c `0b0fe917fa3af5deaef8263274edffbf1a62eedb`
- include/linux/swap_ops.h `a39a1921daf6f272e9812eb63b1aa64fec96c57f`
- include/linux/blk_types.h `0bf866c1571fe6b4d2e49d01b1b2c87fcf2cf04c`
- include/linux/bio.h `f4c5f1730514cf1816ffd5e9787562439dfae236`
- block/bio.c `3ba0e12a96ba3235eb909e3b3dd0be44657c6f6e`
- include/linux/swapz_mm_carrier.h `7ac3fe204983aa7ba5a291aa756d37e235f8508f`

Product/fixture:
- src/kernel/zswap-original-ticket.h `b772cc28755a68719f4dcdabefeefe57b5efea67`
- src/kernel/zswap-original-ticket.c `dcea7cbc40094fed2997d6704c712ac47aa164a1`
- src/kernel/codec.h `e89d316b9cf49f82df0b77648c1be1731607987d`
- src/kernel/codec.c `d920dcaac6f2b7de1334d4133770bd649719c66d`
- src/kernel/Makefile `ed6e19ae28a84a4a3e92117812adc445d5c2e8e5`
- tests/tools/round088-original-mm-carrier.patch `b9a10044c7cd750d908730b5a95a4e945883ec45`
- tests/runtime/native/fixtures/round088-original-mm-carrier.c `d173ef985b801ba34815754d9d9918eeace3ec06`

New files:
- [tests/tools/round088-original-mm-carrier.patch](https://github.com/k1moradi/swapz/blob/28527084a205d7465748af29f6f92dcba420c36e/tests/tools/round088-original-mm-carrier.patch) `b9a10044c7cd750d908730b5a95a4e945883ec45`
- [tests/tools/round088-original-mm-carrier-verify.py](https://github.com/k1moradi/swapz/blob/28527084a205d7465748af29f6f92dcba420c36e/tests/tools/round088-original-mm-carrier-verify.py) `743f4a892e1b351f9d923da9f5241d6938fbd75f`
- [tests/runtime/native/fixtures/round088-original-mm-carrier.c](https://github.com/k1moradi/swapz/blob/28527084a205d7465748af29f6f92dcba420c36e/tests/runtime/native/fixtures/round088-original-mm-carrier.c) `d173ef985b801ba34815754d9d9918eeace3ec06`
- [.github/workflows/phase-a-round088-original-mm-carrier-host-noauth.yml](https://github.com/k1moradi/swapz/blob/28527084a205d7465748af29f6f92dcba420c36e/.github/workflows/phase-a-round088-original-mm-carrier-host-noauth.yml) `6c38a9ec86e353c11a18aed396c6cb967c917da9`

Standards prior `09564b946a300ef12fee4375f752ec78aea8e1a4`, appended `6802dc7db7fafa580bf2ff6ac5038317036345f6`, exact previous blob recreated before append. Source commit parent/paths verified; no peer paths overwritten.

## Historical evidence and next gate

R087 actual broker adapter six-case PASS accepted by Agent1: [job](https://github.com/k1moradi/swapz/actions/runs/45455624750/job/138664150782), [artifact](https://github.com/k1moradi/swapz/actions/runs/45455624750/artifacts/14950116706). No repeat; R086 UML failure preserved. Focused new workflow host-only. Six automatic runs observed including five historical existing workflows; no manual VM dispatch or cancellation; A9 owns retirement. No new physical action.

GO for review of the dormant source artifact; NO-GO live producer until actual route/epoch/generation snapshot, independent global broker lifetime, actual compile/link and integration proof, original ctx initialization audit, generic BIO lifecycle and selected clone proof, foreign-lock ordering and bounded memory are closed. No existing authorization to run physical mutation; no new VM. Source AUTH=0 Phase A BLOCKED direct/forced RAW/import OFF. Ordinary RAW_4096 complete original page, exact20B ordinary map and protected SWAPSPACE2 unchanged. Actual source-authenticated claim, lower durability and real upper ACK unproven.
