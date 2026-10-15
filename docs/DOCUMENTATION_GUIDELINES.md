# Documentation governance

**Status: ACTIVE. Applies to every contributor and AI agent.**

## Single source of truth

1. Keep `README.md` as the GitHub-facing entry point and
   `AGENTS.md`, `CLAUDE.md`, `agent.md`, `CODEX_VALIDATION.md`
   in the root (Copilot's supported entry point stays at
   `.github/copilot-instructions.md`). These are **short pointers**,
   never competing engineering standards.
2. The six authoritative documents are root `README.md` and `VISION.md`,
   plus `docs/coding_standards.md`, `docs/testing_standards.md`,
   `docs/compile.md`, `docs/benchmark.md`. Root agent entry points link
   to these canonical locations; update all references and CI checks
   together if a canonical document moves. Do not create other
   root-level Markdown files.
3. Use [docs/TODO.md](TODO.md) for *active unchecked V3 work*,
   [docs/ROADMAP.md](ROADMAP.md) for milestones and algorithm
   direction, [docs/PRODUCTION_READINESS.md](PRODUCTION_READINESS.md)
   for accumulated release evidence, and
   [docs/DEVICE_GEOMETRY.md](DEVICE_GEOMETRY.md) for geometry.
   [README](INDEX.md) is the documentation navigation index.
4. Place detailed, reusable specifications under `docs/`; place
   dated, exact-revision reports under an appropriate
   `docs/validation/`, `docs/benchmarks/` or
   `docs/archive/<version>/`. Retired V2.2 safety and offline-reporting evidence
   lives under `docs/archive/v2.2/audits/`, **not** as additional standards.
   Keep a component's short README or uniquely applicable protocol
   with its code (for example `kernel/extent-v3/README.md` and
   `tests/runtime/README.md`).
5. Historical Codex task instructions are stored only in
   `docs/archive/v2.2/CODEX_VALIDATION.md`; the root
   `CODEX_VALIDATION.md` must remain a current, safe agent pointer.

## Maintenance and consolidation

- **Before creating a document**, identify its owner and check the
  index and existing reports. Extend an existing page when the
  subject is the same; do not duplicate build, testing, safety or
  benchmark rules. Agent prompts link to governing standards.
- **Keep the TODO short and actionable:** current version only;
  one owner per task, clear verification requirement and status.
  Move completed run transcripts to dated evidence; do not append
  chronological logs to TODO or use archived unchecked boxes as
  current work.
- **Dated evidence must say what was actually run:** status
  (PASS/FAIL/BLOCKED/NOT RUN/INCONCLUSIVE), exact source revision,
  device and isolation scope, test limits, and links to raw evidence
  when available. An analytical or rootless result must never be
  relabeled as loaded kernel, physical device, or production proof.
- **Promote lessons, not entire transcripts:** after code/build/test/CI
  changes, update a *relevant* one of the four standards
  (`docs/coding_standards.md`, `docs/testing_standards.md`,
  `docs/compile.md`, `docs/benchmark.md`) in the same commit,
  as enforced by CI.
  Update README for user-visible changes and VISION only for the
  success criterion.
- **Archive rather than silently erase evidence.** Mark a page
  historical when V3 supersedes V2.x instructions; retain traceable
  exact-revision results, failures and safety incidents. Delete only
  genuinely duplicated or empty documents once unique facts,
  inbound links and test/CI references are handled. Git history
  remains recovery, not an excuse to discard unique proof.
- Use relative Markdown links; when moving a document, update its
  inbound and outbound links in the same change. Recheck agent
  entry points, code/test readmes and workflow contracts. Never turn
  an old privileged example into a new permission to run it.
- **README completeness:** every tracked Markdown file, including
  root agent instructions, component-local documentation, archival
  evidence, and `docs/INDEX.md`, must have a **direct relative
  Markdown link** in the root `README.md`. The complete directory is
  grouped by status/topic; `docs/INDEX.md` remains a curated index.
  The `project-goals` workflow rejects missing README links when
  documents are added, moved, or removed.
- Review documentation as part of the existing `main`-only
  commit workflow: prefer small focused commits, report any
  blocked test honestly, and do not claim a run from a source edit.

## Review checklist

A documentation change is complete when it has one authoritative
owner, lives in the prescribed location, has a working index/entry
link, does not contradict the six mandatory documents, preserves
dated negative evidence, and does not break CI path assumptions.
The project-goals workflow checks the allowed root Markdown inventory
and required documentation entry points; review still verifies
meaning, freshness and links.
