# Direct detached lower WRITE draft — unapplied and unvalidated

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands; the sole owner-approved exception is the development decision loop `make fast_test`, which never qualifies a source, never writes or publishes `test_results.json` and never replaces `make test`. Private scripts and CI jobs are implementation details, not operator interfaces.

Inspected installed Linux 7.0.0-42 headers/Module.symvers and upstream v7.0
block/bio.c, block/blk-core.c and drivers/md/dm-io.c, fetched from
kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux at refs/tags/v7.0.
Primary sources: [bio.c](https://github.com/torvalds/linux/blob/v7.0/block/bio.c),
[blk-core.c](https://github.com/torvalds/linux/blob/v7.0/block/blk-core.c), and
[dm-io.c](https://github.com/torvalds/linux/blob/v7.0/drivers/md/dm-io.c). Kernel distribution changes
and other build hosts still need checking. This is not performance evidence.

The separate lower callback lifetime repair is source 2aa3ba0. Its owner run
was intentionally stopped for the reported busy host (BLOCKED report ff66c70).
The original ARM64 host remains on hold. Qualify that production C on the new,
free x86 host before activating this draft. Verify the new host is quiet enough
for performance work; do not transfer the ARM64 hold to the free machine.

Candidate scope, once the repair qualifies:

- Replace only swapz_submit_inflight_write's detached WRITE dm_io adapter.
  Synchronous four-record/RAW/GC/flush and all READ adapters remain unchanged.
- Keep one immutable lower run, the existing engine.bulk_scratch/bulk_txs,
  original engine pause/resume/publication and all upper completion ownership.
  The existing vzalloc scratch is page-aligned and at most 64*4096 bytes.
- Embed one struct bio plus 64 struct bio_vec metadata entries in the existing
  in-flight owner. This is descriptor preallocation, not another data buffer.
  Confirm compiled context size and allocation size-class before any RAM claim.
- bio_init with NULL bdev after the run buffers are established; track whether
  initialized so constructor-failure cleanup does not uninitialize garbage.
  bio_uninit after both workqueues/lower owners are joined and before releasing
  backing. bio_reset for each reuse, only after the previous run is finalized.
- Set WRITE|REQ_SWAP and default priority before bio_add_vmalloc. That helper
  performs vmalloc-to-page construction and WRITE cache flushing; a manual page
  loop must not silently omit the latter on architectures where it matters.
  Validate 1..64 blocks and the original owned scratch address before mapping.
- submit_bio, like dm_io, rather than changing accounting via submit_bio_noacct
  or enabling polling. Core queue limits may split the BIO; the callback must
  accept completion only for the whole parent and map every nonzero bi_status,
  including unsupported status, to failure of the entire reserved run.
- bio_endio invokes bi_end_io only after chained remaining refs finish and does
  not access the BIO after that callback returns. The callback must copy status
  and private owner before publishing done, and finish all target notification
  under the repaired queue_lock gate. Never access the BIO/slot after release.
- Preserve write_fault_nth at the original pre-submission boundary. No fake
  completion or success publication on BIO construction/submission failure.
- Preserve timing scope: original lower_start_ns precedes dm_io's allocation
  and mapping. Moving BIO construction ahead of that timer would shrink the
  service EWMA by definition and alter dispatch policy; include construction in
  the equivalent timed/accounted adapter interval and use a checked rollback
  with no callback if construction fails. Independent lower statistics remain
  authoritative for actual device traffic.
- The adapter can avoid dm_io io-object/BIO-pool allocation/free, but the block
  layer can still allocate/split/throttle. Do not claim allocation-free storage
  submission or an exact removable 2-us budget from earlier trace wall.

Required evidence before retention: native actual-body callback/rollback and
reused descriptor tests; owned multi-page and forced-split completion/error
coverage; mixed medium/balanced/entropy byte oracles; actual detached use;
fixed screened counterbalanced service/lower-I/O/p99 comparisons; full exact-
source make test, suspend/drain, retained failures and ID36. Keep rejected
probe/control code out of the hot path. No change to on-disk SWZ or allocation
fairness, and no physical-device or active-swap admission.

## Static draft state

The unapplied [patch](direct-lower-write.patch) changes only production
dm-target.c and its source-contract tests. The [manifest](direct-lower-write-state.json)
preserves the base/candidate C and patch hashes. The original generator, full
before/after snapshots and old traces remain ignored on the ARM64 host; applying
this portable patch does not depend on them. Python AST parsing and git apply --check are static
checks only; no C compiler, unit test, loaded device, benchmark or plotting was
run for this draft. Kernel main remains unchanged and clean.

The actual-body test draft covers bounds/null scratch, the owned scratch pointer,
pre-submission fault injection, failed BIO construction rollback without a fake
callback, inline successful/failed completion (submission still returns accepted),
delayed completion, refusal to reuse an outstanding descriptor, and reuse only
after owner reaping. The callback drain-gate test now receives BIO statuses;
READ/synchronous dm_io ABI checks remain in place. Tests themselves are unrun.

Adapter submitted-work counters retain their earlier attempt scope on fatal
construction failures; they are not independent physical-device I/O evidence.
The block layer may allocate or split even with a preallocated parent BIO.
A fully retained candidate still needs actual forced-split lower completion and
error coverage, compilation on both host architectures, fixed statistical
performance confirmation and full owner qualification. No speed or RAM saving
has been established by this draft.

Static review added immediate bio_uninit on construction failure to release
the association acquired by bio_reset before returning the unsubmitted run.
The native draft checks this cleanup without inventing a completion callback.

## Remaining loaded verification

No forced-split loaded phase has been added to the patch. The existing
`device-roundtrip.c` parallel writer uses `pattern()`, which includes full-entropy
pages as well as zero, medium and text pages. It can be reused; a separate
all-RAW parallel writer is not automatically necessary. However, fixture content
alone does not prove a multi-block parent was actually submitted.

On a freshly positively owned RAM null_blk device, a dedicated correctness phase
may lower that device's queue `max_sectors_kb` to 4 and verify the accepted value.
Prove at least one direct parent exceeds one block, then verify completion of
all split work, exact final bytes, one completion owner, error propagation,
suspend/drain and descriptor reuse. Include a genuine supported lower error
path if available; a pre-submission fault does not exercise split-child failure.
Do not change unrelated queues or performance profiles, and do not claim that
this coverage already exists. Check receiving-kernel headers and supported
configfs/queue/fault facilities before selecting the adapter.
