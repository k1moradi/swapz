# Round071 Agent3 — genuine original zswap selected STORED source provenance and negative admission

**State:** start only when [issue #188](https://github.com/k1moradi/swapz/issues/188) posts authoritative `message: ROUND_OPEN`. Fully independent of Agents2/4/5/6: use existing [Agent3 Round070 original native XArray/zsmalloc 3/3](https://github.com/k1moradi/swapz/actions/runs/45045023441) as known baseline and pinned original Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`; never wait for peer Round071 APIs or source.

## Concrete P0

Close the *evidence gap*, not a fabricated production authentication: inspect and stage exact original `mm/zswap.c` source around `zswap_store_page()`, original STORED XArray/entry/slot generation, `zswap_writeback_entry()`, folio/swapcache ownership and source erase, recording under which **actual original locks and lifetimes** a bounded owned pre-erase copy can be made without UAF and whether an unprivileged pinned UML fixture can construct a **genuine swapcache-backed**, not test-allocated, selected STORED source without activating a swap device. Pin exact original source blobs and produce an executable original kernel KUnit/host source negative that rejects test-assembled entry/folio as authenticated, stale swpentry, reissue/epoch mismatch, missing folio ownership, unknown codec/pool and owner tear-down. If the real swapcache page requires `get_swap_device`, `swapon` or privileged setup, do NOT call it or label test as source auth; capture the first missing original source prerequisite and verify default-off rejection. Keep existing 3/3 immutable; do not repeat it merely to restate PASS.

**Exclusive new files**:
- `tests/runtime/native/fixtures/round071-original-zswap-provenance.cfrag`
- `tests/tools/round071-stage-original-zswap-provenance.py`
- `tests/tools/round071-original-zswap-provenance-verify.py`
- `.github/workflows/phase-a-round071-original-zswap-provenance-noauth.yml`
- `docs/handoff/zswapz/round071/agent3-evidence.md`

Original `mm/zswap.c`, `src/kernel/zswap-direct-handoff.h`, `src/kernel/zswap-import-admission.h` and old Agent3 source fixtures are **read only** apart from ephemeral test staging under a checked pristine original clone. No new source/published zswap hook, no actual MM pressure and no memory shrinker. Strict GCC+Clang sanitizer and meaningful compiled/executed source mutations; original pinned native UML KUnit where safe, matching actual JSON+KTAP; exact first failure, no skips claimed green. On missing original physical swap cache, a **tested BLOCKED prerequisite** and fail-closed provenance refusal is a valid deliverable, not pass-for-auth. Commit tests/standards only on sole main with fresh expected-head nonforce FF and evidence to #188.
