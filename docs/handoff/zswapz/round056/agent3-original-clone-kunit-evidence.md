# Round056 Agent3 — original full-clone provenance prototype (default-disabled)

Assignment: issue #173 official ROUND_OPEN comment 7060046353. Frozen real
engineering `1484efd1324feda5a8871e1a2c015393b3d1a435`, frozen task
`7056741b12eac407314151a8f38e45e77a505603`, original Linux pinned
`torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`.

## Prototype, not authorization

New independent `tests/tools/round056-original-clone-stage.py` first demands
pristine original Linux Git HEAD, a fully clean work tree, byte-exact original
Git blobs of `block/bio.c`, `include/linux/bio.h`, `include/linux/blk_types.h`,
`drivers/md/dm.c`, `mm/page_io.c`, and real DM/source completion anchors.
It invokes the **unchanged** existing verified original composer to retain all
66 prior authentic C KUnit registrations, then stages four original-source
files using a uniquely named, default-**UNDEFINED**
`SWAPZ_ROUND056_ORIGINAL_CLONE_PROVENANCE_TEST` guard. No edited original
kernel file is committed to the swapz repository or its enabled production
build. Guarded code uses the actual original block APIs and existing DM
source; it does not change live `src/kernel/dm-target.c`, existing v1
`BIO_CLONED` refusal, APIs/exports, selected codec, on-disk format, or
scheduler.

A bounded test-only ticket starts only on an exact one-vector 4096-byte
ordinary `REQ_OP_WRITE|REQ_SWAP` original BIO. Its immutable geometry records
original bvec address, source bdev pointer, sector and refcount; it does **not**
retain source STORED bytes, a zswap pool, folio lock, swap-slot count or
current DM table lease. After real original `__bio_clone` crypt/integrity
success, an original *noncloned* full-page parent can propagate one additional
ticket reference to a complete clone. The ticket's two references are separate
**synthetic test attachment refs**, NOT proof of a legitimate extra original
swap-slot or BIO allocation ref. A failed clone returns without acquiring any
ticket ref. Original `bio_uninit` drops the associated ref exactly once;
`bio_reset` naturally uses that path. `bio_split` invalidates both resulting
views; `bio_trim` invalidates even zero-offset shortening; both actual
`bio_advance` and `__bio_advance` invalidate after consumption; original
`bio_prepare_reissue` invalidates irreversibly. Source status is per BIO and
never reactivated by restoring old scalar sector/size values.

Source-backed safety boundary: pinned original block/bio.c allocates clones
sharing bvecs (not owning the underlying source vector). Original DM
`alloc_io` creates `BIO_CLONED`, `alloc_tio` can change mapping device and
truncate, `__map_bio` installs `clone_endio` and target owns only after
`DM_MAPIO_SUBMITTED`, `__dm_io_complete` can requeue or terminally call
original `bio_endio` after `pending_io` releases. The staged DM path explicitly
invalidates the candidate on `alloc_tio` device assignment and `queue_io`
suspend/requeue. **No accepted target ever gains source authority from this
guard**. This avoids the false assumption that the clone flag, copied bvec,
source sector, or ticket is a held source-slot/DM lease. Missing actual reviewed
bridge: original native owned pre-erase bytes/codec attach -> clone transfer
through real native folio writeback and current target admission -> durable
lower write -> one map -> one genuine upper `bio_endio` -> full decoded
original-page integrity, including GC/read/dtr and native swapoff.

## Rootless direct evidence, separate from original kernel boot

At preparation time the container cannot resolve github.com for a pristine
Linux checkout (`git ls-remote`: `Could not resolve host: github.com`); source
anchors and Git blob hashes were independently checked through connected
GitHub reads. As **unprivileged uid 1000**, compiled and executed the exact
new guarded C helper injected into the host fixture with GCC and Clang,
`-std=gnu11 -O1 -g -Wall -Wextra -Wconversion -Wshadow -Werror`
`-fsanitize=address,undefined -fno-sanitize-recover=all`
`-fno-omit-frame-pointer -no-pie`, leak detection on, ASan/UBSan halt on error.
For **each compiler**: 84 deterministic executable normal/full-page,
wrong-sector/bvec/device, truncated and 4100-byte, invalid source, split,
trim, requeue, nested-clone, sibling ref, parent-before-child-release and
once-only terminal ref cases PASS; **16 independently compiled and executed
changed-function C mutants**, each rejected by expected
`ROUND056_CLONE_FIRST_ERROR` with process exit exactly 1, not a compiler-only
failure or sanitizer accident. Initial mutant test-harness leak report was
fixed by using a fail-only first-error assertion path terminating before
ordinary program-exit leak checking; successful full baseline still runs
ASan/UBSan leak detection. This is guarded helper host C only: the host's
clone constructor is a stand-in, not original Linux `bio_alloc_clone` or a
real device callback.

Independent **genuine** pinned Linux KUnit runner:
`.github/workflows/phase-a-zswap-round056-original-clone-provenance.yml`.
`tests/runtime/native/fixtures/round056-original-clone-kunit.cfrag` adds
four new KUnit functions in staged original `block/bio.c` using real
`bio_init_clone`, `bio_alloc_clone`, `bio_split`, `bio_trim`,
`bio_prepare_reissue`, `bio_reset`, `bio_endio`, `bio_uninit`, and existing
source bvec/page. The runner requests the 66 inherited cases and four new
actual C cases (`70` only *after* verified genuine boot), checks both original
JSON and KTAP with ten hostile verifier self-tests, strict host C and
`KCFLAGS=-Werror`, and links actual CI run to its exact published source SHA.
**At first publication, this KUnit build has NOT executed and must not be
claimed PASS; no actual accepted DM target/owner device trial exists.**
Other original x86 ZSWAP=y/n and matched GPL DM builds belong to earlier
source SHAs until independently requalified; no new x86 build claimed.

## Nonnegotiable result

Design feasibility remains **NO_GO for positive imported compressed handoff**.
`SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`,
`DIRECT_COMPRESSED_HANDOFF=DISABLED`, `FORCED_RAW_BYPASS=DISABLED`.
Normal `RAW_4096` is the full original UNCOMPRESSED 4096-byte page; never
compressed STORED bytes. Native Linux MM alone drives zswap bounded RAM
pressure eviction; swapz alone packs valid SWAPSPACE2 disk payload and GC.
No independent hidden swap count/reclaim/worker, no new dynamic production
allocation, no retained original SG/pool or post-terminal pointer, and no
modification to the entire first physical 4096 SWAPSPACE2 header/UUID/signature
or any partition table. No owner `make test`/`make fast_test`, privileged,
loaded-module, swapoff/swapon, null_blk, physical-media or real-pressure test.
