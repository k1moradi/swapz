# Testing Standards

**Current testing policy.** Read [README](README.md), [VISION](VISION.md), [coding_standards.md](coding_standards.md), [compile.md](compile.md), and [benchmark.md](benchmark.md) at the **start of every agent task**. Tests must prove correctness on actual source, expose false completions and regressions, and ultimately support the project's **real lower-I/O** objective—not maximize test counts.

Current actionable V3 gaps belong in [docs/TODO.md](docs/TODO.md);
historical validation transcripts belong in the archive indexed by
[docs/README.md](docs/README.md), not in the standards or task list.

## Qualification ladder (do not confuse evidence levels)

| Gate | Shows | Cannot claim |
|---|---|---|
| Source contracts/rootless CI | Structural bounds and expected source path | Loaded BIO semantics or real request reduction |
| Exact production C + C++ model | Executed codec, mapping, GC, lower-write planning | Linux loaded module safety |
| Kbuild W=1/W=2 + verifier | Compiles against named kernel headers | Runtime authority, fault or performance |
| Owned RAM-backed null_blk loaded tests | Real kernel BIO interactions and independent backing counters on the test host | Actual SD/SSD/HDD benefits |
| Separately owner-approved real-device tests | Device-class behavior on that physical configuration | All-device performance or generic readiness |

Report **PASS, FAIL, MIXED, INCONCLUSIVE, BLOCKED, NOT RUN** with exact Git source and loaded binary SHA/vermagic, kernel/compiler, failed records, cleanup evidence. Green CI ≠ production release.

## Reusable native C tests: mandatory first choice

**Only one reusable compiled-output tree:** `~/swapz/build/`. Native tests link to **actual** `kernel/extent-v3/{codec,authority,engine}.c` and use semantic names, not newly duplicated version-number frameworks. From checkout root:

~~~sh
make test                  # all active V3 native production-C suites
make test-codec            # codec-roundtrip
make test-mapping          # mapping authority, transactions, overwrites, raw/discard
make test-gc               # liveness, forbidden victim, rotation, cost
make test-lower-io         # flush/FUA, lower write aggregation
make -C tests/suites test-all
~~~

There are **15 behavior-named native C executables** in `build/tests/native/`: `codec-roundtrip`; `mapping-authority`; `transaction-publication`; `write-verification`; `dead-segment-reclamation`; `raw-discard`; `online-packing`; `randomized-authority`; `gc-forbidden-victim`; `gc-cost-accounting`; `gc-rotation`; `gc-engine-rotation`; `flush-ordering`; `lower-write-aggregation`; `zero-write-elision`. Current V3 test source names reflect behavior in `tests/runtime/native/{codec,mapping,gc,io}/`, without deleting native assertions. Historical v22/host scripts are retained until CI dependency parity is established. One declarative rule in `tests/suites/Makefile` replaces 14 nearly identical C compile recipes. Python helpers must be bounded/necessary and should not replace actual C tests. For sanitizers, use the applicable `SANITIZE=1` native test target and independent ASan/UBSan/Clang gates described in [compile.md](compile.md).

## Minimum correctness matrix

- Compression/decompression: 4096B data and CRC, very small, medium, near-3568B LZ4 payload, RAW fallback, corrupted metadata/CRC and invalid bounds.
- Mapping: latest-generation-wins, compressed↔RAW, multiple overwrites, same-page and disjoint reads, pending-write authority, only post-success publication, readback of **every page**.
- Ordering and lifecycle: PREFLUSH-only, data+PREFLUSH, FUA, DISCARD same/different page, worker-quantum boundaries, full-window flush, suspend/drain (including 1024 accepted BIOs in controlled loaded tests), exactly-once completion.
- Concurrency and GC: stale-read ownership, inflight buffers, segment liveness, blocked full-destination/256-survivor victim, at least eight verified GC reserve-role rotations in the loaded test, invariant-safe retries after failure.
- Failures: pre-submission synthetic write/flush EIO; bounded corrupted backing reads; bypassed READ failing with pending writes; true lower READ/WRITE/flush device-originated or torn completions **only when a safe isolated mechanism is available**. Do not present a synthetic `test_fail_write_nth` injection as real-device fault coverage.
- Resource: bounded worker time, CPU, memory, GC write/read amplification, pending callback drain, no data loss or false positive completion.

