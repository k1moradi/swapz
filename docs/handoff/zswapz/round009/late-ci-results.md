# Round 009 — late exact-source hosted results (2026-11-15, after initial administrative report)

This addendum updates the original [Round 009 closeout](round-report.md) **without retroactively replacing the checkpoint**. Original worker source review, integration and verbatim report archive remain unchanged.

- **Actual modified pinned Linux MM/BIO provenance source, y/n:** [GitHub Actions #43790479509](https://github.com/k1moradi/swapz/actions/runs/43790479509), exact source `1db78aba3d141ae329ea0225b67e283076fe45ed`, **SUCCESS**. The single real hosted `Modified pinned Linux CONFIG_ZSWAP=y/n object Kbuild` job ID `133047525686` succeeded every step: full upstream checkout, 12-case rootless staging regression, modification of **six** real upstream C/H files, per-profile modified-object Kbuild of `mm/page_io.o` and `block/bio.o` plus enabled-only `mm/zswap.o`, and evidence upload. [Artifact #14192086590](https://github.com/k1moradi/swapz/actions/runs/43790479509/artifacts/14192086590), size 2794 bytes, was retained. This is **actual modified Linux source-object Kbuild PASS**, **not** KUnit, kernel boot, a matched linked `dm-swapz.ko`, or real zswap eviction/readback.
- **Production C (stock headers):** [#43790479390](https://github.com/k1moradi/swapz/actions/runs/43790479390), exact source `1db78aba`, **SUCCESS**. This is not a patched-kernel consumer integration.
- **GCC pinned Linux stock external module:** [#43790416873](https://github.com/k1moradi/swapz/actions/runs/43790416873), exact Agent 3 integrated source `7ff6a5b5bd5eb78f660b37f3582dd4df0e64f94c`, remained **IN_PROGRESS** when this addendum was written; **NOT QUALIFIED** until actual linked-module and byte-integrity job result.
- **Native rootless:** [#43790479467](https://github.com/k1moradi/swapz/actions/runs/43790479467), exact source `1db78aba`, remained **IN_PROGRESS** at this checkpoint; no PASS asserted for the unfinished workflow.

**Phase A remains BLOCKED**: no matched MM→BIO→DM loaded source, no verified origin during actual zswap stored-entry writeback, no byte-exact runtime readback. **Phase B RAW bypass DISABLED.** No device operations performed.

Round 010 must use the actual integrated `main` source, and its independent workers must never take in-progress GCC or hypothetical KUnit success as a prerequisite. Follow-up CI results can be appended as new timestamped evidence.
