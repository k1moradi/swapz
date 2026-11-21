# Round052 Agent3 — actual Device Mapper accepted ordinary 4096 BIO test-only receipt

Frozen engineering: `2f7c1692f5287f64b1bcb9d8ec5313546303c825`.
Frozen task: `d83c1d64eafa544c7c221ffcd1dbff501db7e4fd`.
Official ROUND_OPEN #169.

Added only `SWAPZ_ROUND052_DM_INTERNAL_ONE_SHOT_TEST`-guarded
C declarations, a per-existing-`swapz_bio_ref` test-only receipt,
the actual source C helper and passive `swapz_map` admitted normal
4KiB `REQ_SWAP` WRITE observer. It is placed AFTER queue-lock
admission and the real incoming list insertion; the default product
build does not define the guard and its code/ABI/hot path are unchanged.
Its synthetic generation/extents cannot grant any real ownership.

A new rootless verifier extracts actual `src/kernel/dm-target.c`
declarations/helper and verifies the real accepted map callsite plus
original actual lower callback, GC, completion, drain/dtr anchors.
Strict GCC/Clang `-Werror` ASan+UBSan each execute 144 distinct
per-compiler C lifecycle cases (48 faults x 4/8/16KiB extents)
and compile+execute 13 function-mutated real helper C binaries
EACH compiler (26 hostile actual runtime oracles). Cases include
dropped durability, -EIO, stale map/GC generation, clone identity,
admission closed, duplicate callback/map/ACK, exactly-one terminal
release, and abort. Prior actual C 168 negatives and 22 hostile
binaries per compiler stay in the existing CI lane.

The test invokes no actual upper `bio_endio`, lower WRITE,
map publication or original Linux source slot; numeric matches
do not hold a target/GC/dtr lease. This is a **test-only state model**
that cannot itself guarantee real asynchronous callback ownership.
Normal `RAW_4096` means FULL ORIGINAL UNCOMPRESSED 4096 bytes.
No external compressed-byte handoff permitted; source authenticated 0,
Phase A blocked. Zswap exclusively bounded RAM and native MM natural
eviction, swapz exclusively existing valid SWAPSPACE2 disk and GC;
entire first physical 4096 swap header immutable.
No owner make test/fast_test, root, loaded/physical mapper or
real pressure tests performed. New main commit, exact CI and
first errors reported separately to #169.
