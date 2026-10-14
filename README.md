# swapz — V3 kernel development on main

**V3 is the project's only active implementation target.** Its
`swapz3` Device Mapper kernel module uses LZ4, raw fallback, and
4/8/16KiB extent packing to seek fewer **actual lower-device write/read
bytes and requests** for useful, verified 4KiB swap-page I/O. Current
revision: **3.0.0-alpha.16, experimental, NOT production-ready**.
V3 deliberately rejects all backing devices except controlled `null_blk`
until loaded correctness and resource-performance gates are satisfied.

The former V2.2 implementation did not meet the project's compression
expectations and has been **retired from active development, default
builds, default test suites, and required benchmark comparisons**. Its source, old tests, and
measurements remain archived in Git history for provenance only.
No V2.2 comparison is required before improving V3. Some historical
rootless safety checks remain automated to avoid losing safety coverage.

## Start every agent task with these six authoritative documents

| Document | Purpose |
|---|---|
| [README.md](README.md) | Active V3 scope and commands |
| [VISION.md](VISION.md) | Measured lower-I/O outcome and release criteria |
| [coding_standards.md](coding_standards.md) | Kernel C, invariants, main-only collaboration |
| [testing_standards.md](testing_standards.md) | Production-C test and fault coverage |
| [compile.md](compile.md) | Kbuild/Make and only one reused `~/swapz/build/` |
| [benchmark.md](benchmark.md) | Same-data **uncompressed baseline vs V3** evidence |

## Documentation and current work

The concise [current V3 TODO](docs/TODO.md) and
[active V3 roadmap](docs/ROADMAP.md) are under
[the documentation index](docs/README.md). Follow
[documentation guidelines](docs/DOCUMENTATION_GUIDELINES.md) before
adding a document or moving a report. V2.x plans and validation logs
are archived for provenance, not active requirements.
Root agent entry points stay at their expected locations.

**One Git branch: `main`**, no new branches unless expressly authorized.
More than 50% of ongoing engineering effort belongs to the
**production Linux kernel module's C**. At the end of each implementation,
update the relevant standard in the same commit and run goal-aligned CI.

## One-command compile, test and isolated deployment

On a Linux developer host with matching kernel headers and sudo, in
your existing clone:

```sh
cd ~/swapz && git pull --ff-only origin main && make run
```

This first runs all safe rootless V3 tests, then builds the kernel module
with `W=1`/`W=2`, then runs an **ephemeral** owned RAM-backed
`null_blk` deployment with deterministic C write/readback and cleanup.
**It does NOT install V3 as system swap**, reboot, touch existing swap
or use physical media. Results go into `build/deploy/session.*`;
missing headers/sudo/null_blk block the loaded phase. Use
`make verify` if you want the rootless-only checks; `make` compiles
V3 without loading it. See [compile.md](compile.md) and
[testing_standards.md](testing_standards.md) for gates and limits.

## Build and test (rootless compilation only)

```sh
cd ~/swapz
make                             # builds active V3 ONLY; does not load it
make test                        # native C V3 codec/mapping/GC/lower-I/O
make test-codec
make test-mapping
make test-gc
make test-lower-io
```

Compiled V3: `build/kernel/experimental/dm-swapz.ko`. This is the
**active/default build artifact**, retained in the sole reusable
`~/swapz/build/` tree. The executable module is still
**experimental**: "default build" is not permission to load it as
system swap. `dkms.conf` now packages the V3 alpha source and sets
`AUTOINSTALL="no"`; an installation, module insertion or user
`swapon` is NOT part of this build workflow.

The existing userspace `swapzctl` from the old generation is not a
V3 activation interface. Do not follow old physical-disk, manual
activation, DKMS autoinstall, swapoff/swapon or reboot instructions.

## Latest measured result and alpha.12 C implementation

The owner-loaded alpha.11 smoke and both medium-page trials at
`0a10cbfab1b154d2d7a351209adf22503f9d15ac` passed exact readback
and ordinary owned teardown. Every synthetic medium page compressed
to **2,073 bytes**. At matched ~503 IOPS, retention off saved **0%**
lower WRITE bytes; `retain_ms=2` saved **26.99% WRITE bytes** and
**67.14% WRITE requests** against its own uncompressed arm. Measured
READ bytes/requests were unchanged. Candidate write p99 increased
from **1.081ms off to 6.365ms V3**. These short, synthetic trials
had no GC/CPU qualification; see [benchmark.md](benchmark.md).

