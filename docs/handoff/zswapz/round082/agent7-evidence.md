# Round082 Agent7 — original LZO1X host Git ancestry preflight

**Status: NEW SOURCE CI NOT YET OBSERVED; not qualified.** Task `9acefae6a1727123a218a7b728e44c7434f1eed2`, [official #200 ROUND_OPEN](https://github.com/k1moradi/swapz/issues/200#issuecomment-7118124463). Exclusive workflow-only lease; no Agent10/11 changes or dependency.

## Actual preceding source outcome

Exact Round081 source [7a22c0ec3ec2ca56ada6a35a6ad6a670a54aacb8](https://github.com/k1moradi/swapz/commit/7a22c0ec3ec2ca56ada6a35a6ad6a670a54aacb8), sole parent `932249ccb8e6a7654de7773d2008bf9c8b7ca3e9`; [run45293125425/job138106674475](https://github.com/k1moradi/swapz/actions/runs/45293125425/job/138106674475) **COMPLETED FAILURE**. Independently fetched actual job log: GCC C2x ASan+UBSan baseline PASS 774 directed checks and 18/18 independently compiled/executed semantic mutants; Clang C23 ASan+UBSan baseline PASS 560 directed checks and 18/18. First subsequent error: `fatal: ambiguous argument 'HEAD^': unknown revision or path not in the working tree.` Both checkouts were depth1; product lacked parent for post-test git diff, not evidence of actual whitespace defect. Old R080 unused-variable and R081 version/capacity mutant failed source verdicts preserved.

## Surgical workflow repair and preflight evidence

Product checkout depth2; original sibling remains pinned depth1. Before expensive verifier, check exact GITHUB_SHA, product tracked/untracked clean, raw commit header exactly one parent, parent object and HEAD^ traversal availability, resolved/raw parent agreement, and actual `git diff --check HEAD^ HEAD --`. Separate fail-only first errors for missing parent, mismatch, non-single-parent and whitespace. Preserve original pin/clean, dependency checks, unchanged compiler verifier and post-test product clean check. No production source edits.

Actual local rootless disposable Git regression of the same product-preflight Bash block, with local file:// clones, executed 9 assertions: historical depth1 git diff fatal reproduced; depth1 rejected as parent unavailable; depth2 success with empty stdout/stderr; wrong SHA rejected; dirty tracked rejected; dirty untracked rejected; wrong resolved parent via local graft/replace rejected; genuine added trailing whitespace rejected; two-parent commit rejected. All 9 PASS. No real repo clone or original Linux compiler run performed locally; sibling/pinned compilation stays in CI.

## Exact immutable inputs

New workflow blob `d4783b8251d1a0e29cdeb2625c7e46bd7e449d39` (old `a2d62c735ba063ed2be52a573dd675eea8ac07df`). Unchanged passing fixture `74136e58c6810f71ae44531cdecdb142df8601dc`; unchanged verifier `c2bd6a4d35bc8261e94743f92166b7c436d3c1f2`. Original Linux pin `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`; original Git blobs mm/zswap.c `ae19e301fced7e357a4c7587dfdd6abb890b9163`, crypto/lzo.c `d43242b24b4e831e7e0d26f38d2f263877d5748e`, include/linux/lzo.h `4d30e3624acd237290dbfeaefdb9c710e4f85f56`, lib/lzo/lzo1x_compress.c `01586af2347f5e2f8c8528b94e02622fc8b262c8`, lzo1x_compress_safe.c `371c9f849492814afed88a443acb2262dcf35dfe`, lzo1x_decompress_safe.c `318abb82c63d2c27c0d5497b7cf4e21d87d13154`, lzodefs.h `b60851fcf6ce54b57e87d04e917deaa2b6cf62cc`. Product import-codec.h `0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6`, decoder-owner.c `8e0c8f4d2085af7f2e17df412f3a1af654063571`, decoder-owner.h `e1b4b903567070e2307f7d05f8e48c14e0bb3768`. Existing verifier checks full original/product source blobs.

## New exact-source CI

One changed-source [host workflow](https://github.com/k1moradi/swapz/actions/workflows/phase-a-round080-original-lzo1x-independent-decoder-host-noauth.yml). Exact new commit/run/job to be registered after publication; no new positive execution or mutants verified yet. Required GCC and Clang baselines plus 18 compiled AND executed semantic mutants each, strict unchanged ASan+UBSan, full workflow success. Original native NOT_RUN Agent7 host-only.

## Frozen safety

SOURCE_MAPPED_AUTHENTICATED=0; PHASE_A=BLOCKED; direct/forced RAW/import OFF. Real selected original STORED/preerase auth, actual durable lower WRITE+FUA/flush and once-only upper ACK unproved. Original Linux MM/zswap exclusively owns compressed RAM/natural eviction; swapz disk packing/GC only, no competing reclaim or recompression. Original compressed LZO1X/raw LZ4 is separately typed, immutable with independent decoder/GC lease; 3569..4095 rejected without truncation at dormant cap3568. Ordinary RAW_4096 is complete ORIGINAL UNCOMPRESSED 4096. Protect first physical SWAPSPACE2 4096 and exact volatile 20-byte map. No production changes, native, physical, privileged, swapon, or pressure tests; no branches, PRs, force, periodic monitoring.
