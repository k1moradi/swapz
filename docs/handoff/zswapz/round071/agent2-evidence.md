# Round071 Agent2 — original DM upper BIO source / once-only evidence

Issue: https://github.com/k1moradi/swapz/issues/188  
Task publication: `057346ca1fbbed73c7c664c56a3272c9b1a5fbb6`  
Engineering baseline: `73446b1a5f88ec8d3ba1e45e623825fd5fed2880`  
Pinned original Linux: `c339f4010dea8b0d754f84ace70cd1b089878ef8`  
Read-only production DM target Git blob: `f1cab252cd990190646c82da81378d1563475826`

## Exact current code boundary

`src/kernel/dm-target.c` is unchanged. The actual production `swapz_map()` accepts or requeues the current DM target BIO; `swapz_complete()` releases prepared and CI-only descriptor owner state **before** `bio_endio()`, and the ordered completion worker serializes delivery. `swapz_end_io()` sees the clone-to-original DM boundary. `swapz_dtr()` calls `swapz_drain()` before freeing the target. These exact functions do not provide an authenticated original zswap source, a proved current selected production DM target, a durable lower FUA witness, or a native original upper ACK witness.

The new test-only `round071-original-dm-upper-owner.cfrag` exercises candidate same-pointer original BIO, selected target, selected table and monotonically selected nonzero incarnation; an immutable `SWAPZ_ROUND071_SOURCE_AUTH_ACTIVE=0` rejects handoff. A modeled once-only terminal request is not real `bio_endio()` and does not establish its provenance. Inherited Round067 original-kernel KUnit separately exercises genuine original DM suspend/requeue/rebind, clone_endio and upper completion with a **test-only target**, not an authenticated production source.

## Targeted execution

- Locally executed `python3 -B tests/tools/round071-original-dm-upper-owner-verify.py`: **PASS** GCC GNU11 strict `-Werror` ASan/UBSan, 12/12 genuinely compiled/executed semantic C mutants, baseline PASS; Clang identical **PASS**, 12/12. 22 normal-case assertions per run, no exceptions/sanitizer failures.
- Stage runner Python syntax: **PASS**. Stage planner demands original Linux pin, exact original `drivers/md/dm.c` blob, inherited Round067 staged SHA, complete fixture markers, immutable AUTH0 and byte-identical production source Git blob. Its verify-only mode defines seven rejected mutations and no output writes; these stage mutations require the pinned original clone and remain **NOT_RUN locally**.
- Original Linux UML KUnit two new cases and exact JSON/KTAP 2 PASS / 0 FAIL / 0 SKIP requirement: **NOT_RUN locally**; dedicated rootless CI on main is provided and must be evaluated from its exact-source job. No native PASS is claimed until it actually runs.

## Honest first remaining blocker and gates

A real *selected* production `dm-swapz` `dm_target` / parent BIO with authenticated original STORED zswap source cannot be created by these rootless, no-device tests. The staged byte-identical production file is **review-only, not compiled or loaded**. Its identity is not inferred from a fake target or modeled callbacks. Thus genuine selected-source auth, durable physical lower WRITE+FUA, and real production upper BIO exactly-once ACK remain **BLOCKED**, even if native test-only KUnit passes.

`SOURCE_MAPPED_AUTHENTICATED=0`; `PHASE_A=BLOCKED`; `DIRECT_COMPRESSED_HANDOFF=DISABLED`; `FORCED_RAW_BYPASS=DISABLED`; imported `ACTIVE=0`. Conventional `RAW_4096` remains a whole original uncompressed page. No production C, on-disk 20B map, partition/header/UUID, kernel module, privileged operation, loaded-kernel, physical I/O, swap device or memory pressure is changed or used.
