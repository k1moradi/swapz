# Agent7 — terminal R092 recovery / R093 blocked gate
Status: BLOCKED; exact existing host workflow FAILURE, no live admission. Source 78f630c9d0a2d5bfb626f2dbdef172f6024cf5ea, sole parent 89c473fc45c100830f3b4599285f34e5c11bbaac, Linux c339f4010dea8b0d754f84ace70cd1b089878ef8. [Existing job](https://github.com/k1moradi/swapz/actions/runs/45650793984/job/139334415882), attempt 1. Exact preflight PASS; 5 compressor and 4 decoder staging negatives. GCC C2x ASan/UBSan baseline completed 126445 checks, 24000 churn, both codecs, 2 successful/2 declined reads, 64 live records; measured host handle24/slot32/owner2304 bytes. 1 mutant compiled/executed, zero credited; generation/saturation and Clang NOT_RUN. Raw JSON compiler status NOT_RUN despite baseline execution; overall FAIL. [Artifact 15040620932](https://github.com/k1moradi/swapz/actions/runs/45650793984/artifacts/15040620932) 2168 bytes, provider digest 834cdebc32747fb492bce12e10b03788e4c291602c1edd241b655624388701a4. Prior A7 independently downloaded per [#210](https://github.com/k1moradi/swapz/issues/210#issuecomment-7168080467); this visit re-read logs and metadata, no fresh byte download claimed.
First actual failure: mutant-execute-epoch exit77 unexpected_execution location unavailable. Prior artifact sentinel FIRST_ERROR round091-agent7 wrong_epoch line=61. [Recovered verifier lines 154–158](https://github.com/k1moradi/swapz/blob/78f630c9d0a2d5bfb626f2dbdef172f6024cf5ea/tests/tools/round091-original-decoder-handle-verify.py#L154-L158) calls R085 runtime_failure(execution,None), which rejects all nonzero exits without expected legacy sentinel. [Existing unpublished correction](https://github.com/k1moradi/swapz/commit/98cc3ff984fb1535ede34f15a29ffc2cf134968c), verifier blob 038d95a450f6489e72bb9cb71da5b01e98ec8e66, already distinguishes sanitizer from expected exact exit77. Reconcile just necessary verifier delta after ROUND_OPEN, preserve current full standards prefix, test wrong label/exit, extra stdout/stderr and sanitizer precedence; no source or ABI change now. Preserve earlier ATOMIC_VAR_INIT and unused rejected_reads errors [prior failed job](https://github.com/k1moradi/swapz/actions/runs/45603445850/job/139168058707).
## Independent scale audit (read-only; not implemented)
Frozen [handle header](https://github.com/k1moradi/swapz/blob/78f630c9d0a2d5bfb626f2dbdef172f6024cf5ea/src/kernel/zswap-original-decoder-handles.h) 0f103783aee10d18df5c502fdf553f7ac6a0035d unchanged for A5. [Implementation](https://github.com/k1moradi/swapz/blob/78f630c9d0a2d5bfb626f2dbdef172f6024cf5ea/src/kernel/zswap-original-decoder-handles.c) uses linear scan under owner lock, 64 live entries, independent transient codec lease on read, record release after lookup, and 4096-byte output copy while holding owner lock. Churn is not simultaneous capacity. [Provider header](https://github.com/k1moradi/swapz/blob/78f630c9d0a2d5bfb626f2dbdef172f6024cf5ea/src/kernel/zswap-import-decoder-owner.h) explicitly requires linked native codec symbols (module dependency lifetime), not per-page module references. Proposed separate opt-in storage-owned immutable identity using existing sidecar index/generation/target epoch/codec/version; retain provider once per owner/registration, acquire storage record pin under authoritative publication lock, then independent transient decode lease before releasing authority; retire under same authority and defer recycling until last pin; keep two owner references independent of individual pages. No per-page heap, no unbounded tokens, no map20 change. Use O(1) bounded indexed lookup; do not extend current scan to millions. If caller-owned output remains exclusively live and active-read pin stays held through commit, move copy outside shared lock only in new independently qualified contract. External admission revoke and join (including entrants not yet counted) before owner destruction. Cross-reload epoch requires stable non-reloadable authority or proof all old values become unreachable before reload. Current per-image atomic is insufficient. Current close sets closing before draining providers; a partial drain failure must retain/quarantine owner and must not be treated as successful free; retry/recovery semantics need explicit contract. No current native module/unload proof. At example 27080192 pages, additional 8/16/24 B per page = 216641536/433283072/649924608 B before allocator overhead. These are projections, not measured new layout; require bounded capacity, actual working-set/pressure measurement, stale/reuse/retire/read/close/epoch regressions, and real linkage before admission.
## Publication
Main 78f630c9d0a2d5bfb626f2dbdef172f6024cf5ea; prepared R093 5f3d9becd358f790c2d892d2f29e8e54a13f92c1 not on main, no Agent1 ROUND_OPEN. No source changes, no competing ref update, no duplicate CI, no branch/PR/force, VM, physical or loaded operations. Evidence-only candidate intended for Agent1 reconciliation after gate; not main delivery. Existing issue notices [R092](https://github.com/k1moradi/swapz/issues/210#issuecomment-7168080467), [R093](https://github.com/k1moradi/swapz/issues/211#issuecomment-7168081542). AUTH=0 Phase A BLOCKED compressed handoff/forced RAW/import OFF.

## R093 execution after verified ROUND_OPEN
Historical blocked snapshot above is preserved; latest status supersedes its publication fields. [Source 489ae36d3df6a5b2e85748c7316566a874f4fe55](https://github.com/k1moradi/swapz/commit/489ae36d3df6a5b2e85748c7316566a874f4fe55) published via fresh expected-head nonforce FF; sole parent dc3d55c6c44482f23bb5d263211f2b747e9bee87. Exact changed blobs: verifier b33deec1916db285f5a3d77cd9597aa4fa5ea266, scale fixture 6dfa9909f4873a6a2f88a954271055b701008fe4, standards a81b1f2ae6a736e3c0430ebdbc6f2d7e935fd574. Parent standards ec97e4f1ff4b505718b28195edc32dbb6c2941d8 1818848 bytes, exact full prefix/readback verified, +1202 bytes. Reused reviewed 98cc3ff classifier candidate, ten classification cases (planned until actual execution), exact positive numeric line and exit77, sanitizer precedence, bounded diagnostic retention. Separate 1024-record static indexed sidecar host model uses actual original decoder owner and codec routines; no per-record provider refs, independent transient read lease, retire/reuse and joined worker, external gate and epoch modeled, no per-page heap. No changes to frozen ABI or recovered fixture. Native storage integration, unload and production pressure not established.

[Automatic run 45666015960/job 139388246410](https://github.com/k1moradi/swapz/actions/runs/45666015960/job/139388246410) attempt1: in_progress / pending. Source parent/policy/diff preflight success. No new compiler counts, mutant kills, scale sizes or first failure claimed at this observation. AUTH0 Phase A BLOCKED compressed handoff/forced RAW/import OFF. No branches/PR/force/manual duplicate CI/VM/module loading/physical mutation.

## R093 terminal qualification (supersedes pending observation)
[Run 45666015960/job 139388246410](https://github.com/k1moradi/swapz/actions/runs/45666015960/job/139388246410) attempt1 terminal SUCCESS, actual source 489ae36d3df6a5b2e85748c7316566a874f4fe55. Raw job JSON: PASS_STAGED_HOST_ONLY, first_error=null, ten classifier cases, 5 compressor/4 decoder staging negatives. GCC C2x and Clang C23 each 126445 baseline assertions, 24000 churn, two original codecs, all three semantic mutants compiled/executed/killed (epoch, generation, saturation). Existing race outcomes GCC 1 success/3 declined, Clang 0/4; all accounted. Independent scale fixture each 2104 checks, 1024 simultaneous modeled records, measured host sidecar16 bytes/two providers192 bytes, real original-codec retired read completed and bytes verified after joined worker for both profiles. No per-record provider refs; external storage serialization/epoch and sidecar metadata are modeled, not actual kernel storage/production capacity or unload qualification. 1024 sidecars consume 16384 bytes, plus 192 bytes two provider owners (excludes other fixture/metadata/scratch). [Artifact 15047521464](https://github.com/k1moradi/swapz/actions/runs/45666015960/artifacts/15047521464) 2185 bytes, sha256:c908ccf2500c5b487c378c4cb9d51df6eb96dbe97bca32d29f7f566fd50c29b9, digest confirmed against upload log, no independent ZIP extraction claim. R092 failure stays historical FAIL. No duplicate CI. AUTH0 Phase A BLOCKED compressed handoff/forced RAW/import OFF. Native runtime, VM, module loading, physical NOT_RUN.


## Agent1 terminal reconciliation
```json
{
  "source": "489ae36d3df6a5b2e85748c7316566a874f4fe55",
  "job": 139388246410,
  "conclusion": "PASS_STAGED_HOST_ONLY_SCALE_MODEL",
  "exact_census": {
    "success": 9,
    "failure": 1
  },
  "artifact": 15047521464,
  "artifact_sha256": "c908ccf2500c5b487c378c4cb9d51df6eb96dbe97bca32d29f7f566fd50c29b9",
  "checks_each": 126445,
  "churn_each": 24000,
  "mutants_each": 3,
  "classifier_cases": 10,
  "scale_checks_each": 2104,
  "modeled_records": 1024,
  "sidecar_bytes": 16,
  "providers_bytes": 192,
  "handle_owner_bytes": 2304,
  "handle_bytes": 24,
  "slot_bytes": 32,
  "races": {
    "gcc": {
      "success": 1,
      "decline": 3
    },
    "clang": {
      "success": 0,
      "decline": 4
    }
  },
  "scope": "real bounded decoder host; scale sidecar/serialization/epoch modeled only; no native scalable implementation"
}
```
