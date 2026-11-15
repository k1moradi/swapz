# Agent 3 — Round 002: implement passive swapz Device Mapper provenance consumer

**Task ID:** `agent3-passive-dm-consumer-implementation`
**Round issue and mandatory report mailbox:** https://github.com/k1moradi/swapz/issues/119
**Frozen swapz baseline:** `f11e8795f44f15fecc6b2b200c0b1a9e4eaeb364`
**Frozen production blob:** `src/kernel/dm-target.c` = `746a6349823d8e8f52dfc68f025d29db9942ff2e`
**Frozen candidate ABI:** see `round002/README.md`; Agent 2's separate Round 002 code is **not an input or prerequisite**.
**Report file to be archived by Agent 1:** `agent3-passive-dm-consumer-implementation-report.md`
**Task class:** IMPLEMENTATION, not another scaffold discussion. Agent 3 is sole production **author** of `src/kernel/dm-target.c`.

## Objective and required real code patch

Produce a minimal, directly applicable **unified git diff modifying actual `src/kernel/dm-target.c`**, based on frozen full-source bytes. Start from your prior [review-only proposed patch](https://github.com/k1moradi/swapz/issues/116#issuecomment-6890775754) but implement observable Phase A behavior and source-coupled regression tests. **Do not write to GitHub `main`**; submit the complete diff to issue #119 for Agent 1's serialized integration review. No branch/PR/worktree/fork.

### A. Safe per-4KiB admission snapshot (mandatory)

- Add an explicit two-state `swapz_write_origin` and one descriptor-local field on `struct swapz_bio_ref`, independent of `preparation_force_raw`, `RAW_SELECTED` and all scheduling flags.
- Reset every admitted descriptor, including reused/requeued descriptors, to `SWAPZ_WRITE_ORIGIN_ORDINARY_OR_UNKNOWN`. Under `#ifdef BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN`, for only an **exact 4096-byte logical `REQ_OP_WRITE`**, set positive origin if `bio_is_zswap_stored_writeback(bio)` returns true. The custom Linux helper already checks `REQ_SWAP` and the exact positive enum. On stock/unpatched headers this must compile out completely and remain UNKNOWN; do not reference unprovided fields/symbols.
- Copy the scalar before entry publication to a preparation FIFO; do not retain a Linux zswap entry/folio/origin pointer. Make the scalar immutable for the logical write and invalid after upper completion. Do not use origin as an input to compression, RAW selection, speculative preparation, lower IO or authority publication.

### B. Implement useful passive observability (mandatory)

- Implement the smallest **read-only, per-target INFO observability** that proves a positive tag was seen and a verified-tagged logical page successfully committed. Proposed Phase A field names: `verified_zswap_origin_admitted` (admission diagnostics), `foreground_committed_verified_zswap_writeback` (successful authoritative foreground commit, across compressed/RAW/zero-elided), and `origin_carrier_compiled` (indicates only compiled header capability, **not runtime ABI proof**). Choose existing INFO status formatting conventions; append fields without breaking legacy token parsing or changing the existing JSON v1 contract.
- Increment the admitted count only on accepted, authenticated 4KiB writes; account for concurrent `swapz_map()` producers with kernel-safe atomicity and no new hot-path allocations/locks/clocks. Do not count merely attempted, rejected, READ, DISCARD or malformed operations.
- For `foreground_committed_verified_zswap_writeback`, increment **exactly once and only with the existing successful foreground 4KiB mapping/zero publication**, including all existing synchronous batch, detached async, standalone RAW and zero-elision paths. Current frozen source anchors are around `dm-target.c:2615`, `:5452`, `:5581`, `:6322`; recheck actual code/ownership and do not add increments speculatively. Exclude failed/aborted/late preparations, GC copies and lower requests. A deferred ACK is not a second commit.
- Keep carrier unavailable distinct from measured zero: status capability indicates when a zero count cannot establish absent zswap writeback. Never call generic `REQ_SWAP`, initial rejection or global `zswpwb` an authenticated positive. Phase B's four RAW reason counters are **not** part of this task.
- If commit attribution in any existing success path cannot be proven without lifetime/completion risk, deliver the safe minimal admission-only patch and document the exact code blocker instead of guessing; mark the full observability requirement BLOCKED. Do not introduce new completion owners.

### C. Regression/build obligations

- Supply the **full proposed git diff**, not only snippets. Check it against the actual frozen source: `git apply --check`, apply in the permitted single-`main` local checkout if available (do not commit/push), `git diff --check`. If only source-excerpt replay is available, label it precisely rather than claiming full-tree verification.
- Stock-header Kbuild must compile unchanged, with default-UNKNOWN behavior; a capability-enabled compile must use the exact candidate custom header, not a fabricated stock-kernel feature. Run actual `W=1/W=2` builds when matching headers exist; otherwise mark `NOT_RUN` and provide repeatable steps.
- Provide source-coupled tests for exact 4KiB acceptance, READ/DISCARD/non-swap/malformed origin, unsupported kernel, descriptor reuse, concurrency-safe admission counting, all successful representation commit paths, failed writes/deferred ACK/GC, and invariants `0 <= foreground_committed_verified_zswap_writeback <= compressed + raw + zero_elided`. Test identical LZ4/delta64 attempt and RAW/zero decisions for matched tagged versus untagged payloads.
- Inspect ownership and memory ordering around `swapz_map()`, inflight completion, queue publication and status reads. Leave every existing comment, CRC/generation/ordering/FUA/PREFLUSH/GC behavior, disk format and upper completion protocol intact.

## Absolute safety boundary

A header feature guard is **not proof of a patched running-kernel `struct bio` layout**. The diff remains a review-only candidate until a separately source-qualified patched kernel and module are built and loaded together. Do NOT load patched-header modules on an unverified host. No real swap, module insertion, kernel install, mapper or physical operation. No deliberate RAW bypass.

## GitHub report contract

Post exactly one primary `REPORT_READY` **GitHub comment to issue #119** with `round: "002"`, `agent: 3`, `task_id`, `source_sha`, `task_commit_sha`, production source blob, full diff or numbered continuation links, source/build/test commands and exits, patch SHA-256, code safety review, `PASS | FAIL | BLOCKED` and explicit unexecuted test gates. No same-round dependency on Agent 2; consume the **frozen candidate API only**.

Agent 1 alone archives your full comment in `docs/handoff/zswapz/round002/agent3-passive-dm-consumer-implementation-report.md`. **Do not commit or push.**
