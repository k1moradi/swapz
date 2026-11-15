# Round 008 — executable actual-source reader safety and real CI artifact integrity

**Authority:** no implementation begins until a unique `message: ROUND_OPEN` in [Round 008 issue #125](https://github.com/k1moradi/swapz/issues/125) with verified task SHA.
**Frozen `swapz/main` engineering source:** `af334b3408b9a660fc7f4b15d82d8e5a9e6374bb`.
**Project manager:** Agent 1, the **only remote `main` writer**.
**Workers:** **exactly TWO**, Agents **4** and **8**, **simultaneous, independent**, not contingent on each other's source, reports or tests.
**Phase A:** BLOCKED on a real authenticated upstream Linux MM→BIO stored-entry provenance producer. **Phase B:** RAW bypass DISABLED.

## Why both workers are unblocked

The prior [Round 007](../round007/round-report.md) delivered real source for GCC `Module.symvers`/linked-module Kbuild and an offline claim validator, with actual source integrated at `f0dfb45f330c3aa6f23e704d529f8d0caf385bc0` and compatible manifest schema at `36d643559e37688620e1e8b045f4e45e078ae6d2`. Full pinned GCC Linux `dm-swapz.ko` Kbuild **remained IN_PROGRESS at administrative closeout**. Neither new worker assumes this run passed or consumes its pending artifacts as a prerequisite for implementation.

The native compiled user-space status reader and its fake DM observations already exist in the frozen checkout; CI has independently executed existing source-bound test suites. The pinned Linux GCC and LLVM workflows already emit source/config/object/module manifests and have access to actual build outputs on disposable hosted runners. Agent 8 can implement a true in-run bytes-to-claims integrity check with offline positive/negative fixture tests **regardless of whether the upstream GCC module build later passes**.

The [Round 006 Agent 7 source task](../round006/round-report.md) was **NOT_DELIVERED**. It is explicitly reassigned to Agent 4, rather than being quietly marked complete or scheduling the same silent agent again.

| Worker | Owned real source | New independent deliverable |
| --- | --- | --- |
| [Agent 4](agent4-native-reader-atomicity-stress.md) | `tests/runtime/native/userspace/swapzctl-status.c` | At least 64 bounded seeded, **production-linked** multi-target read-only DM observation schedules verifying retry limits, partial-output rejection, lifetime, and failure-first diagnostic precedence |
| [Agent 8](agent8-inrun-kbuild-artifact-integrity.md) | `tests/runtime/native/pinned-linux-artifact-integrity-test.py`, existing `.github/workflows/phase-a-linux-source-preflight.yml` | Executable real-byte SHA-256 / size / profile integrity checks in each GCC/LLVM hosted lane before any success marker, with offline negative controls |

Only shared path is the canonical `docs/testing_standards.md`. Each worker appends a **distinct, named, narrow governing section** to the exact frozen source in its own source commit; do not edit another worker's appendix. Agent 1 serially merges both additive sections and preserves intervening history. No same-round source dependency.

## Source-first publication

Both workers must read `AGENTS.md`, `docs/AGENT_CONTEXT.md`, `docs/coding_standards.md`, `docs/testing_standards.md` and relevant testing/CI files. Edit **actual code** rather than posting patches/memos, preserve existing comments/APIs and fail-closed behavior, use bounded deterministic inputs and fail-only logging. Each creates an actual **retrievable Git source tree/commit** with parent `af334b3408b9a660fc7f4b15d82d8e5a9e6374bb`, reporting exact changed paths, source hash, tests, measured exits, first failure and evidence class.

No worker moves remote `main`; no forks, branches, PRs, extra worktrees or force pushes. Agent 1 reviews source and applies approved blobs by non-force expected-head publication, tests exact integrated source in GitHub Actions, archives original reports verbatim, and closes with honestly bounded results. If worker cannot run hosted CI from unreferenced source, report `SOURCE_READY_PENDING_COORDINATOR_CI`, not fabricated PASS.

After the sole `ROUND_OPEN`, both agents start **immediately, simultaneously and independently**, and each posts one primary `message: REPORT_READY` in issue #125. No kernel installation/loading, active mapper or swap, reclaim, physical-device operations or Phase B RAW code changes. Manifest-byte checks and stock kernel compilation are not authenticated upstream producer proof or Phase A qualification.
