# Mandatory round-scoped GitHub evidence delivery — all swapz agents

**Authoritative communications:** Commit source/tests and durable bounded evidence directly to `main`, then send Agent1 a comment on the current numbered zswapz issue. Never ask the owner to relay a downloaded JSON, ZIP, chat attachment or transcript to GitHub.

## Required round files

For every agent N and round RRR, create or update the following two *real committed repository files*, with exact remote SHA links in the issue comment:

- `docs/handoff/zswapz/roundRRR/agentN-evidence.md` — objective, exact source/test commit SHA and its parent, owned files, original versus modeled boundary, real compiler tests, mutation counts, actual original Linux KUnit/KTAP outcomes, first source/line error, safety gates, no ownership conflict, next action.
- `docs/handoff/zswapz/roundRRR/agentN-results.json` — concise machine-readable status, e.g. `{"round":"072","agent":6,"kind":"original-source-test-only","tested_commit":"<real SHA>","workflow_url":"<real GitHub URL>","jobs":[],"conclusion":"IN_PROGRESS","first_error":null,"source_mapped_authenticated":false,"phase_a":"BLOCKED","actual_physical_io":false}`. Use valid JSON, no placeholder test counts or false `PASS`. For pending jobs, report `QUEUED` or `IN_PROGRESS` and later publish the terminal result.

Large kernel logs remain GitHub Actions artifacts; the committed report must still carry a bounded **first actual error** and exact linked job plus native JSON/KTAP count. A local preliminary host-model JSON may be included as *additional* `agentN-preparatory-*.json`, clearly labeled model-only, not a substitute for the required terminal CI summary.

## Publication and notification order

1. Source/tests and same-commit applicable testing-standard change are committed on the only `main`, single parent, fresh expected-head non-force fast forward.
2. Run or inspect focused exact-source GitHub CI; never duplicate a completed identical run. If queued, mark pending and continue independent tasks.
3. After CI is terminal, update round evidence and JSON on `main` with a **separate evidence-only direct-main commit**; do not amend published source or disguise a failed source commit. If workflow is red, JSON must remain `failure` and include the first real cause.
4. Verify GitHub exact-SHA file links, then comment on **the official round issue** with `message: REPORT_READY` (only when genuinely qualified), `message: PROGRESS` or `message: BLOCKED`, and the source and evidence SHAs, links, CI IDs and limitations. A user-facing file download is optional extra, never the canonical delivery.

No additional branches/PRs/worktrees. No privileged, physical, loaded kernel, swap activation/pressure experiments without fresh explicit authorization. Source AUTH0, Phase A BLOCKED, conventional RAW_4096 is full ORIGINAL UNCOMPRESSED 4096. True zswap natural MM eviction alone owns compressed RAM; swapz disk-only packing and GC, no extra shrinker/recompression.
