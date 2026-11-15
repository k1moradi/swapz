# Round 002 — two independent implementation tasks

**Coordination issue:** [#119](https://github.com/k1moradi/swapz/issues/119)
**Execution status:** PREPARING until the issue receives an authoritative `message: ROUND_OPEN` with the immutable task-commit SHA.
**Frozen swapz source baseline:** `f11e8795f44f15fecc6b2b200c0b1a9e4eaeb364`.
**Frozen `dm-target.c` source blob:** `746a6349823d8e8f52dfc68f025d29db9942ff2e`.
**Frozen Linux producer prototype source:** `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` (7.3-development source; NOT a selected loaded/production kernel).
**Purpose:** Produce two substantial, independently applicable patches, not additional architecture-only reports.

## Same-round independence and ownership

| Agent | Executable task | Canonical report filename |
| --- | --- | --- |
| 2 | [Upstream provenance implementation](agent2-upstream-provenance-implementation.md): exact-pinned kernel-side origin patch with code/tests | `agent2-upstream-provenance-implementation-report.md` |
| 3 | [Passive DM consumer implementation](agent3-passive-dm-consumer-implementation.md): real `dm-target.c` diff and commit-side observability, plus source-coupled tests | `agent3-passive-dm-consumer-implementation-report.md` |

Both agents consume **preexisting** candidate API definitions, documented below. Agent 2 must not wait for Agent 3; Agent 3 must not wait for Agent 2. Do not ask Agent 1 or another worker to finish a Round 002 prerequisite. If build resources are unavailable, produce the actual patch and best available exact-source verification, and mark full kernel build NOT_RUN; a design memo without a code diff does not meet this round's assignment.

Agent 1 is the sole **GitHub archive/integration publisher** under `AGENTS.md`. Worker outputs are full text/patch and evidence posted to this round's **GitHub issue comments**, never competing commits to `main`. No branches, PRs, secondary worktrees or forks. The prior Round 001 original reports and closeout are [archived](../round001/round-report.md).

## Frozen candidate API for parallel implementation (NOT approved runtime ABI)

- `SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN = 0`; `SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK = 1`.
- Proposed Linux private capability `BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN`, BIO scalar `bi_swap_origin`, and helper `bio_is_zswap_stored_writeback(const struct bio *)` in `<linux/bio.h>`.
- The helper must check exact origin `1` with `REQ_OP_WRITE` and `REQ_SWAP`; `REQ_SWAP`, reclaim flags and global `zswpwb` alone never authenticate prior stored-entry writeback.
- Agent 2 publishes the source-side semantics; Agent 3 codes the expected header guard against this **already frozen** name/signature. Both default unknown. An absent macro must compile without referencing the helper or field.
- Kernel `struct bio` layout and the module header/run-time match are UNQUALIFIED: no loaded test or production certification merely because the macro compiles.
- Phase A is **observability only**: no LZ4/delta64 suppression, RAW bypass, scheduling changes, authority/CRC/generation changes, disk-format change or completion change. Phase B remains disabled.

## Common acceptance

A `REPORT_READY` comment MUST include the full unified diff (or numbered follow-up comment(s) containing its full text), file/blob SHA baselines, exact tests/commands/exit codes, PASS/FAIL/NOT_RUN distinction, and a git-apply check against an actual full matching source checkout if available. Source-excerpt/synthetic model success must be labeled ROOTLESS, never exact-kernel Kbuild or genuine zswap eviction. A report with no substantive code patch is BLOCKED for the implementation task even if its review/tests passed.

Agent 1 may later integrate Agent 3's reviewed diff serially on `main`, without taking over code authorship. Agent 2's patch belongs to a separate upstream Linux source tree; it must not be silently applied to Ubuntu headers or committed into swapz. Actual patched-kernel compile, runtime ABI identity, loaded positive-origin writeback and 4KiB exact readback require separate qualification.

No kernel install, module insertion, mapper/swap mutation, reclaim pressure or physical test is authorized by these task prompts.
