# V2.2 foreground generation transaction and nested GC — rootless audit

## Source question

A foreground write first calls `swapz_commit_previous_generation`.
Only after the previous uncommitted page was flushed does it advance
`context->generations[logical_page]` and enter `swapz_store_page`.
Staging the new payload can in turn reserve or rotate a segment,
causing `swapz_clean_segment` to relocate the page's previous physical
mapping under the temporarily advanced generation. That is allowed
because GC is called *within the serialized I/O worker*, not from a
competing thread.

The old mapping may therefore move from one physical location to
another before the new foreground payload has been staged. On nested
GC success, a completed old-content relocation precedes the new write's
subsequent physical publication. On new-write staging failure, the
foreground routine restores its previous generation; the old content
must remain mapped. A failure while committing an old pending
generation must prohibit advancing the generation altogether.

**This review did not establish that this ordering is itself a
production data-loss bug.** Reordering production generation mutations
without a proven failure would risk breaking asynchronous BIO ownership.

## Exact production C portions exercised

`tests/runtime/swapz-generation-gc-transaction-test.py` extracts
the **verbatim production C definitions** of:

- `swapz_checked_page_index`
- `swapz_stream_record_current`
- `swapz_page_has_uncommitted_generation`
- `swapz_commit_previous_generation`
- `swapz_process_write`

It compiles the resulting code into an ordinary rootless userspace
binary, with bounded deterministic substitutes for BIO page-copy,
lower flush, and `swapz_store_page`.

The substituted store callback can simulate a GC relocation of the
*old* mapped content while observing the new tentative generation,
then either stage new payload or fail before staging. The test asserts
that old content remains authoritative on failure and is replaced
only by a successfully staged and finalized new payload.

Cases include plain write; pending pack/ref barriers; pack and lower
batch failures; nested GC with and without previous flush; new-write
failure after nested relocation; generation rollover from `UINT32_MAX`
to 1 and rollback from 1 to `UINT32_MAX`; full-width out-of-bounds
sector; an index that would alias after u32 truncation; and
misaligned sector rejection.

Mutants removing the previous-generation flush, the conditional
rollback, stale-generation comparison, GC generation binding, or the
required batch barrier are rejected by executable/source checks.

### Qualification classification

The five named helpers are **real production C**, not rewritten
Python analogues. Nested GC, mapping publication, physical batches,
BIO copying, and backing errors are **test substitutes**. The test does
not execute real `swapz_clean_segment`, LZ4, dm-io, the Linux workqueue,
or kernel memory management. Structural GC checks pin the source
generation lookup and both dedicated GC scratch buffers but do not
prove every in-kernel error sequence.

The new mandatory rootless combined and teardown workflow steps
execute this test with a 25-second timeout. The workflow-contract
suite fails if the executable gate is removed. It coexists with
the earlier kernel-range, GC source snapshot, and GC compression-output
tests without touching Codex's owner or supervisor modules.

## Outstanding safety/qualification work

1. Independently validated real kernel GC fault injection at segment
   rollover, physical write failure, compressed/raw mixing and
   source-content readback after a failed foreground write.
2. Error and callback races in asynchronous write reaping; stalled
   dm-io, watchdog, upper BIO exactly-once completion, and backing
   buffer lifetime.
3. REQ_FUA and REQ_PREFLUSH postconditions on real block infrastructure.
4. Root-owned process containment and independent kernel I/O
   quiescence before teardown.

No production device or swap operation is authorized by this
qualification. No module, loop device, DM table, NBD server, swap,
physical media, pressure run or privileged cleanup is exercised.
The V2.2 strategy and batch-size winner remain **UNDETERMINED**.

## Exact kernel-only source qualification

The dedicated
[Rootless kernel source contracts CI run 38034762176](https://github.com/k1moradi/swapz/actions/runs/38034762176)
passed on executable SHA
`ea41bae05b23d62128013864229ebf9a28658a46`.
It ran 21 exact-C generation transaction tests, 30 kernel-range
tests, 17 GC source snapshot tests and 15 GC compressed-payload tests.
The workflow is triggered on kernel source, these contract tests,
and its own definition.

Cross-system combined/teardown remained unqualified at that point:
Codex's simultaneously introduced supervisor worker-row shape
conflicted with the strict
`tests/runtime/recall-ipc-adapter.py` consumer, producing
`worker result has incorrect fields` before the kernel gate ran.
The isolated workflow specifically prevents unrelated
workstream development from blocking source-level kernel evidence;
it does not waive future combined/teardown qualification.
