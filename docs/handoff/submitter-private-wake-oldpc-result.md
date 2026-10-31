# Private-FIFO submitter wake suppression: old-PC result

Remove the candidate and retain the original wake policy. Suppressing release
wakes while the ordered worker owns a private FIFO did not establish the
required fast-QD32 service or deferral benefit. Production C is restored
byte-for-byte and rebuilt/exercised by the final control. This is a fixed
owned-null_blk development pilot, not source or physical-media qualification.

## Mechanism and proof scope

Control source: `1b35c3eef4207bc1604d260d85e7ab87dab2a4ea`.
Control `dm-target.c` SHA-256:
`278535d3e0530666f2347cdfc5f0f9e4e8005fdcf1c380fb9e5c94fae2c5dcde`.
Candidate SHA-256: `52ab879b5cbfa2c4aa66a2b67e4f30bf5f32441ec29b678c5785d0bf0f003882`.

ID166 preserved every release wake when incoming was empty. This distinct
candidate wakes only for a nonempty incoming FIFO whose head is no longer
submitter-active. Empty incoming means the releasing entry is already consumed
or belongs to the running worker's private list. The worker's locked ownership
recheck pairs with that decision: a release before the recheck causes a retry;
a release after it observes the restored ready head and wakes the owner.
The submitter selects a queued head afresh under queue_lock and never reuses
the original released descriptor/prepared pointer. Any retained version would
need the governing post-release prose to recognize that protected lookup.

The direct C probe extracts the actual notification/gate blocks and tests
empty/private plus nonempty incoming lists, retained/nonretained policy, and
release before recheck, during handback and afterwards. A missing-recheck
mutant fails the lost-wake assertion. This is controlled interleaving evidence,
not an LKMM or whole-worker proof. The candidate changes no representation,
packing threshold, K=1 depth, authority or acknowledgement contract.

## Fixed experiment

The prospective plan fixes control / candidate / candidate / restored-control,
two repeats each, fast WRITE QD32 (primary), fast QD8/QD4/mixed, and serial
QD32. All 40 raw/swapz pairs run through `make fast_test` with medium content,
submitter preparation on, hand width eight and the enabled production
delta64 + DELTA64_SHUF8 + LZ4 stack. Ordinary WRITE scenarios use the existing
Python-threaded persistent replay; mixed keeps its existing protocol. This is
not a driver comparison and provides no causal GIL attribution.

Primary acceptance requires at least 5% higher raw-normalized useful WRITE and
25% fewer owner deferrals. Guards allow at most 3% nonprimary service loss,
1% more lower bytes, 5% more lower requests and 10% higher available READ/WRITE
p99. The fixed count has no replacements or significance-based extensions.

All 40 pairs pass complete-image byte verification. Paired source, fixture,
trace, payload, engine/mode, operation and final-image identities match.
Normal module builds/native policy checks pass; both candidate and rebuilt
control emit the existing 2112-byte status-function frame warning. No clean
W=1/W=2 or full owner qualification is claimed for this removed variant.

Four observations fail the fixed screen: candidate block 2 mixed repeats have
12.9% raw-repeat spread; final-control QD8 repeats have post busy 38.0/38.8%
(the second also has 5.3% CPU PSI). Exclude their comparisons, preserve the
measurements and collect no replacements. All remaining matched raw spreads
are within 10%.

Effects are geometric candidate/control ratios, matched by repeat in blocks
1/2 and 3/4. Useful WRITE is normalized by each observation's own raw control.
Intervals are unadjusted paired 95% Student-t intervals on log ratios; no
family-wide significance, equivalence or physical-wear claim follows.

| Scenario | Usable pairs | Normalized useful WRITE | 95% interval |
| --- | ---: | ---: | ---: |
| Fast WRITE QD32 | 4 | -2.1% | -5.0% to +0.8% |
| Fast WRITE QD8 | 2 | +3.9% | -22.1% to +38.5% |
| Fast WRITE QD4 | 4 | +2.1% | -5.3% to +10.1% |
| Fast mixed | 2 | +2.8% | -47.3% to +100.5% |
| Serial WRITE QD32 | 4 | -0.2% | -1.6% to +1.3% |

Primary deferrals change -4.5% (-11.1% to +2.6%), short of the required 25%
reduction. Primary lower requests change +1.0% (-3.0% to +5.2%), bytes +0.12%
(-0.17% to +0.41%), WRITE p99 +3.8% (-0.9% to +8.6%), and accepted-work idle
+4.2% (-11.3% to +22.5%). The primary service/deferral targets fail and several
guard bounds remain unresolved. QD8 deferrals have a -43.7% point estimate but
only two usable comparisons and interval -79.6% to +56.0%; that does not rescue
the primary result.

## Decision and evidence

Restore the original release wake and handback code. Both visible-queue and
private-FIFO suppression variants have now failed to establish their intended
service benefit. Do not add another wake predicate without causal evidence for
a specific unnecessary-wake population and a complete progress proof. These
results do not identify every deferral's wake source, a removable CPU budget,
or a universal hardware effect. Further work should address a materially
different bottleneck while preserving the project's service and lower-I/O goal.

Local evidence is under `build/optimization-round/submitter-private-wake-oldpc/`:
plan, exact source copies/patch/hashes, four logs/JSON reports, native probe and
negative-control artifacts, analysis scripts/JSON/text, history refresh and
SHA-256 manifest. No runtime knob, counter, test relaxation or candidate C
remains. Owned mappings are removed. `test_results.json` is unchanged, and
these trials never enter qualified history; the refreshed exact-computer
series still ends at `b336754e3acb`, report `8b67a9425025`. The broader useful
READ/WRITE and lower-I/O goal remains incomplete.