Any byte mismatch, double/lost completion, authority violation, unsafe GC reuse, broken PREFLUSH/FUA ordering or unsound fail-close is a **stop-loaded-benchmark** issue. Preserve minimal C-level reproduction and all original failures. Do not remove the test to get green CI.

## Automated gates and responsibility

- `.github/workflows/project-goals.yml` on `main` runs native C/C++ tests, userspace build, one-build-root and documentation governance.
- `.github/workflows/extent-v3-codec.yml` runs actual-C and source gates and V3 W=1/W=2 kernel builds.
- `.github/workflows/kernel-bestfit4-experimental.yml` is a **manual archival reproduction only**; the combined rootless compatibility/safety workflow remains push-triggered to preserve existing safety contracts, **not** as a mandatory V2.2 benchmark arm. Active required gates are V3 exact-source/native C, kernel compile and general teardown safety.
- A code/build/test/CI change must update a **relevant one of the four current standards** in the same `main` commit; add `README.md`/`VISION.md` when their content changes. Document the failure before repair and rerun at the **final exact HEAD**.

Do not infer green workflow status from the previous commit. A compiler-only success does not qualify a newly changed kernel target as loaded safe.

## Controlled loaded-kernel preflight (no exceptions)

Capture `/proc/swaps`, mounts, lsblk/DM holders and exact module identity; only use a **newly owned, verified memory-backed `null_blk`** test instance. Ensure matching expected major/minor, DM UUID/table, no mounts/active swap. Load only the **V3** module for active qualification; the retired V2.2 target is not part of test/benchmark gates. Do **not** touch `/dev/sdb1`, `/swapfile`, active swap, any physical/unowned device, unrelated DM or system swap/zswap; never reboot, `swapoff`/`swapon`, global failure inject or force teardown. If a hung BIO/holder cannot be safely removed, quarantine test ownership and mark BLOCKED.

## Same workload and realistic source pages

For benchmarking and comparative correctness, feed *identical* immutable 4KiB fixtures and logical trace (offsets, op ordering, read generations, warmup, QD, achieved work) to bare owned null_blk "off" and experimental V3, and verify **full final logical image**. Rootless scratch-file labels do not prove a loaded V3 kernel run. Report fixture/trace/write-stream hashes and actual measured LZ4 sizes. Make compressible **anonymous** heap/stack/COW/text-buffer/decoded-raster/zeros the primary synthetic hypothesis, moderate-entropy controls and incompressible cases separately. Clean file-backed ELF/source/image pages may never enter swap; synthetic weights are not measured real-world swap population. See [benchmark.md](benchmark.md).

## Known gaps (do not overclaim)

As of consolidation, the **loaded off-versus-V3 immutable-trace comparison has NOT been performed**. Genuine device-originated read/write fault coverage is incomplete; kernel-worker CPU attribution, the historical extra backing WRITE request in 120 trials, and generic asynchronous Buffer I/O error attribution are unresolved. The alpha.8 READ-bypass matched-rate result was negative, notwithstanding exercised loaded correctness. Older reports, `PRODUCTION_READINESS.md` and historical `CODEX_VALIDATION.md` preserve detailed provenance, **not new test requirements**.

At the end of each implementation task, update this or another of the four standards with learned results, exact tests and PASS/FAIL/BLOCKED, while preserving separate versioned raw report evidence on `main`.

## Automated governance for the four standards

The `main` project-goal workflow checks that `AGENTS.md`,
`agent.md`, `CLAUDE.md`, Copilot instructions, `CODEX_VALIDATION.md`,
`README.md` and `VISION.md` all reference the four governing standards.
A same-commit change to kernel, tests, userspace, Make/DKMS or CI workflow
paths must also modify at least one of `coding_standards.md`,
`testing_standards.md`, `compile.md` or `benchmark.md`. An unrelated
archival Markdown update cannot satisfy this gate. Documentation-only
changes do not require a separate implementation commit. This is a
mechanical check of **where the learning is recorded**, not a validator
of semantic truth, tested runtime behavior or external agent prompt
compliance.

