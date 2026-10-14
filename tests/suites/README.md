# Reusable native kernel-C regression suites

From repository root use `make test` for the C++ model and native
production-C suites, or `make test-codec`, `make test-mapping`,
`make test-gc`, `make test-lower-io` for one concern. All native
executables are compiled under **`build/tests/native/`** and reused
on the next run. They link to **the actual**
`kernel/extent-v3/{codec,authority,engine}.c`, rather than
reimplementing the tested algorithms. Linux-host module compile and
loaded BIO behavior remain independent release gates.

| Semantic suite | Existing C fixtures | What it validates |
|---|---|---|
| codec | codec-roundtrip | compressed/raw 4096B format and CRC |
| mapping | mapping-authority, transaction-publication, write-verification, dead-segment-reclamation, raw-discard, online-packing, randomized-authority | mapping generations, authority, window transactions, raw fallback |
| gc | gc-forbidden-victim, gc-cost-accounting, gc-rotation, gc-engine-rotation | liveness, bounded safe relocation, request costs |
| lower-io | flush-ordering, lower-write-aggregation | flush/FUA and actual-C bulk planning contracts |

The above are semantic executable names; the original
`tests/runtime/extent-v3-*.c` filename interfaces are preserved.
Historical `v22-*` scripts remain in place for pinned baseline
reproducibility and will be incrementally mapped into reusable named
modules after direct regression parity is established. No rename is
permitted to obscure a test's actual V2.2/V3 source provenance.

Tests run rootlessly. No reboot, actual swap mutation, physical media,
or `null_blk` module loading. See
[project vision](../../VISION.md),
[build conventions](../../docs/BUILD_AND_TEST_CONVENTIONS.md)
and [readiness ledger](../../PRODUCTION_READINESS.md).
