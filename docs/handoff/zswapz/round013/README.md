# Round 013 — FINAL frozen parallel main-only engineering tasks

**Execution authority:** unique `message: ROUND_OPEN` in [issue #130](https://github.com/k1moradi/swapz/issues/130) **after** this exact final task commit is published and verified. Draft issue text alone is not authority.
**Frozen engineering source on canonical `main`:** `2be15cb171a6a4e15453520512df8ebf779e6f3d` — each worker's *real retrievable code commit* MUST have this as its single parent.
**Exactly TWO workers excluding Agent 1:** **Agent 6 and Agent 7**. Begin simultaneously on the same frozen main source; **zero same-round peer dependencies**. Only Agent 1 advances the shared remote `main` serially with non-force expected-head checks; no worker branches, PRs, forks, secondary worktrees or force pushes.

## Disjoint actual implementation

| Agent | Exclusive real tracked files | Concrete independently executable work |
| --- | --- | --- |
| [Agent 6 — verified producer→consumer ABI source test](agent6-source-bound-producer-consumer-abi-regression.md) | Existing `tests/runtime/native/zswap-origin-producer-consumer-abi-test.py`; existing `.github/workflows/product-codec.yml` only for its owned invocation; distinct append-only `docs/coding_standards.md` | Fix **observed x86_64+ARM64 production C CI first failure** on an intentionally retained original Linux anchor in `include/linux/swap_ops.h`; strengthen actual stage postimage checks and strict source mutation negatives, not kernel origin semantics |
| [Agent 7 — RAM source lease + physical non-admission rootless tests](agent7-ram-source-lease-and-physical-nonadmission.md) | Existing `tests/tools/run-tests.py`; **new** `tests/runtime/native/algorithm-ram-source-lease-test.py`; existing `.github/workflows/physical-evidence-rootless.yml`; distinct append-only `docs/testing_standards.md` | Reproduce the owner's source advancement **after five RAM stages PASS**, check physical selector was not invoked and canonical evidence remains not qualified, and make first-refusal diagnostics deterministic, source-bound and privacy-safe without touching devices |

**No file ownership overlap.** Agent 6 uses frozen pre-round actual pinned Linux staging implementation and production `src/kernel/dm-target.c` strictly as source/test inputs; Agent 7's RAM/physical gate needs no KUnit, origin ABI or Agent 6 test result. Both run available rootless tests without waiting for GitHub Actions or each other.

## Exact evidence and qualification ceiling

- [Round 012 accountable closeout](../round012/round-report.md) integrated both genuine source commits; [later hosted failures](../round012/late-ci-results.md) record rootless KUnit test contract, early/late paired module verifier mismatch and production-C source test `include/linux/swap_ops.h` false rejection. Agent 1's test-only fixes ended at [`46290980`](https://github.com/k1moradi/swapz/commit/462909804c85ac1899f743bfa595f1349cef94e2); their final exact-source checks were pending. Do **not** claim matched `dm-swapz.ko`, actual KUnit y/n or loaded writeback PASS without fresh source-exact successful runs.
- The owner's local `make test` observed all five RAM stages PASS at tested source `387dc8a05fae570c8b6119a2688077ad375efc20`, but source advanced before physical admission: `PHYSICAL_ALGORITHM_REAL_SWAP=BLOCKED reason=source_advanced_after_ram phase=before_physical_selector`, `Physical ... NOT RUN`, `Overall qualification: INCOMPLETE`. The report-only archival/restoration commits are **not source qualification** and must not promote old evidence to a newly built kernel or physical trial.
- Repository branch inventory is **only remote `main`, no open PRs**. Do not recreate any remote ref or PR.

## Implementation and handoff rules

Read `AGENTS.md`, `docs/AGENT_CONTEXT.md`, `docs/coding_standards.md` and `docs/testing_standards.md`. Use actual tracked Python/YAML sources, strictly source-coupled negative controls, full real available rootless tests with exit statuses, no model-only or prose-only deliverable. Preserve all prior comments, kernel ABI/source SHA, admission logic, 4096-byte geometry, four foreground success hooks, compression, GC and Phase B disabled semantics. Changes must be minimal, DRY, allocation-conscious and fail-closed. No privileged operations, module loading, swap, mapper, reclaim or physical device activity.

Each worker commits only its owned source to a retrievable Git object with **sole frozen parent `2be15cb171a6a4e15453520512df8ebf779e6f3d`** (it need not be on a new branch and must never advance shared remote main), then posts exactly one post-ROUND_OPEN `message: REPORT_READY` on [issue #130](https://github.com/k1moradi/swapz/issues/130) naming `round: "013"`, agent, task, source commit, changed paths, measured commands/exits/mutations, first failure, and full-rootless/CI/loaded/hardware NOT_RUN limits. Agent 1 reviews and integrates serially, archives original report bodies verbatim with SHA-256, verifies exact-source CI and closes accurately.

**Phase A BLOCKED** absent actual matched loaded zswap producer-to-DM authenticated stored-entry writeback and byte-exact readback; **Phase B RAW bypass DISABLED**.
