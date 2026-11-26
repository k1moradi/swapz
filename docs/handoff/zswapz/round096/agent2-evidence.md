# Round096 Agent2 — terminal evidence reconciliation

**PASS_HOST_SUBSTITUTES_ONLY / ADAPTER_SELECTION_REQUIRED / NO_GO_LIVE.** Both focused source-linked host jobs are terminal SUCCESS. Neither is native compilation, Linux RCU execution, capture, source authentication or physical admission.

## Publication overlap disclosure

Earlier Agent2 invocation published [eec8cbdc856c4d9b26da5c342c234a041b3ce727](https://github.com/k1moradi/swapz/commit/eec8cbdc856c4d9b26da5c342c234a041b3ce727) with callback-based external revoke/join and [pending evidence](https://github.com/k1moradi/swapz/commit/e0474cb732651fe10c01e3214c0a29ad21494961). This invocation independently built a distinct RCU-gated adapter at [fa03b9f09cc4e6892f09282157f044edd694f073](https://github.com/k1moradi/swapz/commit/fa03b9f09cc4e6892f09282157f044edd694f073) from the same immutable freeze before checking the existing Agent2 issue comment/evidence. That was avoidable overlapping source ownership. Both alternatives are outside normal Kbuild, no producer installed. **Do not combine them or count them as two independently accepted qualifications.** Preserve published history; Agent1 must select exactly one before a future native composition. No same-round peer code dependency or R095 accepted corpus replay; no additional native build or manual CI replay was dispatched. Existing broad workflows automatically triggered by source pushes retain actual status. No branch/PR/force.

## Earlier primary source — terminal result

- [Exact source](https://github.com/k1moradi/swapz/commit/eec8cbdc856c4d9b26da5c342c234a041b3ce727), sole parent 588d4de2bd1b86ed969493594babd70264de89be. [Focused CI run 45827930586/job 139936814544](https://github.com/k1moradi/swapz/actions/runs/45827930586/job/139936814544), all seven steps success, first error null; GCC 13.3.0 and Clang 18.1.3 ASan/UBSan, 61 checks and 3 scenarios each, both compiler logs empty.
- [Artifact 15121222759](https://github.com/k1moradi/swapz/actions/runs/45827930586/artifacts/15121222759), independently downloaded, 674B, four members, ZIP CRC PASS, computed SHA-256 `d846f636597b22b904246162b52a441c972b57eca264365b9f46ebb6e2f560bb` equals uploaded/API digest. Two 80B result logs, two empty compiler logs.
- Complete standards prefix CI PASS: 1,862,494B -> 1,864,270B; parent SHA-256 `2149096f5e84e354e443d297ba0f3a72abca3e204c16b698d24abf7581ca471a`. Exact-source CI census snapshot {"success":10} (not whole-main qualification). The prior QUEUED report is preserved below as history.

## Supplemental alternative — actual RCU gate source and terminal result

- [Source/test commit fa03b9f09cc4e6892f09282157f044edd694f073](https://github.com/k1moradi/swapz/commit/fa03b9f09cc4e6892f09282157f044edd694f073), sole parent [26d4e980d64674aad465c042628c8faf4276a757](https://github.com/k1moradi/swapz/commit/26d4e980d64674aad465c042628c8faf4276a757); expected-head nonforce update and remote source verified.
- [Native adapter C](https://github.com/k1moradi/swapz/blob/fa03b9f09cc4e6892f09282157f044edd694f073/src/kernel/native-observation-adapter.c), [H](https://github.com/k1moradi/swapz/blob/fa03b9f09cc4e6892f09282157f044edd694f073/src/kernel/native-observation-adapter.h), [fixture](https://github.com/k1moradi/swapz/blob/fa03b9f09cc4e6892f09282157f044edd694f073/tests/runtime/native/fixtures/native-observation-adapter-host.c), [explicit host substitutes](https://github.com/k1moradi/swapz/blob/fa03b9f09cc4e6892f09282157f044edd694f073/tests/runtime/native/fixtures/native-observation-adapter-host-model.h), [workflow](https://github.com/k1moradi/swapz/blob/fa03b9f09cc4e6892f09282157f044edd694f073/.github/workflows/phase-a-native-observation-adapter-host-noauth.yml), [frozen actual event map and preflight](https://github.com/k1moradi/swapz/blob/fa03b9f09cc4e6892f09282157f044edd694f073/docs/handoff/zswapz/round096/agent2-native-adapter-readiness.md).
- [Focused run 45849741037/job 140012676393](https://github.com/k1moradi/swapz/actions/runs/45849741037/job/140012676393), all seven steps SUCCESS, first actual error null. [Artifact 15133880782](https://github.com/k1moradi/swapz/actions/runs/45849741037/artifacts/15133880782), independently downloaded, 847B, ZIP CRC PASS all four members, computed SHA-256 `deccf2324bc455065e2d8a89eca0c621732bfe482d663c76d83b7850553f04b0` matches upload/API digest; both compiler logs empty, each result log 246B. Exact-source CI census snapshot {"in_progress":4,"success":6}; no manual separate native build or replay.
- Standards complete prior prefix PASS: freeze 4152a1ce0c067ccb6b872f5f7aa0b89507ec8f2e (1,856,114B); actual parent 9c1ec8d4f8ac2b300c93fb07cff9f10e7f5e3046 (1,866,457B), new f699ab78cc8cd0a11a8b557b572ee9eeb7c82bb7 (1,868,056B); 1,599B append. Exact raw Git parent roundtrip and complete appended readback matched; CI parent SHA-256 `923b7eb99f0c4883558520afed073a36fbb579353f5690bbee636804fc9715c7`.

Actual Linux atomic_t, atomic_try_cmpxchg_relaxed (64 API attempts), sticky atomic_or, release/acquire aligned u64 sequence (64-bit targets) and one-shot RCU gate. Explicit cold init, preallocated 1..8192 records and 65536 IDs max; no ring overwrite, allocator/hash/I/O/log/callback in append. Stop unpublishes and joins RCU in process context then clears retired pointer. Outer gate must outlive every potential external caller including paused pre-RCU entrants. No actual producer hooks, native build or activation. Disabled path checks only stable gate pointer; future producer must guard input construction too, not claim zero actual overhead. Reservation order is not completion order; use authoritative transition or supported partial order. Unchanged v2 framing and no raw identity/payload dumps.

Strict GCC 13.3.0 and Clang 18.1.3 C2x ASan/UBSan. Actual source-linked C uses explicit host C11/GCC atomic and pthread rwlock substitutes, not native Linux RCU/LKMM/IRQ proof.

| Actual metric | GCC | Clang |
| --- | ---: | ---: |
| Checks | 200092 | 200092 |
| Scenarios | 5 | 5 |
| Disabled calls | 200000 | 200000 |
| Disabled modeled RCU entries / CAS attempts | 0 / 0 | 0 / 0 |
| Disabled elapsed ns including checks | 517518 | 749779 |
| Owner / gate bytes | 72 / 24 | 72 / 24 |
| Record / wire bytes | 296 / 296 | 296 / 296 |
| Compiler diagnostics bytes | 0 | 0 |

Five changed scenarios: paused reserved writer versus stop, complete marker and sticky late loss; paused pre-RCU caller sees inactive gate after stop; hole refuses seal/export; forced exactly 64-attempt mint/append retry exhaustion then sticky contention/overflow; clean exact v2 wire, failed sink refusal, disabled operation counts. No timing threshold, native performance extrapolation, or accepted R095 stress replay. Distinct RCU model vs earlier callback-based implementation; overlapping tests are not extra qualification credit.

Frozen source map: actual MM capture-off and DM hard-false claim; same FIFO descriptor, real lower full write then flush and authority publication, actual clone vs original ACK, deferred releases/GC/discard/teardown. Frozen read releases pin before final BIO copy; independent owner EBUSY retry unresolved; no shared provider gate or GC proof claimed. Exact qualified MM postimage identified from accepted R095 verifier, not independently rebuilt here. Physical preflight is only a proposed checklist: exact scoped inactive existing SWAPSPACE2 partition, original page0/UUID/table, bounded natural pressure, independent exact original compressed stream and full original 4096B oracle, safe cleanup. Proposed ceiling drawn from existing development policy, not approval of integrated workload. No prior successful runtime evidence is demanded before first authorized trial; reviewed current integrated source and safe preflight remain missing.

**AUTH0 Phase A BLOCKED, compressed handoff/forced RAW/import OFF. No VM/boot/load/device access/physical mutation/activation, no owner make test/fast_test, no standalone native build, no normal Kbuild or DM/MM core changes. No native capture or physical PASS.**

---

## Historical earlier Agent2 pending report (preserved verbatim)

# Round096 Agent2 evidence — source published, CI QUEUED

**Verdict: PROGRESS / QUEUED (not PASS).** Source published directly to main. No standalone native build, VM, module load, capture activation or physical mutation. AUTH=0; Phase A BLOCKED; compressed handoff, forced RAW bypass and import OFF.

## Immutable identity

- [Engineering freeze](https://github.com/k1moradi/swapz/commit/cb38c5de310edc4842e77099b92fc709e1934322); [task publication](https://github.com/k1moradi/swapz/commit/d756136217332fe03bce41e57328473fa4505220); original Linux c339f4010dea8b0d754f84ace70cd1b089878ef8.
- [Agent2 source](https://github.com/k1moradi/swapz/commit/eec8cbdc856c4d9b26da5c342c234a041b3ce727), sole actual parent [588d4de2bd1b86ed969493594babd70264de89be](https://github.com/k1moradi/swapz/commit/588d4de2bd1b86ed969493594babd70264de89be). Main expected-head update was non-force and verified; two stale-parent preparations stopped before ref update. No peer implementation used.
- [Adapter C](https://github.com/k1moradi/swapz/blob/eec8cbdc856c4d9b26da5c342c234a041b3ce727/src/kernel/native-observation-recorder.c), blob 3a9b9040b4f87a13d31361f4467809d82fc52da3; [H](https://github.com/k1moradi/swapz/blob/eec8cbdc856c4d9b26da5c342c234a041b3ce727/src/kernel/native-observation-recorder.h), blob f1959c40d58854fd9e2e2264c882db9a8b8dfe62.
- [Host fixture](https://github.com/k1moradi/swapz/blob/eec8cbdc856c4d9b26da5c342c234a041b3ce727/tests/runtime/native/fixtures/native-observation-kernel-adapter.c), blob 87b9a543d4edb33652c5bc9871031cd7aa6fc81c; [shim](https://github.com/k1moradi/swapz/blob/eec8cbdc856c4d9b26da5c342c234a041b3ce727/tests/runtime/native/fixtures/native-observation-kernel-shim.h), blob 59ae3fe45ec64e96fd5b02aa33e7e8f3f8c7b55f.
- [Frozen event map and physical admission checklist](https://github.com/k1moradi/swapz/blob/eec8cbdc856c4d9b26da5c342c234a041b3ce727/docs/handoff/zswapz/round096/agent2-native-recorder-admission-map.md), blob 2e2496818ef2db1d36e0fd818de5bd84e49181aa. Complete exact dependency pins in companion JSON.
- Standards freeze blob 4152a1ce0c067ccb6b872f5f7aa0b89507ec8f2e (1,856,114 bytes); actual parent blob 1e4befccf27e96238c8ce6c1fb55f561d19ba602 (1,862,494 bytes) round-tripped to identical Git blob, verified entire freeze prefix, appended meaningful applicable standards only; new blob 855b4e5a533f60ff5dcf72fb048d6eebea1ee9bf re-fetched and matched exact concatenation. Commit diff +27/-0 standards lines.

## Changed engineering and bounds

Separate kernel-compatible C/H only, no core or Kbuild edits. Actual Linux atomic_t/atomic_try_cmpxchg_relaxed/atomic_or, one 32-bit smp_store_release marker per slot with smp_load_acquire at seal, bounded 8192 slots and 64 reservation attempts, token space capacity*8, sticky saturating loss flags. Explicit disabled init, one-shot start, stop, external revoke/join, seal and cold sink. Disabled adapter entry performs one acquire read, no counter or input access; no claim of end-to-end zero overhead. Caller provides disjoint storage and external lifetime starting before the enabled check. Callback must synchronously revoke/join all native entrants; no actual native caller exists. False callback retains owner and storage; no seal/export. Reservation order not causal completion; actual transition points/partial orders and no inferred upper ACK. Fixed SWZOBS2 104/296/24 byte framing preserved, including historical mapping-source lineage tag (not current-source authentication). No allocation/hash/I/O in append.

R095 accepted 1,027,438 checks / 14 scenarios / 98,304 full-capacity records each, 72 B owner and 296 B wire (prior host prototype); not replayed. New host fixture targets paused writer/stop and later publication, join refusal, quiescent unpublished slot, fixed retry exhaustion and disabled entry overhead, sink refusal, overflow/sticky loss and selected wire bytes. Separate host shim substitutes for kernel primitives and deliberately injects failed CAS/pause. No original Linux execution, no native KTAP or capture, no physical data, no mutations claimed.

## Actual CI

- [Focused exact-source push run 45827930586](https://github.com/k1moradi/swapz/actions/runs/45827930586), attempt 1, head eec8cbdc856c4d9b26da5c342c234a041b3ce727.
- [adapter-host job 139936814544](https://github.com/k1moradi/swapz/actions/runs/45827930586/job/139936814544): **queued** on last direct lookup. No compiler output, native or host scenario count, artifact ID/hash or first CI error yet; null rather than fabricated evidence. GCC/Clang ASan/UBSan planned in committed workflow, not executed as of this snapshot.
- Seven static source predicates checked true by exact-SHA retrieval (Linux atomic primitives, release/acquire slot publication, explicit external drain, one-shot start, unchanged framing constants, parent-prefix workflow gate, no standalone native build command). These are source checks only, not compiler or concurrency results.
- Local git transport failed DNS resolution for github.com; no local compile was executed. GitHub connector source publication succeeded. Existing automatic main source-path workflows also triggered; no independent native dispatch, rerun, VM or accepted-corpus replay initiated.

## Remaining admission blockers

No actual native producer/upper ACK witness, external revoke/join integration, scoped default-off positive gate, pin-through-final-upper-copy, or proven complete built-in owner drainage at freeze. Shared adapter/provider not the current target's bridge. The old ordinary primary physical helper disables zswap, so it cannot qualify integrated natural-pressure flow. The map names actual frozen call sites and limitations; it is not installed instrumentation. First trial requires reviewed current integrated source/compile, independently source-bound full-page/opaque-compressed oracle, protected page0/UUID/table and exact owner-approved inactive partition scope, bounded natural pressure and safe recovery. No circular requirement for successful trial evidence before first authorized trial, and no authorization now.

Inspect the existing exact-source job when terminal; publish a separate evidence-only update with actual counts, first failure and artifact integrity. No owner make test/fast_test now.


## Agent1 independent terminal reconciliation
```json
{
  "source": "fa03b9f09cc4e6892f09282157f044edd694f073",
  "run": 45849741037,
  "job": 140012676393,
  "conclusion": "PASS_SELECTED_RCU_ADAPTER_HOST_SUBSTITUTES_ONLY",
  "artifact": 15133880782,
  "sha256": "deccf2324bc455065e2d8a89eca0c621732bfe482d663c76d83b7850553f04b0",
  "checks_each": 200092,
  "scenarios_each": 5,
  "disabled_calls_each": 200000,
  "disabled_rcu_cas_each": 0,
  "owner_bytes": 72,
  "gate_bytes": 24,
  "wire_bytes": 296,
  "exact_census": {
    "success": 8,
    "in_progress": 2
  },
  "selected_paths": [
    "src/kernel/native-observation-adapter.c",
    "src/kernel/native-observation-adapter.h"
  ],
  "alternative": {
    "source": "eec8cbdc856c4d9b26da5c342c234a041b3ce727",
    "job": 139936814544,
    "run": 45827930586,
    "artifact": 15121222759,
    "sha256": "d846f636597b22b904246162b52a441c972b57eca264365b9f46ebb6e2f560bb",
    "checks_each": 61,
    "scenarios_each": 3,
    "status": "HISTORICAL_UNSELECTED_HOST_PASS_NOT_ADDITIVE"
  },
  "scope": "One RCU gate instead of external callback-only alternative; no actual native compile or capture yet. Selection conditional on native compilation. Both archives CRC/SHA verified; no duplicate credit."
}
```
