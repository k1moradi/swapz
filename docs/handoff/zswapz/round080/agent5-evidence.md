# Round080 Agent5 — original zswap source-linked preflight repair and qualified host semantic mutants

Official [Round080 issue #198](https://github.com/k1moradi/swapz/issues/198), [Agent5 complete assignment](agent5-preflight-first-error-fix-host-p0.md), [frozen contract](frozen-contract.md). **Scope: pinned pristine Linux original source-linked HOST MODEL ONLY. No original UML KUnit or real selected STORED authentication.**

**Exact tested source commit:** [`ac92b835bf4a60ae7f8bebf8deacc8ab0644491f`](https://github.com/k1moradi/swapz/commit/ac92b835bf4a60ae7f8bebf8deacc8ab0644491f); **single parent:** `d76081b661ce750d2fbeaa247fa16e4670db5e97` (original Round080 task commit). Direct sole-`main` fast-forward used fresh expected-head CAS, `force=false`, with the remote head verified. Source changes were solely test-only existing Round079 workflow, its modeled C fixture negative, and literal-prefix-preserving `docs/testing_standards.md` appendix. The original verifier, original Linux sources and ALL product production code were unchanged.

## Real historical first failure and reproduced cause, not a guess

Prior Round079 source `b1437365849fa574c0e34f9b7729efdb530a6a51`, [run #45237411852](https://github.com/k1moradi/swapz/actions/runs/45237411852), host job [137912686741](https://github.com/k1moradi/swapz/actions/runs/45237411852/job/137912686741) **COMPLETED FAILURE**. The first *observed* failed step was **Assert exact main Git SHA pristine pinned original and compiler toolchain**, process exit 1. **GitHub did NOT record the individual shell assertion**, and original GCC/Clang models and mutants executed **zero**. Preserve that red result permanently.

The old workflow checked out an independent pristine pinned Linux repository at nested `original-linux/` **before** demanding `test -z "$(git status --porcelain --untracked-files=all)"` in the outer swapz repository. In a separate disposable rootless Git reproducer with a clean outer repository, adding a nested Git checkout produced exactly `?? original-linux/`; the old `test -z` necessarily fails. New exact-source CI subsequently independently passed (1) a completely clean original outer checkout **before** nested checkout and (2) a separately clean pinned nested checkout while the sole expected outer porcelain entry was `?? original-linux/`. Thus this is a **reproduced explanation for the old unprinted assertion**, not an invented old log diagnostic. The new workflow emits bounded labeled `ROUND080_AGENT5_PREFLIGHT_FIRST_ERROR` for any future preflight failure, with safe bounded relative dirty paths only on failures.

### Surgical changes

- `.github/workflows/phase-a-round079-original-zswap-preerase-source-copy-noauth.yml`: root ref/branch/SHA/full tracked+untracked cleanliness, exact first-parent `git diff --check`, GCC/Clang toolchain **before** nested `actions/checkout`; separately check pinned `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` SHA and clean nested sparse source, and require exactly that one nested untracked directory afterward. **No `git status -uno`, no broad ignore, no weakened root policy.** Narrow CI triggers to the source fixture, focused verifier and workflow; peer standards-only changes do not launch redundant host source CI. Canonical `repository-policy-test.py --enforce` preserved and passed.
- `tests/runtime/native/fixtures/round079-original-zswap-preerase-source-copy.c`: the 3569 and 4095-length negative cases now supply a 4096-byte test-only destination capacity, so bypassing the **3568-byte original import size restriction** cannot be masked by the independent short-destination restriction. Original compressed 3569..4095 still fail closed; no product bound raised, no RAW aliasing.
- `docs/testing_standards.md`: append-only new first-error and independent semantic mutant contract; earlier/peer material retained byte-for-byte.

## Actual terminal exact-source CI

[Workflow run **45251506069**](https://github.com/k1moradi/swapz/actions/runs/45251506069) tests the exact committed SHA `ac92b835bf4a60ae7f8bebf8deacc8ab0644491f`; [host job **137962067745**](https://github.com/k1moradi/swapz/actions/runs/45251506069/job/137962067745) **COMPLETED SUCCESS**. Both labeled outer-clean-before-nested and nested-original-pristine/only-expected-root-entry preflight steps **PASS**. Exact pinned upstream original Git blobs `mm/zswap.c=ae19e301fced7e357a4c7587dfdd6abb890b9163` and `mm/zsmalloc.c=7ef80e0da6267661cea4d48a4a615444724782e7` pass, as does the product unchanged `codec.h=e89d316b9cf49f82df0b77648c1be1731607987d` and the source-derived original branch order.

| Actual strict compiler | Baseline host-model cases | Individually compiled **and executed** C semantic mutants | Sanitizers | Result |
| --- | ---: | ---: | --- | --- |
| GCC C2x `-Werror` | **4/4** | **20/20 killed by C runtime assertion** | ASan + UBSan | **PASS** |
| Clang C2x `-Werror` | **4/4** | **20/20 killed by C runtime assertion** | ASan + UBSan | **PASS** |
| **Total** | **8/8** | **40/40** | Both | **PASS** |

Actual job stdout includes `PASS ROUND079_AGENT5_EXACT_ORIGINAL_ZSWAP_ZSMALLOC_SOURCE pristine_git_blobs=2 real_product_bound=3568 host_model_cases=8 GCC_Clang_semantic_mutants=40 true_live_MM_STORED=UNPROVEN original_native_KUnit=NOT_RUN SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED`. It also independently asserts all 40 mutations were **compiled, executed, and killed by a deterministic C runtime assertion**—a failed compile or sanitizer crash never counts. [Bounded result artifact 14855993552](https://github.com/k1moradi/swapz/actions/runs/45251506069/artifacts/14855993552) contains the machine-run host JSON (no private hardware data). **First error in this exact-source workflow: NONE.** Canonical source policy job step PASS.

## Live proof still absent and activation safety

This is a **host model compiling four source-extracted predicate expressions**, not execution of the actual original Linux MM/zswap writeback path. The true locked selected STORED folio/XArray generation, zsmalloc handle and pool lease under concurrent invalidate, selected upper DM target, original decoder lifetime at GC, physical lower durable WRITE+FUA/flush and exactly once real upper `bio_endio` remain **UNPROVEN**. Original native Linux UML KUnit for this Agent5 task: **NOT REQUESTED**, JSON/KTAP **UNAVAILABLE**, cases **0**; Agent10 independently owns native Linux qualification. Existing original pinned test-only Round075 4/4 remains a separate historical source/fixture proof, not live STORED auth.

Linux MM/zswap alone owns compressed RAM and natural eviction; swapz only disk packing and GC, never competing reclaim or recompressing original compressed LZO1X/raw LZ4. Volatile original codec identity/independent retained decoder are required; conventional `RAW_4096` is the complete ORIGINAL UNCOMPRESSED 4096-byte page. Source original compressed 3569..4095 is unsupported by dormant import3568 and fails closed. SWAPSPACE2 first physical 4096 bytes/UUID/partition remain protected, mapping exactly 20 bytes volatile; no privileged/loaded/swapon/real pressure/physical device testing or production C modifications.

**SOURCE_MAPPED_AUTHENTICATED=0 · PHASE_A=BLOCKED · DIRECT_COMPRESSED_HANDOFF=DISABLED · FORCED_RAW_BYPASS=DISABLED · import ACTIVE0.**

The companion [agent5-results.json](agent5-results.json) records the immutable source, historical failed run, terminal green host counts, original source pin and safety limits.
