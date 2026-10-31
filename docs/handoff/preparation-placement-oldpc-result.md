# Old-PC preparation placement: pilots and frozen candidate

Keep the submitter-preparation module default enabled. A global off-mode pilot
missed its QD4 primary target. A separate conditional C candidate has a promising
QD8 signal but unresolved latency/other-workload guards. It is restored/unapplied
pending independent confirmation, not a qualified production improvement.

## Same-source placement pilot

Source: `5cc69fe23023b83dc090f4e226ff5d352754195a` on the two-core/four-thread
i3-M330. No C changes: use existing SUBMITTER_PREPARE=1/0/0/1 blocks, two repeats
each, fast QD4/QD8/QD32/mixed and serial QD32 through `make fast_test`.
Both settings retain async background preparation and the required production
delta64 + DELTA64_SHUF8 + LZ4 stack. Primary: background/submitter raw-normalized
QD4 useful WRITE >=5%. Guards: <=3% nonprimary service loss, <=1% more lower
bytes, <=5% more lower requests, <=10% worse available READ/WRITE p99.

All 40 raw/swapz pairs pass the byte oracle. The second off-mode block's mixed
repeats fail the raw-spread screen (17.1%), as do the final on-mode mixed
repeats (23.9%). No replacements. Pair repeats within blocks 1/2 and 3/4;
normalized service uses each observation's own raw control. Effects below are
geometric ratios with unadjusted paired 95% t intervals on logs.

| Workload | Usable pairs | Background/submitter WRITE | 95% interval |
| --- | ---: | ---: | ---: |
| Fast QD4, primary | 4 | +0.8% | -0.8% to +2.5% |
| Fast QD8 | 4 | +4.4% | +2.8% to +6.1% |
| Fast QD32 | 4 | +2.9% | -1.3% to +7.3% |
| Fast mixed | 2 | +1.0% | -20.2% to +27.9% |
| Serial QD32 | 4 | +0.9% | -0.9% to +2.8% |

Primary service misses the practical floor; mixed/latency guards remain
unresolved. This cannot change the global default or establish a portable
placement recommendation. Telemetry proves the off mode changes owners: one
QD8 sample has zero submitter claims, 3679 producer claims and 417 ordered
preparations, accounting for all 4096 WRITEs; 3677 producer starts overlap
lower WRITE. The secondary QD8 signal motivates a distinct conditional policy,
not a posthoc primary-endpoint switch or promotion of the off mode.

## Conditional C pilot

Same source and control C SHA-256:
`278535d3e0530666f2347cdfc5f0f9e4e8005fdcf1c380fb9e5c94fae2c5dcde`.
Frozen candidate SHA-256:
`42adc7541df0418147ff161af06eb928ce514b89d56a6ef3c004b2963fbe8ae9`.

Add only an active-lower-WRITE guard before the submitter resource claim:

```c
if (!ctx->submitter_prepare || !ctx->submitter_lanes ||
    atomic_read(&ctx->lower_write_active))
        return -1;
```

The existing mapper then queues preparation and wakes its bounded producer.
Idle-device admissions retain submitter preparation. No new ownership state,
queue, memory allocation, timer, encoding, depth, threshold or module-default
change. A native probe extracts the actual claim function and real state enum;
it checks busy/idle and I/O-state changes, unchanged ownership/masks on bypass,
normal claims and capacity-failure cleanup. Removing the guard fails its
negative control. This is not a whole-worker or LKMM proof.

Prospective control/candidate/candidate/restored-control, two repeats each on
fast QD8 (new primary), QD4/QD32/mixed and serial QD32. The source, medium
fixture, submitter flag 1, hand eight and production compression stack stay
fixed. Primary floor and guards are the same as above, now with actual producer
starts during lower WRITE plus continued submitter claims required for mechanism.

All 40 pairs pass byte verification. Five observations fail the fixed screen:
first control mixed repeats (36.2% raw spread), first candidate QD4 repeat 1
(pre busy 26.6%), and its mixed repeats (post busy 100.0%, pre busy 55.7%).
No replacements. Inputs, replay modes, source identities and exact final images
match each usable comparison. Per-page actor counts sum exactly to every timed
WRITE in both pilots; no missing preparation work is inferred as savings.

| Workload | Usable pairs | Conditional/control WRITE | 95% interval |
| --- | ---: | ---: | ---: |
| Fast QD8, primary | 4 | +5.7% | +2.4% to +9.1% |
| Fast QD4 | 3 | -0.0% | -2.8% to +2.9% |
| Fast QD32 | 4 | +2.8% | -8.0% to +14.9% |
| Fast mixed | 2 | +9.6% | +5.5% to +14.0% |
| Serial QD32 | 4 | +0.1% | -1.2% to +1.4% |

The QD8 lower-byte change is -0.07% (-0.31% to +0.18%) and requests -1.3%
(-3.3% to +0.8%). WRITE p99 is +0.1% with interval -24.9% to +33.4%, so its
10% guard is unresolved. QD32 and mixed guard intervals also remain unresolved.
All four primary comparisons are positive, but a two-sided exact sign test at
n=4 gives p=0.125. The small-sample t interval alone is not promotion evidence.
In one primary sample, submitter claims remain 301 and producer starts during
lower WRITE reach 3711 versus zero in control: conditional placement engages.

## Decision and artifacts

Keep the current source/default. Freeze this exact conditional candidate for
an independent, fixed-size guard confirmation; do not pool that future data
with this hypothesis-generating pilot. A retained source still needs exact-source
owner `make test`, positive-content/lifecycle/resource-pressure coverage, and
honest host/protocol limits. Modern-host performance is unmeasured here. The
primary is improvement over swapz control, not parity with raw: QD8 still trails
raw, and the broader useful READ/WRITE and lower-I/O goal is incomplete.

Local evidence: `build/optimization-round/preparation-placement-oldpc/` and
`build/optimization-round/submitter-during-io-oldpc/`, including plans, all block
logs/JSON, analysis, actor-conservation checks, exact C/patch/native probe for
the conditional variant and SHA-256 manifests. Original C is restored and
owned mappings removed; `test_results.json` and qualified history are unchanged.
