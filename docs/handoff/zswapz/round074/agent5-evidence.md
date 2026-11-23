# Round074 Agent5 — immutable original compressed-source ownership lifetime host-only evidence

[Official Round074 issue #191](https://github.com/k1moradi/swapz/issues/191), [frozen contract](frozen-contract.md) and [exact Agent5 assignment](agent5-source-copy-ownership-host.md). Authenticated original source and real lower durability remain BLOCKED.

**Source/test commit:** [`b87e4350127164ce49c85d055fd20113c38df3bf`](https://github.com/k1moradi/swapz/commit/b87e4350127164ce49c85d055fd20113c38df3bf); **single parent:** `d6cbad9f0fc35c4c6b5dce5a961e708df6b1614b`; one-parent direct `main` non-force expected-head fast-forward verified against remote. **Original Linux pin:** `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`; Round074 does not build/boot original Linux. Product C/H unchanged.

## Exclusive owned code and testing boundary

- `tests/runtime/native/fixtures/round074-original-owned-copy-lifetime.c` — new source-linked host C fixture, using unmodified original Round067 lower memory, producer and pinned-read harness and compiling actual `src/kernel/authority.c+codec.c` in a separate translation unit.
- `tests/tools/round074-original-owned-copy-lifetime-verify.py` — exact Git-blob product source checks; strict GCC/Clang -Werror ASan+UBSan actual source, six baseline cases/compiler, 11 new source-owner semantic mutations plus 3 actual product C mutations/compiler. A mutation counts only when compiled and executed with a deterministic non-sanitizer semantic failure.
- `.github/workflows/phase-a-round074-original-owned-copy-lifetime-host-noauth.yml` — dedicated focused host-only original codec source workflow, with exact commit, `git diff --check HEAD^ HEAD` and canonical repository policy.
- `docs/testing_standards.md` — meaningful literal-prefix-preserving append. No production C or old agent fixture edited.

Cases exercise original LZ4 and LZO1X exact compression/CRC and complete decoded original 4096; private owner retains byte-identical compressed copy before modeled source erase and scratch poison, modeled BIO buffer independently survives to real product guarded CRC/zero-pad receipt. Negatives reject borrowed pointer without modeled lease, one-byte-short copy, source generation and codec switch, tampered owned payload, 13-byte/EIO and duplicate callbacks. Under actual authority old reader pin, GC relocates EXACT original compressed bytes and preserves stable original source identity/CRC/codec with incremented GC epoch, retiring old physical only on last pin put. No recompress and ordinary RAW_4096 remains full ORIGINAL UNCOMPRESSED 4096. The lease, modeled BIO and lower FUA receipt are **HOST MODELS**, not real `mm/zswap.c` eviction source, genuine original `bio_endio`, actual selected upper ACK, or durable media.

## Actual CI (initial source commit audit)

- [Focused exact-source workflow run #45144990938](https://github.com/k1moradi/swapz/actions/runs/45144990938) — **QUEUED** at initial audit, tested exact code `b87e4350127164ce49c85d055fd20113c38df3bf`.
- Host job **137591957810** — **QUEUED**; actual new GCC/Clang baselines and semantic mutant results **NOT EXECUTED AT THIS AUDIT**. The expected 6 cases/compiler, 14 mutants/compiler are *targets*, not PASS claims.
- Round074 original native UML — **NOT REQUESTED/NOT EXECUTED**, JSON and KTAP unavailable by design. First actual source/compiler/runtime error: **NONE AVAILABLE (queued)**. No additional native kernel build launched.
- Round072 previous exact source-host job **137535284018 SUCCESS** (actual log), dependent genuine original native **137557900023 QUEUED**. Previous-round evidence and machine-readable JSON are updated separately under Round072. The inherited green host proof is not a Round074 PASS.

## Frozen safety and remaining work

`SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`, `DIRECT_COMPRESSED_HANDOFF=DISABLED`, `FORCED_RAW_BYPASS=DISABLED`, imported ACTIVE0. Linux MM/zswap alone owns compressed-RAM residency/natural eviction; swapz exclusively owns disk compression/packing/GC without a secondary shrinker/recompression. Original compressed LZO1X/raw LZ4 uses a distinct VOLATILE codec tag, not swapz disk codec or ordinary full uncompressed `RAW_4096`. First physical SWAPSPACE2 4096-byte header/UUID/partition and 20-byte mapping unchanged. No privileged, loaded, physical, swapon, real-pressure or true media-FUA tests.

Companion [agent5-results.json](agent5-results.json) contains machine-readable exact source status; a terminal source CI result requires a separate docs-only update with real first error or actual PASS before REPORT_READY.


## Agent1 independently verified terminal exact-source CI (COMPLETED_SUCCESS_SOURCE_HOST_ONLY)

This manager terminal audit **supersedes earlier QUEUED status only for this immutable tested SHA**, preserving original source commit `b87e4350127164ce49c85d055fd20113c38df3bf` and previous reports. [Existing Actions run 45144990938](https://github.com/k1moradi/swapz/actions/runs/45144990938), [actual job 137591957810](https://github.com/k1moradi/swapz/actions/runs/45144990938/job/137591957810) is **COMPLETED SUCCESS**. Actual source-linked GCC+Clang strict ASan/UBSan, 6 baseline cases/compiler, 14 independently compiled/executed semantic mutants/compiler (3 actual-product C mutants/compiler); 12 baselines, 28 mutants total. No real original native, physical FUA or upper ACK.

**Scope:** host-source-linked model/fixture only, not authenticated original Linux swapcache STORED, original UML KUnit, physical durable FUA or production once-only upper bio_endio. Source AUTH0; Phase A BLOCKED; direct handoff, forced RAW and import OFF; ordinary RAW_4096 complete ORIGINAL UNCOMPRESSED 4096. No new periodic CI checks. No rerun of already successful unchanged source needed.
