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

Source `8589a010f7c70c4f1f9737e688c434e4a11c9f9c` passed the complete qualification available at that revision. Its first QD pilot found large QD1 loss, QD4/QD8 useful-throughput loss despite request reduction, slow-model QD32 gain and faster-model QD32 loss. This is not statistically confirmatory.

Later cleanup revisions removed rejected hot-path diagnostics and obsolete repository infrastructure. They require a new complete owner-loaded run before becoming the performance baseline.

## Open qualification gaps

Sustained live GC, genuine device-originated/partial lower errors, long-run resource pressure, larger controlled cold-read working sets, kernel-worker CPU attribution and statistically repeated QD saturation remain open. Physical-media testing remains blocked pending separate authorization and safety review.
