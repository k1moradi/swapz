# Round116 Agent4 — terminal held-out full-policy qualification (AUTH0)

[Assignment](agent4-heldout-selector-p0.md) · [Contract](frozen-contract.md) · [Issue #234](https://github.com/k1moradi/swapz/issues/234). **Diagnostic execution PASS; frozen conservative host policy NO_GO on both CRC backends.** No retuning or native permission.

## Exact source and execution

- R116 freeze `dd215d9467491dbe75cd7593bb146e814cabfad3`, tree `bbe592501bc10b334e0192d5f361f49a0947167c`; unchanged product kernel tree `880d169f92383f438513d55e5fa2652bb3d9e0ae`; Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`. Pinned R115 report `01f58f08db2b5f880db056c584b9b0b25a6ab7c3` and frozen Python selector `8faa25c2b6f97713a719d1b2747a7037477d5c0d`. [Tested source 12560a66f7f4daf9988712083af4c0178c31d08d](https://github.com/k1moradi/swapz/commit/12560a66f7f4daf9988712083af4c0178c31d08d), sole parent `9bd7f5a8b564a3ed029c660a0d9086968a5a5e66`, fixture `87c4919979523e4393423871a5c63c10452f85f2`, verifier `3922b965436acabb94ceffe7fd8a70d40af87dcf`, unchanged workflow `837265f165682829286b5d77aa149479c12f5215`. Standards exact prefix `09b02ae725a949317ddf114cbf9cb9d8e9e10317` -> `b7061e8a852c785602361ba65f0489beba99d5e8`.
- [Actual run 46121928515/job 140908109541](https://github.com/k1moradi/swapz/actions/runs/46121928515/job/140908109541) terminal SUCCESS; [artifact 15254256756](https://github.com/k1moradi/swapz/actions/runs/46121928515/artifacts/15254256756), 390602 bytes, GitHub-reported digest `sha256:d9e4b522fec910ce57ef0c57b42190ddc01dbdea1b0168d6e8295581d1d37a13`. ZIP not independently downloaded. Actual log retrieved, 96 reference and 96 held-out case records, full structured evidence retained. Independently recomputed every raw held-out batch statistic, decision, byte totals/regret, fixed-class packing and screening gate; verified all lane stable fields and R115 reference checksum/size/packing fields. No first error in hosted execution. Initial wrong assignment filename lookup recovered 404; no execution impact.
- Baseline CPUID supported, same allowed logical CPU, exact common objects; GCC and Clang ASan/UBSan Werror and separate optimized GCC PASS both backends. Software CRC opcode count 0, SSE4.2 counts 2/2/68; exact R115 256 oracle vectors and full per-page CRC reference match. Actual production codec.c and ordinary compressor unchanged. Old reference only one correctness execution per path/micro-operation; old 20-pair timings omitted. All held-out byte and CRC gates before metrics. Host liblz4/pinned Linux LZO C/scalar predictor; no kernel dispatch or actual lower I/O.
- Fixed held-out seed 0x6d2b79f5, seven 32-page families, 224 pages per codec. No nonconstant held-out page CRC overlaps the frozen R115 reference; constant controls may overlap. CRC comparison is a conservative disjointness check, not statistical independence. New varied repeat widths, mixed boundary prefixes, short repeated arithmetic words, grouped delta-friendly words, high entropy and state gates. Static modeled pressure/read/queue/budget and metadata, not actual STORED, queue reservations, authority or residency. Model constant pages as known same-filled representations; ordinary baseline still decodes synthetic compressed representation (not actual native same-filled path). No ordinary compression or decode before selector choice; C translation checked per decision against frozen Python selector, no content/ID/outcome input. Selected pages preserve actual original bytes; all declines use one ordinary decode/recompress, no oracle-dependent fallback or real claim. LZO negative control. No selected-only CPU measurement; selected subset bytes exact, full and family CPU measured.
- Inclusive thread CPU write includes selection for policy, original decode/recompress if declined, copy and CRC; read follows actual record type, full readback checked outside timers. Three warmups, 20 alternating within-backend AB/BA pairs; separate binaries/codec execution order as R115. Selector standalone 64 repetitions per batch, 20 batches; includes traversal/output stores/barrier, not subtracted from full path. This is a C translation cost, not Python runtime or kernel metadata acquisition. Packing outside timing, actual ordinary planner/builder/read, policy fixed-class length-only model. p95/p99 refer to batch means, not page fault tails.

## Optimized full-policy results

Paired policy-minus-ordinary median ns/all pages; negative faster. All rows are separately timed; aggregate is not a sum of family timings.

| Codec | Family | Selected | Payload ordinary / policy B | Regret B | Worst page B | SW write | HW write | SW read | HW read | SW/HW selector ns |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LZ4 | all_heldout | 105/224 | 225535 / 228113 | 2578 | 176 | -556.2 | -609.2 | 14.9 | -18.4 | 2.4 / 2.4 |
| LZ4 | constant_controls | 0/32 | 416 / 416 | 0 | 0 | 3.8 | -9.5 | -0.2 | -4.4 | 1.5 / 1.6 |
| LZ4 | varied_repeat_width | 25/32 | 13303 / 13303 | 0 | 0 | -525.6 | -492.3 | 1.4 | 0.5 | 3.4 / 3.4 |
| LZ4 | mixed_boundary_prefix | 14/32 | 43084 / 43084 | 0 | 0 | -535.6 | -504.5 | -1.9 | 1.0 | 3.0 / 3.0 |
| LZ4 | short_repeated_delta_words | 32/32 | 4397 / 6975 | 2578 | 176 | -1193.5 | -1474.9 | 122.1 | -179.9 | 3.4 / 3.4 |
| LZ4 | grouped_delta_words | 24/32 | 19842 / 19842 | 0 | 0 | -1404.1 | -1372.9 | 0.5 | 1.0 | 3.4 / 3.4 |
| LZ4 | high_entropy | 0/32 | 131072 / 131072 | 0 | 0 | -4.3 | -1.3 | 0.7 | 0.1 | 1.1 / 1.2 |
| LZ4 | state_gate_controls | 10/32 | 13421 / 13421 | 0 | 0 | -207.3 | -197.0 | 1.8 | 3.5 | 2.3 / 2.3 |
| LZO1X | all_heldout | 0/224 | 225535 / 225535 | 0 | 0 | 21.3 | 11.1 | -15.4 | 2.8 | 2.4 / 2.4 |
| LZO1X | constant_controls | 0/32 | 416 / 416 | 0 | 0 | 1.8 | 1.1 | 22.6 | -1.5 | 1.6 / 1.6 |
| LZO1X | varied_repeat_width | 0/32 | 13303 / 13303 | 0 | 0 | 3.7 | 5.6 | -0.8 | -0.2 | 3.4 / 3.4 |
| LZO1X | mixed_boundary_prefix | 0/32 | 43084 / 43084 | 0 | 0 | 6.4 | 3.9 | -2.7 | -3.3 | 2.9 / 2.9 |
| LZO1X | short_repeated_delta_words | 0/32 | 4397 / 4397 | 0 | 0 | 6.3 | 5.0 | 0.4 | -1.1 | 3.4 / 3.4 |
| LZO1X | grouped_delta_words | 0/32 | 19842 / 19842 | 0 | 0 | -3.4 | 6.6 | 0.3 | 0.0 | 3.4 / 3.4 |
| LZO1X | high_entropy | 0/32 | 131072 / 131072 | 0 | 0 | 1.6 | -0.0 | -3.1 | 1.7 | 1.2 / 1.1 |
| LZO1X | state_gate_controls | 0/32 | 13421 / 13421 | 0 | 0 | 1.0 | 3.1 | -0.2 | -0.3 | 2.3 / 2.3 |

LZ4 selected 105/224, declined 119, no diagnostic-oracle fallback. Selected subset ordinary 35258 B versus preserved 37836 B; all-page 225535 -> 228113 B (+2578, +1.143%). Short repeated delta words all 32 selected, 4397 -> 6975 B (+58.63%), all 32 inflated, worst individual +176 B. Every other family payload equal. LZO selects 0/224 and payload unchanged; aggregate write overhead +21.3/+11.1 ns on SW/HW, standalone selector about 2.4 ns/call. LZ4 full-policy write delta -556.2/-609.2 ns on SW/HW, both 20/20 faster pairs; read +14.9/-18.4 ns, 5/20 and 18/20 faster pairs. No claim of causal additive decomposition, no inference of native read/write benefit or fault latency.

### Boundary coverage and packing

| Codec | Boundary B | Exact | Within 8 below | Within 8 above |
|---|---:|---:|---:|---:|
| LZ4 | 128 | 2 | 4 | 16 |
| LZ4 | 768 | 2 | 9 | 11 |
| LZ4 | 3568 | 0 | 1 | 1 |
| LZO1X | 128 | 0 | 0 | 0 |
| LZO1X | 768 | 0 | 0 | 0 |
| LZO1X | 3568 | 0 | 0 | 0 |

LZ4 exact 128 and 768 covered twice each; 3568 exact not achieved (one below and one above within eight bytes). LZO no exact/near values within eight bytes at these boundaries. No post-hoc adjustment. Selector state refusal reasons and per-page metadata, CRC, sizes and raw timing pairs retained in JSON.

| Codec | Family | Actual ordinary planner B | Ordinary fixed 4/8/16 KiB model B | Policy fixed model B |
|---|---|---:|---|---|
| LZ4 | all_heldout | 233472 | 233472 / 233472 / 241664 | 237568 / 233472 / 241664 |
| LZ4 | constant_controls | 4096 | 4096 / 8192 / 16384 | 4096 / 8192 / 16384 |
| LZ4 | varied_repeat_width | 16384 | 16384 / 16384 / 16384 | 16384 / 16384 / 16384 |
| LZ4 | mixed_boundary_prefix | 45056 | 45056 / 45056 / 45056 | 45056 / 45056 / 45056 |
| LZ4 | short_repeated_delta_words | 8192 | 8192 / 8192 / 16384 | 8192 / 8192 / 16384 |
| LZ4 | grouped_delta_words | 20480 | 24576 / 24576 / 32768 | 24576 / 24576 / 32768 |
| LZ4 | high_entropy | 131072 | 131072 / 131072 / 131072 | 131072 / 131072 / 131072 |
| LZ4 | state_gate_controls | 16384 | 16384 / 16384 / 16384 | 16384 / 16384 / 16384 |
| LZO1X | all_heldout | 233472 | 233472 / 233472 / 241664 | 233472 / 233472 / 241664 |
| LZO1X | constant_controls | 4096 | 4096 / 8192 / 16384 | 4096 / 8192 / 16384 |
| LZO1X | varied_repeat_width | 16384 | 16384 / 16384 / 16384 | 16384 / 16384 / 16384 |
| LZO1X | mixed_boundary_prefix | 45056 | 45056 / 45056 / 45056 | 45056 / 45056 / 45056 |
| LZO1X | short_repeated_delta_words | 8192 | 8192 / 8192 / 16384 | 8192 / 8192 / 16384 |
| LZO1X | grouped_delta_words | 20480 | 24576 / 24576 / 32768 | 24576 / 24576 / 32768 |
| LZO1X | high_entropy | 131072 | 131072 / 131072 / 131072 | 131072 / 131072 / 131072 |
| LZO1X | state_gate_controls | 16384 | 16384 / 16384 / 16384 | 16384 / 16384 / 16384 |

LZ4 aggregate modeled 4KiB placement grows 233472 -> 237568 B; 8/16KiB models unchanged. Actual ordinary aggregate planner 233472 B. No actual mixed opaque packing or disk amplification inference.

## Predeclared screening verdict

| Gate | Software | SSE4.2 |
|---|---|---|
| integrity | PASS | PASS |
| no_unsupported_selection | PASS | PASS |
| positive_full_policy_write_improvement | PASS | PASS |
| no_aggregate_payload_inflation | FAIL | FAIL |
| no_family_payload_inflation | FAIL | FAIL |
| no_selected_family_write_regression | PASS | PASS |

**HOST_POLICY_NO_GO on both.** The length-only gate fails even on a deliberately small independent synthetic corpus; write CPU benefit does not override payload inflation. No threshold tuning on held-out data and no further unchanged run. Ordinary remains default; A1 decides whether any new investigation warranted. No native admission/authorization or physical qualification. AUTH=0 Phase A BLOCKED observation UNKNOWN compressed handoff/forced RAW/import OFF physical NO_GO. Agent1 acceptance only.
