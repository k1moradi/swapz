# V2.2 resident compressed-container compaction validation audit

## Scope and source identity

This narrow audit began from remote `main` at
`1fd24f6ba8368a35153e7d2f1405ac633bac86c7`.
The correction was integrated as
[PR #3](https://github.com/k1moradi/swapz/pull/3), merged at
[`57af151c4f47b24a3ad0533ea1377d289c13a2c1`](https://github.com/k1moradi/swapz/commit/57af151c4f47b24a3ad0533ea1377d289c13a2c1).
This is still experimental source-level qualification, not a validated
production release.

The relevant production routines are `swapz_compact_fill_buffer`,
`swapz_decode_loaded_mapping`, `swapz_read_staged`,
`swapz_emit_repack_container`, `swapz_repack_can_fit`,
`swapz_complete_buffer_bios`, and `swapz_submit_fill_buffer`.
The compactor operates on **locally constructed RAM stream buffers**,
not on untrusted raw device blocks. The corruption cases below are
fault injections; ordinary-operation reachability has not been established.

## Source-level finding and counterexample

Before the change, the compactor checked selected on-block magic,
record index versus on-block count, logical-page identity, stored
length agreement and upper payload extent. It did **not** reject
unsupported container versions, payload overlapping descriptor
metadata, zero lengths, contradictory in-memory and disk record counts,
or out-of-range in-memory counts before indexing the 64-record array.

In addition, discovering a malformed record late in compaction could
occur after earlier source blocks were repacked or staged references
had been rewritten. Flagging the target failed at that point does not
undo those mutations.

`tests/runtime/swapz-compaction-container-contract-test.py` extracts
the actual production compactor/repack functions. Its deliberately
broken executable removes the preflight call and **accepts a
version-2 container, rewriting it as version 1**. The guarded
production function rejects the same container without modifying
stream-buffer data or metadata.

This is a concrete, executable source-level invalid-input acceptance
counterexample, **not** proof that normal runtime generation can
produce that invalid block or that a deployed kernel has corrupted swap.

## Production change

`swapz_validate_compact_fill_buffer` performs a read-only preflight
of the whole fill buffer before any in-place compaction or cancellation.
It checks:

- Block count against the configured preallocated batch capacity.
- Nonzero in-memory per-block record counts, limited to 64.
- Raw record shape (one 4 KiB record, index zero, valid logical page).
- Exact compressed magic/version and disk/in-memory record-count agreement.
- Bounded descriptor-table extent and record-index/order consistency.
- Compressed-only flags, in-range logical pages, nonzero bounded
  compressed lengths, and per-record logical/length agreement.
- Payload start after the descriptor table and payload end within 4 KiB.

The code preserves existing container/layout sizes, repacking policy
and I/O batching. It adds no hot-path allocations; metadata preflight
is an additional bounded RAM scan whose performance cost is still
unmeasured.

The failure fanout in `swapz_complete_buffer_bios` additionally
bounds resident block and record iteration to allocated capacities,
and refuses to index staged references using corrupt logical-page
indices. `swapz_read_staged` likewise rejects resident block/record
indices beyond the configured allocation and 64-record table.

These bounds prevent avoidable out-of-range accesses on the reviewed
failure paths. They do **not** make arbitrary RAM corruption
recoverable, repair damaged acknowledged compressed payloads, or
constitute a whole-kernel memory-safety proof.

## Rootless tests and mutation

The new Python/C harness compiles exact production C with finite
stand-in context buffers, generations, staged references and BIOs.
It exercises valid compressed/raw records; malformed version,
record counts, offsets, length, flags, logical indices, zero length,
oversized resident counts, and a late corrupt second block. It
checks that rejected metadata leaves stream-buffer bytes, block
records, and staged references unchanged, and that bounded failed-BIO
cleanup completes once on modeled damaged indices.

The second executable deliberately omits the validator and succeeds
at the invalid-version repacking case. This makes the negative test
executable, not a textual or regex-only assertion. The existing
async-C contract harness is updated mechanically to model the
new field/capacity dependencies in the production completion routine.

The isolated kernel, combined and teardown workflows run the contract
under a 25-second deadline. The workflow contract treats its omission
from either mandatory joint workflow as a test failure.

## Qualification evidence and remaining limitations

Candidate executable `e3e45f5c8ab7e52e5db20375d12661b97088f0a2`:

- [Isolated kernel source run 38044596044](https://github.com/k1moradi/swapz/actions/runs/38044596044):
  **PASS** for the candidate kernel and C test source.
- [PR kernel source run 38044600544](https://github.com/k1moradi/swapz/actions/runs/38044600544):
  **PASS** at the same candidate SHA.
- [PR NBD source-safety run 38044600630](https://github.com/k1moradi/swapz/actions/runs/38044600630):
  **PASS** at the same candidate SHA.
- [PR combined run 38044600541](https://github.com/k1moradi/swapz/actions/runs/38044600541):
  **PASS** at the same candidate SHA.
- [PR teardown run 38044600642](https://github.com/k1moradi/swapz/actions/runs/38044600642):
  **PASS** at the same candidate SHA.

The test compiles selected C routines, not the entire module, and
does not execute real LZ4, workqueues, DMA, dm-io, or a kernel swap
fixture. A real hostile-RAM fault model and device-level acceptance
require separate review and authorization. GNU worker provenance,
privileged containment, independently attested kernel I/O drain and
physical backing release remain separate blockers. The V2.2
strategy/batch winner is **UNDETERMINED**.

No real device, swap, NBD, DM, module, privileged cleanup, pressure,
backing release or destructive operation was performed for this audit.

### Post-merge CI, exact integration revision

Merged SHA `57af151c4f47b24a3ad0533ea1377d289c13a2c1`
passed rootless [kernel](https://github.com/k1moradi/swapz/actions/runs/38044908279),
[combined](https://github.com/k1moradi/swapz/actions/runs/38044908328),
[teardown](https://github.com/k1moradi/swapz/actions/runs/38044908268),
and [NBD source-safety](https://github.com/k1moradi/swapz/actions/runs/38044908271)
workflows, all at that same SHA. Final PR head
`ffdd28aaabc5511aae294d676c0e57e1a6debf77`
also passed each of these gates separately. These facts do not establish
real kernel I/O or persistence behavior.

Documentation-only commits written after the merge preserve the qualified
executable source and must be distinguished from the exact tested SHA.