**Alpha.12 fixes the production C retained pipeline:**

- Prepare newly arriving ordinary writes immediately on the serialized
  worker, so they can join an open window before its deadline.
- Wake at the first admission's absolute CLOCK_MONOTONIC deadline
  using an hrtimer, removing the unsigned remaining-time underflow
  and explicit jiffy rounding. Scheduler/lower-I/O delays still apply.
- Permit unrelated READs through an opt-in retained window only after
  checking pending logical slots, barriers and transaction authority.
  Same-page reads and ordering fences drain pending writes.
- On a failed independent READ, abort retained WRITE owners without
  publishing or submitting their pending data.

The existing LZ4 codec, 4/8/16KiB format/planner, mixed lower runs,
64-page bound and null_blk-only admission are preserved. **Retention
remains disabled by default (`retain_ms=0`).** A positive setting
uses immediate preparation instead of admission coalescing;
`retained_read_bypasses` reports completed independent reads.

**Alpha.12 has been reviewed as source only. Compilation, native/source
tests and loaded tests were NOT RUN at the owner's request.**
To compile, test and compare fresh owned-RAM control/candidate sessions:

```sh
cd ~/swapz && git pull --ff-only origin main && make run && make bench-pair-medium && make bench-pair-medium-retain
```

`make run` exercises the default policy. The medium control uses
`retain_ms=0`; the explicit retained candidate uses `retain_ms=2`.
Each benchmark first runs rootless tests and W=1/W=2 builds and checks
actual fixture LZ4 sizes, immutable input, achieved load, full readback,
independent lower counters and safe ownership/teardown. Compare read
and write latency as well as bytes/requests; no alpha.12 performance
win or sustained qualification is claimed. Prior alpha.7..11 results
and failures remain in [benchmark.md](benchmark.md) and
[testing_standards.md](testing_standards.md).

## Alpha.13: opt-in early commit for proven packed batches

At exact alpha.12 source `2a3c872b`, the owner ran the default
loaded smoke and two separately owned medium-compressibility off/V3
pilots. Full readback and teardown passed. Opt-in V3 retention saved
**34.8%** lower WRITE bytes and **79.4%** lower WRITE requests
at matched ~503 IOPS, but sampled WRITE p99 was **2.933ms**,
versus **1.015ms** for that session's uncompressed baseline.
This is a short synthetic trial without GC or CPU qualification.

Alpha.13 changes **production Linux kernel C**: an explicitly retained
write window closes immediately when eight already staged compressed
pages provably fit in at most one 16KiB plus one 4KiB SWZ3 extent.
Default `retain_ms=0`, RAW or read-budget-restricted windows, FUA,
the hrtimer, read-dependency handling and publication safety are
otherwise unchanged. The goal is to reduce WRITE p99 without losing
lower-I/O savings; **the loaded alpha.13 outcome is NOT RUN**.

## Actual input MB/s → backing MB/s (alpha.13 owner pilot)

The measured medium 4KiB WRITE input was about **1.544 MB/s**
for retained V3, while independent RAM-backed lower writes were
about **1.006 MB/s** (uncompressed **1.545 → 1.545 MB/s**).
The ratio is **1.534 useful logical WRITE bytes per lower WRITE
byte** on this one 500-IOPS experiment. The source is
`6ec5eae5`, with 17 cumulative pack-ready early closures
and no GC. The paired replay now prints logical READ/WRITE/total
MB/s and independent lower READ/WRITE/total MB/s, with explicit
null fields for rootless runs; see `benchmark.md`.
This is a **fixed-input byte saving**, NOT higher demonstrated
maximum input throughput under an identical saturated disk budget.
A sustained RAM-only controlled-bandwidth experiment is still open.

## Alpha.14 opt-in C-first seven-page early commit

