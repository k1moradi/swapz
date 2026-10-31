# CPU-targeted completion pilot: declined and restored

The fixed reviewer-#4 pilot finished all 24 source blocks and 144 owned pairs;
all 288 raw/target arm byte oracles passed. The new completion variant did not
meet its declared performance screen. Production C and all temporary native,
loaded-gate and development-loop changes are restored exactly to qualified
source `545defa8a1ba21f5dd49cd16a1566806e75b71ec`, owner report `3465b4c08987`.
Restored C SHA-256 is
`78f2d7de073a644c9c4182a0865e57ebdfce8b6d07cc02a4ae5578a8cd3d569a`.
No replacement observations or further confirmation were collected. This is an
inconclusive benefit result, not proof of equivalence or a regression.

## Candidate and correctness scope

The candidate's fixed 64-cell callback pool delivered successful nonempty
READ/WRITE notifications to the CPU observed during admission. Same-CPU, closed-
admission, full-pool and rejected-enqueue paths completed inline. It preserved
existing WRITE ACK batching, lower-success publication, authority/CRC checks and
ordering. Preparation references were released before remote handoff; target-
owned callback storage and a queue-lock drain join protected lifetime.
Candidate C SHA-256 is
`af438e26b01f854ef99194815e47cbd74250de7efc9bb057ea0d9242f02c8d69`.

[The initial audit](cpu-completion-x86-review.md) and
[loaded correctness packet](cpu-completion-x86-lifecycle.json.gz) preserve actual-
body native tests, real concurrent/synchronous mixed delivery, loaded GC,
DISCARD, suspend/readback, lower-fault and post-failure EIO checks. The separate
invalid-destination validation exercised 18,712 real-kernel enqueue rejections
with safe inline fallback; it is not a performance arm. No host CPU was offlined.
All 93 native source contracts passed with the candidate. The unchanged
baseline passes 92 with the new candidate-only probe skipped.

Every mixed candidate pilot session actually delivered thousands of remote
READs and WRITEs. Persistent NVMe5 session ranges were 5,407..5,490 READs and
12,614..12,771 WRITEs. All candidate sessions ended with zero outstanding
callbacks, zero enqueue/full-pool fallbacks and zero upper WRITE errors.
QD1 sessions stayed local; QD4/QD8 delivered 3,239..3,259 / 3,746..3,791 remote
WRITEs. These are complete-session counts, including setup/readback, not timed-
window populations. Full candidate owner/ID36 qualification was not run because
the performance screen declined retention. Development correctness is not
qualification or live-hotplug coverage.

## Fixed comparison and primary results

[The prospective plan](cpu-completion-x86-plan.json) was committed before the
first sample. Twelve rounds alternated AB and BA, with raw-first in odd rounds
and target-first in even rounds. A was unchanged qualified production; B was
the remote-completion candidate. Both retained async/submitter preparation,
medium content, delta64 off, identical fixture/trace/payload/image hashes, and
unchanged owned-RAM model geometry. Each source block ran persistent NVMe5
mixed, SATA mixed, fast mixed and fast WRITE QD1/4/8 once. Common-source/helper
hashes were frozen. The native stub was marked unused for baseline compilation
before the first sample, as recorded in the plan; no source changed mid-pilot.

The three primary endpoints were paired log changes in useful WRITE normalized
by each source block's own raw WRITE control. Practical floor: +3%. Intervals
are 98.3333% paired log-t intervals, with exact two-sided sign tests adjusted for
three comparisons. Chronological dependence and paired-model assumptions remain
limits; host noise screens do not prove an idle host or physical-media fidelity.

| Mixed workload | Usable pairs | Normalized WRITE change | Family interval | Adjusted sign p |
| :--- | ---: | ---: | :--- | ---: |
| NVMe5 persistent | 9 | +4.29% | -1.03..+9.89% | 0.5391 |
| SATA wave | 12 | +0.74% | -3.76..+5.45% | 1.0000 |
| Fast wave | 12 | -0.32% | -1.00..+0.36% | 1.0000 |

Only NVMe5 rounds 5, 8 and 9 were excluded, without replacement: paired raw
WRITE spreads were 10.65%, 10.63% and 18.23%, beyond the declared 10% screen.
The remaining 69/72 scenario-round comparisons passed the provenance, geometry
and host screens. NVMe5's point meets +3%, but its interval crosses zero and its
adjusted sign p fails the declared criterion. The screen therefore declines
this implementation. No primary workload establishes a gain or equivalence.

