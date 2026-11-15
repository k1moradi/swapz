# Agent 5 — Round 004: compiled passive-provenance parser adversarial tests

**Task ID:** `agent5-native-provenance-parser-adversarial-tests`
**Round issue:** https://github.com/k1moradi/swapz/issues/121
**Frozen `swapz/main` baseline:** `f9f65369c2dba65797989e10374e2350d58d25c2`
**Execution:** Begin only after the unique Round 004 `ROUND_OPEN`; run **immediately and in parallel** with Agent 8. No same-round dependencies.

## Own and edit real C test source

- **Exclusive implementation path:** `tests/runtime/native/userspace/swapzctl-status.c`. This existing compiled C fixture directly includes the real `src/userspace/swapzctl.c`; it is NOT a synthetic replacement parser. New self-contained helpers in the same C file are allowed. Do not modify `src/userspace/swapzctl.c` or product kernel C without a separately demonstrated defect/escalation.
- **Applicable governing standard:** append a narrowly titled `Round 004 native provenance parser adversarial tests` section to `docs/testing_standards.md` in the *same source commit*. Agent 8 separately appends a different `Round 004 pinned Linux Kbuild` section, so do not edit/rewrite any other standards text or wait for Agent 8.

## Engineering work and unblocked acceptance

1. Strengthen the existing actual-production-C parser fixture beyond the 19 Round 003 one-off cases using **bounded, deterministic adversarial inputs** and property checks. Preserve existing fixtures and comments. Favor cached byte lengths and fixed arrays/stack storage, no new heap allocations in hot loops; run bounded case counts so CI is fast and reproducible.
2. Generate controlled inputs with combinations of a wholly absent legacy origin group, all three exact canonical keys, duplicate/partial keys, signed/empty/leading-zero/overflowing decimal, non-ASCII bytes, nonseparator token boundaries, invalid `origin_carrier_compiled`, and contradictory admitted/committed/page counts. Use a fixed documented seed and bounded lengths to prevent test-only buffer overflow.
3. Assert the existing production parser **fails closed** on malformed input and returns bounded retry (rather than quietly accepting) when valid per-field counters race across observations. Verify stable-snapshot equality covers the three counters and carrier validity, and that observable zero is never confused with missing/unsupported provenance. Do not weaken the existing compression-ratio, ownership, ERROR/failed precedence or JSON v1 contracts.
4. Build and **execute the actual compiled fixture** via `make -C tests/suites SANITIZE=1 test-userspace`, plus available GCC/Clang high-warning or sanitizer variants. Run `git diff --check` and any relevant existing rootless/native test. Report first failure, actual commands/exits and compiler identities. If your agent environment lacks the complete checkout or toolchain, still commit actual test source via GitHub Git Data and report `BLOCKED_CI_PENDING_COORDINATOR`, not excerpt-only PASS; Agent 1 will run full-source hosted tests after integration.
5. No new public CLI flag, JSON v1 key, production data-path control, platform dependency, kernel API, mapper, swap or physical device operations. Source-bound native fuzz tests are not proof of matched Linux MM→BIO provenance or genuine stored-entry writeback.

## Publication, independence and report

Read project standards before editing. Create a real, retrievable Git tree/commit object with parent `f9f65369c2dba65797989e10374e2350d58d25c2` containing only your C fixture and its own additive `docs/testing_standards.md` section. **Do not push remote `swapz/main`**; Agent 1 serializes both independent source commits and preserves documentation from both workers. No branches/PRs/forks/second worktrees; no text-only patch substitutes. Never wait for Agent 8.

Post one `message: REPORT_READY` at https://github.com/k1moradi/swapz/issues/121, identifying `round: "004"`, `agent: 5`, exact `task_id`, source commit SHA/URL, changed paths, source identity, number of real executed bounded cases and tests/exits, evidence class, first failure and NOT_RUN limitations. No Phase A or Phase B qualification claim.
