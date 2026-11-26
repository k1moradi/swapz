# Round 096 — Agent 3 bounded target transaction / teardown

**PROGRESS — focused composed host PASS; round acceptance BLOCKED. AUTH=0.** No physical mutation, VM, load, activation, forced RAW bypass or import.

- Frozen engineering commit: [cb38c5de310edc4842e77099b92fc709e1934322](https://github.com/k1moradi/swapz/commit/cb38c5de310edc4842e77099b92fc709e1934322); task/contract publication [d756136217332fe03bce41e57328473fa4505220](https://github.com/k1moradi/swapz/commit/d756136217332fe03bce41e57328473fa4505220); [ROUND_OPEN](https://github.com/k1moradi/swapz/issues/214#issuecomment-7192323028).
- Exact [source 58b599346139dd9dbee4120030a23c84a14f03dc](https://github.com/k1moradi/swapz/commit/58b599346139dd9dbee4120030a23c84a14f03dc), sole parent `eca2485f2c7bdf75f9075652a7da8ac7bbcfb752`, non-force expected-head main update verified. No same-round peer implementation consumed. Frozen Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`.
- R095 accepted host result retained, not manually replayed: [source](https://github.com/k1moradi/swapz/commit/4b15bdf4f841195ed240243a81ed13eaad7cf396), [job](https://github.com/k1moradi/swapz/actions/runs/45785010481/job/139789467324), 673 checks and 4 semantic mutants/compiler; 30/30 exact workflows at prior acceptance.
- [R096 focused run](https://github.com/k1moradi/swapz/actions/runs/45827740930), [job](https://github.com/k1moradi/swapz/actions/runs/45827740930/job/139936147434), [artifact](https://github.com/k1moradi/swapz/actions/runs/45827740930/artifacts/15121270263), GitHub-upload ZIP SHA256 `d21d8de6e111e151859f8ba76a0b179d83a317f81f56508ede772bf44b13e383`. Artifact digest confirmed from log and API; not independently downloaded/unpacked here.
- GCC and Clang each logged PASS: 435 checks, 3 claims, 1 claimed error, 2 typed reads, 2 modeled fallbacks, 2 modeled preparation markers, 5 reopens, AUTH0. Each completed the 5 semantic mutant gates in the pinned runner; ASan/UBSan, strict warnings. Focused first_error absent. No integrated native build by A3.

## Source changes and exact boundary

The existing actual selected DM ordered helper retains the same FIFO descriptor, joins ordinary preparation, reserves real storage credit before queue lock, revalidates exact selection/route/generation/cap/credit with one broker trylock, transfers ownership in place, cancels only an unissued verified tail on refusal, permits one ordinary fallback, and handles a claimed result terminally without postclaim ordinary fallback. This round adds the actual owner/trial/storage/bridge/session/epoch/closing guard to that same helper. The native caller remains hard false; host exercises the actual guarded helper positively using the frozen broker, owner, authority, storage and original LZ4/LZO codecs. Linux/DM/RCU, lower/upper and preparation are modeled. No fake authorization or storage credit. Native discarded-preparation time/bytes, actual ACK/redirty, durability and provenance are **not measured**. No new positive native compile-only invocation was established; the positive entry is source-linked host only. Existing native provider lookup/candidate-get stay off before speculative work.

The actual typed READ now returns the exact authoritative pin to its caller; `swapz_read` holds it through `swapz_copy_bio_accounted` and puts afterward even on copy error. The historical helper remains a wrapper for legacy host extraction. No changes to ordinary read path semantics intended.

Teardown sets the trial drain marker only after ordinary invariant checks, resets it on drain entry/resume, and tests registration, route/snapshot, storage/bridge allocations and readiness, release and capability debts before free. An outstanding exact closed owner session/epoch with EBUSY requires explicit proof of independent retry ownership. Native passes false because the frozen producer does not provide that proof; the dtr quarantines rather than dropping the identity/freeing context. This is intentionally fail-closed but can retain memory permanently; no guarantee of eventual native reclamation. No new target work, unbounded wait or self-pin. The host boundary detaches/clears the simulated context, releases the external cap, sees real frozen finish EBUSY with an outstanding ticket, releases ticket, and explicitly retries with the saved owner identity independently of target context, then reopens. This models the required future built-in retry contract; **not** evidence of autonomous retry in current built-in code. Tests cover deferred release, late revoke, scope and preparation refusal, write failure, pin across copy and exactly-once modeled completion.

Chosen bounded old bridge: 8 record/pin slots, 8 broker slots at M3568, 16 logical pages in snapshot, 64 non-reused bridge tokens/lifetime, one target release slot. No claim of new shared-gate integration or capacity gain. All staged dependencies pinned by the runner; see JSON. No peer source edits.

## Regression / CI status

Observed automatic exact-source census: {"queued":19,"in_progress":6,"success":4,"failure":1} out of 30 workflows. A source regression is already confirmed: [R092 ordered-owner job](https://github.com/k1moradi/swapz/actions/runs/45827740512/job/139936146060) failed before host compile, `ROUND091_FIRST_ERROR substring not found`. Its static check at lines 133–134 still searches the old `swapz_round091_read_original(` call in `swapz_read`, now replaced by the retained-pin helper. This is an uncorrected legacy verifier incompatibility, not a clean integrated result. The historical test must be updated to assert the new pin lifetime without weakening existing ordering checks. Other queued/in-progress jobs are not passed. No manual duplicate replay. Local Git DNS resolution failed; all compiler/sanitizer claims are from exact hosted job, not local builds.

## Native recorder and physical admission design only

Frozen A2 protocol mapping: capture/bind at MM capture and selected route; accept at FIFO enqueue, dispatch after prep join; preparation status and discarded CPU/bytes separately; reserve after storage reservation, claim/refuse under queue lock; cancel outside lock; fallback once; actual lower submit/complete lengths, flush, publish; pin, oracle, upper copy, pin release; clone/upper endio (actual MM observation separate); candidate release on deferred put, MM carrier release by MM owner; discard/quarantine, GC begin/end, cleanup after RCU and worker joins and zero debts. Mint scoped monotonic tokens, not pointers; do not introduce recorder allocation/hash/I/O/callback in queue-lock critical section. Loss invalidates observation; stop/seal after producers revoked/joined. No recorder implementation/integration claim.

A future physical admission requires separate owner authorization, current integrated source/compile review and approved bounded workload/oracle, exact inactive dedicated partition scope, exclusive device/host identity, immutable SWAPSPACE2 page0/UUID/table, mapper-only format, no parent/sibling writes, no forced removal. Proposed first finite scope uses M3568 and the bounds above, natural MM eviction only, no extra shrinker/timer/BIO, MemAvailable >=1 GiB, hard 240s, zero OOM/mismatch, conservative 85% PSI FULL/5s stop and <=10s no progress, existing accounting ceilings; exact workload needs separate approval. No physical I/O or device changes performed. Do not require successful first physical observations before permission for that first trial.

## Historical standards preservation

Engineering freeze blob `4152a1ce0c067ccb6b872f5f7aa0b89507ec8f2e` (1,856,114 bytes); actual source parent blob `adf7ec2fa261cd9c21edcbb179fdafad00621a56` (1,859,714 bytes); source postimage `d7b1502b2b2051978f384be4a8e2b2addeca5af1` (1,860,879 bytes). Actual complete parent prefix verified by exact blob round-trip and readback; append only 1,165 bytes. Evidence publication changes no standards bytes.

**Remaining:** resolve failed legacy verifier, complete exact-source CI, native positive bounded entry/actual preparation accounting, independently proved built-in close retry, native composition review. AUTH=0; Phase A BLOCKED; compressed handoff, forced RAW bypass and import OFF.

## Follow-up correction (after initial evidence snapshot)

[Correction 6025956f8e2d97f6036eb22e7b80a94075e3d1d4](https://github.com/k1moradi/swapz/commit/6025956f8e2d97f6036eb22e7b80a94075e3d1d4) changes only the failed legacy verifier and appends standards text. It keeps the typed-before-cache assertion and adds release-after-copy ordering, and defines the kernel unused annotation for isolated host compile. No DM or accepted R095 fixture modification. Exact current parent standards `ef9dfb936a96af9789488b530e33a287e1ffd128` (1865716 bytes) preserved byte-for-byte in `9c1ec8d4f8ac2b300c93fb07cff9f10e7f5e3046` (1866457 bytes); append 741 bytes. [Corrected legacy CI](https://github.com/k1moradi/swapz/actions/runs/45828552407) observed queued, conclusion not yet available. The original failed run remains recorded; a corrective commit is not a passing result. Round remains PROGRESS/BLOCKED. This evidence-only follow-up leaves all standards bytes unchanged.


## Agent1 independent terminal reconciliation
```json
{
  "source": "58b599346139dd9dbee4120030a23c84a14f03dc",
  "run": 45827740930,
  "job": 139936147434,
  "conclusion": "PASS_COMPOSED_HOST_ONLY",
  "artifact": 15121270263,
  "sha256": "d21d8de6e111e151859f8ba76a0b179d83a317f81f56508ede772bf44b13e383",
  "checks_each": 435,
  "claims_each": 3,
  "claimed_errors_each": 1,
  "typed_reads_each": 2,
  "fallbacks_each": 2,
  "preparations_each": 2,
  "reopens_each": 5,
  "mutants_each": 5,
  "exact_census": {
    "success": 29,
    "failure": 1
  },
  "legacy_failed_run": 45827740512,
  "correction": {
    "source": "6025956f8e2d97f6036eb22e7b80a94075e3d1d4",
    "run": 45828552407,
    "job": 139938953491,
    "artifact": 15122108402,
    "sha256": "a82e6208122bb702fb1cd3114b1a9724763b6df45d387d80b0d9923554fd75fb",
    "conclusion": "PASS",
    "exact_census": {
      "success": 10
    },
    "legacy_replay_checks_each": 12708,
    "actual_source_negative_groups": 30
  },
  "scope": "Retained pin through upper copy, actual target_can_free(ctx,false) native path still refuses independent retry; old bridge remains; owner retry host boundary modeled. Native gate hard false. Legacy correction accepted separately, not extra new transaction credit."
}
```
