# Round094 Agent3 — guarded target-owner consumer, source published / CI pending

[ROUND_OPEN](https://github.com/k1moradi/swapz/issues/212#issuecomment-7182008450), task e4de57c4e96669add5072290870ca199d17d8a04, engineering freeze efd77858cd20650213559ceb9cb4d0362db32ea5, original Linux c339f4010dea8b0d754f84ace70cd1b089878ef8. Agent3 DM/core/target tests only. No same-round peer implementation consumed.

## R093 terminal carryover

Independently re-read exact [source ee9b6be46dc99a535439e3372b3004255b4d158d](https://github.com/k1moradi/swapz/commit/ee9b6be46dc99a535439e3372b3004255b4d158d) parent 6faf5ce07f189baed3ec02c50608057c75bdd3d6: exact census28/28 SUCCESS. [Focused job139389189043/run45666285265](https://github.com/k1moradi/swapz/actions/runs/45666285265/job/139389189043) logs show GCC/Clang each18 registry checks, rollback baseline and both mutants omit_rollback/revoke_newer_route killed; direct consumer 24 legacy +6 typed mutation groups; ordered host each12708 checks, 5 claims, 3 refusals, 2 typed reads, 5 modeled terminal owners, 4 killed mutants. [Artifact15046849132](https://github.com/k1moradi/swapz/actions/runs/45666285265/artifacts/15046849132) 656B provider SHA256 3cbd9ae38052b6237d40e9e87ef52f0cc3f0c7297e12989c5a2a1a4a4fc1fb80 matches prior independent Agent1 download; no new ZIP extraction claimed. [R093 terminal checkpoint](https://github.com/k1moradi/swapz/blob/e4de57c4e96669add5072290870ca199d17d8a04/docs/handoff/zswapz/round093/agent1-terminal-checkpoint.md). [Prior report #211](https://github.com/k1moradi/swapz/issues/211#issuecomment-7169786284). No manual replay.

## Actual guarded source

[Source e18e17021065cba3bb343d300b67cd1fdd20407c](https://github.com/k1moradi/swapz/commit/e18e17021065cba3bb343d300b67cd1fdd20407c), sole parent a71c0473aa4f453e62c1c83b51c8d1f28d3df9ef. Direct nonforce expected-head main FF verified, compare exactly four paths:
- src/kernel/dm-target.c 27d3af6f4146bc62adfb091e0d4f1fbc9f1dd285 -> 63705a000274d649c001f47e604f2393098e1201 (+410/-5)
- tests/tools/round094-target-owner-verify.py 8f7283166bf0662c11ffc58f4b3fec879d02a115 (+421)
- .github/workflows/phase-a-round094-target-owner-host-noauth.yml 07d59ba8f41e15f90f31c0d71296c84776659d54 (+50)
- docs/testing_standards.md parent 0c1e9246da8be4c56b66369fe99bbef91f2ac3c5 1832864B -> f4951b7cc7bb63f71b7b3f3b8f3d05349803b46c 1834574B append1710B. Complete raw parent hash roundtrip, full prefix and postimage exact readback verified. Zero historical bytes removed.

Extra compile-only opt-in SWAPZ_ROUND094_TARGET_OWNER_TEST requires frozen selected DM guard. Constructor sets trial only for owned null_blk and initializes joined lifecycle work; resume queues sleepable setup outside caller-held core locks. Actual setup lines15018 onward uses built-in owner open signature with 8 slots / M3568, nonzero owner-issued session/epoch, independent monotonically assigned target incarnation and one exact returned cap moved into route, no second broker get. Real lower callbacks are existing DATA-relative 4K synchronous read/write and separately definitive flush. Bounded vmalloc storage, old frozen pointer decoder bridge and disjoint two 4096B scratch pages, attached to actual existing authority under ordered_owner. Allocation/init/attach/open/install failures unwind reverse ownership; late install only revokes exact attempted incarnation, preserves newer route. Existing provider register/unregister and transient candidate module refs retained. No fake credentials. Setup does not invoke lower I/O.

Drain revokes snapshot and route under queue_lock, removes RCU registry and joins grace before begin_close and cap put in work context; after worker and deferred candidate release drain, storage close then decoder close and finish_close. EBUSY retains owner identity and closed arrays, retry on next lifecycle; if dtr still observes live optional resources/cap/release, explicitly quarantine context rather than free an uncertain reference. That exceptional branch intentionally retains allocations and is NOT a proven leak-free native path; built-in EBUSY at final dtr may leave owner closed pending later owner-side recovery. No native unload proof. No new work on production Kbuild or peer-owned producer, no new BIO/reclaim/shrinker.

## Generation authority and source observation mapping

Lines13685–13738 snapshot for logical pages1..16, exactly64B generation array plus route epoch; no whole-device shadow and no primary map change. Sole ordered owner reads actual map generations while holding queue_lock; publishes only with empty incoming/preparation FIFO, no preparation queued, batch/inflight/GC/replay, valid accepting route and attached storage. Admission invalidates before the sole canonical FIFO link (15521); worker invalidates before every pass and republishes only before owner unlock (13762/13783), submitter fast path already invalidated by admission, republish at13864. This conservative boundary covers ordinary/typed publication, discard and rotating GC within ordered domain; delayed finalization and outstanding windows refuse until drained. Terminal failure/suspend clear snapshot under queue_lock. Lookup uses snapshot only and checks route epoch/range/nonwrapping next generation; retain rechecks snapshot, ordered claim retains actual authoritative generation and sequence checks. This is speculative ticket eligibility only, not destination reservation credit. Existing swapz_round091_ordered_claim_permitted remains hard false (12587), legacy destination-credit false remains. Native synchronized mutation coverage and native lower durability not established by the host adapter. No real import or positive claim enabled.

Per-BIO observation mapping for future A2 parser: source slot/store/key and exact original BIO/clone carrier from existing MM selected origin and retained view, canonical descriptor acceptance at swapz_map FIFO link (opaque per-run IDs not pointer output); ordered reserve/claim/cancel at swapz_round091_claim_reserved (12597) and swapz_round091_process_candidate (12656), lower result/flush in existing storage callback adapter, publish before terminal swapz_complete (2399), typed read/GC/discard and drain/release in existing ordered paths. No actual native event instrumentation added or trace enabled; aggregates cannot prove exact original compressed bytes, correlation, durable publish/upper ACK or full-page read oracle. A2 may use map without relying on new source.

## New focused CI

[Run45756808031/job139697238859](https://github.com/k1moradi/swapz/actions/runs/45756808031/job/139697238859) QUEUED, attempt pending, first error/artifact/counts not observed. New verifier compiles actual extracted register/revoke/match, setup/install, close-owner, storage lifecycle and generation helpers with explicit host allocator/owner/decoder/storage/lock adapters; no actual peer integration or modeled lower durability. GCC/Clang strict warnings ASan/UBSan, planned six semantic mutants no_generation_invalidate, ignore_pending_fifo, ignore_gc, ignore_route_epoch, no_install_rollback, erase_replacement_route. Actual counts unknown until execution. Tests planned for four allocation failures, decoder/storage/open refusal, late install failure/replacement, positive setup, duplicate refusal, range/overflow/stale/GC/FIFO/batch/inflight, begin refusal, EBUSY close/retry, storage close refusal, balanced frees/caps and monotonic reopen. Source callsite checks for canonical admission/worker/drain/resume. Local git ls-remote exit128 DNS could not resolve github.com; local compiler and diff-check NOT_RUN. Source-only CI must establish policy, diff check and actual host results.

Other existing automatic source runs [ordered host45756807994/job139697238310](https://github.com/k1moradi/swapz/actions/runs/45756807994/job/139697238310), [product45756807998](https://github.com/k1moradi/swapz/actions/runs/45756807998) compile139697238165/139697238433 exact-C139697238527/139697238643, [prototype45756808068/job139697238295](https://github.com/k1moradi/swapz/actions/runs/45756808068/job/139697238295) QUEUED. Initial exact source census29 automatic workflows queued. No manual dispatch/duplicate rerun. No new R094 integrated native build, VM, load, privilege or physical mutation. AUTH=0 Phase A BLOCKED direct compressed handoff, forced RAW bypass, import OFF. PARTIAL_NATIVE_CONSUMER_SOURCE_PUBLISHED_HOST_CI_PENDING.


## Agent1 focused terminal reconciliation
```json
{
  "source": "d620a2533ae26f109921fdff48ce28b2b05116b5",
  "previous_source": "e18e17021065cba3bb343d300b67cd1fdd20407c",
  "previous_job": 139697238859,
  "previous_failure": "puts fixture namespace collision; inherited R048 duplicate dtr detach",
  "job": 139712711603,
  "run": 45761622515,
  "conclusion": "PASS_HOST_BOUNDARY_ONLY",
  "artifact": 15090198553,
  "sha256": "0400805b349c94d64d6ad4690fef95e3e3a2b194b9935eaa737b4e565b8cace1",
  "checks_each": 50,
  "mutants_each": 6,
  "dm_blob": "2400ad0ccaf72c2586c4fd1488edb9a00246e213",
  "product_run": 45761622451,
  "product": "PASS",
  "exact_census": {
    "success": 28,
    "queued": 1
  },
  "scope": "actual extracted target code; modeled broker/allocator/decoder. Null_blk-only guard, 8 tickets, 16 logical generations/64B, old bridge, speculative capture, claim hard false. Destructor quarantine is not proven leak-free. Corrected sole detach."
}
```
