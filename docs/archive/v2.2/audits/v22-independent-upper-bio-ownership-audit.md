# V2.2 independent upper-BIO ownership recovery

## Scope and initial code audit

Main-developer source review began at
`9e0e89aa01de0e3d5555ea8936a3d114e71f8a8d`,
independently of Codex's native Linux validation worktree.
Codex's previous reported native compile at `4704995c` did **not**
qualify the changes developed in this branch.

The driver has three non-overlapping ownership stages:

1. Queued BIOs use the existing `dm_per_bio_data` list node.
2. A compressed pack holds pending BIO pointers but does not transfer
   stream-buffer ownership until `swapz_stage_write_block()` succeeds.
3. A fill/in-flight stream buffer owns uncompleted writes until lower
   I/O success, submission failure, watchdog failure, or late callback.
   Early-completed staged writes no longer own a pending upper BIO,
   but their resident data may still be authoritative.

Previously `swapz_complete_buffer_bios()` could discover upper BIOs
**only** by traversing `buffer->block_count` and each in-memory
`block->record_count`. Following a failed compaction preflight,
a lower I/O error, late malformed metadata, or watchdog timeout,
a zeroed/truncated count could conceal an otherwise intact pending
`record->bio`. The target would fail but that BIO could remain
incomplete. A validated/bounded scan protects against out-of-bounds
access, but it does not discover an owner concealed by a bad count.

## Minimal fix

Each stream buffer now has an intrusive `owned_bios` list. It reuses
the existing per-BIO list node allocated by Device Mapper and does
**not** allocate a new node, table, pool, or hot-path buffer.

The serialized worker registers each non-early-completed BIO in the
owning stream buffer during staging, after reserving the destination
block. That list remains independent of mutable block and record
counts, logical indexes and repack positions. Every normal completion
unlinks the node **before** invoking `bio_endio()`; after the upper
BIO is released its list node is never accessed again.

On failure, `swapz_complete_buffer_bios()` first scans only the
bounded resident metadata to clear discoverable failed staged refs
and nullable record pointers. Then it drains the independent owned
BIO list and fails every pending owner exactly once. This still works
if a record count is zeroed, the block count is truncated or grows
beyond allocated capacity, or compaction moved descriptors.
Distinct stream buffers maintain distinct ownership lists.

The finalizer also performs an O(records + owned BIOs), bounded
read-only consistency check between non-null pending record pointers
and the per-buffer independent owner list. It rejects mismatched
counts before publishing any mapping: a lost `record->bio` pointer
can no longer let an outstanding owner survive a successful-looking
buffer reset. The fail-closed reaper then drains the registered owner.

When the target has already failed, `swapz_read_staged()` allows
staged readback only for records whose upper write was previously
acknowledged (`upper_completed`). This prevents unacknowledged
failed writes from becoming authoritative solely because malformed
metadata prevented their staged-ref cleanup. Valid earlier committed
mappings can be consulted through the existing fallback path.

There are no on-disk format changes, no additional heap allocations,
and no new callback-side mutations of worker-owned data.

## Executed exact-C source contracts

`tests/runtime/swapz-upper-bio-ownership-contract-test.py`
compiles actual `swapz_complete_bio()`,
`swapz_register_owned_bio()`, and
`swapz_complete_buffer_bios()` production C functions against
deterministic userspace list and BIO seams.

Seven test methods cover exact-once normal completion, hidden BIOs
after zero/oversized counts, record movement, partial early
completion, detached pending packs, invalid logical indexes,
separate stream-buffer ownership, and a deliberately mutated
count-dependent function demonstrating that a zeroed count strands
otherwise intact BIOs. The regression also checks the production
stage-registration and stream-ledger initialization sites.

Existing `swapz-async-reap-contract-test.py`,
`swapz-compaction-container-contract-test.py` and
`swapz-flush-fua-contract-test.py` shims were updated to model
the new independent ownership source while preserving their
production C bodies and adversarial cases. The staged-read harness
now exercises both unacknowledged failed-target rejection and valid
early-acknowledged failed-target recovery.

## Honest limitations

This is a defined *malformed-count recovery* guarantee, not a
claim to reconstruct arbitrary damaged kernel memory. Corrupting the
intrusive BIO ownership node itself, falsely changing the
`record->bio` pointer into a *different but valid* owner,
or corrupting per-BIO allocation metadata is not recovered merely
by an independent list and an owner-count cross-check. The normal
serializer remains responsible for maintaining exact descriptor-to-BIO
identity. A missing pointer is now detected by the count check;
arbitrary swapping or duplication of pointers is outside its proof.

The test harness never attaches real DM/loop/NBD/swap storage,
loads a kernel module, invokes privileged operations, or calls actual
lower dm-io. Native Linux compilation at this new source SHA
remains independently outstanding. Real fault injection and
powered-device acceptance need separate explicit authorization.
V2.2 strategy and batch winner remain **UNDETERMINED**.

## Exact qualified revision

Pending final PR and merge commit identity, rootless workflow
conclusions and their per-SHA evidence.

## Exact integration evidence

The reviewed owner-ledger change merged as
[`80ea94452e0cdeeb9d83934dbc3e56009ac408b5`](https://github.com/k1moradi/swapz/commit/80ea94452e0cdeeb9d83934dbc3e56009ac408b5).

Four **post-merge** rootless workflows completed successfully on this
same executable SHA:

- [Kernel source contracts](https://github.com/k1moradi/swapz/actions/runs/38056177917): **PASS** (owner 7/7, async 28/28, staged read 8/8)
- [Combined source qualification](https://github.com/k1moradi/swapz/actions/runs/38056177901): **PASS**
- [Teardown safety](https://github.com/k1moradi/swapz/actions/runs/38056177898): **PASS**
- [NBD source safety](https://github.com/k1moradi/swapz/actions/runs/38056177903): **PASS**

The exact PR head
`aa4daa9e13786c8b171df54f1b380ec79659da85`
also passed all four required rootless PR workflows. Later
documentation-only changes on main do not alter executable
qualification. Native Linux module compilation on this executable
source has not yet been independently reported. No loaded kernel
or real DM/loop/NBD/swap/device qualification was performed.
