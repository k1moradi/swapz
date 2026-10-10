# V2.2 stream lower-write extent admission

## Source audit and defect class

Independent main-developer work began from the clean merged read-boundary
commit `03e6e6459fed5317918d1314f3ccf0bdab47564a`. It does not use
the separate native-Linux execution assigned to Codex as qualification
for this newer source.

Before the change, `swapz_submit_stream_buffer()` checked that the
buffer was FILL and that no write was in flight, but then constructed a
dm-io write request directly from resident `buffer->start_block` and
`buffer->block_count`. Neither the bounded in-memory batch allocation
nor the target's usable `context->physical_blocks` extent was
rechecked at this final lower-I/O boundary. A forged or corrupted
batch could thus hand lower dm-io an out-of-extent physical region.

No ordinary-workload corruption or device incident is demonstrated.
The prior preflight already constrains many inputs in the ordinary
fill-buffer path. The added guard is a last-chance fail-closed invariant,
particularly useful if batch ownership or physical reservation
metadata is inconsistent.

## Production change

After checking the existing nonempty and FILL/in-flight conditions,
and **before** assigning the lower dm-io region, changing buffer state,
increasing the asynchronous callback reference, or arming the watchdog,
the submitter now rejects:

- `block_count > max_batch_blocks` (the allocation bound).
- `start_block >= physical_blocks` (outside the usable extent).
- `block_count > physical_blocks - start_block` (crosses its end
  without overflowing a `start_block + block_count` addition).

An invalid batch returns `-EUCLEAN` while remaining fill-buffer-owned
for the existing failed-target/unsent-BIO error path. No callback or
in-flight ownership was transferred; no lower write was initiated.
A valid request retains the prior synchronous submission-error
normalization and asynchronous completion semantics.

No on-disk format, public interface, write-batch policy, hot-path heap
allocation, stream strategy or logical mapping changes.

## Exact-source rootless qualification

`tests/runtime/swapz-stream-submit-bounds-contract-test.py` extracts
the actual `swapz_physical_sector()` and
`swapz_submit_stream_buffer()` C implementations. It compiles them
with bounded ordinary-memory stand-ins at
`-std=c11 -O2 -Wall -Wextra -Werror`.

The deterministic `dm_io()` seam does not issue syscalls or touch
devices. Test cases cover empty and valid batches, valid first and
last block, a legal multiple-block tail batch, crossing the physical
end, `UINT32_MAX`, oversized allocated batch, no physical space,
bad state, already-in-flight state, and synchronous dm-io rejection.
On rejected inputs, assertions require zero lower submissions,
watchdog arms, callback references, or completion-token mutations.

A separately compiled mutant deletes the production bounds guard
and proves the original source passes out-of-range writes to the
mock dm-io call. The isolated kernel, combined, and teardown rootless
workflows execute the bounded regression. The workflow-contract
suite fails if either joint workflow silently removes it.

## Evidence boundary

All tests described above are **unprivileged rootless source tests**,
not native kernel compilation or real-device qualification. After the
change is merged, independently capture four rootless workflow
conclusions at its exact commit before marking integration qualified.
Any real device, dm, swap, backing release, fault injection, pressure
workload or privileged qualification remains blocked pending separate
explicit approval. V2.2 strategy and batch winner remain
**UNDETERMINED**.

## Exact merged-source evidence

The reviewed change merged as
[`49b062a0180990a03b0b81fd40c1c3e41c2f620f`](https://github.com/k1moradi/swapz/commit/49b062a0180990a03b0b81fd40c1c3e41c2f620f).

All four **post-merge** rootless runs on this identical executable
commit passed:

- [Kernel source](https://github.com/k1moradi/swapz/actions/runs/38047254236)
- [Combined source qualification](https://github.com/k1moradi/swapz/actions/runs/38047254217)
- [Teardown safety](https://github.com/k1moradi/swapz/actions/runs/38047254245)
- [NBD source safety](https://github.com/k1moradi/swapz/actions/runs/38047254206)

The original PR head `11f95c24e1e472451a6d5341698309b383de6973`
also passed all four PR qualification workflows before merge.
The exact-C stream submission suite reports 4/4 passing Python
test methods with multiple valid/error scenarios and an executable
unsafe-old-code mutant. Later documentation-only commits on
`main` do not modify qualified executable code. No native loaded
kernel/device qualification was performed for this new SHA.
