# Round 002 correction — actual code edits, not patch-file submissions

**Authority:** Direct owner instruction dated 2026-11-15: *Agents should patch the code, not generate patches*. This additive correction supersedes any conflicting wording in Round 002's frozen Agent 2 and Agent 3 task prompts or previous issue dispatch comments. The frozen task commit and original text remain as historical evidence; they are **not** silently rewritten.

**Round 002 remains open** at [issue #119](https://github.com/k1moradi/swapz/issues/119). Source baseline `f11e8795f44f15fecc6b2b200c0b1a9e4eaeb364`; immutable task commit `b949018a8f0461a5886eeaf0da4a1130c62dcf23`. Original feature/safety/ABI requirements are unchanged. Phase A is still unqualified and Phase B remains disabled.

## Agent 3: write actual swapz code; designated single publisher

1. Synchronize a **clean local `main`** with the canonical remote head, read `AGENTS.md`, `docs/AGENT_CONTEXT.md`, and applicable `docs/coding_standards.md` sections. Confirm the source blob at `src/kernel/dm-target.c` has not changed from the frozen input; if it has, review and reconcile without overwriting concurrent work.
2. **Edit `src/kernel/dm-target.c` directly** to implement the requested passive 4 KiB zswap-origin admission and correctly attributable observability. Add narrow production-linked tests in `tests/` when necessary. Update only the relevant governing standard in the same commit, as required by the coding standards. Keep existing comments, completion/authority paths and stock-kernel behavior; no Phase B RAW bypass.
3. **Do not stop after generating a `.patch` file or posting a diff.** A diff is a review tool, not the outcome. Run `git diff --check`, matching `W=1/W=2` kernel builds if available, applicable rootless tests, and source-bound negative controls. Record all `NOT_RUN` accurately; do not qualify loaded runtime BIO ABI from stock headers.
4. **Agent 3 owns the exclusive `swapz/main` publication lease for its Round 002 source implementation**, starting after this correction commit and coordinator dispatch. Agent 1 performs no further `main` writes during that lease. Commit the actual edited production/test/governing-standard files on local `main`, re-fetch `origin/main`, non-force fast-forward push only if source is current, then verify local/remote HEADs match. If this environment/tool lacks direct-main write capability or source/build prerequisites, stop and report `BLOCKED` with exact evidence; do **not** offer a patch-text-only PASS.
5. Report in [issue #119](https://github.com/k1moradi/swapz/issues/119) with `message: REPORT_READY`, exact published **source commit URL and SHA**, changed file list, tests/exits, first failure/NOT_RUN limits, and `MAIN_WRITE_LEASE_RELEASED`. Release the lease even when blocked; never wait for Agent 2.

## Agent 2: write actual Linux kernel code in a pinned checkout

1. On an existing checkout of **`torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`**, edit the actual Linux `mm/`, `block/` and `include/linux/` files in place to implement the previously agreed producer/propagation semantics. Test the modified source; do not merely prepare or publish a standalone unified diff.
2. The upstream Linux tree is a **separate repository**, so this swapz GitHub issue cannot make upstream C edits land there. Do not push to `torvalds/linux` or create a fork/branch/PR without an authorized writable destination. Record modified source state, exact kernel commit and local tests. If there is no durable authorized upstream source publication route, report `BLOCKED_PUBLISH` even if a local build passes; do not mislabel an issue-comment code snippet as integrated source.
3. Agent 2 does **not** write `swapz/main` during Agent 3's lease. Never depend on Agent 3's Round 002 output. Report progress and the actual edited-source location/provenance through GitHub issue #119.

## Acceptance and code style

- **Code changes first:** production kernel C over speculative test scaffolding; avoid refactors/renames, churn, heavyweight deps, hot-path allocation and unnecessary locks; preserve comments and existing API/data layout where possible.
- **Concurrency/ownership:** describe BIO clone/split/requeue/reset propagation, descriptor lifetime, race/failure handling and immutable origin. Use existing thread-safety patterns, no new unsafe shared state or forged provenance.
- **Testing:** run applicable source-linked and negative-path tests, high-warning builds, and `git diff --check`. Rootless-only results are rootless, never Phase A qualification.
- **Success gate:** Agent 3 must provide an actual published `swapz/main` code commit for an implementation PASS; Agent 2 must provide an actual modified upstream source tree and a legitimate persisted code revision for publication PASS. GitHub issue comments are the **reporting channel**, not the source-delivery mechanism.

**Coordinator handback:** Agent 1 may publish archived Round 002 reports and begin Round 003 planning **only after** Agent 3 releases the exclusive write lease, and only after code change/verification state is independently inspected.
