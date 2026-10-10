# V2.2 mapping replacement: preserve authoritative live accounting on rejection

## Confirmed source-level failure path

Before the correction, `swapz_install_mapping()` called
`swapz_unaccount_mapping(context, mapping)` and *then* checked whether
the proposed `physical_block` was in range and below its
`SWAPZ_MAX_PACKED_RECORDS` capacity.

This allowed the following reproducible transition in the production C
routine:

1. A valid old mapping points to physical block 10 with one live
   record. The segment has one live physical block.
2. A corrupted or otherwise invalid candidate replacement chooses an
   out-of-range block, or chooses a different physical block already at
   capacity.
3. The old call order decrements the old block and segment live counts
   **while leaving the old mapping struct pointing to that block**.
4. Only after the decrement does the destination validation discover
   the error, set `context->failed` and return.

Although the old code latches failure, it leaves the still-authoritative
old mapping inconsistent with the live-reference index. Such failure
accounting must be conservative, especially when an acknowledged
staged page may need readback. This is a proven **source-level state
invariant defect**, not an observed deployed kernel corruption event.

## Narrow production correction

`kernel/dm-swapz.c` now:

- Returns without mutation if the target is already failed.
- Checks new physical-block bounds, segment bounds, and record
  capacity *before* unaccounting the old mapping.
- Allows an in-place same-block replacement when the block currently
  has exactly the maximum number of records, because removing the
  old mapping will free one slot. The old mapping must still pass
  ordinary live-reference underflow checks.
- Calls `swapz_unaccount_mapping` only after valid destination
  admission, and checks for an old mapping consistency failure
  before incrementing the new counters or publishing the mapping.
- Retains the original 8-byte mapping structure, on-disk records,
  per-block 64-record cap, GC policy and async BIO lifetime.

The new ordering does not make corrupted metadata recoverable or turn
a failed target into a reusable target. It preserves the prior mapping
and count on rejected *replacement destinations* so the failure state
is internally consistent.

## Exact-C rootless regression

`tests/runtime/swapz-mapping-accounting-contract-test.py` extracts and
compiles five actual production C functions:

- `swapz_mapping_valid`
- `swapz_mapping_segment`
- `swapz_unaccount_mapping`
- `swapz_invalidate_mapping`
- `swapz_install_mapping`

The userspace harness tests 16 deterministic mapping/counter scenarios
with bounded arrays. It includes valid cross-/same-segment moves,
capacity 63→64, full same-block replacement, two simultaneous live
records within one block, invalid new index (including U32_MAX),
a different full block, already-failed target, corrupt old live counts,
invalidation and first installation.

The test also compiles a **second executable** that moves the real
unaccount call ahead of destination validation, recreating the
old bad order. This intentionally buggy executable fails the
invalid-destination scenarios, while the corrected production
function passes all of them. Additional negative source mutations
require the same-block exception, destination pre-validation,
publication order and underflow guards.

Seven Python test cases drive the 16 positive C scenarios, executable
old-order counterexamples and source mutation checks.

The test uses stand-in kernel failure logging and bounded in-memory
metadata, not Linux block I/O, workqueues, LZ4, or actual GC. Both
mandatory joint rootless workflows and the isolated kernel-only
workflow run it with a 25-second bound; workflow-contract tests reject
a missing execution gate.

## Exact-revision evidence

Qualified executable SHA:
`89ddc5fbd1a98979aa6c661085370a6bc0cff53d`.

- [Kernel source 38039927758](https://github.com/k1moradi/swapz/actions/runs/38039927758):
  PASS, 7/7 mapping tests, plus 9/9 FUA, 22/22 async reaper,
  21/21 generation, 15/15 GC compressed scratch, 17/17 GC
  source snapshot and 30/30 range contracts.
- [Combined 38039927690](https://github.com/k1moradi/swapz/actions/runs/38039927690):
  PASS on identical SHA, 7/7 mapping,
  24/24 workflow contracts, three fresh-process broker repeats
  and 25/25 NBD stress repetitions.
- [Teardown 38039927750](https://github.com/k1moradi/swapz/actions/runs/38039927750):
  PASS on the identical SHA, 7/7 mapping and 24/24
  workflow contracts.

The standalone NBD source workflow previously passed at the
kernel-identical earlier commit
`92425362c51f1ade3aa93a9e649c57ea8c67559d`
([run 38039788369](https://github.com/k1moradi/swapz/actions/runs/38039788369));
do not misreport it as run on the final mapping-test executable SHA.

Codex may advance main concurrently for GNU worker provisioning.
That does not replace the exact executable SHA above or prove live
kernel/device behavior.

## Remaining boundaries

Kernel fault injection should still validate real partially-live GC
victims, physical segment reuse, out-of-range/corrupted metadata
handling, async lower failure and FUA media persistence under an
independently authorized disposable fixture. Rootless C tests
do not authorize teardown, physical backing release or production
swap acceptance. Genuine GNU provenance, privileged containment and
independently verified device-I/O drain remain separate workstreams.

No real DM, loop, NBD, swap, module, pressure, physical device,
reboot or privileged/destructive cleanup occurred as part of this
task. Strategy/batch winner remains **UNDETERMINED**.
