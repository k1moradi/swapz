# Round075 Agent5 — exact original MM staged-source SHA phase ordering repair

**Task**: [Issue #192 Round075](https://github.com/k1moradi/swapz/issues/192), [full Agent5 prompt](agent5-original-native-postimage-order-p0.md), original Linux pin torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8.

**Exact changed-source commit**: [c45d4e946eed7557daf5c475f0bc89ba5f21435b](https://github.com/k1moradi/swapz/commit/c45d4e946eed7557daf5c475f0bc89ba5f21435b); **one parent:** 60b8e074a0e03faefe4ab79e3ae7cceac5b5a465. GitHub sole main non-force expected-head fast-forward verified against live main. Production C/H and all original Linux files unchanged.

## First defect, precise original failure

Original R072 source [f7e3a5ad09d7940baa9a149fdb9ac0f55878f68f](https://github.com/k1moradi/swapz/commit/f7e3a5ad09d7940baa9a149fdb9ac0f55878f68f); original [run45127549397](https://github.com/k1moradi/swapz/actions/runs/45127549397) host137535284018 **SUCCESS**, genuine original pinned Linux UML native137557900023 **COMPLETED FAILURE** in staging. The source-stager emitted six negative-plan PASS and ten verified final Round072 postimage hashes. Immediately afterward a SECOND inline workflow Python compared Round069 pre-join mm/zswap.c staged_sha256 to Round072 post-join mm/zswap.c, raising **Python AssertionError at second inline block line9**, exit1; **no original Linux compiler/boot or KUnit test executed, native JSON and KTAP unavailable**. This is historic and remains permanently FAILED, independent of this new source code.

## Surgical repair

- Existing .github/workflows/phase-a-round072-original-mm-bio-authority-decoder-noauth.yml: preserve original six-assertion inherited manifest source SHA block exactly, but execute it **BEFORE** Round072 appends; retain original complete ten-file final SHA inline block AFTER staging. Add full new two-phase snapshot/order verifier and own host self-test, trigger this workflow on future edits to new focused verifier.
- New tests/tools/round075-original-stage-manifest-order-verify.py: in the real pinned test tree, independently prove pristine original mm/zswap.c and block/bio.c pinned Git blobs, inherited original source SHA and exact test fixture before joined append; take an immutable verified prejoin snapshot, verify final different ten SHA postimages after append, bind final manifest to the inherited manifest SHA256, compare full joined postimage to **exact copied prejoin bytes + inherited native BIO fixture + final four-case KUnit source fixture**. Ensure byte-identical copied actual product decoder/authority/codec C/H Git blobs.
- Source-true host self-test: two valid phase baselines and **12 negatively checked** tampered inherited source/manifest, spoofed inherited SHA, original SHA/blob change, wrong source-stage order, missing final joined witness, wrong/forged final hash, wrong manifest binding, bad product C copy, joined wrong pin and post before joined stage. Each negative must fail with its exact expected error; cannot weaken real original staging source.
- Existing Round072 host verifier unchanged: it still compiles and executes GCC+Clang strict -Werror ASan+UBSan, 10 original source C semantic mutants, 16 genuine product authority C mutants and two decoder-lifetime mutants PER compiler.
- Append-only docs/testing_standards.md meaningful policy update; original code, codec tags, all production activation flags untouched.

## New exact-source CI — initial publication state

[New focused run 45154196590](https://github.com/k1moradi/swapz/actions/runs/45154196590), exact source c45d4e946eed7557daf5c475f0bc89ba5f21435b, initial **QUEUED**, host job **137622871354 QUEUED**, original pristine Linux dependent native job **NOT SCHEDULED** at initial evidence audit. Target four genuine KUnit cases original LZ4/LZO1X, GC retained reader and lower error; **4/4 NOT YET PROVEN**. Host new self-test and inherited GCC/Clang source mutants are not yet claimed PASS for this SHA. First new CI error: **NONE AVAILABLE (queued)**. Subsequent CI terminal outcome requires an evidence-only update with actual job ID and first original compile/boot/runtime error or genuine 4/4 JSON/KTAP.

## Safety / unproved activation

SOURCE_MAPPED_AUTHENTICATED=0, PHASE_A=BLOCKED, DIRECT_COMPRESSED_HANDOFF=DISABLED, FORCED_RAW_BYPASS=DISABLED, imported ACTIVE0. Linux MM/zswap solely owns compressed RAM and natural evictions, swapz controls only disk packing/GC with no competing reclaim or recompression. Original LZO1X/raw LZ4 exact compressed stream and decoder lifetime uses distinct volatile codec metadata, NEVER ordinary RAW_4096 (entire original UNCOMPRESSED 4096). Protected first physical SWAPSPACE2 4096/UUID/partition and fixed 20B map unaffected. Original fixture test-assembled source is NOT real swapcache STORED, physical FUA, selected upper ACK or production authentication. No privileged, loaded, swapon, physical device, or real pressure tests.

Companion machine results: [agent5-results.json](agent5-results.json).
