# Agent 8 — Round 004: real pinned upstream Linux CONFIG_ZSWAP Kbuild matrix

**Task ID:** `agent8-pinned-linux-kbuild-source-matrix`
**Round issue:** https://github.com/k1moradi/swapz/issues/121
**Frozen `swapz/main` baseline:** `f9f65369c2dba65797989e10374e2350d58d25c2`
**Source target:** read-only `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` (Linux 7.3 development source, **not** a committed swapz provenance producer).
**Execution:** Begin only after Round 004 `ROUND_OPEN`; start **simultaneously** with Agent 5 without waiting for its code/results.

## Edit the existing source-controlled CI implementation

- **Exclusive implementation path:** `.github/workflows/phase-a-linux-source-preflight.yml`. The current CI workflow already checks out the entire pinned source via `actions/checkout@v4` and has [verified clean SHA, 97,310 files, `defconfig` and `make prepare` PASS](https://github.com/k1moradi/swapz/actions/runs/43718607383). Extend this actual, existing CI code; do not create a parallel workflow, Linux fork, side branch, external source patch or entire vendor source tree inside swapz.
- **Applicable governing standard:** append one specifically named `Round 004 pinned CONFIG_ZSWAP Linux source Kbuild` section to `docs/testing_standards.md` in the *same source commit*. Agent 5 writes a distinct appendix to the same standard; keep edits isolated and let Agent 1 serialize/merge, no coordination needed.

## Technical changes required

1. Retain the pinned read-only exact source `git rev-parse HEAD`, clean checkout/file-completeness checks, host dependency `libelf-dev`, and existing `defconfig` + `make prepare` passing gate. Verify source identity **before** modifying out-of-tree build configuration. Never rely on the worker's failing local DNS or a prebuilt binary with mismatched source.
2. Extend CI to create **separate, bounded out-of-tree build directories** under `RUNNER_TEMP` for `CONFIG_ZSWAP=y` and `CONFIG_ZSWAP=n` using Linux's own `scripts/config` and `olddefconfig`. Verify the effective generated `.config` actually contains the intended state; reject silent Kconfig fallback.
3. Perform **real Kbuild compilation of actual pinned Linux swap/BIO source objects** as supported by that exact tree (e.g. `mm/page_io.o`, `block/bio.o`, and enabled-`CONFIG_ZSWAP` `mm/zswap.o`), with a configurable bounded parallelism and warning settings. Do not claim KUnit execution or full `vmlinux` build unless those are actually executed. Record exact compilation commands, exit statuses, compiler version, `.config` SHA-256 and source SHA for each config. On missing host packages, install only bounded standard build dependencies in disposable runner; preserve first failure and do not skip errors.
4. Upload a concise per-config evidence manifest **even on failure**, without logging credentials or large build artifacts. Keep CI runtime/resource requirements bounded and the workflow read-only (`permissions: contents: read`), no extra persistent source repository, no kernel/module installation or loading, no swap/mapper/physical operations.
5. A **PASS** is only an actual completed exact-source hosted run of the modified CI workflow. If you cannot push a branch (prohibited) or trigger hosted CI from an unreferenced commit, prepare a **retrievable actual workflow-code source commit**, report `BLOCKED_CI_PENDING_COORDINATOR`, and let Agent 1 non-force integrate and verify the hosted run. A clean Linux base Kbuild is NOT the yet-missing authenticated producer's Kbuild/ABI/Phase A qualification.

## Publication and report

Edit actual YAML code and additive standard text from `f9f65369c2dba65797989e10374e2350d58d25c2`, build an actual Git tree/commit object with that parent SHA and no other modifications. Do not touch Agent 5's C fixture, product C or kernel upstream source. No remote `main` update, branch/PR/fork/secondary worktree/force push, patch-only handoff, or wait for Agent 5.

Post `message: REPORT_READY` in https://github.com/k1moradi/swapz/issues/121 with `round: "004"`, `agent: 8`, task ID, exact source commit SHA/URL, changed files, exact source revision/config states, tested commands/exits, artifact IDs, first failure, evidence class and NOT_RUN/blocked limits. Phase A remains BLOCKED and Phase B disabled.
