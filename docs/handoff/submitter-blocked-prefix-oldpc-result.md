# Dispatch before a submitter-owned head: old-PC development result

Remove the candidate. Dispatching an older four-or-more-record staged prefix
before deferring a submitter-owned FIFO head did not improve the primary fast
QD8 service endpoint and inflated lower-WRITE requests at QD32 and serial QD8.
The original production C is restored byte-for-byte and rebuilt/exercised by
the final control. This is a fixed owned-null_blk development experiment, not
source qualification or physical-storage evidence.

## Hypothesis and ownership

Control source: `9e607c0a6f616c081f181e1068f46b9b91bea81b`.
Control `dm-target.c` SHA-256:
`278535d3e0530666f2347cdfc5f0f9e4e8005fdcf1c380fb9e5c94fae2c5dcde`.
Candidate SHA-256:
`bea5d71f496e07a463ffa5ddac99534f8cbad2b8e1dc89d9a8d5d16622abbd6f`.

The ordered worker normally returns after restoring its local FIFO ahead of
later incoming work when the head is still submitter-owned. Existing control
telemetry shows hundreds of such deferrals, but does not count how many have
an older staged prefix. The hypothesis was that dispatching a ready prefix
at that point could avoid idle service while the submitter finishes.

The candidate adds one helper called after the active-head branch restores the
local list and unlocks. It flushes only an already-staged work-conserving batch
of at least four records, with no in-flight lower WRITE, bulk enabled, normal
verification policy, accepting admission and no terminal failure. It leaves
the active head queued and untouched. Existing prefix publication/completion,
K=1, four-record floor, lower encoding, authority and fences remain unchanged.
Existing early-hand telemetry counts this additional dispatch site.

This was a performance hypothesis, not a demonstrated lifecycle bug. Retention
expiry already permits finite accepted preparation; the submitter releases
ownership and wakes the worker. A return at this gate is not proof of deadlock
or entirely removable idle time.

## Prospective experiment and verification

The plan fixes control / candidate / candidate / restored-control order, two
repeats per block, fast WRITE QD8 (primary), fast WRITE QD32, fast mixed, and
serial WRITE QD8. All 32 raw/swapz pairs use `make fast_test`, medium content,
submitter preparation on, hand width eight and the required enabled production
delta64 + DELTA64_SHUF8 + LZ4 stack. No delta64-off data is collected or pooled.

The primary practical floor is 5% higher swapz/raw normalized useful WRITE.
Guards allow at most 3% normalized service loss, 1% higher lower-WRITE bytes,
5% higher lower-WRITE requests, and 10% higher available READ/WRITE p99.
The fixed run count has no noisy replacements or significance-based extensions.

A direct C probe extracts the actual candidate helper and the real production
four-record constant. It exercises every count 0..64 plus six exclusion guards
and checks active-gate/splice/unlock/helper-call order. This scoped probe is
not an LKMM or whole-worker proof. All loaded pairs pass complete-image byte
verification; paired fixture, trace, payload, replay, operation and final-image
identities match. Normal kernel builds and native policy checks pass. Rebuilds
of both candidate and restored control emit the same existing status-function
2112-byte frame warning; these are not clean W=1/W=2 qualification claims.

## Screened results

Both second-candidate mixed observations fail the 11.0% raw-repeat spread
screen. Final-control serial-QD8 repeat 2 fails post busy/PSI screens
(29.1%/5.2%). Keep those three observations, exclude their comparisons, and
collect no replacements. All remaining matched raw spreads are within 10%.

Pair repeat numbers within blocks 1/2 and 3/4. The geometric effects below
use candidate/control ratios; useful WRITE is first normalized by each sample's
own raw control. Confidence intervals are unadjusted paired Student-t intervals
on log ratios. No comparison-family-wide significance is claimed.

| Scenario | Usable pairs | Normalized WRITE change | Paired 95% interval | Lower request change |
| --- | ---: | ---: | ---: | ---: |
| Fast WRITE QD8 | 4 | -3.7% | -6.2% to -1.2% | +1.8% |
| Fast WRITE QD32 | 4 | +1.8% | -0.5% to +4.1% | +10.0% |
| Fast mixed | 2 | +4.5% | -26.7% to +49.0% | -2.0% |
| Serial WRITE QD8 | 3 | +2.4% | -0.7% to +5.6% | +43.4% |

Fast-QD32 request inflation has interval +5.2% to +15.0%; serial-QD8 request
inflation has interval +35.0% to +52.4%. Both violate the 5% request guard.
Fast-QD8 lower bytes change +0.20%; its WRITE p99 changes +1.2% (-5.4% to
+8.3%). Fast-QD32 bytes change +0.80% (+0.37% to +1.23%) and p99 +3.9%
(-7.0% to +16.0%). Serial-QD8 bytes fall 0.87% and WRITE p99 falls 15.5%,
but neither offsets its request inflation under the declared acceptance rules.
Mixed service and latency remain unresolved with only two usable comparisons.

Among screened matched observations, arithmetic fast-QD8 means are 65.27 ->
63.74 MB/s, 1009 -> 1026.75 lower requests, and 5.5 -> 22.5 early-hand closes.
Serial QD8 reaches 520 early-hand closes versus zero in its controls and emits
759 versus 529 requests. This proves the additional dispatch site engages and
shows its geometry cost. It does not establish a total CPU/critical-path budget.

## Decision and preserved evidence

Keep the existing submitter-owner return and release/acquire handoff. Do not
reopen this exact prefix-flush candidate solely because some idle counters
fall. Avoiding a wait can split useful aggregation and lose service; future
work needs a distinct measured mechanism. No helper, runtime knob, permanent
counter, test relaxation or alternative public interface remains.

Local artifacts are under `build/optimization-round/submitter-prefix-oldpc/`:
prospective plan, four block logs/JSON files, exact control and candidate C,
candidate patch/hash, native probe/result, analysis script and JSON/text,
history-refresh log and SHA-256 manifest. The restored source is clean and
owned DM mappings are removed. `test_results.json` is unchanged; this pilot
never enters qualified history. The exact-computer history still ends at
`b336754e3acb`, report `8b67a9425025`. The broader raw-service goal remains
unmet, including the fast-QD8 deficit under both policies.
