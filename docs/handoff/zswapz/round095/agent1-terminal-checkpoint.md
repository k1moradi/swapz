# Agent1 R095 terminal reconciliation / R096 publication recovery
Connector restored. Freeze cb38c5de310edc4842e77099b92fc709e1934322, sole main, zero PR. All six focused jobs success from actual logs; six ZIP downloads CRC and SHA256 match upload digests, retained native vmlinux/ko sizes and hashes recomputed. A2 and A11 final exact source10/10, A3 30/30, A10 10/10; A5 and A7 10/11 historical legacy YAML failures, not whole-main green. A7 artifact round field094 retained as historical mislabel. A11 actual2 mutants per compiler, four combined. Current standards blob4152a1ce0c067ccb6b872f5f7aa0b89507ec8f2e,1856114B; no standards changes by Agent1. All six preliminary R096 reports are read-only; no new engineering source yet, no R097. A10 accepted R095 native binary references old bounded bridge; newer storage/gate and MM changes not included. Actual A11 qualified capture-off patch after R092 exact postimage, do not stack alternative observation-fence. R096 owner retry semantics frozen to permit independently implemented producer and consumer. No duplicate qualification; no new VM/load/physical/activation. No owner test now. AUTH0 Phase A BLOCKED.
## Agent2
```json
{
  "source": "73e11ed4b50fb34a02e1c5cb9c0821a050d85619",
  "run": 45798553476,
  "job": 139835434200,
  "conclusion": "PASS_CHANGED_HOST_RECORDER_RESERVATION_ONLY",
  "artifact": 15104939406,
  "sha256": "9d9be4817c68c85b1d10e1969b02d2a1be9202a8e33b92351286478a8b21b3b9",
  "checks_each": 1027438,
  "scenarios_each": 14,
  "full_capacity_records_each": 98304,
  "all_recorded_each": 99328,
  "attempted_each": 114688,
  "expected_overflow_each": 13312,
  "owner_bytes": 72,
  "wire_bytes": 296,
  "cas_attempts": 64,
  "exact_census": {
    "success": 10
  },
  "scope": "No unexpected loss in tested schedules; intentional overflow remains; earlier Clang 50% loss preserved. Native adapter/actual causality/entry fence absent."
}
```

## Agent3
```json
{
  "source": "4b15bdf4f841195ed240243a81ed13eaad7cf396",
  "run": 45785010481,
  "job": 139789467324,
  "conclusion": "PASS_COMPOSED_HOST_ONLY",
  "artifact": 15100256797,
  "sha256": "c637d8cfdf0685f7df800aa1bc1d8ccc1e735902b45d3d43449cc08f172f2d32",
  "checks_each": 673,
  "claims_each": 5,
  "claimed_errors_each": 3,
  "typed_reads_each": 2,
  "modeled_fallbacks_each": 6,
  "modeled_preparations_each": 6,
  "reopens_each": 11,
  "mutants_each": 4,
  "inventory": 54,
  "exact_census": {
    "success": 30
  },
  "scope": "Actual extracted target/owner/broker/storage and original codecs. Host Linux/DM/RCU/lower/upper completion modeled; actual sole native caller hard false; no final busy-owner retry proof."
}
```

## Agent5
```json
{
  "source": "34ef333e5054f6428776dcfab63baa6309c1d4ac",
  "run": 45770731713,
  "job": 139742467480,
  "conclusion": "PASS_ACTUAL_SHARED_PROVIDER_STORAGE_HOST_ONLY",
  "artifact": 15093569167,
  "sha256": "69c4205f1885f79384e5ed43a3fbfc4f5c5b3b98e10bdafed87dca892f8193dd",
  "checks_per_compiler": {
    "lz4": 12464,
    "lzo1x": 16561
  },
  "lower_reads_per_scenario": 9,
  "lifecycle_get_put_per_scenario": [
    2,
    2
  ],
  "transient_get_put_per_scenario": [
    6,
    6
  ],
  "storage_bytes": 15296,
  "legacy_bytes": 14912,
  "overhead_bytes": 384,
  "provider_bytes": 312,
  "sidecar_bytes": 1112,
  "handle_bytes": 24,
  "map_bytes": 20,
  "exact_census": {
    "success": 10,
    "failure": 1
  },
  "historical_failure_run": 45770729983,
  "scope": "Actual frozen R094 shared decoder joined to storage, modeled RAM lower/epoch; eight-record authority; no new mutation count; no full pre/post-GC compressed image equality; strengthened R095 gate not yet joined."
}
```

