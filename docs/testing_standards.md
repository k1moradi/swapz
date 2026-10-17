# Testing Standards

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

## Official interface

The root checkout has one supported testing interface:

~~~sh
make test
~~~

It must execute the supported qualification in order and fail closed. Rootless/CI-only success is partial evidence and cannot substitute for the loaded owned-RAM phase. The Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`.

## Required stages

A complete run includes:

1. Product/module/userspace/helper build.
2. Direct production-C native tests plus source, build-interface, report and packaging contracts.
3. Kernel W=1 build.
4. Kernel W=2 build.
5. Owned RAM-backed `null_blk` correctness, lifecycle/fault checks, matched mixed benchmark pairs and the bounded write-only QD pilot.

Stages are ordered and fail fast. Privileged device sessions must never overlap. If noninteractive privilege or safe owned-device provisioning is unavailable, the complete run reports BLOCKED rather than silently skipping loaded work.

## Direct production-C tests

Native tests compile the real `src/kernel/{codec,authority,engine}.c` where applicable. They cover codec integrity, authority publication, torn/short failure, overwrite generations, discard, zero-write representation, online packing, randomized authority, lower-run aggregation, flush/FUA accounting, retention/window policy and GC rotation/cost invariants.

Source contracts validate behavior that requires the Linux Device Mapper target itself, including BIO ownership, queue/drain ordering, null_blk-only admission, lower-I/O accounting and current report/build contracts. Source-string assertions are secondary to executable production-C coverage.

## Loaded correctness

Loaded tests use only newly created, positively owned, RAM-backed `null_blk`. Before and after use, verify device identity, size, major/minor, DM UUID, holders, mounts and active-swap aliases. Never substitute a physical or existing block device.

The deterministic lifecycle oracle must preserve exact readback, RAW fallback, zero elision and explicit flush behavior. Retained-window suspend/resume must drain accepted ownership and verify all pages. Synthetic pre-submission WRITE and FLUSH injection must fail closed. These synthetic failures are not evidence for torn/device-originated errors.

Cleanup never force-removes uncertain resources. If identity or teardown is ambiguous, quarantine and fail.

## Benchmark pairing and provenance

The mandatory mixed matrix uses two RAM-only latency models: 10 MiB/s with 1 ms completion and 80 MiB/s with 0.15 ms completion. Each model has four counterbalanced pairs across synchronous/asynchronous preparation. The control candidate is `off`; the product candidate is `swapz`.

Both arms of every pair carry the same exact source SHA, fixture SHA-256 and trace SHA-256. Missing or divergent provenance is INCONCLUSIVE. Every logical workload must finish its byte-exact oracle before a performance verdict is considered.

The write-only saturation pilot uses QD1/4/8/32 under the same two models with one sync and one async pair per QD. Until at least five counterbalanced pairs per mode/QD/regime and confidence intervals are implemented, it is directional only.

## Report contract

Official human-readable and JSON reports use `swapz`, not implementation-generation labels. Schema keys are version-neutral. SWZ3 is reserved for on-disk format discussion.

Reports distinguish useful logical throughput, backing WRITE throughput, lower READ/WRITE bytes and requests, p95/p99 where available, process CPU scope, kernel counters, GC, fixture/trace/source provenance, lifecycle result and cleanup. Never call synthetic RAM results physical SD/SSD evidence.

The retained production counters must describe active decisions only. Closed/rejected diagnostic counters are removed from production and report schemas.

## Evidence levels

Source contracts show structure, not loaded semantics. Native C shows portable product logic, not Device Mapper runtime. W=1/W=2 shows compilation, not correctness. Owned RAM-backed loaded tests show real kernel BIO behavior on the test host, not physical-media benefit. Only separately authorized physical testing can establish behavior on a particular real device.

## Current qualified baseline

Source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7` passed all five stages and is
the accepted directional performance baseline. It preserved byte-exact loaded
correctness, retained suspend/drain, RAW/zero/flush behavior and synthetic
WRITE/FLUSH fail-closed checks while retaining the large random-read lower-byte
reduction and recovering the earlier QD8 regression. Its QD pilot remains
one-pair exploratory evidence without confidence intervals, and live GC remains
unexercised.

