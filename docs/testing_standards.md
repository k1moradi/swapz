# Testing Standards

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

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. This single public entry point runs native production-C/source/safety checks, W=1/W=2 builds, owned RAM-backed loaded correctness, and counterbalanced off/swapz throughput trials. It must report BLOCKED (nonzero) when noninteractive administrator permission or safe isolated devices are unavailable, never skip required loaded work while claiming a full PASS. **Do not create, publish, recommend, or document alternative test commands** (including additional Make goals, directly executed test scripts, one-off Python test invocations, and manually invoked loaded-device or benchmark helpers). Private implementation scripts/sub-Make targets and CI jobs may orchestrate individual stages internally, but are not supported operator interfaces; rootless-only CI success is explicitly partial.


## Non-negotiable owner Make API

**Exactly four public root Make commands, with no exceptions or aliases:**
`make` builds the V3 kernel module and supported safe binary in
parallel; `make install` installs its versioned DKMS package and binary
to appropriate system locations, without loading or activating swap;
`make uninstall` reverses only that owned installation; and
`make test` runs native C, source/fixture/safety contracts,
W=1/W=2 kernel compilation, **then actual loaded owned-RAM smoke and
counterbalanced rate-limited off/swapz benchmark pairs**. No interactive
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


**Current testing policy.** Read [README](README.md), [VISION](VISION.md), [coding_standards.md](coding_standards.md), [compile.md](compile.md), and [benchmark.md](benchmark.md) at the **start of every agent task**. Tests must prove correctness on actual source, expose false completions and regressions, and ultimately support the project's **real lower-I/O** objective—not maximize test counts.