## Agent7
```json
{
  "source": "21e8533bfdbdc8e09ee86e2a8e8c63f0a36a7cdd",
  "run": 45770634552,
  "job": 139742145865,
  "conclusion": "PASS_ACTUAL_SHARED_PROVIDER_LIFETIME_HOST_ONLY",
  "artifact": 15093757410,
  "sha256": "b6281fc8eb17be9345af38a853c2537152a9ebe3eb2efa617d43111037ba719f",
  "checks_each": 81,
  "mutants_each": 5,
  "owner_bytes": 312,
  "gate_bytes": 88,
  "handle_bytes": 24,
  "exact_census": {
    "success": 10,
    "failure": 1
  },
  "historical_failure_run": 45770632922,
  "artifact_round_field": "094 (historical label; source pins, R095 fixture, job and verdict establish actual R095 lane)",
  "scope": "Actual gate and provider source-linked; external fresh broker capability/storage pin trust, no native reload or storage gate join yet."
}
```

## Agent10
```json
{
  "source": "771340dc5f568bf853c433636a36024f5ea75794",
  "run": 45770431310,
  "job": 139741479810,
  "conclusion": "PASS_FULL_FROZEN_NATIVE_KERNEL_MODULE_COMPILE_LINK_ONLY",
  "artifact": 15093474500,
  "sha256": "03c054965e0c2313be5991f345eaccee51b97d25a3f6e6ac87667b05841bfe7a",
  "artifact_bytes": 3051339,
  "archive_entries": 48,
  "steps": 38,
  "actual_boundary_exports": 15,
  "module_imports": 101,
  "new_owner_imports": 3,
  "forbidden_exports": 0,
  "kernel_bytes": 12558720,
  "kernel_sha256": "e64d286366ceed259d3437787a2cc88e8a4693723f661d893d2606200c60f30d",
  "module_bytes": 428648,
  "module_sha256": "3db74181d77f1a05bce912b49ac6bad248bb27c3f162374ead693de20ffe5b15",
  "exact_census": {
    "success": 10
  },
  "frozen_product": "ff972661a75ca7f8c3c0458c3feb8b603c185eb8",
  "scope": "Actual R092/R094 raw overlays, full vmlinux, actual modpost and final ko. Target calls bounded bridge, zero direct shared/value API references. No R095 later changes, bootable image proof, runtime, physical admission; intermediate objects not retained."
}
```

## Agent11
```json
{
  "source": "62171f7502ab4d2dcc2e762abb534206bbcff7d6",
  "run": 45798829320,
  "job": 139836382630,
  "conclusion": "PASS_HOST_BOUNDARY_ONLY",
  "artifact": 15105438172,
  "sha256": "49f18128969d30ef08e851e053a068516ffdb2007cfec98908dc6929885d26a7",
  "checks_each": 24,
  "mutants_each": 2,
  "exact_census": {
    "success": 10
  },
  "qualified_patch": "fee3d20b8ef872528b1301597eb33e0e0282da52",
  "postimage": "9278abca17077bf9c0e94885eb4d46cdbd9202bd",
  "scope": "Actual R095 unconditional capture-off overlay after R092 MM postimage. Both store and preerase guard removal mutants killed per compiler. Native carrier EBUSY and close identity retry unresolved. Do not stack alternative observation-fence patch."
}
```
