# Agent 2 — Round 016 real pinned Linux BIO provenance UML/KUnit failure correction

Official issue: https://github.com/k1moradi/swapz/issues/133
Frozen source parent: f716a5162a098742ec4bf7ab17b6a6a977bb75d4. Start in parallel with Agent 3 only after official ROUND_OPEN. Work has zero dependency on Agent 3.

## Exclusive code ownership
- .github/workflows/phase-a-zswap-origin-kunit.yml
- tests/runtime/native/pinned-linux-kunit-uml-config-test.py
- tests/runtime/native/pinned-linux-zswap-origin-stage-test.py, only if actual failing TAP/check semantics require a narrow fix
- tests/tools/stage-pinned-linux-zswap-origin.py, only if a reproduced source-staging defect requires a narrow fix
- Unique append-only Round 016 Agent 2 section of docs/testing_standards.md

Do not modify Agent 3's DM target, matched-module workflow, codecs or producer/consumer readback source.

## Implement — not just diagnose
1. Reproduce the source-bound actual failure from prior hosted modified-Linux KUnit run https://github.com/k1moradi/swapz/actions/runs/43826908357: enabled UML finished its command, but verify_uml_config failed with 'malformed-or-duplicate-manifest'. Obtain the actual artifact or reconstruct the exact manifest producer using the committed workflow and a checked-in executable fixture; identify the first *actual* offending field/transition. Do not presume a Kconfig mismatch when the parser rejected manifest grammar first.
2. Make the smallest source correction in workflow or parser that eliminates the real producer/verifier inconsistency while retaining strict duplicate detection for ordinary evidence, wrong status transitions, malformed lines, changed hashes, symlinks, and missing profile fields. Prefer unique evidence keys and deterministic single-writer manifest semantics over weakening parse_manifest.
3. Preserve two independent modified pinned Linux c339f4010dea8b0d754f84ace70cd1b089878ef8 KUnit UML builds (CONFIG_ZSWAP=y/n), exact source hashes, effective requested config equality, and all five distinct executed no-skip PASS TAP cases per profile. A KUnit CLI exit 0 alone is never a five-case PASS.
4. Add source-linked repeatable positive and negative tests for the discovered bug, including deliberately duplicated keys and forged results. Test exact source with Python unittests, workflow Bash syntax, workflow structure, and git diff --check. Hosted Kbuild/KUnit must be reported separately; NOT_RUN if no actual run from the resulting SHA.
5. Never create a new BIO compressed-representation carrier, turn provenance into routing, or permit false initial-rejection/unknown classification. Keep Phase B and direct compressed handoff disabled.

## Completion evidence
A real committed code change in the owned paths plus a meaningful separate testing-standards addition. Show the precise corrected first failure, real generated manifest comparisons, y/n Kconfig evidence, command exit codes, five distinct authentic TAP cases only if witnessed in hosted modified Linux, and one retrievable sole-parent Git source commit. If a known upstream failure survives, report FAILURE/BLOCKED with its exact phase; never remove mandatory checks to pass CI.
No branch/PR/fork/worktree. Do not write remote main; post one new REPORT_READY with round 016 and agent 2 on issue #133.
