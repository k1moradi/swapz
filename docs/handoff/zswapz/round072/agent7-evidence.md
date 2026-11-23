# Round072 Agent7 — source-linked original codec family vs ordinary RAW ABI

## Exact tested source and committed input

- **Latest owned source/test SHA:** [`8fb2577d589ca7ea851d14968098b2b668934f38`](https://github.com/k1moradi/swapz/commit/8fb2577d589ca7ea851d14968098b2b668934f38), **single parent** [`8d9f3d41fe26855b034eae404447c3fb47b08b49`](https://github.com/k1moradi/swapz/commit/8d9f3d41fe26855b034eae404447c3fb47b08b49). Root task: `3c1919f1b2c2ea428045a1afb5c278151cf06ccc`; baseline `4083449f12c3392d5ea534ee4e536865b4caf3ee`.
- **Exact GitHub Actions:** [run 45129220684](https://github.com/k1moradi/swapz/actions/runs/45129220684), [job 137540595608](https://github.com/k1moradi/swapz/actions/runs/45129220684/job/137540595608) are **SUCCESS**, terminal exact-source. GCC (C2x) 92 assertions PASS + 15/15 compiled/executed semantic C mutants; Clang (C23) 92 assertions PASS + 15/15 mutants. Both strict ASan+UBSan. Host JSON/KTAP artifact `round072-agent7-host-only` (artifact ID 14801632608); host KTAP 2/2 per workflow; real original native kernel JSON/KTAP **NOT_RUN**.
- **Owned source blobs:** C `6ee48cc2ee6af36ecdb73c1379cbeba64125f8a9`, Python `656a98027e31d2948c9ddc26345d8391ef574ff9`; product source `src/kernel/codec.c` `d920dcaac6f2b7de1334d4133770bd649719c66d`, `zswap-import-codec.h` `0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6`, `zswap-direct-handoff.h` `864abf9a12071b98f5c157a44f4ed0c04d4a594c`.
- **Pinned original Linux** `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`: `mm/zswap.c` blob `ae19e301fced7e357a4c7587dfdd6abb890b9163`; `crypto/lz4.c` `57b713516aefac823f2af9481c828027b42490dd`; `crypto/lzo.c` `d43242b24b4e831e7e0d26f38d2f263877d5748e`; `lib/lz4/lz4_decompress.c` `3a2cd9acada4a09ef70a344090d48167c46088a1`; `lib/lzo/lzo1x_decompress_safe.c` `318abb82c63d2c27c0d5497b7cf4e21d87d13154`.

## What the exclusive test actually covers

Two new rootless standalone files `tests/runtime/native/fixtures/round072-original-codec-tag-vs-raw.c` and `tests/tools/round072-original-codec-tag-vs-raw-verify.py`, plus a new GitHub Actions workflow and same-commit applicable testing standards additions, compile the repository's real read-only `codec.c`, `codec.h`, `authority.h`, `zswap-import-codec.h`, `zswap-import-admission.h`, and `zswap-direct-handoff.h`. There are **no product changes**. The fixture has zero heap allocations and one ordered host owner. It checks host-generated raw LZ4 round-trip to an independently hashed full 4096 page, exact opaque compressed byte copy, separately volatile source codec/version/epoch, compressed CRC/length, stale identity, mismatched codec and digest, truncated lower read, immutable first physical 4096 bytes, 20-byte map, and only 4/8/16KiB payload extents with deterministic zero padding. `RAW_4096` is always a **whole original uncompressed 4096-byte page**.

The source-linked dormant direct decoder registry is now separately called to reject stale **pool identity, dictionary identity, codec generation, source-record identity, wrong decoder family, and wrong independent SHA-256**. The test supplies fake ownership/ACK and a host-made input: this is **not** original Linux STORED provenance, a genuine decoder-owner lease, real FUA, upper ACK, actual Linux zswap eviction, or a physical load test. Original LZO1X is exact-byte opaque only: an original pinned LZO decoder was not linked for this host test and positive LZO decoding is **NOT_RUN**.

**Concrete source-only API divergence:** original import LZO1X codec `2` and dormant direct ZSTD enum `2` are numerically equal but semantically different. The explicit test adapter rejects this cast; a meaningful negative mutant attempts the unsafe acceptance. No production file or physical on-media codec encoding was altered.

## First error / progress

**Latest exact-source first actual error: NONE — terminal SUCCESS.** The superseded original source SHA `adff0ee5ee3245681118e21f64ab5d6f4a90ede2` was **red** in [run 45127087314](https://github.com/k1moradi/swapz/actions/runs/45127087314), [job 137533799500](https://github.com/k1moradi/swapz/actions/runs/45127087314/job/137533799500): GCC's first 63-assertion host baseline PASS, then GCC compiler refused the `owned-source-lease` semantic mutant under strict `-Werror` due the test-generated boolean expression. The verifier was subsequently changed to parenthesize all mixed boolean mutants and emit the first actionable compiler `error:`; this does **not** certify the latest SHA or hide the older failure.

**Unchanged gates:** `SOURCE_MAPPED_AUTHENTICATED=0`; `PHASE_A=BLOCKED`; direct compressed handoff OFF; forced RAW bypass OFF; all import ACTIVE0; no extra reclaim/pressure controller or recompression. Linux MM/zswap owns natural eviction, swapz disk packing and GC only. No privileged/loaded/physical/real-swap/pressure/FUA experiments. Terminal CI recorded in this evidence-only follow-up; test source and standards unchanged.

The newest test source additionally binds the contiguous **readable source capacity**
under its test-only owner before byte-copy. A one-byte truncated source-copy
negative and an ordinary full-RAW 4095-byte lower read negative independently
expose both guards; the compressed decoder's own short-read check can no
longer make the host mutant redundant. **15 negative C mutants per compiler**
**PASS / rejected 30 of 30** in terminal exact-source CI.

## Terminal verification

Exact run [45129220684](https://github.com/k1moradi/swapz/actions/runs/45129220684), job [137540595608](https://github.com/k1moradi/swapz/actions/runs/45129220684/job/137540595608): success. GCC `-std=c2x`: 92 host-directed assertions and 15/15 compiled/executed C mutants; Clang `-std=c23`: same 92 assertions and 15/15 mutants. Strict warnings, ASan+UBSan, canonical GitHub repository policy and Actions artifact upload success. Artifact `round072-agent7-host-only` ID `14801632608` includes host-only JSON/KTAP; source auth0, no original-native KUnit/KTAP, no real swap I/O.
