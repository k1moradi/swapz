# Sampled admission hold work: notification hypothesis

The fixed diagnostic completed twelve source blocks/48 owned pairs, with all
96 arm byte oracles passing. It sampled one in 64 accepted admissions under the
original queue lock, splitting pre-notification work from the owner-notification
branch. Submitter-claimed admissions were counted separately because they skip
that notification. The initial draft mistakenly placed the sample before lock
acquisition; it was stopped during unchanged baseline A, which finished safely,
and no diagnostic B ran. That technically invalid baseline-only attempt was
excluded before restarting the corrected fixed plan. A new source contract
checks sample placement. No noisy diagnostic observations were replaced.

Six rounds alternated AB/BA with raw-first in odd rounds, target-first in even
rounds. A was unchanged qualified production; B added only the systematic sample
and status counters. Medium inputs, delta64 off, workload hashes and CPU geometry
matched. B passes all 93 source contracts; A passes 92 with the temporary probe
contract skipped. The probe is removed, and production/native/development helpers
are restored exactly to qualified source `545defa8`, report `3465b4c08987`.

| Complete-session workload | Owner-wake samples/session | Pre-notification mean | Notification mean |
| :--- | :--- | :--- | :--- |
| NVMe5 persistent mixed | 126..141 | 30.6..53.2 ns | 494.4..683.8 ns |
| SATA mixed | 122..138 | 32.9..55.2 ns | 583.2..936.0 ns |
| Fast mixed | 134..138 | 35.2..45.3 ns | 545.5..831.4 ns |
| Fast WRITE QD8 | 32 | 19.0..32.8 ns | 337.1..487.9 ns |

Each mixed session had 368 total samples from 23,615 accepted admissions; QD8
had 116 from 7,485. Submitter-claimed samples account for the remainder. Their
pre-notification means ranged 121.0..224.3 ns and skipped-notification means
13.5..21.4 ns. Back-to-back clocks averaged 13.2..21.4 ns per sample, retained
as overhead context and never subtracted as an exact correction. Times are
partial IRQ-disabled hold wall, not exact CPU, lock wait, total acquisition/hold
cost or a removable serialized budget. Sample-counter updates and the final
unlock/IRQ restore are outside the measured end. Counters and clocks perturb
lock occupancy. Systematic accepted-sequence sampling is not random sampling;
complete sessions include setup and verification rather than just timed work.

Perturbation remains unresolved. Four of six NVMe5 pairs failed the declared
10% raw-drift screen; SATA round 2 was NOISY; fast mixed round 2 was NOISY and
failed raw drift. Descriptive paired normalized-service estimates and pointwise
95% intervals were NVMe5 n2 +5.49% [-52.17,+132.64], SATA n5 +2.14%
[-5.76,+10.72], fast mixed n5 +2.97% [-9.44,+17.08], QD8 n6 -1.34%
[-3.32,+0.68]. These establish neither a product change nor negligible overhead
or equivalence. No fresh owner qualification or history plot was generated.
Other hosts and these diagnostic trials remain outside this computer's
qualified history, which still ends at report `3465b4c08987`.

- [Complete packet, scripts, logs and source/module hashes](admission-hold-x86.json.gz)
- [Readable analysis and exclusions](admission-hold-x86-result.json)
- [Unapplied diagnostic bundle](admission-hold-x86.patch)

## Bounded production hypothesis to investigate

The owner-notification branch dominates the sampled non-submitter critical
section on the perturbed implementation. Investigate moving that notification
outside `queue_lock` while retaining FIFO insertion, acceptance checks and
producer/owner reference publication under the original lock. This is a
hypothesis, not a proven cost or performance opportunity on unchanged code.

A candidate must cache every BIO-derived decision before unlock: the ordered
owner may complete and free the descriptor before notification returns. It must
hold a target lifetime reference acquired under the admission-close lock;
drain must close admission, join all such notification tails, then drain the
queues. The releasing caller must make its release the final target access.
Submitter-claimed descriptors already have their separate lane/lifetime join;
that path must remain intact. Preparation-worker wake ownership cannot be moved
outside its required queue-lock protection merely because owner notification
can be separated. Add actual-body native interleavings for close between unlock
and wake, upper completion before wake returns, and no enqueue after drain can
pass; then exercise loaded fault/suspend/drain before a fixed service pilot.
