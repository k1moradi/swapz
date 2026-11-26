# R097 Agent10 — directed native qualification (IN_PROGRESS)

[Source 007621f40e839e119851fce0c3d63ffd9d776153](https://github.com/k1moradi/swapz/commit/007621f40e839e119851fce0c3d63ffd9d776153), sole actual parent 25bf051dbb7ff4496075238f614611f16f37dc51; engineering freeze f7cb6969db189c03d592a89cae43e5464946c716, original Linux c339f4010dea8b0d754f84ace70cd1b089878ef8. [Verifier](https://github.com/k1moradi/swapz/blob/007621f40e839e119851fce0c3d63ffd9d776153/tests/tools/round097-directed-native-compile-verify.py), [workflow](https://github.com/k1moradi/swapz/blob/007621f40e839e119851fce0c3d63ffd9d776153/.github/workflows/phase-a-round097-directed-native-compile-noauth.yml), [native staging and future distro compatibility prerequisites](https://github.com/k1moradi/swapz/blob/007621f40e839e119851fce0c3d63ffd9d776153/docs/handoff/zswapz/round097/agent10-native-staging.md). Four source/test/docs paths, no production changes. Complete historical standards parent blob f699ab78cc8cd0a11a8b557b572ee9eeb7c82bb7 plus appendix verified by exact full blob readback, new blob bec6666e6222b0eca25df5d4c1b0b197cbbaef23; canonical parent/source checks in hosted workflow. Prior R096 full link accepted without replay.

Exact raw chain includes only qualified R095 capture-off fee3d20b8ef872528b1301597eb33e0e0282da52 (98a8a6a66858204b61875ad9b2e8cfb0ecf8980a -> 9278abca17077bf9c0e94885eb4d46cdbd9202bd) and actual R096 retry 6ee63e6515dd2f0337c49d1a868f39435b93119c, ticket/owner postimages 70109f2c2ce9f60681649bd4807382248d0a41a2/278a93a3fd3fd260444aebc55d4a87112e56f704. All 54 frozen product paths pinned, historical callback recorder excluded from staging, selected RCU adapter only. Changed native ticket broker, RCU adapter, DM, gated storage and gate/provider dependency are the five requested directed objects. Early real ELF/OpenSSL probes, actual config/Kbuild, real workqueue and RCU relocations and atomic instruction verification, storage-to-gate references, old target bridge and absence of observation hooks, diagnostic mixed-domain ET_REL via ld -r. No full kernel or final ko, no MODPOST or synthetic stubs/symvers. Actual compile and object counts not yet reconciled. Recorder header's historical source literal is lineage, not current source authentication. No native positive path, native execution or physical readiness.

## Focused CI snapshot

[Run 45856047307/job 140034584799](https://github.com/k1moradi/swapz/actions/runs/45856047307/job/140034584799), attempt 1: in_progress, conclusion pending. Steps: Set up job=success; Run actions/checkout@v4=success; Canonical exact source and parent before scratch checkout=success; Provision compiler, ELF and kernel build prerequisites (runner packages only)=in_progress; Verify actual ELF and OpenSSL compile/link prerequisites before Linux checkout=pending; Run actions/checkout@v4=pending; Run actions/checkout@v4=pending; Raw immutable stage, directed changed objects and diagnostic relocatable only=pending; Preserve exact compile logs and manifest even on failure=pending; Post Run actions/checkout@v4=pending. Exact-source automatic census {"success":1,"in_progress":7,"queued":2}. No terminal first-error or artifact verification yet; no native PASS claimed. No additional manual dispatch.

AUTH0 Phase A BLOCKED; compressed handoff, forced RAW bypass and import OFF; no VM, boot, load, physical mutation or owner tests, no same-round dependencies. Terminal evidence-only update requires actual existing job logs/artifact, not a repeat.


## Agent1 independent reconciliation (A11 still pending)
```json
{
  "source": "007621f40e839e119851fce0c3d63ffd9d776153",
  "run": 45856047307,
  "job": 140034584799,
  "conclusion": "FAIL_NATIVE_VERIFIER_AFTER_FIVE_OBJECTS_COMPILED",
  "first_error": "native-owner-recorder-symbol-check recorder-atomic-reservation-instruction",
  "artifact": 15135832585,
  "sha256": "b50ab4396e4326ab32ca23bf9d12cf86aa2b0d0fb9bc49d78c7f7f410867c174",
  "archive_bytes": 198620,
  "entries": 64,
  "objects_compiled": 5,
  "object_hashes_verified": 5,
  "object_sha256": {
    "native-observation-adapter.o": "28a8d65b4f1df33fd692c8383af4bb387f093ddc6a7cf14fbac9bc99f5f2a2fd",
    "zswap-original-ticket.o": "e50e3ea34d348bdceb825977b2b276061234713bef358ea66e249d0be3116122",
    "dm-target.o": "cb14d1138e9b59287da023610a3fbe961373ad98fb3a49bf73c4b80d605ba8ec",
    "zswap-original-decoder-shared.o": "3cb06bd8cb438c1a94ba811cbac7a58208eadf5dd7056fe7f3807695c07858f8",
    "zswap-original-storage-shared-decoder.o": "43fb4c0e6e5b48f49891115bb1d0a088ad014b6cac6f105fe436553458124306"
  },
  "actual_config": "CONFIG_SMP not set, CONFIG_TINY_RCU=y, CONFIG_PREEMPT_LAZY=y",
  "actual_cmpxchg_sites": [
    "0x63d cmpxchg %edi,(%rsi)",
    "0xae3 cmpxchg %r9d,(%r8)"
  ],
  "actual_rcu_import": "synchronize_rcu",
  "actual_owner_workqueue_import": "queue_work_on",
  "adapter_gate_imports": 4,
  "adapter_direct_provider_imports": 0,
  "diagnostic_composite": "NOT_RUN",
  "full_kernel_link": "NOT_RUN",
  "modpost": "NOT_RUN",
  "exact_census": {
    "success": 7,
    "failure": 1,
    "queued": 1,
    "in_progress": 1
  },
  "scope": "Actual raw overlays and five native directed objects compiled; verifier demanded literal lock cmpxchg on UP configuration. Retain FAIL; no evidence of SMP correctness. Correct build config and verifier based on actual architecture, not weaken regex or rerun same old composition."
}
```
