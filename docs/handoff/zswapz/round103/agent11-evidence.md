# R103 A11 — original swap-area and external terminal joins

**SOURCE_PUBLISHED / QUALIFICATION_PENDING.** Not connected or native acceptance. Agent1 owns integration and final acceptance.

## Immutable source
Issue #221; task c036b9456a03236841274ca2f3f3980c2dc07502; freeze e65d7042b41880c6fef99069d7f65bf6fb4356d4, tree 23a94d1726859c3536e16efd7de5212a68af6531; Linux c339f4010dea8b0d754f84ace70cd1b089878ef8. [Source commit 6a2085050de913ff239e034ff645fbc687a1cb58](https://github.com/k1moradi/swapz/commit/6a2085050de913ff239e034ff645fbc687a1cb58); sole fresh publication parent ab9b2d11b931fa850432fcf188e19b9001eae25e; tree b759161a522ad43ffde5b368b7a74fc2b86c7b22. Main-only nonforce expected-head update/readback verified. Publication parent contains concurrent independent work; no peer R103 source consumed. Complete historical standards raw prefix reconstructed at blob 989a87d9788edbf1ecb6319860b5b71f978ca035 and appended readback verified.

- `tests/tools/round103-original-area-terminal-join.patch` — `5c5e52add5976a96987de22d12cdaacad332f142`
- `tests/tools/round103-external-join-verify.py` — `d6ea4b20517172bc09c64f7d7d27d78640869bad`
- `tests/runtime/native/fixtures/round103-external-join.c` — `11f7d56a8d934118f633f49dfe10898262b9ad50`
- `.github/workflows/phase-a-round103-external-join-noauth.yml` — `aa708cbd79e566d879219d4403f3d27f6b2a7955`
- `docs/testing_standards.md` — `2c9d0d4e55130965057a968a349a8da3fc1d76fa`

## Actual source changes and boundaries

- Original swapfile cold lookup: real active allocator list under swap_lock, SWP_WRITEOK, exact direct block swap_bdev_ops, exact mapper file mapping/bdev, aligned nonheader bounded range within actual area max, actual nonzero epoch. Returns independent owned swap-file reference. Publication rechecks exact epoch under shared terminal gate after cap acquisition, stale rollback and fail-closed cap-put quarantine. No generic setter or activation.
- Actual _enable_swap_info publication/reinsertion mints epoch. Swapoff invalidates before write withdrawal, successful native retirement hook after allocator wait, try_to_unuse, percpu users kill/RCU/completion, discard/reclaim work, extents and zswap teardown. Failed swapoff reinsertion or same-type reopening while scope retained is a sticky fault. Area retirement is deliberately mandatory for the proposed external witness; no claim that a still-active area is quiescent.
- Carrier busy CAS joined to capture RCU gate; a pre-stop entrant remains real debt. MM SIO accounting starts at allocation before submission, persists through synchronous and asynchronous completion, detach before free, put only after writeback/redirty or read unlock and actual SIO free. Deferred carrier release remains separate busy debt. Bounded permanent 192-slot debt state (up to three debts per 64 operations, not extra operation capacity); monotonically allocated exact ticket/kind, no pointer-derived exported ID, pointer only live owner lookup. Exact detach before callback/free prevents address reuse consuming an old ticket; overflow/wrong completion faults qualification.
- DM original callback wrapper installed at actual dm_submit_bio before table SRCU acquisition, separate entrant ticket through SRCU put. Original callback/private data preserved, debt released after callback exits without reading freed BIO; reissued original retains existing callback/token. Split parent completion remains owed, unsupported cloned/remapped shape never replaces chain callback and poisons qualification. Refusal and deferred paths share actual original completion, no new ACK emitted. Ordinary observation one-shot per tracked original, frozen recorder bool API unchanged. Native callback interposition and unsupported shape handling require hosted and later connected review; no runtime/native proof inferred.
- Lock order swap_lock/si lock or scope mutex -> terminal IRQ gate. No gate -> broker, recorder, target or callback acquisition; no mutex/spin held over grace or callback. Join is retryable, exact session/table/target/scope identity, capture stopped, actual retired area, closed admission plus grace, debt and busy zero. -EBUSY for debt/transition/not retired, -ESTALE for wrong/absent identity, -EUCLEAN sticky accounting/reopen fault; retained file/cap/observation survives failed join. Final revoke requires exact witness and rechecks ready atomically with unpublication. Target map/worker/provider/retained candidate and broker retirement remain separate mandatory joins, not a fabricated aggregate. Scope is one-shot; no real operations or physical authority.

