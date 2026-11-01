# Prepared LZ4 cost coverage: owner-qualified correction

Completed asynchronous preparation now supplies the ordered owner's existing
LZ4-cost EWMA. Previously that estimator learned only from inline compression:
the old-PC controls had 4096 submitter compressions, 25.6–27.0 ms of LZ4 wall
and an EWMA of zero. This repairs an adaptive input, not a claimed throughput
optimization.

Qualified source:
[`bb6657303612eaf3f50fbb056d18affd8b9bef05`](https://github.com/k1moradi/swapz/commit/bb6657303612eaf3f50fbb056d18affd8b9bef05).
Exact owner report:
[`48a1580f14d164b548cc3f18394bd38b86a285ee`](https://github.com/k1moradi/swapz/blob/48a1580f14d164b548cc3f18394bd38b86a285ee/test_results.json).
Host: two-core/four-thread i3-M330, x86_64/SSE2, kernel `7.0.0-38-generic`;
all loaded devices are positively owned RAM-backed null_blk.

Both asynchronous preparation owners use one shared wrapper to record their
page's LZ4 elapsed delta before READY publication. Only the ordered consumer
updates the EWMA, after observing READY_COMPRESSED or READY_RAW. Unready,
RAW-selected and error metadata are ignored; zero/unknown samples preserve
the existing estimate. Scratch ownership, original submitter-active lifetime,
slot references, encoding, K=1 and ACK-after-lower-success remain unchanged.
Real kernel-object DWARF shows 8256 bytes per prepared slot before and after.

Actual-body native writer/consumer tests cover consecutive compressed/RAW
samples, a nonzero cumulative lane baseline, zero/unknown timing, codec
outputs and protected unready metadata. Compiled mutants using cumulative
lane time or removing the READY guard fail. Source wiring checks cover both
owners and publication order.

Separate development validation passes three byte-exact, drained pairs with
zero inline preparation:

| Workload | Submitter claims | Observed EWMA |
| --- | ---: | ---: |
| Fast QD4 | 4096 | 7284 ns |
| Fast QD8 | 4096 | 5222 ns |
| Fast mixed | 12301 | 4938 ns |

The full clean-source `make test` passes all five stages: build/helpers,
native/rootless contracts, W=1, W=2 and owned loaded qualification. The command
finishes with exit zero in 2159 seconds (35 minutes 59 seconds), including
publication and plots. Loaded qualification takes 1959.6 seconds. Its final
resource-pressure phase spends substantial startup time faulting code under
memory.high; a raw-control stack confirms charge throttling before swapz
WRITEs, and that raw arm subsequently completes. No pressure or watchdog
limits were relaxed. Eight pressure workers and 576 MiB of ballast produce
120023 memory.high events; the recorded peak is 652496896 bytes, within the
896 MiB bound.

Report audit verifies the exact source/C hash, five PASS stages, default-on
delta64 with second-LZ4 acceleration four in all 66 recorded swapz WRITE arms,
and a positive EWMA in every one of those arms. The 128-page loaded delta64
positive control classifies/adopts all 128 pages and passes byte verification.
Target mappings and pressure workers are removed at completion.

This-host history now has seven qualified reports and 74 points. Against each
current raw control, fast mixed useful WRITE is 27.36 versus 23.45 MB/s,
with 21.7% fewer lower WRITE bytes and 68.1% fewer requests. These are
descriptive report values, not attribution to this fix. Standard mixed WRITEs
remain entirely submitter-prepared and compressed; no new RAW activity explains
the cross-report service change. Host/load and batching variation are not a
controlled source A/B.

Fast WRITE QD1/4/8 still trails raw by 24.6%/48.2%/24.0%, while QD32 is
35.1% above raw. QD1 worsens directionally from the previous report's -19.9%
raw gap to -24.6%, but its one-observation control cannot establish a causal
regression. QD4/8/32 raw-normalized service is approximately +2.3%/+0.4%/+0.6%
versus the preceding report. SATA/NVMe4/NVMe5 mixed means remain about
43.6%/41.5%/51.5% below raw. The broader useful-service goal is incomplete;
RAM traffic savings are not physical NAND lifetime evidence.

Full local validation, immutable source copies, object-layout measurements,
qualification log/state and machine-readable audit remain under
`build/optimization-round/prepared-cost-coverage/`. The rejected unconditional
ROADMAP ID 171's early-snapshot prototype is not retained.
