# Documentation governance

**Active for all contributors and agents.** Keep the project concise,
linked and free of separate report transcripts.

## Canonical owners

- Root `README.md` is the GitHub-facing entry point; root `VISION.md`
  defines measured lower-device I/O acceptance.
- The four engineering standards are `docs/coding_standards.md`,
  `docs/testing_standards.md`, `docs/compile.md` and `docs/benchmark.md`.
  Keep these canonical paths in agent entry points and CI.
- Keep root `AGENTS.md`, `CLAUDE.md`, `agent.md`,
  `CODEX_VALIDATION.md`, and `.github/copilot-instructions.md` as short
  guidance entry points, not competing standards.
- [TODO](TODO.md) owns current unchecked work; [ROADMAP](ROADMAP.md)
  owns milestones, open release gates and algorithm hypotheses.
  [Device geometry](DEVICE_GEOMETRY.md) owns units/layout.
  [INDEX](INDEX.md) is the curated documentation navigation.
- Retain concise reusable design and component-local test specifications
  where needed. Historical plans under [archive](archive/README.md)
  do **not** impose active requirements.

## Remove report duplication safely

- Do **not** add standalone Markdown review/audit, CI validation transcript,
  one-off benchmark report, or dated agent worklog files.
- For each factual new result, update the relevant standard in the **same
  implementation commit**. Record exact source revision, actual PASS/FAIL,
  BLOCKED/NOT RUN/INCONCLUSIVE, test environment, negative evidence, and
  limitations without implying that rootless mocks are loaded-kernel proof.
- Preserve detailed raw output in bounded test artifacts or immutable
  Git history, never erase a unique result without recording where it lives.
- Check all incoming relative Markdown links, source scripts, agent entry
  points and workflow path constraints before deleting/moving a document.
- Root README must have a direct relative link to **every tracked Markdown
  file**, including component-local and archived plans. The project-goals
  workflow checks the inventory.
- Keep work on `main` unless the owner explicitly authorizes another
  branch; do not overwrite concurrent edits or force-push.

Report cleanup is documentation-only. It does **not** permit module loading,
system swap changes, physical-device experiments or unsafe teardown.
Historical files remain available at
[the original Git revision](https://github.com/k1moradi/swapz/tree/abbdbce277938f3678a640af93ef066394b44606).
