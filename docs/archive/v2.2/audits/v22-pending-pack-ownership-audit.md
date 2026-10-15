# V2.2 pending compressed-pack upper-BIO ownership audit

## Origin and scope

Codex's independent read-only review at
`24e2794b173a405c9f9ccfe739c4f733ebc41508`
passed six native-host rootless GC/range/mapping suites (**94/94** methods).
Its review identified that accepted compressed upper BIOs are held in
`context->pending[]` until a pack flush, where both normal flush and
fatal cleanup historically enumerated BIO pointers solely using
`pack_record_count`. Codex found no normal serialized path corrupting
that count; this change supports a precisely bounded in-memory
fault-injection recovery model.

The lead-developer fix began at
`8d86a96b22d5a8d2dc8d261251f20c3d94406dbe`,
which already includes PR #9's exact stream owner identities,
PR #10's mandatory physical-repack relocation test, and PR #11's
rootless checkpoint publication race repair.

## Demonstrated count-dependent failure

A compressed upper BIO has already been accepted into
`pending[0].bio`; `pack_record_count` is then fault-injected to 0.
Old `swapz_fail_unsent_upper_bios()` loops zero times, never completes
that accepted upper BIO, and leaves the worker request indefinitely
outstanding. A truncated count can hide later accepted BIOs; an
oversized count could make normal flush/failure paths access beyond
the fixed 64-element pending array.

The new exact-production-C test compiles a deliberately count-driven
old-failure variant, and checks that the mutated cleanup still leaves
the first two outstanding BIOs on the independent ledger when
`pack_record_count == 0`. That mutant's expected marker is evidence
of a defect in the *old approach*, not a production-path failure.

## Ownership model and source changes

`swapz_context` owns a new intrusive `pending_bios` list, initialized
before the pack's first reset. No allocations and no on-disk changes
are required. The list reuses the existing `dm_per_bio_data` node;
the per-BIO `record_index` from PR #9 serves as the independent
pending slot index.

When `swapz_add_compressed_record()` accepts a BIO, the serialized
worker registers it in `pending_bios`. Garbage-collection-only
records have NULL BIOs and never enter this ledger. Every add and
every flush first checks `swapz_pack_bios_match()`, which validates
`pack_record_count <= SWAPZ_MAX_PACKED_RECORDS`, per-slot indices,
each registered owner against its actual pending descriptor pointer,
and the total count of registered owners. It does not dereference
untrusted descriptor BIO pointers. A count-hidden owner, duplicate
pointer, misplaced owner or oversized count fails closed before the
next add can overwrite a slot or flush can read out of bounds.

`swapz_stage_write_block()` explicitly unlinks the node from
`pending_bios` **before** `swapz_register_owned_bio()` moves an
accepted compressed BIO into the selected stream buffer ledger.
Raw writes already have a detached node and take the previous
direct registration path. The transfer occurs only after earlier
reservation/segment validation returns successfully; the remaining
staging loop does not contain a later failing operation.

Both failed pack flush and failed-target/teardown cleanup complete
BIOs using `swapz_fail_pending_pack_bios()` by draining the
independent ledger, then reset the pack metadata. This completes
owned BIOs even with a zero, truncated or oversized count without
following stale unused pending slots. Repeated cleanup is idempotent.
`swapz_reset_pack()` warns if called while any pending owners remain.

## Exact compiled rootless regression coverage

`tests/runtime/swapz-pending-pack-ownership-contract-test.py`
compiles **verbatim production C** for upper-BIO completion, the
pending owner identity check, registration, pack reset, independent
failure drain, unsent failure handling, pack capacity, compressed
record insertion and pack flush. Lower physical staging is a
deterministic mock; assertions of real production transfer code are
also enforced at source-extraction time.

The 11 test methods cover:
- Two valid accepted owners transferred to stream and completed once
- Zeroed, truncated and oversized count recovery
- Malformed-count flush rejection before any staging
- Valid 64-record full pack
- Stage rejection without ownership transfer and later error completion
- Idempotent failed cleanup
- GC-only records with no upper BIO owner
- Duplicate resident descriptor BIO pointer
- Append rejection before a corrupted count can overwrite a pending slot
- Healthy empty pack
- Expected failure of the deliberately old count-dependent mutant

`tests/runtime/swapz-flush-fua-contract-test.py` additionally
compiles the **actual production staging C** and exercises a new
pending-to-stream list transfer, alongside existing raw, FUA and
early-completion matrix cases. The existing GC compressed-scratch
exact-C fixture explicitly models the added no-BIO ownership seams.
Mandatory rootless kernel, combined and teardown workflows execute
the new pending-pack suite; the workflow-contract suite rejects
omitting its executable gate.

## Complexity and limitations

Identity checking costs O(pending records + pending upper BIOs)
per compressed append and flush, bounded at 64 records. In the worst
case a full pack repeatedly checks at most 64 outstanding owners,
which increases CPU work relative to the old hot path; actual loaded
kernel performance has not been measured. No extra per-BIO allocation,
disk-format modification, or callback mutation occurs.

This fix does **not** promise recovery if the intrusive list pointers
or `dm_per_bio_data` itself are corrupted, or if owner metadata and
record descriptors are both arbitrarily modified to remain mutually
consistent. It does not establish that normal source code produces
malformed pack counts; the reproduced fault requires controlled
in-memory metadata injection.

If a lower asynchronous dm-io callback never arrives, the destructor
still waits for that reference to release rather than freeing
callback-owned memory early. Without a documented safe cancellation
and ownership-revocation guarantee, a finite teardown timeout that
frees the context could produce a use-after-free. The conservative
liveness limitation remains, without a speculative dangerous fix.

No loaded module, real DM, swap, loop, NBD, physical device, pressure,
or privileged testing was performed. Native Linux compilation from
Codex applies to older source SHAs and **does not qualify this new
kernel version**. V2.2 strategy and batch-size winner remain
**UNDETERMINED**.

## Revision-specific evidence

[PR #12](https://github.com/k1moradi/swapz/pull/12) merged the
pending-pack owner repair at executable SHA
[`13451799dc44dd9126d59720568d8116acd9fb61`](https://github.com/k1moradi/swapz/commit/13451799dc44dd9126d59720568d8116acd9fb61).
Exact PR head `ffe16e4cd76522a65decbbde3ded4054b1cd2688`
passed all four applicable rootless workflows before merge.

Four **post-merge** rootless workflows completed successfully on the
same executable SHA:

- [Kernel source contracts, run 38063553855](https://github.com/k1moradi/swapz/actions/runs/38063553855): **PASS**
  (new pack owner 11/11; real C staging/FUA 9/9).
- [Combined source qualification, run 38063553874](https://github.com/k1moradi/swapz/actions/runs/38063553874): **PASS**
- [Teardown safety, run 38063553857](https://github.com/k1moradi/swapz/actions/runs/38063553857): **PASS**
- [Standalone NBD source safety, run 38063553854](https://github.com/k1moradi/swapz/actions/runs/38063553854): **PASS**

Codex's last supplied native evidence and previous six-suite
read-only GC review qualified older `24e2794b` and do not establish
a native module build for this PR #12 source. No loaded-kernel or
real-device validation occurred.
