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
