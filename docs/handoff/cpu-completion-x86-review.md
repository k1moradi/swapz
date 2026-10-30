# CPU-targeted completion: validated draft, not qualified

Reviewer stage #4 now has a compiled kernel C candidate and direct delivery
validation. It remains **unapplied** in [the archived patch](cpu-completion-x86.patch).
Production C, native tests and development helpers are restored exactly to
qualified source `545defa8a1ba21f5dd49cd16a1566806e75b71ec` (all-five-stage report
`3465b4c08987`). No performance benefit, regression or equivalence is established.
The [prospective pilot plan](cpu-completion-x86-plan.json) has not started.

## Mechanism and ownership audit

The admission descriptor records its CPU. Successful, nonempty READ and WRITE
notifications can move to that CPU through `smp_call_function_single_async`.
Authority validation/publication, lower success, decoded-byte copy and ordering
remain with their existing owners. The ordered preparation reference is released
before notification handoff. Errors, closed admission, same-CPU delivery and a
full callback pool retain inline completion. Existing WRITE ACK batching stays
unchanged, so its unbound helper may perform a second notification handoff.
There is no new lower I/O, early ACK or cache/authority access in the callback.
This differs from ID147's removed list-only READ deferral: synchronous and
concurrent READs actually execute remote completion here.

A target owns 64 fixed callback cells. Under `queue_lock`, the sender reserves
one, marks the BIO as remotely delivered, and invokes the asynchronous API.
A rejected enqueue transfers no ownership and restores inline completion.
After successful enqueue, the sender never accesses that BIO/descriptor again;
the callback may already have freed it. The callback rechecks terminal failure
through the existing completion path. Its cell survives `bio_endio`; cell reuse,
active-count release and drain wakeup share `queue_lock`. Nothing accesses the
target or cell after the callback's final unlock. Admission close uses the same
lock; drain joins the queues, waits for all remote callbacks and takes that lock
before checking invariants/freeing memory. Constructor failure has no admitted
BIOs or remote callbacks.

