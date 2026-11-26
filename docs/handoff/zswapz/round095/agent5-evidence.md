# R095 Agent5 — actual authoritative storage pin/shared decoder join

**Checkpoint:** IN_PROGRESS; NO_GO_LIVE; not REPORT_READY. [Task and freeze](https://github.com/k1moradi/swapz/blob/20122e158beef6266bd01bb545951a2a4f77d9d5/docs/handoff/zswapz/round095/frozen-contract.md). [Source](https://github.com/k1moradi/swapz/commit/34ef333e5054f6428776dcfab63baa6309c1d4ac), sole parent `1134a184b592a44a4584a444c1933d22ad51a2d8`, engineering freeze `ff972661a75ca7f8c3c0458c3feb8b603c185eb8`. Main expected-head nonforce publication and six-path compare verified. Prior proposed parent advanced before ref mutation, so exact new blobs and appendix were attached to fresh main; no peer changes overwritten.

## R094 terminal reconciliation (no replay)

Existing [run 45763614607](https://github.com/k1moradi/swapz/actions/runs/45763614607) source f8cac65c8adc76c13fd14b664f8f850b188e91b4, jobs [139719164506](https://github.com/k1moradi/swapz/actions/runs/45763614607/job/139719164506) and [139719165135](https://github.com/k1moradi/swapz/actions/runs/45763614607/job/139719165135) both terminal SUCCESS, independently inspected decoded job logs. GCC/Clang each 8972 modeled checks and 13 semantic kills; actual bounded original LZ4 8349 checks, LZO1X 8348 each, 5 record get/put and 5 transient get/put pairs per codec/compiler. Host layout 15752B storage, 14912B legacy, 840B overhead, 2304B bounded owner, map20 and handle24. Artifact IDs 15090673470 and 15091411797 independently verified by Agent1 in frozen R094 checkpoint; not downloaded again. No unchanged accepted corpus executed.

## Actual new source

- [src/kernel/zswap-original-storage-shared-decoder.h](https://github.com/k1moradi/swapz/blob/34ef333e5054f6428776dcfab63baa6309c1d4ac/src/kernel/zswap-original-storage-shared-decoder.h) blob `b18f05a0d326dfe594e6695f13f757e313a1c3d8`.
- [src/kernel/zswap-original-storage-shared-decoder.c](https://github.com/k1moradi/swapz/blob/34ef333e5054f6428776dcfab63baa6309c1d4ac/src/kernel/zswap-original-storage-shared-decoder.c) blob `05fa6a716dcd5b5fd6a531a63908b2e9bb53cb8f`.
- [tests/runtime/native/fixtures/round095-shared-storage-shared-decoder.c](https://github.com/k1moradi/swapz/blob/34ef333e5054f6428776dcfab63baa6309c1d4ac/tests/runtime/native/fixtures/round095-shared-storage-shared-decoder.c) blob `5f24c1940f6af73878c50ca0c373a7f14d2e0d4c`.
- [tests/tools/round095-shared-storage-shared-decoder-verify.py](https://github.com/k1moradi/swapz/blob/34ef333e5054f6428776dcfab63baa6309c1d4ac/tests/tools/round095-shared-storage-shared-decoder-verify.py) blob `f29f2f363c338e31ccd9f74194d870cf7392dc60`.
- [.github/workflows/phase-a-shared-storage-shared-decoder-host-noauth.yml](https://github.com/k1moradi/swapz/blob/34ef333e5054f6428776dcfab63baa6309c1d4ac/.github/workflows/phase-a-shared-storage-shared-decoder-host-noauth.yml) blob `f812f10c01258a8478bbc00b3e35c4d677e8ab65`.

Separate opt-in storage wrapper reuses actual authority record and pin sidecar (8 records/pins), legacy sealed write/reserve/cancel/commit/relocate path, actual frozen shared provider. The opaque decoder field is a non-owning attachment marker only in this path, not a codec lease; no added per-record table or 64-entry decoder cap. Existing pointer/value interfaces and ordinary map20 unchanged. Borrowed identity uses actual pin resolution, captured lifetime epoch, globally nonwrapping allocator sequence, exact sidecar index, codec/version; no caller snapshot. A single CRC/padding-checked lower read copies compressed bytes into disjoint caller buffer. Scoped pin/bytes live only across synchronous provider call, whose snapshot callback resolves actual authority pin again; final output copy remains under sole ordered owner and retained pin. Busy close preserves attachment, unexpected provider lifetime/lease errors quarantine without releasing uncertain ownership. External caller must serialize all legacy embedded operations, authority mutation, pin/put and close; revoke/join all external entrants before close, no direct provider entry/reentry, no reinitialization while attached. Epoch supplied by modeled host authority, not native built-in epoch authority; no same-round A7 source consumed. Numeric pin IDs can restart across lifetimes, hence caller must carry captured epoch (never refresh epoch for an old pin). No allocation per record or read, no production Kbuild changes. Existing storage sidecar limit remains 8, not production scale qualification.

## Exact focused CI

[Run 45770731713](https://github.com/k1moradi/swapz/actions/runs/45770731713) / [job 139742467480](https://github.com/k1moradi/swapz/actions/runs/45770731713/job/139742467480) observed **IN_PROGRESS** (no conclusion). New source-linked GCC C2x/Clang C23 ASan/UBSan lane stages immutable engineering source via Git archive with explicit C/H pins and pinned original Linux LZ4/LZO1X staging. Targets one lower read per decode, mixed codecs within one shared lifetime, real lease counters, stale pin/epoch, retirement/GC including flush failure, overwrite, digest failure with unchanged output, generation/sequence wrap, pin release, actual layout. No terminal compiler counts, layout, artifact or runtime result observed yet. No new native build; A10 owns integrated native qualification. Local git DNS unavailable exit128; local compile, diff-check and policy NOT_RUN, new CI enforces preflight. No manual dispatch. Existing broader automatic jobs not claimed green.

## Complete historical standards prefix

Actual parent blob `f2d115f932ba471599840bced09ea1f616d486e0` 1844928 bytes +1462 bytes =1846390 bytes, new blob `ba5eaedece0dd7b952a8f1947c47fb529d3ec26e`; full parent raw blob recreation/hash and exact postimage readback verified, no truncation. Five source/test/workflow paths added and four standards lines appended. No old pointer/value or shared provider edits.

AUTH=0; Phase A BLOCKED; direct compressed handoff, forced RAW bypass and import OFF. Host epoch and RAM lower modeled; no native execution, MM source authentication, physical durability, production capacity or module reload/unload proof. No branch, PR, force, VM, module load, physical mutation, duplicate accepted corpus, or same-round peer dependency.

## Terminal qualification — supersedes the pending checkpoint above

**PASS_ACTUAL_SHARED_PROVIDER_STORAGE_HOST_ONLY / NO_GO_LIVE.** [Exact run 45770731713](https://github.com/k1moradi/swapz/actions/runs/45770731713) / [job 139742467480](https://github.com/k1moradi/swapz/actions/runs/45770731713/job/139742467480) completed SUCCESS, all steps passed. Actual decoded log and independently downloaded [artifact 15093569167](https://github.com/k1moradi/swapz/actions/runs/45770731713/artifacts/15093569167) agree: ZIP 2226 bytes, SHA256 `69c4205f1885f79384e5ed43a3fbfc4f5c5b3b98e10bdafed87dca892f8193dd`, one results.json, CRC PASS, JSON parsed, exact source/parent and frozen pins match. First error null. Hosted preflight including canonical policy, exact push sole parent, full standards byte prefix and diff whitespace check passed. No local compiler claim.

| Compiler | Primary codec scenario 1 (LZ4) | Primary codec scenario 2 (LZO1X) | Total checks | Lower reads / scenario | Lifecycle get/put | Transient get/put |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GCC C2x | 12464 | 16561 | 29025 | 9 | 2/2 | 6/6 |
| Clang C23 | 12464 | 16561 | 29025 | 9 | 2/2 | 6/6 |

Both scenarios exercise mixed codec streams inside one actual shared owner; the second includes the foreign/stale epoch refusal across fresh lifetimes, hence differing check counts. Each scenario verifies five successful full-page decodes and one bad-digest transient lease with unchanged output, two GC relocation reads and one failing lower read. Exact lower reads observed once per admitted decode, no lower call on stale pin/epoch or alias refusal, no record-owned codec leases, balanced shared lifetime and transient acquisitions. Retired old/current pins survive GC and overwrite, busy close preserves provider, stale/double put refuses, sequence and map-generation wrap refuse. Decoded full-page bytes match input; compressed bytes are checked against actual RAM lower bytes; separate full pre/post GC compressed image byte comparison not asserted. ASan/UBSan and warnings-as-errors passed; no new semantic mutation count claimed or accepted R094 corpus replayed.

Measured per compiler/scenario: wrapper 15296B, embedded legacy storage 14912B, **384B total overhead** including actual shared provider 312B, existing authoritative sidecar 1112B, map20, handle24. Prior R094 bounded storage wrapper overhead 840B; new constant wrapper includes shared provider and is not a production-scale benchmark. Existing storage capacity 8 remains; no new per-record table, no bounded 64-slot decoder owner instantiated. No native execution, physical durability, module reload/unload or external epoch authority proof. New R095 mutation testing NOT_RUN. No production Kbuild or same-round peer source consumed. Exact-source broader CI snapshot {"success":4,"in_progress":2,"queued":4,"failure":1}; no whole-main green claim. No manual dispatch or duplicate unchanged CI. AUTH0 Phase A BLOCKED compressed handoff/forced RAW/import OFF. Terminal scope is host-only, REPORT_READY.

## Post-terminal exact-source reconciliation

All 11 automatic workflows associated with exact A5 source `34ef333e5054f6428776dcfab63baa6309c1d4ac` are terminal: **10 success, 1 failure, 0 pending**. The earlier partial census is retained above. The only failed [legacy R094 provider run 45770729983](https://github.com/k1moradi/swapz/actions/runs/45770729983) has zero jobs; source inspection identifies an unquoted YAML colon in its job-level if expression (blob bbd1dae6823bee1be6c4571eeb1d04c65feaf6fd); no job-level compiler failure exists. Agent7's [correction 68479945](https://github.com/k1moradi/swapz/commit/68479945f382bfcce2f882b484cbdd6bb48cd414) uses a folded expression; exact correction runs [45771115565](https://github.com/k1moradi/swapz/actions/runs/45771115565) and [45771115671](https://github.com/k1moradi/swapz/actions/runs/45771115671) terminal skipped. Historical failure retained; no retroactive all-green claim. The focused A5 qualification remains SUCCESS; downloaded artifact 15093569167 independently rechecked in this continuation: 2226 bytes, SHA256 69c4205f1885f79384e5ed43a3fbfc4f5c5b3b98e10bdafed87dca892f8193dd, ZIP CRC PASS, results.json exact source/parent and compiler/layout results match; total 58050 checks. No additional tests executed. No new frozen A5 assignment found. Evidence-only change; no source or standards edits, duplicate CI, or same-round peer implementation consumed. All previous limitations and AUTH0/Phase A BLOCKED/live gates OFF remain in force.


## Agent1 independent terminal reconciliation
```json
{
  "source": "34ef333e5054f6428776dcfab63baa6309c1d4ac",
  "run": 45770731713,
  "job": 139742467480,
  "conclusion": "PASS_ACTUAL_SHARED_PROVIDER_STORAGE_HOST_ONLY",
  "artifact": 15093569167,
  "sha256": "69c4205f1885f79384e5ed43a3fbfc4f5c5b3b98e10bdafed87dca892f8193dd",
  "checks_per_compiler": {
    "lz4": 12464,
    "lzo1x": 16561
  },
  "lower_reads_per_scenario": 9,
  "lifecycle_get_put_per_scenario": [
    2,
    2
  ],
  "transient_get_put_per_scenario": [
    6,
    6
  ],
  "storage_bytes": 15296,
  "legacy_bytes": 14912,
  "overhead_bytes": 384,
  "provider_bytes": 312,
  "sidecar_bytes": 1112,
  "handle_bytes": 24,
  "map_bytes": 20,
  "exact_census": {
    "success": 10,
    "failure": 1
  },
  "historical_failure_run": 45770729983,
  "scope": "Actual frozen R094 shared decoder joined to storage, modeled RAM lower/epoch; eight-record authority; no new mutation count; no full pre/post-GC compressed image equality; strengthened R095 gate not yet joined."
}
```