## Active V3-only default gates

`make test` runs V3 native C suites without the retired C++ model; the
latter is retained for explicit historical reproduction only.
`python3 -B tests/runtime/benchmark/io-replay-test.py -v` verifies the
**two-arm** off/V3 oracle including bad-input rejection in safe rootless
files. Benchmarks require an actual loaded V3 module before claiming
performance. Regressions focus on 2:1-ish **measured** LZ4 inputs, raw
fallback, 4KiB/8KiB/16KiB packing, GC and same-page read ordering.

### Retained rootless compatibility safety checks

The combined-rootless workflow remains **push-triggered** because its
workflow-contract regressions explicitly verify executable source
safety gates and their trigger coverage. Removing its push trigger
caused CI failures on V3 transition commit `c240696`, so the trigger
was restored before final qualification. This compatibility suite is
**not** an active V2.2 benchmarking requirement; no retired V2.2
performance comparison should enter new V3 lower-I/O reports. Keep
real V3 kernel C and owned-null_blk safety contracts enforced.

## Runtime tree consolidation — October 14, 2026

Moved/renamed all **14 C native test sources** into
`tests/runtime/native/{codec,mapping,gc,io}/` with functional names;
all test logic and the 14 output executable identities remain. A
**single Make compile rule** now builds them against the same production
kernel codec/authority/engine implementations, preserving their suites.
Moved the three active anonymous-page/immutable-replay scripts to
`tests/runtime/benchmark/`, and renamed the V3 production-source
contract test to `tests/runtime/native/source-contract-test.py`.
Updated source-relative includes/import paths and active workflow
references. Deleted old root-level names; historical Git commits
retain the exact original files. Run `make test`, direct source
contracts and the off/V3 replay test at **final HEAD**.

The remaining V2.2/pressure/recall and old-host helpers remain at
`tests/runtime/` while their sibling imports and literal workflow
references are audited. Their safety CI is **not waived or replaced by
inert stubs**. Subsequent legacy relocation requires explicit test
parity; this is not a claim that all historical duplicate Python
utilities have been eliminated.

### CI relocation fix

On the first test-layout commit `020bec7e`, all 14 native C tests, the
benchmark oracle and the V3 kernel build passed, but project-goals CI
still referenced the removed root-level `io-replay.py` in its policy
guard. The active two-arm manifest contract now resides at
`tests/runtime/benchmark/io-replay.py`. The guard must check this
path and reject the obsolete name. This failure was test-harness
plumbing, **not** proof of a kernel runtime defect or a loaded win.

### Behavior-named legacy isolation with CI parity

Eleven previously root-level `v22-*` strategy/latency/evidence Python
files were moved together into `tests/runtime/legacy/` and given
meaningful names (strategy-screen/comparison, drain-latency-analysis,
evidence-validation, latency-quantiles). Internal sibling imports
continue to resolve within `legacy/`, and imports of general
`streaming-benchmark-*` helpers use the parent runtime directory.
Existing rootless push workflows and the strict
`rootless-workflow-contract-test.py` mandatory execution/deadline
checks have been rewritten for the new paths. Their original test
assertions, negative cases and artifact schemas are retained. This
relocation isolates retired V2.2 code from active V3 benchmarks; it
**does not waive historical source-safety coverage**. Verify the
rootless workflow, NBD and teardown checks at exact HEAD.

### Rootless fio compatibility automation on main

The archived strategy-screen/comparison fixtures remain useful as
**rootless safety and evidence-schema checks**, not active V3 performance
benchmarks. The rootless fio/CLAT compatibility workflow previously
ran only for pull requests, which no longer fits the **single-main**
repository. It now runs on `main` pushes affecting those test paths
and on explicit dispatch, using a `build/python-cache` bytecode root.
This ensures behavior-renamed legacy scripts receive executable
contract validation without creating a branch or requiring physical
or active-swap access. Report synthetic evidence only as synthetic.

## Automated local deploy-and-verify gate

