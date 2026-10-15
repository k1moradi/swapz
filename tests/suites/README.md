> This is an inventory of existing native C test suites, not a separate
> policy. Follow [testing_standards.md](../../docs/testing_standards.md),
> [compile.md](../../docs/compile.md) and [VISION.md](../../VISION.md).
> All compiled outputs reuse the one `~/swapz/build/`.

# Reusable native kernel-C regression suites

From the repository root, **`make test` is the only official test command**.
It includes the native V3 production-C suites, warning-level kernel
builds and (when the safe privileged preconditions pass) loaded RAM-only
correctness and paired benchmarks. No per-suite public test goals exist. All native
executables are compiled under **`build/tests/native/`** and reused
on the next run. They link to **the actual**
`kernel/extent-v3/{codec,authority,engine}.c` or execute the exact
production header predicates, rather than reimplementing algorithms.
Linux-host module compile and
loaded BIO behavior remain independent release gates.

| Semantic suite | Existing C fixtures | What it validates |
|---|---|---|
| codec | codec-roundtrip | compressed/raw 4096B format and CRC |
| mapping | mapping-authority, transaction-publication, write-verification, dead-segment-reclamation, raw-discard, online-packing, randomized-authority | mapping generations, authority, window transactions, raw fallback |
| gc | gc-forbidden-victim, gc-cost-accounting, gc-rotation, gc-engine-rotation | liveness, bounded safe relocation, request costs |
| lower-io | flush-ordering, lower-write-aggregation, window-policy | flush/FUA, actual-C bulk planning and retained dependency/deadline predicates |

The above are semantic executable names; the original
`tests/runtime/extent-v3-*.c` filename interfaces are preserved.
Historical `v22-*` scripts remain in place for pinned baseline
reproducibility and will be incrementally mapped into reusable named
modules after direct regression parity is established. No rename is
permitted to obscure a test's actual V2.2/V3 source provenance.

The native suites run rootlessly as an internal stage of `make test`.
The later loaded stage uses only newly owned RAM-backed `null_blk`;
no reboot, swap activation or physical media is permitted. See
[project vision](../../VISION.md),
[build contract](../../docs/compile.md)
and [release qualification gates](../../docs/testing_standards.md).

The historical C++ model is no longer a default V3 test gate;
its internal legacy reproduction is not an official test entry point.

Build definitions are now consolidated to one Make rule, not one
copied compile command per test. The native C binaries and original
assertions are retained; see `tests/runtime/README.md` for the tree.

The independent `tests/runtime/legacy/` Python safety contracts are
archived and remain in separate CI workflows; they are not included
in `make test` for active V3 kernel-C development.