The running kernel is `7.0.0-42-generic`. The locally installed Ubuntu source
archive's `kernel/smp.c` was inspected, including `generic_exec_single`, async
CSD unlock-before-callback, and the dying-CPU pending-call flush. Its rejection
returns `-ENXIO` for an invalid/offline CPU; accepted calls are flushed during
CPU teardown. Same-CPU execution is synchronous, so it must bypass the remote
path to avoid recursion into the sender's held lock. These behaviors agree with
[upstream v7.0 SMP code](https://github.com/torvalds/linux/blob/v7.0/kernel/smp.c).
The local source hash is preserved in the validation packet; source inspection
is not a live CPU-hotplug test. No host CPU was offlined.

The callback runs with interrupts disabled; `bio_endio` is IRQ-safe, but moving
its entire upstream callback chain into an IPI can add interrupt latency and
cross-CPU lock/cache traffic. Bounded storage does not prove cheap execution.
Kernel lifecycle, error and performance gates remain necessary. Actual source
and module hashes are in the plan and complete validation packet.

## Development evidence

Both final-source `make fast_test` sessions passed all 93 source contracts,
including an ASan/UBSan native probe compiling the actual completion bodies.
It covers all 64 occupied cells plus inline overflow, cell reuse, same-CPU and
closed-admission fallback, `-ENXIO` and `-EBUSY` rejection, explicit errors,
terminal failure after enqueue, and callback completion across admission close.
The probe poisons the BIO at `bio_endio` and the target at final callback unlock.
These controlled primitives do not prove kernel hotplug or real drain races.
A source assertion initially split the unlock call at its function name and
mistook the lock argument for a later dereference; it was corrected before the
final passing sessions. No loaded run occurred on the failed assertion.

Four owned raw/swapz pairs (eight arm oracles) passed on the final candidate:

| Preparation | Scenario | Remote READs | Remote WRITEs | Active afterward | Upper successful WRITEs |
| :--- | :--- | ---: | ---: | ---: | ---: |
| async | NVMe5 persistent mixed | 5,397 | 12,488 | 0 | 15,104 |
| async | fast WRITE QD1 | 0 | 0 | 0 | 5,376 |
| synchronous | NVMe5 wave mixed | 5,429 | 12,790 | 0 | 15,104 |
| synchronous | fast WRITE QD1 | 0 | 0 | 0 | 5,376 |

Counts span the complete target session, including setup/readback, rather than
only the timed replay. Accepted remote-call counters plus zero outstanding cells
and exact byte/upper completion oracles establish delivery. All final-source
runs had zero rejected enqueues, pool-full fallbacks and upper WRITE errors.
The QD1 runs stayed local; they do not demonstrate QD1 remote delivery.
Synchronous versus async rows are different correctness workloads, not a paired
performance comparison. An earlier run preceded the preparation-release
placement correction and is excluded from this final-source packet.

Native DWARF sizes on this host: each callback cell is 64 bytes; the target
structure grows from 24,896 to 29,120 bytes (+4,224 requested bytes), and the
per-BIO descriptor grows from 112 to 120 bytes (+8). No per-I/O allocation was
added by the candidate. Allocator rounding, physical RAM and total CPU costs
remain unmeasured. Short development pairs do not qualify sustained GC.

[Complete compressed validation](cpu-completion-x86-validation.json.gz) contains
all four final-source reports, byte oracles, raw controls, latency, independent
lower I/O, CPU/RSS, status snapshots and native/build logs. Timings are retained
for diagnosis, outside any performance sample family. No new owner report or
plot was generated: history still ends at qualified source `545defa8`, report
`3465b4c08987`, with three identified reports/42 points for this computer.

## Loaded correctness continuation

The archived production candidate (unchanged C SHA-256) subsequently passed the
private loaded deployment gate through `make fast_test`. This includes real GC,
DISCARD, retained lower WRITE/flush faults and suspend/drain/readback. The remote
completion gate observed 14,248 remote WRITEs and 165 remote READs, zero callbacks
active afterward, all 128 final pages verified and exactly 16,512 successful
WRITEs in the observed writer pass. A separate mapping recorded 42,053 remote
WRITEs before one injected lower failure; callback ownership drained, and a new
WRITE returned EIO without adding a success. The existing unbound handoff also
remained active (366 live-session and 1,087 fault-session batches).

A validation-only source sends otherwise eligible remote completions to
`nr_cpu_ids`, an invalid CPU index. The real kernel API rejected 18,712 calls;
all fell back inline, readback passed, no remote calls remained and no upper
WRITE error was recorded. No host CPU was offlined. This source is not a
performance arm and is restored to the archived candidate before timing. Its
initial native preflight stopped before loading because the API stub lacked
`nr_cpu_ids`; adding the constant made all 93 source contracts pass. The native
stub does not itself model the real kernel's CPU-validity check.

[Loaded lifecycle and rejection evidence](cpu-completion-x86-lifecycle.json.gz)
contains complete logs, reports, hashes and the validation-only source. These
are development gates, not full owner/ID36 qualification or a live-hotplug test.
The resolved prospective plan freezes all common-source/helper hashes and
fixture/trace/manifest/image hashes before any performance sample. Its pilot
remains pending at this documentation commit.

## Next gates

1. Verify base/hash and apply the archived draft. Review callback context and
   sender/callback overlap, then prove loaded suspend/resume, teardown and exact
   upper completion accounting with remote callbacks actually exercised.
2. Inject a lower WRITE failure after positive remote delivery and prove
   terminal failure at both callback and DM completion boundaries. Exercise the
   real kernel API's rejected-destination fallback without offlining a host CPU.
3. Only after correctness gates pass, use the declared 12-round counterbalanced
   plan, matched inputs, three primary endpoints, +3% floor, family intervals/
   signs and no replacement samples. Private orchestration must implement and
   record raw/target reversal and matched plan hashes before its first sample.
4. Retain only with justified service/latency/lower-I/O/resource evidence and
   exact-source `make test`. Otherwise restore production and archive the result.
   Reviewer stage #3 lighter admission follows completion-stage disposition.
