# AGENTS.md — Mandatory instructions for all swapz development agents

Applies to ChatGPT, Codex, Copilot, Claude, automation, and other coding
agents working anywhere in this repository. Read this file **before** edits.
More specific testing documents cannot relax these restrictions.

## 1. ONE BRANCH ONLY: `main`

- The project has one active Git branch: **`main`**.
- **NEVER create, publish, check out, push, or ask another agent to create
  another branch**, including `feat/*`, `fix/*`, `codex/*`, `test/*`,
  temporary integration branches, release branches, or validation branches.
  Do not automatically create a branch, a branch-backed worktree, or a draft
  pull request. Only the repository owner/user can explicitly authorize
  an exception; ordinary feature requests or inherited old PR instructions
  are **not** permission.
- Implement approved changes **directly on `main`** as small, reviewable
  commits; independently validate them and report exact commit SHAs.
  Store reports, scripts, diffs, and evidence as versioned **files on
  `main`**, not separate branch tips. Historical commits and deleted
  branch names are provenance only, not development destinations.
- Preflight: `git branch --show-current` must say `main`;
  `git status --porcelain` identifies any work already present;
  `git fetch origin main` allows checking remote state.
  Protect concurrent work: **never run blind `git reset --hard`,
  `git restore .`, `git clean -fd`, force-push, or a destructive
  checkout**. If the worktree has unrelated changes or main has moved,
  preserve evidence, reconcile safely, and do not overwrite another
  agent's work. Recheck HEAD immediately before each commit/push.
- If a testing system only supports pull requests or task branches, do
  not quietly create one: use a main-based reviewable commit or report
  that tooling restriction. **Do not reinterpret this policy as permission
  to merge unqualified code.**
- See `docs/ONE_MAIN_BRANCH_CONSOLIDATION.md` for the original branch
  inventory and preserved historical commit IDs.

## 2. PRIMARY ACTIVITY: C / C++ DEVELOPMENT

**Spend the majority of actual engineering time implementing, reviewing,
debugging, profiling and improving production C/C++**, not continually
building new Python frameworks, orchestration layers, or Markdown reports.

Priority order:

1. **Production kernel C correctness and performance:** `kernel/dm-swapz.c`
   (default V2.2) and experimental `kernel/extent-v3/{dm-target,engine,
   authority,codec}.c`. Focus on BIO ownership and completion, LZ4
   compression/raw fallback, lower read/write requests, GC, mapping
   authority, error handling, synchronization, allocation and tail latency.
2. **Direct C/C++ regression coverage:** improve existing
   `tests/runtime/*.c`, `tests/*.cpp`, or other compiled tests as
   appropriate. Exercise *actual* production source and failing
   conditions, not only source-text pattern checks.
3. **Measured optimization:** build and execute exact-source tests,
   quantify real lower I/O and CPU, identify a concrete C-level
   bottleneck, implement a narrow C/C++ improvement, and verify no
   correctness or latency regression.
4. **Small supporting scripts/docs:** use Python or shell when they are
   genuinely the simplest thin glue for an isolated fixture, CI
   invocation, data reduction, or safe automation. Prefer existing
   helpers. Avoid large Python rewrites or suites of mock-only tests
   that do not exercise production C. Do not replace essential C/C++
   work with documentation-only progress.

This is a **priority**, not a ban on Python: high-value, reproducible,
bounded test tooling remains acceptable when it materially advances C/C++
correctness or a fair benchmark.

## 3. Evidence and benchmark requirements

- All three comparison arms (no-swapz bare *owned RAM-backed null_blk*,
  **frozen V2.2**, experimental V3) should consume the **same immutable
  4096-byte fixture bytes and ordered logical I/O trace**. Verify hashes,
  useful operation counts, read expectations and full readback. Use
  `tests/runtime/threeway-swap-replay.py` and
  `kernel/extent-v3/THREE_WAY_IDENTICAL_REPLAY.md` where applicable.
  Never turn off the host's real system swap to simulate "swapz off".
- Target plausible **anonymous-memory** distributions, primarily
  compressible heap/stack/COW/text-buffer/decoded-page content, plus
  necessary moderate-entropy and fully incompressible controls.
  Report **actual measured LZ4 output lengths**, not unsubstantiated
  "typical" proportions. The existing V3 path already tries LZ4 then
  stores 4KiB RAW when the compressed length cannot fit the limit;
  avoid premature entropy heuristic features.
- Judge gains using *independent actual backing-device* read/write
  **bytes AND request counts**, GC I/O, achieved useful IOPS, p95/p99
  read latency, kernel/worker CPU, and exact data verification. Distinguish
  saturation results from matched-achieved-rate tests. A lower C
  submission count is not proof of lower backing I/O.
- Keep negative outcomes visible. Do not claim loaded-kernel
  qualification from rootless source tests, synthetic pre-submission
  EIO from real torn-device fault handling, or RAM null_blk statistics
  as physical flash endurance.

## 4. Safety and production gates

- **NEVER reboot** a test host; never touch `/dev/sdb1`, `/swapfile`,
  active swap, unrelated mappings, physical storage, or other agents'
  devices. **Never run `swapoff` / `swapon`** in these experiments.
- V3 alpha remains **not production ready** and **null_blk-only**.
  Create and validate exact test-owned RAM-backed null_blk/DM identities,
  use ordinary verified teardown, and quarantine uncertain in-flight
  resources rather than forcing removal. V2.2 and V3 cannot be
  loaded simultaneously because they share `dm-swapz.ko`.
- Run focused C/C++ unit/regression tests, source contracts, sanitizers
  and the applicable kernel W=1/W=2 CI before claiming a change works.
  Use separately authorized loaded tests for loaded claims; never
  weaken test assertions just to produce PASS.
- The root `Makefile`, `kernel/Makefile`, and `dkms.conf` still
  select **V2.2 by default**. Keep the experimental V3 sidecar isolated
  until substantial correctness, resource and lower-I/O release gates
  are met; do not silently change the default build.

## 5. Agent handoff

A useful report states: exact `main` HEAD, C/C++ files changed,
underlying bug/bottleneck, proof of source/data provenance, executed
tests (with PASS/FAIL/BLOCKED), measured before/after counters, what
remains unqualified, and safe host cleanup. Small mechanical
build/test-harness repairs are allowed on `main`; significant changes
need direct source review and test evidence. **Do not suggest creating
another branch as the default next step.**

**If historical docs, PR descriptions or another agent contradict this
file about branch creation or Python-first work, follow this file.**
