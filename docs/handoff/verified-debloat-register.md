# Verified de-bloat register (source-pinned, editorial only)

**Audited source:** [`4c4fc4446e57ed25b491125a2d8941ddf8555559`](https://github.com/k1moradi/swapz/commit/4c4fc4446e57ed25b491125a2d8941ddf8555559)
of `src/kernel/dm-target.c`, blob
`a67d0b1c1e19f969f5f188121171da40d6037905`. Independent re-audit confirmed
that the then-current `main` still used this exact blob. Evidence below verifies overlapping code or
a false-positive candidate by source inspection. It does **not** prove
functional equivalence, unreachable code, production readiness, performance,
loaded-kernel behavior or physical PASS. This file is a review queue, not an
implementation order. Production-C changes require explicit approval by the
owning kernel agent and an equivalence regression. The source and tests remain
the authority for behavior; [first-error triage](../README.md#diagnose-the-first-record)
is the diagnostic entry point.

## P2. RAW BIO snapshot, codec and publication duplication — DEFER

**File/functions:** `src/kernel/dm-target.c`:
`swapz_submitter_prepare_payload()` ([source](https://github.com/k1moradi/swapz/blob/4c4fc4446e57ed25b491125a2d8941ddf8555559/src/kernel/dm-target.c#L3348-L3470)) and
`swapz_preparation_worker()` ([source](https://github.com/k1moradi/swapz/blob/4c4fc4446e57ed25b491125a2d8941ddf8555559/src/kernel/dm-target.c#L3523-L3753)).

**Redundancy evidence:** both map a pinned input with
`swapz_map_single_bio_input()` or fall back to
`swapz_copy_bio_accounted()`, initialize RAW/encoding/CRC fields, call
`swapz_compress_prepared_page()`, update LZ4 size bins and publish the
terminal preparation result.

**Correctness risk:** submitter has a one-reference slot and release-gated
consumer; the background worker has two references and a `queue_lock`
descriptor handoff. Fault category, RAW-selected races, first-error election,
wakeups, and access after `preparation_snapshot_ready` differ.

**Owner:** owning kernel agent for `src/kernel/dm-target.c`; no named owner is identified by repository metadata in this audit, so explicit agreement is still required.
**Equivalence regression:** byte-exact single-/multi-bvec snapshots, CRC and
fault results for both routes; race RAW-selected/CANCELLED/retire/drain and
producer-first/consumer-first teardown using existing
`tests/runtime/native/io/preparation-publication-lifetime.c` and
`preparation-slots.c`, then source-matched loaded RAM execution.
**Safe disposition:** retain both, no C extraction.

## P2. Preparation telemetry field folds — DEFER

**File/functions:** `swapz_preparation_totals_snapshot()`
([source](https://github.com/k1moradi/swapz/blob/4c4fc4446e57ed25b491125a2d8941ddf8555559/src/kernel/dm-target.c#L1150-L1185)) and `swapz_submitter_totals_snapshot()`
([source](https://github.com/k1moradi/swapz/blob/4c4fc4446e57ed25b491125a2d8941ddf8555559/src/kernel/dm-target.c#L1187-L1218)).

**Redundancy evidence:** both zero the totals, walk bounded lane arrays and
sum delta64, LZ4 bins, copied bytes and CRC using `READ_ONCE`.

**Correctness risk:** different lane structures/counts, CPU/wall field names
and background-only lower-write-overlap fields; a generic loop could silently
alter diagnostic aggregation or concurrent sample semantics.

**Owner:** owning kernel agent for `src/kernel/dm-target.c`; no named owner is identified by repository metadata in this audit, so explicit agreement is still required.
**Equivalence regression:** per-field asymmetric golden values, zero and max
lane counts, simultaneous updates, unchanged status output and no lost fields.
**Safe disposition:** defer aggregation consolidation.

## P3. Lower WRITE queue and completion counters — DEFER

**File/functions:** `swapz_submit_inflight_write()` ([source](https://github.com/k1moradi/swapz/blob/4c4fc4446e57ed25b491125a2d8941ddf8555559/src/kernel/dm-target.c#L2148-L2248)),
`swapz_lower()` ([source](https://github.com/k1moradi/swapz/blob/4c4fc4446e57ed25b491125a2d8941ddf8555559/src/kernel/dm-target.c#L2453-L2631)),
`swapz_async_lower_write_done()` ([source](https://github.com/k1moradi/swapz/blob/4c4fc4446e57ed25b491125a2d8941ddf8555559/src/kernel/dm-target.c#L2025-L2071)).

**Redundancy evidence:** the paths count queued preparers at submit/end,
record nonempty transitions and wake workers during lower WRITE service.

**Correctness risk:** synchronous service uses an active flag, detached service
an active count, and callback completion publishes `lower_done` under
`queue_lock` after electing the original lower errno. Same-looking
accounting blocks do not establish interchangeable ordering.

**Owner:** owning kernel agent for `src/kernel/dm-target.c`; no named owner is identified by repository metadata in this audit, so explicit agreement is still required.
**Equivalence regression:** sync/detached success and submission/callback
errors under concurrent preparation and teardown; compare queue counters,
first errno, wakeups, active count and no post-completion target access.
**Safe disposition:** retain existing ordering and code.

## P3. Similar BIO fast checks — REJECT AS DE-BLOAT

**File/functions:** `swapz_copy_bio()` ([source](https://github.com/k1moradi/swapz/blob/4c4fc4446e57ed25b491125a2d8941ddf8555559/src/kernel/dm-target.c#L2963-L3000))
and `swapz_map_single_bio_input()` ([source](https://github.com/k1moradi/swapz/blob/4c4fc4446e57ed25b491125a2d8941ddf8555559/src/kernel/dm-target.c#L3007-L3032)).

**Evidence:** both inspect a one-block vector, but the former copies in
either direction and supports segmented fallback. The latter maps a zero-offset
single-vector **input** only while upper-BIO ownership remains valid,
returning NULL for copy fallback. Neither is unreachable or redundant.

**Owner:** owning kernel agent for `src/kernel/dm-target.c`; no named owner is identified by repository metadata in this audit. **Regression if revisited:** nonzero
bvec offsets, segmented BIO, invalid sizes, copy directions, pin/map lifetime
and exact byte equality. **Safe disposition:** retain both helpers.

No production C or comments were changed, no new abstraction or dependency
was introduced, and no kernel deletion was proved safe. Revisit only after
owner agreement plus regressions and standard source-bound `make test`.
This audit does not convert rootless/CI/VM evidence into an owner-host loaded
or physical qualification. The dedicated first-host `/dev/sda1`,
separately scoped Codex 2 `/dev/sda4`, and owner's ARM64/NEON VM remain
distinct; see [device scope](../AGENT_CONTEXT.md) and
[qualification contract](../testing_standards.md).