`make verify` invokes the 14 production-C native tests, the exact
V3 constructor/source contracts, the safe off/V3 **regular-file**
replay oracle and shell deployment source checks. CI additionally
compiles `tools/device-roundtrip.c` with `-Wall -Wextra -Werror`.
`make deploy` compiles V3 against the **running kernel**, then loads
the exact built module solely against a **fresh, unique memory-backed
null_blk**. The ephemeral mapper has its own test UUID, 16MiB logical
capacity and 64MiB RAM physical capacity. The C oracle writes 128
4096-byte pages in compressible, mixed 2:1-ish and RAW patterns,
performs full byte-exact readback, overwrites half the pages and
verifies the full image again, with ordered flush operations.

The owning script checks `/proc/swaps` and exact DM/major:minor
provenance, and attempts normal teardown of only resources it made.
If outstanding holders prevent removal, **quarantine** the owned
resource; never use `dmsetup remove -f`, `rmmod -f`, host
`swapoff`, or unowned devices. The local loaded test may be
BLOCKED on hosts without null_blk/configfs/module-signing access.
It is not equivalent to real workload performance qualification:
kernel CPU, sustained GC and matched-rate independent lower-I/O
gates in [benchmark.md](benchmark.md) remain open.

### Deployment-helper syntax gate

On commit `62ad212`, the initial rootless CI correctly rejected a
Bash conditional split across a newline in the privileged deployment
helper **before** any module/device deployment. The source was amended
to keep comparisons syntactically complete, and lower teardown now
requires a known lower device and real `holders` sysfs directory
before powering it off. `make verify` always runs `bash -n`; a
compilation PASS alone cannot certify this privileged script, and the
loaded deployment remains **NOT RUN by GitHub Actions**.

## Automated isolated execution entry point

`make run` chains all rootless native/source/replay tests,
matching-running-kernel V3 W=1/W=2 builds, and an **ephemeral**
unique owned RAM-backed `null_blk` loaded test, with all earlier
checks required before invoking sudo. Its C oracle writes and verifies
128 4KiB pages including mixed compressed/raw, overwrites and flush.
The deployment script logs SHA/vermagic, lower device UUID/major:minor,
pre/post system swap inventory, target status and teardown; a swap
inventory change is a failure. It does not benchmark matched-load
lower-device amplification and does not establish production safety.
CI rootless checks verify the entry point but intentionally **do not
load any kernel module on hosted runners**. A host without sudo,
configfs null_blk or valid matching headers is BLOCKED. Users must
never replace missing RAM devices with physical or current swap.


### Owned null_blk configfs-name qualification

Configfs can expose a custom disk name, unlike the historical /dev/nullbN convention. The deployer must fail closed on ambiguous kernel disk names, verify the actual null_blk major and configfs index/minor against the chosen device node, check the node's real rdev and ensure no mounted or active-swap alias. The current script never creates a fallback physical device, invokes swapoff/swapon or removes an unverified config. Rootless regressions and loaded qualification remain distinct.


### Rootless regression for null_blk configfs naming

The automated `make verify` suite invokes `tests/runtime/native/nullblk-identity-test.sh`. Using fake sysfs directories only, it verifies configfs-named and historical nullbN discovery, plus fail-closed ambiguous, missing and invalid identities. Discovery alone never authorizes device IO; the privileged harness separately checks null_blk driver major, index/minor and real block node identity. A subsequent user-supplied Linux 7.0.0-38-generic run at source 68ac4c63 confirmed successful configfs-based owned device discovery, loaded V3 128-page overwrite/flush/full readback, and safe teardown of that *new* device. See benchmark.md for the exact counter scope; this result does not demonstrate an I/O reduction.

### Linux 7.0.0-38 loaded PASS and separately resolved older quarantine (2026-10-14)

The host log at exact source `68ac4c63c41adad911b0f788b38ae4f567087fd9`
reports **PASS** for an owned **64MiB RAM-backed null_blk**, unique
`SWAPZ-TEST-*` mapping UUID, 128-page C direct-I/O write/overwrite/
flush/full readback, and ordinary removal of that newly created
test mapping/device. Before/after `/proc/swaps` were identical
(`/swapfile` and `/dev/sda1`); neither was modified.
Native C regressions, 28 V3 source tests and three replay contract
tests had already passed before the privileged phase. This is a
**loaded bounded correctness test**, not a matched load, GC rotation,
device-originated fault or performance qualification.

