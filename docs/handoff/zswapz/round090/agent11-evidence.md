# Round090 Agent11 — producer RCU lifetime and bounded sparse-cache effectiveness

**PASS_HOST_ONLY_UNAPPLIED_LIFETIME_OVERLAY / NO-GO live.** [Assignment](https://github.com/k1moradi/swapz/blob/edf44c4417f14b5836b1b5f90157e24916afcde2/docs/handoff/zswapz/round090/agent11-producer-lifetime-budget-p0.md), frozen baseline `9f7002c896f86226e93f0523b1f6e935de5c6de9`. [Source commit](https://github.com/k1moradi/swapz/commit/0131ab0a93f6708ab7de4a21f3cbd35efe05de53), sole actual parent `3f0f52f8f07692d3b2e5614bc58bdae3ceadaff8`, verified fresh expected-head nonforce FF. Earlier unpublished attempt stopped when main advanced, reconstructed only owned paths and standards append. Five changed paths, prior standards blob b3d32260fcd0cc4cb877fc06e3802b5130709678, new 8f69e16dbdb64bfdbaaa5729d7b2939f7c8fb8c7, exact prefix verified. R089 accepted corrected 700+700/32+32 preserved, not rerun. Local git ls-remote exit128 DNS unable to resolve github.com; no native checkout or local execution claimed. Prepublication Python-dict parsing and full-patch wrong old-line anchor were rejected; corrected via exact staged overlay before ref update.

## Actual correction and remaining contract

[Reviewable overlay](https://github.com/k1moradi/swapz/blob/0131ab0a93f6708ab7de4a21f3cbd35efe05de53/tests/tools/round090-original-mm-lifetime.patch): 17 hunks against immutable R089 staged postimages, six changed staged files, seventh unchanged. Connector independently reconstructed all seven R089 postimage hashes from the six actual original source blobs and new header, verified all modified pristine pins, then calculated seven exact overlay postimages. Actual scratch-only git apply, hash/pin and source-order qualification PASS in terminal CI; untouched original pinned checkout. Original Linux pin c339f4010dea8b0d754f84ace70cd1b089878ef8; no upstream publication or production Kbuild. 

R089 candidate_get reads nonowning carrier and then retains its ticket; original SIO terminal may drop the sole owner and schedule release/reuse. A BIO reference alone does not establish the carrier's lifetime. This overlay annotates the BIO borrow __rcu, uses RCU publication and NULL invalidation in all 11 existing clear sites (init/uninit/reset/reuse through native helpers, clone/reissue/advance/set_dev/chain/split/trim/endio), and protects the actual candidate_get through ticket retain. Deferred release worker waits for an RCU grace period on an attached carrier before ticket put, cap put and release of busy. Unattached decline does not wait. Existing quarantine on put failure retained. No wait in original BIO completion or dtr, no new allocation, no second BIO, no global BIO cap; only the optional static carrier remains busy longer. The caller MUST still own live mapping and stable original BIO geometry/folio/device, not just a reference to the BIO; RCU does not pin SIO/page/bdev. Generic clones remain empty. Native kernel build/lockdep/RCU workqueue and terminal ordering not qualified.

Provider register/unregister audit: immutable provider pointer published under mutex, RCU read side callback, capability retained before read unlock, unregister clears and synchronizes before returning. Existing callback owner must pin code/broker through unregister grace; callback cannot sleep/allocate/call broker or leave target locks held; independent cap/ticket pins protect broker only, no raw target escape. Broker destroy needs external entrant quiescence in addition to zero refs/caps; no implementation proof of real target/module ownership yet, default absent provider hard refusal. Swap area epoch and cookie identity checks remain, no new pressure machinery. Source capture still exact compressor output CRC and original full-page SHA, route codec/length eligibility and cell acquisition before hashes, no missing-provider/ineligible hash. Preserve digest until eviction verification rather than defer unsafely: computing SHA only at eviction would remove comparison with actual stored page. Source generation nonwrap; collision/contention declines. M3568/M4095 remain separate, original full-page native fallback/RAW_4096 untouched.

## Budget and sparse retention

Prior accepted measured host source72, cookie8, cap24, carrier4176, broker160; 64 cells estimated 80B kernel each =5120B, plus prior host carrier4176 =9296B indicative fixed before other globals/alignment/broker arrays; actual slab/peak memory unknown. Nominal per-entry saving vs R088 key112B; 8B per entry retained (8MiB per 1,048,576 entries). No new per-entry field or extra carrier introduced. Grace period may increase optional busy duration, reducing optimization rate, not ordinary writes. Per eligible store CRC <=4095 bytes plus SHA4096; eviction copies/checks exact stream plus SHA4096, no recompression. CPU and natural reclaim hit rate unmeasured.

Current low-six-bit direct mapping replaces a credential after 64 subsequent contiguous successful stores. Deterministic trace proposed: 1024 stores per lag, lookups only once sequence > lag; expected hits/attempts: lag0 1024/1024; lag32 992/992; lag64 0/960; lag256 0/768. These predicted values were verified by actual strict host trace execution for both compilers. Actual exact helper trace and host process CPU timing executed in CI; does not measure real Linux LRU, contention, SHA, or slab. No arbitrary sampling or eviction policy change adopted without natural-eviction data. For sustained large working sets the cache may be nearly ineffective despite bounded metadata; preserve fallback.

## CI and scope

[Focused job](https://github.com/k1moradi/swapz/actions/runs/45586374203/job/139108905510) terminal SUCCESS on exact source SHA; GCC 30/30 checks and Clang 30/30, one synthetic external-lock lifecycle race each, semantic negatives `no_reader` and `no_grace` both rejected by both compilers (4/4). [Retained artifact](https://github.com/k1moradi/swapz/actions/runs/45586374203/artifacts/15009155737) metadata: 13 files, 2691 bytes, sha256 `b7b65f4e11e6e97e6c0d5f8f567a2aa5fba40237e20af9d2bc1f6131f080027b`, expiry 2026-12-09T09:33:26Z, archive not independently extracted. New [verifier](https://github.com/k1moradi/swapz/blob/0131ab0a93f6708ab7de4a21f3cbd35efe05de53/tests/tools/round090-original-mm-lifetime-verify.py) verifies 15 pristine pins, both seven-postimage stages, duplicate/reverse checks, RCU publication/terminal/route/hash source-order guards and invokes only changed helper tests. [Fixture](https://github.com/k1moradi/swapz/blob/0131ab0a93f6708ab7de4a21f3cbd35efe05de53/tests/runtime/native/fixtures/round090-original-mm-lifetime.c) exact extracted candidate_get/release_workfn, actual unchanged broker/CRC, POSIX reader/writer RCU ABI shim. Sequential candidate pin/terminal release, one deterministic reader versus deferred-release race, retained bytes through revoke/close/destroy, two compiled semantic negatives (missing read protection/grace), deterministic sparse traces; strict GCC/Clang ASan/UBSan. No actual Linux RCU/SG/BIO/workqueue or selected DM execution. Native build NOT_RUN; actual host checks 60, lifecycle races 2, semantic kills 4, deterministic traces four lags per compiler, first CI test error none. gcc trace CPU 0.000731s, clang trace CPU 0.000888s; tiny synthetic measurement, not kernel CPU cost. Nine automatic runs registered including eight inherited lanes (A9 owns routing), no manual dispatch/cancellation, unchanged rerun, VM qualification, physical mutation or periodic monitoring.

## Immutable source pins

- tests/tools/round090-original-mm-lifetime.patch `337f7ff29e72d955251de0c54a9349f20c2586ec`
- tests/runtime/native/fixtures/round090-original-mm-lifetime.c `a6d761368ebbe6610ddf13bd5d176e6d64fa9ef5`
- tests/tools/round090-original-mm-lifetime-verify.py `f0c32cc54fca7b875f80a2baf2906adaa7f03834`
- .github/workflows/phase-a-round090-original-mm-lifetime-host-noauth.yml `4d57f7d8e9362af1fdda67ebdea45599b406e11a`
- src/kernel/zswap-original-ticket.h `2f850b53708c8142ee95d330192c9db1f9ae9418`
- src/kernel/zswap-original-ticket.c `66df826d86dde1bbd5e1967daa0e62517b58ac8d`
- tests/tools/round089-original-mm-carrier.patch `059d1bf29cf4990e22a2f608d5d552abeec3a8d1`
- tests/tools/round089-original-mm-carrier-verify.py `dce6b2417ea33b598eaf00accf7888730b2e4a54`

CI-verified corrected overlay postimages:
- mm/zswap.c `cbf160877e8d8b584d6010c009a3e500f8b99f38`
- include/linux/swap_ops.h `a39a1921daf6f272e9812eb63b1aa64fec96c57f`
- include/linux/blk_types.h `50c94617b08e581021ba25fa6e182a5b88ecfa43`
- include/linux/bio.h `4079365b37690164f85ba962a0bd0918c85899cb`
- block/bio.c `38f24ee2e414107be390d3a01c6b907e06a9dca7`
- mm/page_io.c `c3bd481117dbd29edd821df452f74990d6d5f00a`
- include/linux/swapz_mm_carrier.h `f170d2c2ac63679adb0885f746585ed77c2746a5`

NO-GO live until provider/module lifetime, actual kernel compile/link, stable selected mapping and native lifecycle, exact lock graph, realistic sparse/CPU/slab budget, durable lower write and exactly-once upper ACK proven. AUTH=0 Phase A BLOCKED direct compressed handoff/forced RAW bypass/import OFF. No physical or owner test requested. 20B map, SWAPSPACE2 page0/UUID/table untouched.

## Terminal CI reconciliation — evidence-only, no new dispatch

Exact job `139108905510` on source `0131ab0a93f6708ab7de4a21f3cbd35efe05de53` completed SUCCESS. Its canonical preflight matched actual `github.event.before` `3f0f52f8f07692d3b2e5614bc58bdae3ceadaff8`, sole parent, clean SHA, `git diff --check`, and mandatory repository policy. Existing verifier staged original pinned Linux c339f4010dea8b0d754f84ace70cd1b089878ef8 and R089 overlay in scratch, exact postimage pins and source-order checks passed. Kernel compile/link, live kernel RCU, native BIO, lockdep, physical tests all NOT_RUN. Source and test commits unchanged; no duplicate CI.

Actual bounded job markers:

```text
gcc PASS_HOST_ONLY R090 checks=30 lifecycle_races=1 immediate=1024 lag32=992 lag64=0 lag256=0 source=72 carrier=4176 broker=160 trace_cpu_seconds=0.000731000
gcc semantic kill no_reader
gcc semantic kill no_grace
clang PASS_HOST_ONLY R090 checks=30 lifecycle_races=1 immediate=1024 lag32=992 lag64=0 lag256=0 source=72 carrier=4176 broker=160 trace_cpu_seconds=0.000888000
clang semantic kill no_reader
clang semantic kill no_grace
PASS_HOST_ONLY R090 staged producer lifetime + sparse trace; kernel NOT_RUN AUTH0
```

The 64-entry direct-map cache is worst-case ineffective for sequential lag >=64 and one static carrier plus grace can throttle only the optimization, not ordinary native fallback. Host trace timings exclude hashing/natural eviction/system contention. This is strictly GO for dormant source review, NO-GO for activation: full provider code pin/module/broker external entrant quiescence, native object/folio/bdev stability, exact original kernel compile/link, real selected clone and lock-order proof, lower durability and once-only ACK are outstanding. No physical, new VM, branch, PR, force push, manual rerun or periodic monitor. AUTH=0 Phase A BLOCKED compressed handoff/forced RAW/import OFF.


## Agent1 independently verified reconciliation
Agent1 independently extracted artifact15009155737 results.json, SHA256 b7b65f4e11e6e97e6c0d5f8f567a2aa5fba40237e20af9d2bc1f6131f080027b. Actual15 pristine/7 baseline/7 overlay pins, host30+30 checks,1+1 races,2+2 semantic kills; lag0 1024/1024, lag32 992/992, lag64 0/960, lag256 0/768 each. Host trace is not natural reclaim; zero long-lag hit rate is an architectural utilization warning. R091 prioritize compact source identity with eligible preerase digest derivation, no store-time sparse-cache residency dependence if proven; no unbounded RAM expansion, no extra reclaim path.
