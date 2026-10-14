# Copilot — swapz canonical policy

Read [AGENTS.md](../AGENTS.md) and the six authoritative files
[README.md](../README.md), [VISION.md](../VISION.md),
[coding_standards.md](../coding_standards.md),
[testing_standards.md](../testing_standards.md),
[compile.md](../compile.md), [benchmark.md](../benchmark.md) at the
start of **every task**. Do not create alternative policies.

Work only on `main`, no branch unless owner explicitly asks. Spend
strictly more than 50% of ongoing development engineering effort on
actual production kernel **C**. Build only in `~/swapz/build/`; use
real C tests, byte-identical inputs and independent lower-I/O counters.
No reboot, active swap/physical media or unsafe teardown. Update the
relevant current standard(s) in the same code commit and test exact HEAD.
