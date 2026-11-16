# Round 018 — Agent 2 pinned UML dependent Kconfig gate

- Open: https://github.com/k1moradi/swapz/issues/135#issuecomment-6917527410
- Engineering baseline: 9ecb5cc650cc9be9f4efe2bf38c9e3c91f620fa0.
- Task publication: 37de56d28af54003954d8b0214fd15baf397bf11.
- Original hosted failure: https://github.com/k1moradi/swapz/actions/runs/43860358473 ; job 133275255387. The first observed fatal phase was `verify_uml_config`: `effective-CONFIG_BLK_CGROUP:expected=n:actual=MISSING`. Enabled modified objects and `kunit.py` exit zero did not qualify five TAP cases; the disabled profile did not complete.
- Authenticated pinned dependency: `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8:init/Kconfig` opens `if CGROUPS` at line 866, declares `config BLK_CGROUP` at 921 (`depends on BLOCK`, `default n`), and closes `endif # CGROUPS` at 1203.
- Implemented: one explicit disabled-request-only dependent-child exception in the effective Kconfig gate; use that same function for final pair verification. The Bash workflow no longer requires the suppressed child line after Python validation. All other required options are exact; y/m child, y parent, omitted/forced request, wrong ZSWAP profile, malformed/duplicate evidence still fail.
- New source-coupled rootless tests exercise both y/n, omitted/present disabled child, wrong dependency, required-option suppression, duplicate/malformed/symlink/oversized, and workflow post-gate. Original strict five-case TAP and 3/4 compiled SHA checks are retained.
- Exact-source tests and GitHub Actions results are reported separately in the issue comment. No KUnit `PASS`, loaded writeback or physical readback is implied by test fixtures.
