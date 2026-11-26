# Round 095 — Agent 3: composed ordered transaction

Status: **PASS_COMPOSED_HOST_ONLY / NO_GO_LIVE**. AUTH=0; Phase A BLOCKED; compressed handoff, forced RAW bypass and import OFF.

## Frozen input and prior evidence

- [ROUND_OPEN](https://github.com/k1moradi/swapz/issues/213#issuecomment-7184043926); task commit `20122e158beef6266bd01bb545951a2a4f77d9d5`; freeze `ff972661a75ca7f8c3c0458c3feb8b603c185eb8`; original Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`.
- [R094 corrected source](https://github.com/k1moradi/swapz/commit/d620a2533ae26f109921fdff48ce28b2b05116b5), [focused job](https://github.com/k1moradi/swapz/actions/runs/45761622515/job/139712711603), [artifact](https://github.com/k1moradi/swapz/actions/runs/45761622515/artifacts/15090198553): exact source census 29/29 successful; GCC and Clang each 50 checks and six semantic mutants killed. No manual replay.
- Frozen R092 broker overlay `62db468c14f23b59e7adaae65a11dcb9969f02b3`, R094 owner overlay `e33bb8451210f9e1a97eb6d9bc0423f6b13a2edd`, owner implementation `0eda8753b91d3209c55f65eb90014fd9b8c6ad7c`, staged broker C/H `ba5e891ef7f80bf0b3021ee6c676529cb72f1972`/`c7f4ff59c11ee3475e7577dcc62f7c8db5a578ea`. No same-round peer implementation dependency.

## Reconciled existing source and preserved failure

Existing Agent 3 composition [ca3df00ddb22ce04c8eb064f1b82b1618e67e31c](https://github.com/k1moradi/swapz/commit/ca3df00ddb22ce04c8eb064f1b82b1618e67e31c) appeared on main during independent preparation. Stopped competing publication; reused existing fixture/runner rather than creating a duplicate lane. Exact census 27 successful / 3 failed of 30. [Composed job 139744955598](https://github.com/k1moradi/swapz/actions/runs/45771499496/job/139744955598) failed GCC baseline compilation at extracted target-fragments.h:1:65: ctx shadows fixture global under -Werror=shadow. Full diagnostic also identifies compressed/output global shadowing. [Artifact 15094292631](https://github.com/k1moradi/swapz/actions/runs/45771499496/artifacts/15094292631) downloaded and independently ZIP-integrity/hash checked: 1795 bytes, SHA-256 `49a47d46767bba5d37bf2c0e220fccd7c4d2dc4ee67a5043fb2093ea4586f908`, 54 frozen files, actual fragment SHA-256 `b940c358727355ff34b04065429dbdd73e0f4e54f6e1b1f5926a8661109553a6`, compilers empty; no executed transaction count.

[Product run 45771499293](https://github.com/k1moradi/swapz/actions/runs/45771499293) exact-C ARM and x86 failed source-contract-test.py:6618: stale two-argument process_candidate substring; compile-only both passed. [Project-goal run 45771499729](https://github.com/k1moradi/swapz/actions/runs/45771499729) rootless/source-contract failed. Preserve red evidence, no unchanged rerun.

## Correction

[Source 4b15bdf4f841195ed240243a81ed13eaad7cf396](https://github.com/k1moradi/swapz/commit/4b15bdf4f841195ed240243a81ed13eaad7cf396), sole parent `7b1a17438f29bf081b5bd46931ef27dbf3bd9d74`. Rename only fixture-global identifiers that shadow actual extracted target functions; retain strict compiler warning policy. Update existing source regression to require the single native call's explicit hard-false permission and order before ordinary acceptance. Add five-line teardown guard: if owner close errors or deferred release is busy, preserve storage and return error/-EBUSY; host fixture intentionally invokes teardown with release pending, then joins the actual release worker, exercises external-cap busy finish, puts the cap, retries and reopens. Fourth mutant removes pending-release check. Existing composition directly calls real broker-owner lifecycle, extracted actual target generation/registration/retain/claim/commit/release/read/teardown and real frozen authority/storage/decoder plus original Linux LZ4/LZO1X. Positive permission confined to generated host fixture; native caller hard false. Provider lookup and candidate acquisition decline before speculative capture when claim OFF. No extra ordinary preparation after successful claim in fixture. No second native build by Agent 3.

At the earlier pending checkpoint, planned (not yet observed): 11 scenarios; five claims including three terminal errors; two typed reads; six ordinary fallback/preparation markers; eleven reopens; four mutants per compiler. [Corrected composed run 45785010481/job 139789467324](https://github.com/k1moradi/swapz/actions/runs/45785010481/job/139789467324): was running at the earlier inspection; exact source/complete historical prefix preflight had passed. Terminal results follow below. [Product run](https://github.com/k1moradi/swapz/actions/runs/45785010465), [project-goal run](https://github.com/k1moradi/swapz/actions/runs/45785010290), [ordered host](https://github.com/k1moradi/swapz/actions/runs/45785010453), [target owner](https://github.com/k1moradi/swapz/actions/runs/45785010503) are automatic new-source runs, not manual duplicate dispatches.

Complete actual publication-parent standards prefix verified by blob round-trip, byte count and readback: 1,852,756 -> 1,853,423 bytes, +667 only. Before `e362e2772de763ca1f3245df0a6c50d0b32b66a5`; after `aa0e89c9153b4936447676df13953449fb73d873`. Expected-head nonforce fast-forward verified. No branches/PRs/force/VM/module load/physical mutation.

## Boundaries and physical-development design

Host substitutes Linux synchronization/workqueue primitives, selected BIO identity, RAM lower I/O, ordinary dispatch and upper completion. Actual allocator/record and decoder bytes are exercised, not proof of native provenance or device durability. External outstanding refs after final native dtr remain a quarantined lifetime requiring qualified recovery; current guard avoids dismantling while release remains busy, not proof of universal reclamation. Native live typed writes remain OFF. Local Git checkout unavailable (DNS resolution failure); no local compile/diff-check result claimed. Physical development remains a design: retain null_blk-only admission; require separate authorization, exact host/device scope, protected partition identity/header, bounded observation, drained lifetime proof and safe recovery before any physical trial. Agent 10 owns the single integrated native compile-link. No activation requested or performed.

## Terminal reconciliation — existing corrected source, no replay

The corrected [source 4b15bdf4f841195ed240243a81ed13eaad7cf396](https://github.com/k1moradi/swapz/commit/4b15bdf4f841195ed240243a81ed13eaad7cf396), sole parent `7b1a17438f29bf081b5bd46931ef27dbf3bd9d74`, now has **30/30 successful exact-head workflows**, zero pending/failed, including [composed host job](https://github.com/k1moradi/swapz/actions/runs/45785010481/job/139789467324), [product](https://github.com/k1moradi/swapz/actions/runs/45785010465) (both x86_64/arm64 exact-C and compile-only), [project goals/source contract](https://github.com/k1moradi/swapz/actions/runs/45785010290/job/139789467463), [ordered host](https://github.com/k1moradi/swapz/actions/runs/45785010453/job/139789467658) and [target-owner host](https://github.com/k1moradi/swapz/actions/runs/45785010503/job/139789467461). The composed job's exact HEAD, actual push parent, diff check and complete raw historical standards-prefix preflight all passed. This is a source-specific census, not whole-main/native-runtime certification.

Downloaded [artifact 15100256797](https://github.com/k1moradi/swapz/actions/runs/45785010481/artifacts/15100256797) independently; 793 bytes, ZIP CRC/integrity PASS, SHA-256 `c637d8cfdf0685f7df800aa1bc1d8ccc1e735902b45d3d43449cc08f172f2d32` matches Actions metadata and job log. Contained results.json binds tested source, frozen inventory 54, extracted fragment SHA-256 `43657e523b486a983980cd269ccc6a321b650821c050a176e1b420b2fc4fbf78`. GCC C2x and Clang C23 each executed 673 semantic checks, five claims (three terminal claimed errors), two typed reads, six modeled fallback and preparation markers, eleven reopens, four semantic mutants rejected (not sanitizer crashes). Both use ASan/UBSan; fixture strict warnings include -Wconversion/-Wshadow/-Werror. Mutants: live permission, registration incarnation, prepared owner, pending-release checks. Corrected first error: none; preserve original failed compile and source-contract history above. No new CI run, no new fixture or native retry.

Host-only result: actual frozen broker/owner, extracted target, storage/authority and original decoder linked; modeled Linux primitives, RAM lower, BIO identity, ordinary dispatch and completion. The six preparation markers are not measured native prep CPU or actual lower service. External-reference final destructor quarantine/reclamation remains unqualified. No native BIO provenance, actual device durability, physical scope or live admission evidence; Agent10 alone owns native integrated compile-link. AUTH=0; Phase A BLOCKED; compressed handoff, forced RAW bypass and import OFF. The evidence-only update changes neither implementation nor testing_standards.md. No same-round peer engineering inputs.


## Agent1 independent terminal reconciliation
```json
{
  "source": "4b15bdf4f841195ed240243a81ed13eaad7cf396",
  "run": 45785010481,
  "job": 139789467324,
  "conclusion": "PASS_COMPOSED_HOST_ONLY",
  "artifact": 15100256797,
  "sha256": "c637d8cfdf0685f7df800aa1bc1d8ccc1e735902b45d3d43449cc08f172f2d32",
  "checks_each": 673,
  "claims_each": 5,
  "claimed_errors_each": 3,
  "typed_reads_each": 2,
  "modeled_fallbacks_each": 6,
  "modeled_preparations_each": 6,
  "reopens_each": 11,
  "mutants_each": 4,
  "inventory": 54,
  "exact_census": {
    "success": 30
  },
  "scope": "Actual extracted target/owner/broker/storage and original codecs. Host Linux/DM/RCU/lower/upper completion modeled; actual sole native caller hard false; no final busy-owner retry proof."
}
```
