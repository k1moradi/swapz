# Agent 4 — Round 003: implement passive provenance status reader

**Task ID:** `agent4-passive-origin-status-reader`
**GitHub mailbox:** https://github.com/k1moradi/swapz/issues/120
**Frozen source:** `15b98edef5d8b4e401d8c5e2c9a4d7a012100ff7`. Start immediately after Round 003 `ROUND_OPEN` concurrently with Agent 6. Do not wait for a peer.
**Deliverable:** edited and compiled production C plus real source commit, not a `.patch` file or memo.

## Exact ownership and frozen API

Own ONLY `src/userspace/swapzctl.c`, `tests/runtime/native/userspace/swapzctl-status.c`, and necessary co-change in `docs/coding_standards.md`. Do not modify `src/kernel/dm-target.c`, any Linux upstream source, Agent 6's tests or `docs/testing_standards.md`.

Use existing production code: `status_find_value`, `parse_unsigned_decimal`, `parse_status_unsigned_optional`, `parse_swapz_ratio_status_diagnostic`, `ratio_status_equal`, the snapshot owner and the compiled existing `swapzctl-status.c` fixture. No second parser/tool, new CLI option, duplication or ABI change.

Frozen kernel INFO group (already committed):
- `verified_zswap_origin_admitted=<canonical uint64>`
- `foreground_committed_verified_zswap_writeback=<canonical uint64>`
- `origin_carrier_compiled=0|1`

## Must implement in actual source

1. Extend the existing read-only status/ratio snapshot with this **all-or-none optional** provenance group. Accept an old target with all three absent as **unsupported/unavailable**, never as measured zero. Reject one/two missing fields, duplicates, empty/signed/noncanonical/overflowed values, and capability values other than 0/1.
2. Require committed verified <= admitted verified and <= compressed+raw+zero_elided with overflow-safe arithmetic. In a non-atomic live snapshot, a racing inconsistency requires **existing bounded retry**, not fabricated numbers or premature permanent failure. Preserve failed/unavailable semantics, snapshot identity, ownership and lifetime; never call this proof of runtime BIO ABI.
3. Expose available provenance as **additional passive human-readable `inspect`/`stats` lines**, without changing existing JSON v1 keys/types/semantics, other status/health/diagnose modes, compression ratio logic, RAW decisions or kernel/device state. State compile-time-carrier support distinctly from runtime ABI qualification.
4. Extend the actual compiled `tests/runtime/native/userspace/swapzctl-status.c` fixture with positive/negative cases for absent group, 0/1 capability, actual zero, malformed/partial/duplicate fields, uint64 overflow, invalid positive committed counts, retries, unchanged legacy/JSON v1. Run source-matched GCC/Clang warning-clean builds and UBSan when available; run relevant existing userspace/rootless tests, `git diff --check`.
5. Update applicable `docs/coding_standards.md` in the **same code commit**, preserve existing comments, avoid allocations/locks in the read path and log only failures.

## Source publication and reporting

Edit actual files in a regular main-only checkout frozen at `15b98edef5d8b4e401d8c5e2c9a4d7a012100ff7`. Create a real Git commit (local `main` and/or retrievable Git blob/tree/commit object anchored at `15b98edef5d8b4e401d8c5e2c9a4d7a012100ff7`) for the full C/test/standard bytes. **Do not move remote `main`**: Agent 1 alone serializes direct-main integration, so you and Agent 6 may work simultaneously. No branch, fork, PR or secondary worktree; no generated patch substituted for source. Test the exact committed source; make your commit retrievable via connected GitHub Git Data operations without changing its ref.

Submit one `message: REPORT_READY` GitHub issue #120 comment: `round: "003"`, `agent: 4`, `task_id`, actual code commit SHA and changed files, exact compiler/tests/exit codes, first failure, PASS/FAIL/BLOCKED and evidence class. Do not claim integration until Agent 1 verifies its remote-main SHA. Phase A unqualified, Phase B disabled.
