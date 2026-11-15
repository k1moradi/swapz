# Round 004 — coordinator closeout (2026-11-15)

**Reporting state: CLOSED; 2/2 worker reports archived verbatim with verified SHA-256 identifiers. Engineering outcome: SOURCE-INTEGRATED; HOSTED FULL-SOURCE CI PASS for bounded rootless and pinned-stock-Linux configurations. Phase A: BLOCKED. Phase B: DEFERRED/DISABLED.**

## Frozen contract

- Frozen swapz baseline: `f9f65369c2dba65797989e10374e2350d58d25c2`.
- Final task publication: `1f26be79a94cc856b58e03388c866a3e4df488eb`, [authoritative ROUND_OPEN](https://github.com/k1moradi/swapz/issues/121#issuecomment-6895822859).
- Workers: **two independent agents (5 and 8)**, both created actual source commits parented at the frozen baseline and did not push remote `main`. Agent 1 was sole authorized `main` integrator.

## Code and original reports

| Worker | Original code object | Actual integrated source | Original report archive |
| --- | --- | --- | --- |
| Agent 5 — real C parser adversaries | [`108e725ef7bed612330e71aa887e96dc60c38889`](https://github.com/k1moradi/swapz/commit/108e725ef7bed612330e71aa887e96dc60c38889) | `tests/runtime/native/userspace/swapzctl-status.c` + governing standard in [integration commit `275187fa`](https://github.com/k1moradi/swapz/commit/275187fa53d8c00200093cf1d56a9ba806e5bd2c); 372 bounded test cases authored, no production parser source changed | [issue #121 comment 6896125973](https://github.com/k1moradi/swapz/issues/121#issuecomment-6896125973), [exact archived body](agent5-original-report.md), SHA-256 `d6580ea93c1f62097b3d834e2f61398046637d560b5cb38fadcf407918c4a1a6` |
| Agent 8 — exact pinned upstream Linux Kbuild CI | [`893e3eddb2d75f6e037e5e1668011d25b01cf5a7`](https://github.com/k1moradi/swapz/commit/893e3eddb2d75f6e037e5e1668011d25b01cf5a7) | `.github/workflows/phase-a-linux-source-preflight.yml` + governing standard, in [integration commit `275187fa`](https://github.com/k1moradi/swapz/commit/275187fa53d8c00200093cf1d56a9ba806e5bd2c) | [issue #121 comment 6896102664](https://github.com/k1moradi/swapz/issues/121#issuecomment-6896102664), [exact archived body](agent8-original-report.md), SHA-256 `8e2d8188d2dcd1295cf989c8816b0ed2261efc032ef62c80f8abb0070afe73b6` |

The SHA-256s identify raw original UTF-8 GitHub issue comments, **not** this report. Their full unedited bytes and source links are preserved in [original-report-archive.md](original-report-archive.md); do not reinterpret workers' original `BLOCKED_CI_PENDING_COORDINATOR` reports as having claimed runtime PASS.

## Independent hosted exact-source verification

1. [Pinned Linux Kbuild #43726191654](https://github.com/k1moradi/swapz/actions/runs/43726191654) at integration commit `275187fa53d8c00200093cf1d56a9ba806e5bd2c`: **PASS**. The real exact public `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` source was checked out; the workflow validated separate effective `CONFIG_SWAP=y`, `CONFIG_ZSWAP=y/n` out-of-tree configs, compiled real `mm/page_io.o`, `block/bio.o` under both and `mm/zswap.o` under enabled profile. Build evidence was uploaded as artifact **14166910946**, named `phase-a-linux-source-preflight`. The GitHub workflow job is **success**, not a modified producer.
2. [Native project-goals #43726191538](https://github.com/k1moradi/swapz/actions/runs/43726191538), same source commit: **PASS all seven jobs**, including `Native rootless`, rootless source-contract, Make-interface, repository policy, lifecycle and exact-SHA aggregator. Native `make -C tests/suites ... test-userspace` executes the compiled fixture that now includes the 372 new bounded parser adversarial cases. No independent instrumented per-case execution log has been published; 372 is the **source-defined** count, not a claimed independently collected per-case result.
3. [Exact production-C qualification #43726191553](https://github.com/k1moradi/swapz/actions/runs/43726191553) and [systemd/package #43726191583](https://github.com/k1moradi/swapz/actions/runs/43726191583): **PASS** on source integration revision. Later archived-report-only commit `5aa748c2f26b91eaa84f9078c22635bd74d3e207` also passed its recorded Native, production-C and package CI runs.

## Remaining engineering gate

The original Round 002 upstream producer candidate is **not committed in a real owner-authorized writable Linux source repository**, nor qualified by these stock Linux Kbuild runs. No positive authenticated `zswap_writeback_entry` → swap-I/O/BIO → DM provenance or mixed-origin clone/split and 4KiB byte-exact real swap readback has been observed on a matched patched kernel. The consumer still uses default UNKNOWN where no authenticated carrier is present. No actual kernel boot/install, loaded module, swap/reclaim, mapper mutation, device or physical test is claimed here.

**Closing issue #121 means the assigned *source-controlled* tasks and hosted qualification are accountable and complete, not that Phase A passed or that Phase B RAW bypass is authorized.**
