# Handoff prompt: resume on the free x86_64 / AVX-512 computer

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands; the sole owner-approved exception is the development decision loop `make fast_test`, which never qualifies a source, never writes or publishes `test_results.json` and never replaces `make test`. Private scripts and CI jobs are implementation details, not operator interfaces.

Read the six canonical docs named in [the goal prompt](goal-prompt.md), then
resume that goal on this free x86 host. Stay on `main`. The original ARM64 VM
is busy: no builds/benchmarks there until the owner says it is free. That hold
does not prohibit work on this new free computer. Check its noise/provenance
before timing; no other agent should edit the same checkout concurrently.

## What is already committed

- Production source `2aa3ba06520fbf3a723294d7d7dd09cdd45e6502` fixes a lower-WRITE
  callback lifetime gap: `complete(lower_done)` and owner notification now share
  `queue_lock`, with no target/slot access after final unlock. A controlled
  actual-body test fails on the old callback and passes on the repair under
  both dm-io ABIs. The ARM64 rootless suite (90 source contracts), W=1/W=2 and
  15 development byte oracles passed; known warnings remain. This is a
  correctness repair, not a measured speedup. No kernel UAF was reproduced.
- Its owner run was deliberately stopped when the owner reported a very busy
  host. Report `ff66c705b152` is BLOCKED, exit 2. Stages 1–4 and loaded smoke,
  suspend, faults, ACK handoff and RAW-read gates passed; the full matrix and
  ID36 did not finish. The harness calls the terminated replay a bounded
  timeout; the stop was intentional. Owned cleanup completed. No partial
  performance from that run is accepted, and no history point was added.
- `42b948bf36c56eb6724399ad49dab2f3d9c2d793` documents that state. This handoff
  commit adds portable artifacts and documentation; it does not apply the
  direct-BIO experiment or change production behavior.
- Last fully qualified ARM64 production C is `d2b66acb8c7eed99bbcfb6c89000df2da743ec83`,
  report `77a0c3c587d4194d519edef4f1c2b8eadd253a9f`. ID143's bounded published-WRITE
  ACK handoff had a separate fixed 16-round final-source comparison: persistent
  NVMe5 useful WRITE/raw +22.66% [18.47,27.00] at 99.1667% confidence, n13 after
  three declared raw-drift exclusions, sign p0.000244. Lower WRITE bytes +1.29%
  and requests +26.22% versus control are costs, not an endurance win over that
  control. It still saved about 29.7% bytes and 90.4% requests versus raw and
  still trailed raw throughput substantially. ARM results do not qualify x86.

## First actions on this computer

1. Fetch/fast-forward `main`, inspect status and read the docs. Preserve any
   local edits. Record actual CPU model, exposed ISA/xstate, selected kernel and
   native backends, VM/hypervisor, online/affinity CPUs, memory size and memory
   type if available. Verify rather than assuming LPDDR4 or AVX-512 availability.
2. On this free host, run unchanged-source `make test` before applying the
   draft. It pins a fresh current-source x86 baseline and checks supported
   scalar/SSE2/AVX2/AVX-512 paths and loaded correctness. It publishes its report
   and commits to origin/main; do not run on dirty source or overlap benchmarks.
   Resolve a failure before attributing results to the next optimization.
3. Establish separate x86 history. The current private
   `tests/tools/plot-history.py` is ARM64/NEON/seven-CPU specific and outputs
   `build/history/arm64-neon/`; it does not automatically plot x86 results.
   Extend/reuse the thin plotting implementation with explicit host/ISA
   separation and a distinct x86 output. Keep the ARM history intact. Display
   every generated/refreshed plot and retain immutable image/data snapshots.
   Do not label an ARM refresh as a new x86 performance point.
4. Only after the baseline qualifies, verify the draft's manifest and apply
   `docs/handoff/direct-lower-write.patch` as a development experiment. The patch
   is based on the C in 2aa3ba0 / tree 42b948b. Base dm-target.c SHA256 is
   `8a5ebda7575653ff0807cc89ee958a14602d5f355a6a4f7abc59647ae997870f`.
   Do not apply blindly if current C differs. The patch contains all C and test
   changes; it needs no files from the original host's ignored build directory.
5. Read [the adapter review](direct-lower-write-review.md). Build/check actual
   callback and submission bodies before loading. The draft has passed only
   Python AST parsing and Git patch-applicability/whitespace checks: no C build,
   native test, loaded test, benchmark or x86 execution has run for it.
6. Use `make fast_test` for fixed screened development comparisons, including
   medium and RAW/balanced content, matched persistent and wave mixed modes,
   and relevant low-QD guards. If promising, finish forced-split/error coverage,
   prospective counterbalanced confirmation and exact-source `make test` before
   retaining it. Keep the whole fixed sample, exclusions and trade-offs. Remove
   an unpromising variant; do not retain a new backend only because it builds.

## Direct-BIO experiment and unfinished validation

The draft replaces only detached lower-WRITE dm_io submission with one embedded
BIO and 64 preallocated vectors referencing the existing immutable bulk scratch.
READs, synchronous four-record/RAW/GC writes and flush adapters remain dm_io.
There is no second run, data buffer, worker, reservoir or publication authority.
The callback copies owner/status first, fails every nonzero BIO status and keeps
notification under the repaired lifetime gate. Construction stays inside the
old lower-service timer so EWMA/dispatch policy is not changed by redefining a
measurement. Construction failure releases the BIO association and rolls back
active ownership without a fake callback. The manifest records exact hashes.

