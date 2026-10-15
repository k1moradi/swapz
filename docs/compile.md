# Compile — V3-only Active Build

**Required per-task context:** [README.md](../README.md), [VISION.md](../VISION.md),
[coding_standards.md](coding_standards.md),
[testing_standards.md](testing_standards.md), [compile.md](compile.md),
and [benchmark.md](benchmark.md). Work on **main only**.

## One active module: V3.0.0-alpha.21

`make -j2` builds **only the V3 Device Mapper `swapz3`
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
make test        # ALL rootless tests, loaded owned-RAM smoke and benchmarks
```

**No other root Make goals or aliases are allowed.** Internal Kbuild and
native-suite make goals are not a public user interface. Missing kernel
headers, sudo or exclusively owned RAM null_blk blocks the privileged
test phase rather than counting it as PASS. The current V3 binary
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
`build/tests/native/`. All four semantic `make test-*` interfaces
remain stable. The production source files and test assertions were
not altered by this organization pass. Use `make test` to verify
source path resolution and avoid compilation in `tests/runtime/`.

## Automated V3 build/test/deployment interface

Use `make verify` for rootless native kernel-C suites, exact V3
source contracts, and deterministic byte-exact off/V3 replay.
Use `make` to build V3 (still **not** loaded). Use **`make deploy`**
for the complete flow: verify, compile the exact V3 module for
`/lib/modules/$(uname -r)/build`, compile the C direct-I/O test
oracle into `build/tests/device-roundtrip`, then provision a new
strictly-owned RAM-backed null_blk and swapz3 DM target with
`sudo bash tools/deploy-nullblk.sh`. The host session is **ephemeral**:
it executes 128 4KiB page writes, reads, controlled overwrites and
flushes, then ordinarily removes only that mapping and the owned RAM
device. A busy/changed device is **quarantined**, never force-deleted.

From a clone on `main`:

```sh
cd ~/swapz && git pull --ff-only origin main && make deploy
```

The script checks clean tracked sources, exact staged C/headers,
vermagic=running kernel, unique random configfs/DM UUID, RAM-backed
null_blk size (64MiB), DM dependency, unattached/non-swap status,
and refuses to replace an already loaded `dm_swapz`. It never
installs a default system module, activates swap, or uses physical
storage. Logs remain in the **one build root** at
`build/deploy/session.*/session.log`. Configfs may remain mounted
because it can be shared by other tools. A missing header, configfs,
module-signing permission, root privilege or safe admission is **BLOCKED**,
not a reason to relax the null_blk-only kernel guard.

CI builds W=1/W=2 without loading the module and publishes only the
compile-time `.ko` plus source/version/vermagic/SHA manifest as a
short-lived GitHub Actions artifact. Module artifacts are kernel
version-specific: for actual host deployment, always rebuild locally.

## One-command compile → test → ephemeral isolated deployment

Use `cd ~/swapz && git pull --ff-only origin main && make run` on a
Linux development host with matching kernel headers and installed
`make`, C compiler, Device Mapper tools, `null_blk` configfs support,
and `sudo` privileges. The `main`-only source guard blocks a mismatched
branch, dirty tracked sources, wrong kernel vermagic or nonidentical
staged kernel source. `make run` is a strictly ordered pipeline:

1. `make verify` executes all 14 production-C tests, V3 source
   contracts, the off/V3 rootless replay oracle and deployment-shell
   syntax/safety contract checks. **No kernel module is loaded yet.**
2. Build V3 with `W=1` and `W=2` against the *running* kernel's
   `KDIR`; compile the standalone C device roundtrip oracle. All
   outputs stay under the reused `build/` root.
3. **Only after all prior steps succeed**, `sudo` invokes
   `tools/deploy-nullblk.sh` to create a unique 64MiB RAM-backed
   `null_blk`, insert the exact V3 module, make a unique 16MiB DM
   mapping, write/overwrite/read back 128 deterministic 4KiB pages,
   exercise flushes, print target status and lower counters, and
   perform ordinary ownership-verified teardown.
4. Save logs under `build/deploy/session.*`, report PASS/FAIL/BLOCKED,
   and quarantine unexpected resource ownership or busy holders
   instead of force removal. The script checks the system swap
   inventory before and after and fails if it changes.

`make deploy` remains an alias for this same **ordered** pipeline;
`make check` and `make verify` provide nonprivileged checks only.
The default `make` merely compiles V3. **No permanent deployment,
DKMS installation, system swap enablement, reboot or physical-disk
I/O is authorized.** An environment lacking supported safe `null_blk`
or sudo must report BLOCKED rather than work around isolation.


## 2026-10-14 null_blk configfs naming fix

The first user-loaded Linux 7.0 test passed all C tests and module builds but stopped before V3 insertion because configfs devices may use the configfs name, not /dev/nullbN. V3 kernel admission also requires a nullb-prefixed disk name. The ephemeral harness now creates nullb-swapz-<token>, accepts only its own configfs disk name or the legacy nullb<index> disk, and verifies the registered null_blk driver major, configfs index/minor, sysfs identity, block node rdev, size, mounts, holders and active-swap aliases before module insertion. On failed recognition it logs the config directory and quarantines rather than touching another device. The prior unnamed swapz<token> quarantined config is not automatically deleted; it requires read-only identity and holder inspection. Loaded success on the user's host remains NOT RETESTED.

## Incremental production C build scope — zero page elision

The active V3 `engine.c/engine.h` exports the bit-exact, allocation-free
`sv3_page_is_zero` predicate used by `dm-target.c` for a proven
zero-write mapping transition. `make test-mapping` builds the new
`build/tests/native/zero-write-elision` directly against unchanged
production engine/authority/codec C; `make verify` includes this
regression and the source-path contract. The loaded host oracle stays
at `build/tests/device-roundtrip` and now overwrites exact zero
pages. There is still **one** reused `~/swapz/build/` output tree.

## Isolated deployment write-stat acceptance check

`make run` uses the compiled 128-page `device-roundtrip` C oracle
on newly verified RAM-backed `null_blk`. The deployment shell now
captures the **before/after** V3 and backing-device write snapshots,
requires the expected nine all-zero logical page elisions in its fixed
192-write case, and reconciles target completed bytes with the
independent 512B-sector delta. This is a regression gate for the
zero-page optimization, not a replacement for a matched off/V3
performance benchmark. If it fails, the harness attempts only its
existing ordinary identity-verified teardown or quarantines resources;
never changes active swap. Build artifacts remain under `build/`.

## Opt-in two-arm RAM benchmark

`make bench-pair` is not called by `make`, `verify`, `run` or CI
privileged steps. It completes rootless checks and exact kernel Kbuild
W=1/W=2, then explicitly invokes
`sudo bash tools/benchmark-owned-pair.sh --run-owned-ram-pair`
on a consenting host. Evidence stays in `build/benchmark/session.*/`.
The test uses only new owned RAM-backed devices and normal teardown,
or quarantines failed ownership checks. Loaded test: **NOT RUN**.

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
isolated owner-loaded `make run`, then unpaced
`make bench-pair-medium-unpaced`. A speed benefit
is unmeasured and not presumed.

## Mandatory Make API regression gate

Only `make -j2`, `make install`, `make uninstall` and `make test` are permitted at repository root. All agents MUST reject additional root targets; `tests/runtime/native/make-interface-test.py` is run in the rootless harness and CI to enforce this, including removal of former `verify`, `run`, `deploy` and `bench-*` goals. The privileged part of `make test` must never silently skip its byte-exact owned-RAM smoke or benchmarks. Documentation citing removed commands is historic, not an active instruction.

## V3 system packaging held pending production readiness

`make -j2` also compiles a genuine V3 **read-only** `swapz3ctl` (version, status, help) under `build/userspace/`. `make install` is written to stage the versioned DKMS source at `/usr/src/swapz-<version>`, install `swapz3ctl` into `PREFIX/sbin` (default `/usr/local/sbin`), and the verified owned-device test binary under `PREFIX/libexec/swapz`. It never installs the unsafe retired V2 `swapzctl`, performs activation or enables autoload. `make uninstall` checks installed file hashes, version and ownership, refuses loaded modules and foreign/modified files, and removes only the matching version after successful DKMS removal; partial DKMS failures attempt a safe version-scoped rollback. Rootless `package-dkms-test.py` runs the real packaging script against fake DKMS inside `build/tests/package-sandbox`, including success, failed build rollback, tampering, and failed removal. **No privileged host installation or uninstall has been run.** The owner will not execute either command until production-safety approval; mock success is not system DKMS qualification.
