# Coding Standards

**Authoritative current policy.** At the start of **every task** read [README](README.md), [VISION](VISION.md), [Coding Standards](coding_standards.md), [Testing Standards](testing_standards.md), [Compile](compile.md), and [Benchmark](benchmark.md) from the latest `main`. Agent-specific files are entry-point pointers, not different policy sources.

## North star, Git and engineering priorities

Our criterion is **fewer independently measured, host-visible lower-device READ and WRITE bytes and requests**, including GC and flush costs, under the **same byte-exact verified logical workload**, with acceptable read p95/p99, CPU and memory. Compression ratio, packing diagrams, simulated I/O and green source tests alone cannot establish that win. State the applicable concrete code-level hypothesis or correctness benefit before modifying anything.

- **One branch: `main`.** No new feature/fix/experiment/release/Codex branch, branch-backed worktree, or draft PR without **explicit owner permission**. Commit small, reviewed changes directly on `main` and store evidence as files; old branch names/PRs are historical provenance.
- Check `git branch --show-current`, `git status --porcelain`, `git rev-parse HEAD`, and remote `main` before modifying or pushing. Protect concurrent work. Do not blindly `git reset --hard`, `git restore .`, `git clean -fd`, force push or overwrite another agent's changes.
- **More than 50% of ongoing development engineering time** must concern **actual production Linux kernel module C**: designing, reviewing, debugging, profiling, and implementing swap behavior. Linux modules use C, **not C++**; C++ can support native model tests but cannot count as kernel implementation. Python/shell are thin test/data glue, not the default deliverable. Explicit independent validation-only tasks may spend the necessary time testing; do not invent kernel edits to reach a quota.
- Write clean, focused Linux-kernel-style C: kernel types/APIs, checked arithmetic and pointer lifetimes, bounded stack and allocations, small cohesive functions, meaningful names and minimal duplication. Avoid unsafe recursion, hidden allocations, libc/C++ features in the module, and unnecessary infrastructure.

## Implementation boundaries

Default/frozen comparator: `kernel/dm-swapz.c`, V2.2 `SPWZ` format, root `Makefile`/`kernel/Makefile`/`dkms.conf`. Experimental non-production V3: `kernel/extent-v3/{dm-target,engine,authority,codec}.c`, incompatible `SWZ3` format and `swapz3` target. The two alternative modules share basename `dm-swapz.ko` and are **never loaded simultaneously**. Do not change the default module, physical format or V3's **null_blk-only** constructor admission without an explicit reviewed design and evidence; no in-place V2.2-to-V3 migration or hibernation support exists.

### Non-negotiable BIO contracts

1. **Upper BIO ownership:** every accepted BIO has a unique owner, completed exactly once. Handle callbacks, worker drains, suspend and teardown without use-after-free or lost completions.
2. **Authoritative mapping:** only the most recent successfully published generation is visible. Never publish staged writes, acknowledge completion or reuse extents before their required lower data and FUA/PREFLUSH work succeeds.
3. **Ordering:** same-page read-after-write, multiple overwrites, DISCARD and READ/WRITE dependencies, PREFLUSH-only, WRITE+PREFLUSH, FUA, GC and suspend/drain preserve correct order. Reordering is permitted only for independent records.
4. **Fail-closed:** failed or torn/short lower operations cannot publish mappings or accidentally submit pending unpublished writes after a target failure. Error injection before `dm_io` is a **synthetic pre-submission fault**, not proof of a real device-originated error.
5. **Bounds and geometry:** validate 4096B logical pages, sector arithmetic, 4/8/16KiB V3 physical extents, headers, CRC, segment live references and lower range limits. Linux stat sectors are **512-byte accounting units**, not necessarily drive logical/physical sectors.
6. **GC:** relocate only still-live authoritative objects; no premature reserve rotation, overwrite of referenced extents, stale owner reads, unbounded ENOSPC loops or accidental false success. GC lower READ and WRITE cost must be counted.
7. **Compression:** V3 already calls LZ4 for the 4096B foreground page and stores **whole-page RAW fallback** if compressed output does not fit `SV3_MAX_COMPRESSED=3568`. The DM layer cannot infer original filename/type. Avoid an unsupported entropy/type prefilter; it could turn compressible pages into larger RAW writes and cannot by itself solve singleton write windows.
8. **Resource accounting:** distinguish compression **attempts** from committed windows/bytes, and front-end `dm_io` calls from actual lower-device requests; avoid unexplained counters.

Alpha.8 opt-in disjoint READ bypass remains an **experimental historical branch variant**, not current default V3: independent QD8 matched-rate measurements did not show a lower-write win. Preserve the negative findings in [benchmark.md](benchmark.md).

## Change workflow and review gate

Start from a real production C defect/bottleneck. Add a discriminating **direct-production-C** regression where possible, implement the smallest safe patch, compile with W=1/W=2 and tests from [compile.md](compile.md) and [testing_standards.md](testing_standards.md), then benchmark only according to [benchmark.md](benchmark.md). Never weaken assertion, verification or null_blk admission to manufacture PASS. Preserve failing logs; attribute helper defects separately from kernel faults.

**Mandatory end of EVERY implementation task:** update the **relevant one or more of these four governing standards in the same `main` commit**, documenting new behavior, lesson, invariant, reproducible test and remaining limits. Update `README.md` for user-facing changes, and `VISION.md` if project acceptance criteria change. CI can enforce a standards-file co-change, but it cannot prove factual accuracy. Keep [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md), older `CODEX_VALIDATION.md` and previous PRs as **archival evidence**, not independent active policy.

## Absolute host safety

Never reboot, `swapoff` or `swapon`. Never touch `/dev/sdb1`, `/swapfile`, active swap, physical storage, unrelated DM targets or unowned null_blk. Host tests require exactly owned, uniquely identified **RAM-backed null_blk**, verified major/minor, table UUID and holders, safe ordinary teardown, and quarantine if unresolved I/O remains. Real media experiments are separate owner-authorized future work. Source CI and null_blk results are not physical wear evidence.
