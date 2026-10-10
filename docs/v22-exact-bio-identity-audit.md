# V2.2 exact upper-BIO identity admission

## Source identity and independent native baseline

Lead-developer source audit started at
`24e2794b173a405c9f9ccfe739c4f733ebc41508` after PR #8.

Codex independently validated that baseline on Ubuntu 26.04.1 LTS,
kernel `7.0.0-38-generic`, GCC 15.2.0, matching headers
`7.0.0-38.38`: seven rootless suites, **92/92** Python methods
PASS, and native `W=1` module build PASS with no C-source warnings.
Compiler-name and missing pahole/BTF warnings were environmental.
The native build did not load the module, and it does not qualify
the later executable identity change developed in this branch.

## Demonstrated gap

PR #8 introduced independent `owned_bios` lists and a bounded
finalization check comparing non-NULL `record->bio` count to the
number of registered BIO owners.

Counts alone do **not** establish ownership identity. A late
in-memory mutation replacing the second descriptor's BIO with the
first produces two non-NULL record pointers and two registered owners,
yet normal success or failure processing would complete the first
BIO twice and strand or miscomplete the second. Swapped pointers
and records referencing a different buffer's BIO produce similar
identity faults without changing the count. This is a controlled
malformed-metadata fault model; no normal-operation corruption
trigger was demonstrated.

## Repair and cost

The existing per-BIO `dm_per_bio_data` owner structure now holds
two small slot indices (`block_index` and `record_index`).
The serialized worker fills these indices during ownership transfer
to a stream buffer. The compactor updates them whenever it moves a
pending BIO's descriptor to a new physical batch slot.

`swapz_stream_bios_match()` performs two bounded read-only passes
over resident records and independently trusted owner nodes:

1. Count non-NULL record BIO pointers and reject a completed record
   that still carries a pending pointer.
2. For each registered owner, check its slot is within the validated
   batch and that the slot's record points to **that same BIO**.

The passes also reject count mismatch and out-of-capacity metadata.
No untrusted descriptor BIO pointer is dereferenced to establish
owner identity; the list is the trusted separate ownership source.

The checker runs before either success or lower-write-error
finalization mutates any mapping, staged reference or upper BIO.
It also runs **before compaction** begins altering blocks or
consulting their BIO pointers to update owner locations.
A mismatch sets the target failed; the existing independent
failure-completion path drains registered BIOs once, without
following malformed record pointer identities.

The checker is O(resident records + pending BIO owners).
Each per-BIO node grows by two `u8` indices (actual struct padding
and total memory cost depend on ABI); no hot-path allocation,
persistent format change, hash, O(N²) identity scan, device I/O or
new callback-side metadata mutations are required. Runtime overhead
has not been measured with real loaded-kernel workloads.

## Rootless exact-production-C test evidence

The existing `swapz-upper-bio-ownership-contract-test.py` now
compiles `swapz_stream_bios_match()` verbatim and executes controlled
duplicate, swapped and cross-buffer pointer mismatches, lost pointers,
stale location, already-completed staged writes, plus valid and
legitimately relocated owner slots. An executable count-only mutant
accepts the duplicated pointer as a counterexample.

`swapz-async-reap-contract-test.py` compiles the exact validator
together with actual finalization/reaper functions. It tests that
same-count pointer faults on lower success and lower error cannot
publish mappings, reset the failed buffer, strand upper BIOs or
complete them twice. Existing watchdog and late-callback tests
remain mandatory.

`swapz-compaction-container-contract-test.py` now compiles the
identity checker with the real repacker and exercises an actual
two-block compressed merge where a pending BIO's owner moves to
the new descriptor slot and final identity verification succeeds.
The FUA staging harness models the updated registration signature.

No standalone new test file or workflow steps were needed: all
modified executable suites are already mandatory in kernel,
combined and teardown rootless CI.

## Limitations and qualification boundaries

