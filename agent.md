# agent.md

**Mandatory instruction source:** [AGENTS.md](AGENTS.md).

All swapz development agents, including ChatGPT and Codex, **work directly
on `main` only**. Do not create feature, fix, validation, temporary, or
pull-request branches unless the repository owner explicitly requests an
exception. Do not recommend branches as the normal workflow.

Prioritize **production kernel C and C++ development**, debugging,
correctness, performance improvements, and tests that execute real C/C++
code. Use Python/shell primarily as small supporting harnesses and
analysis tools when necessary.

See AGENTS.md for complete preflight, source-provenance, safety,
matched-workload benchmark, CI and host-protection requirements.
Historical documents referring to deleted branch names do not
override this policy.
