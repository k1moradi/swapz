# Agent 2 — Round 003 DRAFT: edit and commit the real Linux producer

**State: DRAFT / DO NOT EXECUTE before Round 003 `ROUND_OPEN` in [issue #120](https://github.com/k1moradi/swapz/issues/120).**
**Task ID:** `agent2-real-linux-producer-integration`
**Planning swapz baseline:** `408728d43c16e67556c41f2e55c11e56ed68c33b`
**Proposed Linux exact source:** `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`. Actual [GitHub-hosted full Linux source preflight](https://github.com/k1moradi/swapz/actions/runs/43718607383) has verified the full checkout, SHA, `defconfig` and `make prepare`, but **no owner-authorized durable writable Linux source repository exists yet**. Begin only after Agent 1 proves that second gate and publishes `ROUND_OPEN`.
**Previous candidate:** [Round 002 Agent 2 report](https://github.com/k1moradi/swapz/issues/119#issuecomment-6893835007) and [source-context candidate diff](https://github.com/k1moradi/swapz/issues/119#issuecomment-6893821816). These are unqualified input, **not** a full-source patch application or production build.
**Independence:** Do not wait for Agent 3's same-round work. Do not edit swapz `src/kernel/dm-target.c` or push to `swapz/main`.
**Report archive:** `round003/agent2-real-linux-producer-integration-report.md` (Agent 1 writer after issue report).

## Required implementation (real source, not diff-only)

1. Confirm the exact full Linux source checkout in the newly authorized writable source destination, clean initial tree and permitted source-commit path. The hosted source-fetch preflight confirms that remote checkout is feasible; it does **not** give you a persistent working tree or write permission. Only work within an owner-authorized repo. **If the host/source/destination gate is missing, stop and mark `BLOCKED_PRECONDITION`; do not rerun source-context models in place of the real implementation.**
2. In that real checkout **edit the actual kernel C, headers and KUnit source files directly**. Carefully reconcile the earlier nine-file candidate against real code; use the narrowest necessary edits in `mm/zswap.c`, `mm/page_io.c`, `include/linux/swap_ops.h`, `include/linux/blk_types.h`, `include/linux/bio.h`, `block/bio.c`, and Kconfig/Makefile/KUnit sources as justified. Do not create alternative swapz source trees or product APIs.
3. Preserve exact semantics: `ORDINARY_OR_UNKNOWN=0` and `ZSWAP_STORED_WRITEBACK=1` only after actual matching stored entry, validated decompression and full-page backing write. An initial rejection, ordinary path, raced/reused entry, failure or ambiguous provenance stays unknown; do not infer from `REQ_SWAP` or global `zswpwb`.
4. Ensure `bio_init`/`bio_reset`, clone, split, merge/aggregation and requeue/reuse cannot forge a positive origin. Address `swap_io_ctx` and `swap_iocb` ownership; prevent mixed-origin write aggregation; verify `CONFIG_ZSWAP=y/n`. No UAF, over-read of mismatched `struct bio`, leaks, lost completions or double accounting.
5. Keep the frozen review interface `BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN`, `bio_is_zswap_stored_writeback(const struct bio *)`, and exact two-state scalar semantics; any unavoidable ABI divergence must be surfaced to Agent 1 **before** publication. Neither a capability macro nor compiled header alone is proof of live kernel ABI.
6. Write/modify **real KUnit or source-integrated tests**, not only extracted source fragments. Exercise positive authenticated stored writeback, rejection/ordinary negatives, mixed-origin merge, clone/split/reset/reuse and failed I/O. Preserve Linux kernel build conventions and existing comments. Minimal change; fail-only diagnostics.

## Verification and source publication

Run full-tree `git diff --check`, Kbuild `W=1/W=2` under actual matching kernel configs/headers as available, `CONFIG_ZSWAP=y/n`, real KUnit if executable, and relevant warning/sanitizer tests. Report each attempted command/exit, compiler, architecture, config provenance and `NOT_RUN` accurately. Never represent a synthetic fragment compilation as Kbuild.

**The deliverable is an actual edited, tested, durably committed kernel source revision** at the approved writable destination; a standalone `.patch` file or GitHub issue-comment diff is not a deliverable. Use only the authorized direct-branch protocol; no new branch, fork, PR, secondary worktree or unauthorized `torvalds/linux` push. If the destination cannot accept a lawful tested source commit, report `BLOCKED_PUBLISH` with precise evidence rather than PASS.

After work is actually authorized, post one `message: REPORT_READY` to issue #120 with the durable kernel source commit URL+SHA, modified source files, tests/exits, remaining ABI and runtime qualification gates, and task PASS/BLOCKED/FAIL. **Phase A remains BLOCKED** until matched producer/consumer and genuine writeback qualification; Phase B remains disabled.
