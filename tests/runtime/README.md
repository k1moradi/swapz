# Runtime tests — active V3 navigation

**Authoritative policies:** [testing_standards.md](../../docs/testing_standards.md),
[compile.md](../../docs/compile.md), [benchmark.md](../../docs/benchmark.md),
[README.md](../../README.md), [VISION.md](../../VISION.md).
Use **one** reusable `~/swapz/build/` for all compilation.

## One public test entry point

From repository root, `make test` is **the only official way** to run
any supported V3 test or benchmark. It orchestrates all private
production-C suites, source/fixture/safety contracts, warning-level
module builds, loaded owned-RAM correctness and counterbalanced
off/V3 performance trials. Do not invoke per-suite Make goals,
Python test files or shell smoke/benchmark helpers as alternate
operator commands. The helper paths below describe internal
implementation only.

| Internal source group | Coverage |
|---|---|
| `native/codec/` | Format, CRC, 4KiB RAW and LZ4 payload |
| `native/mapping/` | Authority, transactions, rollback, overwrite |
| `native/gc/` | Victim exclusion, relocation, accounting, rotation |
| `native/io/` | Flush/FUA, aggregation, retained-slot policy |
| `native/source-contract-test.py` | Production target, fault/ownership constraints |
| `benchmark/` | Immutable off/V3 fixture and replay oracles |

All compiled tests stay in `build/tests/native/` and link actual kernel
`codec.c`, `authority.c`, and `engine.c` where applicable. The rootless
stage alone cannot qualify loaded behavior or achieved throughput. If
noninteractive privileges or safe isolated RAM devices are unavailable,
full `make test` reports BLOCKED, never a false successful qualification.

## Historical and general safety helpers

The `legacy/` strategy/evidence tests, root-level `streaming-benchmark-*`, `recall-*`,
`pressure-*`, and other host scripts are historical or shared
source-safety dependencies. Some remain automatically exercised by
CI and use sibling-relative imports and literal workflow paths.
They are **not active V3 performance benchmark requirements**.
The 11 tightly coupled former `v22-*` files were moved together and renamed
by behavior into `legacy/` while preserving their old schema strings and
source-safety workflow gates. Other broad host/recall helpers must still be
migrated separately with dependency/coverage parity. Never drop a failure
gate during a tidy-up. The former V2.x README instructions
are available via Git history and are **not live-swap authorization**.

Never reboot, `swapoff`, `swapon`, touch active `/dev/sdb1` or
`/swapfile`, physical/unowned storage, or force remove a mapping.

## Legacy module names (archived behavior, still tested)

Under `legacy/`, these **renamed but retained** tools form three
reusable historical groups:

- `strategy-screen*.py` and `strategy-comparison*.py` — offline
  bounded plan/counter comparison, no runtime device access
- `drain-latency-analysis*.py` and `latency-quantiles-test.py` —
  exact drain and read-tail measurement contracts
- `evidence-validation*.py` — synthetic/validated evidence bundle
  and hash/binding checks (the `-v3` suffix preserves source schema)

Old `v22-*` root names are removed. The existing compatibility safety
workflows still invoke the renamed tests with original deadlines and
assertions. These are **archival/compatibility checks, not V3 performance
benchmarks**. Do not rewrite schema tags or alter source provenance.

The `native/mapping/zero-write.c` regression builds as
`build/tests/native/zero-write-elision` and tests actual-C all-zero
recognition and generational mapping retirement. It is included in the native stage of `make test`.
No separate Python zero-page mock is used.