## Open qualification gaps

Sustained live GC, genuine device-originated/partial lower errors, long-run resource pressure, larger controlled cold-read working sets, kernel-worker CPU attribution and statistically repeated QD saturation remain open. Physical-media testing remains blocked pending separate authorization and safety review.


Source contracts should assert retained scheduling semantics rather than a
particular obsolete branch spelling: retained writes must reach the ordered
worker immediately, while retention-off ordinary writes retain zero-delay
single-instance queueing.


The canonical report is local evidence at `build/test_results.json.xz`.
`make test` must not create commits, push Git refs, or alter the checked-out
source revision. A report describes the exact tested checkout; publishing or
archiving it is an explicit owner action outside qualification.


Rootless incremental-build fixtures mirror the current `src/` and `tests/` layout; they must not recreate removed top-level `tools/` or `userspace/` directories.


Native shell regressions source shared helpers only from `tests/tools/`.
Current reports, test output and product-facing diagnostics use `swapz`;
implementation-generation labels are not permitted outside explicit disk-format
history.


Native engine tests call the same batched write entry point as the product.
Tests that omit bulk callbacks thereby exercise its production sequential
fallback; no test-only write wrapper is part of the engine API.


The owned benchmark table validator must match the current Device Mapper
constructor exactly. Removed constructor fields are removed from replay parsing
in the same change; stale positional compatibility parsing is forbidden because
it can reinterpret ordinary options as fault injection and falsely BLOCK a
healthy product arm. Benchmark diagnostics and errors use the product name
`swapz`, never implementation-generation labels.


The retained suspend/resume oracle gates on observing an open retained window,
successful suspend/resume, a nonfailed target, and byte-exact verification of
all accepted pages. Its status sampler starts before the private writer and
polls without an added sleep so adaptive singleton fast-close cannot hide the
initial full-retention opportunity behind userspace process-start latency. It
must still observe `retain_timer_arms > windows`; historical timer activity is
not a substitute for an actually open window. The maximum supported 4ms
deadline can legitimately expire between that observation and the separate
suspend request, so the oracle must not require a specific close-reason counter
afterwards. Loaded failure reporting skips the generic cleanup epilogue so the
preceding specific sanitized failure remains visible.


Production-C differential tests for the lower-run writer must not freeze an
old physical extent layout when the experiment intentionally changes planner
tie ordering. They still require identical useful payloads and generations,
byte-exact readback, no authority visibility before lower completion, zero
default padding, and no increase in lower WRITE bytes. Physical start blocks,
record indices and extent classes may differ when those changes are the
mechanism being qualified.


The same rule applies to mixed compressed/RAW windows: compressed planner
placement is not an ABI. Differential coverage must preserve RAW CRC/type
authority, logical generations, exact readback and equal lower bytes rather
than require identical physical starts or transaction sequence assignment.


Source contracts for retained suspend/resume follow the observable safety
contract and must not resurrect the removed close-reason race. They require an
observed open retained window, explicit suspend/resume, a nonfailed target and
the byte-exact lifecycle marker; they explicitly reject a mandatory
shutdown-close delta.


Rootless Make-interface fixtures must emit the same current lifecycle marker as
the loaded parser. Synthetic fixture text is not a compatibility surface; when
the report contract changes, stale fixture markers are updated rather than
keeping parser aliases for removed semantics.


The direct production-C zero-elision test includes an intentionally unaligned
4KiB input view. It must accept an all-zero page, reject a nonzero final byte,
and never depend on bytes outside the logical page, preserving the exact
predicate while allowing word-at-a-time implementation.


