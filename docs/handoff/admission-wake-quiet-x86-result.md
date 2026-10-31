# Native-host admission-wake comparison: declined and restored

The new twelve-round comparison finished all 24 source blocks/144 owned pairs;
all 288 raw/target arm byte oracles passed. The out-of-lock owner-notification
candidate did not meet the declared retention screen. Production C and all
temporary test/helper changes are restored exactly to qualified source
`545defa8`, report `3465b4c08987`. Restored C SHA-256 is
`78f2d7de073a644c9c4182a0865e57ebdfce8b6d07cc02a4ae5578a8cd3d569a`.
The restored normal build succeeds and no owned DM devices remain.

This is a native x86_64 Lenovo 82BG/i7-1185G7 host; systemd-detect-virt reports
none. The competing tracing benchmark had exited before the new series. The
standard counter reader's steal field does not imply a VM. RAM null_blk models
still do not establish physical NVMe fidelity or identify RAM bandwidth as the
bottleneck.

## Prospective protocol and primary results

The [new prospective plan](admission-wake-quiet-x86-plan.json) fixed twelve
AB/BA rounds, raw/target order reversal, six workloads, matched inputs and
source/helper hashes, three primary useful-WRITE/raw endpoints, +3% practical
floor, family-adjusted tests, minimum nine usable pairs and exclusions without
replacement. A is unchanged qualified production; B is the archived candidate.
Both retain existing async/submitter preparation, medium content and delta64 off.
No source changed during the run.

Two entry attempts stopped before any device or benchmark observation because
the first startup window failed screening; their records are preserved. Before
the first performance sample, a committed amendment added a fixed two-second
interpreter/import settling interval before three quiet windows. Thresholds and
sample count were unchanged. Final entry checks measured 3.2%, 3.8% and 3.8%
busy, low CPU PSI and no steal. This series does not pool, replace or selectively
reuse observations from the preceding noisy pilot.

| Mixed workload | Usable pairs | Normalized WRITE change | 98.3333% family interval | Adjusted sign p |
| :--- | ---: | ---: | :--- | ---: |
| NVMe5 persistent | 7 | +1.63% | -6.43..+10.39% | 1.000 |
| SATA wave | 11 | -2.18% | -6.52..+2.36% | 1.000 |
| Fast wave | 11 | -0.09% | -0.68..+0.51% | 1.000 |

Seven of 72 scenario-round pairs were excluded. NVMe5 rounds 1, 2, 5, 9 and 10
had paired raw-WRITE spreads 15.31%, 16.85%, 17.25%, 10.39% and 15.83%; round
1 also had a NOISY baseline. SATA round 7 had a NOISY baseline, and fast mixed
round 2 had a NOISY candidate. The other 65 comparisons met the declared
screens. Screening is a heuristic, not proof of an idle host or independent
chronological observations.

NVMe5 misses both the +3% point floor and minimum nine usable pairs; its interval
crosses zero and its adjusted sign test also fails. No primary comparison
establishes a gain, regression or equivalence. No replacement samples or further
confirmation were collected for this implementation.

For the seven usable persistent pairs, arithmetic means A/B were useful WRITE
1,115.65/1,134.29 MB/s and READ 370.31/376.50 MB/s. Own raw controls were WRITE
3,490.17/3,492.96 and READ 1,158.47/1,159.40 MB/s. The paired normalized estimate
differs from a ratio of rounded means. Useful READ/WRITE share elapsed time and
fixed operation counts; they are not independent service gains.

## Secondary trade-offs and scope

All following intervals are descriptive pointwise 95%, not extra family-qualified
claims or proof of practical improvement/noninferiority. Persistent READ p95
was -7.94% [-14.90,-0.42], READ p99 -4.50% [-9.05,+0.28], WRITE p95 -2.64%
[-4.85,-0.39] and WRITE p99 -7.11% [-17.57,+4.68]. Exploratory p95 directions
do not satisfy the declared service criterion. SATA READ p99 was +15.41%
[-4.84,+39.98]; neither a general latency benefit nor regression is established.
All workloads' p95/p99 observations remain in the packet.

Persistent lower WRITE bytes were +0.018% [-0.139,+0.176] and requests +0.018%
[-1.075,+1.123]. A/B means were 34,862,226/34,868,663 bytes and
957.43/957.71 requests. Lower READ means were identical in these observed windows:
35,693.71 bytes/8.71 requests. No incremental lower-WRITE endurance-proxy benefit
is established. Fast WRITE QD1/QD4/QD8 normalized service estimates were +0.28%
[-0.20,+0.76], +0.16% [-0.84,+1.18] and -0.04% [-2.09,+2.05]. These intervals
do not prove equivalence or whole-workload safety.

Native-process system CPU was -4.18% [-7.01,-1.27] for persistent NVMe5, but
kernel workers are excluded and interrupt/scheduling attribution can differ.
Total kernel CPU saving is not established. The candidate introduces one target
atomic counter and its operations, no per-I/O allocation or new I/O buffer;
struct/allocator rounding and physical RAM were not measured. RSS excludes
kernel allocations. Every timed GC-victim delta was zero. The earlier loaded
GC/fault/suspend checks are development correctness, not sustained GC performance
or owner/ID36 qualification. No swap activation, physical backing, reboot or
unrelated device removal occurred.

## Artifacts and disposition

- [Full readable analysis, means and exclusions](admission-wake-quiet-x86-result.json)
- [Complete new-series packet](admission-wake-quiet-x86-pilot.json.gz): all 24
  blocks, entry attempts, fixed plan, source/module/helper/input hashes, screens,
  status snapshots and scripts.
- [Unchanged unapplied candidate](admission-wake-x86.patch), with separate
  [development validation](admission-wake-x86-validation.json.gz) and
  [concurrent lifetime review](admission-wake-lifetime-review.json.gz).

The candidate is removed rather than promoted on current evidence. Reopening
needs a materially different measured opportunity or protocol, not more samples
until significance appears. Both prior and new series remain intact. This round
created no owner report/history point or plot; this native computer's qualified
history still ends at source `545defa8`, report `3465b4c08987`. Other computers
and unqualified trials remain separate.
