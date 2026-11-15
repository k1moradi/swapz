# Agent 2 — Round 002: implement exact-source Linux MM/BIO provenance producer

**Task ID:** `agent2-upstream-provenance-implementation`
**Round issue and mandatory report mailbox:** https://github.com/k1moradi/swapz/issues/119
**Frozen swapz input:** `f11e8795f44f15fecc6b2b200c0b1a9e4eaeb364`
**Frozen upstream Linux input:** `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`
**Report file to be archived by Agent 1:** `agent2-upstream-provenance-implementation-report.md`
**Task class:** IMPLEMENTATION, not repeated source audit. **No same-round dependency on Agent 3.**

## Objective and substantive output

Deliver a **complete, real, version-pinned, minimal unified diff** against that exact upstream Linux source implementing authenticated stored-zswap-entry writeback provenance from MM through the BIO and into the DM clone/split boundary. Start from the six-file candidate patch published in [issue #116, Agent 2 comment](https://github.com/k1moradi/swapz/issues/116#issuecomment-6890555852), then reconcile every hunk against the actual full kernel tree and correct defects found. Merely re-pasting the historical proposal with no exact-tree validation is NOT implementation completion.

Own only the independent upstream Linux patch, currently expected to touch `mm/zswap.c`, `mm/page_io.c`, `include/linux/swap_ops.h`, `include/linux/blk_types.h`, `include/linux/bio.h`, `block/bio.c`, plus the narrowest kernel-linked tests if needed. Do not edit swapz `src/kernel/dm-target.c`, `swapzctl`, or `main`.

## Frozen producer/consumer contract

1. Exactly two semantic states: `SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN = 0`, `SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK = 1`. The positive value means a **previously stored and authenticated matching zswap entry** was successfully decompressed and its full-page bytes submitted to backing swap. Initial rejection, ordinary swap-out, errors and unsupported paths remain zero.
2. Provide `BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN`, `bio_is_zswap_stored_writeback(const struct bio *)`, and the scalar `struct bio::bi_swap_origin`. The helper checks `REQ_OP_WRITE`, `REQ_SWAP`, exact value `1`; no inference from flags, PID or global counters.
3. Set the positive origin only after source-side zswap entry/race/reuse validation and successful decompression; never stamp a compressed zswap payload as if it were backing-store data.
4. Propagate immutable origin through `swap_io_ctx` and `swap_iocb`; prevent mixed-origin WRITE aggregation via `swap_can_merge()` or an equivalent exact-source boundary. Verify `bio_init`, `bio_reset`, `__bio_clone`, `bio_alloc_clone`, `bio_split`, block split, DM `alloc_io`/`alloc_tio` and relevant reissue semantics. A mixed/ambiguous child must never acquire a positive value.
5. Preserve all existing ownership, folio release, dirty-on-error and exactly-once completion contracts. Explicitly inspect `CONFIG_ZSWAP=y` and `CONFIG_ZSWAP=n` code paths, and document any structure-size/offset changes.

## Required execution and evidence

- Obtain/read an actual exact-commit upstream Linux checkout if the environment supports it, on its existing/default detached commit (no feature branch, PR, fork or secondary worktree). Record the `git rev-parse HEAD`, source tree cleanliness and patch SHA-256.
- Produce a full unified patch in the issue comment (numbered continuation comments permitted). A textual plan alone is a task FAIL/BLOCKED.
- Run and report `git apply --check <patch>`, `git apply <patch>`, `git diff --check` on the **real exact kernel checkout** if available. Distinguish actual full-tree checks from synthetic source-hunk replay.
- Run real kernel Kbuild `W=1` and `W=2` for `CONFIG_ZSWAP=y/n` variants if matching config/generated headers and toolchains are available; record exact compiler/config/architecture and failures. If not available, explicitly `NOT_RUN` with missing prerequisites, without claiming the producer qualified.
- Add a kernel-source-coupled regression/KUnit or similarly reproducible test patch covering positive stored-entry eviction, ordinary/rejected negatives, mixed-origin separation, clone/split/requeue/reset/reuse, and 4KiB DM admission. Test the actual changed code when possible; explain limits of models.
- Audit and describe the binary layout and **header-versus-running-kernel ABI mismatch**: compile-time capability is not runtime proof. No loaded module or production approval without a separately verified matching kernel.

## Explicit non-goals and vetoes

No Ubuntu 7.0 port in this task, no RAW bypass, no change in swapz representation decisions, no live swap, no kernel installation, no physical test. Do not let missing host artifacts turn the deliverable into an architecture-only report: include a real code patch and an exact reproducibility recipe regardless, and mark unavailable build/loaded evidence honestly.

## GitHub report contract

Post exactly one primary `REPORT_READY` **GitHub comment to issue #119**, with fields: `round: "002"`, `agent: 2`, `task_id`, `status: PASS | FAIL | BLOCKED`, upstream `kernel_source_sha`, swapz `source_sha`, `task_commit_sha`, full patch or continuation URLs, modified files, source-anchored tests/exits, evidence class, patch SHA-256, blocking findings and next-round integration prerequisites. PASS can mean patch+tests accepted **only for the task**, never Phase A or runtime ABI acceptance.

Agent 1 alone archives your GitHub response in `docs/handoff/zswapz/round002/agent2-upstream-provenance-implementation-report.md`. **Do not commit or push.**
