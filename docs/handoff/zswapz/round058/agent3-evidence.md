# Round058 Agent3 — production Device Mapper default-off ingress/lifetime (AUTH0)

Issue #175 official ROUND_OPEN comment 7062413356. Frozen engineering 383d2b4e5b1b5a31b2f785f99f88241b2d08bce5; frozen task ffc15247418f4566a3230f55af99de96744f9741.

## Genuine guarded production C, not authorization

Exclusive real production source edit: src/kernel/dm-target.c. Existing swapz_map validates original target-relative full-page geometry and owns BIO admission under queue_lock. The new default-UNDEFINED SWAPZ_ROUND058_DM_INGRESS_LIFETIME_TEST records bounded read-only per-BIO negative observation only after this real lock-protected admission recheck, before incoming publication. It checks live target/context/authority pointer agreement, 4096 single bvec, exactly eight target-relative 512-byte sectors, true BIO_CLONED view, bdev and sector shape, and valid target interval. No allocation, extra lock, native bio_get, GPL export, public ABI, scheduler or active mapping changes.

The real ordered owner in swapz_complete monotonically retires the observation before bio_endio invalidates dm_per_bio_data. The real swapz_end_io DM callback marks single endio observation while live. Both reject reissue/changed bdev/sector/target identity, double terminal/endio, and target-failed status. Normal postsuspend may close new admission while an already accepted worker drains; this alone must not refuse completion. Even a matching pointer/shape returns negative -EOPNOTSUPP to compressed-import authority, NEVER a positive lease, lower submission, imported map, GC pin or upper ACK. Ordinary RAW_4096 and existing Round043 BIO_CLONED source v1 refusal remain unchanged.

## Rootless qualification and limitations

Isolated unprivileged C prototype exercised exact new helper text under GCC and Clang with GNU11, -Wall -Wextra -Wconversion -Wshadow -Werror and ASan+UBSan fail-on-sanitizer/leak detection. 22 distinct negative/terminal scenarios baseline PASS each compiler, seven independently modified C helper variants each exited 1 at named semantic first error per compiler; compiler/sanitizer failure does not count. The published tests/tools/round058-dm-ingress-verify.py extracts the marked C directly from actual production dm-target.c and reruns the same cases and mutants with kernel type/API stand-ins. Host types are NOT a genuine kernel DM or physical BIO lifetime.

The dedicated phase-a-round058-dm-ingress-noauth.yml checks exact source, diff --check and policy, stages original pinned Linux torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8 and requests complete original x86 ZSWAP=y/n vmlinux/modules with same-source GPL Module.symvers and default/guarded W1 -Werror linked dm-swapz.ko. It checks guarded symbols absent from default objects. Terminal exact-source CI is required before claiming that qualification; ancestor source success never substitutes.

## Release NO_GO

No original STORED source/folio/slot lifetime traverses the real clone into current accepted DM lease. The observed borrowed bvec is not a retained original owner. No selected original codec after source-pool death, durable FUA/flush imported lower WRITE, authoritative volatile imported mapping and GC pins, one genuine upper kernel ACK or verified full 4096 imported read proved together. RAW_4096 is always FULL ORIGINAL UNCOMPRESSED 4096. Protect whole first physical SWAPSPACE2 4096 and parent partition table. SOURCE_MAPPED_AUTHENTICATED=0; PHASE_A=BLOCKED; DIRECT_COMPRESSED_HANDOFF=DISABLED; FORCED_RAW_BYPASS=DISABLED. No owner make test/fast_test, privilege, loaded-kernel, physical, swap or real-pressure tests.