Source contracts for the ordered worker assert the active finite-quantum
semantics rather than one historical loop spelling. A bounded
`while (remaining && !list_empty(&local))` plus an explicit decrement is
equivalent evidence to the retired pre-decrement break idiom only when FIFO
requeue, the hard quantum, and cooperative rescheduling remain asserted.


Write-only QD qualification records window-size bins and pack-ready/deadline/
idle close deltas for every QD/mode pair, plus the final learned retained-burst
target. These are attribution only and cannot substitute for throughput, lower
bytes, latency or correctness acceptance.


Rootless Make-interface fixtures that synthesize the loaded write-only pilot
must include the same window-size, close-reason and retained-burst-target
attribution required from the real loaded reporter. Fixture success must not
bypass a newly required evidence field merely because no kernel device is
present.


Dry accepted-pack qualification keeps the existing write-only window attribution
and additionally requires direct production-C/source coverage that a complete
accepted pack may close on a proven dry queue below a larger learned target,
that admitted-tail evidence observes worker-local FIFO entries before later
`incoming` entries, and that a single two/three-record deadline cannot shrink
the learned target below the four-record floor. These are scheduling-policy
checks only; acceptance still depends on useful throughput, lower bytes and
requests, latency and loaded correctness.


Source-contract helpers that extract only a function body must assert only text
that can actually occur inside that body. Signature parameters belong to a
full-source/signature assertion, not to a body-only search. When a production
helper gains parameters, every call-site spelling asserted by source contracts
must be updated in the same test change; do not keep stale call syntax as a
compatibility alias.


Service-proven retained closure qualification must distinguish the write
admission decision from the worker-tail decision. Source coverage requires
admission to ignore the accepted-second-pack shortcut below the effective
target, while the worker-tail path may use it only after refreshed queue state,
no active sampled tail, and prior packed-chain or independent-read service
evidence. A successful independent read while a retained write window is open
must be boundedly attributed to that window and cleared when the nonempty
window commits.


Ordered-worker preparation-steal qualification must preserve the producer's
no-publication rule and the original completion wait for entries the producer
has already claimed. Source coverage requires the steal decision and list
removal under `queue_lock`, an explicit inline marker, distinct producer LZ4
work memory, no producer use of the ordered worker's work memory, and combined
reporting from separately written timing accumulators. Drain and teardown must
still empty both queues and free all bounded producer resources.


Circular GC-probe qualification must prove destination selection does not
restart at segment zero on each collection. Direct authority tests must show an
untouched later reserve is selected before wraparound to an evacuated
low-numbered victim, while preserving the exact reserve count, one-destination
rule, forbidden open/victim checks, fail-closed handoff, authoritative mapping
CRC/generation state, and foreground progress. This native evidence does not
qualify sustained loaded GC; that remains a separate release gate.


Engine-level GC rotation follows the same circular destination order as the
authority test. Compressed relocation coverage must validate byte-exact
readback and role safety without freezing the retired segment-zero restart
sequence.


Worker-only retained-close qualification requires source coverage that
`swapz_accept_write()` never emits PACK_READY or calls the retained close
helper. The worker must sample local then incoming under `queue_lock` before
the PACK_READY decision. Initial accepted-width sampling must be limited to a
deferred first pack with no existing one-shot target, and post-pack sampling
must preserve residual-tail ordering. Service-proven dry closure may accept a
one-page residue only after prior packed-chain or independent-read service and
only when no sampled target is active.


Demand-driven preparation-wakeup qualification requires the preparation entry
to be linked before any wake decision, a lone idle-head entry to skip the
producer wake, second-or-later queued entries or active lower WRITE to wake it,
and a second guarded wake check immediately before synchronous lower WRITE
submission. Both wake decisions must share `queue_lock` with producer claim
and ordered-worker steal. Loaded comparison must verify QD1 latency/throughput
without losing high-QD `prep_lower_write_overlap_starts`.
