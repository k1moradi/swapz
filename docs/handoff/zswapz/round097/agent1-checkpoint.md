# Agent1 R097 checkpoint (not all terminal)
Freeze 5a36cabf0989dfffc75de52a6ab8cc021092ebf6; tree f6ec6f6044d33d3f039592306851c09822b0c129; main only zero PR. A2/A3 focused PASS; A10 FAIL verifier after all5 objects compile; A11 queued (not accepted). Three downloaded archives actual CRC/SHA checked, five native object hashes match manifest. Actual config UP/Tiny RCU; two cmpxchg instructions without lock, verifier literal lock cmpxchg. Not compiler failure and not overall PASS. No ld-r/modpost/full link. A3 actual gated consumer and built-in retry host PASS; current DM intentionally append(NULL) when correlation absent. A11 staged patch builds later event records from CAPTURE, retaining forbidden nonzero fields; selected actual adapter validates per-event allowlist, not test-substitute append. Fix actual producer and consumer correlation against selected recorder. R098 four workers, A5/A7 stand down; A11 prior existing run must reconcile before claiming acceptance, no duplicate. One changed SMP directed composition with actual R097 staged sources; no old disconnected full build, full candidate link after real scope/producer/consumer correlation closure. Enable actual scoped development path in source only behind default-off guard, never invoke or authorize live activation. Current standards dff61588713f8ceeecb5e406cab8788e12990147 1874135 bytes unchanged by Agent1. AUTH0 Phase A BLOCKED, no owner tests now, no VM/load/physical.
## Agent2
```json
{
  "source": "be44c51e132593c81f2d1ba773767efecea6792b",
  "run": 45856564834,
  "job": 140036377176,
  "conclusion": "PASS_SELECTED_OWNER_HOST_SUBSTITUTES_ONLY",
  "artifact": 15135253842,
  "sha256": "3b47f7bbf104cecc90558f5b4b25197689916bd294106f92fa380b4599db3829",
  "archive_bytes": 2069,
  "entries": 11,
  "checks_each": 481,
  "modes_each": {
    "clean": 237,
    "join": 118,
    "overflow": 63,
    "invalid": 63
  },
  "source_correlation_cases": 11,
  "exact_census": {
    "success": 7,
    "queued": 2,
    "in_progress": 1
  },
  "scope": "Actual one-shot owner wrappers with host substitutes; selected adapter/parser unchanged; native controller, external drain and producer correlation not established."
}
```

## Agent3
```json
{
  "source": "f15e3682c87444dde69c1ee75b6e4f3ad146493f",
  "run": 45856728473,
  "job": 140036956683,
  "conclusion": "PASS_ACTUAL_GATED_TARGET_RETRY_HOST_ONLY",
  "artifact": 15135319557,
  "sha256": "81f61ec8f9389f56b181b7a4e6906745173e5cc0866eeb76f5ea1f87541bc8fe",
  "archive_bytes": 944,
  "checks_each": 453,
  "claims_each": 3,
  "claimed_errors_each": 1,
  "typed_reads_each": 2,
  "fallbacks_each": 2,
  "preparations_each": 2,
  "reopens_each": 5,
  "retries_each": 5,
  "observation_losses_each": 3,
  "mutants_each": 4,
  "mutant_names": [
    "no_retry_transfer",
    "wrong_read_epoch",
    "ignore_gated_scope",
    "ignore_missing_observation"
  ],
  "inventory": 61,
  "exact_census": {
    "success": 13,
    "queued": 7,
    "in_progress": 10
  },
  "scope": "Actual frozen A5 gated storage, A11 retry, original codecs, retained pin through copy; host Linux/DM/lower/upper substitutes. Native scope hard false, missing correlation deliberately records invalid append. No native execution."
}
```

## Agent10
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

## Agent11
```json
{
  "source": "23979a8e43ff0796018d0bb63675a63d1c52be8e",
  "run": 45856892403,
  "job": 140037517664,
  "conclusion": "QUEUED_NOT_ACCEPTED",
  "artifact": null,
  "checks_each": null,
  "mutants_each": null,
  "first_error": null,
  "exact_census": {
    "success": 3,
    "queued": 7
  },
  "scope": "Source staged only; original MM scope static const zero and claim hard-off, no scope publication. Actual producer event construction reuses CAPTURE fields in PREPARATION/BIND/UPPER_ENDIO/CAPTURE_DROP/CARRIER_RELEASE; selected adapter allowlist rejects those nonzero unused fields. This is a source-review integration defect, not observed CI failure. R098 A11 must first reconcile existing run without rerun and report actual results, then fix event construction and scope/correlation contract."
}
```
