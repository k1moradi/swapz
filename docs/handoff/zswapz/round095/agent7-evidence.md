# Agent7 — R095 shared provider epoch and external entrant lifetime
[ROUND_OPEN](https://github.com/k1moradi/swapz/issues/213#issuecomment-7184043926), task 20122e158beef6266bd01bb545951a2a4f77d9d5, engineering freeze ff972661a75ca7f8c3c0458c3feb8b603c185eb8. [Actual source 21e8533bfdbdc8e09ee86e2a8e8c63f0a36a7cdd](https://github.com/k1moradi/swapz/commit/21e8533bfdbdc8e09ee86e2a8e8c63f0a36a7cdd) sole parent 771340dc5f568bf853c433636a36024f5ea75794, verified on main nonforce expected-head. Actual C/H blobs 3b48a4f6f31ef9c45034db7e0509efe92583e404 / 19bce03addcee7a2eeb0983ea360d4e2a5df0912. Frozen provider signatures and 24B handle preserved; no per-record table/module reference/heap. Complete historical standards 1843426B +1502B =1844928B exact literal prefix and remote byte readback, hosted policy/diff and prefix PASS.

Actual admitted count uses infallible atomic release after final unlocked page copy; stable external admission gate counts through provider call/return, refuses stale session before pointer access, revokes new entrants, busy finish preserves provider. Gate is externally retained until all pre-gate entrants quiesced. One freshly opened built-in broker owner session per lifecycle, burn before fallible init, reject zero/wrap/mismatch/reuse, never reuse existing session after module reload. This is a contract with trusted external owner capability, not raw integer authentication or a module-local epoch authority. Host adapter explicitly supplies broker identity and independent storage pin; no native integration/reload proof. Partial init unwinds independently initialized codecs, both retained references validated before destructive close, failure quarantines; no unsafe retry. Caller retains exact authoritative storage pin, disjoint page buffers and gate across synchronous read. Native producer/consumer integration deferred; A10 sole new native lane; R094 native gelf.h failure retained, not retried.

[Focused run 45770634552/job 139742145865](https://github.com/k1moradi/swapz/actions/runs/45770634552/job/139742145865) attempt1 terminal SUCCESS exact source. Actual GCC C2x and Clang C23 each 81 checks, both real pinned original LZ4/LZO1X, ASan/UBSan, 5/5 actual provider mutants compiled/executed/killed each: copy_count, epoch_match, burned_session, entrant_fence, close_preflight. Deterministic pre-provider lock, before-copy and after-copy pauses, exact output, close busy, failed init burn/unwind, stale old session/value, missing pin and partial-close quarantine. Measured owner312B (unchanged), gate88B (one per lifecycle authority), frozen handle24B; no added per-page storage. First error null. [Artifact 15093757410](https://github.com/k1moradi/swapz/actions/runs/45770634552/artifacts/15093757410) 1170B sha256:b6281fc8eb17be9345af38a853c2537152a9ebe3eb2efa617d43111037ba719f, upload log and metadata agree; independent ZIP extraction not claimed.

## Reporting defects and correction
Historical R094 workflow [run45770632922](https://github.com/k1moradi/swapz/actions/runs/45770632922) failure with zero jobs; unquoted colon in legacy exact-message YAML skip condition identified by source inspection, no job diagnostic available. Raw R095 focused results contain inherited round=094 label; verified actual R095 source/fixture/verifier hashes, run head and named pass sentinels, raw JSON retained unmodified under ci.raw_results. Corrected future metadata label and folded YAML exclusions in [correction 68479945f382bfcce2f882b484cbdd6bb48cd414](https://github.com/k1moradi/swapz/commit/68479945f382bfcce2f882b484cbdd6bb48cd414) sole parent 85139fdd0ca87541cef2cdd24f8bf0c0e1546301, nonforce expected-head verified, C/H unchanged. Complete parent standards 1847695B +770B =1848465B exact prefix/readback. Corrected [R095 run45771115565](https://github.com/k1moradi/swapz/actions/runs/45771115565) and [R094 run45771115671](https://github.com/k1moradi/swapz/actions/runs/45771115671) terminal skipped, confirming syntax and no replay of accepted corpora. Exact source host PASS remains; historical workflow failure retained. Peer advances reconciled unpublished correction against fresh parent, no overwrites. No all-current-main-green claim. AUTH0 Phase A BLOCKED compressed handoff/forced RAW/import OFF. No branch/PR/force/manual duplicate CI/VM/load/physical mutation.


## Agent1 independent terminal reconciliation
```json
{
  "source": "21e8533bfdbdc8e09ee86e2a8e8c63f0a36a7cdd",
  "run": 45770634552,
  "job": 139742145865,
  "conclusion": "PASS_ACTUAL_SHARED_PROVIDER_LIFETIME_HOST_ONLY",
  "artifact": 15093757410,
  "sha256": "b6281fc8eb17be9345af38a853c2537152a9ebe3eb2efa617d43111037ba719f",
  "checks_each": 81,
  "mutants_each": 5,
  "owner_bytes": 312,
  "gate_bytes": 88,
  "handle_bytes": 24,
  "exact_census": {
    "success": 10,
    "failure": 1
  },
  "historical_failure_run": 45770632922,
  "artifact_round_field": "094 (historical label; source pins, R095 fixture, job and verdict establish actual R095 lane)",
  "scope": "Actual gate and provider source-linked; external fresh broker capability/storage pin trust, no native reload or storage gate join yet."
}
```
