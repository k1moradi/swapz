# Testing Standards

**Current testing policy.** Read [README](README.md), [VISION](VISION.md), [coding_standards.md](coding_standards.md), [compile.md](compile.md), and [benchmark.md](benchmark.md) at the **start of every agent task**. Tests must prove correctness on actual source, expose false completions and regressions, and ultimately support the project's **real lower-I/O** objective—not maximize test counts.

## Qualification ladder (do not confuse evidence levels)

| Gate | Shows | Cannot claim |
|---|---|---|
| Source contracts/rootless CI | Structural bounds and expected source path | Loaded BIO semantics or real request reduction |
| Exact production C + C++ model | Executed codec, mapping, GC, lower-write planning | Linux loaded module safety |
| Kbuild W=1/W=2 + verifier | Compiles against named kernel headers | Runtime authority, fault or performance |
| Owned RAM-backed null_blk loaded tests | Real kernel BIO interactions and independent backing counters on the test host | Actual SD/SSD/HDD benefits |
| Separately owner-approved real-device tests | Device-class behavior on that physical configuration | All-device performance or generic readiness |

Report **PASS, FAIL, MIXED, INCONCLUSIVE, BLOCKED, NOT RUN** with exact Git source and loaded binary SHA/vermagic, kernel/compiler, failed records, cleanup evidence. Green CI ≠ production release.

## Reusable native C tests: mandatory first choice

**Only one reusable compiled-output tree:** `~/swapz/build/`. Native tests link to **actual** `kernel/extent-v3/{codec,authority,engine}.c` and use semantic names, not newly duplicated version-number frameworks. From checkout root:

~~~sh
make test                  # C++ model + all native C suites
make test-codec            # codec-roundtrip
make test-mapping          # mapping authority, transactions, overwrites, raw/discard
make test-gc               # liveness, forbidden victim, rotation, cost
make test-lower-io         # flush/FUA, lower write aggregation
make -C tests/suites test-all
~~~

There are **14 behavior-named native C executables** in `build/tests/native/`: `codec-roundtrip`; `mapping-authority`; `transaction-publication`; `write-verification`; `dead-segment-reclamation`; `raw-discard`; `online-packing`; `randomized-authority`; `gc-forbidden-victim`; `gc-cost-accounting`; `gc-rotation`; `gc-engine-rotation`; `flush-ordering`; `lower-write-aggregation`. Current V3 test source names reflect behavior in `tests/runtime/native/{codec,mapping,gc,io}/`, without deleting native assertions. Historical v22/host scripts are retained until CI dependency parity is established. One declarative rule in `tests/suites/Makefile` replaces 14 nearly identical C compile recipes. Python helpers must be bounded/necessary and should not replace actual C tests. For sanitizers, use the applicable `SANITIZE=1` native test target and independent ASan/UBSan/Clang gates described in [compile.md](compile.md).

## Minimum correctness matrix

- Compression/decompression: 4096B data and CRC, very small, medium, near-3568B LZ4 payload, RAW fallback, corrupted metadata/CRC and invalid bounds.
- Mapping: latest-generation-wins, compressed↔RAW, multiple overwrites, same-page and disjoint reads, pending-write authority, only post-success publication, readback of **every page**.
- Ordering and lifecycle: PREFLUSH-only, data+PREFLUSH, FUA, DISCARD same/different page, worker-quantum boundaries, full-window flush, suspend/drain (including 1024 accepted BIOs in controlled loaded tests), exactly-once completion.
- Concurrency and GC: stale-read ownership, inflight buffers, segment liveness, blocked full-destination/256-survivor victim, at least eight verified GC reserve-role rotations in the loaded test, invariant-safe retries after failure.
- Failures: pre-submission synthetic write/flush EIO; bounded corrupted backing reads; bypassed READ failing with pending writes; true lower READ/WRITE/flush device-originated or torn completions **only when a safe isolated mechanism is available**. Do not present a synthetic `test_fail_write_nth` injection as real-device fault coverage.
- Resource: bounded worker time, CPU, memory, GC write/read amplification, pending callback drain, no data loss or false positive completion.

Any byte mismatch, double/lost completion, authority violation, unsafe GC reuse, broken PREFLUSH/FUA ordering or unsound fail-close is a **stop-loaded-benchmark** issue. Preserve minimal C-level reproduction and all original failures. Do not remove the test to get green CI.

## Automated gates and responsibility

- `.github/workflows/project-goals.yml` on `main` runs native C/C++ tests, userspace build, one-build-root and documentation governance.
- `.github/workflows/extent-v3-codec.yml` runs actual-C and source gates and V3 W=1/W=2 kernel builds.
- `.github/workflows/kernel-bestfit4-experimental.yml` is a **manual archival reproduction only**; the combined rootless compatibility/safety workflow remains push-triggered to preserve existing safety contracts, **not** as a mandatory V2.2 benchmark arm. Active required gates are V3 exact-source/native C, kernel compile and general teardown safety.
- A code/build/test/CI change must update a **relevant one of the four current standards** in the same `main` commit; add `README.md`/`VISION.md` when their content changes. Document the failure before repair and rerun at the **final exact HEAD**.

Do not infer green workflow status from the previous commit. A compiler-only success does not qualify a newly changed kernel target as loaded safe.

## Controlled loaded-kernel preflight (no exceptions)