Current actionable V3 gaps belong in [the roadmap's open work queue](ROADMAP.md);
historical validation transcripts belong in the archive indexed by
[coding/documentation governance](coding_standards.md), not in the standards or task list.

## Future physical `/dev/sdb1` trial (blocked pending new authorization)

A dedicated physical-device trial is a legitimate **later release gate**,
not an operation authorized by historic documents. V3's current
`null_blk`-only guard must stay in place. Before changing it,
require an independently reviewed source/host procedure, an exact new
device identity and ownership check (major/minor, all aliases,
active-swap/mount/holder state), full backups and explicit acceptance
of destructive data loss, separate owner authorization for the exact
device and operations, bounded fault/flush/suspend/GC testing,
byte-exact readback and true lower READ/WRITE request/byte metrics,
safe normal teardown and resource quarantine on ambiguity.
Do **not** attempt system swap activation, force-removal, reboot or
physical-device I/O as a substitute for missing owned-RAM evidence.
Until all gates pass: **PHYSICAL TEST BLOCKED**.

## Exact release-version qualification

The rootless source-contract regression requires the README to link to
`src/kernel/VERSION` rather than duplicate an alpha literal.
Additional tests prove the generated kernel version header and module
change when VERSION changes, DKMS resolves its installed VERSION,
and both privileged owned-RAM helpers compare `modinfo -F version`
to the canonical source before any device access. This is a version
consistency gate, **not** permission to load onto physical media.

## Current retained lifecycle contract

Before retained/concurrent preparation can advance toward a default, the
single `make test` loaded phase must carry four sanitized owned-RAM
correctness markers. The deterministic oracle must report exactly 64 RAW
fallback writes, nine zero elisions and at least two successful explicit
flushes. A fresh mapper at the already-supported 4ms maximum retention
bound must expose an actually open timed window
(`retain_timer_arms > windows`) under a private `O_DIRECT`, non-FUA
writer, then ordinary suspend/resume must increase `close_shutdown` and
the helper must verify all 128 pages. Separately recreated retain=2
mappings must pass the existing pre-submission WRITE and FLUSH fault
contracts.

The 4ms lifecycle setting exists only to make the open-window drain race
observable. It does not change the owner-qualified 2ms benchmark policy.
Cleanup may resume the exact owned mapper if the lifecycle command left it
known suspended, but must never force-remove it; UUID, holder or swap
identity ambiguity still quarantines the RAM resource. Synthetic injected
EIO is not device-originated failure evidence. The sanitized reporter must
fail closed when any lifecycle marker is absent or inconsistent.

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

**Only one reusable compiled-output tree:** `~/swapz/build/`. Native tests link to **actual** `src/kernel/{codec,authority,engine}.c` and use semantic names, not newly duplicated version-number frameworks. From the checkout root the **only official test invocation** is:

~~~sh
make test
~~~

It owns all native suites, source and safety contracts, both warning-level
kernel builds, loaded owned-RAM oracle and eight paired RAM-backed
benchmark trials (four per synthetic latency model: slow and faster).
The former uncapped and bandwidth-only reference rows remain in
Git history, not in the mandatory device setup path.
There are no supported per-suite test commands or separate benchmark
entry points. Internal native Make rules remain private implementations.

There are **16 behavior-named native C executables** in `build/tests/native/`: `codec-roundtrip`; `mapping-authority`; `transaction-publication`; `write-verification`; `dead-segment-reclamation`; `raw-discard`; `online-packing`; `randomized-authority`; `gc-forbidden-victim`; `gc-cost-accounting`; `gc-rotation`; `gc-engine-rotation`; `flush-ordering`; `lower-write-aggregation`; `zero-write-elision`; `window-policy`. Current V3 test source names reflect behavior in `tests/runtime/native/{codec,mapping,gc,io}/`, without deleting native assertions. Historical v22/host scripts are retained until CI dependency parity is established. One declarative rule in `tests/suites/Makefile` replaces 14 nearly identical C compile recipes. Python helpers must be bounded/necessary and should not replace actual C tests. For sanitizers, use the applicable `SANITIZE=1` native test target and independent ASan/UBSan/Clang gates described in [compile.md](compile.md).

## Parallel build/incremental-regression gate

The `make test -j2` variant of the *same official test command* may run
independent production-C, userspace and Kbuild compile jobs in parallel,
but its rootless, W=1, W=2 and loaded-device phases must be strictly
ordered and fail fast. Loaded smoke must finish before any benchmark,
and eight counterbalanced benchmark sessions must not overlap. The
kernel Makefile stages source only when content changes, and W=1/W=2
use independent `build/kernel/w1/` and `build/kernel/w2/` outputs,
never overwriting the default module eligible for loaded testing.

`tests/runtime/native/make-interface-test.py` includes an unprivileged,
isolated **fake-Kbuild regression** under `build/tests/` that invokes
the actual root Makefile with `-j2`. It confirms phase order, reuse of
module/user binaries on a second unchanged run, selective helper
recompilation after a helper-only edit, and selective kernel
restaging/rebuild after a kernel-only edit. This proves build graph
and mock orchestration only: no module is loaded and no throughput is
measured by that test. CI must label its result rootless/partial.

The counterbalanced run schedule is synchronous/asynchronous/
asynchronous/synchronous, so overlap counters are required only for
the middle two async runs; never demand async overlap from either
synchronous control run.

**Shell/Python heredoc boundary:** When wrapping the benchmark's fixture
validator inside a Bash `if`/`else`, leave the `PY` terminator
at column zero and keep the embedded Python script's top-level
statements unindented. Adding a shared-fixture path must not silently
break the legacy standalone internal fallback; private rootless Bash
syntax/preflight checks still cover both branches.

**Regression maintenance note:** After moving the serial test-phase
commands into `tests/tools/run-tests.py`, Make API tests must look for those
commands in the runner, not directly in the root Makefile. The Makefile
continues to expose only the public `make test` entry point.

## Paired modeled RAM I/O: qualification and timing

The rootless fail-context test must use the current global pair
denominator, eight; a stale denominator is a regression test failure,
not evidence that any loaded device test failed.

The single official `make test` runs **eight owned-RAM pairs**:
four `sd_emulated` at 10 MiB/s / 1 ms completion and four
`ssd_emulated` at 80 MiB/s / 0.15 ms completion. These are synthetic
`null_blk memory_backed=1` models, **not** performance or safety
claims for actual SD/SSD hardware. Counterbalance sync/async as
`0,1,1,0` and order raw/swapz as `off,v3,off,v3`. Two paired
observations per preparation mode and model preserve bounded replication.

The earlier four-regime 16-pair matrix was an exploratory control and
is retained as source-identified results in Git history. Removing
its bandwidth-only and uncapped diagnostic pairs from the mandatory
test decreases isolated device setup/teardown and maintenance without
reducing per-model replication. Do not substitute cached or unowned
block devices for the eight freshly owned RAM-backed pairs.

Only private model tuples `(10,2,1000000)` and `(80,2,150000)`
are allowed (MiB/s, irqmode, completion delay in ns). Reject any other
flag combinations **before** privileged provisioning. Configure and
read back the exact `mbps`, `irqmode`, `completion_nsec` and
`memory_backed` identity **before and after power-on**; fail
BLOCKED on unsupported kernel features. Verify independent device
identity, absence from host swap/mounts, unchanged swap inventory,
safe teardown/quarantine and one exact shared fixture and trace.
Each raw/swapz pair must carry `source_sha`, `fixture_sha256` and
`trace_sha256` on **both** arm records, and every field must match within
the pair before aggregation. Missing or divergent arm provenance is
INCONCLUSIVE; parser order must never overwrite one arm's identity and mask
a mismatch. Rootless report regressions must independently corrupt each
of the three arm fields and require an INCONCLUSIVE verdict. An existing
pair-level provenance field must also equal the value agreed by both arms;
validation must not silently normalize a tampered aggregate. Cross-pair/regime
provenance checks still apply after this per-pair gate. Actual physical media,
existing SD swap and
`swapon`/`swapoff` remain prohibited.

**Measured I/O boundaries:**

- Mixed-write throughput begins only after fixture verification,
  target prefill, initial read oracle, worker allocation and all
  warmup QD waves. It ends **after the last measured wave and
  required `fsync`**. Lower-device sector counters cover the same
  interval; later complete-image verification is outside the clock.
- For the independent 4MiB packed-read trial, concurrent read-set
  creation, final write drain, packed-close evidence, preallocation
  of read buffers and the whole QD32 worker pool occur **before**
  the read clock. Actual I/O submission/completion is timed,
  and individual read latency samples bracket `preadv` only.
  The byte oracle runs after each sample but before slot reuse;
  throughput still includes QD wave orchestration and oracle
  comparison, which is part of this Python load generator.
  Sampling counters, SHA, publishing and worker teardown occur
  after the interval.
- The replay process/threads CPU values explicitly exclude
  Device Mapper kernel workers. Timing is a user-space issuing
  experiment and **not** pure kernel, swap page-fault, NAND or
  endurance time; avoid claiming otherwise. Tested data remain
  a 4MiB RAM-backed working set, not a 100MiB cold read.

**Failure localization:** The private replay emits only static
`BENCH_IO_PHASE={off|v3}:{prefill|mixed|packed_read}` markers, not
private paths or device IDs. The host test runner reports the
modeled regime, indexed pair and last active read/write subphase
when an owned-device replay aborts. These markers are diagnostic
metadata, never I/O workload or timed operations.
The rootless replay-contract test executes those code paths and checks
that the diagnostic helper has its required imports; a marker must
never prevent the actual byte-exact replay from running. The
fault-localization test must independently assert the previous
general comparison failure and the later read-specific failure;
neither synthetic result can silently overwrite another assertion.

**Test structure:** Preserve separate functional components for
production-C native oracles, Make/Kbuild/API source contracts,
rootless paired-result/report contracts, and safely loaded devices.
Remove the former `tests/runtime/benchmark/owned-pair-preflight-test.sh`
because its argument denial and ownership/teardown assertions are
now enforced by `tests/runtime/native/test-report-test.py` and
the other native/source contracts. No unrelated native safety tests
were removed. This avoids a duplicate shell process matrix while
keeping fail-closed model validation in CI.

An incomplete ABBA pair, mismatched SHA/model tuple, missing packed
read, physical-device identity or changed swap inventory must never
be promoted to PASS. Distinguish correctness PASS from separate
positive/negative performance findings. A 5% materiality threshold
with only two pairs per mode is exploratory, not a confidence interval.
No observed GC means GC remains NOT EXERCISED. The owner's next
`make test -j2` must generate new loaded evidence; rootless CI is
not a substitute.

## Accepted-backlog and accepted-burst packing contract

A first valid 2/3-record pack may be retained for a second pack only
from worker-local work that was already admitted before the current
decision. The worker snapshots `entry->list.next != &local` before
removing the current local-list entry. A later concurrent admission must
never retroactively justify retention. The owner-qualified
plain-WRITE-only successor experiment at `b4d828d` reduced useful
aggregation and is rejected; do not preserve that failed policy merely
as a source-cleanliness preference.

After the existing 4/6-record second-pack geometry is reached, the
worker may keep the window open only while entries remain in that same
finite local snapshot. This is **not additional retention**: at the
snapshot tail, if the window still exists, admission is open, no error
occurred and the original absolute deadline has not expired, the worker
must set the ordinary PACK_READY close reason and synchronously flush
before resetting the local-follow-up snapshot. Any existing boundary
encountered while walking the accepted burst retains its original drain
and clears the extension state through `swapz_flush_window`.

Owner qualification at `ed2ea3d` showed that unconstrained replanning
of these larger windows reduced WRITE requests but caused a material
packed-READ regression through denser 16KiB layouts. Owner-qualified
`c60f24a` then showed that a planning-only cap of two cold 4KiB blocks
per record restores the read side while preserving the accepted-burst
request/wait gain. This temporary planning argument must not mutate
`engine.max_read_blocks_per_record`; runtime reads and explicit target
budgets retain their original semantics.

The capped batched engine must preserve all ordinary validation,
committed-prefix failure behavior, batch pause/resume, lower-run
aggregation, no-padding default and post-success publication. Exact-C
coverage compares the same sixteen 2072-byte records: uncapped planning
must retain its 10-block/four-block-extent control, while cap=2 uses
11 blocks, maps every record to <=2 blocks, still aggregates lower runs
and verifies exact readback. An invalid planning cap must fail before
staging. Source/report contracts require
`accepted_burst_read_caps <= accepted_burst_extensions`.

The rejected cap=3/uncapped planner-stat experiment is closed. Production
must not re-run alternative planners merely for telemetry, and status/reports
must not carry the retired cap-extra, four-extent, planner-failure or cap=3
diagnostic counters. The active write still uses the owner-qualified cap=2
for accepted-burst extensions; removing the probes changes CPU work only,
not on-media layout, lower I/O, authority or completion semantics.
Exact-C coverage must exercise the retained cap=2 planner and write/read authority, not preserve tests for the deleted diagnostic classifier.

Owner-loaded `2619385c` selected 64 metadata entries, and
owner-loaded `8e21ca7e` proved the resulting 256KiB metadata-only LRU.
The production read cache remains exactly 64 validated 4KiB block-zero
slots plus the existing one-extent `read_scratch` fast path. It must not
cache payload blocks or suppress required payload I/O. Every logical read
still executes `swapz_peek`, authority/generation/offset/length checks and
payload CRC validation.

The current production-C read path reuses the descriptor already returned
by that successful `swapz_peek` after fetching any missing payload blocks.
`swapz_read_authoritative_peeked` must recheck current volatile authority,
the on-media sequence and payload bounds, then verify payload CRC before
returning bytes; it must not call `swapz_lookup` or re-run metadata
validation over the same worker-owned block-zero scratch. Exact-C coverage
corrupts payload bytes after a successful peek, forges the decoded generation
and mutates the sequence, requiring fail-closed rejection in every case.
This is a CPU-path optimization only: lower READ request/byte geometry,
cache size and mapping publication are unchanged. Owner-loaded `make test`
at this source is **NOT RUN**.

Owner-loaded `be84880c` (report-only `df8ae7d2`) rejected the
same-memory 64-physical-block alternative: random predicted miss-block
traffic was 1.4-2.1% higher than the retained metadata-cache traffic, with
only 0.6-1.4% predicted request-run savings. Owner-loaded `cc2da694`
(report-only `c95e1d4a`) rejected the 512KiB companion-block design:
predicted random byte savings were 2.86/2.86% SD and 3.36/2.86% SSD,
while request savings were 4.47/4.50% and 5.13/4.38%. Both predeclared
>=5% byte-and-request gates failed. The reuse-distance, physical-block and
companion-block identity probes are therefore retired from production C,
status, timed-read schema and rootless fixtures after their decisions.
Do not pay hot-path diagnostic scan cost after a direction is closed.

Cache residency must still be cleared by
`swapz_engine_invalidate_read_cache()` on every existing
write/GC/discard/barrier fence. A failed, stale or corrupt read must not
insert/touch a slot or increment `read_meta_lru_hits`. Exact-C coverage
must prove reuse beyond one entry saves a real lower metadata read,
explicit invalidation restores the lower read, and overwrite cannot return
an old generation. Timed reports retain the real metadata/payload callback
counters, one-entry/LRU hits, full-extent reuse, 4KiB skip counters and
independent lower-device bytes/requests.
Do not repurpose `raw_crc32c` for a compressed fast path without an
explicit integrity-contract change. Raw pages have no on-media metadata;
compressed pages do, and current reads validate its CRC and sequence every
time. Payload CRC equality alone is not equivalent.

Owner-loaded `cc2da694` shows the QD32 singleton population is
deadline-dominated, not zero-page dominated. Before any retention-policy
change, source/status/report contracts must carry the four mutually
exclusive deadline discovery counters: `deadline_before_bio`,
`deadline_after_read`, `deadline_worker_with_local`, and
`deadline_worker_empty`. Their per-session deltas must sum exactly to
`close_deadline`; synthetic report fixtures must include both a valid
conservation case and a mismatched failure case. These counters are
diagnostic-only and must not move or extend the absolute retention
deadline.

Owner-loaded `9eafe9ea` then showed zero worker-local deadline closures
in both modeled regimes, effectively zero before-BIO closures, and
worker-empty dominance; a longer retention interval is therefore not
authorized by this workload. The next write-only pilot must remain under
the one official `make test` command and may use only owned RAM-backed
`null_blk`. It must generate exact QD1/4/8/32 immutable 0%-read traces,
run sync and async raw/swapz pairs separately under both existing model
tuples, omit packed-read work, preserve the ordinary final-image oracle,
and publish independent lower WRITE bytes/requests plus WRITE p99. The
pilot has one pair per mode/QD and must label confidence NOT ESTABLISHED;
the existing >=5-pair confirmatory requirement remains open.

For loaded fault qualification, the owned null_blk smoke may use only the
target's existing **pre-submission** test hooks. A retained WRITE-fault
phase must recreate the owned DM target with `test_fail_write_nth=1` and
`retain_ms=2`, observe one injected failure plus target fail-close, and
independently prove that lower WRITE requests/sectors did not advance. A
separate retained FLUSH-fault phase must recreate the target with
`test_fail_flush_nth=1`, complete a nonzero lower data WRITE, then
observe the injected flush error and target fail-close. Recreate the DM
mapping between phases so counters and failure state cannot leak. These
tests are protocol/fail-close evidence only: device-originated, partial,
torn, and media-failure coverage remains explicitly unqualified, and the
legacy loop/error-device fault scripts must not be invoked by `make test`.

For WRITE closure analysis, the status/report layer must carry all sixteen
`window_close_reasons` deltas and fail closed unless their sum equals
`windows`. For singleton analysis, `swapz_flush_window()` must increment
exactly one `one_page_close_reasons[reason]` entry whenever `count == 1`;
those deltas must sum to `one_page_windows`. Rootless synthetic fixtures must exercise both the
valid joint singleton sum and a mismatched failure case. Source contracts
must assert the captured `close_reason` index rather than the mutable
`next_window_close` expression, because the latter is deliberately reset
immediately after the legacy close-reason counter is charged.

The first exact-head native CI for the rejected policy failed before
runtime because the bounded uint16 subtraction was compared with unsigned
literal `1U`, producing `-Wsign-compare` under `-Werror`. Keep the
prior greater-than guard and compare the promoted difference with signed
literal `1`; do not hide the warning with a cast. The three replacement
cap=3 probe counters are mandatory through status parsing, per-session
deltas and per-regime summary output; synthetic report fixtures must
exercise the same relationships so schema drift fails before owner-loaded
qualification. The human-readable benchmark table places units in each
metric label once and keeps all three result cells numeric; rootless report
tests pin this presentation without changing machine-readable units. For sixteen uniform 2072-byte
records, the uncapped planner's existing read-cost tie-break selects
3+3+3+7 records; tests must not replace that with the byte-equivalent
7+7+2 shape merely to reduce extent count. Every newly mandatory status field must also be present
in the per-session counter-delta dictionary before any invariant indexes
it; a parser that validates a field and then omits it from the delta
schema is a qualification failure, not an optional diagnostic omission.
The per-regime diagnostic-mean dictionary must carry the same mandatory
planner fields whenever user-visible reporting indexes them; summary
propagation is part of the strict schema rather than an optional view.
The synthetic report fixture must exercise all mandatory planner counters
through the normal verdict path so such schema drift fails rootless CI
before an owner-loaded run. Loaded performance qualification remains
separate from these diagnostic safety contracts.

## Alpha.22 packed-burst tail correctness contract

After a successful pack-ready window, the serialized C worker may drain
a one/two-record compressed tail at a genuine accepted-queue idle point.
Eligibility requires positive retention, unrestricted read budget, valid
non-RAW lengths and distinct slots. The worker must splice any unfinished
local list ahead of incoming and test emptiness under the admission lock.
Release that lock before the ordinary flush path, which synchronously
cancels its timer and preserves lower-success publication/completion.
New BIOs arriving after the decision remain queued for the same worker.

The worker alone owns `packed_burst`. Clear it on every flush entry,
including empty fences; enable it only after complete error-free
pack-ready commit. Partial/failed writes never enable it. Clear at
empty-queue/no-batch idle, preserve across nonclosing worker requeues
and independent READ bypass, and do not double-complete the current
WRITE by returning an already-completed flush error from accept_write.
`burst_tail_flushes` is an attempted-close diagnostic; its windows
are already counted by `close_idle`, not a new primary close reason.

Direct production-header regressions cover positive/negative tail
geometry, disabled/no-history/restricted-read cases, invalid/RAW records
and duplicates. Source contracts check success-gated history, FIFO
splicing, healthy/open admission, unlock-before-flush, timer ordering
and status. Predicate regressions do not execute Linux BIO callbacks
or prove suspend/failure behavior. Loaded follow-up needs
finite-QD bursts, delayed arrivals, initial singleton writes, true
fences, same-page overwrites, independent reads, mixed RAW, WRITE
failure, GC and suspend/drain with exactly-once upper completion.

**Alpha.22 native/source tests, compilation and loaded tests: NOT RUN
by explicit owner instruction.** Use only `make test` for operator
qualification. Its current capped mixed workload can exercise the new
path; the uncapped saturation, packed-read volume, CPU and live-GC
qualification proposed in [benchmark.md](benchmark.md#three-axis-qualification-specification)
remain planned. Do not claim those new stages ran. Retention stays
disabled by default and all device tests stay owned-RAM-null_blk-only.

## Latest-only compressed result and official terminal output

The private `tests/tools/run-tests.py` program invoked *only* by root
`make test` drives five strictly ordered stages: parallel compile
prerequisites, rootless native/source/safety contracts, W=1 kernel
build, W=2 kernel build, and privileged owned-RAM smoke plus eight
benchmark comparisons across two latency-modeled regimes. It replaces the same
`build/test_results.json.xz` file at the start and after each stage,
including on nonzero FAIL/BLOCKED. A failure aborts remaining stages
without silently claiming loaded success. The root Make API remains
exactly four goals; no new public runner is added.

**2026-10-15 loaded phase diagnostic/ownership regression:** The
privileged benchmark helper deliberately creates `build/benchmark/`
as root under `umask 077`, so it is **not writable by the unprivileged
runner**. Never allocate the shared fixture there. Allocate under
`build/tests/benchmark-plan.XXXXXXXX` (where rootless native test
outputs already belong), then have each privileged child copy the
verified immutable fixture into its own isolated and access-checked
session. Do not chmod or delete the root-owned benchmark directory,
or bypass safe device teardown, to work around EACCES. A rootless
regression protects the distinct ownership boundaries.

On nonzero stage exits the single report and terminal MUST include
a sanitized, concrete **failed subphase** (smoke, shared fixture
allocation, numbered pair) and a vetted actionable error category,
including missing permissions or the original `BLOCKED:` reason.
Only the privilege-dependent loaded stage may be classified BLOCKED:
an exit code 2 from build, native/rootless, W=1 or W=2 is a FAIL unless
the loaded stage emits a vetted BLOCKED marker. In particular, a native
assertion such as the `ee95492` planner-oracle failure must retain the
"Native and rootless contracts" phase and must never be relabeled as
"administrator authorization". Sanitized assertion text may be surfaced
without its source path. Never substitute "private stage failed" for a
diagnosable known failure, and never disclose full private paths, device
names, secrets or raw host swap inventories through the report. Path
redaction must consume a complete absolute path through its whitespace or
quote boundary without turning ordinary terms like lower I/O into misleading
output; rootless tests exercise both.

The human terminal displays numbered PASS/FAIL/BLOCKED stage statuses
and a table of raw-off, synchronous and asynchronous useful WRITE
throughput, backing WRITE rate, input/backing WRITE-byte ratio,
lower WRITE requests, READ MB/s, estimated 100 MB swap-in time,
and READ p99. The compressed JSON includes exact source SHA, stage
codes and durations and **sanitized** session aggregates. Raw JSON,
device paths, host swap inventories and authentication details stay
out of terminal and the publishable summary. Existing private evidence
logs remain under `build/` to permit safe audit.

**Git report provenance and history:** The local runner atomically
replaces `build/test_results.json.xz` on every run, including blocked
and failed runs. Only after completing all test stages does it attempt
to publish a sanitized copy as the single root-level tracked file
`test_results.json.xz` on `origin/main`. This one report is an explicit
exception to the `build/`-only generated-artifact convention; no
compiled binary escapes `build/`. A report-only Git commit preserves
each prior version in history, whereas the current file is always the
latest report. Git push/SSH credentials are reused; **no `gh`, GitHub
API token, force push, new branch or release asset** is required.

The Git exporter validates that both `tested_commit_sha` and
`source_sha` inside the compressed report equal the expected tested
parent commit **before** modifying any Git object. Synthetic negative
tests must supply matching IDs to exercise later guards (dirty tree,
wrong checkout), not bypass this provenance assertion.

The JSON records full `tested_commit_sha` and `source_sha` values for
the exact HEAD before loaded tests, and `code_commit_sha` for the latest
source-changing commit excluding only `test_results.json.xz`. Because
the report-only commit is created *after* the run, it is not falsely
labelled as the tested commit; its parent is the tested HEAD. The
publisher assembles the one-file commit with Git object plumbing and
fast-forward pushes it only when the checked-out branch is main,
the working tree/index is clean, origin is the expected GitHub repo,
and remote main still equals tested HEAD. It does **not** move local
HEAD/index or write into the checkout. The next normal fast-forward
pull catches up; if main has moved, Git syncing is skipped while the
local report remains intact. A report-only commit carries `[skip ci]`
to avoid repeatedly rerunning rootless CI. No interactive credential
request is allowed. No private logs, host swap identities, device
paths, authentication secrets or unsafe error text are committed.

The existing fake-Kbuild regression uses the **real Git checkout SHA**
in its *synthetic* loaded output rather than a placeholder identifier,
so it exercises the provenance check without misrepresenting that mock
as actual device or performance evidence. The policy assertion checks
Git plumbing and SHA fields, not the deleted `gh`/Release interface.

Tests in `test-report-test.py` exercise actual nonforce Git operations
against a local bare remote (the configured GitHub push-URL safety
check alone is mocked); they verify two report-only commits, the full
tested SHA, unchanged code, Git history, clean-checkout gating and
stale-head rejection without contacting GitHub. Fake Kbuild and
contract tests still prove rootless incremental builds, finite
compression, correct four-pair summarization and absent raw JSON
stdout. Git publication failure must never change the loaded test
PASS/FAIL/BLOCKED status or touch hardware.
Loaded RAM results, actual swap behavior and real physical endurance
are separate qualification levels; a mixed or negative performance
verdict is not a false correctness failure.

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

Owner-loaded bounded off/swapz pilots, including alpha.11 retention at `0a10cbfa`, have passed exact logical-input and readback gates; sustained GC/CPU/tail qualification remains open. Genuine device-originated read/write fault coverage is incomplete; kernel-worker CPU attribution, the historical extra backing WRITE request in 120 trials, and generic asynchronous Buffer I/O error attribution are unresolved. The alpha.8 READ-bypass matched-rate result was negative, notwithstanding exercised loaded correctness. Historical validation and review reports at [the preserved source revision](https://github.com/k1moradi/swapz/tree/abbdbce277938f3678a640af93ef066394b44606/docs) retain provenance, **not new test requirements**.

At the end of each implementation task, update this or another of the four standards with learned results, exact tests and PASS/FAIL/BLOCKED, while preserving separate versioned raw report evidence on `main`.

## Automated governance for the four standards

The `main` project-goal workflow checks that `AGENTS.md`,
`CLAUDE.md`, Copilot instructions, `CODEX_VALIDATION.md`,
`README.md` and `VISION.md` all reference the four governing standards.
A same-commit change to kernel, tests, userspace, Make/DKMS or CI workflow
paths must also modify at least one of `coding_standards.md`,
`testing_standards.md`, `compile.md` or `benchmark.md`. An unrelated
archival Markdown update cannot satisfy this gate. Documentation-only
changes do not require a separate implementation commit. This is a
mechanical check of **where the learning is recorded**, not a validator
of semantic truth, tested runtime behavior or external agent prompt
compliance.

## Historical VM smoke compatibility handoff

The V2.2 virtual smoke regression remains an active **rootless safety
contract**, not an authorized V2.2 deployment or V3 benchmark. The
dated operator document was removed during documentation cleanup while
the rootless `virtual-smoke-test.py` still requires its authorization,
32 MiB capacity, exact two-read and safe-teardown invariants. Restore
a concise **non-executable safety handoff** at
the historical V2.2 smoke compatibility handoff retained below rather than dropping assertions.
README alpha-version tests permit either the concise current V3 heading
or the older revision-heading phrase; both must match VERSION exactly.

## Experimental concurrent LZ4 producer correctness

The opt-in production C `async_prepare=1` producer uses one workqueue
separate from the ordered lower-I/O worker. Native source contracts
guard that the producer never calls `bio_endio`, `dm_io`, mapping
publication or GC; only the consumer waits for preparation completion,
recycles its buffer and completes the accepted upper BIO. A reserved
64-buffer mempool plus semaphore caps resident preparation memory.
The unchanged default is `async_prepare=0`.

Rootless preflight also rejects unsupported cap values, improper suffixes
and use of the experimental `--lower-mbps 20` on any profile other than
the explicitly authorized medium unpaced QD32 owned-RAM pair. On those
two owned null_blk instances, the harness validates the configfs
`mbps` attribute before activation and again after power-on. This
configuration alone is not independently measured saturation.

Run rootless contracts and W=1/W=2 builds first. Before promotion,
loaded RAM-only qualification must cover 65+ queued BIOs, same-page
overwrites, raw/zero/compressed mixes, independent/conflicting reads,
FUA/PREFLUSH, GC, injected WRITE error and repeated drain/teardown,
under memory pressure. Only then may an owner test verified lower
bandwidth saturation as defined in [benchmark.md](benchmark.md).
**Loaded async safety/performance: NOT RUN**; do not interpret a
status overlap count as proof of useful throughput or media wear.

## Active V3-only default gates

`make test` runs V3 native C suites, source/fixture/safety contracts,
W=1/W=2 builds, then loaded owned-RAM correctness and off/swapz paired
performance in that order. Its private Python replay oracle includes
bad-input rejection in safe rootless files. Benchmarks require an actual
loaded V3 module before claiming performance. Without noninteractive
privilege or safe owned `null_blk`, the full command exits BLOCKED (nonzero),
not PASS. Rootless CI uses only the internal rootless subset and must
report its result as partial; it is **not a competing public test command**.
The retired C++ model is retained for historical source inspection. Regressions focus on 2:1-ish **measured** LZ4 inputs, raw
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
retain the exact original files. Run the official `make test` pipeline at **final HEAD**; its internal
stages perform both source contracts and off/swapz replay tests.

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

## Historical per-alpha deployment notes — NOT current commands

The original source-specific examples below refer to retired
`make verify`, `make deploy`, `make run` and `make bench-*`
commands. **They are not executable instructions on current main.**
The supported user command today is `make test`, which runs
rootless source/kernel checks and then requires explicit
noninteractive authorization for isolated owned-RAM work.
Historical test records remain in Git history.

## Automated local deploy-and-verify gate

`make verify` invokes the 14 production-C native tests, the exact
V3 constructor/source contracts, the safe off/swapz **regular-file**
replay oracle and shell deployment source checks. CI additionally
compiles `tests/tools/device-roundtrip.c` with `-Wall -Wextra -Werror`.
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

The native suite exercised by `make test` now includes the
`zero-write-elision` executable compiling the **actual engine and
authority C**. It verifies full-byte zero recognition, nonzero at
start/middle/end, RAW-to-zero-to-nonzero generation transitions,
physical liveness retirement, in-flight refusal and overflow fail
closed. An additional source contract checks that the production
`dm-target.c` path drains prior writes, invalidates via
`swapz_discard_page`, maintains FUA flushing and counts only
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
a matched off/swapz throughput performance comparison. See
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
`src/kernel/VERSION` and production `SWAPZ_ALPHA_VERSION`.
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

The off/swapz immutable replay's `--owned-nullblk-name` is the owned
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
off/swapz replay, actual physical-media improvement or release
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
off/swapz experiment or new V3 production-kernel behavior**.

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
`swapz_flush_window()`, including a failed physical commit. An empty
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
beginning of each nonempty `swapz_flush_window()` captures elapsed
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

### Exact-head alpha.11 CI repair and constructor/table alignment

The first alpha.11 direct-main commit (`0a750dcf`) FAILED
native/source CI because `body()` recognized only `int`/`void`
helper signatures and the preexisting constructor contract expected
the obsolete 9-argument limit. Kbuild also FAILED with an implicit
forward declaration of `swapz_retention_expired` in `swapz_process`.
The repair adds a forward prototype, expands source function
recognition to `bool`/`unsigned long`, updates the constructor
argument test to `argc<=10`, and accepts both the historical
12-field V3 table and new 13-field table with a tightly checked
`retain_ms=0..4` final field. Any extra, negative or out-of-range
field is refused. The old table implies **retention off**.
No loaded alpha.11 execution follows merely from source/CI green;
first test the default on owned null_blk.

## Alpha.11 separate opt-in pilot harness gate

Do not change `make run`, default `make bench-pair` or
`make bench-pair-medium` to enable retention. Only a separate
explicit `make bench-pair-medium-retain` target is allowed to
pass `--run-owned-ram-pair --profile medium --retain-ms 2`.
All other retention flag forms must be rejected before any
privileged device setup. The provisioned DM table and INFO status
must confirm the intended policy before touching its upper device.
The existing full-oracle, independent-device counter, unique
major:minor, no-swap and quarantined-teardown checks remain.
Source/rootless syntax gates are necessary but *not* a validated
timed BIO/GC/drain/fault-path loaded result; keep `retain=0`
default until an explicit controlled evaluation proves otherwise.

## Alpha.11 loaded smoke: volatile host Used caused harness failure (2026-10-14)

At source `b5d54fe9aa0a9e0cfd24e03da473fc6516fe508e`,
Linux `7.0.0-38-generic`, host-local
`build/deploy/session.TTeZUSq8/session.log`, the exact C oracle,
nine zero elisions, independent lower WRITE 183/749,568B,
READ 490/2,007,040B and all 119 FUA closure/age counts **passed**.
The **complete** `make run` nonetheless **FAILED** at cleanup:
the existing system `/swapfile` Used changed 1,624→1,620KiB.
Its Filename, Type, Size, Priority and the second active swap
entry were unchanged. This is a volatile consumption metric, not
an inventory identity change or evidence that swapz touched
system swap. The retained candidate was NOT enabled (`retain_ms=0`).

The owned smoke and owned pair now canonicalize the active swap
inventory's **path/type/size/priority** (sorted) before/after,
ignoring only Used. Continue logging exact raw snapshots, and
quarantine resources **before teardown** on an actual entry
addition/removal or path/type/size/priority change. Reject malformed,
duplicate or missing swap rows. Rootless fake-/proc/swaps tests
cover benign usage drift plus adversarial changes. These snapshots
do not monitor every intervening moment. This correction changes
no production C or alpha version. **Loaded retest NOT RUN.**

## Alpha.12 dependency-aware retention and failure contracts

Positive `retain_ms` prepares every arriving ordinary WRITE immediately
on the existing worker. Admission coalescing applies only when retention
is off. A CLOCK_MONOTONIC absolute hrtimer wakes the worker at the
first record's original deadline; later arrivals cannot extend it. This
removes alpha.11's two-sample unsigned remaining-time underflow and
explicit jiffy rounding. Timer callback code only schedules work under
the admission lock; cancel outside that lock before window closure,
suspend/drain and destruction. Dispatch and synchronous lower I/O can
still exceed the nominal 1..4ms budget.

A READ may pass an opt-in retained window only when it addresses no
pending slot, has no PREFLUSH/FUA, admission remains open, the target
is healthy, and no authority transaction is active. The serialized READ
uses separate scratch and committed mappings. Same-slot reads, duplicate
writes, zero writes, discard and barriers drain as before.
`retained_read_bypasses` counts successfully completed independent reads;
it is not a closure count. A failed bypass READ fails the target and
error-completes every original pending WRITE without staging, lower
submission, publication or successful logical-write accounting. An
aborted nonempty window still conserves window, reason and age counts.

The new native `window-policy` regression executes the exact production
header predicates for compressed/RAW dependencies, caller fences and
nanosecond deadline edges. Source contracts inspect IRQ callback bounds,
immediate admission, cancellation order and the failed-window abort.
These cannot establish loaded timer/BIO behavior. **Alpha.12 native/source
tests, W=1/W=2 and loaded tests: NOT RUN, explicitly deferred by owner.**

Owner follow-up: run the command in [compile.md](compile.md), then extend
loaded coverage to same-page/independent READs, mixed RAW writes,
PREFLUSH/FUA, no-arrival expiry, READ failure with a retained window,
exactly-once upper completion, suspend/drain and GC reserve exhaustion.
Compare independent lower bytes/requests and achieved rate against
retention off; keep retention disabled by default pending repeatable
latency/CPU/GC qualification.

## Alpha.13 C-first opt-in useful-packing early commit

In `dm-target.c`, the only early-closure addition occurs after
admitting the eighth **compressed** record into a retained window,
when the actual production-C predicate proves all eight are
non-RAW, bounded length, and the largest seven compressed payloads
plus the existing 16B header and seven 16B descriptors fit 16KiB.
The remaining valid compressed record fits an additional 4KiB.
The existing byte-minimal engine can thus place the group in no more
than 20KiB versus 32KiB of independent 4KiB writes. This is only a
format geometry upper bound; physical lower request counts must be
measured. The rule is strictly disabled when `retain_ms=0`,
`read_budget>0`, or a batch has fewer/more than eight records,
RAW, zero or invalid lengths. A FUA write takes its original fence
before this possible early closure. The exact existing
`swapz_flush_window()` performs all physical I/O, CRC and mapping
publication and completes accepted BIO owners exactly once.
The new `SWAPZ_CLOSE_PACK_READY` belongs in window-closure
conservation. The separate `packed_early_commits` counter reports
attempted early closures, **not** successful lower I/O savings.

The rootless native C test must exercise eight actual 2,073B lengths,
retention default off, every read-budget restriction, short group,
NULL, RAW, zero and overlarge payloads, overfilled seven, and the
smallest-outlier case irrespective of arrival order. The source
contract checks after-admission placement and FUA precedence.
W=1/W=2, independent lower read/write-sector equality, byte-exact
loaded oracle, repeated same-source control/candidate comparison,
CPU and read/write p99 remain independent host gates.
**Alpha.13 loaded testing: NOT RUN.**

## Throughput units and measured input-to-backing evidence

Every matched loaded `io-replay.py` result must explicitly
report decimal **MB/s** for completed logical WRITE/read bytes
and independently observed backing WRITE/read bytes using the
same single-arm measured elapsed seconds. Include total MB/s
(READ+WRITE) for context and a dimensionless logical-write /
lower-write byte-efficiency factor when lower bytes are positive.
The logical input is the completed 4096B WRITE payload stream,
**not** `lz4_accepted_bytes`, prefill, warmup or final readback.
Backing bandwidth derives from independently owned `/sys/block`
READ/WRITE sector deltas, NOT compressor sizes or target-only
physical-I/O counters. Preserve two separate arms, same immutable
trace/source/readback, 5% matched achieved IOPS, READ requests/bytes,
p95/p99 and exact teardown. Report rootless lower bandwidth as
`null`, and reject NaN/zero/negative times, malformed logical
counts and negative/misaligned lower sector byte values. A
WRITE byte ratio does NOT prove a higher maximum logical input
MB/s at a fixed disk bandwidth limit. This requires a separately
qualified, explicitly controlled and saturated bandwidth ceiling;
RAM-only `null_blk` cannot be treated as physical SSD evidence.

## Alpha.14 C-first seven-record early commit gate (2026-10-14)

In the updated production `window-policy.h` predicate, an
explicitly retained unrestricted-read window is pack-ready
only when **exactly seven** immutable staged non-RAW,
nonzero-length LZ4 records fit in a **single 16KiB extent**:
the real SWZ3 header (16B), seven descriptors (7x16B)
and **all seven actual compressed payload lengths** sum
to no more than 16384B. For seven 2073B records,
the exact footprint is 14639B, proving a 16KiB planner
candidate instead of 7 separate 4KiB units (28KiB).
The earlier alpha.13 eight-record rule waited for another
arrival and could require 16+4KiB; this experiment attempts
to reduce that wait without sacrificing format density.
It does **not** guarantee a lower I/O or p99 win.

Rootless direct production-C tests must reject count 6/8,
retention off, restricted read budgets, NULL, RAW,
zero or oversized payloads, 7x3568B overfull records
and unfittable shuffled short-outlier cases; exercise the
valid 7x2073B case. Preserve worker admission-before-rule,
FUA-before-early-closure, complete synchronous lower
I/O + authoritative mapping publication, unique BIO completion,
timer expiry, GC, exact status close-reason conservation,
no physical-device access and safe quarantine. Alpha.14
loaded tests and higher input MB/s at fixed disk MB/s
are **NOT RUN**; the kernel revision remains experimental.

## Unpaced input-MB/s RAM-only ceiling probe

The 500-IOPS medium control/candidate is unchanged. A separate
explicit opt-in `make bench-pair-medium-unpaced` uses two
newly owned RAM-backed null_blk devices, the same immutable
medium 4KiB fixture, QD32, 1024 warmup and **16384**
measured operations with 25% READ and `iops=0`.
The identical trace is replayed for uncompressed and
`retain_ms=2` V3. No unowned/physical device, host swap
configuration or destructive teardown is allowed. Retain
lower READ/WRITE byte/request deltas, full-image oracle,
timeout/quarantine and provenance checks.

Unpaced comparisons **do not** impose the 5% equality rule
because differing completed MB/s/IOPS is the metric
under test. Mark `UNPACED_THROUGHPUT_MEASUREMENT_ONLY`,
report each completed logical READ/WRITE MB/s and independent
lower READ/WRITE MB/s, the achieved-rate difference and
logical/lower throughput ratios. Only the original paced
comparisons may be labeled matched load after the 5%
check. Loaded unpaced evidence: NOT RUN. RAM null_blk
has **no defined disk bandwidth ceiling** and this
does NOT prove increased throughput at equal saturated
physical disk MB/s. Source/kernel alpha stays alpha.14,
as no production-C scheduling behavior changes.

## Alpha.15 C-first nonretained hot-path timer optimization

At exact alpha.14 owner source `a3c0a1ae`, the default
smoke and a separate paced medium off/retained comparison
passed: 767 completed 4KiB WRITEs per arm, immutable
final image, both independently owned RAM devices,
lower WRITE 3,141,632B off versus 2,048,000B V3,
lower READ 1,052,672B per arm and ordinary teardown.
Retained V3 sampled WRITE p99 2.696ms (off 1.120ms),
with 64 cumulative pack-ready early closures, no GC.
These were **500 IOPS paced** results. The explicit
new `make bench-pair-medium-unpaced` was **NOT RUN**.

Production `swapz_flush_window` now avoids calling the
synchronous `hrtimer_cancel()` for `retain_ms=0`,
because the only worker timer arming branch is gated
on `swapz_window_timer_enabled(retain_ms)` and returns
false when disabled. The nonretained singleton/quantum
hot path therefore skips an unnecessary timer operation
at every window closure. When retention is enabled
(`retain_ms=1..4`), the call remains synchronous,
outside `queue_lock` where the timer callback also
takes that lock. Drain and free must **always** cancel
regardless of configuration to prevent teardown races.
The direct native production-header test checks 0 vs
1..4, and the source contract checks guarded flush,
gated arming and unconditional drain/free. No change
to storage format, completion, outstanding work or GC
is intended. W=1/W=2 kernel build and rootless CI are
necessary; actual loaded throughput and timer-race
qualification of alpha.15 remain **NOT RUN**. High MB/s
must be measured with 16384-operation QD32 unpaced
pilot, not extrapolated from 500 IOPS.

## Alpha.16 retention hrtimer rearm suppression (C-first)

The owner's exact alpha.15 source `75d96be0` first
passed a loaded 128-page default-off C oracle, full
lower read/write reconciliation, FUA conservation and
owned RAM teardown. The owner then ran the explicitly
unpaced QD32 / 16384-operation medium pair at source
`75d96be0`, Linux `7.0.0-38-generic`, module SHA256
`df24ece353e7a51e144aed10bbff5eb9989e0651e149dbb99821f3ea184f9594`
with identical verified fixture and trace and safe teardown.
Uncompressed achieved 10,248.923 IOPS; V3 retained
8,086.307 IOPS (-21.10%). Off logical WRITE
31.518 MB/s / lower WRITE 31.518 MB/s, V3 logical
WRITE 24.867 MB/s / lower WRITE 14.792 MB/s.
Actual V3 WRITE bytes were 29,970,432 versus
50,384,896 off (40.52% fewer); lower requests
2,061 versus 12,301 (83.25% fewer). READ lower
bytes 16,723,968 and READ requests 4,083 for
BOTH arms, with unequal READ MB/s due to completion
time difference. Sampled WRITE p99 off 1.879ms,
V3 2.333ms, not statistically qualified. No
GC victims. The unpaced verdict was correctly
`UNPACED_THROUGHPUT_MEASUREMENT_ONLY`, NOT
matched achieved throughput or device saturation.

The retained V3 cumulative status reported
`windows=3124`, `retain_timer_arms=12228`,
`close_deadline=1483`, `close_pack_ready=1641`,
indicating avoidable repeated hrtimer starts at
one pinned absolute deadline while the worker
processes subsequent admitted BIO waves. The
production C worker now checks
`hrtimer_is_queued(&ctx->retention_timer)`
while holding its existing `queue_lock`, and
calls `hrtimer_start` only if the timer is
**not** currently enqueued and retention is
enabled. An already queued timer retains the
original first-record expiry. A concurrently
dequeued/expired timer can be armed to the SAME
absolute first-record deadline, never extending
the window. No cancellation is weakened; existing
retained flush, unconditional drain and free still
use synchronous `hrtimer_cancel()` outside
`queue_lock`. `retain_timer_arm_skips` is
an observational count of skipped arming attempts,
not a measured lower-I/O/CPU saving. Direct
production-header native C tests check retain=0
and 1..4 with queued and dequeued states, and
source qualification verifies the guard precedes
arming, status and teardown. This is a small
hot-path experiment; time savings, throughput,
fault/suspend races and GC on loaded alpha.16
are **NOT RUN**. The exact medium fixture is
synthetic and null_blk-only; no physical device
claim is permitted.

## Alpha.17 production-C homogeneous compressed ordering fast path

Owner source `59acee3534fd46fbcaabb51a1f30a366098ed1fd`
ran alpha.16 loaded default smoke and paced QD8 medium
control+retained comparison on fresh owned RAM null_blk;
byte-exact 128-page and 1024-page oracles, independent
lower READ/WRITE stats, unchanged host swap configuration
and ordinary teardown **PASS**. The retained V3 arm achieved
~1.54353 logical WRITE MB/s with 1.00621 lower WRITE
MB/s, actual 2,048,000 lower WRITE bytes / 158 requests
versus 3,141,632B / 767 off (34.81% byte saving).
READ lower bytes/requests were unchanged (1,052,672B /
257), and WRITE p99 was 2.688ms V3 against 1.104ms
off, in this short sample. Across wider cumulative state,
`windows=1202`, `retain_timer_arms=1202`,
`retain_timer_arm_skips=844`, `close_pack_ready=64`,
`close_deadline=1138`, `gc_victims=0`. The requested
QD32 **unpaced alpha.16 comparison was NOT RUN**;
therefore no new high-throughput gain is established.

Alpha.17 optimizes the actual production
`swapz_order_window` C path. The existing greedy algorithm
picks the EARLIEST remaining largest compressed record;
if all payload lengths are equal, it may pair that record
with the EARLIEST remaining partner fitting the existing
4KiB metadata+two-payload bound. In both the pairing
and no-pairing cases, the resulting order is exactly the
original arrival order, so the worker can emit a linear
identity mapping instead of rescanning every remaining
record in O(n^2) greedy selection. The predicate requires
nonzero record count <=64, valid non-RAW compressed
lengths 1..SWAPZ_MAX_COMPRESSED and *all equal lengths*.
Mixed sizes, RAW, invalid, null or empty windows still
use the unchanged original greedy logic. Direct native
production-header tests cover singleton, 7 and 64
uniform 2073B records, tiny pairing-capable compressed
payloads, RAW, mixed length, invalid size and bounds.
Source contracts require both fast and fallback paths
join the same `planned` construction and original
`swapz_engine_write_window_batched` lower-success/
mapping-publication path. No changed storage format,
algorithm, GC, flush, read or upper BIO contract is
intended. Loaded alpha.17 performance and sustained
CPU/GC/fault gates: **NOT RUN**. Do not infer higher
input MB/s from an algorithmic complexity improvement
alone.

## Alpha.18 production-C phase-wall-time instrumentation

At exact owner-loaded alpha.17 source `90c0d5b9`,
module SHA256
`ae003b83a5e77f8f5888c9ab6477dace4efa91b88d5137603f5057d26e9b7efb`,
the default 128-page owned-null_blk smoke and distinct
medium QD8 500-IOPS off/swapz control and retained sessions
passed immutable 4KiB byte-exact oracle, full lower
READ/WRITE requests+sector reconciliation and ordinary
teardown without changing system swap. The retained
arm completed 767 logical WRITEs and 257 READs:
1.54339 logical WRITE MB/s -> 1.00612 actual lower
WRITE MB/s, versus off 1.54482 -> 1.54482.
Lower WRITE bytes 2,048,000 V3 against 3,141,632 off
(34.81% reduction), 158 vs 767 lower WRITE requests;
lower READ bytes/requests identical at 1,052,672/257.
Sampled WRITE p99 2.742ms vs 0.994ms off, not a
stable tail claim. Cumulative `windows=1202`,
`retain_timer_arms=1202`, `retain_timer_arm_skips=836`,
`close_pack_ready=64`, `close_deadline=1138`,
`gc_victims=0`; alpha.17 unpaced was **NOT RUN**.

The alpha.18 real `dm-target.c` worker now collects
**cumulative monotonic wall nanoseconds** for the
already-existing synchronous sections: LZ4 compression
attempts, LZ4 decompression, bounded window ordering,
engine physical write commit (including dm_io and
publication), synchronous lower dm_io READ/WRITE,
and GC victim relocation on capacity pressure.
These scopes overlap: engine commit includes lower
write waits; GC includes nested lower operations.
Do **not sum** overlapping times and do **not**
label them CPU utilization. Timer retention wait,
BIO queueing, prefill, warmup, oracle readback and
reads outside the replay measurement interval may
also affect reported totals. For interval comparison,
take target-status counter differences at validated
measurement boundaries; until then use only
cumulative diagnostic ratios with explicit scope.

The production-header `swapz_elapsed_ns` helper
returns zero for a reversed timestamp rather than
underflowing an unsigned accumulator. Native tests
cover zero, forward, backward and boundary samples;
source contracts require the new instrumentation
directly around actual LZ4, lower dm_io, sorting,
physical commit, read decode and GC sites, plus
truthful status fields. The new timestamps add
small but nonzero overhead, so a same-source
benchmarked baseline and repeated owner-loaded
QD32 comparisons are required before attributing
performance changes. Loaded alpha.18 unpaced
and sustained GC/CPU/fault qualifications:
**NOT RUN**. All test IO must remain uniquely owned
RAM-backed null_blk with byte-exact readback,
independent lower sectors/requests and safe teardown.

## Alpha.19 bounded same-invocation worker queue continuation

Owner's exact alpha.18 source
`88197bf4479eeb66db6bf52301a3cbd3d4c6a6e7`,
module SHA-256
`aee943cd3023027a790fcdb1152510ea60cfa76581f39e289f97ae614226b6ef`,
passed the default 128-page byte-exact loaded smoke
and isolated `make bench-pair-medium-unpaced` on two
uniquely owned RAM-backed null_blk devices at QD32,
16,384 measured operations and no IOPS pacing.
Identical immutable source/fixture/trace/final image
and independent lower counters were verified;
existing host swap remained unchanged and cleanup
was ordinary. Uncompressed attained **9,909.850
IOPS, 30.4753 logical WRITE MB/s -> 30.4753 lower
WRITE MB/s**. V3 retained attained **8,020.113
IOPS, 24.6639 logical WRITE MB/s -> 14.6728 lower
WRITE MB/s**, 19.07% fewer completed logical IOPS.
Actual lower WRITE bytes 29,974,528 vs off
50,384,896 (40.51% saved), requests 2,062 vs
12,301 (83.24% saved). Physical READ bytes/requests
were equal: 16,723,968B and 4,083. Sampled WRITE
p99 was 2.333ms V3 vs 2.023ms off, and READ
p99 2.726ms V3 vs 3.015ms off; no GC occurred.
Alpha.18's C cumulative wall timings include
71.716ms LZ4 attempts, 0.949ms ordering, 168.616ms
window commit, 69.721ms lower WRITE and 57.315ms
lower READ, plus setup/warmup/oracle, with overlapping
sections. Do NOT sum these or label them CPU cost
or a direct accounting of the 2.043s replay interval.

Alpha.19 changes only **actual Linux kernel
`swapz_worker` scheduling**. Previously the worker
requeued any newly arrived BIOs, even if its
current finite 64-BIO work quantum was not spent.
It now keeps the remaining quantum across inline
snapshots and directly loops to drain newly queued
BIOs, but ONLY while `ctx->accepting` and
`remaining > 0`. The worker still splices
unfinished older BIOs to the head of incoming
before considering this branch (strict FIFO);
on `remaining=0`, it uses the SAME
`mod_delayed_work` yield path. When admission
is closed for suspend/drain, it resets a fresh
64-BIO budget AFTER releasing `queue_lock`,
calls `cond_resched()`, and keeps processing
all previously accepted BIOs to completion.
No new async lower I/O, compression format or
publication/GC/FUA/read fence is introduced.
`worker_inline_drains` is only a count of
skipped workqueue handoffs, not proof of higher
MB/s. Direct C policy tests check zero/nonzero
budgets and closed admission, and source tests
require FIFO splice before continuation, 64-BIO
bound, fallback requeue, shutdown drain, and
status telemetry. Exact-head rootless compilation
and tests are necessary; owner-loaded alpha.19
default-off smoke, no-starvation tests and
unpaced useful WRITE/READ throughput remain
**NOT RUN**. Same-source RAM-only comparison,
full image oracle, independent sectors and
bounded teardown are mandatory before claims.

## Alpha.20 evidence-based withdrawal of alpha.19 inline drain

The owner ran `make run` then `make bench-pair-medium-unpaced`
on alpha.19 exact source `841f5517798fb8ce12ae5699b0729dc15a69b36a`,
Linux `7.0.0-38-generic`, module SHA-256
`9ed69e810aa99df66598fd24e81fc42632e9f487db8b8a2cf0fa9d0b4b4c55a9`.
The loaded 128-page smoke and the QD32 16,384-operation unpaced
off/swapz trial PASSED full byte-exact readback, unchanged system
swap, independent separate owned RAM null_blk statistics, and
ordinary safe teardown. Off completed 10,564.904 IOPS,
**32.48972 useful logical WRITE MB/s -> 32.48972 lower WRITE
MB/s**. V3 retained completed 7,690.293 IOPS,
**23.64957 logical WRITE MB/s -> 14.07708 lower WRITE MB/s**.
This is a 27.21% same-source V3 useful-throughput deficit.
Independently observed V3 lower WRITE bytes 29,990,912
vs off 50,384,896 (40.48% saving), requests 2,065 vs
12,301 (83.21% saving). Lower READ bytes/requests were
identical at 16,723,968B / 4,083 per arm. Sampled WRITE
p99 2.594ms V3 vs 1.813ms off; READ p99 3.591ms V3
vs 2.681ms off. Zero GC victims and target failures.
Cumulative alpha.19 `worker_inline_drains=3153`,
`worker_requeues=0`: the proposed optimization was
used but did not produce a benefit. Previous separate
alpha.18 test V3 achieved 24.664 logical WRITE MB/s,
off 30.475 MB/s; cross-version differences are not
statistically conclusive. Do not promote alpha.19.

**Alpha.20 production C correction** reinstates the
exact alpha.18 serialized `swapz_worker`, including its
normal-mode FIFO splicing and bounded workqueue requeue
even when the snapshot has remaining 64-BIO budget;
on closed admission it loops with `cond_resched` to
complete all previously accepted BIOs. Remove unused
`swapz_worker_can_inline_drain`, its native test and
`worker_inline_drains` telemetry. Source qualification
must reject inline continuation and check requeue,
64-BIO processing, FIFO, full shutdown drain and
timer cancellation. Existing native randomized
engine and exact-C safety suites still apply.
Do not weaken correctness, FUA/GC or ownership
acceptance criteria. Loaded alpha.20 is NOT RUN;
potential restoration of prior useful MB/s is a
hypothesis pending the same RAM-only unpaced run,
independent lower counters, read/write p99, full
oracle and ordinary teardown. Physical-disk
saturation and sustained CPU/GC remain unqualified.

## Alpha.20 same-source 1ms versus 2ms high-QD retention experiment

The owner loaded exact alpha.20
`faf17bc2d3614cad56f1d027dda4d2acf6dc6e66`
(Linux `7.0.0-38-generic`, module SHA-256
`1f385ee3dc20f59d068a8105de190f1d5c5185d8b2c442bbfdeebde9204c7005`).
Default `make run` and the distinct unpaced QD32
16,384-operation `make bench-pair-medium-unpaced`
passed independently measured READ/WRITE bytes and
request counts, complete byte-exact oracle, no host
swap change and safe cleanup of newly owned RAM null_blk.
The normal uncompressed arm achieved 10,488.863 IOPS,
**32.255877 logical WRITE MB/s** and the same lower
WRITE MB/s. Retained 2ms V3 achieved 8,120.119 IOPS,
**24.971397 logical WRITE MB/s -> 14.853728
independent lower WRITE MB/s**, 22.58% fewer useful
IOPS than off. V3 saved **40.517% lower WRITE bytes**
(29,970,432 vs 50,384,896) and **83.245% lower WRITE
requests** (2,061 vs 12,301). Lower READ traffic
was equal at 16,723,968B and 4,083 requests per arm.
Sampled V3 WRITE p99 2.340ms vs off 1.843ms, and
READ p99 2.723ms vs off 2.786ms. Cumulative target
`worker_requeues=3171`, `windows=3124`,
`close_pack_ready=1642`, `close_deadline=1482`,
`gc_victims=0` and no target failures. The result
restores useful write MB/s compared with the separately
executed alpha.19 trial at 23.650 MB/s (+5.59%)
but does NOT beat the off arm, prove statistical
significance, qualify sustained GC or impose a
fixed physical disk bandwidth ceiling.

**New opt-in comparison at the EXACT SAME production
alpha.20 kernel source:** `make
bench-pair-medium-unpaced-retain-1` uses the existing
kernel-supported `retain_ms=1` policy. It leaves
`make bench-pair-medium-unpaced` at `retain_ms=2`,
with identical QD32, 1024 warmup, 16,384 measured
operations, 25% READ, the immutable medium liblz4
~2073B fixture, the same full 1024-page byte oracle
and the same independent lower-device sector and
request checks. The shell preflight accepts **only**
the exact opt-in `--run-owned-ram-pair --profile medium
--retain-ms 1 --unpaced`; it rejects paced 1ms,
arbitrary 0/3ms and unknown flags before any privilege
or resource creation. Both arms use separate exclusive
RAM-backed null_blk, validated DM UUID/backing, stable
host swap, strict timeout and teardown quarantine.
Compare completed logical WRITE/READ MB/s, achieved
IOPS, READ and WRITE p95/p99, actual lower READ/WRITE
bytes and request counts, and `close_deadline`/
`close_pack_ready` without relaxing any correctness
criterion. The 1ms candidate might reduce latency
and increase useful throughput **at the cost of**
worse lower WRITE-byte savings. Label both outcomes
honestly; no 1ms owner-loaded result yet. This is
intentionally an independent measurement/configuration
increment, not a new production C algorithm; the
module stays alpha.20 so comparisons share code.

## Alpha.21 production C: useful short-window early commits

Alpha.20 owner-loaded QD32 medium run at exact source
`faf17bc2d3614cad56f1d027dda4d2acf6dc6e66`
showed V3 **24.971397 logical WRITE MB/s versus
14.853728 lower WRITE MB/s**, compared to the uncompressed
**32.255877 MB/s** arm. Independently measured V3 physical
WRITE bytes were 29,970,432 vs 50,384,896 off (40.517%
saved), and lower WRITE requests 2,061 vs 12,301
(83.245% saved). Read lower bytes/requests matched at
16,723,968B and 4,083. Both arms passed full byte-exact
1024-page oracle and clean owned RAM teardown; no GC.
The V3 useful-input shortfall remained 22.58% vs off,
with sampled WRITE p99 2.340ms vs 1.843ms off.
Cumulative `close_deadline=1482` and
`close_pack_ready=1642` out of 3,124 windows. These
measurements **do not prove** which deadline windows
would benefit from different packing.

Alpha.21 makes a substantive C write-path policy change
for **only already opted-in retention**. Previously, a
7-record group that fit a single 16KiB V3 extent could
close before the absolute deadline. The actual production
`swapz_window_pack_ready` now accepts exactly:
- 2 valid non-RAW compressed pages, including 16B
  header plus 2x16B records, fitting 4,096B;
- 3 such pages plus 16B header and 3x16B records,
  fitting 8,192B; or
- 7 such pages and 16B+7x16B metadata, fitting
  16,384B (prior policy).
All records must have 1..3568 actual accepted LZ4
bytes; retain_ms>0, zero read-budget and non-NULL
buffer are mandatory. The native regression checks
two medium 2073B pages do NOT fit 4KiB but
three DO fit 8KiB (6283B total), the exact
two-page boundary at 2024B each, 2700B x3
fitting 8KiB, and 2800B third, RAW, zero,
oversized, disabled retention, read budget,
invalid count and NULL rejections. Source
contracts require FUA precedence, complete
admission, exact metadata and the unchanged
`swapz_flush_window` physical-success publication/
upper-BIO completion gate. This directly
addresses earlier closure without relaxing
ordering, GC, CRC, device ownership or teardown.
It can **reduce** effective seven-record density:
for seven 2073B pages, earlier 3+3+1 writes
can require 20KiB rather than one 16KiB
extent. Thus a logical MB/s improvement is
*not sufficient* if actual lower WRITE bytes,
requests, READ p99 or FUA cost regress badly.
Measure the retained 2ms alpha.21 owner-loaded
same-source off/swapz QD32 trial, with full oracle
and independent lower sector/request counters,
then compare to alpha.20 under repeated
counterbalanced conditions. Default retention
remains off; alpha.21 loaded result: NOT RUN.

## Retired V2.2 audit lessons — not a V3 test result

Historical exact-production-C and rootless audits exposed important failure
classes: upper-BIO identity and pending-pack ownership, callback lifetime
after timeouts, fail-closed bounds for published mappings and lower extents,
generation-scoped publication, GC scratch isolation, and FUA/flush completion
ordering. The findings and links to all 15 safety audits are consolidated in
[the historical V2.2 audit evidence](https://github.com/k1moradi/swapz/tree/abbdbce277938f3678a640af93ef066394b44606/docs/archive/v2.2/audits); all dated reports remain retrievable in Git history. They **do not** qualify current
V3 behavior or establish loaded, physical-device, or production readiness.
Re-test a relevant invariant against *current V3 production C* instead of
counting retired V2.2 rootless PASS results as V3 evidence.

## Rootless package install/uninstall and production hold

Do not ask the owner to run `make install` or `make uninstall` before V3's production safety gates are accepted. Rootless fake-DKMS tests must run under `build/tests/package-sandbox` and exercise the actual installer, including versioned source installation, the read-only `swapzctl` binary, refused activation arguments, ownership checks, double-install prevention, exact uninstall, modified binary refusal, failed DKMS removal quarantine and install rollback. Root execution must reject test-mode overrides. These test results are **not** loaded module correctness, real DKMS compatibility or production readiness. No root Make commands may be added beyond the four owner-approved commands.

The V3 DKMS script resolves a controlled executable path and invokes `"$dkms_bin" add/build/install/remove`. Policy checks must match those **validated calls**, not a hardcoded bare `dkms add` string; behavioral rootless fake-DKMS tests remain the decisive packaging gate.

## Consolidated recall, pidfd, NBD and backing-release safety specifications

**Status: ROOTLESS MODELS ONLY; direct production mapper recall is DISABLED.**
The former separate `docs/recall-*`, `docs/pidfd-*` and `docs/nbd-*`
specifications are retired. Their exact state machines, adversarial cases,
source versions and negative evidence remain in immutable Git history.
The reusable safety acceptance contract is:

1. **Worker identity and ownership.** Each direct child receives a stable
   opaque handle; retain its exact pidfd and owning process/descriptor through
   gated start, stop, wait and reap. Do not fall back to numeric PID signalling
   or infer a stopped process from a reused PID. Use a one-use start gate,
   bounded READY handshake and fixed worker program. Account independently
   for registered and early-unconfirmed children, service exit, descendant
   containment and all role descriptors. A pidfd reap is **not** a kernel
   I/O-completion or durability barrier.
2. **Worker and executable admission.** Direct recall accepts exactly the
   fixed `writer`, `a`, `b`, `a2`, `b2` roles with no caller-controlled
   argv, executable path, environment, PIDs, mapper name, backing path or
   identity. The writer precedes reads; require both concurrent reads READY
   behind gates before group release. Pinned file descriptors and exact
   post-write identity checks prevent readback aliasing. The ordinary test
   CLI still admits only fixed short-lived test workers, not production
   `dd` or live Device Mapper work.
3. **GNU worker trust bootstrap.** Authenticate source and a separately
   reviewed static GNU `dd` build before trust admission. A root-controlled
   path and a matching SHA alone are insufficient. The fixed app Ed25519
   signing key must be provisioned independently of the signed manifest;
   the GNU GPG source key is a different trust chain. Open directories/files
   descriptor-relatively without symlink following; reject changed, revoked,
   unexpected, unowned or writable entries. Pin and verify the OpenSSL
   verifier/executable and its host dynamic-library trust assumptions.
   Require supported ELF/architecture, sealed executable memfd, minimal
   descriptor set, no-new-privileges, sandboxed seccomp and parent-death
   containment. An ordinary rootless successful five-role run, even with
   same-host reproducible builds, **does not install a production trust key
   or qualify privileged mapper ownership**.
4. **Exact mapper lifecycle.** Acquire an exclusive fixture-specific
   lifecycle owner *before creation*, bind the mapper name, UUID,
   major/minor, table fingerprint and descriptor, and re-inventory each
   before every role. Deny arbitrary table reload or worker-owned DM
   commands. Close role admission, reconcile authenticated session-bound
   complete worker/error/descriptor/service inventories, and independently
   establish any test swap inactive. Ordinary upper-to-lower DM suspend
   without `--noflush` and positively observed kernel pending-I/O drain
   must precede normal removal. Close exact owner descriptors and require
   complete zero open-count and empty holder inventories; use neither force
   nor deferred removal. Independently prove each exact mapping absent
   after removal, then normal loop/NBD disconnect/absence before even
   considering backing release.
5. **Backing release is separate from mapper release.** Mapping disappearance
   or an `all_reaped` receipt cannot authorize image deletion. Use a
   strictly session-bound, sequence-checked, authenticated evidence record
   whose producer is a trusted owner directly observing state. Reject stale,
   duplicate, forged, out-of-order, missing or contradictory evidence.
   Any crash, changed identity, timeout, failed suspend, unobservable
   holder/open count, failed disconnect or ambiguous finalization requires
   **preserve backing and logs**, not forced teardown.
6. **NBD/live admission remains closed.** The old pidfd-owned NBD server,
   control bridge and telemetry models operate on synthetic files only;
   they neither connect a kernel NBD server nor qualify DM drain.
   Do not enable the legacy NBD benchmark backend, real swap, physical
   media or privileged operations because rootless mocks pass. A future
   separately authorized, bounded owned-RAM test needs real server
   process-tree ownership, verified kernel NBD disconnect, exact mapper
   suspend/removal, byte-exact readback and complete independent observations.

**Test oracle:** the rootless regressions for pidfd, supervisor, IPC,
five-role recall, trusted GNU worker, broker ownership, session/HMAC drain,
NBD crash behavior and telemetry check their *own synthetic failure models*.
Preserve negative outcomes and quarantine. These rules are not certification
of deployed V3 or physical-media readiness.


# Legacy V2.2 virtual smoke — safety compatibility handoff

This retained note exists because rootless compatibility tests verify that
the archived V2.2 virtual smoke contract continues to state every relevant
authorization and cleanup constraint. It is **not** an active V3 benchmark,
permission to load a V2 module or authorization to test the owner's PC.
All privileged V2.2 work requires a separate authorized operation. V3
remains experimental and null_blk-only. There is no implicit sudo step in
`make test`; no physical swap, mount, swapoff/swapon, or host reboot is
permitted by this document.

## Historical disposable-VM prerequisites

The operator must independently confirm disposable VM ownership, the
matching exact source/module digests, and kernel support for
`modprobe dm-delay`. The former harness used only a newly owned
32 MiB tmpfs image, not an existing block device. Its 32 MiB image
is **65,536 sectors** (512-byte accounting sectors), or
**32 complete 1 MiB segments**. The reserve bound was
the larger of 25% of the one-page logical size or two segments.
Only the swapz logical table is one page (`0 8` sectors).
A one-page V2.2 target is NOT a 32 MiB logical data volume.

The operator-supplied VM label is an untrusted string: the test
cannot authenticate the operator-supplied VM label. Explicit authorization
must match the VM label and immutable exact source and module SHA-256.
The former runtime relied on two separate aligned 4 KiB reads:
the first while the lower write is outstanding, the second
after ordinary suspend/resume drain. Tests must verify byte identity
and the one-owner completion invariant. Unexpected holders or incomplete
lower callbacks make ordinary cleanup unsafe: forensic cleanup or VM reset needs a new operator decision and must not be automated.

This literal authorization template is retained only for the source
contract; do not execute it on an owner's machine:

```bash
AUTH="I AUTHORIZE swapz V2.2 smoke only on disposable VM $VM_ID with source $SOURCE_SHA and module SHA-256 $MODULE_SHA256; permitted operations are one /dev/shm-backed loop device, one dm-delay target, one swapz target, one aligned 4 KiB write, two separate aligned 4 KiB reads (one while the lower write is outstanding and one after ordinary suspend/resume drain), ordinary suspend and resume, ordinary removal of resources positively created by this run, and insmod/rmmod of only the selected dm-swapz module; no swap activation, mount, physical storage, forced removal, or host reboot."
```

The current `tests/runtime/virtual-smoke-test.py` verifies only the
compatibility and safety statements; that rootless gate does not load any
kernel module and does not establish live kernel or device correctness.


## Version-neutral repository layout migration — October 17, 2026

Active product source is rooted at `src/`; production kernel contracts read
`src/kernel/dm-target.c` and kernel-source workflows trigger on
`src/kernel/**`. Test-only Python, shell helpers and native fixtures stay
under `tests/`. Maintained Markdown stays under `docs/`.

Migration checks must not preserve deleted source paths or obsolete
version-suffixed test identities merely to keep old CI assertions green.
When a versioned implementation path or test artifact is retired, update the
source contract and workflow trigger in the same change. Historical on-disk
`SWZ3` terminology remains format identity, not an implementation-version
name.


The retained `swapz-kernel-range-contract-test.py` is explicitly a historical
safety regression over `tests/legacy/kernel/dm-swapz.c`; it is not current
product source. Current product contracts use `src/kernel/` and the exact
native production-C suites. Do not repoint legacy helper-extraction tests at
the current target merely because the repository layout changed.


Official human-readable and JSON reports use the product name `swapz`,
not an implementation-generation label. Report/schema keys must likewise be
version-neutral; historical release provenance belongs in source/version
fields or Git history. `SWZ3` is reserved for the on-disk format identity.
