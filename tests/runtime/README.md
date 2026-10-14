# Runtime tests — active V3 navigation

**Authoritative policies:** [testing_standards.md](../../testing_standards.md),
[compile.md](../../compile.md), [benchmark.md](../../benchmark.md),
[README.md](../../README.md), [VISION.md](../../VISION.md).
Use **one** reusable `~/swapz/build/` for all compilation.

## Production C first

| Directory | Coverage | Entry point |
|---|---|---|
| `native/codec/` | Format, CRC, 4KiB RAW and LZ4 payload | `make test-codec` |
| `native/mapping/` | Authority, transaction commit, rollback, overwrites | `make test-mapping` |
| `native/gc/` | Victim exclusion, live relocation, accounting, rotations | `make test-gc` |
| `native/io/` | FUA/flush ordering and lower-write aggregation | `make test-lower-io` |
| `native/source-contract-test.py` | Real DM target, fault/ownership and constructor source contracts | `python3 -B tests/runtime/native/source-contract-test.py -v` |
| `benchmark/` | Synthetic anonymous-page fixture and immutable off/V3 replay | `python3 -B tests/runtime/benchmark/io-replay-test.py -v` |

`make test` executes the four C groups; each retains its original C
test functions and assertions. `tests/suites/Makefile` shares **one
compile recipe** across all 14 native C executables, linking the exact
kernel `codec.c`, `authority.c`, and `engine.c` where applicable.
**No executable is built in source folders.**

The benchmark test uses isolated scratch files to validate the replay
oracle and **does not claim a loaded V3 target**. The off arm in
separately authorized loaded tests is bare **owned RAM-backed null_blk**,
never a host `swapoff`.

## Historical and general safety helpers

The root-level `v22-*`, `streaming-benchmark-*`, `recall-*`,
`pressure-*`, and other host scripts are historical or shared
source-safety dependencies. Some remain automatically exercised by
CI and use sibling-relative imports and literal workflow paths.
They are **not active V3 performance benchmark requirements**.
They should be moved separately only after complete dependency and
source-safety-contract parity is established; never silently drop a
failure gate during a tidy-up. The former V2.x README instructions
are available via Git history and are **not live-swap authorization**.

Never reboot, `swapoff`, `swapon`, touch active `/dev/sdb1` or
`/swapfile`, physical/unowned storage, or force remove a mapping.
