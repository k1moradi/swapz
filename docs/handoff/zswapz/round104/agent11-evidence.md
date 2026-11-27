# R104 A11 — actual original MM/core witness integration

**SOURCE_PUBLISHED_QUALIFICATION_PENDING.** Agent1 owns integration/final acceptance. Source-only guarded integration, no physical authority.

## Immutable source and publication

Issue #222, task 3ec158e2870170bd58fc13dfc340722a89f51cae, freeze a9094f96e3fb2841ed0fa553102d98699950221d tree 554b80152c9ea277cd6e0f63069bfb8f8ba671b6, Linux c339f4010dea8b0d754f84ace70cd1b089878ef8. [Source commit 3c11e1463029cb1095d4c4af84739cbdb062c6c1](https://github.com/k1moradi/swapz/commit/3c11e1463029cb1095d4c4af84739cbdb062c6c1); sole fresh parent eba09a4abb2a9afcc5b9775924f578f1fc8661c5, tree 18b39fe8dcdcdb3d00133e84863c78478c2bb615. Main-only expected-head nonforce update/readback verified. No same-round peer source consumed. Task header blob e3bca3367459c7f79960105f63e9ddef4e95b4d6 unchanged; frozen R103 adapter and owner declarations explicitly staged by exact hashes, no new peer native implementation. Standards raw complete prefix a253b3423c55107140ddaccc3568d6721a1f710f hash-verified, appended raw readback c74fb3b65869ac5a50755a26a92db41f299a4e01.

- `tests/tools/round104-original-mm-core-witness.patch` — `132c03fcefe961696f468a41c763666f1dc4f90c`
- `tests/tools/round104-mm-core-witness-verify.py` — `4e7bea38ad8529eb47eaae8718aacd1c5fbf3fde`
- `tests/runtime/native/fixtures/round104-mm-core-witness.c` — `3b26bb20585b28528c24fcbcdb1394ee83ddd6c6`
- `.github/workflows/phase-a-round104-mm-core-witness-noauth.yml` — `7d159e7ad3339b5da0b613de493640e936f30a0f`
- `docs/testing_standards.md` — `c74fb3b65869ac5a50755a26a92db41f299a4e01`

## Actual call sites and lifetime

- `swapz_mm_trial_scope_matches_exact(scope, mapper_file)` uses RCU currently published capture pointer, exact independently retained mapper-file pointer, every identity/device/broker/session/table/target/area/type/range field, and actual live area epoch. Non-sleeping under target queue lock, no ref transfer. Publication/stop/area invalidation and observation unpublication grace remain existing R103 lifecycle; a pre-stop RCU reader can finish under the established grace rule. No new control/activation.
- Actual `zswap_store_page`: before `zswap_compress`, guarded exact scope/byte gate, whole-page locked folio and direct block slot/type/epoch/sector identity, `kmap_local_folio` then synchronous `swapz_trial_byte_stage_input` copy then unmap. No allocation, SHA, extra I/O, 4K stack or decoder-derived input. After real successful XArray insertion under folio lock, finish token with actual `entry->original_cookie` before LRU publication; failure labels finish zero, raw/ineligible cookie zero abandons. Actual cookie with missing input while byte gate live invalidates evidence. Old replaced entry cannot acquire the new cookie; A2 owns independent key/retention invalidation. No change to ordinary zswap decisions, compression or error returns. Guard absent adds no store work.
- MM CAPTURE/PREPARATION/BIND/CAPTURE_DROP/CARRIER_RELEASE and original MM UPPER_ENDIO call the shared inline evidence helper: real `swapz_trial_observation_append_sequence` once, then byte_event with actual record/returned ordinal and NULL/0 (not independent byte witness); zero or bridge failure calls byte invalidate. Existing original MM SIO callback remains actual typed-write ACK site. Ordinary WRITE ACCEPT and pinned final BIO ORACLE bytes are A3 responsibility; A2 owns bridge/byte retention and outcome correlation. No new schema or expected outcome plan.
- Ordinary DM final unsplit completion now stashes operation/original into exact retained original debt slot (no early ACK). Actual original terminal wrapper builds UPPER_ENDIO from final BIO status at callback entry, after block completion/deferred completion, restores and invokes original callback, releases terminal ticket only after return without dereferencing BIO. Typed carrier is excluded from DM ordinary origin; no clone-as-upper ACK. Requeue/split/flush reissue invalidates evidence without duplicate valid append or remint; terminal debt retained through reissue. Real block-layer `bio_chain_endio` special sentinel is detected by guarded helper even for fresh noncloned child; callback is never replaced. Chained parent retains original callback debt but evidence is rejected; missing callback/cloned/remapped/late shapes fault qualification, no alteration of ordinary I/O. Actual chain remaining-count/deferred endio concurrency still needs native runtime review.
- Original R103 allocator publication/invalidation/retirement and external exact terminal join are not rewritten. Scope close, target/provider/map/worker/candidate and broker debt remain independent. Sticky qualification loss cannot authorize use. Explicit development build guard only, no physical admission.