**Earlier quarantine resolved by explicit owner verification:** the
user subsequently inspected the separate 64MiB RAM-backed configfs
device `swapzefb107e5be14c186` (index 0, memory_backed=1,
power=1), confirmed no block holders or Device Mapper targets,
checked major:minor, mounts, active swap and open users, and
reported `PASS: old RAM-backed test configuration removed` after
power-off and configfs removal. The `/swapfile` and `/dev/sda1`
swap entries remained unchanged. This was a **separately verified
cleanup**, NOT a result of the newer harness cleanup or a blanket
permission to delete similar names. Keep the read-only identity,
holders and active-swap checks before any future device teardown.

## Exact-zero write-path regression (2026-10-14)

The V3 `make test-mapping` group now includes the native
`zero-write-elision` executable compiling the **actual engine and
authority C**. It verifies full-byte zero recognition, nonzero at
start/middle/end, RAW-to-zero-to-nonzero generation transitions,
physical liveness retirement, in-flight refusal and overflow fail
closed. An additional source contract checks that the production
`dm-target.c` path drains prior writes, invalidates via
`sv3_discard_page`, maintains FUA flushing and counts only
successfully acknowledged elisions. The host's C roundtrip oracle
will additionally overwrite multiple pages with exact zero to
validate loaded readback and O_SYNC/flush behavior.

**Qualification status:** the native test and kernel W=1/W=2 builds
must pass at the new SHA. An actual loaded post-change run and a
matched off-versus-V3 two-arm trace with real lower counters remain
**NOT RUN** until the owner runs the safe isolated host command.
A zero-write optimization cannot be credited as a generic 50% LZ4
packing win; incompressible/random and nonzero compressible pages
remain unchanged.

## Loaded V3 zero-elision oracle and host evidence — October 14, 2026

The user loaded new V3 source `4c6e29b848a7f3327c1637a7f8fd234b60b840e8`
on Linux `7.0.0-38-generic` after successful native C, 29
source tests and three rootless replay tests. Its 128-page C oracle
passed overwrite, direct readback, FUA/flush, and clean owned null_blk
teardown; active swap inventory remained unchanged. Target stats:
`logical_write=786432`, `zero_elided=9`,
`physical_write=749568`, `physical_write_reqs=183`, 119 nonzero
compressed windows all singleton, 64 RAW, no GC rotations or errors.
The independent 64MiB lower `null_blk` confirmed **183 writes and
1,464 512B sectors**. This confirms 36 KiB lower-write saving
**within the synchronous smoke's logical 192-write workload**, not
a matched off/V3 throughput performance comparison. See
[benchmark.md](benchmark.md) for complete read counters and caveats.

The isolated deployment script's next release now snapshots independent
lower request/sector counters **before and after** the oracle and
rejects a run if its expected nine zero pages are not actually
accounted for, if completed target writes exceed uncompressed logical
write bytes minus zero elisions, or if completed target bytes disagree
with independent lower bytes. The comparison tolerates block-layer
request merging/splitting; actual write **requests are still recorded
separately**. These checks are test-scope-specific, not generic
hardware endurance claims. Rootless CI validates script syntax and
source contracts; host rerun of this tighter gate is **NOT RUN**.

### New regression guard CI wiring

The first zero-write lower-sector regression guard commit
`54e09ebe` passed native C, V3 W=1/W=2 compilation and source
qualifications but failed `make verify` because a new Makefile
literal-variable source check used `$DMNAME` rather than escaped
`$$DMNAME` in the Make recipe. The check expected a shell variable,
but Make consumed a single-dollar variable reference before `grep`.
This was an **automation assertion defect**, not a kernel failure.
The source-guard pattern was corrected without weakening owned
device cleanup, byte-exact readback or nine-zero-write validation.

### Exact-head regression guard and same-commit policy repair

