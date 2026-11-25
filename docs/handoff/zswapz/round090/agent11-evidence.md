# Round090 Agent11 — producer RCU lifetime and bounded sparse-cache effectiveness

**IN_PROGRESS_HOST_ONLY_UNAPPLIED_LIFETIME_OVERLAY / NO-GO live.** [Assignment](https://github.com/k1moradi/swapz/blob/edf44c4417f14b5836b1b5f90157e24916afcde2/docs/handoff/zswapz/round090/agent11-producer-lifetime-budget-p0.md), frozen baseline `9f7002c896f86226e93f0523b1f6e935de5c6de9`. [Source commit](https://github.com/k1moradi/swapz/commit/0131ab0a93f6708ab7de4a21f3cbd35efe05de53), sole actual parent `3f0f52f8f07692d3b2e5614bc58bdae3ceadaff8`, verified fresh expected-head nonforce FF. Earlier unpublished attempt stopped when main advanced, reconstructed only owned paths and standards append. Five changed paths, prior standards blob b3d32260fcd0cc4cb877fc06e3802b5130709678, new 8f69e16dbdb64bfdbaaa5729d7b2939f7c8fb8c7, exact prefix verified. R089 accepted corrected 700+700/32+32 preserved, not rerun. Local git ls-remote exit128 DNS unable to resolve github.com; no native checkout or local execution claimed. Prepublication Python-dict parsing and full-patch wrong old-line anchor were rejected; corrected via exact staged overlay before ref update.

## Actual correction and remaining contract

[Reviewable overlay](https://github.com/k1moradi/swapz/blob/0131ab0a93f6708ab7de4a21f3cbd35efe05de53/tests/tools/round090-original-mm-lifetime.patch): 17 hunks against immutable R089 staged postimages, six changed staged files, seventh unchanged. Connector independently reconstructed all seven R089 postimage hashes from the six actual original source blobs and new header, verified all modified pristine pins, then calculated seven exact overlay postimages. Actual git apply in fresh CI pending. Original Linux pin c339f4010dea8b0d754f84ace70cd1b089878ef8; no upstream publication or production Kbuild. 

R089 candidate_get reads nonowning carrier and then retains its ticket; original SIO terminal may drop the sole owner and schedule release/reuse. A BIO reference alone does not establish the carrier's lifetime. This overlay annotates the BIO borrow __rcu, uses RCU publication and NULL invalidation in all 11 existing clear sites (init/uninit/reset/reuse through native helpers, clone/reissue/advance/set_dev/chain/split/trim/endio), and protects the actual candidate_get through ticket retain. Deferred release worker waits for an RCU grace period on an attached carrier before ticket put, cap put and release of busy. Unattached decline does not wait. Existing quarantine on put failure retained. No wait in original BIO completion or dtr, no new allocation, no second BIO, no global BIO cap; only the optional static carrier remains busy longer. The caller MUST still own live mapping and stable original BIO geometry/folio/device, not just a reference to the BIO; RCU does not pin SIO/page/bdev. Generic clones remain empty. Native kernel build/lockdep/RCU workqueue and terminal ordering not qualified.

Provider register/unregister audit: immutable provider pointer published under mutex, RCU read side callback, capability retained before read unlock, unregister clears and synchronizes before returning. Existing callback owner must pin code/broker through unregister grace; callback cannot sleep/allocate/call broker or leave target locks held; independent cap/ticket pins protect broker only, no raw target escape. Broker destroy needs external entrant quiescence in addition to zero refs/caps; no implementation proof of real target/module ownership yet, default absent provider hard refusal. Swap area epoch and cookie identity checks remain, no new pressure machinery. Source capture still exact compressor output CRC and original full-page SHA, route codec/length eligibility and cell acquisition before hashes, no missing-provider/ineligible hash. Preserve digest until eviction verification rather than defer unsafely: computing SHA only at eviction would remove comparison with actual stored page. Source generation nonwrap; collision/contention declines. M3568/M4095 remain separate, original full-page native fallback/RAW_4096 untouched.

## Budget and sparse retention

Prior accepted measured host source72, cookie8, cap24, carrier4176, broker160; 64 cells estimated 80B kernel each =5120B, plus prior host carrier4176 =9296B indicative fixed before other globals/alignment/broker arrays; actual slab/peak memory unknown. Nominal per-entry saving vs R088 key112B; 8B per entry retained (8MiB per 1,048,576 entries). No new per-entry field or extra carrier introduced. Grace period may increase optional busy duration, reducing optimization rate, not ordinary writes. Per eligible store CRC <=4095 bytes plus SHA4096; eviction copies/checks exact stream plus SHA4096, no recompression. CPU and natural reclaim hit rate unmeasured.

Current low-six-bit direct mapping replaces a credential after 64 subsequent contiguous successful stores. Deterministic trace proposed: 1024 stores per lag, lookups only once sequence > lag; expected hits/attempts: lag0 1024/1024; lag32 992/992; lag64 0/960; lag256 0/768. These are analytical expected values, not executed results. Actual exact helper trace plus host process CPU time requested in CI; does not measure real Linux LRU, contention, SHA, or slab. No arbitrary sampling or eviction policy change adopted without natural-eviction data. For sustained large working sets the cache may be nearly ineffective despite bounded metadata; preserve fallback.

## CI and scope

[Focused job](https://github.com/k1moradi/swapz/actions/runs/45586374203/job/139108905510) QUEUED at inspection, exact source SHA; no artifact or actual counts yet. New [verifier](https://github.com/k1moradi/swapz/blob/0131ab0a93f6708ab7de4a21f3cbd35efe05de53/tests/tools/round090-original-mm-lifetime-verify.py) verifies 15 pristine pins, both seven-postimage stages, duplicate/reverse checks, RCU publication/terminal/route/hash source-order guards and invokes only changed helper tests. [Fixture](https://github.com/k1moradi/swapz/blob/0131ab0a93f6708ab7de4a21f3cbd35efe05de53/tests/runtime/native/fixtures/round090-original-mm-lifetime.c) exact extracted candidate_get/release_workfn, actual unchanged broker/CRC, POSIX reader/writer RCU ABI shim. Sequential candidate pin/terminal release, one deterministic reader versus deferred-release race, retained bytes through revoke/close/destroy, two compiled semantic negatives (missing read protection/grace), deterministic sparse traces; strict GCC/Clang ASan/UBSan. No actual Linux RCU/SG/BIO/workqueue or selected DM execution. Native build NOT_RUN; no actual compiler/mutant/race/trace counts claimed pending CI. First CI error none observed, not success. Nine automatic runs registered including eight inherited lanes (A9 owns routing), no manual dispatch/cancellation, unchanged rerun, VM qualification, physical mutation or periodic monitoring.

## Immutable source pins

- tests/tools/round090-original-mm-lifetime.patch `337f7ff29e72d955251de0c54a9349f20c2586ec`
- tests/runtime/native/fixtures/round090-original-mm-lifetime.c `a6d761368ebbe6610ddf13bd5d176e6d64fa9ef5`
- tests/tools/round090-original-mm-lifetime-verify.py `f0c32cc54fca7b875f80a2baf2906adaa7f03834`
- .github/workflows/phase-a-round090-original-mm-lifetime-host-noauth.yml `4d57f7d8e9362af1fdda67ebdea45599b406e11a`
- src/kernel/zswap-original-ticket.h `2f850b53708c8142ee95d330192c9db1f9ae9418`
- src/kernel/zswap-original-ticket.c `66df826d86dde1bbd5e1967daa0e62517b58ac8d`
- tests/tools/round089-original-mm-carrier.patch `059d1bf29cf4990e22a2f608d5d552abeec3a8d1`
- tests/tools/round089-original-mm-carrier-verify.py `dce6b2417ea33b598eaf00accf7888730b2e4a54`

Predicted corrected overlay postimages:
- mm/zswap.c `cbf160877e8d8b584d6010c009a3e500f8b99f38`
- include/linux/swap_ops.h `a39a1921daf6f272e9812eb63b1aa64fec96c57f`
- include/linux/blk_types.h `50c94617b08e581021ba25fa6e182a5b88ecfa43`
- include/linux/bio.h `4079365b37690164f85ba962a0bd0918c85899cb`
- block/bio.c `38f24ee2e414107be390d3a01c6b907e06a9dca7`
- mm/page_io.c `c3bd481117dbd29edd821df452f74990d6d5f00a`
- include/linux/swapz_mm_carrier.h `f170d2c2ac63679adb0885f746585ed77c2746a5`

NO-GO live until provider/module lifetime, actual kernel compile/link, stable selected mapping and native lifecycle, exact lock graph, realistic sparse/CPU/slab budget, durable lower write and exactly-once upper ACK proven. AUTH=0 Phase A BLOCKED direct compressed handoff/forced RAW bypass/import OFF. No physical or owner test requested. 20B map, SWAPSPACE2 page0/UUID/table untouched.
