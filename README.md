# swapz — V3 kernel development on main

**V3 is the project's only active implementation target.** Its
`swapz3` Device Mapper kernel module uses LZ4, raw fallback, and
4/8/16KiB extent packing to seek fewer **actual lower-device write/read
bytes and requests** for useful, verified 4KiB swap-page I/O. Current
revision: **3.0.0-alpha.7, experimental, NOT production-ready**.
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

**One Git branch: `main`**, no new branches unless expressly authorized.
More than 50% of ongoing engineering effort belongs to the
**production Linux kernel module's C**. At the end of each implementation,
update the relevant standard in the same commit and run goal-aligned CI.

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
[PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) and prior commits,
are *diagnostic evidence*, not required V2.2 benchmark controls.
The new **off vs V3** loaded immutable-trace comparison has **not
yet been performed**. Native tests and compiler success are not loaded
performance measurements.

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
