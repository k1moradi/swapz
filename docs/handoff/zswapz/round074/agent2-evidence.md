# Round074 Agent2 — original Linux DM native strict-prototypes correction

Official issue [#191](https://github.com/k1moradi/swapz/issues/191), [ROUND_OPEN](https://github.com/k1moradi/swapz/issues/191#issuecomment-7095827205), task `d62552f7048d5a512c7a0a79b86558fa228b31f2`.

## Exact source, parent and exclusive files

- **Changed-source commit:** [`92a0a3273e1daea76e766f0d29dae05ce8b29e79`](https://github.com/k1moradi/swapz/commit/92a0a3273e1daea76e766f0d29dae05ce8b29e79); **single parent `f74d896ae9093ed94b62d311c34dd9aafef656ba`**, directly on main via nonforce fresh expected-head FF, remote verified.
- Original Linux frozen pin `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`; original pristine `drivers/md/dm.c` blob `1881d86111fb2e655893ad898cf21b88f0e4e7f3`; production read-only `src/kernel/dm-target.c` blob `f1cab252cd990190646c82da81378d1563475826`. **No production C changes**.
- Modified exclusive Round071 DM KUnit fixture, stage/negative verifier, and original DM workflow. Added `tests/tools/round074-original-dm-native-prototype-verify.py`; appended literal full peer-preserved `docs/testing_standards.md` prefix only.

## First exact true native failure and corrective reason

Old [Round072 source run 45127049313](https://github.com/k1moradi/swapz/actions/runs/45127049313) at source `27e50960fdc21b51c92ce8278d2c8aedf922dc8a`: source-host `137533678365` **SUCCESS**, GCC/Clang ASan+UBSan 18 compiled/executed source C semantic mutants **per compiler**, policy PASS; original Linux UML `137536327380` **FAIL BEFORE KUNIT**, despite successful stage and **eight** refused stage negatives. First diagnostic `linux/drivers/md/dm.c:4544:16: error: function declaration isn’t a prototype [-Werror=strict-prototypes]`. Zero native cases executed, zero native JSON or KTAP.

Independently reconstructed exact staged 4544 as `struct dm_table current = { .swapz_round065_incarnation = 7 };` in **test-only** third KUnit case. Frozen original `include/asm-generic/current.h` defines `#define current get_current()`; macro expansion corrupts the variable declaration, causing the misleading strict-prototype error. Fixed **only 19 test-local identifier uses** `current` → `active_table`. No kernel warning disabled, production function altered, case renamed, selected target/table/parent BIO incarnation guard weakened, requeue/teardown/terminal claim changed, or source auth activated.

## Changed-source tests

- Independently **executed locally** a narrow GCC+Clang GNU11 `-Wall -Wextra -Wstrict-prototypes -Werror` macro reproducer: `current` declaration rejected as expected by **both compilers**, descriptive `active_table` compiled/executed successfully by both. **This is a narrow standalone host check only**, not original KUnit, not the new source-extracted test.
- New exact test-only source extractor builds and executes **all three actual native C KUnit case bodies** under a minimal host kernel-type adapter with `#define current get_current()`, GCC+Clang strict high warnings and ASan+UBSan. A negative reintroduced `current` must be compile-rejected. Existing 12+6 source semantic mutants **per compiler** remain mandatory; staging now demands **nine** negative mutation refusals.
- Exact new [workflow 45144645175](https://github.com/k1moradi/swapz/actions/runs/45144645175), source `92a0a3273e1daea76e766f0d29dae05ce8b29e79`, was **QUEUED** at evidence preparation; source-host job `137590793528` initially queued, dependent original UML job not allocated. **No new exact CI PASS or original KUnit PASS is claimed.** Native JSON+KTAP requirement is genuine **3 PASS / 0 FAIL / 0 SKIP**. On failure report the first source-linked compiler/runtime error.

## Round072 terminal evidence obligation

Both `docs/handoff/zswapz/round072/agent2-evidence.md` and `agent2-results.json` are updated in this direct-main evidence commit with **old source host SUCCESS/native FAIL before execution**, exact test counts, run/job IDs and root cause. The original #189 report must use these verified commit-pinned files. No previous red source rerun or periodic check.

## Source versus real production boundary and gates

A test-only `struct dm_target`, fake `struct dm_table`, modeled owner state or source-linked host C adapter cannot prove live production selected mapper, original zswap STORED source, genuine durable lower WRITE+FUA or exactly-once real production upper `bio_endio()`. All remain **BLOCKED**. `SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`, `DIRECT_COMPRESSED_HANDOFF=DISABLED`, `FORCED_RAW_BYPASS=DISABLED`, imported `ACTIVE=0`. Linux MM/zswap alone owns compressed RAM and natural eviction; swapz disk packing and GC only, no duplicate shrinker or recompression. Original LZO1X/raw LZ4 codec tag is volatile and distinct; ordinary `RAW_4096` is always original complete **UNCOMPRESSED 4096 bytes**. Preserve protected SWAPSPACE2 first 4096 bytes/UUID/partition table and 20-byte volatile map. No branches, PRs, force, loaded kernel, privileged, physical, real swap or memory-pressure tests.
