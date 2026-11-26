# Agent7 — R094 actual shared decoder provider
Verified [ROUND_OPEN](https://github.com/k1moradi/swapz/issues/212#issuecomment-7182008450), task e4de57c4e96669add5072290870ca199d17d8a04, engineering freeze efd77858cd20650213559ceb9cb4d0362db32ea5. [Source 0bd024561b2b03fa7837556cbd723f8f27d80b27](https://github.com/k1moradi/swapz/commit/0bd024561b2b03fa7837556cbd723f8f27d80b27), sole parent 1f8f7023d6fda5617ce021d65e44372cfb391c91, expected-head nonforce FF verified. Peer advanced during preparation; reattached owned unpublished source and applicable appendix to fresh main, no competing overwrite. Six paths only. Complete standards 5488f1437c94559b94fe7f480e8d83557033afe6 1830041B, literal full prefix +1355B, 13eaf8c16d39a2d5cc5eea55ed24fc4a5f72a383 1831396B, complete remote readback. Frozen value handle header 0f103783aee10d18df5c502fdf553f7ac6a0035d unchanged; prior R093 accepted corpus not repeated.

Actual opt-in [provider C](https://github.com/k1moradi/swapz/blob/0bd024561b2b03fa7837556cbd723f8f27d80b27/src/kernel/zswap-original-decoder-shared.c) and [header](https://github.com/k1moradi/swapz/blob/0bd024561b2b03fa7837556cbd723f8f27d80b27/src/kernel/zswap-original-decoder-shared.h) implement constant-size two shared codec owners with retained lifecycle leases and independent transient read leases. Borrow caller-retained immutable authority pin, resolve authoritative snapshot outside owner lock, compare epoch/generation/index/codec/version, validate bounds and disjoint ranges, actual original decode with CRC/SHA, release lease, copy output outside owner lock with external entrant/pin still held. No second table, scan, per-page heap or module ref. Begin-close fences admission; busy finish refuses; inconsistent private reference count or release failure quarantines instead of waiting on impossible drain. Caller must revoke/join all entrants (including pre-lock and post-decrement output copy) and drain storage pins before finish. Non-reused external authority epoch must survive consumer reload or refuse. No actual native reload/target/authority integration proven; trusted callbacks and host storage metadata remain boundary adapter. No production wiring, hard activation OFF.

[Focused run 45756625253/job 139696644377](https://github.com/k1moradi/swapz/actions/runs/45756625253/job/139696644377) attempt1 queued / pending. New strict GCC/Clang source-linked test targets 1024 simultaneous pins and five semantic mutants per compiler (epoch admission, generation, index, closing, read lease release); real pinned original LZ4/LZO1X, deterministic paused admitted reader, retired pinned read, stale reuse and epoch exhaustion. No compiler counts, sizes, mutant kills or artifact claimed until actual CI completes. First error none observed. Native runtime NOT_RUN. No branches, PRs, force, manual duplicate CI, VM, module loading, physical mutation or activation. AUTH0 Phase A BLOCKED compressed handoff/forced RAW/import OFF.

## Terminal R094 qualification (supersedes queued observation)
[Run 45756625253/job 139696644377](https://github.com/k1moradi/swapz/actions/runs/45756625253/job/139696644377) attempt1 terminal SUCCESS on exact source 0bd024561b2b03fa7837556cbd723f8f27d80b27, sole parent 1f8f7023d6fda5617ce021d65e44372cfb391c91. All job steps SUCCESS, source/policy/diff preflight and full actual parent standards prefix passed. Raw job JSON PASS_ACTUAL_SHARED_PROVIDER_HOST_ONLY; GCC C2x and Clang C23 each 2107 checks, 1024 simultaneous retained host storage records, real pinned original LZ4/LZO1X, 5/5 actual provider mutants compiled/executed/killed each (epoch, generation, index, admission, read_release); first_error=null. Original staging negatives 5 compressor/4 decoder. Measured constant host shared owner 312 bytes, host authority sidecar 16 bytes, frozen handle 24 bytes; 1024 sidecars 16384 bytes, owner plus sidecars 16696 bytes excluding payload, caller handles, scratch and other metadata. No new decoder-owned record table or per-record codec reference. Actual shared provider host code passed; storage authority/epoch issuance and external entrant quiescence remain explicit integration assumptions, native module linkage/unload/reload and actual physical/production capacity NOT_RUN. [Artifact 15088755172](https://github.com/k1moradi/swapz/actions/runs/45756625253/artifacts/15088755172) 1602 bytes sha256:910b12bd73da857472b6b194eeab646226b5b917afd640e71366dd0670871e44; GitHub metadata and job upload log agree, no independent ZIP extraction claim. Prior R093 accepted corpus not replayed. AUTH0 Phase A BLOCKED compressed handoff/forced RAW/import OFF. No branch/PR/force/manual duplicate CI/VM/load/physical operation.

## Directed native continuation — separate from accepted host PASS
[Source f2f0a3ec0450352e5b70338b21710029c892fd31](https://github.com/k1moradi/swapz/commit/f2f0a3ec0450352e5b70338b21710029c892fd31), sole parent 0f490355e1a414909b694ff20d9dc92486f1c16d, direct main FF verified. Actual shared provider source remains 0bd024561b2b03fa7837556cbd723f8f27d80b27 (unchanged); one directed native object only, exact seven source/header pins, original Linux c339f4010dea8b0d754f84ace70cd1b089878ef8, strict warnings, isolated Kbuild with dormant guards. No R093 composite or accepted host replay. Checks four provider API definitions and five decoder/owner call imports, no host/allocation/module-reference imports, actual ELF relocatable object; no full kernel/module link, modpost/load/runtime. Parent standards dad412d7e8f0b069538b3460420f90bd949f5e3d 1838245B +901B =1839146B post19c38b30cc013c227d6048b3e8ce2fe7ccd76d95 exact literal prefix and byte readback verified. [Run 45763547658/job 139718948300](https://github.com/k1moradi/swapz/actions/runs/45763547658/job/139718948300) attempt1 queued / pending at observation. No native compile PASS, object or symbol counts claimed yet. First error none observed. Prior actual-provider HOST PASS remains terminal. AUTH0 Phase A BLOCKED all activation OFF. No branch/PR/force/manual dispatch/VM/load/physical mutation.


## Agent1 focused terminal reconciliation
```json
{
  "source": "0bd024561b2b03fa7837556cbd723f8f27d80b27",
  "job": 139696644377,
  "run": 45756625253,
  "conclusion": "PASS_ACTUAL_SHARED_PROVIDER_HOST_ONLY",
  "artifact": 15088755172,
  "sha256": "910b12bd73da857472b6b194eeab646226b5b917afd640e71366dd0670871e44",
  "checks_each": 2107,
  "mutants_each": 5,
  "owner_bytes": 312,
  "host_sidecar_bytes": 16,
  "handle_bytes": 24,
  "records": 1024,
  "exact_census": {
    "success": 10
  },
  "native_source": "f2f0a3ec0450352e5b70338b21710029c892fd31",
  "native_job": 139718948300,
  "native_run": 45763547658,
  "native_conclusion": "FAIL_PREREQUISITE_BEFORE_OBJECT",
  "native_artifact": 15091117691,
  "native_sha256": "d2de025e64bff12c0709412fca5ccaef38912275cc8e3ced72eb6ebaa14d25eb",
  "native_first_error": "modules-prepare exit2; objtool/elf.h:10:10 fatal error: gelf.h: No such file or directory",
  "scope": "Actual provider C/H, host authority model. Shared API requires trusted retained storage pin and external epoch authority surviving reload; current bounded storage callback lacks pin argument. Native compile not reached."
}
```
