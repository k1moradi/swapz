# Historical source-bound qualification snapshots

The three records below preserve original ROADMAP benchmark baselines,
ID107–ID108 qualification, and subsequent ARM64/x86 qualification and
development observations. They are transcribed **without modifying any
PASS, FAIL, BLOCKED, source hash, host qualification or measured value** from
[ROADMAP.md](../ROADMAP.md) at commit `6ea3478aa9ad816316f4d3e93a729cae4e99dc96`. The historical heading
"Current qualified source" only described the source during that period.
No observation below qualifies current `main` or replaces the canonical
[owner report](../../test_results.json). Current production operating policy,
release criteria and test semantics live in [AGENT_CONTEXT.md](../AGENT_CONTEXT.md),
[VISION.md](../VISION.md) and [testing_standards.md](../testing_standards.md).

## Previous comparison baseline

The prior official owner `make test` passed all five stages on production
source `0f5db1f8a771` (report `08a4b855f541`), which carries ID101–ID104.
Fast QD32 mixed useful WRITE/READ is 69.69/23.13 MB/s versus raw 62.94/20.89
(+10.7%, READ p99 0.85 vs 4.32 ms) and SD mixed is +405%; fast QD1/QD4/QD8/QD32
are -5.2/-11.9/+25.4/+54.5% and SD QD1/QD4/QD8/QD32 -3.1/+260/+242/+264%. Lower
WRITE bytes per useful byte stay ~26–31% below raw with 79–91% fewer requests.
Storage envelopes (swapz/raw useful WRITE) on the medium mixed fixture: SD card
3.35, SATA 0.53, NVMe Gen4 0.54, Gen5 0.60. The report's `delta64_rescue=1`
envelope rows replay a different fixture (delta64-positive, write-only QD32,
whose raw control is ~4x faster on NVMe), so they are not a delta64 off/on A/B;
the same-fixture paired A/B is ID67. Lower host WRITE bytes are an endurance
proxy, not NAND wear measurement.

## Previous qualified source (ID107–ID108)

Exact source `03becc01802b` passed all five owner `make test` stages; report
`b5227ca58001` records that qualification. Fast mixed async useful WRITE
is +7.4% versus raw (READ p99 0.88 vs 3.71 ms), SD mixed is +393%, and fast
QD1/QD4/QD8/QD32 are -2.7/-10.2/+18.2/+56.3%. This single qualification run
preserves host-WRITE savings but does not establish SATA/NVMe or QD4 parity.

The later owner run on `de79f2ec832d` (report `a4ff2205fa95`) passed stages
1–4 and loaded correctness smoke, then failed the first mixed swapz session:
`profile_epoch` returned success without exporting its acknowledgement. The
callback now returns DM's success-with-output value 1, covered by an executable
rootless regression. The subsequent owner run on `b86fefd` passed, as below;
the failed run itself establishes no performance for the new delta64 defaults.

The preceding directional `make fast_test` observations were
(absolute swapz useful WRITE MB/s; raw varies ~5%):

| Scenario | 0f5db1f | Candidate | vs raw |
|---|---:|---:|---:|
| SATA mixed QD32 | ~188 | 216–223 | -51% -> -42..-45% |
| NVMe Gen4 mixed QD32 | ~324 | 332–345 | -50% -> -36..-44% |
| Fast mixed / QD8 / QD32 | unchanged within noise | | +11% / +30% / +36..+50% |
| Fast QD1 / QD4, SD mixed / QD32 | unchanged within interleaved A/B noise | | |

Lower WRITE bytes remain ~0.69–0.74 of raw in those development observations.
The owner run qualifies this source on owned RAM; cross-host architecture
coverage and repeatable product performance remain distinct evidence gates.

## Current qualified source and newer development

The last fully qualified ARM64 production C,
`d2b66acb8c7eed99bbcfb6c89000df2da743ec83`, passed all five
ARM64 stages, report `77a0c3c587d4194d519edef4f1c2b8eadd253a9f`, including
ID143's published-ACK handoff. The new loaded gate observed 602 handoffs,
verified 128 final pages and exactly 16,512 successful upper WRITEs across
suspend/resume, then observed seven handoffs before a later injected WRITE
failure and verified a fresh syscall returned EIO. The RAW gate verified 2,048
pages with 182 async READ batches and 768 lower READ requests. ID36 passed with
16,117 memory.high events, 732,389,376 peak bytes and 14 CPU pressure workers.
Automatic history refresh succeeded with 56 ARM64 PASS reports. Default mixed
useful service versus each report's raw control is +407.2% serial, +7.8% fast,
+274.7% SD-card, -43.6% SATA, -40.8% NVMe4 and -37.2% NVMe5. These are qualified
synthetic observations, not causal cross-report gains; the modern mixed controls
remain LZ4-only. The newer x86 qualification is separate, as below.

