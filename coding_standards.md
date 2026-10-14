# Coding Standards

**Authoritative current policy.** At the start of **every task** read [README](README.md), [VISION](VISION.md), [Coding Standards](coding_standards.md), [Testing Standards](testing_standards.md), [Compile](compile.md), and [Benchmark](benchmark.md) from the latest `main`. Agent-specific files are entry-point pointers, not different policy sources.

## North star, Git and engineering priorities

Our criterion is **fewer independently measured, host-visible lower-device READ and WRITE bytes and requests**, including GC and flush costs, under the **same byte-exact verified logical workload**, with acceptable read p95/p99, CPU and memory. Compression ratio, packing diagrams, simulated I/O and green source tests alone cannot establish that win. State the applicable concrete code-level hypothesis or correctness benefit before modifying anything.

- **One branch: `main`.** No new feature/fix/experiment/release/Codex branch, branch-backed worktree, or draft PR without **explicit owner permission**. Commit small, reviewed changes directly on `main` and store evidence as files; old branch names/PRs are historical provenance.
- Check `git branch --show-current`, `git status --porcelain`, `git rev-parse HEAD`, and remote `main` before modifying or pushing. Protect concurrent work. Do not blindly `git reset --hard`, `git restore .`, `git clean -fd`, force push or overwrite another agent's changes.
- **More than 50% of ongoing development engineering time** must concern **actual production Linux kernel module C**: designing, reviewing, debugging, profiling, and implementing swap behavior. Linux modules use C, **not C++**; C++ can support native model tests but cannot count as kernel implementation. Python/shell are thin test/data glue, not the default deliverable. Explicit independent validation-only tasks may spend the necessary time testing; do not invent kernel edits to reach a quota.
- Write clean, focused Linux-kernel-style C: kernel types/APIs, checked arithmetic and pointer lifetimes, bounded stack and allocations, small cohesive functions, meaningful names and minimal duplication. Avoid unsafe recursion, hidden allocations, libc/C++ features in the module, and unnecessary infrastructure.

## Implementation boundaries

**V3 is the only active source target on `main`:** `kernel/extent-v3/{dm-target,engine,authority,codec}.c`, `SWZ3` format, `swapz3` DM target. The root `Makefile` builds this V3 module by default, and `dkms.conf` packages it with `AUTOINSTALL="no"`. This is a **development build default, NOT production readiness**. V3 remains **null_blk-only** and no real swap/physical media may be used. Retired V2.2 `kernel/dm-swapz.c`/`SPWZ` is archival source, not an optimization target, default build or benchmark comparator. Never activate both modules together or interpret this change as an in-place format migration.

### Non-negotiable BIO contracts

1. **Upper BIO ownership:** every accepted BIO has a unique owner, completed exactly once. Handle callbacks, worker drains, suspend and teardown without use-after-free or lost completions.
2. **Authoritative mapping:** only the most recent successfully published generation is visible. Never publish staged writes, acknowledge completion or reuse extents before their required lower data and FUA/PREFLUSH work succeeds.
3. **Ordering:** same-page read-after-write, multiple overwrites, DISCARD and READ/WRITE dependencies, PREFLUSH-only, WRITE+PREFLUSH, FUA, GC and suspend/drain preserve correct order. Reordering is permitted only for independent records.
4. **Fail-closed:** failed or torn/short lower operations cannot publish mappings or accidentally submit pending unpublished writes after a target failure. Error injection before `dm_io` is a **synthetic pre-submission fault**, not proof of a real device-originated error.
5. **Bounds and geometry:** validate 4096B logical pages, sector arithmetic, 4/8/16KiB V3 physical extents, headers, CRC, segment live references and lower range limits. Linux stat sectors are **512-byte accounting units**, not necessarily drive logical/physical sectors.
6. **GC:** relocate only still-live authoritative objects; no premature reserve rotation, overwrite of referenced extents, stale owner reads, unbounded ENOSPC loops or accidental false success. GC lower READ and WRITE cost must be counted.
7. **Compression:** V3 already calls LZ4 for the 4096B foreground page and stores **whole-page RAW fallback** if compressed output does not fit `SV3_MAX_COMPRESSED=3568`. The DM layer cannot infer original filename/type. Avoid an unsupported entropy/type prefilter; it could turn compressible pages into larger RAW writes and cannot by itself solve singleton write windows.
8. **Resource accounting:** distinguish compression **attempts** from committed windows/bytes, and front-end `dm_io` calls from actual lower-device requests; avoid unexplained counters.

