# Round073 Agent10 — pinned original reader pin / GC / decoder lifetime

**Current evidence: PROGRESS — CI QUEUED, NOT PASS.** The source/test commit is [`ecaf63cb7860879364a6e3943884bc30e578ca63`](https://github.com/k1moradi/swapz/commit/ecaf63cb7860879364a6e3943884bc30e578ca63) with its **single parent** [`bd78c1382b284bf257e2c452247efe1512a799a3`](https://github.com/k1moradi/swapz/commit/bd78c1382b284bf257e2c452247efe1512a799a3). The Round073 task publication is `5f4d74f1ea538187e37fa0cdec2babb49186c59d`; the separate original Linux pin is `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`. **No native success is asserted.**

## Exclusive new owned paths

- `tests/runtime/native/fixtures/round073-original-reader-pin-gc-kunit.cfrag`: genuine original Linux zswap source fixture KUnit, four distinct read-side cases.
- `tests/tools/round073-stage-original-reader-pin-gc.py`: pin-checking scratch-only stage of inherited Round058/069 original upstream mm/zswap and block/bio source; byte-identical current product authority, codec and decoder-owner snapshots, ten per-path SHA-256 postimages.
- `tests/tools/round073-original-reader-pin-gc-verify.py`: source-host preflight, independent C23/C2x GCC/Clang ASan+UBSan compiled-executed semantic mutants, real current source-linked authority and decoder lifetime checks, strict 4/4 native JSON/KTAP verifier and forged-result negatives.
- `.github/workflows/phase-a-round073-original-reader-pin-gc-noauth.yml`: one scoped source-host plus one dependent rootless original Linux UML native KUnit job; no scheduled trigger.
- `docs/testing_standards.md`: cumulative same-source Round073 rule appended without replacing prior policy.
- This file and `agent10-results.json`: immutable GitHub-first pending evidence, not a substitute for CI artifacts.

## Source chain and proof boundary

The new independent READ-side KUnit consumes the pinned-original XArray/folio-lock/zsmalloc test-created STORED source, retains an exact owned compressed-byte copy and a separately tagged original LZO1X or raw LZ4 codec, and releases its original source object. It stages a prerequisite in-memory lower BIO through the **actual original kernel `bio_endio`** and frozen current product authority, then begins a **real product authority pinned lower READ** before a byte-identical physical-extent *RAM model* GC move. The old extent must remain live until that actual read endio and pin release, including after GC epoch advances. The old original decoder lease allows complete independent 4096-byte decoding after source destruction, then closes/drains; a late get and duplicate put must be rejected. Negative cases require output untouched for stale source/store generation, stale GC epoch, wrong original codec, CRC and SHA.

Only `mm/zswap.c` and temporary copied product C/H are modified in a rootless, private **scratch original Linux checkout**. Checked-in product `src/kernel/*.c` and the original upstream repository stay read-only. Round072 writer-MM-to-BIO fixture and Agent4 original pool/RCU retirement fixture are **not used as test dependencies**. Prior Round058/069 pinned original upstream staging is an already-published input. Exact original committed Linux blobs, current product Git blobs, the inherited postimage, test fixture structure and all new staged SHA-256 postimages fail closed on drift.

**Not authenticated:** the original STORED XArray entry uses a *test-created locked folio* and is **not** independently proven swapcache-backed. This does not prove the real original zswap natural eviction, selected-current DM ownership, actual durable device FUA/flush, real physical reclaim, or a real upper completion. The native closer thread exercises the separate decoder-owner lease, **not** actual original upstream pool RCU retirement. There is no independent RAM-pressure initiator, secondary shrinker or recompression. Original compressed codec identity is independently volatile; ordinary `RAW_4096` always means full original **uncompressed** 4096 bytes.

## Exact CI and tests, pending

- [Run `45134656124`](https://github.com/k1moradi/swapz/actions/runs/45134656124), event `push`, exact head `ecaf63cb7860879364a6e3943884bc30e578ca63` (captured immediately after publication).
- [Source-host job `137557932353`](https://github.com/k1moradi/swapz/actions/runs/45134656124/job/137557932353): **QUEUED** at first direct inspection; no observed real GCC/Clang baseline, sanitizer or mutant execution yet.
- Original Linux UML native job: **not created / waiting on host dependency** at first inspection. Expected four cases: `swapz_round073_original_lz4_old_reader_gc`, `swapz_round073_original_lzo1x_old_reader_gc`, `swapz_round073_original_stale_crc_sha_codec`, `swapz_round073_original_decoder_retire_with_pin`. Actual native KUnit JSON/KTAP **NOT_RUN**, not four passes.
- Source verifier demands **10 independently compiled and executed original-source C23 semantic mutants for GCC and 10 for Clang**. It also rechecks existing changed real product authority GC/lower mutants (14 per compiler) and decoder drain lifetime mutants (2 per compiler); these counts are **expected only, not observed** as of this evidence. Strict `-Werror`, ASan+UBSan; compiler failure cannot count as mutant rejection.
- CI preflights `git diff --check HEAD^ HEAD` and canonical `repository-policy-test.py --enforce`. The GitHub staged blob publication was checked for new-file trailing whitespace and source pinning, but **no independent local Linux compilation or KUnit run** occurred in this environment.

## First failure and next action

`first_error=null` because no execution failure was observed; **queued is not passed**. Once this exact source run reaches terminal state, read its existing logs/jobs **on demand**, record the first genuine root-cause/error, actual compiled-executed per-compiler counts, exact native JSON/KTAP and the run/job links, and publish a **separate evidence-only** main commit updating both handoff files. Do not rerun unchanged CI, schedule polling, create branches/PRs or ask the owner to upload evidence.

Safety gates: `SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`, `DIRECT_COMPRESSED_HANDOFF=DISABLED`, `FORCED_RAW_BYPASS=DISABLED`, import `ACTIVE0`; no privileged, loaded, real pressure, swap activation or physical I/O. Original Linux MM/zswap alone owns compressed RAM pressure/eviction; swapz owns disk packing/GC.


## Agent1 independently verified terminal exact-source CI (COMPLETED_FAILURE_ORIGINAL_UML_COMPILE_BEFORE_KUNIT)

This manager terminal audit **supersedes earlier QUEUED status only for this immutable tested SHA**, preserving original source commit `ecaf63cb7860879364a6e3943884bc30e578ca63` and previous reports. [Existing Actions run 45134656124](https://github.com/k1moradi/swapz/actions/runs/45134656124), [actual job 137610101851](https://github.com/k1moradi/swapz/actions/runs/45134656124/job/137610101851) is **COMPLETED FAILURE**. Original reader source-host job137557932353 SUCCESS; native job137610101851 FAILED after pinned-source stage negatives and 10 final native postimage hashes verified, in original staged linux/mm/zswap.c:5307:25 implicit declaration of function usleep_range [-Werror=implicit-function-declaration]. Test fixture tests/runtime/native/fixtures/round073-original-reader-pin-gc-kunit.cfrag calls usleep_range(1000,2000) without explicit linux/delay.h include; original UML KUnit ZERO, no JSON/KTAP PASS. Round077 Agent10 owns minimal test-only fix.

**Scope:** genuine original pinned UML native was attempted but failed compilation before any KUnit cases ran. Source AUTH0; Phase A BLOCKED; direct handoff, forced RAW and import OFF; ordinary RAW_4096 complete ORIGINAL UNCOMPRESSED 4096. No new periodic CI checks. One surgical original-native test-only correction is assigned to Agent10 in Round077; keep this exact source/red result historical.

## Round077 Agent10 subsequent original delay declaration — distinct new SHA, no retroactive old PASS

The historical Round073 exact source `ecaf63cb7860879364a6e3943884bc30e578ca63` and [run 45134656124](https://github.com/k1moradi/swapz/actions/runs/45134656124) **remain native FAILED before KUnit with zero executed cases** and the unchanged first `usleep_range` declaration error. The narrowly repaired original test-only source is `04b190b00131c1d40254acd2279e6240a11913d0` ([new distinct run 45179168125](https://github.com/k1moradi/swapz/actions/runs/45179168125)); its verdict is independently **PENDING**. The authoritative current-source evidence lives in [Round077 Agent10 evidence](../round077/agent10-evidence.md) and [JSON](../round077/agent10-results.json). Never repaint prior red native as success.
