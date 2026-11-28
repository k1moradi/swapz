# Round115 Agent4 — terminal same-host CRC32C sensitivity (AUTH0)

[Assignment](agent4-crc-backend-p0.md) · [Contract](frozen-contract.md) · [Issue #233](https://github.com/k1moradi/swapz/issues/233). **Host diagnostic PASS, both CRC backends; no universal preservation policy or native acceptance.**

## Exact source and execution

- R115 freeze `308f3b57774b42e20f295a13139655a10b25539d`, tree `80538948801519c0c3c17440cc64edf77443a896`; R114 frozen evidence blob `ca98c75e68a92ba456cd450aaaaab60b02995783`, unchanged product kernel tree `880d169f92383f438513d55e5fa2652bb3d9e0ae`; Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`. [Tested source 115a587af41bbc1007b2d5cf5c434fdf8fced135](https://github.com/k1moradi/swapz/commit/115a587af41bbc1007b2d5cf5c434fdf8fced135), sole parent `1b528e7cb45e39ffb5b7537091d0b073901e9321`, fixture `1c12c16c4a384042f18144b2d35c7e9bb3bfb141`, verifier `bd49aa30c90c179b54a00180d52e535ca7ea09b4`, unchanged workflow `837265f165682829286b5d77aa149479c12f5215`. Parent standards `e22b44ca9089c929c1e33cfb2740043d875d9741` exact prefix preserved in `7198ea65ea0166f0023afad5605e55e06fcfc490`.
- [Actual run 46110562505/job 140872920490](https://github.com/k1moradi/swapz/actions/runs/46110562505/job/140872920490) terminal SUCCESS, one changed-source automatic run, no dispatch or retry. [Artifact 15249162586](https://github.com/k1moradi/swapz/actions/runs/46110562505/artifacts/15249162586), 255340 bytes, GitHub-reported digest `sha256:add262f7c7b3f66b30c1b947f34213f776d5df8f6278af58bf87259bf548a666`; ZIP not independently downloaded or checked. Actual log 657629 characters, all 96 case records and metadata retrieved. Independent recomputation of every reported raw batch median, p95/p99, sample SD, faster-pair count, all 256 CRC vectors via separate byte-table implementation and cross-backend/common-object/R114 non-timing agreement passed. First error null.
- Baseline CPUID probe reports SSE4.2 supported; diagnostic process/children constrained to one allowed logical CPU, x86_64 hosted runner. Exact production codec.c compiled with -mno-sse4.2 or -msse4.2 only for that TU; other eight object hashes match across each compiler's backend pair, identical link flags, no global -march. GCC/Clang strict Werror ASan/UBSan and separate GCC -O3 pass both backends. Macro and object disassembly checks:

| Lane | Software CRC opcodes | SSE4.2 CRC opcodes |
|---|---:|---:|
| gcc-asan-ubsan | 0 | 2 |
| clang-asan-ubsan | 0 | 2 |
| gcc-optimized | 0 | 68 |

- Independent reflected Castagnoli bitwise oracle inside fixture: known 123456789 -> E3069283, NULL/zero -> 0, 8 alignment offsets x32 lengths (0..4096), all actual full pages/original compressed buffers/ordinary and preserved-or-fallback record CRCs. All values and byte-exact 4096 readback, fallback controls, actual ordinary extent planner/builder/read and opaque namespace refusal pass; all six lanes agree on every non-timing case field including per-page checksums. Independent JS byte-table oracle matches all 256 vectors. All 16 cases reproduce frozen R114 size/eligibility/packing exactly; R112 shared agreement also enforced. Full raw data retained in JSON; no private actual page bytes.
- Same 224 synthetic pages, seven strata, 192-page shared aggregate; 20 within-backend inclusive paired AB/BA batches, same independent micro batches and controls as R114. Separate binaries/processes, same logical CPU, software then hardware for LZ4 and reverse for LZO in GCC, reverse initial order in Clang. Not per-batch interleaved between backends: differences of within-backend medians, no cross-backend paired distribution, no additive causal decomposition. CRC flag can change other code generation inside codec.c; no direct kernel CRC dispatch equivalence. Host liblz4 wrapper, original Linux LZO C conservative unaligned shim and scalar predictor remain. Synthetic content not temperature/residency. No native or physical execution.

## Optimized inclusive paired deltas and size

Positive preserve-minus-ordinary is worse, negative is faster, ns/eligible page; same payloads on both backends.

| Codec | Stratum | Eligible | Payload ordinary / preserve B | SW write | HW write | SW read | HW read |
|---|---|---:|---:|---:|---:|---:|---:|
| LZ4 | r112_shared | 95/192 | 131739 / 195953 | 297.8 | -2298.8 | 3721.6 | 1172.9 |
| LZ4 | repeated | 32/32 | 41987 / 41987 | -873.8 | -824.2 | -0.2 | -0.0 |
| LZ4 | structured | 32/32 | 1612 / 65826 | 3262.7 | -4296.5 | 11145.3 | 3487.5 |
| LZ4 | mixed | 31/32 | 88140 / 88140 | -1624.6 | -1450.9 | 17.7 | 0.6 |
| LZ4 | pattern512 | 32/32 | 17184 / 17184 | -683.1 | -628.2 | -0.1 | -0.6 |
| LZO1X | r112_shared | 91/192 | 117770 / 175528 | 29.5 | -2379.0 | 3758.0 | 1308.0 |
| LZO1X | repeated | 32/32 | 41987 / 47862 | -107.8 | -759.3 | 656.2 | -30.9 |
| LZO1X | structured | 32/32 | 1612 / 49987 | 622.5 | -5088.1 | 10023.7 | 4201.4 |
| LZO1X | mixed | 27/32 | 74171 / 77679 | -450.6 | -886.3 | 44.5 | -513.9 |
| LZO1X | pattern512 | 32/32 | 17184 / 18336 | -516.4 | -598.0 | 102.5 | -32.2 |

Zero/same/random have no eligible timing; fallback readback passed. Hardware shared LZ4/LZO1X write medians improve from +297.8/+29.5 to -2298.8/-2379.0 ns, both 20/20 faster pairs. Read penalties decrease from +3721.6/+3758.0 to +1172.9/+1308.0 ns, both 0/20 faster pairs. Payload unchanged +48.74%/+49.04%. Structured payload penalty remains substantial: 1612 -> 65826/49987 bytes; read penalty persists +3487.5/+4201.4 ns even with hardware CRC, though writes improve. LZ4 repeated/mixed/pattern512 equal payload and read near parity; LZO1X hardware repeated/mixed/pattern512 shows faster read/write on this corpus, but larger payload. These findings are content-dependent and backend-dependent, not proof of net workload or I/O benefit.

## Independent optimized micro-batches

Standalone medians ns/page; CRC uses actual lengths. All other micro measurements (decode/inverse, copy, clock-score, empty batch) and distributions in JSON. No sum/subtraction of overlapping timers.

| Codec | Stratum | SW ordinary CRC | HW ordinary CRC | SW preserve CRC | HW preserve CRC | SW paired CRC delta | HW paired CRC delta |
|---|---|---:|---:|---:|---:|---:|---:|
| LZ4 | r112_shared | 5416.4 | 111.7 | 8030.3 | 160.8 | 2610.5 | 48.9 |
| LZ4 | repeated | 5052.8 | 98.8 | 5051.8 | 98.7 | -0.8 | -0.1 |
| LZ4 | structured | 162.1 | 12.9 | 7938.2 | 161.8 | 7776.4 | 148.7 |
| LZ4 | mixed | 11161.1 | 237.0 | 10984.0 | 236.8 | -136.3 | 0.1 |
| LZ4 | pattern512 | 2045.8 | 35.2 | 2045.1 | 34.4 | -0.4 | -0.5 |
| LZO1X | r112_shared | 4976.0 | 104.8 | 7518.6 | 149.9 | 2539.3 | 45.2 |
| LZO1X | repeated | 5053.7 | 99.4 | 5763.4 | 116.6 | 708.9 | 17.9 |
| LZO1X | structured | 161.9 | 12.5 | 6019.3 | 116.7 | 5857.8 | 104.0 |
| LZO1X | mixed | 10614.6 | 229.5 | 11116.4 | 242.0 | 501.9 | 12.3 |
| LZO1X | pattern512 | 2046.0 | 35.7 | 2184.8 | 37.6 | 140.0 | 2.1 |

Shared CRC standalone costs fall from ~5–8 us to ~0.10–0.16 us, roughly 47–50x; CRC paired penalty ~2.5–2.6 us -> 45–49 ns. Original decode remains ~1.5–1.7 us vs ordinary ~0.43 us; these are independent, nonadditive measurements. Hardware CRC changes the write/read trade-off markedly; original payload expansion and decoder costs remain. Actual ordinary packer identical to R114; preserved fixed 4/8/16 KiB length-only next-fit model, no lower IO, amplification, fault tail or native reclaim claim. Compare R114 only non-timing equality, not controlled cross-run timings. Sanitized results correctness only.

Evidence -> Goal implication -> Verdict: exact supported same-host CRC branches and independent checks PASS -> prior portable CRC penalty not transferable to hardware; retain conservative content-/codec-/backend-sensitive investigation, require separate native matched workload/CPU/reclaim/IO/fault measurements and authorization -> diagnostic PASS only. No runtime selector or defaults changed. AUTH=0, Phase A BLOCKED, observation UNKNOWN, compressed handoff/forced RAW/import OFF, physical NO_GO. Agent1 acceptance only.
