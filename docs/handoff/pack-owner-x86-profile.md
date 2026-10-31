# Native x86 owner profile: distinguish the RAM backend from packing

A new fixed three-pair production-C diagnostic completed through `make fast_test`
on the native Lenovo/i7 host. All six owned raw/target arm byte oracles passed.
There are six complete, nonoverlapping root-native GO-to-final-fsync gates;
emitted sample counts match capture populations, no profiler loss diagnostic
was emitted, and all module frames resolve. Exact ELF, live section snapshots
and hashes were preserved; the ELF hash remained unchanged across the run.
Production C remains qualified `545defa8` with SHA-256
`78f2d7de073a644c9c4182a0865e57ebdfce8b6d07cc02a4ae5578a8cd3d569a`.
No production code or protocol policy changed.

This is attribution, not a performance comparison. All three rows are NOISY
because raw-repeat WRITE spread reached 16.0%. No useful-service gain, regression
or equivalence follows. Cycle-weighted stack samples and IRQ-inclusive scheduled
work-function intervals are not nanosecond phase budgets or exact uninstrumented
CPU. Hardware stacks are bounded to 40 frames; owner populations are conditional
on containing an observed swapz_worker ancestor. Profiling itself contributes
work. Source/inline return-PC locations identify context, not exact line cost.

## What the source resolution adds

Across 1,019 samples containing swapz_worker, a separate, exclusive stack-presence
partition gives:

| Observed owner ancestry | Samples |
| :--- | ---: |
| null_blk backend present | 165 |
| dm_io path without observed null_blk backend | 39 |
| Other owner stacks | 815 |

Do not add this partition to the independent function-category partition.
The backend population includes 44 samples at _raw_spin_lock_irq, 25 at
__rmqueue_pcplist, 22 at kernel_init_pages, 11 at rmqueue_bulk and six at
__refill_objects_node. Captured stacks run through null_insert_page,
copy_to_nullb, null_transfer and null_queue_rq before returning through dm_io
and the swapz owner. Inline source chains place most of this population beneath
swapz_submit_inflight_write/swapz_flush_window. These are lower RAM-device
allocation/initialization, tree/locking and transfer costs, not automatically
swapz packing or dm_io descriptor-allocation cost. They are about 16.2% of the
observed owner samples, not 16.2% of exact CPU or a recoverable service gain.

The ordinary exclusive labeler still assigns 266 owner samples to pack/stage
ancestry, illustrating why that broad category must not be treated as a pure
packing implementation budget. Leaf/context examples elsewhere include memcpy
at inlined admission/staging (36 samples), encoded append (24), READ handling
(21), and transaction staging (five), as well as decoding, CRC and scheduler/
completion work. Inline chains and offsets are retained to review operations
before proposing edits; optimized debug locations alone do not justify a change.

Source review confirms that codec sealing already clears only the unused gap,
private planner uniqueness reuses the batch proof, and active transaction
snapshots already limit protected/copy bytes. Do not repeat those settled ideas.
The rejected direct-BIO experiment cannot eliminate null_blk's own backing-page
allocation merely by bypassing dm_io, so this evidence alone does not reopen it.

## Next bounded question

The private pair helper creates separate newly owned 64MiB memory-backed devices.
Ordinary mixed tests prefill logical input but do not materialize every physical
backing page before timing. Raw overwrites a bounded logical working set, while
swapz's circular append allocator can first-touch new lower pages. ID36 already
materializes both owned devices before entering its constrained cgroup; that
special resource protocol is not the ordinary performance protocol.

Measure this model sensitivity with unchanged production C: compare fresh
backing against full backing materialization before setup/timing, applying the
same treatment to BOTH the raw device and the swapz backing. Keep new device
ownership, target/allocator state, workload/input hashes and service geometry
matched. Fix order, samples, endpoints, floor and exclusions before collection;
preserve cold and materialized results separately from qualified history.
This is a host/model sensitivity study, not a product optimization or proof of
physical-media fidelity. Allocation ancestry is not evidence of RAM-bandwidth
saturation. Do not retune or prewarm only one arm to manufacture a desired rate.
Further C selection needs the resulting model context and actual product work.

## Artifacts

- [Readable attribution, populations and hashes](pack-owner-x86-profile.json)
- [Complete diagnostic packet](pack-owner-x86-profile.json.gz): all three reports,
  gates, resolved owner samples, source-relative inline locations and scripts.

Raw IP stacks, the saved ELF and kernel symbol snapshot remain ignored locally
under build/optimization-round/pack-owner; the packet records their hashes and
resolved evidence rather than committing a generated module. No test mappings
remain. This diagnostic generated no owner report/history point or plot; this
computer's identified qualified history still ends at source 545defa8, report
3465b4c08987. Other machines and these unqualified measurements remain separate.
