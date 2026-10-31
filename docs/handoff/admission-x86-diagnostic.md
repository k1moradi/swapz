# Admission contention: diagnostic observation, not a tuning decision

Reviewer stage #3 now has direct C contention observations. A temporary probe
replaced only `swapz_map`'s acquisition with try-lock plus its existing blocking
fallback. Four counters, protected by the same lock, counted attempts, failed
tries, fallback wall and maximum fallback wall. Clocks ran only after failed
tries. Admission close, FIFO insertion, producer/owner references and wakeups
remained inside the original critical section. The try-lock path and counter
stores perturb the implementation; these are not exact uninstrumented costs.

Three fixed rounds AB/BA/AB compared qualified production A against diagnostic B
on persistent NVMe5 mixed, SATA mixed, fast mixed and fast WRITE QD8. Raw/target
order reversed in round 2. Medium inputs, delta64 off, fixture/trace/payload/image
hashes and CPU geometry matched. Six blocks/24 owned pairs/48 arm byte oracles
passed; all 92 native source contracts passed in each block. The probe compiled
and ran in the real module, but did not receive full owner/ID36 qualification.
It is removed, with production and development helpers restored exactly to
qualified source `545defa8`, report `3465b4c08987`.

| Complete-session workload | Attempts per session | Failed tries | Hit fraction | Fallback wall per admission |
| :--- | ---: | ---: | :--- | :--- |
| NVMe5 persistent mixed | 23,615 | 2,664..2,995 | 11.28..12.68% | 56.2..78.5 ns |
| SATA mixed | 23,615 | 2,928..3,029 | 12.40..12.83% | 55.6..81.2 ns |
| Fast mixed | 23,615 | 542..582 | 2.30..2.46% | 4.2..4.8 ns |
| Fast WRITE QD8 | 7,485 | 241..298 | 3.22..3.98% | 4.3..6.8 ns |

Counts include setup and verification, not just timed replay. Wall averages
include uncontended attempts in the denominator. The clock starts after a
failed try, before blocking acquisition, and stops after acquisition; it omits
the initial try and includes clock/fallback overhead and possible interruption
or preemption before acquisition. Maximum observed fallback wall ranged from
0.555 to 10.378 us across sessions. These intervals are not exact CPU, complete
lock wait, hold duration, an upper bound on savings or a serialized budget.
The observations prove actual contention on the perturbed implementation;
they do not establish its prevalence or cost on unchanged production.

Perturbation assessment is unresolved. All three NVMe5 A/B pairs exceeded the
prespecified 10% paired raw-WRITE drift screen; none supports a performance
comparison. Counts are retained as diagnostic observations only. Remaining
three-pair descriptive normalized-service estimates and pointwise 95% intervals:
SATA -3.71% [-15.05,+9.15], fast mixed +6.44% [-16.28,+35.34], QD8 +0.57%
[-5.85,+7.43]. No significance, equivalence, overhead-free or product-gain claim
is supported; no replacement samples were collected. Full throughput, p95/p99,
independent lower I/O, GC and resource observations remain in the packet.

The [complete packet](admission-x86-diagnostic.json.gz) preserves plan, exact
C/module/helper hashes, all six blocks, screens, counters, logs and orchestration.
The [unapplied probe bundle](admission-x86-diagnostic.patch) reconstructs the
measurement, not a shipping optimization. No new owner report or plot was
generated; this computer's qualified history still ends at `3465b4c08987`.

Next measure time/work held under the lock, including notification, with explicit
instrumentation-cost controls and a more stable raw reference before selecting
an admission change. This probe did not measure uncontended acquisition cost
or hold work, and cannot rule those opportunities in or out. Do not select a
lockless rewrite from a hit fraction or add concurrent waits into a CPU total.
Preserve FIFO, producer/owner references and admission-close/drain synchronization.
