# Agent 2 — Round 002 original REPORT_READY archive
Original GitHub comment: https://github.com/k1moradi/swapz/issues/119#issuecomment-6893835007
Original complete comment-body SHA-256 (UTF-8): `e910ed61e58b9de72febf1aff17dcfe86d9fd4c25826dd93e8ec1d8e01b432a1`
Round source baseline: `f11e8795f44f15fecc6b2b200c0b1a9e4eaeb364`
Outcome: BLOCKED_PUBLISH; source-context patch, not a full Linux checkout or kernel source commit.

This archive reproduces the entire original `REPORT_READY` comment below without omissions. SHA-256 refers to the source comment body, not the enclosing archive. Any original separately posted code artifact remains linked in the report.

---

message: REPORT_READY
round: "002"
agent: 2
task_id: agent2-upstream-provenance-implementation
status: BLOCKED
outcome: BLOCKED_PUBLISH
source_sha: f11e8795f44f15fecc6b2b200c0b1a9e4eaeb364
kernel_source_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
task_commit_sha: b949018a8f0461a5886eeaf0da4a1130c62dcf23
correction_commit_sha: fc32c7b9a07aafedbe1cb9aa693e3ffa71602966
published_upstream_source_commit: NONE
modified_files:
  - block/bio.c
  - block/Kconfig
  - block/Makefile
  - block/bio-zswap-origin-test.c
  - include/linux/bio.h
  - include/linux/blk_types.h
  - include/linux/swap_ops.h
  - mm/page_io.c
  - mm/zswap.c
patch_sha256: 8629381028e3a99d1e6229eb19aa3a0b7663bfd1a3c745585e3d905f0e79e35f
patch_full_text: https://github.com/k1moradi/swapz/issues/119#issuecomment-6893821816
tests:
  - command: "bash run_implementation_checks.sh (local synthetic source-context main-only fixture)"
    exit_code: 0
  - command: "git apply --check linux-c339f401-zswap-origin-implementation.patch (synthetic context fixture)"
    exit_code: 0
  - command: "git apply linux-c339f401-zswap-origin-implementation.patch (synthetic context fixture)"
    exit_code: 0
  - command: "git diff --check (synthetic context fixture)"
    exit_code: 0
  - command: "gcc -std=c23 -O2 -g -Wall -Wextra -Werror -fsanitize=undefined -fno-sanitize-recover=all kernel_source_extracted.c -o kernel_source_extracted_gcc && ./kernel_source_extracted_gcc"
    exit_code: 0
  - command: "clang -std=c23 -O2 -g -Wall -Wextra -Werror -fsanitize=undefined -fno-sanitize-recover=all kernel_source_extracted.c -o kernel_source_extracted_clang && ./kernel_source_extracted_clang"
    exit_code: 0
  - command: "read-only GitHub fetch_file exact source-blob/anchor audit: 8 original Linux files, 21 anchors"
    exit_code: 0
  - command: "git ls-remote https://github.com/torvalds/linux.git c339f4010dea8b0d754f84ace70cd1b089878ef8"
    exit_code: 128
  - command: "git apply --check / git apply / git diff --check on a complete original Linux checkout at kernel_source_sha"
    exit_code: NOT_RUN
  - command: "Linux kernel Kbuild CONFIG_ZSWAP=y/n, W=1/W=2 and CONFIG_BIO_ZSWAP_ORIGIN_KUNIT_TEST=y execution"
    exit_code: NOT_RUN
  - command: "Matched producer/consumer loaded ABI, genuine zswap stored-entry eviction, 4KiB readback"
    exit_code: NOT_RUN
evidence_class: rootless
blocking_findings:
  - "No complete torvalds/linux@c339f401 exact source checkout is present or network-accessible in the available container; no real full-tree git apply or kernel Kbuild was executed."
  - "No authorized writable Linux repository or upstream publication route was supplied; only local edited source-context fragments and a reviewable exact-anchor patch exist. There is NO persisted upstream code commit."
  - "Exact kernel .config, generated headers, Module.symvers, build tools and boot image identity are unavailable; patched struct bio and module runtime ABI still unqualified."
next_round_recommendations:
  - "Obtain a complete source checkout at the exact kernel_source_sha and rerun full-tree git apply and W=1/W=2 Kbuild for CONFIG_ZSWAP=y/n."
  - "Review the exported GPL helper and enforce matched running-kernel/module identity before any consumer attempts to read a modified struct bio."
  - "Provide a legitimate owner-approved writable Linux source destination if the source changes are to be persisted as a commit; do not push to torvalds/linux or swapz/main by assumption."
  - "Only after source/build acceptance, run authorized KUnit and genuine stored-entry eviction/clone/split/4KiB byte-exact readback tests. Keep Phase B disabled."