## Staged source identities

| Path | Frozen preimage | Predicted postimage |
|---|---|---|
| `mm/zswap.c` | `833f089bc01e8803f427732975d706c894436eb3` | `e088dd706763bec377d09a81905cf5de9b371c6a` |
| `drivers/md/dm.c` | `e07dfd963edcdfb438af2ae1f43e3023e54544b7` | `6912eb7ec5a9ef325f7282ef9c9226b39265f01d` |
| `mm/swapz-trial-terminal.inc` | `3f980d04958676c22d44a6ca2778c4bd40a464fb` | `1ecc86d30f20790f1fae7506a3f55d612200831a` |
| `include/linux/swapz_mm_carrier.h` | `7091e456b6c09f29d68140cfff3f072e940ccd2f` | `b930f6f04a21d3f2b8b6f2279e028a94cfc99502` |
| `include/linux/swapz_trial_debt.h` | `207cd1b7a87f493992938cfa00ed4f95c7196811` | `d1d2fc65084936380c211094ce6f073273596338` |
| `block/bio.c` | `38f24ee2e414107be390d3a01c6b907e06a9dca7` | `f6f1ddc82a5632f1f9cf8dbb0bdb2138eb8e0e64` |
| `include/linux/bio.h` | `4079365b37690164f85ba962a0bd0918c85899cb` | `c7d5543249003b7f190d6ea065fd6253d5572792` |

Connector reconstruction verified seven full Git blobs and deterministic strict zero-context overlay roundtrip; this is not hosted Git apply or compile credit. Hosted verifier stages exact historical R101/R103 original overlay chain and reverse/reapply; exact R104 pre/postimage checks, strict index apply/check/reverse/reapply and staged census/diff. Stage immutable task header and R103 adapter/owner declarations separately. Actual extracted scope, area, stage/store, ordinal and terminal source functions in host fixture; modeled kernel RCU/locks, BIO, allocator, compressor and peer recorder/byte calls. Six requested modes normal (scope field/file mismatches, actual source before compression, actual committed cookie, replacement and abort, exactly one original ACK and real debt), chain, chain-parent, requeue, late, ordinal. Five actual source mutants wrong-file, wrong-store, late-input, chain-child, early-ack; GCC and Clang ASan/UBSan assertions requested. Only directed mm/zswap.o, mm/page_io.o, drivers/md/dm.o, block/bio.o, SMP/TREE_RCU default-off generated config. Page_io unchanged raw source; built because original typed ACK uses changed header. No full link/MODPOST/VM; no native fake peer definitions. Expected unresolved peer symbols listed in JSON, must be verified via nm/relocations, no native link credit.

## Qualification snapshot

Local git ls-remote exit128 DNS could not resolve github.com. [R104 focused run 45954589398, job 140358011743](https://github.com/k1moradi/swapz/actions/runs/45954589398/job/140358011743): **IN_PROGRESS**. Direct-main and full standards-prefix precheck PASS. Artifact count 0. No terminal qualification first error verified. GCC/Clang host counts, mutants, actual source staged/native compile, generated config and object/symbol hashes not yet independently verified. No fabricated success. No manual duplicate dispatch.

R103 corrected lane accepted by A1 checkpoint only, not R104: 1235 checks per compiler, all four directed objects, job 140342576444 after filename repair. Historical qualification preserved, not replayed unchanged as current test.

AUTH0 Phase A BLOCKED, compressed handoff/forced RAW/import OFF, physical NO_GO. No branches, PRs, force pushes, duplicate dispatches, disconnected full build, VM, module load, activation, device I/O or physical mutation.
