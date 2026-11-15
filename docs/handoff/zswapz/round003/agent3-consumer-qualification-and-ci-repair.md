# Agent 3 — Round 003 DRAFT: actual consumer CI diagnosis and focused repair

**State: DRAFT / DO NOT EXECUTE before Round 003 `ROUND_OPEN` in [issue #120](https://github.com/k1moradi/swapz/issues/120).**
**Task ID:** `agent3-consumer-qualification-and-ci-repair`
**Planning swapz baseline:** `408728d43c16e67556c41f2e55c11e56ed68c33b`, revalidated by Agent 1 at round opening.
**Previously committed implementation:** `a60d407f1e58879cdd6c38f79f24c8b6181d3d3d` and `721133790fa77b8ab47dc870abea833351799723`.
**Known source-bound CI failure:** [Native kernel-C project goals run #43710387874](https://github.com/k1moradi/swapz/actions/runs/43710387874) at `721133790fa77b8ab47dc870abea833351799723`, `quiet-lower-io-test.sh` `nonzero_exit`; **root cause unconfirmed**. Other workflows on that SHA succeeded and do not cancel this failure.
**Ownership:** Sole `swapz/main` code publisher **after** opening, until explicit `MAIN_WRITE_LEASE_RELEASED`. Agent 1 does not push `swapz/main` during this lease. No dependency on Agent 2's Round 003 results.
**Report archive:** `round003/agent3-consumer-qualification-and-ci-repair-report.md`.

## Priority 1: investigate actual CI failure, then fix only what is proven

1. Start from an existing **clean local `main`** synchronized to the verified canonical remote head. Read mandatory project standards and inspect the actual `721133790fa77b8ab47dc870abea833351799723` GitHub Actions logs and retained artifact as available. The job reported a `quiet-lower-io-test.sh` nonzero exit with insufficient root-cause information in the available top-level log.
2. Reproduce the failing test from actual source on an equivalent safe rootless environment. Capture first failure, deterministic inputs and exact exit code, then classify: product regression, test-harness reporting deficiency, environment/CI flake or unresolved. Do not assume the prior provenance code caused the failure; compare reproducibly against the pre-implementation baseline where appropriate.
3. **If a source defect is proven, patch the actual existing C/test source in place.** If the rootless harness suppresses the necessary first failure, fix that logging limitation along with the cause, as mandated by `AGENTS.md` and `docs/testing_standards.md`. Preserve fail-closed status and avoid success-output logging. Do not weaken assertions to turn CI green.
4. If CI failure is independently proven environmental/flaky and no product defect is demonstrated, provide reproduced evidence and a targeted stable test fix if justified; **do not invent a production C change** simply to produce a commit.

## Priority 2: verify actual passive provenance consumer, fix defects only

Review actual `src/kernel/dm-target.c`, including per-BIO descriptor initialization/reset/requeue, the guard `#ifdef BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN`, immutable scalar and atomic admission count, and all four successful foreground commit paths.

Check `verified_zswap_origin_admitted`, `foreground_committed_verified_zswap_writeback`, and `origin_carrier_compiled` for default-UNKNOWN semantics, no forged origin, no double count, failed/late completion and GC exclusion, correct INFO formatting and stable existing consumers. Validate equality of compression/RAW/zero choices for tagged-vs-untagged inputs; no Phase B RAW bypass. Ensure no use-after-completion, heap/stack bloat, new allocation or unnecessary hot-path locks.

Use real stock-header module builds `W=1/W=2` on available x86_64/ARM64 configurations and focused source-linked negative/concurrency tests. Do **not** compile a modified `struct bio` header against an unverified running kernel or claim a positive-tagged real-kernel test.

## Mandatory publication and reporting

When a defect is established, edit the **actual** affected existing source and narrow tests, update the relevant governing standard in the **same commit** if behavior/evidence changes, run `git diff --check`, available `make fast_test`/rootless build and exact targeted CI. Commit and push **non-force directly to `main`**, rechecking expected remote HEAD; no branches, PRs, forks, second worktrees, forced pushes, refactors, renames or untested replacements. Do not publish a diff as the code deliverable.

Report one `message: REPORT_READY` in issue #120 with linked actual source commits and exact SHAs (or clearly justified no-change finding), first-failure classification, exact tests and exits, and missing qualification. Explicitly include `MAIN_WRITE_LEASE_RELEASED`. **No Agent 1 archival commits while the lease is active.** Phase A remains unqualified and Phase B disabled.
