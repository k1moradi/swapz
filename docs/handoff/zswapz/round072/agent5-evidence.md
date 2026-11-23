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
