# Round 009 — Agent 1 closeout: both real source integrations; hosted Linux CI pending

**Disposition:** `CLOSED_SOURCE_INTEGRATED_CI_PENDING` — exactly 2/2 delivered source code, parent verified, separately integrated on canonical `main` by guarded non-force commits. This is **not** a Linux Kbuild PASS, authenticated kernel ABI qualification, or runtime proof.

## Frozen authority
- [Unique ROUND_OPEN in #126](https://github.com/k1moradi/swapz/issues/126#issuecomment-6905118318): frozen source `4063b88422dd62b1d4b1a990f0cfe9961e73277c`, final task commit `419db8446a4d9ad58dfaf4bbebdee8895515e070`.
- Actual worker source objects are real retrievable Git commits and each has the exact frozen parent; no worker pushed remote `main`.

## Agent 3 — independent build metadata correction

- [Original source commit `7f49d99`](https://github.com/k1moradi/swapz/commit/7f49d99ac919d23a956a23a6a7efa881a22d01a3), [primary `REPORT_READY`](https://github.com/k1moradi/swapz/issues/126#issuecomment-6905235304), [verbatim archived report](agent3-original-report.txt).
- Four actual source changes: existing `.github/workflows/phase-a-linux-source-preflight.yml` adds quoted `SWAPZ_BUILD_SOURCE_CLEAN_STRING` to the real workflow-generated build-info header, existing `.github/workflows/product-codec.yml` runs new executable `tests/runtime/native/pinned-gcc-build-info-source-test.py`, and `docs/coding_standards.md` adds the relevant governing contract. The prior first error `dm-target.c:71` was missing that quoted macro; consumer `MODULE_INFO` remains unchanged.
- [Coordinator source integration `7ff6a5b5`](https://github.com/k1moradi/swapz/commit/7ff6a5b5bd5eb78f660b37f3582dd4df0e64f94c); code paths and Git blobs verified against original. Reported worker-local source-test 7/7 PASS and 14/14 malformed cases rejected: **local source evidence only**.
- [Exact hosted GCC pinned Linux preflight run #43790416873](https://github.com/k1moradi/swapz/actions/runs/43790416873) was still **IN_PROGRESS** at administrative closeout; do not infer `dm-swapz.ko` linked for either `CONFIG_ZSWAP=y/n`.

## Agent 2 — real Linux C/H source-staging producer prototype

- [Original source commit `b4ed94e7`](https://github.com/k1moradi/swapz/commit/b4ed94e73a778db8772d48dc9a6a1364b603bcc5), [primary `REPORT_READY`](https://github.com/k1moradi/swapz/issues/126#issuecomment-6905279759), [verbatim archived report](agent2-original-report.txt).
- Four actual source changes: executable `tests/tools/stage-pinned-linux-zswap-origin.py` with six pinned upstream C/H file edits and preimage checks, executable `tests/runtime/native/pinned-linux-zswap-origin-stage-test.py`, independent real-source workflow `.github/workflows/phase-a-zswap-origin-prototype.yml`, and relevant `docs/testing_standards.md`. No fake patch publication, writable upstream repository, physical swap operation or upstream mutation.
- [Coordinator source integration `1db78aba`](https://github.com/k1moradi/swapz/commit/1db78aba3d141ae329ea0225b67e283076fe45ed); code paths and parent verified, distinct standards preserved. Worker-local rootless staging 12/12 PASS and 11 upstream source anchors checked; **not the full compiled or loaded modified Linux**.
- [Exact-source hosted modified Linux prototype run #43790479509](https://github.com/k1moradi/swapz/actions/runs/43790479509) was **IN_PROGRESS** at administrative closeout. It must compile actual modified `mm/zswap.o`, `mm/page_io.o`, `block/bio.o` for `CONFIG_ZSWAP=y/n` before a pinned source Kbuild PASS can be asserted. No KUnit or real zswap eviction/readback executed by worker.

## Original reports, Git main and qualification status

- [Exact UTF-8 original worker issue comments with SHA-256](original-report-archive.md) were archived verbatim at [`69810561`](https://github.com/k1moradi/swapz/commit/698105617a1da4244774292182328ddc8b5fe5dd): Agent 3 `f9db7a5e4162bcd3c7f1df7a7aad6369fe08209b64b5b10c3de1460c6c849ebc`, Agent 2 `272673ae172098d1bcaf2bcdf5b4d53ef2a9631d089a9176c8c3ca729d99f23e`.
- Rootless physical evidence [run #43790479459](https://github.com/k1moradi/swapz/actions/runs/43790479459) **PASS** on `1db78aba`; native [#43790479467](https://github.com/k1moradi/swapz/actions/runs/43790479467), production-C [#43790479390](https://github.com/k1moradi/swapz/actions/runs/43790479390) and other native runs were **IN_PROGRESS** at closeout. Do not conflate their later outcomes with this checkpoint.
- A later GitHub Actions check can be added as **separate time-stamped follow-up** with exact run/commit SHA and job results, without changing earlier reported facts.

**Round 010 scope can proceed independently** from already committed source. The next tasks must never assume that currently running Linux Kbuild passed: separate source-hardened provenance semantics/tests and a fail-closed matched patched-kernel + swapz external-module CI qualification workflow are independently executable on the frozen integrated source. Neither needs the other’s edits.

**Phase A BLOCKED** on the real matched MM→BIO→DM build and authenticated forced writeback/readback, **Phase B RAW bypass DISABLED**. No module loading, reclaim, active mapper/swap or physical device operations.
