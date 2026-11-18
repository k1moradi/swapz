# Round034 Agent2 — original Linux zswap=y KUnit source evidence

## Scope and safety

Agent2 owns only the original pinned Linux source compositor and new original BIO KUnit execution path. This commit never changes the original Linux repository's pinned upstream SHA `c339f4010dea8b0d754f84ace70cd1b089878ef8`, its immutable 10 preimage hashes, the original old MM/BIO stagers, the Linux zswap compressed-RAM eviction policy, or `src/kernel/dm-target.c`. The entire v1 KUnit addition is gated by new, undefined-by-default `SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST` **and** previous BIO/MM/copied-view CI gates **and** `IS_ENABLED(CONFIG_KUNIT)`. The default production kernel must not acquire a new export, metadata field, write path, or external import.

## Exact original source being tested

Original `block/bio.c` receives six additional guarded KUnit cases in the existing `swapz_round025_sideband_compiler_only` suite, preserving all 11 original KUnit source cases. They call the actual `swapz_ci_bio_snapshot_lz4_v1`, with the actual refcounted original sealed `swapz_ci_owned_create_source_v1` constructor, not a reimplementation. A KUnit-owned one-page BIO has `REQ_OP_WRITE | REQ_SWAP`, zswap-stored original origin, `bi_iter.bi_size=4096`, `bio_sectors=8`, and the genuine original `bi_vcnt=0` **despite its one populated bvec**. Original kernel LZ4 creates independent compressed bytes, and original kernel SHA-256 covers exactly 4096 bytes before compression. The accessor must preserve the source full swap entry, epoch, stored identity, CRC32C, representation version, codec and store-time plaintext SHA; a real LZ4 decoder checks full 4096 exact SHA. These are **KUnit synthetic producer inputs**: neither an actual MM zswap STORE nor true pressure/eviction.

New cases:
1. `swapz_round034_v1_owned_copy_kunit`: real original kernel LZ4 input and 4096 SHA, independent source corruption after sealing, real v1 copy/decode, copied bytes surviving parent uninit.
2. `swapz_round034_v1_bio_reject_kunit`: READ/WRITE distinction, missing REQ_SWAP, wrong page size/sector count, nonzero iterator offset/index, fabricated bi_vcnt, ordinary origin and cloned geometry.
3. `swapz_round034_v1_owner_reject_kunit`: missing source entry, zero epoch/stored identity, unsupported codec/version, impossible length/CRC and missing store SHA; both outputs must stay byte-identical on rejection.
4. `swapz_round034_v1_constructor_reject_kunit`: null full source entry, zero epoch/identity, wrong length/codec/CRC, zero digest; valid BIO with detached owner refuses.
5. `swapz_round034_v1_alias_kunit`: output-vs-view alias, output-vs-private-owner alias, undersized destination, unchanged caller output and source bytes.
6. `swapz_round034_v1_lifetime_kunit`: true original clone refcount across parent release, no freed-BIO accessor invocation, stale clone rejection, independent successful copied bytes, real split and both half-page snapshot refusals.

## Evidence gate and CI status

The new `.github/workflows/phase-a-zswap-original-v1-kunit.yml` is triggered by this source-changing main commit. It stages and SHA256-verifies all ten generated files against the exact pristine original Linux checkout. It runs existing source-extracted original C provider with strict GCC and Clang `-Wall -Wextra -Wshadow -Wconversion -Werror` and ASan/UBSan, and adversarial verification self-tests. It must boot **actual original Linux UML** with effective `CONFIG_ZSWAP=y`, `CONFIG_SWAP=y`, original LZ4 compression/decompression and SHA256 library, actual guarded KUnit C. It records first failure, real v1 JSON and KTAP, effective config and kernel hashes. A new independent verifier refuses any missing, duplicated, skipped, failed, crashed or fabricated case; exact total demanded is 11 old + 6 new = 17, **not a claim of executed 17 until actual CI evidence exists**.

**Status at source authoring: CI not yet executed.** This file must be updated with the exact run, job, failure and verdict after the GitHub Actions run is inspected. No source-only static or hosted mock result is sufficient for a runtime PASS.

## Missing authority and explicit NO-GO

The real full packed `swp_entry_t.val` created by `mm/zswap.c` cannot be inferred from sector arithmetic or KUnit sample values. Original `mm/page_io.c` moves an original owner's reference into the 4096 BIO after setting origin/size, but the v1 KUnit source constructed in this test does **not** prove a real active swap-area type→bdev→mapped-device mapping or current slot incarnation. There is no demonstrated executed original MM `zswap_writeback_entry` STORE-to-pressure eviction. These remain separate **NOT_RUN/unproven** gates even with `CONFIG_ZSWAP=y`.

`PHASE_A=BLOCKED`, `FORCED_RAW_BYPASS=DISABLED`, `DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED`, `LOADED_ORIGINAL_4096=NOT_RUN`, `PHYSICAL_SWAPSPACE2=NOT_RUN`. Original RAW is **uncompressed original 4096 bytes**, never compressed stored LZ4. No change to protected SWAPSPACE2 first 4096 header, signature, UUID, partition table or any physical disk, swapfile, module-load or pressure trial; no host privilege or real-device execution. Future authentic stored LZ4 requires independent current source epoch, mapping and durable READ-back authority before lower-copy staging/once ACK.
