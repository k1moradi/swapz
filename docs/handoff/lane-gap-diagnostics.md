# Work order: lower-lane gap attribution (ROADMAP ID178)

Implementer: external agent. Reviewer: lead developer. Owner runs loaded tests.

## Why

On the x86 and ARM64 owner reports (`9123b811` / `7ff94fd4`) the SATA and NVMe
mixed envelopes lose 22-54% to raw while saving 28-30% of lower bytes and
84-91% of lower requests. The single K=1 lower-WRITE lane is busy only 38-76%
of measured wall, and the interval from one lower WRITE completing to the next
one starting is ~31-35 us per run on x86 (~40-59 us on ARM64) regardless of
device. Existing counters attribute only 14-35% of that interval
(`pipeline_post_lower_wall_ns`, `accepted_work_lower_idle_*`). Leading
hypothesis: single-lane pipeline recovery. It is not proven, and the next
mechanism (seal-ahead, owner pickup, upper round trip, or finalization) depends
on which part of the gap dominates. This round measures that gap exactly. See
ROADMAP "Current bottleneck ranking" item 1 and rows 176, 178-180.

## Hard scope

Observational only; the ID114 profiling rules in `docs/coding_standards.md`
apply. Allowed: `ktime_get_ns()` reads, owner-only plain counters, `atomic64_t`
counters on concurrent completion paths, new fields in `struct swapz_bio_ref`
and `struct swapz_dm`, status tokens, harness/report plumbing, tests, docs.

Forbidden: any read of the new state by policy, retention, close, ACK or
scheduling code; new waits, locks, queues, work items, timers or allocations;
changes to ACK timing, K, retention, close reasons, SWZ format or module
parameters; resetting cumulative counters; renaming anything (`swapz`,
`dm-swapz.ko`, `SWZ` and existing token names are immutable). Do not change the
existing `admitted_ns` / `write_admit_worker_*` semantics; add fields instead.

## Definitions

A *run* is one lower WRITE carrying a K=1 window: an asynchronously detached
run (`struct swapz_inflight_write`) or a synchronous window. For a successful
predecessor run P and the next run S submitted on the lane:

| Mark | Meaning | Async capture point | Sync capture point |
| :--- | :--- | :--- | :--- |
| t0 | P lower completion | `inflight->lower_end_ns` (endio callback) | return of the lower WRITE |
| t1 | owner observes P's completion | later of `swapz_finalize_inflight_write()` entry and its `wait_for_completion()` return | t1 = t0 |
| t2 | P publication finished | `finalize_end` after `swapz_engine_complete_batched_run()` | equivalent point after publication |
| a | earliest admission among S's WRITE BIOs | new per-BIO `lane_admitted_ns`, set in `swapz_map()` next to `admitted_ns` | same |
| s | earliest ordered ownership among S's BIOs | new per-BIO `lane_owned_ns`, set where `write_admit_worker_*` samples (ID175 dispatch: dispatch time) | same |
| t3 | S seal start | `inflight->commit_start_ns` in `swapz_flush_window()` | sync window prepare start |
| t4 | S lower submit | `inflight->lower_start_ns` in `swapz_submit_inflight_write()` | sync lower submit |

Put the arithmetic in a new pure header `src/kernel/lane-gap.h` (include
`codec.h`; add a `swapz_u64` typedef there in both the kernel and native
branches) so it is native-testable like `window-policy.h`:

```c
/* clamp(x, lo) = min(max(x, lo), t4) */
t1c = clamp(t1, t0);  t2c = clamp(t2, t1c);  ac = clamp(a, t2c);
sc  = clamp(s, ac);   t3c = clamp(t3, sc);
completion_wake  = t1c - t0;   publication = t2c - t1c;
no_work          = ac - t2c;   admitted_unowned = sc - ac;
staged_held      = t3c - sc;   seal = t4 - t3c;
```

