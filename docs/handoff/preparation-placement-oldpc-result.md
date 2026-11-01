# Old-PC preparation placement: pilots and independent confirmation

Keep the submitter-preparation module default enabled. A global off-mode pilot
missed its QD4 primary target. Independent confirmation of the conditional C
candidate establishes its QD8 service signal and resolves QD8/QD32 guards,
but mixed-I/O coverage, service and latency guards remain unresolved. The
candidate is restored/unapplied, not a qualified production improvement.

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

## Independent frozen-source confirmation

Source: `c0b0954406d859c0971ce5aa658315bc123819da`; control and candidate C
hashes remain exactly those above. Before collection, freeze eight cycles of
control/candidate/candidate/control, two repeats each on fast QD8, QD32 and
mixed. This gives 32 blocks and 192 raw/swapz pairs in 48 minutes 24 seconds.
All 192 pass the byte oracle and exact preparation-actor accounting. The
compression stack, module flags, hand threshold, fixture and replay identities
stay fixed. No pilot observations enter these estimates.

Match repeat numbers within the two source-order strata, then give those strata
equal weight on log ratios. The independent unit is a cycle: delete-one-cycle
jackknife uncertainty with Student-t critical values, plus an exact two-sided
cycle sign-flip test for the primary under a symmetric-null assumption. Each
endpoint requires at least six usable cycles, three contributing cycles per
source-order stratum and 12 usable comparisons. The primary requires a >=5%
QD8 normalized useful-WRITE gain, a positive lower 95% bound and p<=0.05.
Guards retain the declared <=3% nonprimary service loss, <=1% lower-byte
increase, <=5% request increase and <=10% available p99 increase.

| Workload | Usable comparisons / cycles | Conditional/control WRITE | Cluster 95% interval |
| --- | ---: | ---: | ---: |
| Fast QD8, primary | 24 / 8 | +5.61% | +3.83% to +7.41% |
| Fast QD32 | 22 / 8 | +0.65% | -1.69% to +3.05% |
| Fast mixed | 11 / 5 | +0.75% | -5.98% to +7.96% |

QD8 passes the primary, including cycle sign-flip p=0.0078125. Its lower
requests change -0.98% (-1.61% to -0.34%); lower bytes -0.074% (-0.149% to
approximately zero); WRITE p99 -1.13% (-4.72% to +2.59%). QD32 also passes
all guards: WRITE-p99 upper bound +1.52%, lower-byte upper +0.151% and
request upper +0.708%. Every usable candidate primary observation shows both
submitter claims and producer preparation starting during lower WRITE service.

Mixed does not meet minimum coverage, and the remaining descriptive intervals
do not establish service or latency noninferiority: normalized service lower
-5.98%, WRITE-p99 upper +24.90%, READ-p99 upper +26.39%. Its lower-byte
upper +0.603% and request upper +4.14% fit the numeric guards, but insufficient
coverage prevents those endpoints passing too. This is unresolved evidence,
not proof that the candidate regresses mixed I/O.

The unchanged screens exclude 46 of 192 observations. Requiring both members
of a comparison and <=10% matched-raw drift leaves 57 of 96 comparisons usable
across the three scenarios. Preserve all exclusions, with no replacements or
significance-driven extension. The 200ms CPU/PSI samples do not identify the
responsible task or prove operator activity, even with exclusive computer access;
the source of these bursts is unestablished. Raw repeat drift also excludes
mixed observations. Do not relax the screens after seeing the result.

The [machine-readable confirmation summary](submitter-during-io-confirmation.json)
includes the frozen plan, every endpoint's coverage/interval, acceptance results
and screen-reason counts. Full local block logs, JSON, actor checks, native
probe, source copies, patch and analysis remain under
`build/optimization-round/submitter-during-io-confirmation/` with SHA-256 manifest.

## Decision and artifacts

Keep the current source/default. The fixed confirmation supports the primary
mechanism but does not authorize retention while mixed guards remain unresolved.
Do not add replacement observations to this completed protocol. Any follow-up
needs a prospective protocol and a reasoned account of the screening/coverage
problem, keeping this result separate. A retained source still needs exact-source
owner `make test`, positive-content/lifecycle/resource-pressure coverage, and
honest host/protocol limits. Modern-host performance is unmeasured here. The
primary is improvement over swapz control, not parity with raw: QD8 still trails
raw, and the broader useful READ/WRITE and lower-I/O goal is incomplete.

For a separate prospective mixed follow-up, the development loop now supports
`MIXED_OPS=65536` on ordinary mixed-only scenarios. Rootless tests prove the
original 16384-operation measured stream is an exact prefix and validate the
extended plans' final-image oracle. Two loaded control pairs pass at 65536
operations per arm (49060 WRITEs and 16476 READs), with both unchanged screens
passing. These are harness-validation pairs, excluded from candidate inference.
The default and official qualification traces remain unchanged. A new plan must
state how a longer steady-state workload addresses guard evidence and preserve
the distinction from the completed shorter-trace cohort.

A separate fresh idle diagnostic captured two >25%-busy intervals among 50
enclosing process/host snapshots, with ChatGPT/Codex process activity observed.
This supplies a plausible source of interference under exclusive access, not
attribution of the earlier exclusions; the diagnostic observer also consumes
CPU and its process windows enclose the host sample. Evidence for this
measurement preparation remains in `build/optimization-round/quiet-screen-audit/`.

Pilot evidence: `build/optimization-round/preparation-placement-oldpc/` and
`build/optimization-round/submitter-during-io-oldpc/`, including plans, all block
logs/JSON, analysis, actor-conservation checks, exact C/patch/native probe for
the conditional variant and SHA-256 manifests. Original C is restored and
owned mappings removed; `test_results.json` and qualified history are unchanged.
Refreshed this-host history still ends at qualified source `b336754e` and report
`8b67a942`; development confirmation observations are excluded from its plots.
