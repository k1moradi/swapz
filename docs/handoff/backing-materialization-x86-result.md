# Native RAM-backing sensitivity: fixed study complete

Production C was unchanged throughout. Sixteen fixed condition blocks/96 owned
pairs completed; all 192 raw/target arm byte oracles passed. Every materialized
pair verified a full 64MiB completed direct write to EACH newly owned device,
with zero outstanding I/O, before target setup and useful-work timing. The two
temporary helper changes are removed. Product and test source again match
qualified source `545defa8`, report `3465b4c08987`; production C SHA-256 is
`78f2d7de073a644c9c4182a0865e57ebdfce8b6d07cc02a4ae5578a8cd3d569a`.
No test mappings remain. This is a native x86 host, not a VM.

## Fixed protocol and primary results

[The prospective plan](backing-materialization-x86-plan.json) specified eight
FM/MF rounds, two repetitions per condition block and three workloads. F keeps
the canonical fresh-backing setup. M materializes BOTH the raw and swapz lower
devices before setup. Target/allocator state, workload/input hashes, CPU and
service geometry remain matched. Two log observations are averaged inside each
condition block before pairing M/F by round; repetitions are not independent
rounds. The primary endpoint is change in useful swapz WRITE divided by its own
raw WRITE control. Direction requires at least seven usable rounds, absolute
point effect >=5%, a 98.3333% family interval excluding zero and adjusted exact
two-sided sign p<0.05 across three comparisons.

| Workload | Usable rounds | Normalized M/F effect | Family interval | Adjusted sign p |
| :--- | ---: | ---: | :--- | ---: |
| NVMe5 persistent | 5 | +9.07% | +0.78..+18.04% | 0.1875 |
| SATA wave | 7 | +1.10% | -1.84..+4.13% | 1.0000 |
| Fast wave | 8 | -0.19% | -0.85..+0.47% | 1.0000 |

Four of 24 scenario-round comparisons were excluded, without replacement.
NVMe5 rounds 2, 5 and 8 failed the within-materialized-condition raw-repeat
spread screen (>10%). SATA round 5 had one materialized repetition with a noisy
pre-window (47.8% busy). These are protocol exclusions, not exact causal
attribution of noise. Cross-condition raw-rate changes were outcomes, never
screened away. The first technical attempt contained only an F block and an M
native-preflight failure; its records are separate and do not enter this study.
Corrected helper hashes were frozen before restarting, without examining a
paired treatment effect or reusing observations from attempt 1.

The persistent estimate is suggestive, with all five usable paired effects
positive, but it misses minimum n=7 and the adjusted sign criterion despite the
positive paired-t interval. No primary endpoint meets every declared direction
criterion. There is no equivalence, product improvement or confirmed physical-
storage result. No samples were added for significance. Interval/model
assumptions and chronological host dependence remain limits.

## Absolute service and secondary trade-offs

Arithmetic means on the same usable rounds are shown below. The paired log
estimates differ from ratios of these rounded means. READ/WRITE share elapsed
mixed-replay time and fixed operation counts; they are not independent wins.

| Workload/state | Raw WRITE MB/s | Swapz WRITE MB/s | Raw READ MB/s | Swapz READ MB/s |
| :--- | ---: | ---: | ---: | ---: |
| NVMe5 F | 3,670.98 | 1,160.05 | 1,218.49 | 385.05 |
| NVMe5 M | 3,583.96 | 1,235.23 | 1,189.60 | 410.00 |
| SATA F | 414.08 | 337.30 | 137.44 | 111.96 |
| SATA M | 418.28 | 344.47 | 138.84 | 114.34 |
| Fast F | 62.89 | 118.70 | 20.88 | 39.40 |
| Fast M | 63.01 | 118.69 | 20.91 | 39.40 |

Secondary intervals below are descriptive pointwise 95%, not extra
family-qualified claims. Persistent absolute swapz WRITE is +6.48%
[+5.61,+7.37], while raw WRITE is -2.37% [-8.15,+3.78]. Thus the normalized
+9.07% is not wholly an absolute target-service effect. Persistent target READ
p95/p99 effects are -8.02% [-10.57,-5.39] and -4.45% [-6.81,-2.03]; WRITE
p95/p99 are -8.44% [-9.38,-7.50] and -8.76% [-11.98,-5.42]. SATA absolute
swapz WRITE is +2.13% [+1.49,+2.76], raw WRITE +1.01% [-1.08,+3.15]. Fast
absolute swapz WRITE is -0.008% [-0.397,+0.383], but WRITE p99 is +5.79%
[+2.54,+9.15]. Do not summarize materialization as a universal latency win.

Independent target lower WRITE bytes/requests remain unresolved: persistent
-0.032% [-0.194,+0.131] / +0.191% [-0.344,+0.729], SATA -0.040%
[-0.156,+0.076] / -0.020% [-0.159,+0.119], fast -0.066% [-0.161,+0.030] /
-0.288% [-1.292,+0.727]. No lower-WRITE endurance-proxy improvement is
established. All raw/target p95/p99, lower READ/WRITE and resource observations
and paired secondary estimates remain in the packet.

## Interpretation and next C work

The ID157 profile observed null_blk page allocation/initialization and locking
beneath swapz submission. This matched treatment changes lower memory residency,
initialization/cache state and setup work; it does not isolate exact allocation
CPU or remove all lower-backend cost. It writes 128MiB of owned backing data per
pair outside useful timing. Extra kernel residency, allocator/radix metadata and
physical RAM were not measured; native process RSS omits those pages. Process
CPU excludes kernel workers, so no total CPU saving is established. Every timed
GC-victim delta was zero; this does not qualify sustained GC behavior.

Keep canonical fresh-device qualification and its history unchanged. Materialized
backing is a separate sensitivity/control protocol, not a way to relabel the
existing product as faster or claim NVMe fidelity. RAM bandwidth saturation is
not demonstrated. Do not prewarm/retune only one arm. A mechanism/residual-owner
profile can distinguish backing allocation from remaining product C work; select
further C changes from that actual operation evidence rather than the broad
pack/submit label. Do not extend this fixed study until significance appears.

## Artifacts

- [Complete analysis and exclusions](backing-materialization-x86-result.json)
- [Complete fixed study packet](backing-materialization-x86-pilot.json.gz): all
  sixteen blocks, input/source/helper/module hashes, model notes, oracles,
  entry checks, scripts and the separately marked failed technical attempt.
- [Unapplied private treatment bundle](backing-materialization-x86.patch).

No production implementation changed, no owner report/history point or plot was
generated, and no swap activation, physical backing, reboot or unrelated device
removal occurred. This computer's identified qualified history still ends at
source `545defa8`, report `3465b4c08987`; keep other machines and this study separate.


During closeout, remote main advanced with all-five-stage PASS reports
`9d30bf11` (different aarch64 host identity) and `42c6c9a1` (different x86_64
host identity), both on baseline source `4233d8e7`. They were fast-forwarded
without altering the study or product source. Their qualification/history stays
separate; neither qualifies this materialization protocol as a product gain.