The six parts sum to `t4 - t0` exactly. Any zero mark or `t4 < t0` is invalid
(no parts; count it). Work admitted before t2 gives `no_work = 0`; a successor
sealed before publication (seal-ahead) gives a short `seal`. Provide pure bin
helpers too: successor count bins `0, 1, 2-3, 4-7, 8-15, 16+` and dwell bins
`<=1us, <=4us, <=16us, <=64us, <=256us, <=1ms, >1ms` (boundaries inclusive).

## Counters (status tokens, differenced over the timed window)

1. **Gap partition.** `lane_gap_runs`, `lane_gap_wall_ns`,
   `lane_gap_completion_wake_ns`, `lane_gap_publication_ns`,
   `lane_gap_no_work_ns`, `lane_gap_admitted_unowned_ns`,
   `lane_gap_staged_held_ns`, `lane_gap_seal_ns`; outcomes for runs without a
   measured gap: `lane_gap_foreign_runs`/`lane_gap_foreign_ns` (any other lower
   WRITE, e.g. GC relocation or metadata, was submitted between t0 and t4: the
   whole gap goes to foreign, no parts), `lane_gap_unpaired_runs` (no valid
   predecessor: first run after an epoch, after a failed run, after
   drain/suspend), `lane_gap_invalid`.
2. **Successor availability at t0** (paired and foreign gaps):
   `lane_successor_admitted_by_completion_{0,1,2_3,4_7,8_15,16_plus}` counts S
   BIOs with `lane_admitted_ns <= t0`; `lane_successor_owned_by_completion_*`
   counts those with `lane_owned_ns <= t0`.
3. **ACK dwell (ID108).** Per successful WRITE BIO, store `published_ns` and
   `published_deferred` in `swapz_bio_ref` when its run's publication succeeds
   (immediate completion or `swapz_defer_upper_completion()`). In
   `swapz_complete()`, before `bio_endio()` and only for success, add
   `now - published_ns` to `ack_dwell_{deferred,immediate}_{count,ns}` and one
   bin `ack_dwell_{deferred,immediate}_{le_1us,le_4us,le_16us,le_64us,le_256us,le_1ms,gt_1ms}`.
   `swapz_complete()` runs on the worker and on `completion_work` concurrently,
   so these are `atomic64_t`, like `upper_write_completed_ok`.
4. **Owner READ annotation.** Owner wall inside the synchronous
   `swapz_process()` READ path that overlaps `[t2, t4]` of an open gap:
   `lane_gap_owner_read_ns`, `lane_gap_owner_reads`. Accumulate pending and
   commit only when the gap closes as paired. Overlaps the parts; not a part.
5. **Envelope host CPU.** `parse_storage_envelope_sessions()` in
   `tests/tools/run-tests.py` drops `host_cpu`; keep `host_cpu_record(obj)` per
   arm (verify io-replay emits it for envelope sessions).

Chronology state (predecessor t0/t1/t2, a valid flag, a foreign flag, pending
READ annotation) is owned by the ordered domain: the worker pass or an ID175
dispatch holding `ordered_owner`. Prove that for every writer. The
`profile_epoch` message may only `WRITE_ONCE()` the valid flag to false; the
owner reads it once with `READ_ONCE()` at t4, so an epoch race can only drop one
sample, never mix marks. Failure, drain and suspend clear it on the owner.

## Invariants (replay and report validators fail closed)

- `lane_gap_wall_ns == sum of the six parts`; `lane_gap_invalid == 0`.
- Each successor family sums to `lane_gap_runs + lane_gap_foreign_runs`, and
  for every threshold k, runs with owned >= k <= runs with admitted >= k.