At `73a440c4`, the rootless `make verify` checks passed, including
the updated literal `dmsetup remove` source check, but the repository's
**same-commit standards co-change gate** correctly rejected the
Makefile-only fix. The static source gate uses a literal teardown
command substring (no Make-dollar interpolation) while the **runtime**
privileged harness still verifies exact owned UUID, major:minor, holder,
mount, swap and module identity before ordinary teardown. The V3
deployment preflight now also statically checks that the loaded test
requires exactly **nine** zero-page elisions and that the independent
lower WRITE-sector delta equals V3's completed lower-write bytes.
The actual numerical check is **not executed in hosted CI**, which does
not create/load null_blk mappings. This note and Makefile additions
restore same-commit policy compliance without relaxing safety or
claiming a new performance win.

## Source-contract ownership after documentation moves

The active V3 version contract must read the canonical root `README.md`
and compare its advertised revision to the actual
`kernel/extent-v3/VERSION` and production `SV3_ALPHA_VERSION`.
Do not require an archived goals document, or recreate a removed root
`V3_GOALS.md`, to make source qualification green. Path-filtered kernel CI
must watch the active `docs/ROADMAP.md`, not the former root location.
A documentation move also requires checking Python module-import paths
and CI path filters: a missing file can prevent *all* source tests from
running even when the independently compiled native C suites pass.
This regression was exposed by exact-C and project-goals runs at
`57ad2c78`; its remedy is a source/test routing correction, not a
change to validated kernel behavior or a claim of loaded qualification.

## Replaying only on exactly owned modern/legacy null_blk

The off/V3 immutable replay's `--owned-nullblk-name` is the owned
`nullb-swapz-<16 lowercase hexadecimal>` **configfs** name.
The kernel disk may have that name or legacy `nullb<index>`; the
replayer must independently resolve **exactly one**, then check the
configfs memory/power/index, registered nullb major, lower major:minor,
canonical sysfs/dev/block identity, exclusive DM dependency, mapping
UUID, mounts and swap exclusions. Reject missing/ambiguous identities.
Report lower I/O using the *resolved disk*, not an assumed configfs
pathname. Revalidate the actual opened file descriptor before writes
to guard against node replacement after pathname preflight.

This is a safety-gate repair for Stage 2, not a kernel data-path
optimization. The rootless mock-sysfs test exercises modern/legacy
acceptance and rejection on ambiguity, wrong major/minor, unsafe
naming, non-RAM config and index aliases. No loaded paired
off/V3 replay, actual physical-media improvement or release
readiness is claimed.

### Rootless fixture notation is part of the admission gate

The first exact-head CI run at `e72d72a7` failed before exercising
the new owned-nullblk identity checks: its temporary fake sysfs
attributes contained literal backslash-n instead of newline
terminators. Native production-C suites passed independently.
The test fixture now emits genuine newline-terminated index,
memory_backed, power, devices, and disk-dev data; the source safety
checks themselves were not weakened. Re-run both source contract and
rootless replay tests at the final exact head.

## V3 table and matched-load replay source contracts

An owned replay must validate the *entire single* V3 DM table,
including exact geometry, backed block identity, bounded read budget,
window, GC/coalescing/bulk settings, and **zero diagnostic
lower-write/flush fault injection**. The target's table format is
`<start> <length> swapz3 <owned backing> <8 numeric settings>`.
Its backing may be reported as pinned `major:minor` or the exact
verified `/dev/<owned kernel disk>`. Reject arbitrary /dev paths,
wrong block rdev, malformed/multiple tables and unsafe settings.
The source uses `dm-target.c`'s existing emitted policy and does not
change its runtime ABI.

Pairing tests must prove identical operations and final oracle while
also rejecting missing lower-device counters, mixed rootless/loaded
arms, duplicate backing identities or source SHA mismatch.
Record mismatched achieved rates explicitly as **INCONCLUSIVE**
rather than treating exact logical bytes as a performance win.
The current declared achieved-rate closeness is at most 5%.
These are rootless CI acceptance gates, **not a completed loaded
off/V3 experiment or new V3 production-kernel behavior**.

## Isolated paired host-pilot safety contract

