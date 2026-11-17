# Round027 Agent2 — exact pinned Linux six/default and seven/allocator manifest repair

Task publication: 5da826bdcfbc358ed80814afb0ca19d46ac23806.
Prior engineering baseline: ce68d2ada7a9e5eb41d64fd30a20ab1ef036a11c.
Historical first failure: https://github.com/k1moradi/swapz/actions/runs/44048517348 job 133920135140 emitted **paired-build-invalid: source_manifest_paths**, not a kernel compiler error. The Round026 source stage produced a legitimate seventh exact original `mm/swapfile.c` while the paired verifier accepted exactly six. The follow-on wrapper misleadingly characterized source failure as a kernel-doc warning gate failure.

The paired verifier now requires exact ordered six-file default or seven-file opt-in manifest; the seventh requires original pinned upstream Git blob `254ce86fa923e6b5f1fefda88c39315c4cc00642`, literal NO_AUTHENTIC_GENERATION_NO_GO, compiled=false, direct_compressed=false. Wrong blob, duplicate, reordering, missing/extra path, forged flags and object set/digest fail closed. In the optional profile, real `mm/swapfile.o` is required in the paired SHA256 manifest under both CONFIG_ZSWAP=y and n, while `mm/zswap.o` remains y-only. No allocator-issued epoch or compressed-publish success was added.

The owned workflow final source path allowlist matches the seven opt-in original C/H sources already required at staging. Original source SHA, exact four pinned upstream kernel-doc warning signatures, source-hash and warning-count/digest evidence, W=1/-Werror, module compilation and source cleanliness remain strict. The wrapper reports a source-manifest OR warning-classification error, preserving the actual preceding `paired-build-invalid` cause. The full original GCC CONFIG_ZSWAP=y/n, opt-in allocator mm/swapfile.o machine-code nm and objdump and normal restored object, original zswap proof objects and full vmlinux/modules plus source-linked dm-swapz.ko require **actual hosted workflow final result**; host synthetic manifest tests are not kernel build evidence.

GO/NO_GO for direct compressed handoff: NO_GO; authenticated original Linux swap allocator reuse epoch absent. Phase A BLOCKED, forced RAW bypass DISABLED, direct compressed transport DISABLED. Original RAW is uncompressed 4096. SWAPSPACE2 first 4096 bytes, UUID and partition table unchanged. LOADED/PHYSICAL NOT_RUN.

## First Round027 hosted regression failure and correction

Initial published `3c7e8b2dc7195ab5d0ca1a76a5974d1b8b8fcd62`
[real pinned workflow](https://github.com/k1moradi/swapz/actions/runs/44056324540),
job `133946531684`, failed the new source-host regression before
Linux Kbuild: `test_round027_unknown_duplicate_reordered_allocator_paths`
expected `source_manifest_paths`, but the true first verifier response
was `paired-build-invalid: source_manifest_allocator_profile`.
Removing seventh path leaves the valid six paths, yet retains a forged
allocator opt-in marker: the **profile mismatch** is correctly rejected.
The test assertion is fixed; the validator and warning gates are unchanged.
Next exact-SHA source/build and first compiler errors remain authoritative.

## Additional source-first verification gate (no production behavior change)

The first Round027 six/seven verifier publication `3c7e8b2dc7195ab5d0ca1a76a5974d1b8b8fcd62` triggered exact-SHA [source workflow #44056324540](https://github.com/k1moradi/swapz/actions/runs/44056324540), job `133946531684`. All earlier host source regressions passed, but `test_round027_unknown_duplicate_reordered_allocator_paths` failed with exit **1**: the source validator correctly raised `paired-build-invalid: source_manifest_allocator_profile` when the seventh path was removed but the opt-in marker remained, whereas the negative test expected `source_manifest_paths`. Peer Agent2 corrected this test-oracle mismatch in published `5d2aff0bb37e0811b163267b8e9bda6f9f4b127c`, without weakening validation; its real pinned CI is separate.

This **additional nonconflicting** change makes source-check failures cheap and precisely attributed: `tests/runtime/native/pinned-linux-origin-paired-module-test.py --verify-source-manifest-only --source-manifest <path>` calls the exact existing bounded duplicate-rejecting `load_source_manifest()` (no privileged host read, no kernel compiler, no physical device), returns exit **0** only for authenticated six/default or seven/opt-in and exit **1** with typed `paired-build-invalid` on invalid. New process-level tests execute the real script for synthetic default and opted-in shapes and forged opt-in identity, verifying private temp path is never printed. The production `phase-a-zswap-origin-prototype.yml` invokes this CLI **after** original full Git-hash-checked Linux source staging, exact source allowlist and `git diff --check`, **before** expensive real `CONFIG_ZSWAP=y/n` kernel Kbuild. A new full-workflow source contract refuses removal, reordering or bypass of that early gate.

No kernel-doc warning whitelist, exact baseline source SHA1/counts/digest, `W=1` or `-Werror`, kernel/module source profile, source manifest validator semantics, MM allocation, zswap STORE, BIO, DM or physical owner code were altered. Historical first source-gate failure remains `source_manifest_paths` from [#44048517348](https://github.com/k1moradi/swapz/actions/runs/44048517348); first test oracle failure remains `source_manifest_allocator_profile` from [#44056324540](https://github.com/k1moradi/swapz/actions/runs/44056324540). **Neither is a real kernel C compiler error**, and no full paired y/n Kbuild PASS is inferred from these older failed runs.

`SOURCE=ROOTLESS_PREFLIGHT_ONLY`; `ORIGINAL_ALLOCATOR_EPOCH=ABSENT`; `DIRECT_COMPRESSED=DISABLED`; `PHASE_A=BLOCKED`; `FORCED_RAW_BYPASS=DISABLED`; `LOADED_4096=NOT_RUN`; `PHYSICAL=NOT_RUN`. Current RAW remains full original **UNCOMPRESSED 4096 bytes**; SWAPSPACE2 original header/signature/UUID/table and owner hardware remain untouched. Exact published SHA and subsequent true hosted tests/first failures reported in issue #144.
