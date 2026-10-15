# Compile — V3-only Active Build

**Immutable naming policy (read before every prompt):** The project is `swapz`;
the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the
Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`.
**Never rename or version-suffix these public identities** (for example to
`swapz3`, `dm-swapz3`, or any other replacement). Enforce the same names
in production kernel C, Kbuild/DKMS, DM tables, test harnesses, benchmarks,
CI and documentation, before every agent change. Version numbers belong in
release metadata and source paths, not the project/module/target name. Keep
`SWZ3` as the distinct V3 on-disk format; the separate safe `swapz3ctl`
utility does not rename the project or module.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. This single public entry point runs native production-C/source/safety checks, W=1/W=2 builds, owned RAM-backed loaded correctness, and counterbalanced off/V3 throughput trials. It must report BLOCKED (nonzero) when noninteractive administrator permission or safe isolated devices are unavailable, never skip required loaded work while claiming a full PASS. **Do not create, publish, recommend, or document alternative test commands** (including additional Make goals, directly executed test scripts, one-off Python test invocations, and manually invoked loaded-device or benchmark helpers). Private implementation scripts/sub-Make targets and CI jobs may orchestrate individual stages internally, but are not supported operator interfaces; rootless-only CI success is explicitly partial.


**Required per-task context:** [README.md](../README.md), [VISION.md](../VISION.md),
[coding_standards.md](coding_standards.md),
[testing_standards.md](testing_standards.md), [compile.md](compile.md),
and [benchmark.md](benchmark.md). Work on **main only**.

## One active module: V3.0.0-alpha.21

`make -j2` builds **only the V3 Device Mapper `swapz`
module**, without loading it, using Linux **Kbuild/Make**. Linux kernel
module compilation is controlled by the kernel's headers, compiler flags,
symbol versions and module link process, so CMake cannot replace Kbuild.

All generated software artifacts belong under the **one persistent
`~/swapz/build/` folder**, reused between tasks:

| Output | Location |
|---|---|
| Active/default V3 module | `build/kernel/experimental/dm-swapz.ko` |
| V3 research smoke | `build/kernel/research/swapz_extent_v3.ko` |
| Native kernel C test binaries | `build/tests/native/` |
| Optional userspace test cache | `build/python-cache/` |
| Archival V2.2 module (only if explicitly requested) | `build/kernel/stable/dm-swapz.ko` |

V3 source: `kernel/extent-v3/{dm-target,engine,authority,codec}.c`.
Kbuild stages source in `build/kernel/experimental` (for older kernel
header compatibility) and writes object/`*.ko` there. `dkms.conf`
now identifies **V3 alpha.12** with **`AUTOINSTALL="no"`** to prevent
automatic installation of an experimental module. Even a manual DKMS
build or a successful compile is **NOT permission** to enable system
swap, bypass the null_blk-only guard, or load on physical media.

## Only supported root Make commands (owner policy)

```sh
make -j2         # build experimental V3 module and owned-device helper
make install     # install versioned V3 DKMS package + safe helper
make uninstall   # uninstall only matching owned DKMS package + helper
make test        # rootless checks, W=1/W=2, then owned-RAM smoke and paired benchmarks
```

**No other root Make goals or aliases are allowed.** Internal Kbuild and
native-suite make goals are not a public user interface. Missing kernel
headers fail the build/test. `make test` runs the rootless gates then
`tools/test-loaded.sh`, which executes actual owned-RAM kernel smoke and
four rate-limited 20 MiB/s off/V3 runs (sync/async/async/sync). The
loaded phase requires root or previously authorized `sudo -n`; it
**never prompts**, changes host swap or installs DKMS. If privilege,
null_blk features, identity checks, oracle or rate caps are unavailable,
`make test` exits nonzero BLOCKED/FAIL rather than reporting a complete
PASS. CI executes only internal rootless checks, not the complete
operator qualification. Standalone loaded-device scripts are private
implementation details, **not alternate test entry points**. The current V3 binary
`device-roundtrip` installs to `/usr/local/libexec/swapz/` by
default. The retired V2 `swapzctl` is NOT installed because it
invokes swapon/swapoff. The V3 DKMS install does not load or activate
the kernel module, and AUTOINSTALL stays disabled. Uninstall refuses
loaded modules, foreign files, and ownership mismatch. CI runs the
internal rootless test script without privileged device access.

## Automated build/qualification gates

`.github/workflows/extent-v3-codec.yml`: real V3 production-C
source/sanitizer contracts and W=1/W=2 builds.
`.github/workflows/project-goals.yml`: V3 native C and two-arm
off/V3 fixture/oracle tests; same-commit standards updates and build
hygiene. The historical V2.2 kernel-geometry workflow is manual-only; combined rootless source-safety tests remain automated for existing invariants, **not** as a V2.2 benchmark requirement. See
[testing_standards.md](testing_standards.md) for actual loaded-kernel
gates. Module build PASS ≠ loaded/physical performance.

## Why retire the old default?

The user has withdrawn V2.2 from active development because its
compression behavior did not meet project requirements at roughly
50% compressibility. This is a **product-priority decision**, not a
new independently measured benchmark claim. Keep historical Git
provenance without requiring V2.2 builds or fresh comparisons. Spend
ongoing engineering effort on safe V3 kernel C and actual reduced
lower bytes and requests.

## Preventing active-target regressions

The main-branch project-goal workflow now checks that root `make`
selects `all: v3`, V3 DKMS package identifies alpha.9 with
`AUTOINSTALL="no"`, and the immutable benchmark accepts **only
`("off", "v3")`**, rejecting reintroduction of the retired three-way
harness to the active tree. These are mechanical **workflow checks**,
not evidence of loaded V3 performance, physical-media readiness or
an I/O reduction. The historical module remains inspectable in Git
history without being part of required builds.

## Reusable native source-tree layout

The 16 current kernel-C tests are grouped under
`tests/runtime/native/{codec,mapping,gc,io}/`; only
`tests/suites/Makefile` contains the declarative test-to-production-C
link map. Its one `BUILD_NATIVE` recipe writes test binaries to
`build/tests/native/`. The old per-suite `make test-*` interfaces are retired and unsupported
at repository root. The internal native-suite build rule remains private.
Use `make test` to verify
source path resolution and avoid compilation in `tests/runtime/`.

## One official compile → test → loaded RAM benchmark interface

From a clean checkout on `main`:

```sh
cd ~/swapz && git pull --ff-only origin main && make test
```

This one supported test invocation first builds the current V3 kernel
module and userspace oracle, executes production-C, replay/source/safety
checks and W=1/W=2 builds, then runs an isolated loaded-kernel smoke
followed by four 20 MiB/s rate-limited off/V3 benchmark pairs
(sync/async/async/sync). No separate `make verify`, `make run`,
`make deploy`, suite-specific Make goal or direct helper invocation is an
official testing alternative.

Private implementations enforce clean source, same-kernel vermagic,
a matching staged binary and exact owned RAM-backed `null_blk`
identities, swap/mount/holder checks, and unique DM UUIDs. A busy or
ownership-mismatched device is quarantined rather than force-deleted.
The command never installs or activates system swap, touches real media,
performs a reboot or adds DKMS installation. For full qualification,
root or *already authorized noninteractive* `sudo -n` is required;
otherwise `make test` exits BLOCKED without opening a password prompt.
Logs are retained beneath `build/`. CI's internal rootless subset is
not a full `make test` PASS and does not qualify loaded performance.

## Historical implementation notes — not executable instructions

The dated alpha-series entries below preserve how previous experiments
were qualified at their original commits. Any earlier testing Make goals,
per-suite commands or standalone script invocations mentioned in that
history have been retired as public interfaces. **Use only `make test`
for all current testing and benchmarking.** It contains the formerly
separate native, loaded-smoke and off/V3 benchmark stages.

## 2026-10-14 null_blk configfs naming fix

The first user-loaded Linux 7.0 test passed all C tests and module builds but stopped before V3 insertion because configfs devices may use the configfs name, not /dev/nullbN. V3 kernel admission also requires a nullb-prefixed disk name. The ephemeral harness now creates nullb-swapz-<token>, accepts only its own configfs disk name or the legacy nullb<index> disk, and verifies the registered null_blk driver major, configfs index/minor, sysfs identity, block node rdev, size, mounts, holders and active-swap aliases before module insertion. On failed recognition it logs the config directory and quarantines rather than touching another device. The prior unnamed swapz<token> quarantined config is not automatically deleted; it requires read-only identity and holder inspection. Loaded success on the user's host remains NOT RETESTED.

## Incremental production C build scope — zero page elision

The active V3 `engine.c/engine.h` exports the bit-exact, allocation-free
`sv3_page_is_zero` predicate used by `dm-target.c` for a proven
zero-write mapping transition. `make test` runs the private native `zero-write-elision` executable
built directly against production engine/authority/codec C, as well
as the source-path contract. The loaded host oracle stays
at `build/tests/device-roundtrip` and now overwrites exact zero
pages. There is still **one** reused `~/swapz/build/` output tree.

## Isolated deployment write-stat acceptance check

The loaded phase of `make test` uses the compiled 128-page
`device-roundtrip` C oracle
on newly verified RAM-backed `null_blk`. The deployment shell now
captures the **before/after** V3 and backing-device write snapshots,
requires the expected nine all-zero logical page elisions in its fixed
192-write case, and reconciles target completed bytes with the
independent 512B-sector delta. This is a regression gate for the
zero-page optimization, not a replacement for a matched off/V3
performance benchmark. If it fails, the harness attempts only its
existing ordinary identity-verified teardown or quarantines resources;
never changes active swap. Build artifacts remain under `build/`.

## Owned-RAM benchmark (included in make test)

The full `make test` invocation includes the off/V3 replay after
successful rootless contracts, kernel builds and loaded device oracle.
It creates newly owned RAM-backed devices, verifies the independent
lower I/O counters and readback, then performs safe teardown or
quarantines failed ownership checks. Evidence stays in
`build/benchmark/session.*/`. Loaded throughput on the user's current
kernel: **NOT RUN** as of this documentation revision.

## Alpha.9 observational stage-3A version

The exact production VERSION and status, DKMS package, two owned
null_blk script guards and workflow version gate now use
`3.0.0-alpha.9`. Archived alpha.8 referred to an independently
unsuccessful unrelated-READ bypass and must not be relabeled.
Run `make verify`, Kbuild W=1/W=2 and the owner-authorized RAM-only
smoke before interpreting live close counters. Alpha.9 has **NOT
YET BEEN LOADED** at this source revision.

## Alpha.10 source/version alignment and smoke

The active source, DKMS package, Device Mapper status string, both
owned RAM null_blk harness guards and exact CI version gate are
`3.0.0-alpha.10`. No physical-device admission or system swap is
permitted. Alpha.10 adds window-age diagnostic fields to production
C and a loaded smoke conservation assertion. Use `make verify`,
W=1/W=2 Kbuild, then the already authorized `make run` only on
freshly owned RAM null_blk. Alpha.10 loaded: **NOT RUN**.

## Opt-in nonzero medium fixture

`make bench-pair-medium` is deliberately **separate** from
`make bench-pair`, default, `verify` and `make run`. It runs the
same rootless and W=1/W=2 kernel build gates before explicitly
launching two fresh owned RAM null_blk devices with
`--run-owned-ram-pair --profile medium`. The default pilot's
weight mix remains intact. Medium data are prechecked using measured
liblz4 output to avoid false 2KiB compression assumptions.
Results are preserved under `build/benchmark/session.*/`.
Loaded result at creation: NOT RUN.

## Alpha.11 opt-in serialized retention

The kernel table accepts a final optional `retain_ms` 0..4 setting;
`0` preserves alpha.10 scheduling by default. The experimental
opt-in retains immutable prepared records across worker invocations
until their original absolute first-admission deadline, with a timer
even if no further BIO arrives. All existing RAM/null_blk-only
admission, 64-page cap, barrier ordering, GC and fail-close remain.
At introduction, every version gate (DKMS, source and both owner scripts)
identified alpha.11; current gates identify alpha.12.
Run rootless `make verify`, W=1/W=2 Kbuild and default `make run`
before a separately opt-in retained policy. Subsequent owner-loaded
alpha.11 results are recorded in [benchmark.md](benchmark.md).

## Candidate-only medium retention entry point

Introduced for alpha.11, `make bench-pair-medium-retain` opts
`retain_ms=2` behavior into one newly owned RAM Device Mapper
target. The existing `make bench-pair-medium` is unchanged
conceptually, explicitly table-configured `retain_ms=0`; both
rootless-test and W=1/W=2-compile first. Record both exact session
logs and compare source/fixture/trace, lower I/O, achieved IOPS
and read tails, treating separate runs cautiously. This is NOT
part of any default/rootless command. Its owner-loaded alpha.11 result
is recorded in [benchmark.md](benchmark.md); alpha.12 is NOT RUN.

## Alpha.12 retained pipeline qualification handoff

Active source, status, DKMS and both owned-host guards identify alpha.12.
Positive `retain_ms` now prepares arriving writes immediately, uses an
absolute CLOCK_MONOTONIC hrtimer, and permits dependency-checked disjoint
reads. Retention remains off by default. Timer initialization supports
`hrtimer_setup` on Linux >=6.13 and `hrtimer_init` on older headers;
matching-host W=1/W=2 builds are still required. The header policy
regression builds only into `build/tests/native/window-policy`.

**At owner request, alpha.12 compilation and tests were NOT RUN during
implementation.** On the final clean main HEAD, the owner can run:

```sh
cd ~/swapz && git pull --ff-only origin main && make run && make bench-pair-medium && make bench-pair-medium-retain
```

Each loaded phase retains the existing owned RAM-null_blk admission,
exact source/module identification, full readback, independent counters
and ordinary teardown. This bounded sequence cannot qualify sustained
GC, CPU, real-device performance or every BIO/timer failure permutation.

## Alpha.13 packed-window early commit

The active source, DKMS, CI project-goals gate and both owned
null_blk harness version checks are `3.0.0-alpha.13`. Production
`dm-target.c` invokes a directly tested C geometry predicate
after staging the eighth compressed page in an explicitly retained
window; a provable 16KiB+4KiB batch commits without waiting for
the nominal hrtimer. This does not alter codec format, default
retention setting, FUA/READ fences or completion ownership.
Run `make verify`, W=1/W=2, owner-host `make run` and then
separately opt-in `make bench-pair-medium` and
`make bench-pair-medium-retain` only on freshly owned RAM
null_blk devices with exact preflight and ordinary teardown.
Loaded alpha.13 qualification: **NOT RUN**.

## Alpha.14 seven-record early window commit

Active source, DKMS, module status, Makefile and both owned
null_blk deployment guards now identify `3.0.0-alpha.14`.
The production C retained/zero-read-budget packing rule
checks seven staged compressed lengths plus exact SWZ3
header and seven descriptors against one 16KiB extent.
Default `retain_ms=0`, FUA/READ ordering, hrtimer and
lower authority are unchanged. Run rootless `make verify`
and W=1/W=2 kernel compilation before the owner-loaded
isolated RAM `make run`. After safe teardown use separate
`make bench-pair-medium` and
`make bench-pair-medium-retain` to test physical bytes,
write p99, matching achieved IOPS, and full readback.
Do not use existing host swap, physical or unowned devices.
The alpha.14 loaded result is NOT RUN.

## Unpaced QD32 high-throughput RAM-only comparison

After rootless `make verify` and a clean `make run`,
the explicit `make bench-pair-medium-unpaced` probes
completed useful I/O MB/s with no 500 IOPS offer cap.
This only adds a supported opt-in benchmark: QD32,
1024 warmup and 16384 measured 4KiB operations
using the already approved two newly owned RAM null_blk
lower devices, medium liblz4 fixture, full oracle,
independent lower stats, original module build/safety
preflight, timeouts and conservative cleanup.
Unpaced achieved-rate differences are results, not
matched-load disqualifications. Rootless checks and
kernel version remain alpha.14; **no loaded unpaced
throughput result has been reported**.

## Alpha.15 unarmed-timer hot-path optimization

Version gates, Kbuild and owned null_blk scripts now use
`3.0.0-alpha.15`. `sv3_flush_window` no longer synchronously
cancels an hrtimer in the default `retain_ms=0` case because
its worker never arms a timer. For the opt-in retained window,
timer synchronization, shutdown/free draining, FUA and mapping
authority are unchanged. Test actual production header predicate
and source paths, compile W=1/W=2, then owner-only fresh RAM
`make run` and `make bench-pair-medium-unpaced` after
passing safety preflight. An increased completed MB/s is
unproven until measured.

## Alpha.16 high-QD retention timer suppression

The active source, DKMS, project-goals version gate
and both owned-null_blk harnesses are
`3.0.0-alpha.16`. `sv3_worker` now inspects
`hrtimer_is_queued()` under its existing
`queue_lock`; for an already enqueued absolute
first-record expiry it does not restart the timer,
while an unqueued timer still arms with the
original deadline. No change to serialized worker
ownership, hrtimer callback, synchronous flush,
GC or shutdown/free cancellation. Direct native C
and source-contract tests cover the predicate and
no-extension invariants. On the authorized Linux
host, compile W=1/W=2 and run `make run` before
the separately opt-in `make bench-pair-medium-unpaced`
with freshly owned RAM-only devices. Alpha.16
loaded correctness/throughput is **NOT RUN**.

## Alpha.17 equal-compressed-length kernel order fast path

The active alpha build is `3.0.0-alpha.17`;
source, DKMS, workflow version check and both owned
RAM test guards advance together. The real worker's
`sv3_order_window` uses a linear identity permutation
for valid uniform LZ4 payload lengths. Mixed,
invalid or RAW windows still use the original greedy
reorder; engine extent planning, lower I/O, mapping
and upper completion remain unchanged. Direct
production-C policy tests and source qualification
must pass W=1/W=2 compile before owner-safe
`make run` and the opt-in
`make bench-pair-medium-unpaced`.
Alpha.17 loaded throughput is **NOT RUN**.

## Alpha.18 actual-C phase wall-time diagnostic

Active build and owned RAM guard versions advance to
`3.0.0-alpha.18`. Production `dm-target.c` now
reports cumulative monotonic elapsed nanoseconds for
LZ4, decompression, window reorder, engine commit,
lower synchronous dm_io READ/WRITE and GC. A native
test runs the exact kernel header elapsed helper with
forward/equal/backward/boundary timestamps. Source
contracts check actual timing around C operations
and status output. These counters are **not** CPU
usage, do not measure waiting for batch retention,
and may overlap. Perform W=1/W=2 kernel builds and
`make verify`, then only owner-run `make run` and
`make bench-pair-medium-unpaced` on fresh owned
RAM/null_blk. High-QD loaded alpha.18 is NOT RUN.

## Alpha.19 finite-quantum worker inline drain

Active kernel and guards: `3.0.0-alpha.19`.
The serialized `sv3_worker` preserves its
single 64-BIO quantum **across** inline
iterations, allowing newly arrived work to
be processed in the same invocation while
the budget remains positive. At zero budget
it still requeues, while during shutdown it
resets the quantum with `cond_resched`
and drains all accepted work. No
data format, on-media authority or FUA/GC
change. Direct production-C helper tests,
source contracts and W=1/W=2 compilation
are required before opt-in owner-loaded
`make run` and
`make bench-pair-medium-unpaced` on
unique owned RAM/null_blk. The new
`worker_inline_drains` counter measures
avoided requeue handoffs. Alpha.19 loaded
MB/s remains **NOT RUN**.

## Alpha.20 restore finite-worker handoff after negative high-QD result

Active `3.0.0-alpha.20` production C restores
the alpha.18 worker snapshot and bounded
workqueue requeue behavior, withdrawing the
alpha.19 inline continuation because it failed
to improve loaded useful WRITE MB/s. Rejected
code, telemetry and native predicate were removed;
source regression guards FIFO/backlog requeue
and shutdown drain. The module still uses
the same null_blk-only physical-admission guard,
engine, LZ4, CRC, FUA, GC and mapping publication.
Run W=1/W=2 kernel builds, `make verify`, then
a safe owner-loaded default `make run` followed
by the explicit unpaced 2-device owned-RAM
`make bench-pair-medium-unpaced`. Alpha.20
loaded speed and resource limits are NOT RUN.

## Alpha.21 real V3 write-window policy change

The active module is now `3.0.0-alpha.21`. Its
production header permits opt-in retained LZ4 writes
to close when two pages fit one 4KiB extent or three
pages fit one 8KiB extent, with exact SWZ3 metadata.
The seven-record 16KiB condition remains. Kernel
code still enforces read/duplicate/FUA dependencies,
publication after successful synchronous lower I/O,
GC reserve and the null_blk-only admission guard.
This is a CHANGE to the C commit schedule and
must be W=1/W=2 built and rootless-tested before
the owned-RAM qualification and unpaced benchmark phases of
`make test`. A speed benefit
is unmeasured and not presumed.

## Mandatory Make API regression gate

Only `make -j2`, `make install`, `make uninstall` and `make test` are permitted at repository root. All agents MUST reject additional root targets; `tests/runtime/native/make-interface-test.py` is run in the rootless harness and CI to enforce this, including removal of former `verify`, `run`, `deploy` and `bench-*` goals. The privileged part of `make test` must never silently skip its byte-exact owned-RAM smoke or benchmarks. Documentation citing removed commands is historic, not an active instruction.

## V3 system packaging held pending production readiness

`make -j2` also compiles a genuine V3 **read-only** `swapz3ctl` (version, status, help) under `build/userspace/`. `make install` is written to stage the versioned DKMS source at `/usr/src/swapz-<version>`, install `swapz3ctl` into `PREFIX/sbin` (default `/usr/local/sbin`), and the verified owned-device test binary under `PREFIX/libexec/swapz`. It never installs the unsafe retired V2 `swapzctl`, performs activation or enables autoload. `make uninstall` checks installed file hashes, version and ownership, refuses loaded modules and foreign/modified files, and removes only the matching version after successful DKMS removal; partial DKMS failures attempt a safe version-scoped rollback. Rootless `package-dkms-test.py` runs the real packaging script against fake DKMS inside `build/tests/package-sandbox`, including success, failed build rollback, tampering, and failed removal. **No privileged host installation or uninstall has been run.** The owner will not execute either command until production-safety approval; mock success is not system DKMS qualification.

Explicit `make all` and combined invocations such as `make install uninstall` are also **rejected**: `all` is the internal default recipe for `make -j2`, not a fifth public command. CI's Make contract test checks these cases.
