# Agent 5 — Round 010: actual Linux BIO-origin lifecycle and mixed-origin hardening

**Task ID:** `agent5-real-bio-origin-lifecycle-regressions`
**Issue:** https://github.com/k1moradi/swapz/issues/127
**Frozen `swapz/main` source; exact sole commit parent:** `4f88c81dcba4ee09d32f067e7353664a821ba986`.
**Start:** unique `ROUND_OPEN` only; begin **simultaneously with Agent 8**, never await its new workflow or commits.

## Exclusive real source ownership

Modify only `tests/tools/stage-pinned-linux-zswap-origin.py`, `tests/runtime/native/pinned-linux-zswap-origin-stage-test.py`, and a uniquely headed append-only section `Round 010 BIO origin lifecycle and mixed-origin correctness` in `docs/testing_standards.md`. Do not edit Agent 8's `.github/workflows/phase-a-zswap-origin-prototype.yml`, paired-module test or `docs/coding_standards.md`; do not directly edit `src/kernel/dm-target.c`. The existing staging tool **is actual source-controlled implementation code** which applies exact, checked transformations to six real upstream Linux C/H files in a disposable verified pinned checkout; this is the production-prototype authoring surface.

## Implement and prove source semantics; not a model-only report

1. Examine the **actual pinned upstream Linux** `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` source for `bio_init`, `bio_reset`, `bio_reuse`, `bio_prepare_reissue`, `bio_clone_fast`/`__bio_clone_fast`, `bio_split`, `swap_can_merge`, `swap_add_folio`, `swap_write_submit` and zswap stored-entry `zswap_writeback_entry`. Keep a precise source-bound ownership argument. Do not invent a kernel function or rely on generic `REQ_SWAP` as origin authority.
2. Strengthen the real `EDITS` transitions as justified by that source review so an **ordinary/unknown** or reset/reused BIO cannot retain a stale positive tag; a cloned/split child representing only authenticated base pages must preserve its origin, and ordinary/mixed pages must never inherit positive provenance. Validate initialized `swap_io_ctx` and `swap_iocb` lifetimes and prevent origin-mixed aggregation without allocating hot-path extra buffers or introducing locks. Do not introduce origin-based RAW bypass, change compression/CRC/4KiB layout or alter asynchronous completion ownership.
3. Add executable deterministic rootless cases in the existing real staging regression file that run the **production staging program**, fail closed on corrupted/duplicate/missing kernel anchors or wrong Git blob SHA, assert the modified exact Linux postimage, reject incorrect merge/clone/reset/reissue changes and verify accurate origin distinction. Add source-coupled C compile or test if feasible without loading the kernel. **Test a deliberately wrong mutation**, not merely counting keywords. Keep tests bounded and use standard library.
4. Keep all upstream source edit anchors unique and version-pinned with explicit pre/postimage SHA-256 in the retained staging manifest. Preflight must finish for **all files before mutation**; failed preflight must leave entire source untouched, and failed publication must be transparently rolled back or correctly marked partial. Preserve original comments and existing full-source Kbuild access.
5. Run `python3 -B tests/runtime/native/pinned-linux-zswap-origin-stage-test.py -v`, `python3 -m py_compile`, source/whitespace checks and GCC/Clang source-coupled tests where possible, recording actual results/exits and mutation case counts. The existing previous-round modified pinned Linux y/n hosted [build #43790479509](https://github.com/k1moradi/swapz/actions/runs/43790479509) passed, but **your new postimage is NOT compiled in hosted CI until Agent 1 integrates and that CI reruns**. Do not claim that the previous PASS qualifies changed kernel source. A KUnit test that cannot actually execute stays NOT_RUN.

## Required source commit and handoff

Modify actual tracked staging/test/standard sources; create **one real retrievable Git commit parented exactly to `4f88c81dcba4ee09d32f067e7353664a821ba986`**, no remote `main` update, no PR/branch/fork/worktree. Post a new post-ROUND_OPEN `message: REPORT_READY` to #127 with `round: "010"`, `agent: 5`, task ID, parent and source commit, exact changed paths, tests/mutations, compile and runtime NOT_RUN limits, and any first failure. Coordinate only through issue reports; start independently of Agent 8.

**No actual swap/mapper/reclaim, kernel installation or physical I/O. Phase A BLOCKED; Phase B RAW bypass DISABLED.**
