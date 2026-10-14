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
request. The read-byte check has **not yet been host-retested** at this
source revision. This is still a null_blk-only development qualification,
**not** production readiness or a matched off/V3 benchmark (see
[benchmark.md](benchmark.md)).
