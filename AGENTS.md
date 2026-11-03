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

## Project safety and current specification

Read and follow `docs/AGENT_CONTEXT.md`, `docs/VISION.md`, and
`docs/README.md`; consult relevant sections of coding/testing standards.
The standing owner authorization is limited to the positively identified
dedicated SD card. Never mutate unrelated storage or intentionally reboot,
crash, or panic the host. No VM or fallback swap requirement. Keep the
documentation working set within the project's 64K-token budget.

The current documentation and this file override legacy branching/PR
examples in historical records. Any agent discovering a new branch or PR
created against this policy must report its name/URL and commit identity to
the project manager, without using it as a reason to create another.