On the receiving native i7-1185G7/eight-CPU host, unchanged ID148 production C
at source `a2b556998a8554b4f64960c77d6818fce1d4e811` passed all five stages,
including ID36; report `c0feb2127c05ffde1826e250e1ade55918d21448` was pushed.
Firmware verifies 16 GB LPDDR4 at configured 4267 MT/s, and boot/runtime evidence
confirms AVX-512 xstate and selected transform/inverse. This is not measured
RAM bandwidth or physical NVMe fidelity. The direct-BIO pilot below was removed,
and production C remains byte-identical to that baseline. Exact-host history
uses the owner-confirmed legacy-report registry rules in the testing standards;
unconfirmed legacy candidates never enter the pooled series automatically.

Main now also contains the ID148 lower-callback lifetime repair in
`2aa3ba06520fbf3a723294d7d7dd09cdd45e6502`. Its owner run was deliberately
interrupted after the owner reported a very busy host; report `ff66c705b152`
is **BLOCKED**, exit 2, with stages 1–4 and loaded smoke/ACK/RAW-read gates
passing but the full matrix and ID36 unfinished. The harness reports the
terminated raw replay as a bounded timeout; the local stop record identifies
the intentional TERM sent to its positively owned replay timeout. This is not
a demonstrated source regression or a completed qualification. Treat the run's
partial performance as unusable; it adds no historical point. Owned mapping
cleanup completed. Hold further benchmarks until the owner says the host is
free, then run exact-source owner qualification before promotion.

Previous source `a9bfe44c253271dc928cde0593c2e0f6236d24ec` passed all five
ARM64 stages, report `1e8a5bbf8965f4857c8366ea6bb5a2416ddcbe88`, with the
RAW READ fan-out in ID129. The added all-RAW/balanced correctness gate verified
2,048 pages and observed 172 async READ batches. Default medium fast mixed
useful WRITE is 68.49 versus raw 62.98 MB/s (+8.7%); lower WRITE bytes per useful
byte remain about 26% below raw. Fast QD1/4/8/32 is -1.4/-12.0/+24.6/+60.2%.
These owner means qualify this source; the prospective source A/B in ID129
separately establishes the RAW-content gains and leaves medium changes
inconclusive. Automatic history refresh succeeded with 55 ARM64 PASS reports.

Earlier owner source `b86fefd9e364727fa002ebd891ef4adfbd1166b1`, report `0d97e99`,
passed all five stages with delta64 rescue on and second-pass acceleration 4.
Fast mixed useful WRITE is +10.8% versus raw; fast QD1/4/8/32 is
-4.9/-11.3/+28.4/+50.0%. SD mixed is +404%. These are this VM's synthetic
results; the mixed fixture made no rescue attempts and cannot establish
representative-content prevalence. ID115 holds the paired positive evidence.

Newer source `005592d` implements DELTA64_SHUF8 and the faster NEON inverse
(ID116–ID117). Its ARM64 rootless, warning builds, loaded correctness smoke
and positive-fixture pair passed. Owner x86 source `005592d` subsequently passed
all five stages (report `4886c4d`), including scalar/SSE2/AVX2/AVX-512 runtime
checks and resource pressure. ARM64 source `3362fa0` (same production C as
`005592d`) then passed all five stages, report `87180ee`. Do not attribute the
old plain-delta64 report to this encoding or pool the two hosts.

The x86 paired positive-fixture rescue comparison reports useful WRITE
124.80 -> 319.55 MB/s (+156.2%, paired 95% CI +146.4..+165.9%), lower WRITE
bytes -73.7% and p99 -94.0%. Lower requests rise 43.4% (160 -> 229.4): byte
savings and useful service improve, but request fragmentation remains a trade-off.
Fast mixed is +48.7% versus raw on that host; these x86 results do not replace
the ARM64 VM's baseline or establish representative anonymous-memory prevalence.

The new ARM64 matrix reports fast mixed +9.9% and SD mixed +400% versus raw;
fast QD1/4/8/32 remains -3.7/-11.7/+21.7/+52.2%. Its five matched positive
rescue pairs give 138.05 -> 309.69 MB/s useful WRITE (+124.4%, paired 95% CI
+118.4..+130.3%), lower WRITE bytes -73.4%, p99 -93.9%, and requests +7.1%.
This is strong controlled-content service/byte evidence with a request trade-off,
not evidence that ordinary mixed pages benefit from the transform.

The worker-quantum repair in `b30b2ab` (ID123) subsequently passed all five
ARM64 stages, report `8458690`. Fast mixed useful WRITE is 68.20 MB/s versus
raw 62.94 MB/s (+8.4%); lower WRITE bytes per useful byte remain about 26% below
raw. This establishes correctness and measured service for the repaired budget,
not a causal speedup over the preceding source.
