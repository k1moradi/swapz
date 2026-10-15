# V2.2 prior-generation scan: bounded pending-pack ownership admission

## Finding and provenance

Current baseline before this change:
`3a623c17ab19fd09ea34aae618e92bde0f375f35`.
PR #12 had established an independent pending compressed-BIO ownership
ledger, bounded identity admission on append/flush, and independent
failure completion. Codex's latest native Linux evidence, **132/132**
rootless methods and a warning-free kernel C `W=1` build, was pinned to
older `8d86a96b22d5a8d2dc8d261251f20c3d94406dbe` (PR #9 code).
It does not qualify PR #12 or this generation-scan change.

One earlier-read path was still outside the PR #12 guard.
`swapz_process_write()` calls `swapz_commit_previous_generation()`
*before* advancing the generation. That function first called
`swapz_page_has_uncommitted_generation()`, whose raw
`for (record_index < pack_record_count)` indexes `pending[]`.
An oversized fault-injected count may reach past the 64 allocated
records before pack append/flush can reject it. A zeroed/truncated
count may hide an accepted previous-generation upper BIO and permit
a new generation to become authoritative.

No source path in the serialized worker has been demonstrated to
produce a malformed count in ordinary operation. The defect model
is explicitly controlled in-memory metadata corruption.

## Minimal production repair

`swapz_commit_previous_generation()` first checks the existing
`swapz_pack_bios_match(context)` from PR #12. That checker bounds
`pack_record_count` to 64, validates each resident descriptor's
slot index, and establishes an exact one-to-one association for
non-NULL upper BIOs with the independent `pending_bios` ledger.
The preflight runs **before** the staged-ref fast path and before
the first pending-array scan. On mismatch, it sets the target failed
with `-EUCLEAN` and returns that error; the caller returns before
incrementing `generations[logical_page]`, copying the new BIO
payload or modifying a mapping. The existing serialized failed-target
worker path completes accepted pending owners independently.

Healthy staged references, GC-only NULL upper BIO records, ordinary
rewrites and generation wrap keep their existing semantics.
No changes to the on-disk format, allocations, per-BIO structures,
or lower asynchronous I/O lifecycle are required. This guard adds
O(pack records + registered pending upper BIOs), at most 64 each,
to the foreground write's previous-generation decision; a real
loaded-kernel performance cost has not been measured.

## Executable source-contract counterexamples

`tests/runtime/swapz-generation-scan-pack-preflight-contract-test.py`
extracts and compiles verbatim production implementations of:

- `swapz_pack_bios_match()`
- `swapz_page_has_uncommitted_generation()`
- `swapz_commit_previous_generation()`
- `swapz_process_write()`

Userspace list and lower-storage seams are deterministic; no
real device access or privileged operations occur.

A deliberate *old-code mutant* removes only the new guard from
the compiled production rewrite barrier. With an accepted upper
BIO in `pending[0]` but `pack_record_count=0`, the mutant accepts
a new generation and leaves the previous BIO independently owned
and outstanding. With an oversized count of 65, the mutant sees
a valid matching prior generation in a deliberately allocated
canary at logical `pending[64]`. The canary backing is larger
than production's 64-record array, so these tests do **not**
actually read out of bounds. The repaired code rejects both
cases with `-EUCLEAN` before calling the scanner or modifying
the generation.

Positive and adversarial cases cover valid empty and full
64-record packs, prior record at a later slot, stale/current
staged references, unrelated-page records, GC-only NULL BIOs,
record slot corruption, owner coordinate/pointer corruption,
prior flush failure, and generation wrap. Existing exact-production-C
foreground transaction/GC tests enforce ordering and retain their
healthy-case seam; the dedicated generation-scan harness compiles
the real pending-pack identity checker.

The new suite is mandatory in kernel source, combined and teardown
rootless workflows, with source-trigger coverage and an executable
gate-removal mutation test.

## Limits

Independent ledger pointer corruption and coordinated mutations
that preserve all identities are outside this supported fault model.
The asynchronous teardown lifetime limitation remains: a lower
callback that never arrives cannot be safely treated as having
released its buffer simply because a timeout elapsed. This PR does
not modify watchdog or teardown lifetime semantics.

No native Linux module build of this new SHA, loaded module, real
swap/DM/NBD/loop device, privileged fault injection or performance
qualification is claimed. V2.2 strategy and batch-size winner
remains **UNDETERMINED**.

## Exact commit and workflow qualification

[PR #13](https://github.com/k1moradi/swapz/pull/13) merged as
[`9bb280588a2f0f4ffcc7764ab616ee873fed5352`](https://github.com/k1moradi/swapz/commit/9bb280588a2f0f4ffcc7764ab616ee873fed5352).
All four applicable rootless workflows passed on the PR head
`0f12ccf79607fdd14dea4a712502f587d847b534`:

- [Kernel source 38065446412](https://github.com/k1moradi/swapz/actions/runs/38065446412): **PASS**
- [Combined source 38065446448](https://github.com/k1moradi/swapz/actions/runs/38065446448): **PASS**
- [Teardown safety 38065446416](https://github.com/k1moradi/swapz/actions/runs/38065446416): **PASS**
- [NBD source safety 38065446429](https://github.com/k1moradi/swapz/actions/runs/38065446429): **PASS**

The four **exact post-merge** workflows on the executable merge SHA
also passed:

- [Kernel source 38065599090](https://github.com/k1moradi/swapz/actions/runs/38065599090): **PASS**
- [Combined source 38065599097](https://github.com/k1moradi/swapz/actions/runs/38065599097): **PASS**
- [Teardown safety 38065599100](https://github.com/k1moradi/swapz/actions/runs/38065599100): **PASS**
- [NBD source safety 38065599105](https://github.com/k1moradi/swapz/actions/runs/38065599105): **PASS**

Kernel source CI reports **13/13** new generation-scan methods
(including both deliberately unguarded mutants) and **22/22**
foreground generation/GC methods. These are rootless source-contract
results, not native module or real-device qualification.

At the time of this audit, Codex had been assigned separate native
Linux validation of the older PR #12 executable revision; that result
has not been provided in this turn. Neither that assignment nor its
PR #9 native report qualifies the newly changed PR #13 source.