The opt-in `bench-pair` target first executes `verify` and
kernel W=1/W=2 before running the privileged benchmark, and is
not part of default/run/deploy. The benchmark must create two
separately owned unique RAM configfs null_blk lowers, verify
registered major/index, rdev, size, memory backing, mount/holders,
active swap exclusion and an exact V3 DM UUID/dependency. The replay
UUID check now requires the newly owned `SWAPZ-TEST-<16hex>`.
A test-owned mapping is removed normally before its lowers and
module. Partial setup or changed ownership is quarantined instead
of force-removed. A rootless opt-in regression checks that help and
invalid/no flag execute without provisioning. No loaded-pair success
or host I/O win is claimed until actual owner-host evidence arrives.

### First exact-head owned-pair script repair

CI at `e63ea33c` passed the exact production-C and kernel compile
jobs, but failed `make verify`: the shell cleanup conditional split
`!=` across a newline, which Bash rejects at execution. The fix keeps
the full ownership predicate and adds a `READY_COUNT` to quarantine a
two-device **partial** setup without dereferencing unset arrays under
`set -u`. It checks the host's swap inventory **before** teardown,
quarantining all resources if it changed, not afterward only.
These guards are rootless source/syntax qualifications, not loaded
device cleanup evidence. Preserve that failed CI run.

## Alpha.9 exact close-reason telemetry and semantics

Count one primary closing cause per **nonempty**
`sv3_flush_window()`, including a failed physical commit. An empty
flush increments neither `windows` nor close counts and clears any
stale provisional reason. The serialized worker assigns capacity,
duplicate logical WRITE, zero-write fence, FUA, nonbulk RAW fallback,
READ conflict/independent, DISCARD, PREFLUSH, worker quantum/idle,
shutdown, unknown/other. `window_gc_pressure` separately counts
ENOSPC retry encounters, and must **not** be summed with closure
causes. Status fields are cumulative worker-written diagnostic
counters; sample quiescent targets for conservation.

Rootless source regression must assert actual flush remains present
at nonwrite and worker boundaries, and check all close assignments
and status fields. Kernel W=1/W=2 and loaded owner-host exact byte
oracle, null_blk backing counter reconciliation and
`sum(close_*) == windows` remain mandatory. Do not infer any
scheduling win from telemetry alone. Existing active behavior and
alpha.8 negative unrelated-read bypass are unchanged.
**Loaded alpha.9: NOT RUN.**

### Alpha.9 deployed oracle must conserve close reasons

The owned and unchanged `make run` C roundtrip oracle now takes
**before/after** deltas for all 14 primary `close_*` counters,
asserts their sum equals the `windows` delta, and prints
`PASS_WINDOW_CLOSE_REASONS` together with the separate GC
pressure delta. Zero-value causes are allowed; a missing status
field, negative counter delta or missing closure fails this exact
loaded gate. This validates telemetry accounting only; it does
not authorize cross-worker retention or replace byte-exact,
independent lower I/O acceptance. The source and shell contracts
run in CI; alpha.9 loaded test remains **NOT RUN**.

## Alpha.9 two-extra-lower-read failure and bounded paired counters

The owner-loaded exact `make run` at `a7e5ad69` passed byte-exact
128-page I/O and 119/119 FUA close-reason accounting, but failed
independent lower READ accounting by **two 4KiB reads (8,192 B)**.
Host-local evidence is `build/deploy/session.TlILja3J/session.log`.
Origin is **not established**; never discount those reads merely
because they might come from asynchronous udev/device probing or a
status/stat race.

A new sourceable synchronous counter helper accepts only two
unchanged full target-status and independently owned backing-stat
samples, 200ms apart, before and after the oracle; retry at most
12 times. A changing/missing status, incomplete stat or unsettled
udev is BLOCKED. This improves measurement boundary provenance but
does **not** prove isolation during the measured I/O. Keep strict
target/completed versus device sector equality: no error tolerance.
Primary `close_*` conservation must run even when read accounting
subsequently fails. Test the counter helper rootlessly with fake
V3 status, fake stat, transiently changing read sectors, and invalid
inputs; no real devices, sudo or module needed. Quiescence output is
owned by one serialized shell caller, not concurrency-safe.
The new loaded retest is **NOT RUN**. Keep version alpha.9: only
test harness code changes, no new kernel data-path experiment.

