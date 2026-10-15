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

## One active V3 module — version defined in VERSION

`make` builds **only the V3 Device Mapper `swapz`
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
reads the canonical version and retains **`AUTOINSTALL="no"`** to prevent
automatic installation of an experimental module. Even a manual DKMS
build or a successful compile is **NOT permission** to enable system
swap, bypass the null_blk-only guard, or load on physical media.

## Incremental parallel builds without parallel device access

The sole official test pipeline supports `make test -j2` (or another
intentional Make job count). The phony `all` target depends on three
**independent** build outputs: the current running-kernel Device Mapper
module, the C direct-I/O oracle, and the read-only userspace helper.
GNU Make may compile them concurrently. Native test binaries retain
file prerequisites and inherit Make's jobserver through the private
rootless runner. Changing `userspace/swapz3ctl.c` or its version rebuilds
only that helper; changing the C oracle rebuilds only the oracle. The
root Makefile itself is a dependency of both userspace builds so recipe
changes are not silently ignored.

A Kbuild invocation still validates the current `KDIR` and module
build even when no source changed. The staging recipe compares
content with `cmp -s` before copying Makefile/C/header inputs; it
**never uses unconditional `cp -f`**, which previously invalidated
all kernel object timestamps on each test. Kbuild itself decides whether
an object needs recompilation. Separate staged outputs isolate
normal `build/kernel/experimental/`, `W=1` at `build/kernel/w1/`,
`W=2` at `build/kernel/w2/`, and the memory-only research smoke in
`build/kernel/research/`, preventing warning-flag changes from
recompiling or replacing the kernel module used for safe loaded tests.

The `test` recipe deliberately has **no `.NOTPARALLEL` directive**.
Its commands are instead sequential failure gates: prerequisite
compilation completes; rootless native/source tests complete; W=1 and
W=2 Kbuild complete; only then does the owned-RAM loaded smoke run;
only after smoke success do the sync/async/async/sync pairs run in the
private loaded helper. `@+bash` forwards jobserver descriptors to the
rootless native suite. Parallelism cannot overlap any privileged
device session. No extra root Make goals or alternative public test
commands are introduced.

A rootless sandbox regression runs these actual Makefiles with a fake
unprivileged Kbuild and mock loaded phase. It checks ordering and the
mtimes for an unchanged rerun, a userspace-only change and a kernel
source-only change. **Mock success verifies orchestration/incrementality,
not loaded-kernel behavior or actual sustained throughput.**

## Only supported root Make commands (owner policy)

```sh
make             # build experimental V3 module and owned-device helper
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
selects the internal default V3 build, and the DKMS package follows VERSION with
`AUTOINSTALL="no"`, and the immutable benchmark accepts **only
`("off", "v3")`**, rejecting reintroduction of the retired three-way
harness to the active tree. These are mechanical **workflow checks**,
not evidence of loaded V3 performance, physical-media readiness or
an I/O reduction. The historical module remains inspectable in Git
history without being part of required builds.

## Reusable native source-tree layout

The current kernel-C tests are grouped under
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

## Retired alpha.9–alpha.20 build protocols — historical only

The former `make verify`, `make run`, `make deploy` and
`make bench-*` entry points no longer exist. Do not execute the
historical alpha-specific instructions against current main. Their
original experimental evidence and exact commands remain recoverable
[at the earlier revision](https://github.com/k1moradi/swapz/blob/b3c2f80ce5cab93a857404410b0114ccf5c07c0a/docs/compile.md).
The only current public test/benchmark entry point is `make test`;
its private stages check rootless C, W=1/W=2, owned-RAM correctness
and paired comparisons without touching physical media.

## Single-source release version

To publish a new alpha, edit **only**
[`kernel/extent-v3/VERSION`](../kernel/extent-v3/VERSION).
Kbuild generates `build/kernel/{experimental,w1,w2}/swapz-version.h`
from it. Production C embeds that version in the target status
and module metadata; `swapz3ctl`, DKMS and the loaded-test guards
derive or verify it automatically. CI tests a synthetic version change
without loading any module or touching devices. Do not copy version
literals into source, packaging scripts or CI assertions.

## Mandatory Make API regression gate

Only `make`, `make install`, `make uninstall` and `make test` are permitted at repository root. All agents MUST reject additional root targets; `tests/runtime/native/make-interface-test.py` is run in the rootless harness and CI to enforce this, including removal of former `verify`, `run`, `deploy` and `bench-*` goals. The privileged part of `make test` must never silently skip its byte-exact owned-RAM smoke or benchmarks. Documentation citing removed commands is historic, not an active instruction.

## V3 system packaging held pending production readiness

`make` also compiles a genuine V3 **read-only** `swapz3ctl` (version, status, help) under `build/userspace/`. `make install` is written to stage the versioned DKMS source at `/usr/src/swapz-<version>`, install `swapz3ctl` into `PREFIX/sbin` (default `/usr/local/sbin`), and the verified owned-device test binary under `PREFIX/libexec/swapz`. It never installs the unsafe retired V2 `swapzctl`, performs activation or enables autoload. `make uninstall` checks installed file hashes, version and ownership, refuses loaded modules and foreign/modified files, and removes only the matching version after successful DKMS removal; partial DKMS failures attempt a safe version-scoped rollback. Rootless `package-dkms-test.py` runs the real packaging script against fake DKMS inside `build/tests/package-sandbox`, including success, failed build rollback, tampering, and failed removal. **No privileged host installation or uninstall has been run.** The owner will not execute either command until production-safety approval; mock success is not system DKMS qualification.

Explicit `make all` and combined invocations such as `make install uninstall` are also **rejected**: `all` is the internal default recipe for `make`, not a fifth public command. CI's Make contract test checks these cases.
