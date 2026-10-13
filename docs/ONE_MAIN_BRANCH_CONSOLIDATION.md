# One-main-branch consolidation (2026-10-13)

This repository intentionally uses **main as the only maintained branch**. No new feature, validation or research branches should be created. Change files on main with ordinary reviewed commits and run CI on each revision. Preserve independent Codex evidence in versioned report directories, not additional long-lived branches.

## Original refs and preserved histories

Exactly **68** named branch references existed before the consolidation, including main and 20 divergent histories. Their exact original branch SHA values and 46 open PR references are recorded in [the machine-readable manifest](docs/branch-consolidation-2026-10-13.json). The single consolidation merge commit has as parents the already source-qualified `feat/threeway-identical-workload-replay` tip and all 20 previously-diverged branch heads. Other original branch heads are ancestors of that first parent. This ensures **the branch commit histories remain reachable from main after refs are deleted**, even when a divergent feature did not pass the test gates or was not included in the checked-out code. Original source can be inspected through recorded historical SHA values and Git merge parents.

**Critical distinction:** merging Git history is NOT equivalent to enabling every conflicting feature. The main working tree retains a conservative **default V2.2 module** (`kernel/Makefile`, `Makefile` and `dkms.conf` unchanged from the prior main) with experimental V3 in `kernel/extent-v3/`. V3 is NOT loaded simultaneously with V2.2 and is restricted to uniquely owned RAM-backed null_blk; no production or physical-media claim. Alpha.8 read bypass is unproven at matched load and was deliberately NOT enabled in the main working tree. Prior drafts and negative experiment trees remain in Git history, not silently merged into the runtime.

## Current research gate

- Actual foreground LZ4-size admission histograms and reproducible synthetic anonymous-memory-style page fixtures are in the working tree. Synthetic weights are NOT measured Linux swap proportions.
- The three-way **no-compression off / frozen V2.2 / experimental V3** replay protocol ensures identical 4KiB fixture SHA, logical operation sequence and expected complete readback. Off is bare owned RAM null_blk, NEVER changing active swap.
- Rootless source and exact-C tests passed at the pre-merge three-way branch tip; main workflows must run again at the consolidation merge commit.
- A loaded three-way comparison with this precise plan, kernel-worker CPU attribution, full device-originated fault handling and V3's singleton-window performance challenge are still open. Keep experimental gates intact.

## Deleting old refs safely

The one-time workflow [one-main-branch-prune.yml](../.github/workflows/one-main-branch-prune.yml) is authorized by the explicit user instruction to remove all branch refs **other than main**, but only after checking that (1) main has the entire historical commit ancestry; (2) no branch tip moved relative to the archived manifest; (3) main has not advanced during the check; and (4) no unexpected branch name exists. It will refuse unsafe deletion, never force-update a branch, and never delete main. Branch deletion can close open pull requests; their historical metadata and commits are preserved in the manifest and merge ancestry. If GitHub rejects deletion due to permissions or protection, that must be reported as a remaining branch and not misrepresented as success.

No GitHub branch deletion alters host storage. The hard ban on reboot, active /swapfile and /dev/sdb1, swapoff/swapon and physical-media test I/O remains unchanged.