The owner-loaded alpha.13 retained trial at `0a443ca4`
measured **1.5435 MB/s** completed logical WRITEs and
**1.0062 MB/s** independently observed lower WRITEs,
a **34.81% write-byte reduction** and 79.4% fewer lower
WRITE requests than uncompressed at matched ~503 IOPS.
The byte-exact oracle, matched input, two owned RAM devices
and safe teardown passed; sampled WRITE p99 was **2.788ms**
versus **0.984ms** off. There was no GC or disk saturation.

Alpha.14 changes the actual production C early-commit
predicate: seven admitted non-RAW LZ4 pages may commit when
their exact SWZ3 metadata plus payloads fit one 16KiB extent,
without waiting for alpha.13's eighth record or deadline.
Default `retain_ms=0`, read/FUA barriers, physical authority
and null_blk-only admission are unchanged. Loaded alpha.14
safety and performance have **NOT RUN**.

## No 500-IOPS cap: explicit maximum-input experiment

The previous ~1.545 MB/s input rate came from a fixed
`--iops 500` artificial offering schedule. It was never
swapz's demonstrated throughput ceiling. The new
`make bench-pair-medium-unpaced` removes the IOPS sleep
on a separate, explicitly opt-in 16,384-operation QD32
off/V3 comparison, using two newly owned RAM-only null_blk
devices and the original medium fixture, exact readback,
independent lower I/O, timeout and guarded teardown.
It reports completed logical WRITE/READ MB/s and lower
WRITE/READ MB/s, plus V3/off logical-throughput ratio.
The unpaced loaded result is **NOT RUN**; it is not a
fixed-bandwidth/saturated physical-drive measurement.

## Alpha.15: skip unarmed retention-timer cancellation in production C

The owner-loaded alpha.14 default-off smoke passed; the paced
medium-payload off/V3 comparison also passed byte-exact oracle,
independent read/write accounting and ordinary teardown. It
measured ~**1.5436 logical WRITE MB/s → 1.0063 lower WRITE
MB/s** with opt-in retention (34.81% fewer WRITE bytes),
but the benchmark still requested only 500 IOPS and **did not
run the new unpaced probe**.

Alpha.15 performs one low-risk kernel-C hot-path optimization:
default-off write windows never arm the retention hrtimer,
so their repeated synchronous `hrtimer_cancel()` is now
skipped. Retained windows continue to cancel synchronously;
drain and free still unconditionally cancel for safety.
The kernel's compression, on-media format, ordering and
BIO publication are unchanged. No unpaced speed improvement
is claimed without the owner-loaded
`make bench-pair-medium-unpaced` result.

## Alpha.16: avoid redundant retention timer rearming at high QD

The first **unpaced QD32** owner-loaded alpha.15 run completed
identical 16,384-operation medium-payload traces with full
byte-exact oracle and clean two-owned-RAM-device teardown.
Off achieved **31.518 logical WRITE MB/s → 31.518 lower
WRITE MB/s**, versus V3 retained **24.867 logical WRITE
MB/s → 14.792 lower WRITE MB/s**. V3 saved 40.52%
independently measured backing WRITE bytes and 83.25% of
WRITE requests but was **21.10% slower in useful logical
throughput**. READ bytes per fixed trace were unchanged;
write p99 rose from 1.879 to 2.333ms. No GC occurred.
This is a real negative throughput result, NOT an SSD
saturation test or a candidate promotion.

Cumulative V3 status recorded **12,228 retention timer
arms for 3,124 windows**, indicating repeated rearming of
the same pinned absolute deadline. Alpha.16 changes the
actual production C worker to **skip rearming a timer
already queued**. It still arms when dequeued, cancels
on retained-window close and during drain/free, and
preserves read/FUA/GC/completion invariants. New
`retain_timer_arm_skips` reports avoided attempts.
The purpose is to improve useful high-QD MB/s
without sacrificing lower write savings; **alpha.16
loaded results are NOT RUN**.

## The active performance question

**Can V3 reduce true backing I/O against uncompressed 4KiB block I/O,
for the exact same logical pages and operations, including GC, without
compromising read p99, CPU/memory, ordering or data integrity?**

