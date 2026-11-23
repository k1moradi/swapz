# AGENTS.md — mandatory instructions for Codex and all coding agents

This file applies to the entire repository and every delegated or parallel
agent. Read it at task start, after context compaction, and after syncing
`main`. The user's **main-only / no-PR** decision is mandatory even when a
tool, agent template, or GitHub interface recommends a pull request.

## Non-negotiable Git workflow

**`main` is the only permitted local and remote development branch.**

- **Never create, publish, switch to, or perform work on another branch.**
  This includes temporary, feature, experiment, fix, release, backup, CI,
  `agent-*`, `codex/*`, and automatically generated branches.
- **Never open, create, submit, update, merge, or use a pull request** for
  current swapz work, including draft PRs. Do not open PRs just to run CI,
  request review, resolve conflicts, or publish a small documentation change.
- Do not create secondary worktrees or repository forks.
- Do not invoke GitHub `create_branch`, `create_pull_request`,
  `merge_pull_request`, or PR-update actions; do not run
  `git switch -c`, `git checkout -b`, `git branch <new-name>`,
  `git push origin HEAD:<non-main>`, or `gh pr create`.
- Existing remote branches and historical PRs are **read-only artifacts**,
  not an exception, assignment, or publication destination. `git fetch`
  may display them; ignore them and stay on `main`. Do not delete or
  rewrite them merely to satisfy this policy.

### Direct-main publication protocol

1. Verify the working branch is `main` and identify all local changes.
2. Fetch `origin/main` and verify the current canonical remote head.
3. Fast-forward local `main` before new changes when possible. Preserve
   ongoing uncommitted/unpublished work without creating another branch.
4. Make a focused, tested commit on local `main`.
5. Fetch/recheck the remote head immediately before pushing.
6. Push a **non-force fast-forward** directly to `origin/main`; use an
   expected-head check when the remote edit tool supports it.
7. Verify local `HEAD` and remote `main` match after publication.

If the remote advances, reconcile only **unpublished** local work onto the
new `main` and rerun affected checks. Never overwrite concurrent work or
rewrite published history. If direct-main publication is denied or a tool
only supports branch/PR workflows, **stop publication, preserve the work,
and report BLOCKED**. Do not silently switch workflows.

## Mandatory self-diagnosing `make test` workflow

Every failure that requires the owner to run an additional diagnostic command
or manually extract a traceback is also a test-harness reporting defect.
Fix that reporting gap **alongside the original bug**, and add rootless
regression coverage before calling the issue resolved. The official `make test`
console must automatically show the source-bound first failure, bounded
actionable details, and safe next step. Retain richer evidence automatically
in private mode-0600 files and print their repository-relative paths; do not
require the owner to discover or extract the data. Never print arbitrary child
stderr, credentials, absolute host paths, identities or raw device details.
Preserve fail-closed qualification, first-cause precedence and original exits.
Block dirty tracked source before expensive qualification, naming only safe
tracked repository-relative paths; leave all unpublished owner edits untouched.
See `docs/testing_standards.md` for the detailed reporting contract.

## Mandatory ordinary Linux swap partition design (2026-11-09)

Real backing must be an existing, valid SWAPSPACE2 Linux swap partition.
Never repartition, run mkswap on, or rewrite its header, UUID or partition
table. After a safe swapoff and exact-exclusive admission, only the data
area after the protected 4096-byte first page may be used. The newly
created virtual Device Mapper mapper alone may receive mkswap.
Switch between ordinary swap and swapz with verified swapoff/swapon,
without reboot. After a successful trial, obtain the owner's choice:
keep swapz active or return to ordinary Linux swap.

All swapz-specific record and extent descriptors, offsets, lengths,
generations, CRCs, mapping/segment allocation and GC metadata must
be bounded volatile RAM state. Production compressed extents now contain
payload bytes and deterministic zero padding only, with authoritative
descriptors in RAM. Legacy serialized-codec and synthetic SWAPZ001/null_blk
fixtures are never an accepted physical partition format or metadata source.
Preserve 4/8/16KiB packing, readback integrity, ordering, concurrency and
fail-closed semantics. Production acceptance remains blocked until current-
source loaded, lifecycle and real-device qualification passes.

Earlier permissions to format/repartition even the dedicated SD card
are superseded; only post-swapoff swap *data* may be overwritten.

## Project safety and current specification

Read and follow `docs/AGENT_CONTEXT.md`, `docs/VISION.md`, and
`docs/README.md`; consult relevant sections of coding/testing standards.
The first host's standing owner authorization remains limited to its
positively identified dedicated SD card. A separate owner-authorized Lubuntu
host may select only its independently identified `/dev/sda4` partition after
the exact root-owned host-scope record and all runtime identity gates described
in `docs/AGENT_CONTEXT.md` pass. This exception never authorizes the parent
disk or sibling partitions. No separate recovery device or physical-parent
separation is required: the backing SWAPSPACE2 header is immutable and
runtime ownership is same-boot RAM state. A scope record alone does not
qualify or enable production swap.
Never mutate unrelated storage or intentionally reboot, crash, or panic the
host. No VM or fallback swap is required. Keep the documentation working set
within the project's 64K-token budget.

The current documentation and this file override legacy branching/PR
examples in historical records. Any agent discovering a new branch or PR
created against this policy must report its name/URL and commit identity to
the project manager, without using it as a reason to create another.

## Mandatory GitHub-first, round-scoped engineering evidence (all agents)

For every numbered `zswapz` round, **GitHub is the owner-to-Agent1 reporting
channel and the repository is the evidence system of record**. This rule
applies to every agent, even if a chat client offers file downloads.

1. Publish bounded human-readable evidence as
   `docs/handoff/zswapz/roundNNN/agentN-evidence.md` and machine-readable
   qualification as `docs/handoff/zswapz/roundNNN/agentN-results.json`
   on the authorized sole `main` branch. Preserve the source/test commit,
   parent, pinned inputs, exact compiler/native test statuses, earliest true
   error, safety gates and original-versus-synthetic limitations. Never call
   a queued native test PASS or replace failed CI with local results.
2. After a workflow completes, commit the updated bounded evidence JSON and
   report in the SAME round folder using a fresh non-force direct-main
   fast-forward; evidence-only follow-up commits do not qualify failed source
   commits, must not change implementation/standards, and must not trigger
   duplicate expensive workflows. Link the tested code SHA distinctly from
   the later evidence-document SHA. Where logs are large, store a bounded
   first-error/KTAP/JSON excerpt and link to the exact GitHub Actions job and
   uploaded private CI artifact; do not commit raw multi-megabyte logs.
3. POST a `message: REPORT_READY`, `PROGRESS` or `BLOCKED` comment on the
   official numbered round GitHub issue with clickable commit-pinned GitHub
   URLs to BOTH the report and JSON, exact CI run and job IDs and first
   verified failure. Verify that all referenced paths exist remotely first.
   A chat attachment, local JSON/ZIP, sandbox download, hand-delivered file,
   or report posted only to the user is **NOT delivery to Agent1**. Never
   require the owner to upload or forward your evidence to GitHub.
4. If repository publication is blocked, report the exact GitHub permission
   or non-force main fast-forward failure to the issue as `BLOCKED`, keep
   unpublished work safe, and do not claim the evidence was delivered.

Follow `docs/handoff/zswapz/evidence-policy.md` and the exact current round's
frozen contract. This communication policy never authorizes a branch, PR,
force push, real-device/privileged operation, or production safety-gate change.