Historical alpha.8 disjoint-read bypass did not establish a matched-load lower-I/O gain and is not active by default. Prior comparisons are archival diagnostic evidence, not a requirement to benchmark V2.2.

## Change workflow and review gate

Start from a real production C defect/bottleneck. Add a discriminating **direct-production-C** regression where possible, implement the smallest safe patch, compile with W=1/W=2 and tests from [compile.md](compile.md) and [testing_standards.md](testing_standards.md), then benchmark only according to [benchmark.md](benchmark.md). Never weaken assertion, verification or null_blk admission to manufacture PASS. Preserve failing logs; attribute helper defects separately from kernel faults.

**Mandatory end of EVERY implementation task:** update the **relevant one or more of these four governing standards in the same `main` commit**, documenting new behavior, lesson, invariant, reproducible test and remaining limits. Update `README.md` for user-facing changes, and `VISION.md` if project acceptance criteria change. CI can enforce a standards-file co-change, but it cannot prove factual accuracy. Keep [PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md), older `CODEX_VALIDATION.md` and previous PRs as **archival evidence**, not independent active policy.

## Documentation ownership

Keep policies in the six canonical documents and agent prompts as pointers.
Use [docs/README.md](docs/README.md) for navigation,
[docs/TODO.md](docs/TODO.md) for current V3 work, and
[docs/DOCUMENTATION_GUIDELINES.md](docs/DOCUMENTATION_GUIDELINES.md)
for document creation, consolidation, archival and link review.
Do not append dated evidence transcripts to TODO or revive archived
V2.x instructions. Root Markdown locations are CI-governed. The root README must provide
one direct Markdown link to **every tracked Markdown file**, including
archival reports and component notes; `project-goals` CI checks this
inventory. Preserve the four engineering standards' co-change
requirement for actual code, build, test and workflow changes.

## Absolute host safety

Never reboot, `swapoff` or `swapon`. Never touch `/dev/sdb1`, `/swapfile`, active swap, physical storage, unrelated DM targets or unowned null_blk. Host tests require exactly owned, uniquely identified **RAM-backed null_blk**, verified major/minor, table UUID and holders, safe ordinary teardown, and quarantine if unresolved I/O remains. Real media experiments are separate owner-authorized future work. Source CI and null_blk results are not physical wear evidence.

## Current V3 development focus (after retirement of V2.2)

Prioritize the **C-level singleton write-window bottleneck**, physical
extent geometry, actual on-device write-byte/request reduction versus
uncompressed direct I/O, correct GC accounting, and completion-safe
read/write dependencies. Compression of a 4096B page to about 2048B
must be validated by actual LZ4 output measurements; it is not proof
of a 2048B lower-device write. Fail-closed publication and null_blk-only
safety still precede any optimization.

## Safe module deployment for development

`tools/device-roundtrip.c` is the minimal **compiled C** loaded-I/O
oracle for an exact V3 mapping, not a new userspace swap controller.
It does direct aligned byte-exact reads/writes, overwrites and flushes.
`tools/deploy-nullblk.sh` is the thin privileged provisioning and
teardown guard. Only owned RAM-backed configfs null_blk and matching
DM UUID/major:minor are eligible; never make a deployment helper
support physical devices or automatically use active Linux swap.
No global module removal, force deletion, reboot or partitioning.
The workflow may report BLOCKED if an incompatible module already
exists, and must preserve the host's other mappings and swap state.

## Exact-zero logical write representation

V3 may elide a **truly all-zero, full 4096-byte page** by treating it
as the same mapping state as an authoritative discarded/never-written
page. This is legitimate because a read of an invalid map returns
exactly 4096 zero bytes; **not** because compressible data are
interchangeable with zero. The kernel first attempts LZ4 as before;
only if the output is at most 64 bytes does it scan **every input byte**
with production-C `sv3_page_is_zero`. Nonzero values must use the
normal LZ4/RAW path, however small the compressed output is.

**Ordering rule:** drain all pending accepted upper writes, then
`sv3_discard_page` advances generation and releases old liveness;
only then acknowledge the logical zero write. PREFLUSH preceding the
BIO is honored by the worker; for REQ_FUA an actual successful lower
flush is still required before completion. A failed flush/discard
fails closed; no successful zero counter or logical-write accounting
may occur on error. The path does not invoke lower WRITE or invent
on-media persistence for this volatile alpha. The `zero_elided`
status key counts **successful logical write elisions**, not all
LZ4-attempted pages and not observed lower-media erase operations.
