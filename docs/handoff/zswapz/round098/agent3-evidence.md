# Round098 Agent3 — guarded scoped DM and producer-candidate correlation

**PROGRESS / COMPLETED / FAILURE — AUTH=0, Phase A BLOCKED.** Compressed handoff, forced RAW bypass, import OFF. No invocation, boot, load, device access, or physical operation.

## Immutable inputs and publication

- [Task](https://github.com/k1moradi/swapz/commit/d3b7896bdc63bff8e5d84b50319aea55657c908f); [engineering freeze](https://github.com/k1moradi/swapz/commit/5a36cabf0989dfffc75de52a6ab8cc021092ebf6); [official open](https://github.com/k1moradi/swapz/issues/216#issuecomment-7197685535). Existing own round directory and R097 checkpoint reviewed before edit. R097 [accepted source](https://github.com/k1moradi/swapz/commit/f15e3682c87444dde69c1ee75b6e4f3ad146493f), [job](https://github.com/k1moradi/swapz/actions/runs/45856728473/job/140036956683), artifact 15135319557 SHA256 81f61ec8f9389f56b181b7a4e6906745173e5cc0866eeb76f5ea1f87541bc8fe, 453 checks/four semantic mutants per compiler (Agent1 reconciled). No replay. R097 native verifier failure retained, not misreported as PASS.
- [R098 source](https://github.com/k1moradi/swapz/commit/fdb750848000b59a2ca18b64efdc3f81ee6ebc02), sole parent `27d5750eadc847b7aa21be4db2d1f2a54b998532`. Main-only fresh expected-head nonforce. Own DM target, new focused fixtures/runner/workflow, standards appendix. No MM/core, recorder/provider implementation, normal Kbuild or A5/A7 changes. Frozen selected owner/adapter only, no same-round peer dependency.
- Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`. Frozen R097 producer stage runner and raw chain must verify actual MM/page_io/carrier postimages; those remain expected until CI executes. Exact producer accessor and candidate-get functions extracted from staged MM, actual broker/owner retry, actual original codecs, actual A5 storage/provider, selected actual RCU adapter and observation owner. No source-authentication credit.

## Scoped consumer source

Explicit new guard `SWAPZ_ROUND098_SCOPED_TARGET_TEST` requires frozen R097 gated path and 64-bit ABI. Legacy hard-false helper remains for old staging. No ordinary Kbuild change. Private `swapz_scope_install_locked(ctx, const struct swapz_mm_trial_scope *)` is a cold target-local control boundary, no exported setter, message, sysfs or parameter; **no native caller installed**. The controller must retain exact target lifecycle and mapper bdev plus the counted MM scope cap across revocation/grace. Install validates independent exact route query, current cap/session/table/target epochs, snapshot registration, aligned nonzero range within pages 1..16, area/type, supported geometry and ordinary accepting state. One installation per fresh session, not per resume; route revoke clears hint but not used-session high-water. Constructor still null_blk/nonphysical only; no physical bootstrap or unreviewed enable switch. Scope is not recorder active.

Provider lookup uses local route availability under queue_lock, not an invented area/type; MM must independently check actual area/type/codec/length. Candidate_get declines before retain without local scoped route. At admission and again under queue_lock immediately before broker tryclaim, exact captured key, local scope identity, session/table/target epoch, area/type, logical page/sector, M3568 codec/version/dictionary/decoded length are verified against the proposed read-only MM query. Existing selected-origin and accepted-clone/table/registration/generation proofs remain. Native sole process caller uses the accepted descriptor's scoped identity under new guard; final revalidation prevents stale admission from authorizing claim. Existing reserve/commit/cancel uses the actual embedded storage. No new map/provider, no second BIO, no postclaim ordinary fallback. Existing R097 stable gate, epoch consume, retained read pin through copy, drain/retire/real autonomous retry logic unchanged.

**Scope incarnation/interface gap:** proposed bool query does not return the MM scope identity. Source assumes one independently published scope per exact nonreused broker session/route, and local control prohibits rearm for that session. Trusted MM/controller must enforce the same rule and retained lifetime. If same-session scope republish is permitted, require additive exact ABI `bool swapz_mm_trial_scope_matches_route_identity(struct block_device *, sector_t, u64 area, u32 type, u8 codec, u32 length, const struct swapz_mm_route *, u64 expected_scope_identity)` and an immutable value scope_identity from the retained original carrier accessor, then revalidate that exact identity under queue_lock. No naked pointer or guessed ID. Until reviewed connection, native private installer deliberately unreachable; no physical admission proof.

## Actual typed-WRITE correlation

Under scoped observation guard consume frozen `swapz_mm_candidate_observation(origin,ref,out)` at same selected-origin invocation before queue lock. Validate complete captured key and page digest; mint independent clone/descriptor IDs only when recorder active, retain operation/original/clone/descriptor/extent and compressed digest on single actual FIFO descriptor; no pointer identity. Fresh event-specific zeroed records at FIFO accept, ordered dispatch, actual prepared-page presence (no fabricated discarded preparation), reserve, claim linearization, refuse/cancel/fallback, actual synchronous lower submit/completion and flush, authoritative publish, actual clone end_io after final status and deferred candidate put. Deferred release carries only operation/descriptor scalar tokens, no BIO pointer; clone terminal retains tokens even on fallback. Lower observed SHA is of actual submitted immutable compressed buffer, only while active, not independent media readback. No hash/IO/alloc under queue lock, no store-time hash/cache, no observation-based authorization. Existing gated provider and retry unchanged.

Unsupported or missing lineage explicitly invalidates evidence, not I/O. Typed read retains pin through final copy but no real read original/extent token or independent full-page oracle yet, so read trace invalidated. Ordinary write, discard and fallback lower/original completion not correlated, unsupported traces invalidated; no inferred original ACK from clone. GC/cleanup full trace and actual native prep discard/decode-cost metrics still missing. Frozen producer R097 event builders known invalid for selected adapter; fixture supplies explicitly host-seeded correct CAPTURE/BIND records to exercise actual accessor and DM-created events, not a producer event-conformance or original upper proof. A11/A2 lanes own those components.

## Exact CI snapshot

[Focused job](https://github.com/k1moradi/swapz/actions/runs/45870750218/job/140085220786), source fdb750848000b59a2ca18b64efdc3f81ee6ebc02: completed, conclusion failure. No completed compiler counts or semantic kills established in this snapshot. Artifact inventory [{"id":15142447528,"name":"round098-agent3-composed-target","digest":"sha256:4de79976a1c4de9570167353ed610c443a23dfd918abcbdd3a1d89ae2de398b9","size_in_bytes":484}]. First error: 2026-11-26T17:48:26.5244737Z R098_FIRST_ERROR carrier type swapz_mm_route. Automatic source census {"queued":26,"failure":2,"in_progress":2} of 30, not whole-main acceptance.

New focused lane intends one LZ4 scoped transaction and revocation after admission using real reservation cancellation/ordinary fallback, exact producer accessor and real selected recorder allowlist/wire correlation, host Linux/DM/lower/upper primitives and explicit scope query boundary (actual frozen scope predicate, no R098 native publication). Two changed semantic mutants (ignore MM scope revocation, ignore producer slot); no accepted R097 corpus replay or retry test replay. Host seeded source events and modeled final clone callback, not native execution. Actual selected adapter rejects invalid event fields; expected wire counts are not completed results. No native full build, no manual CI rerun, no KUnit/KTAP or real device evidence by A3. Local tool does not provide a repository-native compiler checkout; only exact-source hosted qualification pending.

## Complete historical standards

Freeze dff61588713f8ceeecb5e406cab8788e12990147 (1874135 bytes); actual source parent de0c920b51294c8d3311836d227e5e71d3a89c69 (1877087 bytes); post 7e1f11bef82d1214b96234e84d1a2065a5864ec3 (1879120 bytes). Complete byte prefix verified by parent exact Git blob roundtrip and append readback, 2033 bytes appended. Evidence-only publication leaves standards unchanged.

Remaining: terminal exact-source CI, externally validated scope/controller publication and one-session identity agreement, native linked full producer/consumer/recorder, true read/ordinary/discard/fallback original ACK correlation and independent oracle, actual native preparation costs. No live activation or physical trial permission.

## Terminal first-run failure and corrected qualification
Initial exact-source job [140085220786](https://github.com/k1moradi/swapz/actions/runs/45870750218/job/140085220786) completed FAIL before compiler execution: `R098_FIRST_ERROR carrier type swapz_mm_route`. Raw producer postimage verification returned before failing struct extraction. New runner double-escaped raw regex literals for carrier extraction and two verdict parsers. Original failed archive [15142447528](https://github.com/k1moradi/swapz/actions/runs/45870750218/artifacts/15142447528), 484 bytes, SHA256 4de79976a1c4de9570167353ed610c443a23dfd918abcbdd3a1d89ae2de398b9 agrees between log/API, not independently downloaded. No compiler credit.

Narrow [correction](https://github.com/k1moradi/swapz/commit/bd5b2573adc31ea1e58c6094faf616964cbfafff) sole parent 88e485625d7e9c44a614d7abf11844b0d3350f35: only those three verifier literals and standards appendix. DM unchanged. Actual parent 1,879,120 bytes preserved; 667 appended, 1,879,787 total. Corrected [job 140086855765](https://github.com/k1moradi/swapz/actions/runs/45871228934/job/140086855765) terminal PASS_SCOPED_TARGET_ACTUAL_ACCESSOR_RECORDER_HOST_ONLY: GCC c2x and Clang c23, ASan/UBSan, each connected 67 checks/1 claim/12 actual selected recorder records/loss0; revoked 63 checks/0 claims/1 fallback/10 records/loss4; 130 checks and two semantic mutants each (exit77 witnesses in JSON). Actual staged producer postimages verified. [Corrected artifact 15141444720](https://github.com/k1moradi/swapz/actions/runs/45871228934/artifacts/15141444720), 827 bytes SHA256 dfc948ba3cdc5da889198a52b8782962c7618afaeee8977708a3b40da2d5eb81 agrees between log and API, archive not independently downloaded. No manual rerun. First error none on corrected job. Host controller and CAPTURE/BIND seeded explicitly; no native publication, actual original ACK or complete trace claim. External controller, same-session identity agreement, native link, missing operation classes and independent oracle remain blockers. Initial FAIL retained. AUTH0 Phase A BLOCKED, no activation. [Issue notification](https://github.com/k1moradi/swapz/issues/216#issuecomment-7199854664).


## Agent1 independent terminal reconciliation
```json
{
  "source": "fdb750848000b59a2ca18b64efdc3f81ee6ebc02",
  "tested_corrected_source": "bd5b2573adc31ea1e58c6094faf616964cbfafff",
  "run": 45871228934,
  "job": 140086855765,
  "conclusion": "PASS_SCOPED_TARGET_HOST_ONLY_WITH_RETAINED_INITIAL_FAIL",
  "artifact": 15141444720,
  "sha256": "dfc948ba3cdc5da889198a52b8782962c7618afaeee8977708a3b40da2d5eb81",
  "archive_bytes": 827,
  "checks_each": 130,
  "connected": {
    "checks": 67,
    "claims": 1,
    "fallbacks": 0,
    "events": 12,
    "loss": 0
  },
  "revoked": {
    "checks": 63,
    "claims": 0,
    "fallbacks": 1,
    "events": 10,
    "loss": 4
  },
  "mutants_each": 2,
  "dm_blob": "aaff4d782323f9f17046cb2ba4fabcc0069e51e6",
  "initial_failure": {
    "run": 45870750218,
    "job": 140085220786,
    "artifact": 15142447528,
    "sha256": "4de79976a1c4de9570167353ed610c443a23dfd918abcbdd3a1d89ae2de398b9",
    "error": "carrier type swapz_mm_route",
    "correction": "Three double-escaped raw regex literals; DM unchanged."
  },
  "exact_census": {
    "success": 5,
    "queued": 3,
    "failure": 1,
    "in_progress": 1
  },
  "legacy_failure": {
    "run": 45871228833,
    "job": 140086855188,
    "error": "Round048 target_map lost actual original lifetime anchor: entry = dm_per_bio_data(bio, sizeof(*entry));"
  },
  "scope": "Actual typed-WRITE accessor and selected recorder, seeded producer records; no native controller or physical target; revoked scenario deliberately incomplete (loss4), NOT clean fallback evidence. Source audit: two dm_per_bio_data assignments in swapz_map at 16188/16253, audit expects exactly one. Fix without weakening lifetime proof; preserve early zero-token initialization before early KILL/REQUEUE."
}
```