Persistent usable-pair arithmetic means were A/B useful WRITE 1,181.02/1,227.17
MB/s and READ 392.01/407.33 MB/s, against own raw WRITE 3,682.52/3,669.85 MB/s
and READ 1,222.32/1,218.11 MB/s. Useful READ and WRITE share each mixed replay's
elapsed interval and fixed operation counts; they are not independent service
wins. The paired normalized effect differs from the ratio of rounded means.
Configured NVMe5 bandwidth remains a RAM-backed model input, not physical NVMe
qualification or evidence identifying a RAM-bandwidth bottleneck.

## Secondary latency, lower I/O and resources

These are descriptive pointwise 95% paired intervals, outside the primary
family; do not turn them into extra family-qualified direction claims.
Persistent READ p95/p99 effects were -1.56% [-5.91,+3.00] and -1.87%
[-6.75,+3.26]; WRITE p95/p99 were -2.49% [-4.06,-0.89] and -0.17%
[-1.80,+1.49]. These do not establish a general tail-latency benefit.

Persistent lower WRITE bytes were +0.043% [-0.040,+0.126] and requests +2.03%
[+1.41,+2.65]. A/B arithmetic means were 34,861,056/34,876,075 bytes and
942.56/961.67 requests. Lower READ traffic was identical in these observed
windows: 36,864 bytes/nine requests. Cache-heavy fixture behavior is not a
universal READ result. There is no incremental lower-WRITE endurance-proxy
improvement; request reduction is not a reason to retain this candidate.

Fast WRITE QD1/QD4/QD8 normalized service estimates were -0.17% [-0.46,+0.11],
+0.66% [-0.43,+1.77] and -2.28% [-4.67,+0.17]. None triggers the predeclared
point <=-3% plus upper-bound-below-zero guard flag, but those intervals do not
prove noninferiority or equivalence. The wide QD8 latency/request intervals and
all other workload/latency/lower-I/O estimates remain in the readable analysis.

Native-process system time was +3.78% [+0.37,+7.31] on persistent NVMe5 and
+6.69% [+4.57,+8.86] on SATA. The host kernel lacks separate IRQ-time accounting,
and these counters exclude kworkers, so moving work into IPI/current-task
context changes attribution. No total kernel CPU saving or increase is proved.
RSS excludes kernel allocations. Native DWARF sizes add 4,224 requested bytes
per target and eight per BIO descriptor, including 64 callback cells of 64
bytes each; allocator rounding and physical RAM were not measured.

All pilot timed GC-victim deltas were zero. The separate loaded gate exercised
GC correctness, not sustained GC performance. Restored production retains its
previous owner GC/failure/drain and resource-pressure qualification. No swap
activation, reboot, physical backing or unrelated device removal occurred.

## Artifacts and next work

- [Readable full analysis and hashes](cpu-completion-x86-result.json)
- [Complete fixed pilot packet](cpu-completion-x86-pilot.json.gz): all 24 blocks,
  plan, source/module/helper hashes, byte oracles, screens, status snapshots,
  delivery counts and analysis/orchestration scripts.
- [Full unapplied as-run bundle](cpu-completion-x86-pilot.patch): product C,
  native probes, loaded gate and temporary development controls. It is a full
  alternative bundle against restored production, not an incremental patch
  atop the original draft. It is development-tested, not owner-qualified.

This pilot generated no owner report/history point or plot. A concurrent PASS
report `3190f39b1239` on baseline source `7ce0e2695d99` was fast-forwarded from
remote main during closeout; its different host digest keeps it separate and
it does not qualify the remote-completion candidate. This computer's history
still ends at source `545defa8`, report `3465b4c08987` (three reports/42 points).
Other computers and unqualified trials remain separate. Reopen this variant
only with a materially different, measured placement/batching opportunity;
do not repeat the same pilot until significance appears.

Reviewer stage #3 now follows: establish actual admission-lock contention before
choosing a lighter admission design, preserving FIFO, producer/owner references
and admission-close/drain synchronization. Prior lock/IRQ-restore stack frames
are not an exact removable lock budget. This host lacks CONFIG_LOCK_STAT, so
built-in lock-stat evidence is unavailable; any direct C timing must disclose
probe overhead and distinguish hold/wait wall from serialized CPU.
