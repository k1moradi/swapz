# CLAUDE.md — swapz agent policy

**Canonical mandatory instructions: [AGENTS.md](AGENTS.md).**
Read that file in full before editing any file.

**Only work on the existing `main` branch.** Never create or push a
branch (temporary, feature, fix, validation, release, or PR branch),
or a branch-backed worktree, unless the repository owner **explicitly**
requests an exception. Commit small changes directly on `main` with
tests and exact commit provenance. Preserve existing local work:
no blind hard resets, full-worktree restore/clean, or force-push.

**Spend strictly more than 50% of ongoing engineering effort on the
actual Linux kernel module's production C code**: design, implementation,
review, debugging and profiling of swap I/O, LZ4 compression, raw
fallback, BIO completion, mapping authority, segment GC, concurrency
and lower-device I/O economics. Kernel modules are written in C;
C++ is useful for separately built direct regression tests, not kernel
C++ compilation. Python, shell, CI, test-fixture generation and Markdown
must remain supporting work, not the default center of development.
Never weaken tests or create arbitrary source churn to satisfy a quota.

Preserve the V2.2 default build; V3 is experimental and null_blk-only.
Never touch real active swap, /dev/sdb1, /swapfile, unrelated/physical
devices; never swapoff/swapon, reboot or force teardown. Verify
identical logical 4KiB page inputs across off/V2.2/V3 benchmarks, and
report measured backing bytes and request counts and correct readback.

Historical branch names in old reports are provenance only and must
not be recreated. AGENTS.md takes precedence over older instructions.
