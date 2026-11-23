# Round072 — Agent5 actual original MM→BIO→authority→independent decoder joined evidence

Official [Round072 issue #189](https://github.com/k1moradi/swapz/issues/189), [frozen contract](frozen-contract.md), Linux pin `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`.

**Exact source/test commit:** [`f7e3a5ad09d7940baa9a149fdb9ac0f55878f68f`](https://github.com/k1moradi/swapz/commit/f7e3a5ad09d7940baa9a149fdb9ac0f55878f68f); **one parent:** `471b406d81b08e097d3bbddc8518d06bab687d8`. Confirmed single-branch `main` non-force expected-head fast-forward and remote ref check. Original source and production C imported into test image byte-identically, not edited in repository.

## Owned implementation

- New test-only original native joined fixture `tests/runtime/native/fixtures/round072-original-mm-bio-authority-decoder-joined.cfrag`.
- New original Linux staging/manifest/source negative tool `tests/tools/round072-stage-original-mm-bio-authority-decoder-joined.py`.
- New actual product-source linked GCC/Clang compiled/executed semantic-mutant verifier `tests/tools/round072-original-mm-bio-authority-decoder-joined-verify.py`.
- New exact-source original UML workflow `.github/workflows/phase-a-round072-original-mm-bio-authority-decoder-noauth.yml`.
- Appended prior-and-peer preserving `docs/testing_standards.md` to same implementation commit. **Product C/H changed: NONE.**

Native fixture is test-only in original `mm/zswap.c`, following existing staged original Round058 MM and Round069 XArray/zsmalloc STORED fixture; links real original `block/bio.c::bio_endio` and byte-identical original-product `authority.c` and `codec.c` and independent `zswap-import-decoder-owner.c` and `zswap-import-codec.h` with real original LZO1X/raw LZ4 decoder. It tests LZO1X, LZ4, GC old reader last put and 13-byte/duplicate lower completion, and checks full original 4096 CRC/SHA. It erases test XArray source and frees native zs object before real endio while native BIO owns copied compressed data. **Test-assembled source is NOT genuine real swapcache-backed STORED**. Decoder `upper_write_ack_count=1` is an explicitly named *model admission assumption*, not a real upper `bio_endio` or physically durable acknowledgement.

## Exact-source CI status (initial committed evidence)

- [Exact source workflow #45127549397](https://github.com/k1moradi/swapz/actions/runs/45127549397) — **QUEUED at initial audit**.
- Host job **137535284018** — QUEUED; actual strict GCC/Clang ASan+UBSan linked C source mutants **NOT RUN** at this report. No host PASS claimed.
- Original Linux pin native 4-case KUnit — **NOT RUN**; native job ID, JSON, KTAP counts unavailable until dependent job scheduled. Existing Round071 independent original BIO/authority 4/4 PASS at `db2b877` is historical, not counted as this joined execution.
- First source/compiler/runtime error: **NONE AVAILABLE YET** (queued, not green). If CI returns FAIL, preserve first actual source diagnostic and update both committed reports rather than lowering tests.

## Preserved gates and remaining blockers

`SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`, `DIRECT_COMPRESSED_HANDOFF=DISABLED`, `FORCED_RAW_BYPASS=DISABLED`, import ACTIVE0. Linux MM/zswap alone owns compressed RAM and natural eviction; swapz owns disk compression, packing and GC without secondary reclaim/recompression. Opaque original LZO1X/LZ4 codec/version tags stay volatile and separate from conventional `RAW_4096` (fully uncompressed original 4096). Protected first SWAPSPACE2 4096-byte block, UUID/partition and fixed 20-byte map unchanged. Rootless source-host/original UML tests only: no real swap device, loaded/privileged Linux, physical media/FUA or actual memory pressure. Production source authentication, current selected upper BIO/ACK and physical durability remain UNPROVEN.

Machine-readable companion: [agent5-results.json](agent5-results.json). The final terminal result requires a subsequent evidence-only fast-forward commit and issue comment with exact job IDs/results.

## Round074 Agent5 actual previous-round host CI audit (Round072 remains OPEN)

The exact-source [run #45127549397](https://github.com/k1moradi/swapz/actions/runs/45127549397) tests source commit [`f7e3a5ad09d7940baa9a149fdb9ac0f55878f68f`](https://github.com/k1moradi/swapz/commit/f7e3a5ad09d7940baa9a149fdb9ac0f55878f68f), parent `471b406d81b08e097d3bbddc8518d06bab687d8`. Actual host job **137535284018 COMPLETED SUCCESS**: original source GCC/Clang 16 cases and ten executed semantic C mutants per compiler; actual product authority GCC/Clang seven lower callback cases and 14 mutated real C callbacks each, plus one retired/close and one GC codec guard mutant per compiler; exact retained decoder owner two semantic C mutants per compiler. Total per compiler: source 10 + authority 16 + decoder 2 = **28**; both strict ASan/UBSan. Host log confirms `PASS round072_original_join_strict_GCC_Clang_ASAN_UBSAN`. This is not original Linux native evidence.

Dependent genuine pinned Linux UML joined native job **137557900023 QUEUED** at this audit; **native JSON=UNAVAILABLE, KTAP=UNAVAILABLE, tests/passed/failed/skipped/crashed/errors=NOT_EXECUTED**. First genuine source/compiler/runtime native error: **NONE AVAILABLE, job not started**. Original source AUTH=0, Phase A BLOCKED, all activation OFF; no real selected source/upper ACK/physical durability. No additional kernel CI run was launched.

## Round075 terminal correction to historical Round072 original-native FAILURE

**This is the terminal verdict for the ORIGINAL unchanged source commit [f7e3a5ad09d7940baa9a149fdb9ac0f55878f68f](https://github.com/k1moradi/swapz/commit/f7e3a5ad09d7940baa9a149fdb9ac0f55878f68f), not a later requalification.** [Original workflow 45127549397](https://github.com/k1moradi/swapz/actions/runs/45127549397) host job **137535284018 SUCCESS** with actual GCC+Clang strict sanitizer original source (ten C mutations each), real authority C (16 each) and independent decoder (two each), but **native job 137557900023 COMPLETED FAILURE** in the source-staging step **before any kernel compiler/boot or joined KUnit execution**. The real log first error, after all ten final Round072 postimage checks succeeded, was:

    Traceback (most recent call last):
      File "<stdin>", line 9, in <module>
    AssertionError
    ##[error]Process completed with exit code 1.

That second Python assertion tested the Round069 PRE-join mm/zswap.c staged SHA after the Round072 composer appended its joined witness to the same mm/zswap.c. This is an out-of-phase manifest check, not a native KUnit failure. **Native JSON/KTAP: unavailable; 4 requested KUnit cases NOT EXECUTED; 0 actual KUnit cases executed, no per-case result**. Do not infer 4/4, or replace this historical failure with any corrected later source SHA. Source AUTH0 and Phase A BLOCKED throughout. The separate Round075 [fix source c45d4e946eed7557daf5c475f0bc89ba5f21435b](https://github.com/k1moradi/swapz/commit/c45d4e946eed7557daf5c475f0bc89ba5f21435b) validates the inherited SHA before append and all final SHA postimages after append, with independent negative checks and a fresh CI run (not part of the old failed run).
