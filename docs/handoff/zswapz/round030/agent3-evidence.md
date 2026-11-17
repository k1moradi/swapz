# Round030 Agent3 — source-only real DM ordered lower commit

Frozen publication: `3636346987898b2d9cccf3bcf39b3914e79c051f`.

Actual guarded `src/kernel/dm-target.c` adds `swapz_round030_dm_commit_owned_lz4` and `swapz_round030_dm_read_owned_lz4`. Real swapz authority stage/bind/mark, checked 4/8/16KiB zero-padded compressed lower-image, checked `swapz_lower_write`+optional FUA, `swapz_finish` COW RAM map, physical sequence check, then test-only exactly-once hypothetical ACK. The separate caller-owned volatile descriptor retains current map, source slot, STORE epoch/identity, codec/version, original SHA and compressed CRC; the existing 20-byte map layout is unchanged. The real Round028 `swapz_lower_read`/map/GC-fenced byte-exact 4096 CRC32C+LZ4+SHA path is reused. Failed I/O quarantines the staged extent through real `swapz_finish`; staging failures call real `swapz_abort`; previous map is not published on failure.

The three-macro CI-only helper has NO real upper-BIO ingress or upper ACK: `swapz_zswap_admission_try_live` is still unconditional `-EOPNOTSUPP`. The independent host fixture is **not** trusted carrier provenance and its fake lower callbacks are NOT physical I/O. Cross-ABI source extracted GCC/Clang ASan/UBSan checks and actual Linux x86/ARM external module Kbuild remain separately required; do not confuse a host fixture's map mock with real authority, which is separately kernel compiled but not loaded.

This does not authorize Phase A. PHASE_A=BLOCKED, FORCED_RAW_BYPASS=DISABLED, DIRECT_COMPRESSED=NO_GO_DISABLED, LOADED=NOT_RUN, PHYSICAL=NOT_RUN; original RAW remains uncompressed 4096. No SWAPSPACE2 header, UUID, first-page or partition-table mutation. No independent zswap RAM eviction policy or pressure controller.

## First hosted actual module compiler failure and direct correction

Exact source SHA `0eaca41cae54402881c0d770ff4ce65fee6c4196`, product-codec x86/arm64 [run #44119135592](https://github.com/k1moradi/swapz/actions/runs/44119135592), arm64 job 134165335785: **Kbuild W=1 opt-in failed** (`dm-target.c:3554`, function declaration not prototype; GCC `asm/current.h` macro collided with local variable `current`, resulting in conflicting `get_current` and lvalue-required error). The failure was in actual new kernel C, not the test harness. Rename only the Round030 local map pointer to `current_mapping`; all gates remain strict. Not a loaded-kernel or physical failure, no live compressed activation. Any later hosted CI must be checked at its actual fix SHA.
