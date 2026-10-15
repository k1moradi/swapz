# Copilot — swapz canonical policy

Read [AGENTS.md](../AGENTS.md) and the six authoritative files
[README.md](../README.md), [VISION.md](../VISION.md),
[coding_standards.md](../docs/coding_standards.md),
[testing_standards.md](../docs/testing_standards.md),
[compile.md](../docs/compile.md), [benchmark.md](../docs/benchmark.md) at the
start of **every task**. Do not create alternative policies.

Work only on `main`, no branch unless owner explicitly asks. Spend
strictly more than 50% of ongoing development engineering effort on
actual production kernel **C**. Build only in `~/swapz/build/`; use
real C tests, byte-identical inputs and independent lower-I/O counters.
No reboot, active swap/physical media or unsafe teardown. Update the
relevant current standard(s) in the same code commit and test exact HEAD.

Before creating or moving documentation, consult
[docs/INDEX.md](../docs/INDEX.md) and
[documentation guidelines](../docs/DOCUMENTATION_GUIDELINES.md).
Use the active [V3 TODO](../docs/TODO.md) instead of historical tasks.
