# Round091 Agent10 — current frozen R090 compile/link only

**Terminal CI FAILURE: original 6/6 and product 9/9 PASS; full vmlinux link PASS; module modpost FAIL. AUTH0; Phase A BLOCKED; all activation OFF.**

## Terminal CI reconciliation — exact source, attempt 1

**Original directed 6/6 PASS; product directed 9/9 PASS; full vmlinux link PASS; external module modpost FAILURE (six undefined symbols).** Supersedes historical pending snapshot below.

[Run 45599641943](https://github.com/k1moradi/swapz/actions/runs/45599641943) / [job 139154826234](https://github.com/k1moradi/swapz/actions/runs/45599641943/job/139154826234) terminal failure exit2 on `8dc64dfd2c7b19e1f64e7ce42e3d6ba4c8d3fbb3`. [Artifact 15014753457](https://github.com/k1moradi/swapz/actions/runs/45599641943/artifacts/15014753457) downloaded 40551 bytes, independently verified archive SHA256 `5df09c2da63c7568683aa2f04452535e7c8c314f9f159160115920811b76b208`. Actual results, raw/stage manifests, effective config, original/product compiler logs, kernel link and module modpost logs inspected. Ordered intermediate stage and final raw manifests agree, final raw 8/8, exact scratch-compatible hashes match predictions. No object/vmlinux binaries in archive; reported binary hashes are CI manifest values, not independently hashed binary bytes. Config independently hashed `89127024a38ad68dd091c9dd5787bba097b85c8ce69d118cd147a8d7ff4c6d0b`. GCC13.3.0/ld2.42. CI complete standards prefix PASS 1796686 -> 1798344 bytes (1658 append). No standards modification in this terminal commit.

Pristine three-patch application, final raw 8/8, frozen product pins41, scratch Kbuild, authorized current identifier overlay (11 replacements in three files), ELF header/link/exec, OpenSSL and effective config PASS. No obsolete bvec overlay, no peer edits. Original raw staged patches plus scratch-only product namespace correction; not untouched raw product compile. No qualification of new R091 peer source. One attempt.

Original object blobs (CI manifest): `block/bio.o` 0aed09203301109202b2a1a39909a856557de490; `drivers/md/dm.o` 728fe0353f3b945e9ba77c63692ccc41ac1829e9; `mm/page_io.o` 558dc9dab371391ccd1ea13d2c7f15a18d135bcd; `mm/round091-swapz/codec.o` aab9fb9f916891a1d719875aa7f8a91ec742726f; `mm/round091-swapz/zswap-original-ticket.o` c6c6977cab5cbd171d90dd3672c3483897486e06; `mm/zswap.o` a998da2e0e674b58ed1e086c7efca70dc209c4b8.

Product object blobs (CI manifest): `authority.o` 61fb90127d0606e0efa70f420858082fae48a9e9; `codec.o` aab9fb9f916891a1d719875aa7f8a91ec742726f; `dm-target.o` 67d72edd2fe64d70d4f8d6f93725c00c451b43f1; `engine.o` b3d42f1c18236bed973f997482e41e4b106794c2; `zswap-import-decoder-owner.o` 0a18a68bff04b25c79b150b8cd5fa92b36620611; `zswap-original-decode.o` a11680c1283c5f1280d872e60271151143e3a862; `zswap-original-decoder-bridge.o` 09d3c36f6fb5cd4148e0b235f7e356b8fa4dca98; `zswap-original-extent.o` 6e57729542626eb0e98ac0ee15dadcc05706f4b6; `zswap-original-storage.o` fa3d9d61b6b993191a11877d2e34dca42b9827ce.

Actual vmlinux SHA256 `def4e04f36351fb5f639103c052c43c7bd29a6146bc12489510595161d1afa9f`, kernel Module.symvers SHA256 `26ea28c680007771a754de951d198798d0ad53b16ecbcec74125a731ccbe693f`; kernel-symbol-check PASS, kernel-undefined.txt empty (0 bytes). All 15 inventory symbols defined in kernel, three selected-DM exports present and 12 other expected inventory symbols absent from kernel Module.symvers. Not all absent inventory symbols are actual module imports. Additional four predictor objects compiled, composite dm-swapz.o linked, then modpost failed. Final .ko link and final module nm NOT_REACHED.

Actual ordered module errors:
```text
ERROR: modpost: dm-swapz.ko: symbol 'swapz_ticket_put' undefined!
ERROR: modpost: dm-swapz.ko: symbol 'swapz_mm_candidate_get' undefined!
ERROR: modpost: dm-swapz.ko: symbol 'swapz_mm_unregister_provider' undefined!
ERROR: modpost: dm-swapz.ko: symbol 'swapz_ticket_broker_put' undefined!
ERROR: modpost: dm-swapz.ko: symbol 'swapz_mm_register_provider' undefined!
ERROR: modpost: dm-swapz.ko: symbol 'swapz_ticket_view' undefined!
```

Frozen [broker source](https://github.com/k1moradi/swapz/blob/e8a3f08000f81dcc3b1bda74b407b9e523ed3bab/src/kernel/zswap-original-ticket.c#L338) blob 66df826d86dde1bbd5e1967daa0e62517b58ac8d: broker_put338, view358, put402. [MM base patch](https://github.com/k1moradi/swapz/blob/e8a3f08000f81dcc3b1bda74b407b9e523ed3bab/tests/tools/round089-original-mm-carrier.patch#L72) blob 059d1bf29cf4990e22a2f608d5d552abeec3a8d1: register72, unregister87, candidate_get233, lifetime overlay applied. No exports for these APIs in frozen sources. Agent11/Agent3 coordinate with Agent1 on narrow guarded GPL exports or reviewed built-in consumer boundary; one broker owner; explicit provider/module hard refs, revocation, RCU grace, teardown drain. No blanket export, fake Module.symvers, duplicate broker or warning suppression. Link proof alone cannot establish lifetime. No export overlay authorized, no retry or peer edits.

Verifier limitation: swapz_ticket_view omitted from expected symbol inventory; actual modpost caught it. Next authorized compile lane should derive actual consumer imports and include view, preserve actual modpost as authority. No claim all 12 absent inventory symbols are current imports.

No VM boot/build-for-VM, module load, privileged/physical test, activation, duplicate dispatch or migration edit. AUTH0 Phase A BLOCKED direct/forced RAW/import OFF.

## Authority and source

[ROUND_OPEN](https://github.com/k1moradi/swapz/issues/209#issuecomment-7160219532), [immutable task 7fa5e3dc74c67330f341ae39c11dc3f8bff01187](https://github.com/k1moradi/swapz/commit/7fa5e3dc74c67330f341ae39c11dc3f8bff01187), [frozen R090 baseline e8a3f08000f81dcc3b1bda74b407b9e523ed3bab](https://github.com/k1moradi/swapz/commit/e8a3f08000f81dcc3b1bda74b407b9e523ed3bab), original Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`. Read dedicated prompt, revised frozen contract, R090 checkpoint, agent/evidence/scheduling policy and relevant source. Independent compile-only lease; no current peer outputs, production edits or migration work. [Source 8dc64dfd2c7b19e1f64e7ce42e3d6ba4c8d3fbb3](https://github.com/k1moradi/swapz/commit/8dc64dfd2c7b19e1f64e7ce42e3d6ba4c8d3fbb3), sole parent `7fa5e3dc74c67330f341ae39c11dc3f8bff01187`, fresh expected-head single-parent nonforce main. Owned source paths only:
- [Verifier](https://github.com/k1moradi/swapz/blob/8dc64dfd2c7b19e1f64e7ce42e3d6ba4c8d3fbb3/tests/tools/round091-original-composed-compile-verify.py) blob `3daaceff892859fe6ab88d59abe25e6741ebc4d1`.
- [Workflow](https://github.com/k1moradi/swapz/blob/8dc64dfd2c7b19e1f64e7ce42e3d6ba4c8d3fbb3/.github/workflows/phase-a-round091-original-composed-compile-noauth.yml) blob `875fdb1fb74d21b56a0eca3df9ec787e54391385`.
- Append-only testing standards blob `70214fff0eee9d652c9e32e91b02ba58e4a5d833`.

**Full standards preservation verified before publication:** exact actual parent and frozen baseline blob `6441a8b096a181b9a80890a1d1f63a87773c3fb3`, raw Git tree size 1796686 bytes, full fetch_blob content matched that byte length and Git blob roundtrip. New blob 1798344 bytes (1658-byte append); exact full new fetch_blob readback equaled constructed text and full old prefix. No truncated contents output used to replace file. CI independently checks actual event.before full bytes/hash/prefix and requires append before expensive stage. Canonical preflight step PASS at current CI snapshot.

## Previous actual failure retained

[R090 job 139108048304](https://github.com/k1moradi/swapz/actions/runs/45586120960/job/139108048304) and [artifact 15008368383](https://github.com/k1moradi/swapz/actions/runs/45586120960/artifacts/15008368383), prior terminal evidence [20fca8dc2780db020b541d787f5c1035cecfe679](https://github.com/k1moradi/swapz/commit/20fca8dc2780db020b541d787f5c1035cecfe679). Raw stage 8/8, libelf header/link/execute PASS and 6/6 actual directed original objects PASS; product compile exit2 first error linux/arch/x86/include/asm/current.h:28:17 struct swapz_shared_original_record has no member named get_current (authority.c:30:29 expansion). Full links NOT_RUN. No repeat of old snapshot.

## Frozen staged source and authorized compatibility scope

Connector read and independent exact Git blob computation verified three raw patch bytes, seven existing pristine Linux file contents and all hunk old lines/counts. Three-stage reconstruction in required order:
1. `tests/tools/round089-original-mm-carrier.patch` blob `059d1bf29cf4990e22a2f608d5d552abeec3a8d1`; 7 changed staged paths.
2. `tests/tools/round090-original-mm-lifetime.patch` blob `337f7ff29e72d955251de0c54a9349f20c2586ec`; 6 changed staged paths.
3. `tests/tools/round088-original-dm-selected-clone.patch` blob `0eaffeb0b1939c889ea7a305b378a9a1fcd75273`; 1 changed staged paths.

| Final staged path | Pristine blob | Predicted final raw blob |
|---|---|---|
| `mm/zswap.c` | `ae19e301fced7e357a4c7587dfdd6abb890b9163` | `cbf160877e8d8b584d6010c009a3e500f8b99f38` |
| `include/linux/swap_ops.h` | `57ac6c703f685883d3a15ebc1a5c7f6c298deb1b` | `a39a1921daf6f272e9812eb63b1aa64fec96c57f` |
| `include/linux/blk_types.h` | `0cc09b975d8ffbd45ca3dc47533a71f8e8164de6` | `50c94617b08e581021ba25fa6e182a5b88ecfa43` |
| `include/linux/bio.h` | `7a794ce723b84b2a148f8f9beccf057b266e8ac9` | `4079365b37690164f85ba962a0bd0918c85899cb` |
| `block/bio.c` | `b0fcc69de653524479e3b328aa29a37e97945b84` | `38f24ee2e414107be390d3a01c6b907e06a9dca7` |
| `mm/page_io.c` | `c6824fcd483e0aa2c412e14dae0d2a356b17c373` | `c3bd481117dbd29edd821df452f74990d6d5f00a` |
| `include/linux/swapz_mm_carrier.h` | absent | `f170d2c2ac63679adb0885f746585ed77c2746a5` |
| `drivers/md/dm.c` | `1881d86111fb2e655893ad898cf21b88f0e4e7f3` | `554dd8215ec6be0cfeaa016ca25e772ac6d363ff` |

Actual Git apply on pinned checkout pending. CI separately checks/applies each raw patch with --index --unidiff-zero --whitespace=error, per-stage postimage pins, exact final path census and raw source diff. No whitespace normalization or fuzzy source edits. 41 frozen product file identities in verifier and JSON; current actual DM `d9f24339c5316cb7de637bbf35b5166fba82436f`, storage header `0da04b61921e3dbc0544cb9c9c8168513628997b`, decoder bridge header `507b25debe0ca7b30b57ed6a350dab4868dced51`. Pinned bvec.h `b63914ff56e33df302055fabf2a84ba490bc8d2c`, R090 core and target already use bi_offset; obsolete bi_bvec_done absent. No old bi_offset overlay.

Only authorized scratch-only kernel current compatibility, verified raw product blobs and exact anchors, independently predicted hashes:
| Product path | Raw blob | Predicted compatible blob | Replacement count |
|---|---|---|---:|
| `authority.h` | `c320498ce530c0887bf498cc4d5b121765bb41f3` | `e65654de963016f62a45944e41de587a6c245f06` | 1 |
| `authority.c` | `73b3e2dc98c6a47315519d3ab650c3d3b0656de7` | `6a1f575b81a2a34a2de5c2bc73e6d0526b899286` | 9 |
| `zswap-original-storage.c` | `d4feaca4d114cfdb1877df65e68e8d6b52859126` | `924bdb7a22a3c308948ecb70909e99892a396472` | 1 |

Member current->is_current in authority declaration, four record field uses, one designated initializer and direct storage consumer; local map pointer current->current_mapping at declaration, assignment and two generation accesses. Native kernel current remains intact; no global substitution, no #undef, no peer file edits. All actual compiled product scope if reached is scratch-compatible, not untouched raw. Actual original patched sources unmodified by compatibility overlay.

Scratch-only Kconfig/Makefile integrates real built-in ticket broker/codec under MM guard, actual original DM core and R090 selected composition guard, real product authority/engine/extent/storage/decoder bridge and original decoder owner in external product module. Correct scratch subdirectory path; module include path for actual carrier header's ticket dependency. No mocks or manufactured exports. Source review: original DM core has three GPL exports for selected clone, selected origin and live route; staged original MM provider/candidate functions and actual broker source do not export their symbols. Potential built-in-to-module symbol/lifetime blocker; not observed modpost result. Keep actual module resolution and absence visible, no fake exports or second broker owner. Full vmlinux and external module/modpost attempted only if preceding directed objects pass, actual symbols/exports/undefined inspection and hashes required. One focused new build attempt. Local full pinned build not performed; use existing exact CI.

## Actual new CI snapshot

[Run 45599641943](https://github.com/k1moradi/swapz/actions/runs/45599641943), [job 139154826234](https://github.com/k1moradi/swapz/actions/runs/45599641943/job/139154826234), exact source `8dc64dfd2c7b19e1f64e7ce42e3d6ba4c8d3fbb3`, attempt1, created 2026-11-25T10:55:54Z, IN_PROGRESS. Actual setup, source checkout, canonical policy/parent/prefix and frozen baseline checkout completed successfully. Pinned Linux checkout in progress. Provision, raw apply, overlay, effective config, actual gelf/ELF compiler/link/execute and OpenSSL prerequisites, directed original/product objects, vmlinux/.ko/modpost, symbol inspection and artifact pending. Build attempts observed0; first new error null pending. No new compiler or runtime PASS. Nine additional inherited automatic runs observed; no manual dispatch/cancellation, Agent2 sole migration successor, no Agent9 lease interference. No polling automation, VM boot/build-for-VM, module load, privileged/physical testing, activation or peer edits. Preserve ordinary 20B map, RAW_4096 full original uncompressed page, protected SWAPSPACE2, Linux MM sole compressed RAM/natural eviction, swapz disk packing/GC, no recompression. AUTH0 Phase A BLOCKED, direct/forced RAW/import OFF. Terminal evidence required for this same run.


## Agent1 independent terminal reconciliation
Exact job139154826234 terminal FAILURE; independently downloaded artifact15014753457 and inspected actual results/logs. Frozen R090 baseline and scratch namespace correction only: original6/product9 directed objects, actual full vmlinux link and empty undefined kernel symbols, product composite linked, modpost six undefined. Kernel hash def4e04f36351fb5f639103c052c43c7bd29a6146bc12489510595161d1afa9f. No final .ko. Artifact contains hashes/logs not binaries. Next lane stages latest frozen R091 source including A5 actual macro fix, R091 DM patch and MM eviction overlay. Agent11 owns real guarded export/provider lifecycle; A10 independently allowed exact scratch-only narrow GPL exports for actual unresolved/used API, no fake symvers/duplicate broker, distinguish from raw. Include missing swapz_ticket_view and audit actual references incl new ordered claim; exact module symbol inventory, actual modpost/final .ko. No boot.
