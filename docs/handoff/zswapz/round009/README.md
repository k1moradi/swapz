# Round 009 — FINAL parallel engineering assignments (Agent 1 coordination)

**Frozen swapz engineering source:** `4063b88422dd62b1d4b1a990f0cfe9961e73277c`. **Coordination:** [GitHub issue #126](https://github.com/k1moradi/swapz/issues/126). **Authority:** only a unique `message: ROUND_OPEN` after this task package is verified on canonical `main`. **Exactly two workers excluding Agent 1: Agents 3 and 2.** Start simultaneously; neither worker needs another worker's new code, reports, commits or tests to begin.

## Outcome-driven, independent ownership

| Worker | Exclusive real code | Independently achievable result |
| --- | --- | --- |
| [Agent 3](agent3-pinned-gcc-build-info-fix.md) | Existing `.github/workflows/phase-a-linux-source-preflight.yml`; actual build-header producer (root `Makefile` or relevant header) only if verified, plus unique rootless regression test and `docs/coding_standards.md` appendix | Fix verified `MODULE_INFO` build-info macro failure and obtain real linked `dm-swapz.ko` plus artifact-verifier evidence for both `CONFIG_ZSWAP` profiles after coordinator CI |
| [Agent 2](agent2-real-linux-provenance-source-staging.md) | New `tests/tools/stage-pinned-linux-zswap-origin.py`, dedicated `tests/runtime/native/pinned-linux-zswap-origin-stage-test.py`, new `.github/workflows/phase-a-zswap-origin-prototype.yml`, uniquely titled `docs/testing_standards.md` appendix | Deterministically edit actual full pinned Linux MM/BIO source in an ephemeral disposable checkout and compile genuine modified kernel objects for `CONFIG_ZSWAP=y/n`; no new writable upstream repo required |

Round 008 [closed with documented source qualification failure](../round008/round-report.md): the two worker commits and reports were integrated; native and production C CI passed, independent LLVM stock-Linux source-object Kbuild passed; real pinned GCC external module build failed on unresolved `SWAPZ_BUILD_SOURCE_CLEAN_STRING` at `src/kernel/dm-target.c:71`. The new Agent 3 task owns that immediate build failure. Earlier Agent 2 provenance proposals were not production-qualified; Agent 2 now has a specific source-controlled route to produce and compile **actual changed pinned Linux C**, instead of being blocked by lack of a separate writable Linux repository.

## Invariants: worker independence, real source and publication

Both workers must read current `AGENTS.md`, `docs/AGENT_CONTEXT.md`, `docs/coding_standards.md` and `docs/testing_standards.md`, preserve existing comments and public names, add no heavy dependencies and follow fail-only bounded diagnostic rules. They edit **actual tracked source-controlled implementation files**, not produce a patch file, standalone diff, plan-only report, or synthetic source fragment as delivery. Each creates a real retrievable Git source commit whose **single parent is the frozen source SHA above**, with changed paths limited to its exclusive assignment; do not push remote `main`. Agent 1 alone reviews and serially integrates both sources with no force or branches/PRs/forks/secondary worktrees. The two assignments have zero shared edit paths, including their separate governing standards files.

Agent 2's new tool must apply **actual source edits** to upstream Linux's full checked-out C/H files with pinned source/hash gates, record changed output hashes and compile; no bundled `.patch` file, no mutation of Agent 3's existing workflow. Agent 3 may need to edit only the existing workflow's build-header generator; no production C change unless that proves necessary. None of these tasks loads a kernel, modifies a live mapper or Linux swap device, triggers reclaim, touches a physical device or enables origin-driven RAW bypass.

**Evidence labels:** local rootless tests are rootless; a real hosted source compile is Kbuild only; linked stock-pinned `dm-swapz.ko` is not an authenticated kernel MM producer; a source-staged new producer is not a qualified booted running-kernel ABI. Agents must report exactly what was and wasn't run. Agent 1 integrates source, inspects exact-source CI, archives verbatim worker reports and closes with truthful PASS/FAIL/BLOCKED classifications. `Phase A=BLOCKED` until matched authenticated running producer/consumer and real zswap eviction/readback; `Phase B=DISABLED`.

## Required reporting and kickoff

Start only after the authoritative `ROUND_OPEN` comment on issue #126 (task SHA fixed). Submit one new `message: REPORT_READY` to #126 with `round: "009"`, `agent`, `task_id`, frozen source SHA, actual retrievable new commit SHA, exact modified paths, tests/commands/exits, first failure, supporting CI links where applicable, negative checks, and `NOT_RUN` limits. Do not claim that worker rootless runs are hosted qualification; do not await the peer.