Use the immutable fixture and two-arm replay:
`tests/runtime/benchmark/anon-page-fixture.py`,
`tests/runtime/benchmark/io-replay.py`, and `tests/runtime/benchmark/io-replay-test.py`.
The *off* arm means **bare test-owned RAM-backed null_blk**, not
disabling a host's actual swap. The V3 arm receives identical 4096B
page payloads, addresses, operations and a full readback oracle.
Prioritize plausibly compressible anonymous-memory-style pages, with
**measured LZ4 size distributions**: especially approximately 2:1
(2048B payload from a 4096B page), but retain fully incompressible
RAW controls. Do not claim the synthetic distribution is a measured
Linux swap population.

The previously exercised V3 alpha code produced mostly **singleton
write windows at matched load**. That can prevent compressed data from
reducing physical write bytes even when its LZ4 ratio is good.
**Production-C batching, completion, mapping authority, GC, actual
lower I/O and kernel CPU are the development priorities**, not more
version comparisons or speculative Python frameworks.

Historical alpha.8 READ-bypass and alpha.7 reports, retained in
[PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md) and prior commits,
are *diagnostic evidence*, not required V2.2 benchmark controls.
Owner-loaded **off vs V3** bounded immutable-trace pilots have passed;
sustained GC, CPU, repeated-trial and tail-latency qualification remain
open. Native tests and compiler success are not loaded performance
measurements.

## Non-negotiable test-host safety

Never reboot, `swapon`, or `swapoff`. Do not access `/dev/sdb1`,
`/swapfile`, active system swap, physical media, unowned DM mappings
or unowned `null_blk`. Loaded tests, when authorized, must use new,
uniquely owned **RAM-backed null_blk** and safe identity checks and
teardown. V3's null_blk-only guard must not be relaxed for benchmarking.

## Organized V3 runtime checks

[tests/runtime/README.md](tests/runtime/README.md) now indexes
function-named native C tests and paired-input benchmark contracts.
Native source tests are in `tests/runtime/native/`; the synthetic
anonymous-page fixture and immutable replay are in
`tests/runtime/benchmark/`. The four native test targets and actual
production-C compilation semantics are unchanged. Historical host
helpers remain separate to preserve safety coverage.

## Automated compile, test, and isolated deployment

From an **existing clone** (no new branches, no recloning), run:

```sh
cd ~/swapz && git pull --ff-only origin main && make deploy
```

The one command uses the **current main source**, executes the native
kernel-C tests, V3 source contract tests and deterministic off/V3
rootless I/O replay, compiles the **exact V3** `dm-swapz.ko` against
**the running kernel**, compiles a small C direct-I/O oracle, and uses
`sudo` to provision one **new unique RAM-backed null_blk** + V3
`swapz3` Device Mapper test target. It performs bounded direct
4KiB reads/writes, compressible/RAW and overwrite verification and
flushes, emits source/module/target evidence in
`build/deploy/session.*/session.log`, and **normally removes
the owned test mapping and backing device** afterward.

This is an **ephemeral development deployment, NOT installation as
system swap**, and it never invokes `swapon`, `swapoff`, formats,
mounts a test filesystem or touches physical disks. If safe teardown
cannot be proven, the script stops and **quarantines the owned test
resources instead of force-removing them**. Do not manually remove
quarantined mappings while I/O is outstanding.

Requires Linux, matching running-kernel headers, gcc/cc, make,
`dmsetup`, `kmod` (modprobe/insmod/rmmod/modinfo), `null_blk`
with configfs, `sudo` privileges and other standard Linux tools.
The script reports missing prerequisites or a conflicting loaded
`dm_swapz` module without touching existing active swap. For
rootless compilation/tests only, use `make verify`; for compilation
without deployment use `make`.

GitHub Actions additionally runs rootless and W=1/W=2 builds on
`main` and publishes an **experimental compile-only** module artifact
with SHA/vermagic. CI-hosted builds are not asserted to be loadable
on your different running kernel. The isolated loaded deployment
runs **on your host only when you execute `make deploy`**.


**Linux null_blk naming note:** the isolated deployment now recognizes both configfs disk names and legacy nullbN names, with driver/index/rdev verification. Older quarantined test groups are not automatically removed. See compile.md before rerunning after a prior incomplete deployment.

## Production-C zero-page write elision (under rootless qualification)

