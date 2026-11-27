# Round 108 — Agent 2 evidence

**PASS_STRICT_TERMINAL_BYTE_HOST_AND_DIRECTED_BRIDGE_OBJECT_ONLY.** Issue #226; A1 owns integration/acceptance. Terminal host/directed-only evidence; earlier progress snapshot preserved below.

## Exact source/publication

Engineering freeze `f600b79e0e1a812cae4c1c0ae8ab9f68c3d34da3`, tree `e577889d015f85115b1dc1a9845e472e95884c01`; task `32e841f773cdf6fc0519f6747f255d7b4980a4f4`; Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`. [Source 6243f45a5f0f8d432bcb3ee5769f227c65ec3345](https://github.com/k1moradi/swapz/commit/6243f45a5f0f8d432bcb3ee5769f227c65ec3345), sole task parent, tree `674c84a848f32a6467436e7848c8993ef40548ce`. [Qualification-only correction 5ed7c52ceb03a503e57783bfc5b08bba8f38c6e6](https://github.com/k1moradi/swapz/commit/5ed7c52ceb03a503e57783bfc5b08bba8f38c6e6), sole source parent, tree `96a8510164d0cca714e9993a0860f5a0a7f3b4d4`. Both serialized fresh expected HEAD non-force main updates succeeded with exact immediate readback. Frozen dependency blobs verified before publication; no R108 A10 implementation consumed.

| Path | Frozen preimage | Current postimage |
|---|---|---|
| `src/kernel/native-observation-byte-bridge.c` | `81b86699c4790672ab6d35f1ac6ddbc70b9a165d` | `902507cb065828bfa9a8b732edd61fb26ca2f08d` |
| `tests/runtime/native/fixtures/round106-private-delivery.c` | `e7650577ab1142853a88c9277c3a06c4091e6149` | `bee7ff71ca2b89996568cebcf18a7f238d7e385a` |
| `tests/runtime/native/round106-private-delivery-test.py` | `5cf488b2da37d8523f91aedd0cfd1a2c075f1d99` | `9a55e450ab8137b233ac8c9dcbcc45d6c3500f18` |
| `.github/workflows/phase-a-round102-native-byte-collector-noauth.yml` | `e8ec80a40b2cf77730469359fdde411156d8edcf` | `66b642572ff5a33e73fbb19b2048f403fb58452f` |
| `tests/runtime/native/fixtures/round108-terminal-byte.c` | new | `8ecb8105291825ef6f16f9ca654993819c59903c` |
| `tests/tools/round108-terminal-byte-mutants.py` | new | `3a7acbed2548bb1a7a99f41621a93a9a8ab672cb` |

Original workflow postimage `41ccea26fb2202cf8d2a0c58f38f93e32abdbfab` corrected only as above. Shared integration H `e3bca3367459c7f79960105f63e9ddef4e95b4d6`, bridge H `8105f87229b3aac1d0d3f9798a59915af0232526`, owner C/H, collector C/H and adapter C/H unchanged exactly (see JSON). No target/controller/MM/DM source, wire or oracle change. Complete historical standards blob `87075de87c2668006077aac4e4eeb571c002f47b` recreated exactly before append; `fa5c52c0faffca01b22a7a2cba2b253511f8240a` exact prefix checked on remote readback (1935222 -> 1936753 bytes). Correction appended only to `3ca5c4cba656aa9d7ffaa7cee8cf584935423d0c`; hosted prefix check succeeded.

## Actual bridge correction

Under the existing bridge lock, shared terminal_ready requires the completed operation, candidate/carrier releases for captured input, and scans only bounded state->pages (<=16) for token OR committed input. Only successful BIND consumes the committed bank into the collector; canceled replacement does not retire the prior bank. A still-committed unrepresented bank is evidence debt; a historical store sequence with committed=false is not. No assertion-generated retirement. CLEANUP also checks flags7 and all previous schema counters plus quarantines. Finish after cleaned loses evidence before the token scan and retains the banks/token, without altering the external join requirement; ordinary completion not changed. Close repeats the actual bounded input/operation census even if cleaned. Existing exact_record checks committed recorder sequence, capacity, contiguous ordinal and field equality; export still compares last_sequence to sealed recorder count. No hot-path scan, new lock, endpoint, or positive authority. Active hint unchanged.

The historical R106 claimed-error private export fixture now requires refusal at CLEANUP for nonzero quarantine rather than allowing an oracle-classified blocked bundle. The R099 oracle itself and independent historical tests remain unchanged. Historical actual transition extraction retained as host-modeled compatibility; current R108 frozen controller `0ea943f55449cacae473c182f33e75c48eb371bb` terminal shape source check adds seven debt fields, flags, and ordinal forwarding before stop. Current controller not executed end-to-end. No native CLEANUP credit from synthetic fixtures.

## Tests and qualification (observed)

Existing host private delivery/retry/actual producer modes retained with corrected claimed-error expectation; new pending token + late finish/cancel, committed-unrepresented, late stage/finish after accepted cleanup, duplicate cleanup, nonzero quarantine, wrong ordinal, independent close residual pending/committed and late finish private-state injection. The injected impossible states test defensive gates only and are explicitly not reachable native proof. Five narrow mutants target pending census, committed census, cleaned finish guard, quarantine and independent close. GCC/Clang strict ASan/UBSan Werror planned; exact changed bridge object only against genuine pinned Linux generated SMP/TREE_RCU/module-unload headers, no full link. No compiler counts claimed before results.

Initial automatic [run 46029977657](https://github.com/k1moradi/swapz/actions/runs/46029977657) terminal FAILURE, zero jobs. First observed error: malformed workflow YAML tail caused by replacement-string expansion (exact published blob contained duplicate tail). No host/native compilation happened. Fixed only workflow and append-only standards; no manual rerun or duplicate dispatch.

Corrected [run 46030111164/job 140611454673](https://github.com/k1moradi/swapz/actions/runs/46030111164/job/140611454673), exact qualification source, attempt 1: **IN_PROGRESS** at this checkpoint.
- Set up job: completed / success
- Run actions/checkout@v4: completed / success
- Source, frozen oracle and complete standards prefix: completed / success
- Provision real kernel build prerequisites on hosted runner: completed / success
- Changed private delivery and actual frozen transition contracts: completed / success
- Run actions/checkout@v4: in_progress
- Directed changed bridge object only, exact Linux SMP generated headers: pending
- Retain bounded redacted evidence only: pending
- Post Run actions/checkout@v4: pending
- Post Run actions/checkout@v4: pending
No terminal compiler/check counts, config or object hashes, artifact digest, or final first error available at this snapshot. Local git checkout failed DNS resolving github.com; no local C compile claimed. A10 alone owns full connected compile/link. No runtime, VM, module load, activation, device access or physical mutation. AUTH=0; Phase A BLOCKED; compressed handoff, forced RAW, import OFF; physical NO_GO.

## Terminal update — host and directed bridge object PASS

Corrected run [46030111164 / job 140611454673](https://github.com/k1moradi/swapz/actions/runs/46030111164/job/140611454673), attempt 1, exact tested SHA `5ed7c52ceb03a503e57783bfc5b08bba8f38c6e6`, terminal SUCCESS, all steps successful. First error on corrected run: none. Historical initial workflow parse failure remains recorded above. Exact complete standards prefix 1936753 -> 1937111 bytes confirmed by hosted log.

GCC 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1) and Clang 18.1.3 (Ubuntu 1ubuntu1), strict C2x O2 Werror with ASan/UBSan: **49 checks per compiler, 98 total**, 13 historical actual extracted transition modes each; 17 frozen functions, 12 initializer shapes. Five mutants killed per compiler, 10 total: pending_finish, unrepresented, late_finish_internal, quarantine_debt, close_pending. Both compiler logs exactly report R108_TERMINAL_BYTE_HOST_PASS and native_capture=false; all compile log files empty. Frozen current controller terminal shape PASS (source only). Guard-off exercised in changed-source suite, no separate historical standalone rerun.

Directed genuine pinned Linux x86_64 changed bridge object only: SMP=y TREE_RCU=y NR_CPUS=4 MODULES=y MODULE_UNLOAD=y force unload disabled, TINY_RCU absent. Actual symbol manifest independently checked: all six existing exported trial byte symbols present; all five private bridge owner functions defined but not exported (including no __export_symbol marker); collector stop_after_join import present. ELF64 little-endian ET_REL x86-64. No full link by A2.

| Independently verified artifact member | Bytes | SHA256 |
|---|---:|---|
| effective.config | 40815 | `623c5c642fe5859ebcc5de43ba864317c22a98b6300c8150171858d0f0b93108` |
| native-observation-byte-bridge.o | 19024 | `5ff81dc0e1b8605c800cf345402e2b87452636f7b91a1b66fb8c734f346b47eb` |

[Artifact 15213583264](https://github.com/k1moradi/swapz/actions/runs/46030111164/artifacts/15213583264): independently downloaded ZIP, 27032 bytes, SHA256 `c9c3b0a4d19ee433be0a254f93b8128d4259840beffc88229517b8116e39b797`. Exact metadata digest, ZIP CRC, member hashes/lengths, effective flags, native ELF header, source/parent and frozen dependency manifest, compiler and mutant outputs verified. No native workload, actual runtime terminal provenance, activation, device I/O, physical acceptance or connected link inferred. A10 owns connected build; A1 owns integration and acceptance. AUTH=0 Phase A BLOCKED, all switches OFF.
