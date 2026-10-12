# Evidence bundle: swapz V3 alpha loaded null_blk validation

Canonical report: `validation-report.md`. All reported source, module and run identities are in `source-module-identity.txt`; `ci-runs.txt` lists exact-source GitHub runs.

- `rootless/`: final exact-C, randomized C, source-contract and workflow-contract output.
- `final-check/`: final exact command reruns of the randomized C property test and both Python source/workflow suites.
- `rootless-variants/`: GCC `-O0`, GCC `-O2`, and Clang ASan/UBSan builds/executions for all seven baseline exact-C suites plus the randomized suite. `initial-invocation-cwd-error.log` records the corrected out-of-worktree include-path invocation mistake noted in the report.
- `build-*.log`: W=1/W=2/final W=1 module build transcripts.
- `raw/`: page smoke, extent geometry, concurrent fio, GC successes and suspend/resume snapshots.
- `read-budget/`: per-repetition raw counters, extent dumps, latency CSVs and summaries for read caps 0–3.
- `faults/`: foreground partial write, raw/read/CRC errors, and GC relocation failure evidence. These negative-path I/O errors were deliberately injected on the uniquely owned null_blk.
- `final-state/`: post-cleanup module, DM, swap, null_blk, protected-file and kernel-log inventory.

`SHA256SUMS` covers this README, the report and every evidence file except the manifest itself. No compiled module or test executable is included; the module digest and build logs are recorded instead.
