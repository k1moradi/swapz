# Compile — Build and Workspace Standards

**Authoritative build policy.** Agents read [README](README.md), [VISION](VISION.md), [coding_standards.md](coding_standards.md), [testing_standards.md](testing_standards.md), and [benchmark.md](benchmark.md) **at the start of every task**.

## Why Make/Kbuild, not CMake?

Linux external **kernel modules require Kbuild** to match the running/target kernel's module symbols, flags, compiler conventions and header tree. The normal interface is `make -C <kernel build> M=<external source/stage> modules`. CMake does not replace that and would add redundant orchestration/output directories. The existing thin Make wrappers also handle userspace C++ and test compilation. Do not introduce a parallel CMake build unless explicitly authorized. See [Linux Kbuild documentation](https://docs.kernel.org/kbuild/modules.html).

## Exactly one persistent generated-artifact folder

The **only** compiled-output root is `~/swapz/build/`, or equivalently `$(git rev-parse --show-toplevel)/build/` when checkout path differs. Reuse it for every task. Categorized children are not additional build roots:

| Build target | Relative compiled artifact |
|---|---|
| Default/frozen V2.2 module | `build/kernel/stable/dm-swapz.ko` |
| Experimental V3 Device Mapper | `build/kernel/experimental/dm-swapz.ko` |
| Research/smoke V3 variant | `build/kernel/research/swapz_extent_v3.ko` |
| Direct-production-C native tests | `build/tests/native/` |
| C++ model test | `build/tests/model/swapz-model-tests` |
| C++ userspace utility | `build/userspace/swapzctl` |
| Optional Python bytecode | `build/python-cache/` |

Kbuild source files are refreshed/staged inside the matching `build/kernel/*` folder before compilation because some old kernel versions lack `MO=`. Never leave generated .o/.ko/module/link objects in the source directories, create `build-debug/`, `tests/build/`, `cmake-build-*`, or compile software under `/tmp`. Benchmark data/test-owned backing-file fixtures are **not compile outputs**; keep independently hashed evidence without deleting other agents' files.

The root `Makefile` and `dkms.conf` select V2.2 by default, package version `0.2.2`, built module location `build/kernel/stable`. V3 is experimental and has incompatible SWZ3 format; both targets produce basename `dm-swapz.ko` and **must not be loaded concurrently**. The root `/build/` path is ignored by Git. `make clean` removes only defined generated artifacts, **not the whole build root**; never use blind `git clean`/hard reset.

## Reproducible build commands

~~~sh
cd ~/swapz
git branch --show-current     # must be main; preserve dirty work
git status --short
mkdir -p build
make KDIR="/lib/modules/$(uname -r)/build"          # stable module + userspace
make experimental-kernel KDIR="/lib/modules/$(uname -r)/build"
make -C kernel/extent-v3 KDIR="/lib/modules/$(uname -r)/build" SV3_BUILD_SMOKE=1
make test                   # C++ model + 14 production-C native tests
make test-codec
make test-mapping
make test-gc
make test-lower-io
~~~

For the target kernel headers and compiler, run warnings and verify module provenance:

~~~sh
KDIR="/lib/modules/$(uname -r)/build"
make -C kernel KDIR="$KDIR" W=1
make -C kernel/extent-v3 KDIR="$KDIR" W=1
make -C kernel/extent-v3 KDIR="$KDIR" W=2
# Optional when kernel/toolchain supports LLVM:
make -C kernel KDIR="$KDIR" W=1 LLVM=1
sha256sum build/kernel/stable/dm-swapz.ko build/kernel/experimental/dm-swapz.ko
modinfo build/kernel/experimental/dm-swapz.ko
~~~

Build only against known matching headers/vermagic; a compiler success on one host is not evidence a module ran on a different kernel. Track exact `git rev-parse HEAD`, input production-C blob, compiler, KDIR, target source stage and binary SHA. Never mask W=1/W=2 failures by disabling checks. GCC/Clang sanitizer and exact-C qualification are separate from loaded tests.

## CI and task hygiene

`.github/workflows/project-goals.yml` runs the reusable actual-C/C++ tests and userspace build, checks one-build-root output and documentation co-change. `.github/workflows/extent-v3-codec.yml` checks V3 actual-C/source and kernel W=1/W=2 build; `.github/workflows/kernel-bestfit4-experimental.yml` compiles stable kernel and checks source geometry. Existing rootless source/teardown workflows remain separate. All are scoped to `main`.

At the end of every implementation prompt: update at least one of the **four governing standards in the same commit**, include new build practices/warnings and verified results, update `README.md` if user-facing commands changed, `VISION.md` if success criteria changed, and report SHA and CI. CI cannot independently guarantee that prose is truthful.

**Legacy limitation:** several archival shell/Python test helpers still compile under source directories or `/tmp`; that history is not a license to violate this standard. Migrate those helpers only with test parity and safe review. Do not delete an entire shared build directory or unrelated outputs.
