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
