message: REPORT_READY
round: "006"
agent: 8
task_id: agent8-pinned-linux-clang-config-build
status: SOURCE_READY_PENDING_COORDINATOR_CI

**Real, retrievable Git source commit:** [a2fcfddb86d8a0e295802fbaeac7869281f35631](https://github.com/k1moradi/swapz/commit/a2fcfddb86d8a0e295802fbaeac7869281f35631)
**Exactly one parent:** `47a793c1480556c075f23ecbe13a5b465d616916`; Git tree `b12d6384a9df4fb7dc2dee25455926be2f60f5a3`. The GitHub commit API and compare verify both.

**Actual source-controlled edits (two files only):**
- `.github/workflows/phase-a-linux-source-preflight.yml` (+216/-0). Append the completely independent `pinned-linux-clang-objects` job; original GCC full-kernel/external-module job is byte-for-byte unchanged. This job has no `needs:` edge to GCC. On Ubuntu 24.04 it installs bounded clang-18/lld-18/llvm-18 and standard Kbuild dependencies, checks out the exact full public `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` with credentials disabled, validates original checkout SHA/cleanliness/file count/required source, verifies versioned LLVM tools, records package/compiler/linker versions and binary SHA-256, and builds two independent out-of-tree `O=` profiles with `LLVM=-18`, `-j2`, `W=1`. It invokes Linux `scripts/config` and `olddefconfig` and rejects any effective Kconfig fallback from `CONFIG_SWAP=y`, requested `CONFIG_ZSWAP=y/n`, or `CONFIG_CC_IS_CLANG=y`. It compiles `mm/page_io.o block/bio.o` on both profiles plus `mm/zswap.o` only for enabled ZSWAP; verifies real nonempty outputs and clean upstream tree, rejects warning-only green builds, and always uploads bounded per-profile text manifests including command/exits/config SHA/source and first failed phase.
- `docs/testing_standards.md` (+37/-0): unique additive `Round 006 independent pinned Linux Clang source Kbuild` governing section.

**Available tests executed (local only, NOT a full-source Linux compiler run):**
1. `python3` PyYAML `safe_load` on the added job: **PASS**, exit 0.
2. `bash -n /mnt/data/agent8-clang-build.sh` on the precise embedded job Bash: **PASS**, exit 0.
3. `python3 /mnt/data/test-agent8-clang.py` with temporary fake Git/make/compiler/Kconfig scripts: **8/8 PASS**, exit 0. Scenarios and actual/expected exits: normal enabled+disabled (0/0), enabled Kconfig fallback (1/1), disabled compilation failure preserving earlier enabled PASS (19/19), Clang warning gate (3/3), missing compiled object (1/1), incorrect source SHA (1/1), out-of-range parallelism (2/2), unexpected disabled zswap object (1/1).
4. Exact source transfer verification: committed new job **10,649 bytes** FNV-1a32 `166d19cc` (same as locally tested YAML); embedded Bash **7,168 bytes** FNV-1a32 `47ca2c72` (same as mocked/tested Bash). GitHub post-commit static scope assertions: **12/12 PASS** (SHA, parent, only two paths, original GCC untouched, independent parallel job, exact Linux revision, always artifact, no full-kernel/module link, Kconfig gates, unrelated C sources untouched, standard update and job identity).

**Evidence class:** `SOURCE_READY_PENDING_COORDINATOR_CI / LLVM_STOCK_SOURCE_OBJECT_KBUILD` is the prospective hosted lane, NOT a completed hosted PASS. **Actual hosted Clang Kbuild:** NOT_RUN for this unreferenced commit, as required. **Hosted artifact IDs:** none. **First local failure:** none in 8 successful control cases; negative paths deliberately preserve their injected first failure and exits. The worker's local container cannot download the complete pinned Linux source because external GitHub DNS is unavailable. LLVM 18 package compatibility and the real pinned-tree compile outputs remain unverified pending CI.

No branches, PRs, forks, worktrees, source code producer changes, main ref movement, kernel/module loading, mapper/swap or physical operations. **Phase A BLOCKED; Phase B RAW bypass DISABLED.** Agent 1 should non-force integrate the exact commit delta (serialize Agent 7's independent standards appendix), then run the hosted workflow and retain exact run/artifact IDs, Kbuild exit statuses and any first failure.