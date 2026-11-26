# R098 Agent2 — actual selected recorder event conformance and external controller readiness

**PASS_ACTUAL_SELECTED_RECORDER_EVENT_CONFORMANCE_HOST_ONLY / NO_GO_LIVE.** Focused exact-source host qualification terminal success. The frozen R097 event defect is reproduced by the actual selected adapter; no native event capture or controller closure claimed.

- [Engineering freeze](https://github.com/k1moradi/swapz/commit/5a36cabf0989dfffc75de52a6ab8cc021092ebf6), [task](https://github.com/k1moradi/swapz/commit/d3b7896bdc63bff8e5d84b50319aea55657c908f), [source/test](https://github.com/k1moradi/swapz/commit/13ebac98ce9dfcaf6ba77604d0248f6bc54e09c2), sole [actual parent](https://github.com/k1moradi/swapz/commit/da19176ae71c0c1b0ae8e5a55fdb41fdeec1038d). Direct main expected-head nonforce, existing own round directory/issue checked twice; no overlapping recorder, same-round peer source or accepted replay.
- [Extraction](https://github.com/k1moradi/swapz/blob/13ebac98ce9dfcaf6ba77604d0248f6bc54e09c2/tests/runtime/native/round098-observation-extract.py), [actual recorder-linked fixture](https://github.com/k1moradi/swapz/blob/13ebac98ce9dfcaf6ba77604d0248f6bc54e09c2/tests/runtime/native/fixtures/round098-observation-conformance.c), [wire conformance checks](https://github.com/k1moradi/swapz/blob/13ebac98ce9dfcaf6ba77604d0248f6bc54e09c2/tests/runtime/native/round098-observation-conformance-test.py), [controller readiness](https://github.com/k1moradi/swapz/blob/13ebac98ce9dfcaf6ba77604d0248f6bc54e09c2/docs/handoff/zswapz/round098/agent2-controller-readiness.md), [workflow](https://github.com/k1moradi/swapz/blob/13ebac98ce9dfcaf6ba77604d0248f6bc54e09c2/.github/workflows/phase-a-round098-observation-conformance-noauth.yml).
- [Exact CI run 45870066080 job 140082863894](https://github.com/k1moradi/swapz/actions/runs/45870066080/job/140082863894) SUCCESS seven steps; first unexpected error null. GCC13.3.0 / Clang18.1.3 strict C2x high warnings ASan/UBSan, compiler logs empty. [Artifact 15141643001](https://github.com/k1moradi/swapz/actions/runs/45870066080/artifacts/15141643001) independently downloaded 4,411B, all 20 members CRC PASS; computed SHA-256 `bb7bcfb87a006a147502f973218d98d15fa700a5532672070462efa768b8ebdb` matches API. Bounded logs only, no raw wire artifacts. Broader automatic exact-source census snapshot {"queued":3,"success":3,"in_progress":4}; not whole-main qualification. No manual duplicate CI.
- Full historical standards prefix: freeze dff61588713f8ceeecb5e406cab8788e12990147 1,874,135B; actual parent b681c3997a733ba40ae85cbd9c90f238c057e1d7 1,875,291B raw roundtrip exact; new de0c920b51294c8d3311836d227e5e71d3a89c69 1,877,087B +1,796B only. Connector and CI complete-prefix PASS, parent SHA256 `727654ff79fac2bdd22252232e9cefa92a165a687abd28b58a346b98a785ffbe`. Eight selected adapter/owner/parser/shim pins PASS. R097 accepted 481/4 +11 cases each not replayed.

## Actual frozen constructor conformance

Selected RCU adapter C/H and owner C/H, both parsers and host primitive shim unchanged. Exact frozen R097 patch c35b35c18cc11f9b86c0b65856dbc0cd2a0bd2c8 and DM f1922cc26caf7bfa097c1f561f8719744c3a4e75 verified from freeze, exact added MM constructor functions extracted unedited, plus actual DM missing-lineage helper. Extraction log: MM 3028B SHA256 447db0b6ea868c7ab56a4201746ea9a7bfdd5e74f8241a391bec0bca04c5bac6; DM 146B caab60dc0492ba77c2bcd6728cc536acdc82ac00a7273b484bb803e066f2a57f; frozen owner support 2128B d99759b037ae8031d489708e1b4edd041c310a496c1af63499226af84bc68434. No applied Linux postimage or native execution asserted. Actual adapter allowlist, append, mint, loss, export, owner scope and parser; host substitutes only for surrounding minimal carrier and primitive implementations, not permissive append.

| Mode | Checks each | Actual retained events | Actual sticky loss |
| --- | ---: | --- | ---: |
| Frozen PREPARATION | 8 | CAPTURE | 4 |
| Frozen BIND | 10 | CAPTURE | 4 |
| Frozen UPPER_ENDIO | 12 | CAPTURE + fresh setup BIND | 4 |
| Frozen CAPTURE_DROP / release | 10 | CAPTURE | 4 |
| Frozen bound carrier release | 12 | CAPTURE + fresh setup BIND | 4 |
| Frozen DM missing lineage | 8 | none | 4 |
| Fresh event-specific clean typed write/read/drop | 53 | 30 | 0 |
| Terminal release overflow during failed join | 17 | CAPTURE + CAPTURE_DROP | 10 |
| **Total** | **130** | | |

Seven expected malformed append rejections/compiler across six frozen defect modes; no malformed records retained. Offline parser rejects actual exported loss; DM empty-record trace first error header_bounds, not recorder_loss (footer separately verified INVALID). Terminal overflow fails release while gate remains active during join; failed join retains array and invalidates evidence, subsequent modeled true join releases storage without restoring lost records. Eight allocations/frees and nine join callbacks per compiler. New validator checked 23 frame/semantic cases per compiler, 46 total. Seven new semantic refusals each: wrong capture key, premature ordinary prep, publish before flush, pin release before oracle, missing candidate release, missing carrier release, missing capture drop. No accepted corpus replay.

New clean 30-record host trace passes strict current-source v2 validator with two distinct clone ACKs and two original ACKs, one each of initial MM decode / ordinary prep / prep discard, actual minted IDs, reserve/claim/lower/flush/publish ordering, typed read pin and 4096-byte modeled host comparison, deferred candidate/carrier release after next acceptance, one capture drop, cleanup. This is fresh **synthetic event construction**, not native corrected A3/A11 code or actual lower/upper I/O, actual codec or independent physical workload oracle. No native KTAP. No actual native RCU/IRQ/SHA/link proof. Actual selected adapter and owner unchanged, no permissive substitute.

## Controller and physical gate

[Detailed source-mapped external join and physical preflight](https://github.com/k1moradi/swapz/blob/13ebac98ce9dfcaf6ba77604d0248f6bc54e09c2/docs/handoff/zswapz/round098/agent2-controller-readiness.md) maps actual frozen DM drain 16058–16185, target retirement 16344–16390, pin-through-copy 11582–11591 and R096 exact autonomous retry. Design requires independently approved retained scope (not recorder active), revoke optional producer admissions before joining old borrowers, preserve terminal observations during normal I/O drain, actual core SRCU/target work/deferred carrier and candidate puts, independent built-in exact old-session retry retirement witness even after target detach, authoritative zero cleanup debts and actual quarantine count before seal. Failed join sticky and retains allocation; no synthetic debt zeros, no reopening old scope, no forced removal. Strict source-bound private manifest and independent full4096 workload-reference comparison tied to exact final copy/pin and user-visible data; digest alone cannot certify independent byte oracle. No real controller or external source join installed; scope publication, read/ordinary/discard original completion, exact retry-idle witness and actual workload oracle binding remain blockers. A3/A11 own independently corrected MM/DM event fields and source admission; not consumed or edited here. No normal Kbuild, native build, physical activation, VM, module load, owner tests or device access. AUTH0 Phase A BLOCKED, compressed handoff/forced RAW/import OFF. First separately approved trial requires actual connected full native link and safe exact inactive dedicated SWAPSPACE2 scope, protected first page/UUID/table, existing bounded natural pressure and independent oracle/cleanup; no circular demand for prior physical success.


## Agent1 independent terminal reconciliation
```json
{
  "source": "13ebac98ce9dfcaf6ba77604d0248f6bc54e09c2",
  "run": 45870066080,
  "job": 140082863894,
  "conclusion": "PASS_ACTUAL_SELECTED_RECORDER_EVENT_CONFORMANCE_HOST_ONLY",
  "artifact": 15141643001,
  "sha256": "bb7bcfb87a006a147502f973218d98d15fa700a5532672070462efa768b8ebdb",
  "archive_bytes": 4411,
  "entries": 20,
  "checks_each": 130,
  "scenarios_each": 8,
  "malformed_rejections_each": 7,
  "clean_trace_records_each": 30,
  "frame_checks_each": 23,
  "semantic_refusals_each": 7,
  "exact_census": {
    "success": 9,
    "queued": 1
  },
  "scope": "Actual frozen R097 malformed constructors and DM NULL witness rejected by selected recorder; fresh positive trace synthetic I/O; no native controller, original completion, workload oracle. No source change to selected adapter/owner."
}
```
