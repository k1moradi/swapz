# Round085 Agent9 — scoped historical CI trigger fan-out remediation

**State:** ROOTLESS_TRIGGER_REGRESSION_PASS; migration published and exact one-time automatic workflow registration VERIFIED 40/40. Remote qualification remains IN_PROGRESS. No production or activation qualification.

## Immutable scope

- [Official Round085 opening](https://github.com/k1moradi/swapz/issues/203#issuecomment-7131985167); task and audited workflow baseline `9e3c770004418cbf622f5f3eb647ee79ef5fe735`.
- Actual GitHub head_sha run lists for `1095acd05fff26c9da3941d62a12e179dcaeb808`, `3ef350588cec0e9d1364f80a94bea33e498144ad`, and `f7df9058c7291d15b6159b6bbe95e8a845113bf4` each returned 41 push-triggered workflows (123 total). The manifest records all exact run IDs, actual changed paths, complete before/after path arrays and per-workflow exact blobs.
- One coherent migration: 31 historical YAML files each lose only one standalone positive `docs/testing_standards.md` push-path line. All 82 workflow definitions were read; the regression checks complete text equality except that exact deletion. Preserve every other trigger, existing self/manual dispatch, branch, permissions, checkout, job, source verification, artifacts and concurrency. No workflow deletion, blanket disable, cancellation, skipped checks, manual dispatch or rerun. No product source changes.
- Always-on `project-goals.yml` blob `04596df7514ad33243d98c5a96295d8816d9ef07` and `tests/runtime/native/repository-policy-test.py` blob `b200e0ca3e20d4c1f37e350ac9ef1c6426179817` unchanged; canonical first-parent same-commit standards enforcement remains mandatory. Prior standards text preserved literally with a meaningful appendix in the migration commit. All R084 workflows untouched.
- Four broad workflows stay unfiltered (project-goals, product-codec, systemd-package-readiness, original-table-gc-lifetime). Five historical standards-trigger lanes remain conservative: kernel-debug, physical-evidence-rootless, R063/R064 original native KUnit inheritance, and R072 joined original native. Their broader/transitive dependencies need additional audit, not speculative narrowing. See [workflow manifest](agent9-workflow-manifest.json).

## Actual rootless results before publication

The exact pure JavaScript regression function serialized into `tests/runtime/native/round085-ci-trigger-contract-test.mjs` was executed in the rootless V8 tool runtime on all 82 complete connector-fetched immutable workflow snapshots and the 3 actual GitHub run lists/changed-path sets. Final result **PASS_ROOTLESS_TRIGGER_CONTRACT**, 12 scenarios, 581 retained-trigger witnesses, 31 retained edited self/manual triggers, 79/79 manual-dispatch workflows, 10/10 rejected negative mutations, 173348 individual guard evaluations. These are executable trigger checks, NOT compiler mutants or actual Actions runs.

| Scenario | Before | Predicted after |
| --- | ---: | ---: |
| R084 A5 / A10 / A11 each (actual before) | 41 | 10 |
| Unrelated standards append | 40 | 9 |
| Ordinary DM source | 25 | 25 |
| Historical exact helper | 12 | 12 |
| Historical wildcard fixture | 10 | 10 |
| Policy workflow self | 4 | 4 |
| Policy script + standards | 40 | 9 |
| Mixed disjoint multi-commit net change | 42 | 11 |
| Evidence-only push | 4 | 4 |
| One-time migration push (self triggers preserved) | 40 | 40 |

Equivalent R084 pushes: 123 actual historical vs 30 predicted runs; 93 fewer runs (75.6%). A migration touching all 31 workflow files legitimately self-triggers once; it does not suppress existing expensive jobs. No claim about GitHub scheduling limits, diff timeout, >300-file truncated path selection, or future dependency additions.

Parser fail-closed initial first error: `ROUND085_TRIGGER_FIRST_ERROR unsupported-yaml-path:.github/workflows/phase-a-round073-lower-fua-ordering-noauth.yml`. This unchanged workflow legitimately has three plain literal paths. Corrected the regression parser to accept only safe plain literals (no wildcard/negation) in addition to the observed quoted positive grammar; final regression PASS, no final first error. Unsupported event, mixed globstar and negation mutants rejected. No Git checkout available in the local container (DNS failed resolving github.com); Node Git-tree CLI wrapper and full local git diff/policy execution NOT_RUN. The exact function itself ran on full immutable GitHub snapshots; migration copies are the tested literal edits. No remote compiler/native dispatch or local broad tests.

Reproduction in an existing rootless full repository checkout:
`node tests/runtime/native/round085-ci-trigger-contract-test.mjs <migration-source-SHA>`
This reads the exact baseline and candidate git trees, validates recorded baseline blobs and historical first-parent paths, replays the same regression function and compares the full result with the manifest.

## Publication and safety

**Exact migration commit:** [`a37d7c459ac0977836ddf5cfb40495a3ea13f375`](https://github.com/k1moradi/swapz/commit/a37d7c459ac0977836ddf5cfb40495a3ea13f375), verified single parent `9e3c770004418cbf622f5f3eb647ee79ef5fe735`. Post-publication GitHub compare confirms exactly 31 YAML files each 0 additions / 1 deletion, and the complete 82-file remote workflow directory blob census matches the tested candidates, including unedited project-goals and all R084 files. The other five files in that commit are the test, canonical standards, manifest and both reports. No product source changes.

**Actual migration CI registration:** first observation 39 runs during registration; later one-time evidence census 40/40 exact expected workflow paths, no missing or unexpected paths. At that capture 25 queued, 13 in progress, 2 completed SUCCESS (historical imported-volatile-map and physical-evidence-rootless); no terminal failure observed. [Mandatory project-goals run 45408067512](https://github.com/k1moradi/swapz/actions/runs/45408067512), [repository-policy job 138494058468](https://github.com/k1moradi/swapz/actions/runs/45408067512/job/138494058468) QUEUED. The JSON includes all 40 run IDs/statuses and observed mandatory job IDs. These are automatic self-triggered migration checks, not additional dispatched work. Full remote CI remains pending, first remote error not observed; 10 per equivalent future source push remains a verified prediction, not a fresh future push observation. Evidence-only follow-up is expected to trigger four unfiltered workflows. Do not qualify queued or failed runs or rerun earlier jobs. No branches, PRs, force pushes, recurring checks, physical/privileged/loaded/swapon/pressure operations.
SOURCE_MAPPED_AUTHENTICATED=0; PHASE_A=BLOCKED; DIRECT_COMPRESSED_HANDOFF=DISABLED; FORCED_RAW_BYPASS=DISABLED; IMPORT_ACTIVE=0. Linux MM/zswap owns compressed RAM and natural eviction only; swapz disk packing/GC only, no recompression of accepted original bytes. Ordinary RAW_4096 remains the full original uncompressed 4096-byte page.


## Agent1 terminal reconciliation
Exact migration 40/40 workflows SUCCESS; mandatory project-goals 7/7 including repository policy 138494058468 and exact-SHA 138502130021. Historical 41→10 remains prediction. Local full Git-tree regression NOT_RUN; no production C/H change. R085 scope complete.
