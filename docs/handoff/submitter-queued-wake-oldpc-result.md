# Queued-head submitter wake suppression: old-PC result

Remove the candidate. Suppressing a submitter-release wake only while the
visible incoming FIFO head remains submitter-owned did not establish either
the required fast-QD32 service gain or a reduction in owner deferrals. Original
production C is restored byte-for-byte and rebuilt/exercised by the final
control. This is owned-null_blk development evidence, not source qualification.

## Candidate and race boundary

Control source: `b01577f694b5f85da947443ffd436fc1b339a330`.
Control `dm-target.c` SHA-256:
`278535d3e0530666f2347cdfc5f0f9e4e8005fdcf1c380fb9e5c94fae2c5dcde`.
Candidate SHA-256: `8c68c44795458b87d7e5678f60fdd78b2300b21436e599031b49e95a5cea2e25`.

After releasing its original descriptor, the submitter takes `queue_lock` and
selects the current incoming head afresh. It suppresses the wake only if that
queued head is still submitter-active; empty incoming retains the original
wake because the worker may own a private local FIFO. This does not reuse the
released descriptor pointer. A retained change would need the governing prose
to distinguish a lock-protected queued-head lookup from stale descriptor use.

The worker also rechecks the active gate under `queue_lock` before FIFO
handback/return. Without that recheck, a local head could release ownership,
find a different active incoming head and suppress its wake, followed by the
worker returning on a stale active observation. The recheck retries instead;
a release after the recheck sees the restored FIFO head under the same lock.
Packing/dispatch thresholds, K=1, representations and acknowledgement rules do
not change. There is no new runtime parameter or telemetry field.

A native C probe extracts the actual candidate notification and active-gate
blocks. It checks active/ready/empty incoming lists, retained/nonretained wake
policies, and release before the locked recheck, during handback, and after
handback. A mutant removing the locked recheck fails the lost-wake assertion.
The initial probe fixture had a dangling local list anchor; its corrected
single-owner fixture and failed initial build are both preserved. These are
controlled interleavings, not an LKMM or whole-worker proof.

## Fixed comparison

The prospective plan fixes control / candidate / candidate / restored-control,
two repeats each, fast WRITE QD32 (primary), fast QD8, fast QD4, fast mixed and
serial QD32. All 40 raw/swapz pairs use `make fast_test`, medium content,
submitter preparation on, hand width eight and the required enabled
production delta64 + DELTA64_SHUF8 + LZ4 stack. The primary practical floor is
5% higher swapz/raw useful WRITE with fewer owner deferrals. Guards allow at
most 3% nonprimary service loss, 1% more lower bytes, 5% more requests and
10% higher available READ/WRITE p99. No replacement observations are collected.

All 40 pairs pass complete-image byte verification. Paired source, fixture,
trace, payload, replay, operation counts and final-image identities match.
Normal builds and native policy checks pass; candidate and rebuilt control
both emit the existing status-function 2112-byte frame warning. This is not a
clean W=1/W=2 or full `make test` qualification claim.

Six observations fail the fixed screen: candidate block 3 QD4 repeat 2
(pre busy 41.6%, PSI 8.1%), its two mixed repeats (raw spread 20.9%), final
control QD8 repeat 2 (pre busy 25.3%), and its two mixed repeats (raw spread
13.8%). In addition, the first control/candidate mixed repeat 2 comparison
fails the matched raw spread limit. Preserve every observation and exclude
those comparisons without replacement.

Effects are geometric candidate/control ratios, paired by repeat within
blocks 1/2 and 3/4. Useful WRITE is normalized by each observation's own raw
control. Intervals are unadjusted paired 95% Student-t intervals on log ratios;
no family-wide significance or equivalence is claimed.

| Scenario | Usable pairs | Normalized useful WRITE | 95% interval |
| --- | ---: | ---: | ---: |
| Fast WRITE QD32 | 4 | -0.2% | -6.6% to +6.5% |
| Fast WRITE QD8 | 3 | +4.3% | -7.5% to +17.6% |
| Fast WRITE QD4 | 3 | -1.0% | -18.3% to +20.0% |
| Fast mixed | 1 | -1.3% | unavailable |
| Serial WRITE QD32 | 4 | +0.7% | -1.2% to +2.6% |

Primary owner deferrals change +1.4% (-6.1% to +9.6%); lower requests change
-0.4% (-4.4% to +3.9%), lower bytes +0.13% (-0.30% to +0.56%), and WRITE
p99 +0.8% (-6.7% to +8.9%). Primary service and mechanism benefits remain
unproved; other service/latency guards are unresolved. A lower point estimate
elsewhere cannot establish a retained optimization.

## Decision and limits

Restore the original release wake and active-head handback. This result closes
this particular visible-queued-head suppression policy; do not extend it to seek a favorable
interval. It does not test suppressing wakes for an empty incoming
list/private local FIFO, which the candidate explicitly preserves. The source
shows that structural limitation, but the current telemetry does not attribute
deferrals to individual wake causes or count that empty-list path. Reopening
requires a distinct measured mechanism and renewed lost-wake proof.

Local evidence is in `build/optimization-round/submitter-wake-oldpc/`: plan,
exact control/candidate C and patch/hashes, four logs and JSON reports, native
probe and negative-control artifacts, analysis JSON/text and scripts, history
refresh and SHA-256 manifest. No candidate code, test relaxation, knob or schema
remains. Owned mappings are removed and `test_results.json` is unchanged.
Development samples are excluded from qualified history; its latest point
remains source `b336754e3acb`, report `8b67a9425025`. The broader useful-service
and lower-I/O goal remains incomplete.
