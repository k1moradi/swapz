# Legacy build and test conventions — relocated

**Historical link only. New engineering policies do not belong here.**

The current **six authoritative documents** are
[README.md](../README.md), [VISION.md](../VISION.md),
[coding_standards.md](coding_standards.md),
[testing_standards.md](testing_standards.md),
[compile.md](compile.md), and [benchmark.md](benchmark.md).
Agents must read all six **before every task**.

Build and test policy is now in `compile.md` and
`testing_standards.md`: one `~/swapz/build/` reused for all compiled
outputs; Kbuild/Make; rootless production-C suites, safe owned
null_blk loaded validation; main-only development; exact equal-data
off/V3 comparisons and same-commit documentation updates.

The previous detailed text remains retrievable in this file's Git
history, but is **not a seventh current standards document**.
