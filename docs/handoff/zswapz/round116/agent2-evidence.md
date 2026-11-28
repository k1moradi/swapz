# R116 Agent2 — consumable queue and capacity credits

**Rootless engineering PASS_ROOTLESS_MODEL_ONLY; routing NO_GO. AUTH=0, Phase A/native qualification BLOCKED, observation UNKNOWN, actual ORDINARY, compressed handoff/forced RAW/import OFF, physical NO_GO.** Immutable candidates for A1 integration only.

## Source and evidence
Freeze dd215d9467491dbe75cd7593bb146e814cabfad3, tree bbe592501bc10b334e0192d5f361f49a0947167c; task 9bd7f5a8b564a3ed029c660a0d9086968a5a5e66. [Source candidate](https://github.com/k1moradi/swapz/commit/ee26a85a296b41beaa84f9c3b6ef465bca08da34) sole parent task, tree 01c7fc0640a5632ea6c9f16ad88de0a040be7d76. Actual tested [ledger](https://github.com/k1moradi/swapz/blob/ee26a85a296b41beaa84f9c3b6ef465bca08da34/tests/tools/phase-a-storage-credit-replay.py) blob 96147ddfd5294dc34d76a4b61b8a908f1ab73c3b and [test](https://github.com/k1moradi/swapz/blob/ee26a85a296b41beaa84f9c3b6ef465bca08da34/tests/runtime/native/phase-a-storage-credit-replay-test.py) blob 9f3ce8054491386e4d27b30578a027d4e8b4eccf exact local git hash-object and remote readback. Compare only +466/+232 new Python lines and +4 standards, no deletions. Parent standards 09b02ae725a949317ddf114cbf9cb9d8e9e10317 exact prefix preserved in 54efb632c8c4ffa53a73de70ffeccb8bff8a6093. Read frozen R115 selector 8faa25c2b6f97713a719d1b2747a7037477d5c0d, R115 A2/A4 JSON 55700d1ebf3e9adb63cd8a954bbc09a4ff5b62e9 / 01f58f08db2b5f880db056c584b9b0b25a6ab7c3 and A1 checkpoint, AGENTS and relevant standards. No R116 peer dependency.

Frozen [R114 A4 JSON](https://github.com/k1moradi/swapz/blob/dd215d9467491dbe75cd7593bb146e814cabfad3/docs/handoff/zswapz/round114/agent4-results.json) 189295 bytes, exact Git blob ca98c75e68a92ba456cd450aaaaab60b02995783 independently recomputed in connector. DNS direct git exit128; recovered exact projection of all unique optimized per-page rows, verified aggregate matches its constituent strata before exclusion. Projection 7949 bytes, Git blob f6b361912819dc219d98a54566a03bc5d999ff6d, SHA256 400f109920ea08f89f3e8f31476142e68e4b95539c6f307bf2e3229faa2792a6 matched independently computed connector Git hash. Full report not executed locally; CPU timing data not used. Reproduce projection from pinned full JSON with Python stdlib:
```python
import json
from pathlib import Path
report = json.loads(Path("docs/handoff/zswapz/round114/agent4-results.json").read_bytes())
cases = report["measurements"]["results"]["gcc-optimized"]["cases"]
rows = [sorted([[c["stratum"], *row] for c in cases if c["codec"] == codec and c["stratum"] >= 0
                for row in c["page_sizes"]], key=lambda row: row[1]) for codec in (1, 2)]
Path("frozen-rows.json").write_bytes((json.dumps(dict(source_blob="ca98c75e68a92ba456cd450aaaaab60b02995783",
    rows=rows), separators=(",", ":")) + "\n").encode("ascii"))
```

## Actual execution
Python 3.13.5 UID65534 nobody.
- `runuser -u nobody -- python3 -B tests/runtime/native/phase-a-storage-credit-replay-test.py`: exit0, 7 methods, zero skips, 2.676s. Strict metadata/caps, no outcome leakage, queue/capacity exhaustion, preclaim cancel and fresh retry, duplicate/stale/out-of-order completions, wrong sizes/status, postclaim quarantine, failed read/GC and GC retry, pin/invalidation overlap refusal, read/GC progress under full writes, RAW/zero accounting, exact unchanged state on refused external transitions, cleanup debt, deterministic schedule and redacted failure.
- `runuser -u nobody -- python3 -B tests/tools/phase-a-storage-credit-replay.py frozen-rows.json`: exit0, 25.56s wall execution of Python audit (not selector or simulated latency); stdout SHA256 91175466ad7beaa9b0c3adf4d9640c84976b5cae65c93cf9e5ffa0a827796d47. 18 combinations, 36 independent matched backing replays. No semantic test failure. First environment error direct Git DNS exit128, recovered relevant input. No A2 CI jobs.

## Lifecycle and scope
Serial single-owner model, max224 distinct logical IDs/32768 events, capacity <=256 KiB and queue 3..64. Full class reservation at arrival for every route, including zero/RAW, before ordinary size/diagnostic eligibility observed. Queue full or capacity unavailable -> defer to owner, no forced ordinary or ACK; exact metadata retry, fresh monotonic token. Explicit cancel preclaim returns reservation/queue, claim allows at most one diagnostic fallback, dispatch single active and exact completion; successful write releases unused reservation only (zero/RAW), committed allocation persists. Failed write quarantines full reservation, no fallback or ACK; unknown partial bytes not estimated. Read pin from enqueue through completion, invalidation while pinned rejected; invalidated record remains occupied until external GC completion, failure retains space and permits explicit retry. One record per 4/8/16 KiB fixed extent, ordinary RAW separate 4096, zero no extent; no multi-record packing or relocation modeled. No native path or concurrency claim.

Q-2 write slots including unclaimed reservations, one read slot and one GC slot; round-robin dispatch among write/read/GC, queued control work has <=2 intervening dispatches, conditional on continuing external opportunities; no time bound. Seven external 32-page windows (pressure/read likelihood per mille): 850/50,850/800,300/50,850/50,850/800,300/50,850/50; four service opportunities every eight arrivals, explicit read/GC offers, then two bounded recovery passes over external logical list. 7292 opportunities per run, identical across modes and backing twins. Missed read/GC offers include unavailable or already released pages; no guarantee of identical successful reads under a different schedule. No page selection/reclaim/timer initiated by ledger. Frozen R115 conservative thresholds exactly mirrored (LZ4 128..768, pressure>=750/read<=100/queue<=16, valid metadata); eligible-always differs deliberately by attempting all metadata-eligible originals before diagnostic outcome, not R115 prefiltering by label. Actual ordinary route unchanged.

## Frozen replay
All 18 alternatives: 224 write ACKs and 224 successful GC retire/reclaim completions; zero outstanding and occupied after drain; each reserved byte returned once. Backing twins identical. Per extent metrics below identical across both codec alternatives and all three policy modes; queue slots=6 (4 write,1 read,1 GC).

| Extent | Capacity | Peak space | Peak queue | Deferred (unique) | Queue/space refusals* | Modeled write/read B | Reserved=returned B |
|---|---:|---:|---:|---:|---|---|---:|
| 4096 | 32768 | 32768 | 6 | 213 | 30/189 | 786432/782336 | 917504 |
| 8192 | 65536 | 65536 | 6 | 212 | 36/182 | 1437696/1429504 | 1835008 |
| 16384 | 131072 | 126976 | 6 | 210 | 36/180 | 2740224/2740224 | 3670016 |

*Reasons may overlap. Every deferred logical was retried once in this replay. Read ACKs 224/224/225; max read wait 0 and GC wait 1 dispatches (dedicated saturation test asserts both <=2). Modeled write/logical ratio 0.857142 / 1.566964 / 2.986607; includes zero, RAW and allocation padding, excludes failed unknown transfers, GC relocation and actual device traffic. All modes have the same allocation bytes because one record per extent; NOT evidence of no packing benefit in a real multi-record system.

| Codec/mode | Attempted | Selected | Preclaim fallback | Payload B |
|---|---:|---:|---:|---:|
| ordinary either | 0 | 0 | 0 | 284923 |
| LZ4 conservative | 37 | 37 | 0 | 284923 |
| LZ4 eligible-always | 191 | 127 | 64 | 349137 |
| LZO conservative | 0 | 0 | 0 | 284923 |
| LZO eligible-always | 187 | 123 | 64 | 343833 |

Deferrals not fallback. Frozen schedule success path only; failure/quarantine and cancellation tested separately. No actual storage, GC implementation, residency/fault, native latency or CPU selection evidence. No multi-record packing, no overlapping active service, no quarantine recovery implementation (cleanup correctly blocks). **NO_GO: model conservation PASS but no qualified preservation advantage.** No main ref movement, branch, PR, CI/workflow, duplicate build or native/physical action. Agent1 integrates exact owned blobs and standards append on fresh main; acceptance A1 only.
