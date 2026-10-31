# Sixteen-record early hand: production-stack development result

Keep the production eight-record early hand. Sixteen reduces fast-QD32
fragmentation, but this fixed pilot does not establish the required useful
service gain. No production C, default, or qualification report changes follow
from this result. This is owned-RAM development evidence, not physical-device
or NAND-endurance evidence.

## Protocol and provenance

Source: `99fa60bbb4074b07fd4aa395694e3a68bfe8901b`, clean throughout all four
blocks. Production `dm-target.c` SHA-256:
`278535d3e0530666f2347cdfc5f0f9e4e8005fdcf1c380fb9e5c94fae2c5dcde`.
Only the existing read-only `HAND_RECORDS` development selector differs.
K=1, submitter preparation, the four-record dry-service boundary, medium
content, and device/trace geometry remain fixed.

The current production delta64 + DELTA64_SHUF8 byte shuffle + LZ4 stack is
enabled throughout; every swapz arm reports rescue 1 and second-LZ4 acceleration
4. The ordinary medium fixture records zero delta64 attempts. This evaluates
dispatch under the required enabled policy; it cannot establish service for a
delta64-positive population. The earlier delta64-off pilot was superseded by
the owner-required benchmark protocol and is not pooled with these results.

The prospective plan fixes hand8 / hand16 / hand16 / hand8 block order,
two repeats per block, and fast WRITE QD32, serial WRITE QD32, fast mixed,
and fast WRITE QD8 scenarios. All four blocks use `make fast_test`. There are
32 raw/swapz pairs and no replacement observations. This is a policy-selector
comparison on one source, not a production-source A/B.

The primary endpoint requires at least 5% higher swapz/raw normalized useful
WRITE, at least 10% fewer lower-WRITE requests, and no more than 1% higher
lower-WRITE bytes. Guards allow at most 3% normalized service loss, 1% higher
bytes, and 10% higher available READ/WRITE p99. Unresolved guard confidence
cannot establish safe promotion. Exact-source owner `make test` remains
necessary for any retained production change.

## Screened comparison

All 32 pairs pass the complete-image byte oracle. Source, fixture, trace,
payload stream, replay engine/mode, operation counts and final-image hashes
match between each paired policy observation. Three observations fail the
fixed quiet-host screen: first hand8 block serial-QD32 repeat 1 (post busy
25.3%), second hand16 block serial-QD32 repeat 2 (30.4%), and final hand8
block fast-QD8 repeat 2 (34.2%). Keep them in the local artifacts but exclude
their matched comparisons. No remaining matched raw spread exceeds 10%.

Pair repeat numbers within blocks 1/2 and 3/4. Effects below are geometric
means of hand16/hand8 ratios; useful WRITE is first normalized by each
observation's own raw control. Intervals are paired 95% Student-t intervals
on log ratios, transformed back to percent changes. They are unadjusted,
small-sample intervals; no family-wide significance or equivalence is claimed.

| Scenario | Usable pairs | Normalized WRITE change | 95% interval |
| --- | ---: | ---: | ---: |
| Fast WRITE QD32 | 4 | -0.5% | -10.7% to +10.8% |
| Serial WRITE QD32 | 2 | +0.4% | -5.0% to +6.0% |
| Fast mixed | 4 | +1.5% | -0.1% to +3.2% |
| Fast WRITE QD8 | 3 | -0.7% | -3.7% to +2.5% |

Fast-QD32 requests fall 18.0% (interval -28.4% to -6.1%) and lower bytes
fall 1.74% (-2.53% to -0.94%). Its WRITE p99 changes -3.8% (-22.4% to
+19.3%). These are host-I/O savings without an established useful-service win.
Serial-QD32 byte change is -0.09% (-1.65% to +1.50%); fast-QD8 WRITE-p99
change is -1.6% (-56.1% to +120.6%). Thus the latency/byte guards are not
all resolved, even where their point estimates are small.

## Mechanism and decision

Among the four screened fast-QD32 matched comparisons, arithmetic means
move as follows:

| Metric | Hand8 | Hand16 |
| --- | ---: | ---: |
| Useful WRITE MB/s | 105.38 | 105.23 |
| Lower-WRITE requests | 516.25 | 424.00 |
| Physical windows | 507.00 | 414.75 |
| Early-hand closes | 351.25 | 34.00 |
| Accepted-work lower-idle ms | 20.90 | 35.38 |
| Lower-WRITE service ms | 94.26 | 78.80 |

The geometric paired idle-time increase is 69.8% (36.9% to 110.7%). Fewer
windows and less lower service accompany more accepted-work idle, consistent
with the packing/service trade-off this experiment was designed to test.
These counters do not partition the critical path or identify a removable CPU
budget. Do not infer that every added idle nanosecond caused a throughput loss.

The primary 5% service benefit is unproved. Keep hand8 and do not promote
hand16 solely for fewer requests. Do not extend this pilot to seek a favorable
interval. Threshold64, submitter-off interactions and positive-content
effects remain separate untested questions, not established improvements.
The goal remains useful READ/WRITE above raw with lower I/O; fast mixed and
fast-QD8 still lag their own raw controls in this pilot.

Local artifacts are in `build/optimization-round/hand16-production-stack/`:
the prospective plan, four logs, four JSON reports, analysis script and
JSON/text results, history-refresh log, and SHA-256 manifest. Development
observations never enter `test_results.json` or qualified history. Teardown
leaves no DM mappings. Production C and the latest passing qualification
report remain unchanged. The refreshed exact-computer history contains six
PASS reports and still ends at source `b336754e3acb`, report `8b67a9425025`.
