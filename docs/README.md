# swapz

swapz is an experimental Linux Device Mapper target for reducing measured lower-device I/O for swap-like workloads while preserving exact data, ordering, completion, and failure semantics.

## Immutable naming policy (read before every prompt)

The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`; and the administrative utility is `swapzctl`. Do not encode implementation generations in source directories, symbols, workflow names, binaries, benchmark candidates, or helper names.

`SWZ3` is intentionally retained because it names the on-disk format, not the implementation generation. Release numbers belong only in release metadata, whose canonical source is [`src/kernel/VERSION`](../src/kernel/VERSION).

## Repository layout

- `src/kernel/` — active product kernel C and headers, Kbuild file, and canonical VERSION.
- `src/userspace/` — active product userspace source.
- `tests/` — all test code, Python, test-only C/C++, fixtures, benchmark helpers, and private test orchestration.
- `packaging/` — installation/packaging helpers that are not test code.
- `docs/` — all maintained project documentation.
- `.github/workflows/` — CI configuration only.
- `build/` — generated output only; never source.

Retired implementation source needed by compatibility tests belongs under `tests/legacy/`, not beside the active product.

## Single official test command (read before every prompt)

Run `make test` at the repository root for every supported swapz test and benchmark. It must report BLOCKED (nonzero) when noninteractive administrator permission or safe isolated devices are unavailable. Do not create, publish, recommend, or document alternative test commands. Private scripts and suite targets under `tests/` are implementation details for CI and the root test runner.

The four supported root Make commands are `make`, `make install`, `make uninstall`, and `make test`.

## Safety status

The current target remains experimental and restricted to owned RAM-backed `null_blk` for loaded qualification. Do not bypass the null-backed admission guard, use active swap partitions, or infer physical-media results from the synthetic RAM models. Physical-media validation requires separate owner authorization and a rollback/recovery plan.

## Engineering objective

The primary success criterion is fewer independently measured host-visible lower READ/WRITE bytes and requests for the same verified logical workload, including GC and flush costs, without unacceptable throughput, swap-in latency, CPU, memory, or correctness regressions. Compression ratio by itself is not a result.

The detailed acceptance standard is in [VISION.md](VISION.md). Current algorithm work is in [ROADMAP.md](ROADMAP.md).

## Maintained documentation

- [VISION.md](VISION.md) — product success criteria and safety boundary.
- [ROADMAP.md](ROADMAP.md) — current engineering roadmap and measured evidence.
- [coding_standards.md](coding_standards.md) — implementation and review rules.
- [testing_standards.md](testing_standards.md) — test, provenance, failure, and loaded-device rules.
- [compile.md](compile.md) — build, packaging, and compatibility requirements.
- [benchmark.md](benchmark.md) — workload, I/O-accounting, and performance methodology.

Historical one-off reports and component-local Markdown are intentionally not retained in the working tree; Git history remains the archive.

## Source architecture

The active kernel implementation in `src/kernel/` contains the Device Mapper target, codec, volatile mapping authority, extent engine, GC policy helpers, and window policy. The public names stay stable while the release evolves. Internal implementation symbols use the `swapz_` / `SWAPZ_` prefixes rather than a release-number prefix.

The active userspace utility in `src/userspace/swapzctl.c` is deliberately read-only for the current experimental target. Packaging installs that utility and the kernel module but does not automatically activate swap.

## Development discipline

Keep changes small, fail closed, preserve exact upper-BIO completion ownership, and test production C directly where possible. Implementation changes must update the relevant canonical standard in the same commit. Never move generated objects into `src/` or test-only Python into the product tree.

All supported development happens on `main`.
