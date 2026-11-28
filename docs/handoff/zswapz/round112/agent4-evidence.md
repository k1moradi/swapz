# Round112 Agent4 — terminal offline diagnostic recovery (AUTH0)

[Assignment](agent4-codec-recovery-p0.md) · [Frozen contract](frozen-contract.md) · [Issue #230](https://github.com/k1moradi/swapz/issues/230). **PASS: rootless diagnostic only; no production/admission acceptance.**

## Exact source and execution

- R112 freeze `7911cb6873ea4bd7158c9fa06ac615eee1d4d2f1`, tree `5a9553a2a7c9a66bd0080fcf073bef2a4f672fe0`; original R111 product freeze `4345f21b1da720e6c8d685c7b232bfcebe635d50`, tree `98cb27a3f57d6482d859a260526edb5614ec7994`. Both freezes and tested source have identical src/kernel tree `880d169f92383f438513d55e5fa2652bb3d9e0ae`. Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`. All checked Linux/product blob hashes and compiler flags are retained in the adjacent JSON.
- [Tested source c7996667b5764356bd8ee2b766e181f6f452b27f](https://github.com/k1moradi/swapz/commit/c7996667b5764356bd8ee2b766e181f6f452b27f), sole parent `a308e20d11cb34250724fa30bc843aa4ad0e0d65`, fixture `3a194c006e6424673dd11eb512d3b0f4dd77450e`, verifier `38c9895196cabad34d9a41a854f10569e95f9fe1`, unchanged workflow `837265f165682829286b5d77aa149479c12f5215`.
- Previous terminal failure [R111 run46056108200/job140698870412](https://github.com/k1moradi/swapz/actions/runs/46056108200/job/140698870412), artifact15226127927: actual extracted production local int candidate shadowed fixture candidate[PAGE] under -Werror=shadow. Fixed fixture scratch name, not extracted function or warnings.
- [R112 run46104589478/job140854378183](https://github.com/k1moradi/swapz/actions/runs/46104589478/job/140854378183) terminal SUCCESS, one automatic changed-source lane, no manual dispatch. [Artifact 15246204379](https://github.com/k1moradi/swapz/actions/runs/46104589478/artifacts/15246204379), 6694 bytes, GitHub-reported digest `sha256:fe6ea3c8e63f9f7de32b3776cad15d849e504c17717ad8679b8d4b0d5cf0ca4d`. Bounded structured results independently retrieved from exact job log; artifact ZIP not independently downloaded or CRC-checked in this session.
- GCC 13.3 and Clang 18.1 ASan/UBSan Werror PASS, separate GCC 13.3 -O3 PASS; exact 4096-byte readbacks including untimed fallback controls and immutable preserved bytes; cross-compiler and optimization non-timing equality gate PASS. Recomputed medians from every raw batch in job log. No first failure in recovery lane. Local exact-source compilation unavailable (DNS/checkout); hosted evidence is the execution proof.
- x86_64, 4 reported CPUs; CPU model not supplied beyond x86_64. Actual scalar predictor; original LZO Linux C conservative unaligned shim; original LZ4 wrapper with host liblz4, not kernel backend. 192 deterministic pages per codec (32 per category), 3 warmups, 20 alternating AB/BA pairs, thread CPU batch ns/page; p95/p99 are percentiles of 20 batch averages (not fault-latency or individual-page percentiles). Timed eligible subset only. Both arms compute and verify CRC. Ordinary production wall clocks/stats included, preserve has no such clocks; source generation, packing, full memcmp outside timer. No attribution of individual CPU subcomponents or pure codec speed. No live pool, native eviction, lower-I/O or runtime claim.

## Optimized observed costs

| Codec | Eligible / total | Ordinary write ns/page | Preserve write | Ordinary read | Preserve read | Ordinary payload B | Preserve payload B | Payload increase |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LZ4 | 95/192 | 7816.0 | 8080.9 | 5846.6 | 9647.1 | 131739 | 195953 | +48.74% |
| LZO1X | 91/192 | 7548.7 | 7561.9 | 5495.5 | 9212.8 | 117770 | 175528 | +49.04% |

| Codec | Paired write delta median / p95 / p99 / SD ns/page | Paired read delta median / p95 / p99 / SD | Preserve faster write / read pairs |
|---|---|---|---|
| LZ4 | 249.0 / 529.1 / 540.6 / 140.7 | 3831.3 / 4004.2 / 4027.4 / 133.2 | 0/20; 0/20 |
| LZO1X | 12.5 / 201.0 / 326.4 / 123.4 | 3775.7 / 3946.6 / 3957.8 / 127.8 | 7/20; 0/20 |

All raw pairs, per-arm medians/p95/p99/SD, bins, eligibility, explicit copy bytes and ordinary last-batch telemetry are in JSON. Zero/same/over-cap/unsupported controls LZ4 32/32/32/1 and LZO1X 32/32/36/1, separately byte-exact ordinary fallback. No ordinary raw pages in timed subset. Explicit preserved copy bytes equal preserved payload totals. Internal recompression copies/CRC cost not individually isolated. Tag 2 stays original LZO1X, never direct ZSTD or ordinary encoding.

## Packing boundary

| Codec | Actual ordinary planner + builder B | Ordinary fixed 4/8/16 KiB model B | Preserved fixed 4/8/16 KiB model B | Ordinary model padding B | Preserved model padding B |
|---|---:|---|---|---|---|
| LZ4 | 143360 | 192512 / 172032 / 147456 | 262144 / 229376 / 212992 | 60773 / 40293 / 15717 | 66191 / 33423 / 17039 |
| LZO1X | 126976 | 167936 / 147456 / 131072 | 229376 / 212992 / 196608 | 50166 / 29686 / 13302 | 53848 / 37464 / 21080 |

Actual ordinary extent append/seal/read and byte-exact decode passed. Builder rejects opaque original encoding with -EINVAL and unchanged cursor/count. Original preserved payloads not appended using a fabricated ordinary tag. Fixed-class next-fit model max64 records; no lower I/O, alignment/GC/device/endurance claims.

## Decision

Evidence -> Goal implication -> Verdict: all mandatory byte-exact host correctness gates passed; preservation enlarged payloads about 49%, had no observed write-side advantage (LZ4 0/20 faster, LZO1X 7/20), and read-side CPU was worse (0/20 faster both) -> avoiding recompression alone is insufficient on this synthetic scalar/CRC-heavy host corpus; additional codec-/corpus-dependent work and eventual separately authorized native matched measurements are needed -> **diagnostic PASS, performance advantage not established; do not activate or infer product/native performance**. No causal attribution to CRC without isolation. Agent1 retains acceptance. AUTH=0; Phase A BLOCKED; compressed handoff, forced RAW, import OFF; physical NO_GO. No same-round peer dependency, no repeated connected build or unchanged-source rerun, no runtime or physical operations.

