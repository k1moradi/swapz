# Round072 Agent2 — original DM upper BIO ownership, exact-source requalification

Official issue: https://github.com/k1moradi/swapz/issues/189

## Exact source and ownership

- Task SHA `3c1919f1b2c2ea428045a1afb5c278151cf06ccc`, engineering baseline `4083449f12c3392d5ea534ee4e536865b4caf3ee`.
- **Changed-source commit:** [`27e50960fdc21b51c92ce8278d2c8aedf922dc8a`](https://github.com/k1moradi/swapz/commit/27e50960fdc21b51c92ce8278d2c8aedf922dc8a); **single parent:** `62f137b838a2434764926a24457f700d0bfb984c`.
- Original Linux pin `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`; pristine original `drivers/md/dm.c` Git blob `1881d86111fb2e655893ad898cf21b88f0e4e7f3`.
- Production `src/kernel/dm-target.c` **READ ONLY** Git blob `f1cab252cd990190646c82da81378d1563475826`; **zero production C changes**, no other agent's code modified.
- Changed: Round071 Agent2 evidence whitespace, original pinned DM owner KUnit fixture, stage verifier, original DM workflow; added independent `tests/tools/round072-original-dm-selected-owner-verify.py`, and appended the full prior+peer prefix of `docs/testing_standards.md`.

## Previous exact CI P0 and current fix

Previously, [run 45110728672](https://github.com/k1moradi/swapz/actions/runs/45110728672), source `07ccd88843a3fd988b15e9f5dea4c16fe4d3a365`, host job `137482233393` **FAIL** at `git diff --check HEAD^ HEAD` *before compilation*: trailing whitespace `docs/handoff/zswapz/round071/agent2-evidence.md:3–6`. Dependent original native job `137486343808` **SKIPPED**. Four trailing spaces were removed without changing substantive report content.

The changed original-source-linked KUnit fixture additionally refuses foreign original BIO, wrong selected `struct dm_target`/active `struct dm_table`, stale or zero `swapz_round065_incarnation`, requeued owner, and late teardown/terminal callback. This is an **original-kernel type-linked negative**, not an authenticated live production selected table. Existing two original KUnit cases retained; new suite requires **three actual cases** and strict JSON+KTAP with zero skips.

Source host CI executes old **12** and new **6** compiled/executed C semantic mutants **per compiler**, with GCC+Clang `-Werror`, ASan+UBSan; original staged SHA plus **eight** stage mutation refusal tests. Local preparatory copy of the new predicate compiled and executed under GCC/Clang sanitizers with baseline PASS and 6/6 mutants per compiler, but was **not a GitHub source-linked run** and is not counted as CI PASS.

## Exact current workflow and pending qualification

[Run 45127049313](https://github.com/k1moradi/swapz/actions/runs/45127049313) targets the changed-source SHA `27e50960fdc21b51c92ce8278d2c8aedf922dc8a`. At this checked-in preliminary snapshot, source-host job `137533678365` was **QUEUED**, dependent original Linux UML native job unallocated; **no exact-source CI/compiler/native JSON/KTAP PASS is claimed**. See accompanying machine-readable `agent2-results.json` for exact counts, states and first historical error. The terminal source-specific outcome must be recorded in an additional docs-only direct-main evidence update, not a chat file.

## Authentication boundary and safety

The native `struct dm_target`, `struct dm_table` and `struct bio` test objects and staged review-only product source are **not** a live selected production `dm-swapz` mapper, genuine original swapcache-backed STORED source, real durable WRITE+FUA, or exactly-once real production upper `bio_endio()`. Those remain **BLOCKED** regardless of modeled owner-state successes. `SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`, `DIRECT_COMPRESSED_HANDOFF=DISABLED`, `FORCED_RAW_BYPASS=DISABLED`, imported `ACTIVE=0`. Linux MM/zswap solely owns compressed RAM and natural eviction; swapz disk packing/GC only. Original compressed codec tags remain distinct volatile identities with no recompression; conventional `RAW_4096` remains complete original **UNCOMPRESSED 4096 bytes**. Protected SWAPSPACE2 header/UUID/signature/partition table and on-disk map unchanged. No branch, PR, loaded module, privileged, real physical swap or memory-pressure operation.

## Terminal exact-source CI result — recorded in Round074

The preceding Round072 queued snapshot is superseded by actual terminal [run 45127049313](https://github.com/k1moradi/swapz/actions/runs/45127049313), **overall FAILURE**, original source `27e50960fdc21b51c92ce8278d2c8aedf922dc8a` parent `62f137b838a2434764926a24457f700d0bfb984c`. Source-host job `137533678365` **SUCCESS**: strict GCC+Clang ASan/UBSan, 12+6 = **18** genuinely compiled-and-executed C semantic mutants per compiler and source policy. Original pinned Linux UML job `137536327380` **FAIL** after 8/8 staging negatives and byte-identical unbuilt product copy, **before any KUnit cases or JSON/KTAP were generated**. First diagnostic: `linux/drivers/md/dm.c:4544:16: error: function declaration isn’t a prototype [-Werror=strict-prototypes]`. Reconstructed staged line 4544 was test-only `struct dm_table current = { .swapz_round065_incarnation = 7 };`; original `include/asm-generic/current.h` defines `#define current get_current()`, so the variable name is the actual prototype collision. Corrective source is a **distinct** [Round074 commit `92a0a3273e1daea76e766f0d29dae05ce8b29e79`](https://github.com/k1moradi/swapz/commit/92a0a3273e1daea76e766f0d29dae05ce8b29e79) with a source-linked regression; new [run 45144645175](https://github.com/k1moradi/swapz/actions/runs/45144645175) is separate and initially queued. This original Round072 native outcome remains **FAIL (zero cases executed)**, never a PASS. SOURCE_AUTH=0; PHASE_A=BLOCKED; direct handoff, forced RAW bypass and imports OFF.