V3 now recognizes an **exactly all-zero 4096B logical WRITE** after a
small LZ4 result (at most 64B) and safely replaces that slot's mapping
with the implicit-zero representation rather than writing a 4KiB
compressed container. Old pending writes drain first; logical page
generation/liveness advance and FUA still flushes before completion.
This can reduce lower WRITE bytes for zero-filled anonymous pages but
does **not** fix general ~2KiB-page packing. The target INFO counter
`zero_elided` reports successfully acknowledged zero writes.

The native production-C `zero-write-elision` regression tests the
full-page predicate, nonzero false-positive controls, old mapping
liveness, overwrite generation and failure on in-flight/overflow.
The isolated `make run` C readback oracle also writes fully zero
pages during overwrites to exercise the loaded path when run on an
authorized owned null_blk. Rootless CI builds/tests are not loaded
performance evidence; no lower-I/O win is asserted until an actual
post-change loaded run supplies device counters.

## Verified first loaded zero-elision result

On Linux 7.0.0-38, the updated V3 exact-zero C path passed the owned
128-page readback/flush/overwrite smoke on source `4c6e29b`.
It elided **9** writes, giving **183 lower requests / 732 KiB**
instead of the equivalent 192 x 4096B = 768 KiB useful logical writes:
a **36 KiB (4.69%)** write-side reduction in this controlled,
synchronous test. Independent lower-device write sectors agreed
exactly. All remaining **119** nonzero compressed windows were
singletons; no nonzero compressed-data packing win was established.
The `make run` deployment guard verifies the nine elisions
and reconciles oracle-interval lower-write **and read** bytes using
independent before/after null_blk sector counters. It reports request
counts separately rather than assuming one dm_io call is one device
request. The read-byte check **PASSED** on the user's owned Linux
7.0.0-38 RAM-backed host at `2e21fac5`. This is still a null_blk-only development qualification,
**not** production readiness or a matched off/V3 benchmark (see
[benchmark.md](benchmark.md)).

## Opt-in owned-RAM off/V3 pilot

`make bench-pair` (explicit separate command) runs rootless checks and
the kernel build before provisioning **two new RAM-backed null_blk**
test devices, bare uncompressed off and separately backed V3. It uses
one synthetic immutable trace and full logical readback, records
independent lower read/write sectors and requests, preserves reports
under `build/benchmark/session.*/`, and ordinarily removes only the
verified owned resources. Uncertain identities or busy resources are
quarantined. No physical media, system swap activation or forced
cleanup is permitted. **Owner-loaded alpha.11 pilots passed; alpha.12 is NOT RUN**.
The bounded pilot is not steady-state GC or release qualification.

## Complete documentation directory

Every tracked Markdown document is linked directly from this README.
The six **authoritative** project documents are in the table at the top;
the links below cover agent entry points, active references, component
notes, and **historical/archived evidence**. Historical pages are
preserved for provenance, **not** as instructions that override V3
safety, build, testing, or benchmark policies.

<!-- BEGIN COMPLETE DOCUMENTATION INDEX -->

### AI agent entry points

Current agent bootstraps; they point to the six governing documents above.

- [`.github/copilot-instructions.md`](.github/copilot-instructions.md)
- [`AGENTS.md`](AGENTS.md)
- [`CLAUDE.md`](CLAUDE.md)
- [`CODEX_VALIDATION.md`](CODEX_VALIDATION.md)
- [`agent.md`](agent.md)

### Current plans and shared references

The current V3 plan is in `docs/TODO.md` and `docs/ROADMAP.md`. The consolidation and legacy-conventions pages record older context.

