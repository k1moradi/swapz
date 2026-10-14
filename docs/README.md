# swapz documentation index

Start at the repository [README](../README.md) and
[AGENTS.md](../AGENTS.md). The six authoritative project documents
remain at the repository root because current agent entry points and
CI governance explicitly require those paths:
[README](../README.md), [VISION](../VISION.md),
[coding standards](../coding_standards.md),
[testing standards](../testing_standards.md),
[compile](../compile.md), [benchmark](../benchmark.md).
The root AI-agent entry points are [AGENTS.md](../AGENTS.md),
[CLAUDE.md](../CLAUDE.md), [agent.md](../agent.md),
[CODEX_VALIDATION.md](../CODEX_VALIDATION.md) and
[Copilot instructions](../.github/copilot-instructions.md).

## Active plans and references

| Document | Ownership |
| --- | --- |
| [Documentation guidelines](DOCUMENTATION_GUIDELINES.md) | Required placement, consolidation, maintenance, and archival rules |
| [Active V3 tasks](TODO.md) | Short, current, prioritized unchecked work |
| [V3 roadmap / goals](ROADMAP.md) | Algorithm direction and milestones; VISION controls acceptance |
| [Device geometry](DEVICE_GEOMETRY.md) | Sector, allocation, filesystem and lower-stat meanings |
| [Production readiness ledger](PRODUCTION_READINESS.md) | Version-specific results and open qualification gaps, not release approval |
| [Kernel V3 README](../kernel/extent-v3/README.md) | Component-local implementation and experimental notes |
| [Runtime tests](../tests/runtime/README.md) | Active V3 test and oracle navigation |
| [Native suites](../tests/suites/README.md) | Test inventory and build targets |

## Versioned evidence, not policy

The historical [Codex validation worklog](archive/v2.2/CODEX_VALIDATION.md),
[long V2.2 checklist](archive/v2.2/TODO.md),
[V2.x validation history](archive/v2.2/VALIDATION.md),
[old V2.2 roadmap](archive/v2.2/ROADMAP.md),
[old V2.2 design](archive/v2.2/DESIGN.md), and
[V2.1 testing plan](archive/v2.1/TESTING.md) preserve provenance, not
current commands. The [historical V3 goals](archive/v3/V3_GOALS.md) and
[performance diagnosis](archive/v3/PERFORMANCE_DIAGNOSIS.md)
likewise records a dated experiment; read the active
[benchmark standard](../benchmark.md) before drawing conclusions.

Existing subject-specific reports under [benchmarks](benchmarks/),
[validation](validation/), and the `docs/v22-*`, `docs/recall-*`,
`docs/nbd-*`, `docs/codex-*` and `docs/main-developer-*`
families are retained as **historical, scope-limited evidence**.
Many document only rootless models or independent reviews; do not
interpret them as enabled V3 features or measured device improvements.
Component-local test protocols remain with the component where needed.

Do not create a second source of policy or a separate unindexed
worklog. For a new topic, first update an existing owner document
and link immutable supporting evidence there.
