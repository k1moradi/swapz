# Canonical one-build-root and test policy

Every agent must read this **with [VISION.md](../VISION.md)**,
[V3_GOALS.md](../V3_GOALS.md) and
[PRODUCTION_READINESS.md](../PRODUCTION_READINESS.md) before
every prompt/task. Source code, tests, docs and CI must serve the
project's **actual lower read/write bytes AND requests**, including GC,
for exactly matched byte-verified useful work, with safe authority,
CPU, RAM and cold-read p95/p99.

## Only `~/swapz/build/` for compiled artifacts

Use `cd ~/swapz && make`. The one reusable output root is
`~/swapz/build/` (or the checkout's equivalent absolute `build/`).
`make clean` deletes **only known generated binaries inside that
root**; it does not erase the whole directory, input fixtures, or
unrelated agent artifacts.

| Output | Directory inside the ONE build root |
|---|---|
| Default V2.2 Kbuild module | `build/kernel/stable/dm-swapz.ko` |
| Experimental V3 Device Mapper module | `build/kernel/experimental/dm-swapz.ko` |
| Opt-in V3 research smoke module | `build/kernel/research/swapz_extent_v3.ko` |
| Native C tests | `build/tests/native/` |
| C++ model test | `build/tests/model/swapz-model-tests` |
| Userspace C++ executable | `build/userspace/swapzctl` |
| Python bytecode (if needed) | `build/python-cache/` |

Wrapper Makefiles **stage exact production C sources inside their
respective build subdirectories** and ask Linux Kbuild to build from
those staged copies. That avoids source-tree .o/.ko output and works
with older external-module toolchains that lack Kbuild `MO=`.
The staged source must always be refreshed before a compilation;
record the actual Git source hash and module sha256. A Kbuild target
must be rebuilt after any source or kernel header change. Each
V2.2/V3 mode is isolated; their shared module artifact name is never
mixed or loaded concurrently. Only the experimental V3 path remains
null_blk-only; DKMS installs the default V2.2 module from its
`build/kernel/stable/` location.

### Commands

```sh
cd ~/swapz
make KDIR=/lib/modules/$(uname -r)/build            # stable kernel + userspace
make experimental-kernel KDIR=/lib/modules/$(uname -r)/build
make test                                           # C++ model + native C suites
make test-codec
make test-mapping
make test-gc
make test-lower-io
make clean                                          # only generated binaries
```

Linux kernel **Kbuild/Make** is mandatory for loadable kernel modules:
it uses the kernel's matching compiler flags, module linking and
headers. CMake does not replace Kbuild. The existing small Make
wrappers also build native C/C++ tests and userspace utilities with
no independent CMake output hierarchy. Reference:
[Linux external-module Kbuild documentation](https://docs.kernel.org/kbuild/modules.html).

## Automated, goal-aligned tests

The `main`-push project-goal CI verifies:
- the userspace C++ executable is built and reused under `build/userspace/`, without creating `userspace/swapzctl`;
- canonical agent documents reference vision, tidy build and
  documented results;
- production compiled tests run the **actual kernel C logic**;
- deterministic exact input/output CRC/readback regressions and
  FUA/GC/bulk-lower-I/O group tests run with meaningful suite names;
- a C++ model test passes;
- code/build/test/CI changes have a **meaningful documentation
  co-change** in the same commit;
- no compiled software is created outside `build/` by this workflow.

Kernel W=1/W=2 module builds and source contracts run in the
existing kernel qualification workflow, independently. Do not
promote rootless C test PASS to loaded host or real-media PASS.

For credible *performance* results, run the independent
[three-way immutable workload contract](../kernel/extent-v3/THREE_WAY_IDENTICAL_REPLAY.md),
measuring exactly the same 4KiB data and operations on owned no-swapz
null_blk, frozen V2.2 and experimental V3; verify full readback,
matched achieved IOPS, lower write/read request counts and bytes,
GC, p99 read latency and kernel CPU. Synthetic fixture weights are
hypotheses, not measured Linux anonymous swap population.

## Prompt completion hygiene

After each prompt that implements code, build, tests or CI:
1. Update relevant `.md` docs **in the same commit**, including
   behavior, exact commands, results and outstanding gaps.
2. Run focused compiled tests plus automated CI. Report actual
   pass/fail/blocker and SHA; do not claim a run that did not happen.
3. Keep source and test files semantically named and reusable; do not
   duplicate per-version test frameworks. Document historical source
   identifiers only where needed for comparison.
4. Do not create another branch; make small reviewed commits on main.
5. Never remove another agent's in-progress outputs or protected host
   swap, physical media or unowned block mappings.

**Limit:** CI can check documentation changes, but it cannot read
the agent's hidden prompt context or prove the semantic quality of
documentation. Agents must enforce the per-prompt vision gate
themselves. Agent behavior policy is not the same as kernel runtime
safety and performance proof.
