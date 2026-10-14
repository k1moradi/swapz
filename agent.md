# agent.md

**Mandatory instruction source:** [AGENTS.md](AGENTS.md).

All swapz development agents, including ChatGPT and Codex, **work directly
on `main` only**. Do not create feature, fix, validation, temporary, or
pull-request branches unless the repository owner explicitly requests an
exception. Do not recommend branches as the normal workflow.

**MANDATORY: More than 50% of ongoing engineering time must be spent
developing the swapz kernel module itself**, including production kernel
**C** implementation, debugging, code review and performance profiling.
C++ is suitable for separately built direct regression tests, but the
Linux kernel module is written in C. Spend the majority of time on the
kernel implementation, **not on Python scripts, orchestration, Markdown,
or building test frameworks**. Use Python/shell only as minimal, useful
support for the kernel C development and safety/correctness gates.
Explicitly requested validation-only assignments are exceptions to the
time allocation, not invitations to make development Python-first.

See AGENTS.md for complete preflight, source-provenance, safety,
matched-workload benchmark, CI and host-protection requirements.
Historical documents referring to deleted branch names do not
override this policy.

**EVERY TASK:** Read current-main `VISION.md`, `V3_GOALS.md`,
`PRODUCTION_READINESS.md`, and `docs/BUILD_AND_TEST_CONVENTIONS.md`
at the start, and formulate the relevant project-goal correctness /
lower-I/O hypothesis. Reuse **only `~/swapz/build/`** for all compiled
artifacts and bytecode. Prefer reusable, behavior-named native-C test
suites; do not proliferate version-labeled test runners. After **every
implementation prompt** update relevant Markdown documentation in the
same commit, execute automated project-goal tests and report their
result. This is mandatory alongside the main-only / majority kernel C
rule, not a replacement for it.
