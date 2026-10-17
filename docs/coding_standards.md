# Coding Standards

**Immutable naming policy (read before every prompt):** The project is `swapz`;
the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the
Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`.
**Never rename or version-suffix these public identities** (for example to
`swapz3`, `dm-swapz3`, or any other replacement). Enforce the same names
in production kernel C, Kbuild/DKMS, DM tables, test harnesses, benchmarks,
CI and documentation, before every agent change. Version numbers belong in
release metadata and source paths, not the project/module/target name. Keep
`SWZ3` as the distinct V3 on-disk format; the separate safe `swapzctl`
utility does not rename the project or module.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. This single public entry point runs native production-C/source/safety checks, W=1/W=2 builds, owned RAM-backed loaded correctness, and counterbalanced off/V3 throughput trials. It must report BLOCKED (nonzero) when noninteractive administrator permission or safe isolated devices are unavailable, never skip required loaded work while claiming a full PASS. **Do not create, publish, recommend, or document alternative test commands** (including additional Make goals, directly executed test scripts, one-off Python test invocations, and manually invoked loaded-device or benchmark helpers). Private implementation scripts/sub-Make targets and CI jobs may orchestrate individual stages internally, but are not supported operator interfaces; rootless-only CI success is explicitly partial.


## Non-negotiable owner Make API

**Exactly four public root Make commands, with no exceptions or aliases:**
`make` builds the V3 kernel module and supported safe binary in
parallel; `make install` installs its versioned DKMS package and binary
to appropriate system locations, without loading or activating swap;
`make uninstall` reverses only that owned installation; and
`make test` runs native C, source/fixture/safety contracts,
W=1/W=2 kernel compilation, **then actual loaded owned-RAM smoke and
counterbalanced rate-limited off/V3 benchmark pairs**. No interactive
sudo is attempted: an ordinary user needs previously authorized
noninteractive privilege, otherwise the command exits BLOCKED (nonzero)
rather than misreporting a complete test. All previously exposed root targets such as
`verify`, `run`, `deploy`, `v3`, `clean`, `bench-*`
and `test-*` are **removed and must not be reintroduced**.
Internal Kbuild/native-suite targets do not count as public root commands.
Rootless CI runs `tests/tools/test-rootless.sh` without device access; its PASS
is not loaded-device evidence. The full `make test` must never silently
skip a privileged qualification or prompt for a password: it reports
BLOCKED if safe owned RAM devices or noninteractive privilege are unavailable.

**Enforcement:** `tests/runtime/native/make-interface-test.py`
runs in the internal rootless script and in GitHub CI, checks the exact
four-target allowlist and safety boundaries, and rejects new aliases.
All AI agents must uphold that check and update this owner contract
whenever touching the build, installation, test or CI paths.
The obsolete V2 `swapzctl` must not be installed: it can call
`swapon` and `swapoff` on a backing device. V3 remains
experimental, DKMS `AUTOINSTALL="no"`, and installation does
not permit activation, physical devices or existing system swap.


**Authoritative current policy.** At the start of **every task** read [README](README.md), [VISION](VISION.md), [Coding Standards](coding_standards.md), [Testing Standards](testing_standards.md), [Compile](compile.md), and [Benchmark](benchmark.md) from the latest `main`. Agent-specific files are entry-point pointers, not different policy sources.

## North star, Git and engineering priorities

Our criterion is **fewer independently measured, host-visible lower-device READ and WRITE bytes and requests**, including GC and flush costs, under the **same byte-exact verified logical workload**, with acceptable read p95/p99, CPU and memory. Compression ratio, packing diagrams, simulated I/O and green source tests alone cannot establish that win. State the applicable concrete code-level hypothesis or correctness benefit before modifying anything.

- **One branch: `main`.** No new feature/fix/experiment/release/Codex branch, branch-backed worktree, or draft PR without **explicit owner permission**. Commit small, reviewed changes directly on `main` and store evidence as files; old branch names/PRs are historical provenance.
- Check `git branch --show-current`, `git status --porcelain`, `git rev-parse HEAD`, and remote `main` before modifying or pushing. Protect concurrent work. Do not blindly `git reset --hard`, `git restore .`, `git clean -fd`, force push or overwrite another agent's changes.
- **More than 50% of ongoing development engineering time** must concern **actual production Linux kernel module C**: designing, reviewing, debugging, profiling, and implementing swap behavior. Linux modules use C, **not C++**; C++ can support native model tests but cannot count as kernel implementation. Python/shell are thin test/data glue, not the default deliverable. Explicit independent validation-only tasks may spend the necessary time testing; do not invent kernel edits to reach a quota.
- Write clean, focused Linux-kernel-style C: kernel types/APIs, checked arithmetic and pointer lifetimes, bounded stack and allocations, small cohesive functions, meaningful names and minimal duplication. Avoid unsafe recursion, hidden allocations, libc/C++ features in the module, and unnecessary infrastructure.

## Implementation boundaries

**V3 is the only active source target on `main`:** `src/kernel/{dm-target,engine,authority,codec}.c`, `SWZ3` format, `swapz` DM target. The root `Makefile` builds this V3 module by default, and `dkms.conf` packages it with `AUTOINSTALL="no"`. This is a **development build default, NOT production readiness**. V3 remains **null_blk-only** and no real swap/physical media may be used. Retired V2.2 `kernel/dm-swapz.c`/`SPWZ` is archival source, not an optimization target, default build or benchmark comparator. Never activate both modules together or interpret this change as an in-place format migration.

### Non-negotiable BIO contracts

1. **Upper BIO ownership:** every accepted BIO has a unique owner, completed exactly once. Handle callbacks, worker drains, suspend and teardown without use-after-free or lost completions.
2. **Authoritative mapping:** only the most recent successfully published generation is visible. Never publish staged writes, acknowledge completion or reuse extents before their required lower data and FUA/PREFLUSH work succeeds.
3. **Ordering:** same-page read-after-write, multiple overwrites, DISCARD and READ/WRITE dependencies, PREFLUSH-only, WRITE+PREFLUSH, FUA, GC and suspend/drain preserve correct order. Reordering is permitted only for independent records.
4. **Fail-closed:** failed or torn/short lower operations cannot publish mappings or accidentally submit pending unpublished writes after a target failure. Error injection before `dm_io` is a **synthetic pre-submission fault**, not proof of a real device-originated error.
5. **Bounds and geometry:** validate 4096B logical pages, sector arithmetic, 4/8/16KiB V3 physical extents, headers, CRC, segment live references and lower range limits. Linux stat sectors are **512-byte accounting units**, not necessarily drive logical/physical sectors.
6. **GC:** relocate only still-live authoritative objects; no premature reserve rotation, overwrite of referenced extents, stale owner reads, unbounded ENOSPC loops or accidental false success. GC lower READ and WRITE cost must be counted.
7. **Compression:** V3 already calls LZ4 for the 4096B foreground page and stores **whole-page RAW fallback** if compressed output does not fit `SWAPZ_MAX_COMPRESSED=3568`. The DM layer cannot infer original filename/type. Avoid an unsupported entropy/type prefilter; it could turn compressible pages into larger RAW writes and cannot by itself solve singleton write windows.
8. **Resource accounting:** distinguish compression **attempts** from committed windows/bytes, and front-end `dm_io` calls from actual lower-device requests; avoid unexplained counters.

Historical alpha.8 disjoint-read bypass did not establish a matched-load lower-I/O gain and is not active by default. Prior comparisons are archival diagnostic evidence, not a requirement to benchmark V2.2.

## Change workflow and review gate

Start from a real production C defect/bottleneck. Add a discriminating **direct-production-C** regression where possible, implement the smallest safe patch, compile with W=1/W=2 and tests from [compile.md](compile.md) and [testing_standards.md](testing_standards.md), then benchmark only according to [benchmark.md](benchmark.md). Never weaken assertion, verification or null_blk admission to manufacture PASS. Preserve failing logs; attribute helper defects separately from kernel faults.

**Mandatory end of EVERY implementation task:** update the **relevant one or more of these four governing standards in the same `main` commit**, documenting new behavior, lesson, invariant, reproducible test and remaining limits. Update `README.md` for user-facing changes, and `VISION.md` if project acceptance criteria change. CI can enforce a standards-file co-change, but it cannot prove factual accuracy. Keep [current qualification gates](testing_standards.md), older `CODEX_VALIDATION.md` and previous PRs as **archival evidence**, not independent active policy.

## Canonical project version

`src/kernel/VERSION` is the only manually edited project version.
The kernel build generates its version header; `dm-swapz.ko`
exports `MODULE_VERSION`, DKMS sources the installed VERSION file,
`swapzctl` uses the same string, and CI/loaded safety gates must
verify consistency. Never pin independent alpha literals in production
C, `dkms.conf`, helper scripts, Make rules or CI assertions.

## Documentation ownership and consolidated standards

The only Markdown documents directly under `docs/` are
`coding_standards.md`, `testing_standards.md`, `compile.md`,
`benchmark.md` and `ROADMAP.md`. Root `README.md` and `VISION.md`
complete the authoritative entry points; agent instructions are short
pointers. The roadmap owns **current unchecked V3 tasks and milestones**.
The testing standard owns reproducible test oracles, rootless limitations,
owner-authorized virtual-device work, pidfd/recall and teardown safety.
Benchmarking owns evidence scope and device geometry. Compile owns the
exact four-command Make interface and reused build tree.

Do not create standalone dated audit, review, test-report, JSON-evidence,
agent transcript or obsolete version-plan documents. Condense relevant
correctness and negative findings into the owning core document, label
exact source and actual PASS/FAIL/BLOCKED/NOT RUN scope, and preserve raw
records in test artifacts or immutable Git history. Never promote old
V2.2 scripts or source-only model PASS as current V3 evidence.

For any deletion or move, check code/test and CI hard-coded paths,
change all incoming relative Markdown links, keep the root README
linked to **every tracked Markdown document**, and preserve required
workflow checks. Implementation changes must update the relevant
canonical standard in the same main-branch commit. The old single-main
branch-consolidation manifest was a one-time cleanup input; do not
reintroduce a branch-prune workflow after main is the sole branch.

### Shared utilities and legacy retirement

General-purpose maintained scripts and measurement helpers belong under
`tests/tools/`, not parallel `bench/` and `scripts/` roots. Fixture-specific
regressions remain under `tests/`. The root Make API retains exactly four
approved commands; moving scripts must not add a fifth public goal.
Old V2 scripts accepting arbitrary block devices or using the retired
Device Mapper target remain accessible only from immutable Git history,
not runnable within current V3 helper entry points.

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

`tests/tools/device-roundtrip.c` is the minimal **compiled C** loaded-I/O
oracle for an exact V3 mapping, not a new userspace swap controller.
It does direct aligned byte-exact reads/writes, overwrites and flushes.
`tests/tools/deploy-nullblk.sh` is the thin privileged provisioning and
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
with production-C `swapz_page_is_zero`. Nonzero values must use the
normal LZ4/RAW path, however small the compressed output is.

**Ordering rule:** drain all pending accepted upper writes, then
`swapz_discard_page` advances generation and releases old liveness;
only then acknowledge the logical zero write. PREFLUSH preceding the
BIO is honored by the worker; for REQ_FUA an actual successful lower
flush is still required before completion. A failed flush/discard
fails closed; no successful zero counter or logical-write accounting
may occur on error. The path does not invoke lower WRITE or invent
on-media persistence for this volatile alpha. The `zero_elided`
status key counts **successful logical write elisions**, not all
LZ4-attempted pages and not observed lower-media erase operations.
