# Round097 Agent3 — actual gated DM consumer and autonomous owner close retry

**PROGRESS / QUEUED — AUTH=0; Phase A BLOCKED.** Native policy remains hard false, compressed handoff, forced RAW and import OFF.

## Immutable source and boundaries

- [Task publication](https://github.com/k1moradi/swapz/commit/25bf051dbb7ff4496075238f614611f16f37dc51); [engineering freeze](https://github.com/k1moradi/swapz/commit/f7cb6969db189c03d592a89cae43e5464946c716); [official open](https://github.com/k1moradi/swapz/issues/215#issuecomment-7196749592). Checked previous R096 own reports and terminal reconciliation: accepted 435 checks and five semantic mutants per compiler; legacy correction accepted. No manual replay.
- [R097 source](https://github.com/k1moradi/swapz/commit/f15e3682c87444dde69c1ee75b6e4f3ad146493f), sole parent `be44c51e132593c81f2d1ba773767efecea6792b`. Direct main, fresh expected-head nonforce. Owned changes only DM target, new isolated fixture/runner/workflow and standards appendix. No A5/A7 provider edits, no MM edits, no recorder alternative or same-round peer dependencies.
- Original Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`. Runner verifies immutable complete staged inventory and exact R092/R094/R096 broker+owner postimages, actual A5 gated adapter/provider. No MM overlay stacked in host build; no native MM compilation attempted. Frozen capture-off native policy unchanged.
- [Focused CI](https://github.com/k1moradi/swapz/actions/runs/45856728473/job/140036956683) exact source `f15e3682c87444dde69c1ee75b6e4f3ad146493f`: queued, conclusion not yet available. No completed compiler counts established in this snapshot. Artifacts: none available at observation. First error: none observed (not a PASS claim if queued). Automatic exact-source workflow census {"in_progress":5,"queued":25} of 30; not a whole-main green claim.

## Actual guarded consumer integration

New explicit `SWAPZ_ROUND097_GATED_TARGET_TEST` requires the frozen shared-storage build guard and `SWAPZ_ROUND096_OWNER_RETRY_TEST` staging marker. The latter is only legal with the actual verified owner retry overlay; it is not a runtime permission. Normal Kbuild untouched. Old legacy bridge branch remains under the old composition for historical source-linked verifiers. No two providers in one target.

Fresh exact built-in owner cap is acquired outside target/ordered locks and moved into the temporary retained cap before calling gated storage init under ordered_owner. The epoch callback consumes that exact session/epoch once; repeated/missing/mismatched capability refuses. Module-lifetime stable gate initializes before provider registration, never on resume. Actual A5 adapter init binds embedded sole storage, with no new record table, per-page module reference or map growth. Allocation/failed-bind rollback checks gate/authority attachment before freeing; uncertain provider state quarantines. Exact source/route generation and retained cap are revalidated in the existing ordered claim. Additional scope check under ordered_owner + queue_lock requires null_blk trial, current matching owner cap/epoch, bound gated storage and logical pages 1..16; native policy still returns false. Existing native provider lookup and candidate_get refuse before speculation. Same accepted descriptor, real reserve/commit/cancel, no postclaim fallback; storage relocation still uses the embedded authority. The old prepare marker is not a measured native discard; candidate path excludes producer-owned preparation, actual native decode/CPU/bytes measurements unavailable.

Actual gated read takes the authoritative pin, captures storage lifetime epoch, invokes shared adapter decode into disjoint buffers, and transfers the pin to the real swapz_read upper BIO copy. Put follows copy even on error. Stale pin/epoch refusal stays fail closed. No ordinary read cache for typed namespace.

Close revokes route, joins registry RCU and deferred release, begins exact built-in close and drops target cap before storage close. Close on suspend with current typed records remains busy and preserves maps/provider for reads and ordinary overwrites; no reopening a provider over retained records. Final dtr only after drain verifies zero live pin/reservation debt and retires at most eight current typed records in RAM, no lower discard/extra BIO. It then closes the real gate/storage. After complete target-dependent debt is zero, the exact finish call in R096 arms the actual independent built-in worker; only genuine finish EBUSY after a successful begin, exact cap put and drain transfers ownership, clears retired identity and permits target free. Fresh open is independently refused by the built-in owner until old debt/work retires. No model retry=true as authority (guarded free ignores that parameter); no target pointer passed to retry, no self-pin/unbounded wait; arbitrary other errors remain quarantine. Host fixture calls actual staged owner_retry_run via a scheduling substitute after clearing target, not an explicit consumer finish. Native workqueue/RCU timing and dtr execution not qualified by this source-only lane.

## Observation readiness gap

The optional `SWAPZ_ROUND097_TARGET_OBSERVATION_TEST` declares the frozen proposed wrappers without adding a recorder implementation. Active candidate path invokes the real ABI's append(NULL) invalid-loss boundary when lineage unavailable, never changes I/O status. Host substitutes count this refusal. Frozen carrier has no run-local operation/original/clone correlation; do not mint IDs independently and pretend source linkage. Proposed additive guarded interface: retained carrier getter supplies immutable run-local operation/original/clone tokens and recorder capture incarnation alongside exact ticket key while source/clone held; DM mints descriptor token at accept, retains tuple through deferred put; distinct lower/extent/pin tokens minted at authoritative transitions. Map admission, reserve/claim/refuse/cancel, lower submit/completion and flush, authority publish, typed read pin/oracle/copy/release, clone endio, GC and cleanup events still require actual correlated hooks and field validation. Native original upper endio remains MM-owned. No positive recorder trace, native activation, source AUTH or physical qualification claimed.

## Standards and qualification

Frozen standards f699ab78cc8cd0a11a8b557b572ee9eeb7c82bb7 (1868056 bytes); source parent 06598d838ac9b7ef05bf71f058bf1188bd4fd5f3 (1871039 bytes), post 411cebf374af8a8b8f730016f9bab57de5629daf (1872507 bytes). Complete raw historical prefix verified by parent exact Git blob roundtrip and append readback. Evidence-only publication leaves standards unchanged. No VM, boot, module load, physical mutation, native build by A3, manual CI duplicate or force push. The new focused corpus intends both original codecs, stale incarnation/scope refusals, safe claimed WRITE failure, exact bytes, pin retention, suspend vs final dtr, actual autonomous retry/reopen, and four changed-boundary semantic mutants; only actual results above count. Remaining: terminal exact-source CI, native connected compilation by designated lane in a later freeze, complete recorder lineage, actual producer/candidate and measurement proof. All physical trial authority remains separate.


## Agent1 independent reconciliation (A11 still pending)
```json
{
  "source": "f15e3682c87444dde69c1ee75b6e4f3ad146493f",
  "run": 45856728473,
  "job": 140036956683,
  "conclusion": "PASS_ACTUAL_GATED_TARGET_RETRY_HOST_ONLY",
  "artifact": 15135319557,
  "sha256": "81f61ec8f9389f56b181b7a4e6906745173e5cc0866eeb76f5ea1f87541bc8fe",
  "archive_bytes": 944,
  "checks_each": 453,
  "claims_each": 3,
  "claimed_errors_each": 1,
  "typed_reads_each": 2,
  "fallbacks_each": 2,
  "preparations_each": 2,
  "reopens_each": 5,
  "retries_each": 5,
  "observation_losses_each": 3,
  "mutants_each": 4,
  "mutant_names": [
    "no_retry_transfer",
    "wrong_read_epoch",
    "ignore_gated_scope",
    "ignore_missing_observation"
  ],
  "inventory": 61,
  "exact_census": {
    "success": 13,
    "queued": 7,
    "in_progress": 10
  },
  "scope": "Actual frozen A5 gated storage, A11 retry, original codecs, retained pin through copy; host Linux/DM/lower/upper substitutes. Native scope hard false, missing correlation deliberately records invalid append. No native execution."
}
```