# Agent 2 Round 002 source-edit report — BLOCKED_PUBLISH (not an integration PASS)

## Code produced
I followed the [owner's source-edit correction](https://github.com/k1moradi/swapz/blob/fc32c7b9a07aafedbe1cb9aa693e3ffa71602966/docs/handoff/zswapz/round002/source-edit-correction.md): edited local kernel-source-context files, added actual C implementation and optional kernel KUnit code, and validated the resulting diff in a Git-controlled rootless source-context fixture. **The local file fragments contain synthetic filler outside the known pinned source anchors and are not full Linux source files.** They must not be mistaken for an actual full `torvalds/linux` checkout or a published upstream revision.

The complete **9-file, 14-hunk, 204-insertion** unified code diff, including `block/bio-zswap-origin-test.c`, is in the [preceding source-edit artifact comment](https://github.com/k1moradi/swapz/issues/119#issuecomment-6893821816). I fetched that comment back and verified its 10,701-byte diff matches local SHA-256 `8629381028e3a99d1e6229eb19aa3a0b7663bfd1a3c745585e3d905f0e79e35f`. No draft fragment has been characterized as compiled Linux production code.

The implementation supplies `SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN=0` and `SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK=1`; the latter is assigned only after zswap entry identity/reuse validation and successful decompression and before backing submission. It carries the scalar through `swap_io_ctx`, a homogeneous `swap_iocb`, the initialized `struct bio`, and `__bio_clone`. `bio_init` starts at unknown; `bio_reset`/payload reuse clear the scalar via `BIO_RESET_BYTES`; the exact upstream `bio_split` calls `bio_alloc_clone`; `bio_prepare_reissue` retains origin for the **same** retried operation. The helper checks WRITE, REQ_SWAP and exact origin 1, and is **GPL-exported** so a mismatched unpatched running kernel cannot silently provide that same named export. This export is a mitigation, not a substitute for authenticated kernel/module identity.

The narrow KUnit file covers the helper's positives/negatives, shared mixed-origin merge predicate in both orders, clone and reset/reuse, and a 2x4096-byte BIO split. Its actual KUnit execution is NOT_RUN, not PASS. No producer signal controls RAW bypass, delta64/LZ4, extent representation or scheduling; Phase B remains disabled.

## Verification and environment

**Source identity:** all **8 existing edited Linux file paths** match their exact pinned GitHub blob IDs, with **21/21** original source anchors present. This authenticates input snippets, not an applied full-tree patch.

**Runnable rootless checks:** `run_implementation_checks.sh` created an isolated main-only **synthetic context** Git fixture; `git apply --check`, `git apply`, `git diff --check`, source-edit/replay equality all exited **0**. Source-extracted real C predicate bodies compiled on **GCC 14.2** and **Clang 17** with `-std=c23 -O2 -Wall -Wextra -Werror -fsanitize=undefined -fno-sanitize-recover=all`, both compilation and execution exited **0**. Each executed **4,096 exact-positive/negative origin helper cases and 4 two-origin merge comparisons**. This does **not** execute Linux `bio_init`, clone, split, KUnit, MM eviction, or DM, despite source/KUnit coverage plans.

**Build blocker (first environment-level failure):** local sandbox running kernel `6.18.57`, x86_64, no matching running-kernel headers or complete 7.3-development source/config/Module.symvers. Direct `git ls-remote` of GitHub failed **exit 128** with `Could not resolve host: github.com`. A read-only GitHub connector can inspect pinned blobs, but cannot materialize an authorized full Linux checkout or authenticate a booted image.

**Binary layout/ownership:** inserting `u8 bi_swap_origin` after `bi_bvec_gap_bit` changes `struct bio` ABI layout/offsets in a config/architecture-sensitive way. It falls before `bi_max_vecs` and thus inside `BIO_RESET_BYTES`; `bio_init` zeroing and `__bio_clone` copy are explicit. The `struct swap_iocb` and `swap_io_ctx` also grow by an enum field. Exact sizeof/offset, `CONFIG_MODVERSIONS`, export resolution, module/signature and booted image equality require **a compiled matching tree**. No read of the new field is allowed to be treated as safe on stock, header-only or unknown loaded kernels.

## Final disposition

**`BLOCKED_PUBLISH` (status `BLOCKED`), not PASS**. I did not have the mandated complete upstream source checkout, nor a writable destination permitted for kernel source publication. The issue artifact is durable code review material but **not an integrated Git commit**. I did not push to `torvalds/linux`, create a fork/branch/PR, commit to `swapz/main`, claim loaded kernel evidence, or perform swap/mapper/device operations. Agent 3's exclusive swapz/main publication lease is unaffected. Agent 1 may use this report only as partial source-development evidence, not Round 002 kernel producer integration acceptance.
