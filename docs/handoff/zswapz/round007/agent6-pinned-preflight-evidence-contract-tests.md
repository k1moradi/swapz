# Agent 6 — Round 007 DRAFT: executable pinned-Linux preflight evidence acceptance tests

**Task ID:** `agent6-pinned-preflight-evidence-contract-tests`
**Coordination mailbox:** https://github.com/k1moradi/swapz/issues/124
**Provisional baseline:** `79bb7c0c8bdf055eaeecf81c0fa291d167bd0e61`. The eventual `ROUND_OPEN` provides the authoritative frozen source and task SHA.
**START GATE: DO NOT BEGIN BEFORE ROUND 007 `ROUND_OPEN`.** Once opened, start at the same time as Agent 3; no same-round technical dependency.

## Owned actual implementation paths

- **New executable test:** `tests/runtime/native/pinned-linux-preflight-evidence-test.py` — actual Python source, not a fixture plan.
- **Existing hosted source-test entry point:** `.github/workflows/product-codec.yml` — add one scoped invocation of that actual Python executable in the existing exact-C/source-contract stage, alongside its existing source-contract tests, without altering any production-C or module-build behavior.
- **Same-commit governing standard:** append your distinct `Round 007 pinned Linux CI evidence contract negatives` section to `docs/testing_standards.md`.

Do **NOT** edit Agent 3's Linux preflight workflow or the pending Agent 7 C fixture. Do not rely on Agent 3's same-round changes or new manifest fields; all keys and semantic invariants must come from the **already committed** frozen preflight evidence schema. Both can work completely independently.

## Actual test-source engineering

1. Parse tiny, **offline** profile evidence text from the existing source-bound CI schema. Use an explicit bounded key/value grammar that fails closed on duplicate reserved keys, invalid UTF-8/noncanonical unsigned sizes, unexpected/wrong source SHA, conflicting/absent `requested_zswap`, nonmatching effective config and missing config/source hash. Preserve forward compatibility for truly optional unrelated keys while rejecting ambiguous claim-critical fields. Use only Python stdlib, no network or privileges.
2. Treat **`result=PASS` as a claim to validate, not a fact**: a linked external module PASS must additionally show a real positive module size, valid module SHA-256, nonempty export symbol-table hash, source identification, successful build command status and correct `module_linked=yes`. A `CONFIG_ZSWAP=n` profile may not assert a compiled enabled-only zswap object. Negative tests must deliberately forge each class and prove validator refusal, with first-failure-only diagnostics. Source-only LLVM object profiles must be labeled separately and must **never** count as linked `dm-swapz.ko` proof.
3. Keep successful rootless tests independent from actual GitHub artifacts, host Linux downloads or another worker's source commit. Use small deterministic in-code or local temporary fixtures, descriptive variable names and bounded input sizes. Test on the actual committed Python source (`python3 -B ... -v`, `python3 -m py_compile`, relevant existing source-contract CI), including valid old profiles, truncated profile, duplicate-conflict, wrong source, failed commands and false-clean-PASS cases. Do not conflate mocked manifest tests with genuine host kernel Kbuild.
4. Make `.github/workflows/product-codec.yml` execute the test on the exact checked-out repository source through its existing rootless source-contract stage; preserve all existing jobs, comments, GitHub permissions and test ordering, and update the governing test standard in your exact same code commit. No new heavy dependencies, no API refactors or unrelated C edits.
5. No imported source code from an unapproved separate Linux repo, no producer helper simulation billed as real authenticated writeback. Phase A remains BLOCKED, Phase B disabled.

## Publication and report

After the real `ROUND_OPEN` on issue #124, edit actual tracked test+CI files; build a real retrievable Git source commit parented to its *final frozen* source SHA, without moving any remote Git ref, branch, PR, fork or secondary worktree. Run existing tests available to the agent. Post one `message: REPORT_READY` to issue #124 with source commit SHA, file list, exact test invocations/exits, negative case count and evidence class. Agent 1 alone serializes main integration and honors same-commit standards. No issue-only patch or text proposal is accepted.
