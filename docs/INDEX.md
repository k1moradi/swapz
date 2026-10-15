# swapz documentation index

Start with the project's six authoritative documents:
[README](../README.md), [VISION](../VISION.md),
[coding standards](coding_standards.md), [testing standards](testing_standards.md),
[compile](compile.md) and [benchmark](benchmark.md). Root agent
entry points remain [AGENTS](../AGENTS.md), [CLAUDE](../CLAUDE.md),
[Codex validation bootstrap](../CODEX_VALIDATION.md), [agent](../agent.md)
and [Copilot](../.github/copilot-instructions.md).

## Active owner documents

| Document | Purpose |
|---|---|
| [Documentation governance](DOCUMENTATION_GUIDELINES.md) | Canonical locations, ownership, maintenance |
| [V3 TODO](TODO.md) | Active, prioritized tasks only |
| [V3 roadmap](ROADMAP.md) | Design direction, open correctness/performance gates |
| [Device geometry](DEVICE_GEOMETRY.md) | Allocation, sector and real lower-I/O accounting |
| [V3 component README](../kernel/extent-v3/README.md) | Source-specific scope and layout |
| [V3 loaded test gate](../kernel/extent-v3/LIVE_TEST_GATE.md) | Safety preconditions and reproducibility |
| [Runtime test README](../tests/runtime/README.md) | Test and oracle navigation |
| [Native suites](../tests/suites/README.md) | Current compiled-C tests |

## Historical plans and technical specifications

[Archive index](archive/README.md) covers retained older designs and plans.
The `docs/recall-*`, `docs/nbd-*` and `docs/pidfd-*` documents describe
specific prototype interfaces, ownership and safe failure boundaries.
Component-local Markdown may define test protocols; it is not itself
a claim of a successfully loaded or physically tested implementation.

Standalone test **reports**, dated reviews, V2.2 audit documents and offline
qualification records were removed from the tracked tree. Their exact text,
including failures, observations and revision labels, remains in
[the pre-cleanup Git revision](https://github.com/k1moradi/swapz/tree/abbdbce277938f3678a640af93ef066394b44606).
Do not treat historical rootless evidence as qualification of current V3.
New evidence belongs in the owning active standard, existing TODO/roadmap
or test artifacts, with precise outcome and source revision.
