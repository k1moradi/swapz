# Round024 — Agent1 accountable integration and source qualification

**CLOSED_SOURCE_COMPILED_FINAL_8_OF_8_CI_PASS; LIVE_AND_PHYSICAL_BLOCKED.** Official issue #141 https://github.com/k1moradi/swapz/issues/141 . All complete original reports and source-status updates are preserved in [the verbatim archive](original-report-archive.md). Final exact engineering source [c2469a86107f632dc795f4957113234f5bac62f6](https://github.com/k1moradi/swapz/commit/c2469a86107f632dc795f4957113234f5bac62f6).

## Actual ancestry, file ownership and first failure

Task SHA 0f812e51b242b13229cc78f00368eff1f67085a2, then exactly eight consecutive one-parent nonforce direct-main engineering commits: Agent3 actual module import compiler probe 94512aeb2198a56d12ca0a91b8ec15c811fb20d4; Agent2 pinned Linux compiler-probe 2ac53e70a384abd8bd3fcede1aff4741b2500129; source-host test repairs fb4bbc01963f1e0b32825b993744a598ab5f76d7, 15824ab7cf95d00896548b251ebea4d6e9e16a1c, 84c688218dc986760444609b79900676086bd587, e675dcbabf80deb600a53664d99182a51c09d7b6; LZ4 source-identity and strict compiler profile 9470f1f221f5997eb558061e25fa3c4ae7dcec3b; final pinned Linux attribute correction c2469a86107f632dc795f4957113234f5bac62f6. GitHub compare ahead=8 behind=0, ten modified/added paths. All testing-standards edits strictly APPEND-ONLY (+170 lines, -0). Sole branch main; zero open PRs. No branches to merge/delete.

**Agent3 real Kbuild:** src/kernel/dm-target.c now has optional compile-only kernel object verifier selected only by SWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE. It forces compilation of actual LZ4, production CRC32C, original 4096 SHA and import admission interfaces, but has ZERO production call sites and ALWAYS returns unsupported. Actual module Kbuild proved on x86_64 and ARM64 at exact Agent3 SHA #43992124313, including nm symbol presence; standard module build unchanged.

**Agent2 real Kbuild:** exact source-pinned Linux mm/zswap.c optional SWAPZ_ROUND024_ZSWAP_KBUILD_PROBE compiles genuine original fields: locked folio, entry/xarray identity, zpool pool_idx and codec-at-store-time LZ4, handle and 1..3568 length. Every return is negative. Original zswap_writeback_entry still decompresses to original 4096 ordinary backing WRITE. Kernel compile-only optional symbol verified present in GCC W=1 -Werror opt-in object and absent from default restored object; matched CONFIG_ZSWAP=y/n Linux and external module Kbuild completed SUCCESS. No authoritative original store-time SHA or reused-slot generation, no cloned BIO compressed carrier, no loaded admission.

**Historical REAL first failures:** initial hosted source C combined-fixture newline, source fixture inclusion and pool_idx initialization errors were repaired under GCC/Clang -Werror/ASan/UBSan without deleting peer source. Real pinned Linux Kbuild at earlier e675dcb... SHA, workflow #43993407400, failed at mm/zswap.c:996:28: expected ')' before '__attribute__' caused by kernel noinline macro expansion inside a raw attribute. Final c2469a86107f632dc795f4957113234f5bac62f6 fixes to kernel-safe __attribute__((__used__, __noinline__)) and executes an explicit host regression with Linux noinline defined. Earlier failed runs remain FAILED, not retroactively qualified.

## EXACT final engineering source GitHub Actions

At c2469a86107f632dc795f4957113234f5bac62f6, EIGHT actually triggered workflows COMPLETED SUCCESS:
- Pinned Linux CONFIG_ZSWAP=y/n, real opt-in zswap.o, default restoration, external matched module: https://github.com/k1moradi/swapz/actions/runs/43993865394
- Genuine modified pinned Linux BIO-origin UML KUnit (source only): https://github.com/k1moradi/swapz/actions/runs/43993865610
- Original source cross-ABI/DM admission C/Clang/GCC: https://github.com/k1moradi/swapz/actions/runs/43993865872
- Native code and source goals: https://github.com/k1moradi/swapz/actions/runs/43993865565
- Production C: https://github.com/k1moradi/swapz/actions/runs/43993865595
- Rootless physical adversarial SOURCE audit only: https://github.com/k1moradi/swapz/actions/runs/43993865556
- Private static: https://github.com/k1moradi/swapz/actions/runs/43993865335
- Systemd/package: https://github.com/k1moradi/swapz/actions/runs/43993865885

This proves source/kernel compilation and source UML KUnit, NOT a booted owner kernel, actual loaded matching dm-swapz, compressed stored-entry MM/BIO transaction, original 4096 kernel swap-in or physical media qualification.

## Owner-approved architecture and required safety

Original valid SWAPSPACE2 physical partition: first 4096 bytes (header/signature/UUID) and partition table unchanged; owner-approved post-swapoff exclusive data area only; physical 4/8/16KiB extents payload+deterministic zero padding only; bounded volatile RAM stores codec/CRC32C/logical generation/GC/offset/ownership. zswap manages small configurable compressed RAM cache and authentic kernel eviction; swapz manages backing disk, ordinary LZ4/delta64/SHUF8 compression or original RAW fallback, NO competing RAM-pressure reclaim controller. For future supported genuine retained LZ4 zswap eviction, transfer exact already compressed bytes via separate ZSWAP_COMPRESSED RAM-described record and safe RAW-path lower-I/O mechanics, NEVER current RAW encoding (RAW is UNCOMPRESSED ORIGINAL 4096). Swapz disk READ must decode correct codec and return original 4096 bytes, while zswap RAM hits decoded by zswap. Unknown codec/lifetime/provenance -> ordinary original-page fallback. Canonical compressed CRC32C is ~crc32c(~0U, bytes, length), independent of original 4096 SHA256.

Phase A BLOCKED; Phase B forced RAW bypass DISABLED; direct compressed transport DISABLED. Real old owner physical make test at de5bc09e had five owned RAM stages PASS, actual owner-protected physical anonymous_workload FAIL swap_attribution with original private numerical counters missing, recovery reported COMPLETE but not physical PASS; no new physical test.

**Owner test decision: NO make test and NO make fast_test needed now.** Quick optional unprivileged direct source tests:
- python3 -B tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py -v
- python3 -B tests/runtime/native/zswap-compressed-admission-test.py -v
- python3 -B tests/runtime/native/zswap-compressed-cross-abi-test.py -v
These do not establish loaded or physical success. Existing sudo owned-null_blk make fast_test benchmarks currently active normal path, not disabled compressed handoff.