Capture `/proc/swaps`, mounts, lsblk/DM holders and exact module identity; only use a **newly owned, verified memory-backed `null_blk`** test instance. Ensure matching expected major/minor, DM UUID/table, no mounts/active swap. Load only the **V3** module for active qualification; the retired V2.2 target is not part of test/benchmark gates. Do **not** touch `/dev/sdb1`, `/swapfile`, active swap, any physical/unowned device, unrelated DM or system swap/zswap; never reboot, `swapoff`/`swapon`, global failure inject or force teardown. If a hung BIO/holder cannot be safely removed, quarantine test ownership and mark BLOCKED.

## Same workload and realistic source pages

For benchmarking and comparative correctness, feed *identical* immutable 4KiB fixtures and logical trace (offsets, op ordering, read generations, warmup, QD, achieved work) to bare owned null_blk "off" and experimental V3, and verify **full final logical image**. Rootless scratch-file labels do not prove a loaded V3 kernel run. Report fixture/trace/write-stream hashes and actual measured LZ4 sizes. Make compressible **anonymous** heap/stack/COW/text-buffer/decoded-raster/zeros the primary synthetic hypothesis, moderate-entropy controls and incompressible cases separately. Clean file-backed ELF/source/image pages may never enter swap; synthetic weights are not measured real-world swap population. See [benchmark.md](benchmark.md).

## Known gaps (do not overclaim)

As of consolidation, the **loaded off-versus-V3 immutable-trace comparison has NOT been performed**. Genuine device-originated read/write fault coverage is incomplete; kernel-worker CPU attribution, the historical extra backing WRITE request in 120 trials, and generic asynchronous Buffer I/O error attribution are unresolved. The alpha.8 READ-bypass matched-rate result was negative, notwithstanding exercised loaded correctness. Older reports, `PRODUCTION_READINESS.md` and historical `CODEX_VALIDATION.md` preserve detailed provenance, **not new test requirements**.

At the end of each implementation task, update this or another of the four standards with learned results, exact tests and PASS/FAIL/BLOCKED, while preserving separate versioned raw report evidence on `main`.

## Automated governance for the four standards

The `main` project-goal workflow checks that `AGENTS.md`,
`agent.md`, `CLAUDE.md`, Copilot instructions, `CODEX_VALIDATION.md`,
`README.md` and `VISION.md` all reference the four governing standards.
A same-commit change to kernel, tests, userspace, Make/DKMS or CI workflow
paths must also modify at least one of `coding_standards.md`,
`testing_standards.md`, `compile.md` or `benchmark.md`. An unrelated
archival Markdown update cannot satisfy this gate. Documentation-only
changes do not require a separate implementation commit. This is a
mechanical check of **where the learning is recorded**, not a validator
of semantic truth, tested runtime behavior or external agent prompt
compliance.

## Active V3-only default gates

`make test` runs V3 native C suites without the retired C++ model; the
latter is retained for explicit historical reproduction only.
`python3 -B tests/runtime/benchmark/io-replay-test.py -v` verifies the
**two-arm** off/V3 oracle including bad-input rejection in safe rootless
files. Benchmarks require an actual loaded V3 module before claiming
performance. Regressions focus on 2:1-ish **measured** LZ4 inputs, raw
fallback, 4KiB/8KiB/16KiB packing, GC and same-page read ordering.

### Retained rootless compatibility safety checks

The combined-rootless workflow remains **push-triggered** because its
workflow-contract regressions explicitly verify executable source
safety gates and their trigger coverage. Removing its push trigger
caused CI failures on V3 transition commit `c240696`, so the trigger
was restored before final qualification. This compatibility suite is
**not** an active V2.2 benchmarking requirement; no retired V2.2
performance comparison should enter new V3 lower-I/O reports. Keep
real V3 kernel C and owned-null_blk safety contracts enforced.

## Runtime tree consolidation — October 14, 2026

Moved/renamed all **14 C native test sources** into
`tests/runtime/native/{codec,mapping,gc,io}/` with functional names;
all test logic and the 14 output executable identities remain. A
**single Make compile rule** now builds them against the same production
kernel codec/authority/engine implementations, preserving their suites.
Moved the three active anonymous-page/immutable-replay scripts to
`tests/runtime/benchmark/`, and renamed the V3 production-source
contract test to `tests/runtime/native/source-contract-test.py`.
Updated source-relative includes/import paths and active workflow
references. Deleted old root-level names; historical Git commits
retain the exact original files. Run `make test`, direct source
contracts and the off/V3 replay test at **final HEAD**.

The remaining V2.2/pressure/recall and old-host helpers remain at
`tests/runtime/` while their sibling imports and literal workflow
references are audited. Their safety CI is **not waived or replaced by
inert stubs**. Subsequent legacy relocation requires explicit test
parity; this is not a claim that all historical duplicate Python
utilities have been eliminated.

### CI relocation fix

On the first test-layout commit `020bec7e`, all 14 native C tests, the
benchmark oracle and the V3 kernel build passed, but project-goals CI
still referenced the removed root-level `io-replay.py` in its policy
guard. The active two-arm manifest contract now resides at
`tests/runtime/benchmark/io-replay.py`. The guard must check this
path and reject the obsolete name. This failure was test-harness
plumbing, **not** proof of a kernel runtime defect or a loaded win.
