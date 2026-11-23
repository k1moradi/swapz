# Round072 Agent7 — exact-source codec versus conventional RAW ABI

## Exact publication and test status

- **Tested source commit:** [`adc38477c80706908df94097467c75e0a0727753`](https://github.com/k1moradi/swapz/commit/adc38477c80706908df94097467c75e0a0727753) (one parent [`923709674f2d94e766b9409f1fef776b34825687`](https://github.com/k1moradi/swapz/commit/923709674f2d94e766b9409f1fef776b34825687)); original task `3c1919f1b2c2ea428045a1afb5c278151cf06ccc` and frozen engineering baseline `4083449f12c3392d5ea534ee4e536865b4caf3ee`.
- **GitHub Actions:** [run 45127458505](https://github.com/k1moradi/swapz/actions/runs/45127458505), [job 137534988276](https://github.com/k1moradi/swapz/actions/runs/45127458505/job/137534988276) — **QUEUED**, no terminal result, no compiler assertions claimed PASS. This document is a durable preliminary report, to be updated after terminal CI.
- **Exact source linkage (Git blob IDs):** host C `00b853fbe0a17bff4b1f9158491667983074562b`; strict Python verifier `b7f91671f6833d0b4a347aa0d6318c856a57779c`; product `codec.c d920dcaac6f2b7de1334d4133770bd649719c66d`, `zswap-import-codec.h 0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6`, `zswap-direct-handoff.h 864abf9a12071b98f5c157a44f4ed0c04d4a594c`.
- **Original Linux pin:** `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`, `mm/zswap.c`, `lib/lzo/lzo1x_decompress_safe.c` and `lib/lz4/lz4_decompress.c`. Genuine original-kernel native KUnit **NOT_RUN** (native JSON/KTAP **NOT_RUN**); this host test does not execute original MM/zswap or prove source provenance.

## Implemented independent rootless test

Exclusive new `tests/runtime/native/fixtures/round072-original-codec-tag-vs-raw.c`, `tests/tools/round072-original-codec-tag-vs-raw-verify.py`, and `.github/workflows/phase-a-round072-original-codec-tag-vs-raw-noauth.yml` read original product `codec.h`, `codec.c`, `authority.h`, `zswap-import-codec.h`, `zswap-import-admission.h` and `zswap-direct-handoff.h` without modifying production. Strict GCC+Clang C23 ASan+UBSan, exact 4096 original-page SHA-256, unframed LZ4 decoding, immutable exact byte copy, separate volatile original codec identity, 4/8/16KiB extent padding, first physical protected 4096 bytes, 20-byte map, source epoch, CRC, truncated lower bytes and ordinary **full uncompressed RAW_4096** are executable checks. Fourteen meaningful C semantic mutants are configured **per compiler**, but compiled/executed count remains **unknown until CI completes**. No hot-path heap allocation.

Original LZO1X is preserved only as a distinct opaque source-family tag and exact source byte copy: the generic host build intentionally has no pinned original LZO decoder lease; positive original LZO decode is **NOT_RUN** and must not be reported PASS. Host-generated LZ4 input is not an authentic original Linux zswap STORED object. Neither upper ACK nor durable lower I/O is real; the read-authority receipt is explicitly a test-supplied witness, not source authentication.

## Concrete source-only interface divergence

`src/kernel/zswap-import-codec.h` assigns **original LZO1X = 2**, but dormant `src/kernel/zswap-direct-handoff.h` assigns **direct ZSTD = 2**. A numeric cast crosses disjoint codec families incorrectly. The exclusive test uses an explicit family adapter that refuses LZO on the older direct interface; the negative mutant attempts the exact prohibited collision. This is a source-only dormant integration mismatch for Agent1 to track, not proof of a live production vulnerability. No product header modification was made.

## First failure and immutable gates

**First actual CI error: none yet (QUEUED).** Source AUTH=0, Phase A **BLOCKED**, direct compressed handoff **OFF**, forced RAW bypass **OFF**, all imports ACTIVE0, original opaque payload **not** ordinary RAW, Linux MM/zswap alone handles natural evictions, swapz exclusively disk packing/GC, no secondary reclaimer or recompression. No physical partition, UUID, SWAPSPACE2 header, FUA, loaded kernel, root-level swap or pressure experiment occurred.
