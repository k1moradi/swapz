# swapz V2.2 kernel logical-range preflight audit

## Confirmed source-level defect and correction

The previous swapz_process_discard loop validated bounds only immediately
before each page's generation increment and mapping invalidation. A discard
crossing the exported logical end could invalidate earlier live pages before
the later range error was returned. Read/write/discard also narrowed the
sector_t page quotient to u32 before checking the logical-pages limit,
which could alias high malformed sector offsets to live mappings.

The correction adds two pure production C guards:
- swapz_checked_page_index validates full-width sector_t alignment and
  logical page bound before narrowing to u32. Both read/write paths check
  this before touching staging or generations.
- swapz_checked_discard_range rejects unaligned starts and lengths, then
  validates the *entire* range with subtraction after checking the start
  bound, avoiding addition overflow and partial invalidation. The discard
  handler invokes it before staging the pending pack, changing generations,
  clearing staged references, or invalidating mappings.

An aligned zero-length discard retains its previous successful no-op
behavior. GC, persistent formats, and other pipeline behavior are unchanged.

## Exact C guard execution (rootless)

The tests/runtime/swapz-kernel-range-contract-test.py suite extracts
the two pure helper bodies verbatim from checked-out kernel/dm-swapz.c.
It compiles only those helpers as a short-lived user-mode C shared
library and tests actual production C arithmetic via Python ctypes.
It covers page/sector boundaries, partial-page discard, crossing-end
ranges, full-extent discard, U32 wraparound, U64 high-sector cases,
and exact-end zero-length cases. Two negative mutants show regression
detection if an inclusive bound or tail check is weakened.

Source-anchored tests also require preflight checks before data mutation,
previous-generation commit before increment, staged success publication
only for current generation, GC batch flush and zero-live victim
verification before reclaim, and pack-to-batch-to-lower flush ordering.
These structural checks are not execution of the kernel or real DM I/O.

Both joint workflows now require the bounded C-contract test and are
triggered by changes to kernel/dm-swapz.c. The workflow contract refuses
a silently dropped source trigger or source-test execution.

## Explicit limits

This qualifies arithmetic of extracted pure functions on a simulated
64-bit sector_t and selected source-level ordering invariants. It is
NOT a whole-module kernel build, actual block I/O, KUnit, concurrent GC
stress test, real FUA/flush durability guarantee, privileged containment,
physical benchmarking, or backing-release authority. No module, device,
swap, discard, or destructive operation was performed.

Next source-only priorities include GC relocation and generation races,
mapping publication on asynchronous failures, and flush/FUA semantics.
Production prerequisites remain independently trusted owner and collector,
kernel quiescence evidence, and separately authorized disposable
device tests. V2.2 strategy and batch winner remain UNDETERMINED.
