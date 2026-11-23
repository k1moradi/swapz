# Round071 Agent2 — original current-DM upper BIO ownership and once-only handoff

**State:** execute only after authoritative `message: ROUND_OPEN` on [issue #188](https://github.com/k1moradi/swapz/issues/188). This work is independent of new source/tests/results from Agents 3–6; existing committed `main` plus pinned original Linux at `c339f4010dea8b0d754f84ace70cd1b089878ef8` is sufficient. Read [common contract](frozen-contract.md), `AGENTS.md`, context/vision/coding/testing standards and the [Round070 closeout](../round070/round-report.md).

## Deliverable and exact bounds

Develop **original-kernel source-bound negative/positive tests** for the current dm-swapz upper BIO lifecycle and correct source identity at the *real current selected DM mapping*, with no import activation. Reuse currently committed Round063/065 original DM target KUnit/stage infrastructure **read only**, stage only byte-identical production `src/kernel/dm-target.c` with original pinned Linux source, and identify actual existing callbacks, `bio` identity, `dm_target` selection, ordered worker handoff and `bio_endio` once-only invariant. Demonstrate requeue, table replacement/dtr, duplicate/late callback, failed write, resubmission, unknown source identity and active table generation **fail closed**. A test-only fake selected target does not authenticate a production selected source; clearly mark NOT_AUTHENTICATED. Avoid new API demands from any peer and do not attempt privileged DM loading.

**Exclusive new owned files**:
- `tests/runtime/native/fixtures/round071-original-dm-upper-owner.cfrag`
- `tests/tools/round071-stage-original-dm-upper-owner.py`
- `tests/tools/round071-original-dm-upper-owner-verify.py`
- `.github/workflows/phase-a-round071-original-dm-upper-owner-noauth.yml`
- `docs/handoff/zswapz/round071/agent2-evidence.md` (only as implementation evidence)

Inspect `src/kernel/dm-target.c`, `src/kernel/zswap-import-admission.h` and historical originals **read-only**. If a true original current-DM source cannot be attached safely, assert the exact absent identity/entry point in a tested *negative* and report `SOURCE_MAPPED_AUTHENTICATED=0` rather than calling a modeled source authentic. Do not edit `src/kernel/dm-target.c` or any Agent3/4/5/6 files unless Agent1 grants exclusive ownership of a demonstrated isolated defect.

**Acceptance:** one exact current main + original Linux pin; actual rootless original UML KUnit JSON/KTAP execution when viable, zero skipped for claimed passing tests; strict GCC/Clang source-linked ASan/UBSan + compiled/executed C semantic mutants; exact stage postimage and negative mutation checks; no UAF/leaked owned `bio`, duplicate `bio_endio`, orphan after requeue or stale table. If resource/compatibility prevents original runtime, report precise original first compiler/runtime blocker honestly. Never claim actual physical FUA, true upper BIO publication or production source auth. Commit test source and appended standards on sole main using single-parent non-force fresh expected-head FF; publish SHA/parent/tests/limitations to #188.