An independent owner list must itself remain intact. Arbitrary
corruption of `dm_per_bio_data` or the intrusive list, pointer
lifetime violations, and modifications to both owner coordinates
and record data that preserve the complete identity relation are
outside the supported recovery model.

A real loaded-kernel callback, live GC churn, swap pressure,
device power failure and the performance cost of extra identity
checks have not been qualified by rootless tests. Codex's native
build report covers the older executable PR #8 SHA; this
identity change requires separate native Linux compilation before
claiming native qualification. Do not infer durability or strategy
selection from these source contracts. V2.2 strategy/batch winner
remains **UNDETERMINED**.

## Revision-specific workflow evidence

The executable identity fix merged in
[PR #9](https://github.com/k1moradi/swapz/pull/9) as
[`89c4aeedb7632913e91c8c530fb7af679b3b7a13`](https://github.com/k1moradi/swapz/commit/89c4aeedb7632913e91c8c530fb7af679b3b7a13).
All three applicable **exact post-merge rootless workflows** passed:

- [Kernel source 38060222060](https://github.com/k1moradi/swapz/actions/runs/38060222060): **PASS**
- [Combined source 38060222088](https://github.com/k1moradi/swapz/actions/runs/38060222088): **PASS**
- [Teardown safety 38060222038](https://github.com/k1moradi/swapz/actions/runs/38060222038): **PASS**

The standalone NBD source workflow was not triggered by this
kernel-only change; NBD rootless coverage is included in combined.

A post-merge review caught a missing Python method for scenario 23:
the new real two-block compressed repack was compiled but had not
actually been executed by the PR #9 test selection. This was not
counted as prior execution. [PR #10](https://github.com/k1moradi/swapz/pull/10),
merged as `a49d9dcc2fb12ac6be0d8541778307b226aa3df9`, adds an
explicit `test_real_repack_updates_pending_bio_owner_slot` method.
Its exact head `02eb175b56a1d47cc16184b94403a253eb2cc8a3` passed
[kernel 38060310127](https://github.com/k1moradi/swapz/actions/runs/38060310127),
[combined 38060310069](https://github.com/k1moradi/swapz/actions/runs/38060310069),
and [teardown 38060310111](https://github.com/k1moradi/swapz/actions/runs/38060310111).
On the PR #10 merge SHA, [kernel 38060472581](https://github.com/k1moradi/swapz/actions/runs/38060472581)
and [teardown 38060472580](https://github.com/k1moradi/swapz/actions/runs/38060472580)
passed, while [combined 38060472567](https://github.com/k1moradi/swapz/actions/runs/38060472567)
**FAILED** in an unrelated pressure-checkpoint publication race on
repeat 2/10. This failed run remains in the qualification record.

The pre-existing `pressure_checkpoint.py` publisher atomically links
its complete temporary marker into its final filename, then unlinks the
temporary name. A concurrent reader could reject the legitimate marker
during its brief `st_nlink == 2` interval. [PR #11](https://github.com/k1moradi/swapz/pull/11)
implements a bounded retry that **never accepts two links**, while a
permanent hardlink or nonregular marker remains denied. Deterministic
rootless tests cover both cases. PR #11 merged as
[`4e68d9bcfd05ffec8f4785a073c3656735304320`](https://github.com/k1moradi/swapz/commit/4e68d9bcfd05ffec8f4785a073c3656735304320).
Its exact post-merge [combined 38060923597](https://github.com/k1moradi/swapz/actions/runs/38060923597)
and [teardown 38060923539](https://github.com/k1moradi/swapz/actions/runs/38060923539)
workflows **PASS**, including the pressure-token repeat stage.

Neither PR #10 nor PR #11 changed `kernel/dm-swapz.c`: the
qualified executable kernel driver remains at PR #9's merge SHA.
Codex's last native Linux report qualified the earlier PR #8
executable revision `24e2794b`, not PR #9. New native Linux
compilation and real loaded-kernel/device qualification remain
outstanding; V2.2 winner is **UNDETERMINED**.
