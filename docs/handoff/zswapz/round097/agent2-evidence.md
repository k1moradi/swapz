# R097 Agent2 — single selected RCU observation owner / current-source binding

**PASS_SELECTED_OWNER_HOST_SUBSTITUTES_ONLY / NO_GO_LIVE.** Focused exact-source host job terminal success; no actual native capture or physical qualification.

- [Engineering freeze](https://github.com/k1moradi/swapz/commit/f7cb6969db189c03d592a89cae43e5464946c716), [task](https://github.com/k1moradi/swapz/commit/25bf051dbb7ff4496075238f614611f16f37dc51); [source/test be44c51e132593c81f2d1ba773767efecea6792b](https://github.com/k1moradi/swapz/commit/be44c51e132593c81f2d1ba773767efecea6792b), sole actual parent [b641cf1a9efd8f18b0dc0e965c2c0b92473a2c65](https://github.com/k1moradi/swapz/commit/b641cf1a9efd8f18b0dc0e965c2c0b92473a2c65). Expected-head nonforce main publication verified. Checked issue and directory before coding and again before publication; no existing R097 A2 source/evidence. No alternative recorder, no same-round peer engineering dependencies.
- [Built-in owner C](https://github.com/k1moradi/swapz/blob/be44c51e132593c81f2d1ba773767efecea6792b/src/kernel/native-observation-owner.c), [H](https://github.com/k1moradi/swapz/blob/be44c51e132593c81f2d1ba773767efecea6792b/src/kernel/native-observation-owner.h); [strict current-source validator](https://github.com/k1moradi/swapz/blob/be44c51e132593c81f2d1ba773767efecea6792b/tests/tools/native-observation-current-export.py); [fixture](https://github.com/k1moradi/swapz/blob/be44c51e132593c81f2d1ba773767efecea6792b/tests/runtime/native/fixtures/native-observation-owner-host.c), [explicit host shim](https://github.com/k1moradi/swapz/blob/be44c51e132593c81f2d1ba773767efecea6792b/tests/runtime/native/fixtures/native-observation-owner-host-model.h), [new scope/correlation tests](https://github.com/k1moradi/swapz/blob/be44c51e132593c81f2d1ba773767efecea6792b/tests/runtime/native/native-observation-owner-test.py), [workflow](https://github.com/k1moradi/swapz/blob/be44c51e132593c81f2d1ba773767efecea6792b/.github/workflows/phase-a-round097-observation-owner-host-noauth.yml), [actual frozen event map and physical preflight](https://github.com/k1moradi/swapz/blob/be44c51e132593c81f2d1ba773767efecea6792b/docs/handoff/zswapz/round097/agent2-selected-observation-owner-readiness.md). Exact frozen inputs and owned blobs in JSON.
- [Focused run 45856564834, job 140036377176](https://github.com/k1moradi/swapz/actions/runs/45856564834/job/140036377176), seven steps success, first actual error null. GCC 13.3.0 / Clang 18.1.3 strict C2x high warnings ASan/UBSan; both compiler logs empty. [Artifact 15135253842](https://github.com/k1moradi/swapz/actions/runs/45856564834/artifacts/15135253842), independently downloaded 2069B, all eleven members CRC PASS, computed SHA-256 `3b47f7bbf104cecc90558f5b4b25197689916bd294106f92fa380b4599db3829` matches upload and API. No raw wire artifacts; bounded logs only. Nine existing broad/legacy source-push workflows automatically triggered; no manual dispatch. Exact-source census snapshot {"in_progress":4,"success":3,"queued":3}, not whole-main green.
- Complete standards prefix verified in connector and CI: freeze f699ab78cc8cd0a11a8b557b572ee9eeb7c82bb7 (1,868,056B); actual parent bec6666e6222b0eca25df5d4c1b0b197cbbaef23 (1,869,039B) roundtripped exact Git blob; new 06598d838ac9b7ef05bf71f058bf1188bd4fd5f3 (1,871,039B), +2,000B only, complete frozen and actual parent prefix. CI parent SHA-256 `cc7a30705d3395da80073c075e4827a0ccbb401544cdbcdc5fe2eca4863aa226`. CI four selected recorder/parser/shim blob pins PASS. R096 selected adapter C/H and legacy parser unchanged; accepted 200092/5 each not replayed. Unselected callback alternative historical/unlinked, no duplicate qualification credit.

## Implementation

Single guarded built-in owner uses selected RCU adapter, permanent static gate and recorder, one-shot per boot and bounded cold kvcalloc array 1..8192 records (max 2,424,832B). Only three frozen wrapper declarations and GPL export annotations: active/mint/append; no module target or BIO pointer retained. No native link/export check here. Active is a hint, must precede event construction, wrappers recheck gate. No allocation/hash/lock/I/O in disabled path; actual producer path overhead not measured. Cold control mutex serializes start/stop/export/release. Trusted synchronous external revoke+join includes paused pre-active/pre-RCU callers and all terminal event debts before RCU drain/seal. Failed join disables gate, sets sticky late loss and retains allocation, refuses export/free until genuine join; callback not retained. Static gate remains stable after release. No installed control caller or real external join integration; contract not proof of source quiescence.

Cold scope validates exact compile-time checkout SHA (not old mapping lineage), nonzero fixed ASCII hex artifact/workload/nonce/opaque target and numeric epoch/range constraints. Canonical sorted-key compact JSON hashed by SHA-256, independent expected manifest needed; SWZOBS2 104/296/24 framing and old lineage unchanged, no retroactive relabeling. New strict expected-source parser delegates existing semantic validator unchanged. No source authentication from digest assertions. Guard excludes MODULE; future scratch stage links only selected adapter + owner built-in and actual SHA API, requires real native symbol/link review. No normal Kbuild change, no runtime activation entry or caller.

## Actual new focused observations

| Scenario | GCC checks | Clang checks |
| --- | ---: | ---: |
| Clean start, scope refusals, allocation rollback, external terminal join and one-shot release | 237 | 237 |
| Failed join/retry, retained allocation and sticky loss | 118 | 118 |
| Overflow | 63 | 63 |
| Invalid event | 63 | 63 |
| Total | 481 | 481 |

Each compiler executed four separate one-shot owner instances, five allocation attempts (one deliberate refusal), four successful allocations/frees, five cold hashes and five join callbacks. Eight groups of 16 disabled calls to each of the three wrappers (128 each, 384 total per compiler), zero modeled RCU entries/CAS/hash/alloc during those checks. The clean case pauses producer before active hint; genuine pthread join releases that producer to append separate modeled original upper ACK and cleanup, then drains/seals. This is a **modeled event producer**, not native upper ACK. New offline validator on actual owner-emitted wire: 11 cases/compiler, 22 total, one consistent clean trace and ten refusals per compiler (stale source/expected source/lineage, nonce digest mismatch, wrong original ACK, clone/original alias, removed upper ACK, failed join/overflow/invalid loss). No separate mutation builds, no accepted stress or corpus replay. No native KUnit/KTAP. Host substitutes (pthread mutex/rwlock, C11 atomics, OpenSSL SHA) do not prove actual Linux RCU/barrier/IRQ/crypto/linkage or performance.

## Integration / physical gate

Frozen actual map corrects R095 read pin gap: DM 11352–11419 acquires/transfers pin; final copy 11515 then put 11520. R096 actual built-in retry overlay arms before debt check and owns exact session/epoch; frozen native DM still calls target_can_free(ctx,false) and opens old bridge before cap. No claimed A3/A11 same-round integration. Independent true native original completion is distinct from clone endio and deferred debt release; source map records actual call sites and proposed additive bounded carrier/descriptor/core identity fields, not hooks installed here. Lower completion length/status then flush/authority publication, pin-through-copy/full independent original oracle, GC/discard and terminal debts require actual witnesses. No synthetic native ACK, pointer-derived IDs, raw payload or device identity. First future bounded trial requires exact connected source/build, actual producer/consumer/external join, exact owner-approved inactive existing SWAPSPACE2 scope, protected first page/UUID/table, bounded isolated natural pressure and progress-aware safety, verified teardown and independent byte oracle. No circular prior physical-success prerequisite; no admission now.

**AUTH0 Phase A BLOCKED, compressed handoff/forced RAW bypass/import OFF.** No VM, boot, module load, device access, physical mutation, activation, owner tests or standalone native build. Only main, no branch/PR/force. Next: Agent1 review and stage one connected native composition after actual producer/consumer inputs frozen.


## Agent1 independent reconciliation (A11 still pending)
```json
{
  "source": "be44c51e132593c81f2d1ba773767efecea6792b",
  "run": 45856564834,
  "job": 140036377176,
  "conclusion": "PASS_SELECTED_OWNER_HOST_SUBSTITUTES_ONLY",
  "artifact": 15135253842,
  "sha256": "3b47f7bbf104cecc90558f5b4b25197689916bd294106f92fa380b4599db3829",
  "archive_bytes": 2069,
  "entries": 11,
  "checks_each": 481,
  "modes_each": {
    "clean": 237,
    "join": 118,
    "overflow": 63,
    "invalid": 63
  },
  "source_correlation_cases": 11,
  "exact_census": {
    "success": 7,
    "queued": 2,
    "in_progress": 1
  },
  "scope": "Actual one-shot owner wrappers with host substitutes; selected adapter/parser unchanged; native controller, external drain and producer correlation not established."
}
```