- Each dwell family's bins sum to its count; `ack_dwell_deferred_count <=
  deferred_upper_completion_bios`; deferred + immediate counts <=
  `upper_write_completed_ok`.
- `lane_gap_runs + lane_gap_foreign_runs + lane_gap_unpaired_runs +
  lane_gap_invalid` equals runs submitted in the window (use an existing
  submission counter; add `lane_runs_submitted` only if none exists).
- Missing tokens are an error, never zero. All of this is descriptive: no gate,
  exit code, scorecard or publication decision may read the results.

## Plumbing

- `src/kernel/dm-target.c`: tokens in one new `DMEMIT` block next to
  `accepted_work_lower_idle_*`; do not grow the `swapz_status` stack frame (no
  local arrays; read atomics directly into the arguments). Report the status
  line length before/after on one host.
- `tests/runtime/benchmark/io-replay.py`: add the fields to the kernel WRITE
  snapshot list (timed deltas) and the validators.
- `tests/tools/run-tests.py`: per swapz arm a `lane_gap` object in mixed,
  storage-envelope and write-saturation sessions; `benchmarks.lane_gap_attribution`
  rows; one compliant console table **"SSD lower-lane gap attribution"** for
  the SATA/NVMe4/NVMe5 envelopes plus fast mixed: runs, gap/run (us), share of
  each part (%), successor >= 1 admitted at t0 (%), deferred-ACK p99 as the
  bin upper bound, host busy. Label percentiles as bin bounds.
- `tests/tools/fast-test.py`: print the same table for swapz arms and keep it
  in `latest.json`, so the follow-up A/B can iterate in `make fast_test`.
- Plots: none new; confirm `plot-history.py` ignores the new fields.

## Tests and docs (same commit as the code)

- Native `tests/runtime/native/io/lane-gap.c`, wired into
  `tests/suites/Makefile` (`PROGRAMS`, `_SRC`, `_HDR`, `test-lower-io`): every
  mark ordering (work before t0, after t2, `s < a`, `t3 < s`, `t3 < t2`), exact
  sum identity over an exhaustive small grid, each invalid case, and every bin
  edge (e.g. 1000/1001 ns, 15/16 records).
- `tests/runtime/native/source-contract-test.py`: new state is referenced only
  by accounting helpers and `swapz_status`; no wait/lock/`queue_work`/allocation
  in the helpers; dwell sampled before `bio_endio()`; `profile_epoch` only
  clears the valid flag; admission timestamps live in `swapz_bio_ref`;
  existing `write_admit_worker_*` sampling unchanged.
- Python tests for replay parsing/validators (conservation, bin, dominance,
  missing-token failures), the report table, the envelope `host_cpu` field and
  `make-interface-test.py` if new files must be copied.
- Run the full rootless suite and a kernel module build at W=1 (and W=2 if
  available). Do not run loaded or privileged tests; the owner does that.
- Update `docs/coding_standards.md` (new "Lower-lane gap attribution (ID178)"
  subsection), `docs/testing_standards.md` (validators and table), and ROADMAP
  row 178 to "implemented / owner make test pending".

Work directly on `main`: fetch first, fast-forward only, never force-push.

## Report back to the lead

1. Commit SHA(s) and changed files.
2. For each mark, the exact function and line where it is captured, plus every
   lower WRITE submission site classified as run or foreign.
3. The ownership proof for chronology state and the concurrency argument for
   the dwell counters.
4. Commands run with pass counts; status line length before/after.
5. Any deviation from this order, with the reason, and open questions.

## After review (owner)

`make test` on the ARM64 VM and the x86 AVX-512 PC, and on the quiet x86
`make fast_test SCENARIOS=nvme5-stripes,sata-stripes` (ID160, descriptive).
The lead then applies the ROADMAP ID178 decision rules.

## When the round closes

After the owner reports are recorded and the lead takes the ID178 decision, an
implementing agent (not the lead) checks that the standards and ROADMAP row 178
already carry everything durable from this file (definitions, invariants,
decision rules), merges anything missing, repoints the ROADMAP link, and
deletes this file (see "Change discipline" in `docs/coding_standards.md`).
