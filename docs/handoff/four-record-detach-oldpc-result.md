# Four-record async detachment: old-PC development result

The candidate did not establish a useful-service gain and is removed. Production
C is restored byte-for-byte to the control. This is a fixed owned-null_blk
development pilot, not source qualification, a causal regression claim, or
physical-device evidence.

## Hypothesis and design

Control HEAD: `7d3fa725db04e3b563bd779f1113146b7f51ef29`; its production C is
the owner-qualified `b336754e3acb` code (report `8b67a9425025`). The candidate
changes only `count > SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS` to `>=` in
`swapz_flush_window()`'s async-detach predicate. The hypothesis was that allowing
four-record detachment without an unclaimed preparation descriptor would let
the ordered worker stage accepted QD8 followers and learn a wider burst.
K=1, the existing immutable run, FIFO publication, fences and completion
ownership are unchanged.

The prospective local plan fixes control/candidate/candidate/control source
order, two repeats per block, and four scenarios: fast WRITE QD8 (primary),
fast WRITE QD4, fast mixed QD32 and serial WRITE QD8. Each invocation uses the
existing `make fast_test` loop with medium content, delta64 off, submitter
preparation on, and the default eight-record hand. All scenarios retain their
ordinary device models. There are four observations per policy/scenario,
32 raw/swapz pairs total. No replacement runs were collected.

The primary practical floor is a 5% improvement in swapz/raw useful WRITE.
Guard scenarios permit at most 3% normalized service loss, 1% more lower WRITE
bytes per useful byte, and 10% higher READ/WRITE p99. Host-screen failures and
paired raw drift above 10% exclude comparisons. This bounded pilot can reject
an unsupported candidate; it cannot promote production without owner `make test`.

## Evidence

All 32 pairs passed exact-byte checks. Fixture and trace hashes agree within
each scenario across all blocks; effective module policies match the plan.
Six observations are excluded: control block 1 QD8 repeat 2, QD4 repeat 1,
and serial QD8 repeat 1; candidate block 2 QD8 repeat 1; both final-control
mixed repeats. The first four fail quiet-host CPU/PSI screens; the final mixed
controls fail the 10% raw-repeat screen (11.6% spread). Excluded data remains
in the artifacts.

Pair the first control block with the first candidate block and the second
candidate block with the final control block, matching repeat numbers. The
effect is the geometric mean of paired candidate/control ratios. Useful WRITE
is first normalized by its own raw control. Intervals are ordinary paired
95% Student-t intervals on log ratios, exponentiated back to percent changes;
small n produces wide intervals. No family-wide significance is claimed.

| Scenario | Usable pairs | Normalized WRITE change | 95% interval |
| --- | ---: | ---: | ---: |
| Fast WRITE QD8 | 2 | +0.4% | -37.8% to +61.9% |
| Fast WRITE QD4 | 3 | -4.4% | -11.8% to +3.6% |
| Fast mixed | 2 | +1.4% | -36.9% to +63.0% |
| Serial WRITE QD8 | 3 | -0.3% | -2.1% to +1.6% |

QD4's WRITE-p99 point estimate increases 22.8% (interval -8.8% to +65.4%).
Neither the primary benefit nor the service/latency guards is established.
These intervals do not establish equivalence or a causal service regression.

Mechanistic observations across **all** four observations per policy, including
excluded ones: QD8 synchronous four-record commits fall from 790 to zero;
async runs rise from 138.8 to 691.5. Window count falls 968 to 828 and lower
requests 975.5 to 836.5, but accepted-work idle grows 21.5 to 77.8 ms. These
diagnostics prove the candidate engaged and describe its packing/idle trade-off;
they are not screened performance estimates. More asynchronous activity and
fewer requests alone do not establish the project's useful-service goal.

## Decision and artifacts

Restore the qualified strict greater-than-four/backlog predicate. No candidate
runtime knob, production counter, source-contract relaxation or new public
test interface is retained. The final control block rebuilt and exercised the
restored C. Do not repeat this variant until significance appears; a new
proposal needs a different measured mechanism.

Local evidence is under `build/optimization-round/four-record-detach-oldpc/`:
`plan.json`, four block logs and JSON reports, `candidate.patch`,
`candidate.sha256`, `control-dm-target.c`, `analysis.json` and `SHA256SUMS`.
Control C SHA-256: `278535d3e0530666f2347cdfc5f0f9e4e8005fdcf1c380fb9e5c94fae2c5dcde`.
Candidate C SHA-256: `840a8f619e009ebb88909a883c9d84d1befb35f64ea10f1f7c5d6a81ec780766`.
These dirty development variants never enter `test_results.json` or qualified
host history; the latest owner-qualified point remains `b336754e3acb`.