## Alpha.10 worker-window open age is not physical write latency

The serialized production-C worker now timestamps the FIRST accepted
compressed or staged RAW write in an empty window, and at the
beginning of each nonempty `sv3_flush_window()` captures elapsed
monotonic nanoseconds BEFORE planning, lower I/O, verification, FUA,
or GC. Exactly one bucket <=100us, 101..1000us, >1000us must be
incremented per nonempty window. No count may be added by an empty
flush. Include `age_sum_ns` and `age_max_ns` as diagnostic,
not proof of CPU or BIO completion time. First admission must not
be refreshed by later writes. No worker schedule or completion
semantics are changed. The owned `make run` harness now checks
`sum(age bucket deltas) == windows delta` as well as primary
close-reason conservation. Unit/source and Kbuild W=1/W=2
qualification are separate from the **NOT RUN alpha.10 loaded gate**.

## Opt-in medium fixture and owned paired replay qualification

The medium profile is an explicitly synthetic **nonzero**, deterministically
seeded 4KiB page with 2040 high-entropy bytes and remaining zeros.
On the evaluation host measure all 128 pages using actual liblz4
`LZ4_compress_fast` (not an inferred ratio or fixture label);
each must produce a payload between 2049 and 2200 bytes, no RAW
fallback and no exact-zero pages. Its manifest must prove the range
before using the two separate preflighted RAM-backed devices.
A rootless regression confirms deterministic bytes, actual per-page
lz4 sizes and unchanged default profile. Only the exact opt-in
`--run-owned-ram-pair --profile medium` may select the alternative.
The existing default pilot and `make run` must not change.

Preserve matched offered/achieved rates, independent lower READ/WRITE
request/byte delta, original immutable trace and complete final
readback, and exact UUID ownership and ordinary/quarantined teardown.
This is a feasibility pilot at QD8: host loaded **NOT RUN**.

### Qualification correction — extremes, not only average

Do **not** qualify `medium` data from a histogram bucket plus a mean
alone: one over-large page can hide behind smaller peers. The
manifest now retains independently measured `lz4_min_accepted_payload_bytes`
and `lz4_max_accepted_payload_bytes` (null only when no pages
compress), and the owned host harness requires the **minimum >= 2049**
and **maximum <= 2200** before permitting replay. This is a
fixture-integrity check, not loaded I/O evidence. The broad
2,049..3,072 size-bin classification remains diagnostic, not
sufficient for medium acceptance.

## Alpha.11 opt-in serialized window retention (kernel C)

The medium loaded pilot at alpha.10 exposes 1,957 / 1,961 idle
closures and almost no real lower-write byte savings. To test
whether idle closure is avoidable, the experimental target now
accepts a **final optional** `retain_ms=0..4` DM table parameter,
default **0** (the original flush behavior). Positive opt-in
retains already staged immutable upper BIOs across worker invocations
at most until the **absolute** first-record deadline, never resetting
the timestamp when additional writes arrive. A delayed worker is
armed under the same queue/admission lock and wakes even if no
new BIO arrives. Expiry is checked before every newly processed
BIO and at worker boundaries. A pending full window drains; a
READ, duplicate, exact zero, FUA/PREFLUSH, discard or unsupported
operation retains its original conservative flush/ordering behavior.
Presuspend closes admission, expedites delayed work, drains every
accepted BIO and issues the original lower flush; no new
publication, GC ownership or on-media states are introduced.

The timer is **bounded in jiffies and subject to kernel scheduler
latency**: `retain_ms=2` is a nominal window budget, not a
real-time upper-BIO service-level guarantee. A QD1 synchronous
issuer may gain nothing and experience additional wait. Diagnostic
`close_deadline` is one primary cause in conservation;
`retain_passes`, `retain_timer_arms` are not closure counts.
Rootless source-contract checks cover deadline, hard capacity,
quiescent timer rearm, urgent admission and drain. This does not
substitute for loaded dependent-read/overwrite/FUA/GC/suspend/fault
tests or a same-source opt-in/control comparison. **Host alpha.11
loaded: NOT RUN.** Keep `retain_ms=0` as default.