## Proposed integration ABI (guarded, source only)

- `int swapz_mm_trial_area_get(struct file *mapper_file, sector_t first, sector_t count, u32 *type, u64 *epoch, struct file **area_file)`
- `u64 swapz_mm_trial_area_epoch(u32 type)`
- `int swapz_mm_trial_scope_join_external(u64 identity, u64 session, u64 table_epoch, u64 target_epoch)`
- `void swapz_mm_trial_mm_enter(struct block_device *bdev, u32 type, const void *sio)`
- `u64 swapz_mm_trial_mm_take(const void *sio)`
- `void swapz_mm_trial_mm_put(u64 ticket)`
- `u64 swapz_mm_trial_dm_enter(struct bio *bio)`
- `void swapz_mm_trial_dm_leave(u64 entrant)`
- `bool swapz_mm_trial_dm_origin(const struct bio *bio, sector_t sector)`

Caller of area_get must fput returned actual area file; publication independently obtains its own ref. Existing stop_capture/revoke signatures retained; under new guard revoke refuses without external join. Controller must separately stop target admission and join target/provider debt, then final revoke and exact old broker retirement before sealing/reuse. No new A2 ordinal or A3 controller call consumed.

## Staged identities

| Path | Exact reconstructed preimage | Predicted postimage |
|---|---|---|
| `mm/zswap.c` | `fcb2f7487cb7ed02ae8ca9a8d486909f721a2ef6` | `833f089bc01e8803f427732975d706c894436eb3` |
| `mm/page_io.c` | `08c11d2f9a16a322093b305afa10ba011f67fc2b` | `5c3ebb46e2d885b0d3ab492a796996c004954d79` |
| `mm/swapfile.c` | `254ce86fa923e6b5f1fefda88c39315c4cc00642` | `031a93193886b093045e4aa15456016da49a7a43` |
| `drivers/md/dm.c` | `f0c0cd4add03bf2b6f9bf37997444ecd08bbb83b` | `e07dfd963edcdfb438af2ae1f43e3023e54544b7` |
| `include/linux/swapz_mm_carrier.h` | `f50911d4c1ff7f87b502cec042b90968ba3a282f` | `7091e456b6c09f29d68140cfff3f072e940ccd2f` |
| `include/linux/swapz_trial_debt.h` | `absent` | `207cd1b7a87f493992938cfa00ed4f95c7196811` |
| `mm/swapz-trial-terminal.inc` | `absent` | `3f980d04958676c22d44a6ca2778c4bd40a464fb` |

Connector reconstruction verified all actual full file Git blob hashes and deterministic zero-context patch roundtrip; not native git apply/compiler credit. Focused verifier imports exact R102 unified staging tool, full original Linux, applies/reverses/reapplies R103 strict index overlay, exact census/diff. R101 historical target in base; R103 frozen current target/controller/collector pins explicitly checked separately, not compiled. Focused actual-source host test uses serial kernel API models, real extracted area_get/next/publish/stop/revoke and actual debt/terminal inc; eight modes normal, reopen, wrong-completion, split, late, overflow, publish-race, publish-quarantine. Actual native call-site static checks and requested generated x86_64 SMP/TREE_RCU default-off config with ELF/OpenSSL prerequisites; directed mm/zswap.o, mm/page_io.o, mm/swapfile.o, drivers/md/dm.o only. No unchanged host composition replay, no full link or MODPOST.

## CI

Local git ls-remote reconfirmed exit128 DNS (Could not resolve host: github.com); raw local download unavailable. [R103 focused run 45927429520 / job 140271957716](https://github.com/k1moradi/swapz/actions/runs/45927429520/job/140271957716) snapshot **QUEUED**; artifacts 0. No hosted git apply, GCC/Clang sanitizer result, actual native object/config result or current terminal first failure yet; no PASS claimed. No manual replay.

Prior R102 [job 140262410396](https://github.com/k1moradi/swapz/actions/runs/45924444583/job/140262410396) independently fetched terminal success and logs: ORDERED_STATIC_PASS mutants=11, GCC and Clang each 12708 checks, 5 claims/5 modeled terminal owners/3 refusals/2 typed reads, four behavioral mutants each; R102_A11_UNIFIED_STAGE_PASS AUTH0 NO_COMPILE. Artifacts 15165753564 and 15165788164 metadata/digests in JSON, archives not extracted. This is historical frozen proof only.

AUTH0 Phase A BLOCKED, compressed handoff/forced RAW/import OFF, physical NO_GO. No branches, PR, force, VM, activation, load, physical mutation, disconnected build or duplicate dispatch.