Native test drafts cover bounds, owned/non-null scratch, pre-submit faults,
construction failure, inline and delayed completion, refusal to reuse an active
descriptor, and reuse after owner reaping. They are written, not executed.
Forced-split loaded coverage is NOT in the patch. A dedicated newly owned RAM
queue may use a verified 4KiB max request limit, but must prove an actual parent
larger than one block, exact complete readback, single completion, failure and
suspend/drain behavior. The existing parallel oracle includes entropy pages and
can be reused; fixture content or a small queue limit alone is not proof of a
split. A pre-submission synthetic fault does not test split-child failure.
No runtime control or probe should survive a rejected experiment.

## Earlier x86 history and the RAM caveat

[The verified candidate index](x86-history-candidates.json) includes report
`4886c4d79a362b546b69bc5f9356be05ec2f536f`, all five stages PASS on source
`005592dbb7fe6503c37a306bfd2987b56e1affef`, kernel 7.0.0-42-generic, eight CPUs,
with measured scalar/SSE2/AVX2/AVX-512 backends. This is the earlier owner-pasted
x86 result and a candidate for this machine's historical series. It lacks an
immutable machine ID, CPU model and RAM identity; establish the host/protocol
match before joining lines. Otherwise show it separately and start a new series
from the fresh qualification. Another report, `1df2e5a6d7c5`, has only scalar/
SSE2 and four CPUs; do not merge that profile into the eight-CPU AVX-512 series.
Recover reports from Git history of test_results.json; the working file is only
the latest overwriteable report. Old source results cannot qualify current C.

NEON-specific code and measurements are ARM-only. Architecture-neutral authority,
RAW READ fan-out, ACK handoff and lifetime changes still apply on x86, but their
benefits require new measurement. DELTA64_SHUF8 already had an old x86 PASS; it
is not an untested encoding. Retain the scalar oracle and runtime ISA checks.
Do not repeat the retired SSE2-forward comparison as if it were a new idea.

The owner suspects slower LPDDR4 RAM; treat that as unverified. Memory-backed
null_blk uses host memory plus configured bandwidth/completion behavior; it is
not a physical NVMe controller. Preserve official profile settings and record
achieved raw throughput and latency. Low 4KiB raw MB/s alone does not prove a
RAM bottleneck: latency, QD, CPU, copies and scheduling also limit it. If the
host caps a fast envelope, label it host-limited synthetic evidence, keep it
separate from achieved-model results, and do not claim real Gen4/Gen5 fidelity.
Do not retune only one arm, rescale results to advertised rates, or combine ARM
and x86 points. Verify high-bandwidth calibration through the existing private
qualification/development machinery if needed; add no public test command.

## Remaining untested ideas

- **Original #5: direct BIO submission.** This unapplied draft is the next
  bounded experiment. Polling is a separate untested intervention and must be
  fair to raw; null_blk polling can bypass timer behavior.
- **Original #2: submitter-side compression.** Still unimplemented. Profile x86
  first: the producer does not perform all LZ4; much runs on the ordered owner.
  Per-CPU scratch, context/FPU rules, source lifetime and RAW fallback need a
  bounded ownership design.
- **Original #3: lockless/lightweight admission.** Still unimplemented. Preserve
  FIFO, dual producer/owner references and close/drain lifetime. Summed concurrent
  lock waits are not a removable critical-path budget.
- **Original #7: dm-linear calibration.** Still untested as an additional
  reference. DM fast paths mean it is not an exact unavoidable-overhead budget.
- **Original #6: cached READ in admission.** Still unimplemented and high risk.
  Needs pinned immutable cache/authority views, same-page pending WRITE, GC,
  DISCARD, fences and teardown handling; generation checks alone are inadequate.
- **CPU-targeted terminal delivery / a redesigned READ handoff.** Unimplemented.
  Check exports, persistent callback lifetime, offline-CPU fallback and a real
  callback-return join. The list-only READ deferral in ID147 is already tried
  and removed: 15,653 deferred READs yielded only seven helper READs; delivery
  did not precede every synchronous READ wait. Do not repeat it unchanged.
- **256-bit AVX-512VL / CPU-specific predictor selection.** No implementation
  or measurement in this checkout. Only prioritize if x86 timings show a useful
  total-I/O opportunity; do not assume a universal 512-bit frequency penalty.
- **ID113 folio locality / explicit zswap origin.** Later representative-evidence
  and cross-subsystem tasks. Do not infer earlier WRITE folios from READ buffers,
  wait for locality partners, add blocks, or activate swap without authorization.
- **Original #9: ACK from staging/write-back.** Untested but outside the current
  lower-success publication/failure contract; it needs an explicit architecture
  decision. It is not an authorized ordinary tuning change.

Already explored: spin/sleep ID137; first-window lead ID140; persistent-vs-wave
sensitivity ID141; ACK attribution/handoff ID142/143; counter padding ID145;
wakeup attribution ID146; list-only READ deferral ID147. K=2 ID110, extra-worker
variants, and various timer/ACK changes also have roadmap evidence; don't call
them new. Reopen only with a materially different hypothesis and measurements.

## Expected continuation output

Report what changed and why, exact source/report hashes, byte correctness,
noise exclusions, intervals/practical significance, latency and lower-I/O costs,
and keep/remove decisions. Preserve circular allocation/GC fairness and call
host-write savings an endurance proxy. Update governing docs in the same source
commit. Keep plotting glue thin and spend most engineering effort on kernel C.
Show every newly rendered plot; if there is no qualified new point, say so.
