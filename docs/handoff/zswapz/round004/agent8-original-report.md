message: REPORT_READY
round: "004"
agent: 8
task_id: agent8-pinned-linux-kbuild-source-matrix
status: BLOCKED_CI_PENDING_COORDINATOR

**Real retrievable source commit:** [893e3eddb2d75f6e037e5e1668011d25b01cf5a7](https://github.com/k1moradi/swapz/commit/893e3eddb2d75f6e037e5e1668011d25b01cf5a7)
**Exact parent:** `f9f65369c2dba65797989e10374e2350d58d25c2` (verified via Git commit API).
**Source baseline targeted:** read-only `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` (Linux 7.3 development source).

**Changed actual tracked files (exactly two, verified compare):**
- `.github/workflows/phase-a-linux-source-preflight.yml` (+154/-5): preserves existing pinned clean/full-source verification and original defconfig/prepare gate; adds bounded disposable build dependencies, two independent out-of-tree CONFIG_SWAP=y / CONFIG_ZSWAP=y,n configurations, scripts/config + olddefconfig and effective-state validation, make prepare and targeted Kbuild object compilation, pre/post source cleanliness, fail-first logging, per-config .config SHA-256/compiler/source/command/exit records, and always-on evidence upload.
- `docs/testing_standards.md` (+30/-0): additive `Round 004 pinned CONFIG_ZSWAP Linux source Kbuild` governing section.

**Exact planned hosted compilation targets:** CONFIG_ZSWAP=y: `mm/page_io.o block/bio.o mm/zswap.o`; CONFIG_ZSWAP=n: `mm/page_io.o block/bio.o` (and absence check for `mm/zswap.o`). Both use separate `$RUNNER_TEMP/linux-kbuild-{enabled,disabled}`, `CC=gcc`, default `-j2 W=1` (bounded input validation), `make defconfig`, `scripts/config --enable SWAP --enable/--disable ZSWAP`, `make olddefconfig`, `make prepare`, and actual `make` targets. All command lines and exit statuses are emitted to per-profile uploadable manifests. Neither configuration performs installation/loading, swap, mapper or physical I/O.

**Actual test results (local, unprivileged):**
- `bash -n /mnt/data/agent8-local-tests/matrix.sh`: exit **0**, PASS. The local script matches the committed workflow's exact 4,955-byte matrix run body (FNV-1a32 `4a956101`, matching all 127 line fingerprints).
- `/mnt/data/agent8-local-tests/test-matrix.sh` using *fake* Git/make/Kconfig commands and temporary paths: **7/7 PASS** with expected exit statuses: success 0; Kconfig fallback rejection 1; disabled-profile compile failure 19 (first failure preserved while enabled manifest PASS); invalid parallelism 2; mismatched source SHA 1; missing compiled object 1; unexpected disabled zswap object 1. **These are mocked control-path tests, not Linux compilation.**
- GitHub commit API: parent SHA exact, tree exists; compare shows only the two authorized files, no branch ref moved.
- Remote-source static assertions: **13/13 PASS** covering exact pinned checkout, read-only permissions, previous gate, deps, separate outputs, config verification, object targets, resource bounds, upload on failure, additive standard, and blocked statuses.

**Evidence class:** `RETRIEVABLE_WORKFLOW_SOURCE_COMMIT_PLUS_LOCAL_MOCK_CONTROL_TESTS`.
**Hosted CI:** **NOT_RUN** for this unreferenced commit; cannot claim real `CONFIG_ZSWAP=y/n` Kbuild PASS until Agent 1 non-force integrates and hosted Actions completes. **Artifact IDs:** none; evidence manifests defined but not uploaded by a hosted run. **First actual failure:** none in the seven local control tests; hosted compilation/actual Linux Kconfig results **NOT_RUN**, not inferred successful. The worker cannot download/build the complete pinned source locally because outbound GitHub DNS/network access is unavailable.

No branch, PR, fork, remote main update or force push was created. No KUnit, full vmlinux, upstream producer patch, matched-module ABI, loaded writeback, swap or physical test was run. **Phase A remains BLOCKED; Phase B RAW bypass remains disabled.** Coordinator action: integrate this retrievable commit's two-file delta with any concurrent Agent 5 standards edit, then run the hosted workflow and retain exact successful/failed artifact IDs and first failure.