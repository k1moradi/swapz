# Compile — V3-only Active Build

**Required per-task context:** [README.md](README.md), [VISION.md](VISION.md),
[coding_standards.md](coding_standards.md),
[testing_standards.md](testing_standards.md), [compile.md](compile.md),
and [benchmark.md](benchmark.md). Work on **main only**.

## One active module: V3.0.0-alpha.7

`make` or `make v3` builds **only the V3 Device Mapper `swapz3`
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
now identifies **V3 alpha.7** with **`AUTOINSTALL="no"`** to prevent
automatic installation of an experimental module. Even a manual DKMS
build or a successful compile is **NOT permission** to enable system
swap, bypass the null_blk-only guard, or load on physical media.

## Commands

```sh
cd ~/swapz
make KDIR="/lib/modules/$(uname -r)/build"
make v3 KDIR="/lib/modules/$(uname -r)/build"
make test                # V3 native production-C suites
make test-codec
make test-mapping
make test-gc
make test-lower-io
make v3-smoke KDIR="/lib/modules/$(uname -r)/build"
```

For compile qualification:

```sh
KDIR="/lib/modules/$(uname -r)/build"
make -C kernel/extent-v3 KDIR="$KDIR" W=1
make -C kernel/extent-v3 KDIR="$KDIR" W=2
sha256sum build/kernel/experimental/dm-swapz.ko
modinfo build/kernel/experimental/dm-swapz.ko
```

`make legacy-v22` and `make userspace-legacy` exist **only to preserve
reproducibility of historical code**, not to validate current V3. The
old system-`swapzctl` interface is not V3. No second build directory,
`swapon`, `swapoff`, reboot, physical/unowned block access or forced
teardown is permitted. `make clean` removes only known compiled targets.

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
selects `all: v3`, V3 DKMS package identifies alpha.7 with
`AUTOINSTALL="no"`, and the immutable benchmark accepts **only
`("off", "v3")`**, rejecting reintroduction of the retired three-way
harness to the active tree. These are mechanical **workflow checks**,
not evidence of loaded V3 performance, physical-media readiness or
an I/O reduction. The historical module remains inspectable in Git
history without being part of required builds.

## Reusable native source-tree layout

The 14 current kernel-C tests are grouped under
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
