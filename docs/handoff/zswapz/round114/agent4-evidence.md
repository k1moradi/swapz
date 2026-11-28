# Round114 Agent4 — terminal host codec-cost attribution (AUTH0)

[Assignment](agent4-codec-attribution-p0.md) · [Binding contract](frozen-contract.md) · [Issue #232](https://github.com/k1moradi/swapz/issues/232). **Rootless diagnostic PASS; no general preservation policy or native acceptance.**

## Exact source and execution

- R114 freeze `c87f9f92fc656db5670d9bfd75c7fcf826aa9bbf`, tree `7b6fe1478215a0485bb054c30a2a2f51711ddf45`; R111 experiment `4345f21b1da720e6c8d685c7b232bfcebe635d50`, R112 recovery `7911cb6873ea4bd7158c9fa06ac615eee1d4d2f1`, same product kernel tree `880d169f92383f438513d55e5fa2652bb3d9e0ae`. Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`. [Tested source b867fbdcd669c625a5b1e645d4e86d0b8943661f](https://github.com/k1moradi/swapz/commit/b867fbdcd669c625a5b1e645d4e86d0b8943661f), sole parent `94ec9494a3a9929905856d8ae7775d3410198dc2`, fixture `64ff056d565bf2bf4c658a0e1cd51269ffdf4854`, verifier `4403848e698da99970634f75f1a60df6a3f99629`, unchanged workflow `837265f165682829286b5d77aa149479c12f5215`. Standards parent `cc2731972491ec73e55f330694179a522d4ea9d7` exact prefix preserved in `19e59f14efe9c23178a9e589d12606755a6a79d0`.
- [Actual run 46109251705/job 140868873612](https://github.com/k1moradi/swapz/actions/runs/46109251705/job/140868873612) terminal SUCCESS, one automatic changed-source run, no manual dispatch. [Artifact 15248568637](https://github.com/k1moradi/swapz/actions/runs/46109251705/artifacts/15248568637), 70585 bytes, GitHub-reported ZIP digest `sha256:2a64538fc67140e97f47764c869e9da4f5fd1ec945c85e23f5dc21a83883d8ec`. Exact bounded job log metadata + all 48 case records retrieved; recomputed medians, p95/p99 and sample SD for every raw inclusive and micro batch distribution and paired deltas; cross-compiler non-timing agreement verified. ZIP not independently downloaded/CRC checked. First error null.
- GCC 13.3 ASan/UBSan Werror PASS; Clang 18.1 ASan/UBSan Werror PASS; separate GCC 13.3 -O3 PASS; exact every 4096-byte readback and preserved payload equality including fallback controls; actual ordinary extent builder/read and opaque namespace refusal. All required correctness gates before reporting any metrics. Full exact source hosted checkout, no local full checkout. No production changes. x86_64 4 reported CPUs; host liblz4 with pinned Linux wrapper (not kernel LZ4 backend); actual pinned Linux LZO C conservative unaligned shim; actual scalar predictor; production ordinary compressor verbatim.
- 192 unchanged R112 pages + 32 deterministic 512-byte repeated-pattern pages, 32 per content stratum. First 192 R112 non-timing totals independently reproduced exactly against immutable R112 report `b8e676ee4fc4889fb66b3b528c39e1e8dc7600d9`. Aggregate covers only original 192; do not add shared aggregate to stratum totals. Page sizes/IDs/eligibility for every generated page in JSON. Synthetic patterns are not actual hot/cold temperature, tmpfs residency or MM pressure. Untimed zero/same/high entropy/over-cap/unsupported ordinary fallback controls, no reinterpretation of codec 2. Eligible timing only; no eligible zero/same/random pages.
- Inclusive paired thread-CPU batches 3 warmups and 20 alternating AB/BA pairs per nonempty case. Both arms CRC-check actual payload; ordinary includes original decode, verbatim production clocks/statistics and compression, preserved copy; read includes CRC plus decoder. Independent micro batches one warmup and 20 forward/reverse passes, same eligible page IDs, actual arm lengths, output validated outside timer. Empty batch includes loop/barrier/timer, clock-score proxy two monotonic calls and actual score note (precomputed scores); not exact production instrumentation total. Inverse-only denominator is actual delta64 subset with selection loop included, null if none. No subtracting overhead or summing overlapping measurements. p95/p99 are 20-batch averages, not individual fault latencies.

## Inclusive paired cost and payload (optimized only)

Paired delta = preserve minus ordinary, positive is worse; medians ns/eligible page. Raw pairs, per-arm medians/p95/p99/SD, paired distributions and actual all-page lengths in JSON.

| Codec | Content | Eligible | Payload ordinary / preserved B | Payload change | Write delta ns | Read delta ns | Faster write/read pairs |
|---|---|---:|---:|---:|---:|---:|---|
| LZ4 | r112_shared | 95/192 | 131739 / 195953 | 48.74% | 365.6 | 3790.6 | 0/20; 0/20 |
| LZ4 | repeated | 32/32 | 41987 / 41987 | 0.00% | -880.9 | 2.3 | 20/20; 8/20 |
| LZ4 | structured | 32/32 | 1612 / 65826 | 3983.50% | 3310.3 | 11226.0 | 0/20; 0/20 |
| LZ4 | mixed | 31/32 | 88140 / 88140 | 0.00% | -1458.3 | 3.8 | 20/20; 9/20 |
| LZ4 | pattern512 | 32/32 | 17184 / 17184 | 0.00% | -688.7 | 1.8 | 20/20; 7/20 |
| LZO1X | r112_shared | 91/192 | 117770 / 175528 | 49.04% | -44.2 | 3821.8 | 13/20; 0/20 |
| LZO1X | repeated | 32/32 | 41987 / 47862 | 13.99% | -91.4 | 629.6 | 15/20; 0/20 |
| LZO1X | structured | 32/32 | 1612 / 49987 | 3000.93% | 480.2 | 10298.7 | 0/20; 0/20 |
| LZO1X | mixed | 27/32 | 74171 / 77679 | 4.73% | -380.2 | -10.6 | 20/20; 11/20 |
| LZO1X | pattern512 | 32/32 | 17184 / 18336 | 6.70% | -530.3 | 104.3 | 20/20; 1/20 |

R112 shared write paired deltas +249.0/+12.5 ns LZ4/LZO1X; R114 +365.6/-44.2 ns. Read R112 +3831.3/+3775.7 ns, R114 +3790.6/+3821.8 ns. Shared payload exact +48.74%/+49.04%. Distinct runner/time and expanded diagnostic binary; not a controlled cross-run timing comparison.

## Independent micro costs (optimized only)

All medians ns/page; inverse uses actual transformed subset, not full denominator. CRC/copy use real payload lengths, not fixed equal lengths. These are independent standalone batches, not additive parts of inclusive path. The compiled host CRC32C is the nibble-table fallback (codec.c not compiled with -msse4.2; kernel crc32c is a different dispatch). CRC cost and decode differences are consistent with the large structured-stratum penalty, not proof of exact causal shares or native cost.

| Codec | Content | Empty | Original decode | Ordinary decode incl inverse | Ordinary CRC | Preserve CRC | Ordinary copy | Preserve copy | Clock/score proxy | Inverse only (count) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| LZ4 | r112_shared | 2.8 | 1555.1 | 433.8 | 5352.5 | 8044.2 | 35.2 | 48.4 | 45.5 | 279.6 (32) |
| LZ4 | repeated | 7.3 | 193.5 | 196.3 | 5052.9 | 5053.2 | 41.1 | 39.6 | 50.5 | N/A (0) |
| LZ4 | structured | 7.7 | 3738.0 | 388.4 | 162.6 | 7969.9 | 12.9 | 53.8 | 51.1 | 241.8 (32) |
| LZ4 | mixed | 7.4 | 702.5 | 699.4 | 11214.1 | 11097.6 | 67.3 | 66.7 | 52.5 | N/A (0) |
| LZ4 | pattern512 | 7.1 | 156.9 | 158.3 | 2044.9 | 2045.1 | 25.2 | 25.5 | 50.2 | N/A (0) |
| LZO1X | r112_shared | 2.9 | 1711.7 | 430.8 | 5062.8 | 7530.1 | 33.2 | 46.0 | 45.6 | 263.4 (32) |
| LZO1X | repeated | 7.2 | 128.1 | 198.2 | 5052.5 | 5764.2 | 41.1 | 45.1 | 50.4 | N/A (0) |
| LZO1X | structured | 7.8 | 4613.4 | 389.5 | 162.1 | 6020.2 | 13.0 | 44.5 | 51.2 | 242.3 (32) |
| LZO1X | mixed | 8.4 | 165.0 | 727.2 | 10768.0 | 11190.5 | 66.9 | 68.5 | 53.5 | N/A (0) |
| LZO1X | pattern512 | 7.4 | 107.8 | 160.6 | 2044.9 | 2184.3 | 25.0 | 24.4 | 50.3 | N/A (0) |

| Codec | Content | Paired CRC delta ns | Paired copy delta ns |
|---|---|---:|---:|
| LZ4 | r112_shared | 2700.6 | 13.2 |
| LZ4 | repeated | -0.4 | -1.6 |
| LZ4 | structured | 7807.4 | 41.0 |
| LZ4 | mixed | -117.5 | -0.8 |
| LZ4 | pattern512 | -0.3 | 0.3 |
| LZO1X | r112_shared | 2478.5 | 12.6 |
| LZO1X | repeated | 710.4 | 3.9 |
| LZO1X | structured | 5858.3 | 31.5 |
| LZO1X | mixed | 505.5 | 1.1 |
| LZO1X | pattern512 | 139.9 | -0.6 |

For shared LZ4/LZO1X, independent CRC deltas +2700.6/+2478.5 ns/page; original decode medians 1555.1/1711.7 vs ordinary 433.8/430.8; copy delta +13.2/+12.6 ns; clock/score proxy ~45.5 ns. Structured stratum original sizes far larger than ordinary Delta64; standalone CRC and decoder penalties both large. Same-size LZ4 repeated/mixed/pattern512 shows preserved write advantage, read near parity; LZO1X pattern512 shows write improvement with modest read and size penalty. This supports content-/codec-dependent investigation, not a blanket routing policy. LZO shared write delta small with 13/20 faster pairs, not general advantage. No statistical independence guarantee across repeated batches on same host.

## Packing boundary

| Codec | Content | Actual ordinary planner/builder B | Ordinary fixed-class 4/8/16KiB model B | Preserved fixed-class model B |
|---|---|---:|---|---|
| LZ4 | r112_shared | 143360 | 192512 / 172032 / 147456 | 262144 / 229376 / 212992 |
| LZ4 | repeated | 45056 | 49152 / 49152 / 49152 | 49152 / 49152 / 49152 |
| LZ4 | structured | 4096 | 4096 / 8192 / 16384 | 131072 / 90112 / 81920 |
| LZ4 | mixed | 94208 | 126976 / 114688 / 98304 | 126976 / 114688 / 98304 |
| LZ4 | pattern512 | 20480 | 20480 / 24576 / 32768 | 20480 / 24576 / 32768 |
| LZO1X | r112_shared | 126976 | 167936 / 147456 / 131072 | 229376 / 212992 / 196608 |
| LZO1X | repeated | 45056 | 49152 / 49152 / 49152 | 65536 / 57344 / 65536 |
| LZO1X | structured | 4096 | 4096 / 8192 / 16384 | 65536 / 57344 / 65536 |
| LZO1X | mixed | 77824 | 110592 / 98304 / 81920 | 110592 / 98304 / 98304 |
| LZO1X | pattern512 | 20480 | 20480 / 24576 / 32768 | 20480 / 24576 / 32768 |

Actual compatible ordinary extent plan/build/read verified. Preserved payload model length-only fixed-class next-fit, max64, raw separate; no actual opaque builder, disk I/O, GC or amplification inference. No native execution or physical mutation.

Evidence -> Goal implication -> Verdict: host correctness and R112 non-timing reproduction PASS, CRC payload-length and codec/decode differences measured independently, significant strata dependence -> no universal benefit, future separately authorized matched native CPU/reclaim/IO/fault evidence needed -> **diagnostic PASS only; no policy/activation**. AUTH=0; Phase A BLOCKED; observation UNKNOWN; compressed handoff, forced RAW, import OFF; physical NO_GO. Agent1 retains acceptance.
