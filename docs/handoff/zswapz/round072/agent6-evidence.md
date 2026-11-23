# Round072 Agent6 — cooperative natural-pressure source CI and repository-policy repair

**Status: IN_PROGRESS / exact-source GitHub CI not yet terminal.** Task commit `3c1919f1b2c2ea428045a1afb5c278151cf06ccc`; source publication parent **3c1919f1b2c2ea428045a1afb5c278151cf06ccc**. This report and paired JSON are committed with the source in the same first-parent commit; the immutable tested commit SHA, actual workflow/job IDs, real first error, and terminal verdict will be filled after CI with a separate non-force main evidence-only commit.

## Exact P0 and bounded changes

The Round071 original source-linked workflow [run 45111120206](https://github.com/k1moradi/swapz/actions/runs/45111120206) reached GCC and Clang strict ASan+UBSan PASS, 48/48 compiled/executed source-C mutants rejected, then failed repository-policy enforcement with `SOURCE_CONTRACT_MISMATCH: push base SHA unavailable or invalid`. The source workflow omitted the real push before SHA. This new change supplies only job-scoped `SWAPZ_PUSH_BEFORE_SHA: ${{ github.event.before }}`, retains `--enforce`, runs the existing first-parent push/dispatch synthetic repository-policy tests and independently asserts the workflow binding in the source-host checker. No production C/header/codec or old C fixture is modified.

**Owned source files:** `.github/workflows/phase-a-round071-natural-pressure-cooperation-noauth.yml`, `tests/tools/round071-natural-pressure-cooperation-verify.py`; `docs/testing_standards.md` appended with a substantive applicable rule and its entire previous prefix retained. This `agent6-evidence.md` and `agent6-results.json` are the mandatory same-round GitHub-first artifacts.

The existing source-linked 24 GCC + 24 Clang compiled and executed semantic mutants, C23 `-Werror`, ASan+UBSan, bounded 8-slot owned-copy, 28,544 maximum compressed bytes, 4/8/16KiB FIFO, original LZO1X/raw LZ4 identity, source buffer lifetime/codec retirement, GC reader pins and lower EIO/FUA modeled first-error remain required without relaxing any negative. No duplicate Round071 run is requested.

## Honest execution limits and next decision

Targeted exact-source CI: **PENDING**; job IDs, source-specific first diagnostic and JSON/KTAP summaries **NOT_YET_AVAILABLE**, not PASS. The policy selftests run without privileged/loaded kernel/device/pressure. Host-model KTAP is not genuine original Linux KUnit. Actual source authentication, original selected STORED/DM ownership, lower durability and upper BIO ACK remain unqualified. Existing `RAW_4096` is the entire original **UNCOMPRESSED** 4096 bytes, never original compressed bytes. No competing zswap reclaim/pressure, no recompression, no on-disk map/SWAPSPACE2 header/UUID/partition table change.

Safety frozen: `SOURCE_MAPPED_AUTHENTICATED=0`; `PHASE_A=BLOCKED`; `DIRECT_COMPRESSED_HANDOFF=DISABLED`; `FORCED_RAW_BYPASS=DISABLED`; imported codecs `ACTIVE=0`. Linux MM/zswap alone selects natural RAM eviction; swapz owns disk packing/GC.
