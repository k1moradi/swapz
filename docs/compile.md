# Build and Install

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

## Build

The production kernel source is `src/kernel/`. There is one module:
`dm-swapz.ko`. Kbuild links the DM/codec/authority/engine core plus the
delta64 predictor core. x86_64 also links isolated SSE2 and AVX2 predictor
objects; arm64 with kernel-mode NEON links the isolated NEON object. These are
backends inside the same module, not alternate research modules. The Device
Mapper target is exactly `swapz`; the module alias is `dm-swapz`.

Normal artifacts live only under `build/`:

- `build/kernel/experimental/dm-swapz.ko`: normal current-kernel build eligible for owned-RAM qualification.
- `build/kernel/w1/dm-swapz.ko`: W=1 warning build.
- `build/kernel/w2/dm-swapz.ko`: W=2 warning build.
- `build/userspace/`: supported userspace binary.
- `build/tests/native/`: native production-C test executables.

The one generated qualification artifact outside `build/` is the root
`test_results.json.xz`. It is intentionally overwriteable and versioned so
the latest completed PASS/FAIL/BLOCKED result is directly readable from
GitHub; no second report copy is generated.

[`src/kernel/VERSION`](../src/kernel/VERSION) is the release-metadata source. Kbuild generates the version header; DKMS and userspace resolve the same value.

## Root Make API

Exactly four commands are public:

- `make`: build product artifacts without loading them.
- `make install`: install the owned package/binary without activating swap.
- `make uninstall`: remove only the matching owned installation.
- `make test`: execute the complete supported qualification.

No extra root aliases or public test targets are permitted.

## Incremental builds

Kernel staging compares content before copying so unchanged source does not invalidate all object timestamps. W=1, W=2 and normal builds use separate output directories. Userspace/helper changes should not force unrelated kernel recompilation.

SIMD predictor files are separate translation units so ordinary kernel objects
retain architecture no-FPU flags. x86 SSE2/AVX2 objects opt into
`CC_FLAGS_FPU` (AVX2 also `-mavx2`) and remove conflicting no-SIMD flags;
arm64 NEON uses `CC_FLAGS_FPU` and removes `CC_FLAGS_NO_FPU`. Runtime
selection never changes the single-module artifact.

The official test runner may use Make jobserver parallelism for independent compilation, but loaded device phases and benchmark pairs remain sequential.

## Packaging

DKMS uses `AUTOINSTALL="no"`. Installation does not load the module, create a mapper or activate swap. Uninstall verifies ownership/version and refuses unsafe removal. Packaging tests run in a rootless sandbox; they are not system-install qualification.

## Removed build paths

The standalone memory-only kernel smoke module and retired C++ model are intentionally absent. They were not shipped or part of the official qualification. Historical reproduction belongs in Git history, not a second current build path.


The test runner keeps `test_results.json.xz` unchanged until all qualification
work has stopped. It then replaces that one file and publishes a report-only,
nonforce, lease-checked commit directly to `main`. The parent is the exact
tested revision; publication is refused if origin/main moved or unrelated
tracked/index state is dirty. After a successful push the local main ref/index
is advanced to the same report commit, so the operator does not accumulate a
dirty report file or need a separate pull solely for generated evidence.


Because the root `test_results.json.xz` is generated evidence, its local
working-tree/index state is excluded from the privileged loaded-source
cleanliness gate. No other tracked path is exempt. The report is atomically
replaced only after qualification stops and publication then reconciles the
local main/index on success.


Loaded `make test` helpers execute privileged device work through `sudo`, but
Git inspection inside those helpers is read-only and runs with
`GIT_OPTIONAL_LOCKS=0`. The privileged phase must not refresh or replace
`.git/index`; repository/index ownership remains with the invoking operator.