- [`docs/BUILD_AND_TEST_CONVENTIONS.md`](docs/BUILD_AND_TEST_CONVENTIONS.md)
- [`docs/DEVICE_GEOMETRY.md`](docs/DEVICE_GEOMETRY.md)
- [`docs/DOCUMENTATION_GUIDELINES.md`](docs/DOCUMENTATION_GUIDELINES.md)
- [`docs/ONE_MAIN_BRANCH_CONSOLIDATION.md`](docs/ONE_MAIN_BRANCH_CONSOLIDATION.md)
- [`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md)
- [`docs/README.md`](docs/README.md)
- [`docs/ROADMAP.md`](docs/ROADMAP.md)
- [`docs/TODO.md`](docs/TODO.md)

### Kernel and test component documentation

Component-specific instructions and experimental protocols; older V2.x material is historical, not host-test authorization.

- [`kernel/BESTFIT4_TESTING.md`](kernel/BESTFIT4_TESTING.md)
- [`kernel/extent-v3/ANON_COMPRESSIBILITY_QUALIFICATION.md`](kernel/extent-v3/ANON_COMPRESSIBILITY_QUALIFICATION.md)
- [`kernel/extent-v3/LIVE_TEST_GATE.md`](kernel/extent-v3/LIVE_TEST_GATE.md)
- [`kernel/extent-v3/LOWER_WRITE_AGGREGATION.md`](kernel/extent-v3/LOWER_WRITE_AGGREGATION.md)
- [`kernel/extent-v3/LOWER_WRITE_FAULT_QUALIFICATION.md`](kernel/extent-v3/LOWER_WRITE_FAULT_QUALIFICATION.md)
- [`kernel/extent-v3/MIXED_LOWER_WRITE_AGGREGATION.md`](kernel/extent-v3/MIXED_LOWER_WRITE_AGGREGATION.md)
- [`kernel/extent-v3/ONLINE_IO_RETEST.md`](kernel/extent-v3/ONLINE_IO_RETEST.md)
- [`kernel/extent-v3/README.md`](kernel/extent-v3/README.md)
- [`kernel/extent-v3/THREE_WAY_IDENTICAL_REPLAY.md`](kernel/extent-v3/THREE_WAY_IDENTICAL_REPLAY.md)
- [`tests/runtime/README.md`](tests/runtime/README.md)
- [`tests/suites/README.md`](tests/suites/README.md)

### Archived plans and validation history

Preserved V2.x and dated V3 evidence. These documents do not override current policy or authorize old host commands.

- [`docs/archive/README.md`](docs/archive/README.md)
- [`docs/archive/v2.1/TESTING.md`](docs/archive/v2.1/TESTING.md)
- [`docs/archive/v2.2/CODEX_VALIDATION.md`](docs/archive/v2.2/CODEX_VALIDATION.md)
- [`docs/archive/v2.2/DESIGN.md`](docs/archive/v2.2/DESIGN.md)
- [`docs/archive/v2.2/ROADMAP.md`](docs/archive/v2.2/ROADMAP.md)
- [`docs/archive/v2.2/TODO.md`](docs/archive/v2.2/TODO.md)
- [`docs/archive/v2.2/VALIDATION.md`](docs/archive/v2.2/VALIDATION.md)
- [`docs/archive/v3/PERFORMANCE_DIAGNOSIS.md`](docs/archive/v3/PERFORMANCE_DIAGNOSIS.md)
- [`docs/archive/v3/V3_GOALS.md`](docs/archive/v3/V3_GOALS.md)

### Benchmark and validation reports

Mostly historical test designs, source-only checks, or versioned results.

- [`docs/benchmarks/v2.2-live-gc-latency.md`](docs/benchmarks/v2.2-live-gc-latency.md)
- [`docs/benchmarks/v2.2-request-plateau-model.md`](docs/benchmarks/v2.2-request-plateau-model.md)
- [`docs/benchmarks/v2.2-rootless-sweep-plan.md`](docs/benchmarks/v2.2-rootless-sweep-plan.md)
- [`docs/benchmarks/v2.2-size-aware-nbd.md`](docs/benchmarks/v2.2-size-aware-nbd.md)
- [`docs/streaming-benchmark-reporting.md`](docs/streaming-benchmark-reporting.md)
- [`docs/validation/v2.1-runtime-report.md`](docs/validation/v2.1-runtime-report.md)
- [`docs/virtual-smoke.md`](docs/virtual-smoke.md)

### Recall, NBD, and process supervision records

Versioned safety designs and qualification boundaries, not active V3 test instructions.

- [`docs/gnu-coreutils-qualification.md`](docs/gnu-coreutils-qualification.md)
- [`docs/nbd-pidfd-owned-rootless.md`](docs/nbd-pidfd-owned-rootless.md)
- [`docs/pidfd-supervisor-design.md`](docs/pidfd-supervisor-design.md)
- [`docs/recall-broker-2eab914-independent-review.md`](docs/recall-broker-2eab914-independent-review.md)
- [`docs/recall-control-bridge.md`](docs/recall-control-bridge.md)
- [`docs/recall-dd-allowlist.md`](docs/recall-dd-allowlist.md)
- [`docs/recall-denial-telemetry-offline.md`](docs/recall-denial-telemetry-offline.md)
- [`docs/recall-fixture-owner-and-drain-evidence.md`](docs/recall-fixture-owner-and-drain-evidence.md)
- [`docs/recall-io-drain-mock-integration.md`](docs/recall-io-drain-mock-integration.md)
- [`docs/recall-io-drain.md`](docs/recall-io-drain.md)
- [`docs/recall-role-bridge.md`](docs/recall-role-bridge.md)
- [`docs/recall-role-process-rootless.md`](docs/recall-role-process-rootless.md)

### Independent reviews and CI evidence

Dated review findings and rootless evidence inventories.

- [`docs/codex-gnu-9-11-review-2026-10-09.md`](docs/codex-gnu-9-11-review-2026-10-09.md)
- [`docs/codex-trust-bootstrap-review-2026-10-09.md`](docs/codex-trust-bootstrap-review-2026-10-09.md)
- [`docs/main-developer-broker-review-2026-10-09.md`](docs/main-developer-broker-review-2026-10-09.md)
- [`docs/main-developer-fixture-owner-review-2026-10-09.md`](docs/main-developer-fixture-owner-review-2026-10-09.md)
- [`docs/rootless-ci-evidence-inventory.md`](docs/rootless-ci-evidence-inventory.md)

### V2.2 implementation and evidence audits

Historical defect reviews, source-based checks, and offline evidence; V2.2 remains retired.

- [`docs/swapz-kernel-range-preflight-audit.md`](docs/swapz-kernel-range-preflight-audit.md)
- [`docs/v22-async-reap-watchdog-audit.md`](docs/v22-async-reap-watchdog-audit.md)
- [`docs/v22-compaction-container-validation-audit.md`](docs/v22-compaction-container-validation-audit.md)
- [`docs/v22-drain-plateau-offline.md`](docs/v22-drain-plateau-offline.md)
- [`docs/v22-evidence-bundle-offline.md`](docs/v22-evidence-bundle-offline.md)
- [`docs/v22-evidence-bundle-v3.md`](docs/v22-evidence-bundle-v3.md)
- [`docs/v22-exact-bio-identity-audit.md`](docs/v22-exact-bio-identity-audit.md)
- [`docs/v22-flush-fua-durability-audit.md`](docs/v22-flush-fua-durability-audit.md)
- [`docs/v22-gc-compressed-scratch-audit.md`](docs/v22-gc-compressed-scratch-audit.md)
- [`docs/v22-gc-source-snapshot-audit.md`](docs/v22-gc-source-snapshot-audit.md)
- [`docs/v22-generation-gc-transaction-audit.md`](docs/v22-generation-gc-transaction-audit.md)
- [`docs/v22-generation-scan-pack-preflight-audit.md`](docs/v22-generation-scan-pack-preflight-audit.md)
- [`docs/v22-independent-upper-bio-ownership-audit.md`](docs/v22-independent-upper-bio-ownership-audit.md)
- [`docs/v22-inflight-finalize-preflight-audit.md`](docs/v22-inflight-finalize-preflight-audit.md)
- [`docs/v22-latency-v3-sidecar.md`](docs/v22-latency-v3-sidecar.md)
- [`docs/v22-mapping-replacement-accounting-audit.md`](docs/v22-mapping-replacement-accounting-audit.md)
- [`docs/v22-pending-pack-ownership-audit.md`](docs/v22-pending-pack-ownership-audit.md)
- [`docs/v22-published-mapping-read-bounds-audit.md`](docs/v22-published-mapping-read-bounds-audit.md)
- [`docs/v22-staged-read-metadata-audit.md`](docs/v22-staged-read-metadata-audit.md)
- [`docs/v22-stream-submit-bounds-audit.md`](docs/v22-stream-submit-bounds-audit.md)
- [`docs/v22-virtual-benchmark-qualification.md`](docs/v22-virtual-benchmark-qualification.md)

<!-- END COMPLETE DOCUMENTATION INDEX -->
