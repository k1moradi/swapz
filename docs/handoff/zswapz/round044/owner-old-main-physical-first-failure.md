# Owner local `make test`: physically real FAILED at old `1539baeb`, reported recovery PASS — read-only forensics only

Evidence directly transcribed from owner-provided `make test` log on 2026-11-19; **this is owner-reported test output, not a new Agent1-run local/privileged test or independent hardware inspection**. Exact final line: `Tested Git commit: 1539baebb5d6245d752b41ab249aa9bf8ace675d`; initial fast-forward `ce68d2ad..1539baeb`, and `Local source qualification PASS source=1539baebb5d6`. **Older than all Round043** agent source changes `f6d974...`, `971b728...`, `5d4a0...`, `459df8...`, `c59f9e...`. Do not compare or attribute old physical outcome to new code.

Owner log lists Rootless stage 54 PASS cases, multiple synthetic owned-RAM loaded stages, `Stages passed: 5/5`, `loaded service: NOT QUALIFIED`. These are **not** original zswap STORED compressed handoff or full Phase A. Direct separate rootless `python3 -B tests/tools/round041-dm-target-verify.py host-test`: `Ran 2 tests in 22.630s OK` with GCC/Clang strict ASan/UBSan and hostile mutation result; not new Round043 original Linux 53 C KUnit.

After owner explicit confirmation, actual active SWAPSPACE2 backing trial failed:
```text
Physical | Authorized physical swap trial (dev) | FAIL
Physical first refusal: phase=anonymous_workload check=bounded_primary_workload reason=producer_refused original_errno=unavailable
Next: first producer cause UNKNOWN; review the retained private workload evidence and verified recovery.
PHYSICAL_RECOVERY_EVIDENCE=state:COMPLETE original_header_matches_final:PASS restored_swap_verified:PASS mapper_removal_succeeded:PASS module_cleanup_succeeded:PASS
Overall qualification: FAIL
make: *** [Makefile:90: test] Error 1
```

**Confidentiality:** user's actual device names, disk UUID/PARTUUID and host identity are deliberately NOT repeated here. The private **first failure producer** diagnostic file `build/tests/stage-failure-ruupwsex.private.log` (0600) and `build/tests/swapz-qualification-failure-mfjj8v0s.json` (0600) were **not** attached. No causal inference is possible from public outer message beyond `producer_refused`; no private log upload to public issue or routine report, avoid symlinks/revealing unique device IDs, redact if owner later supplies sanitized excerpt. `RECOVERY=COMPLETE` is source log claim, not an independently rechecked current boot state.

**Safety decision:** No additional privileged operation, physical `swapoff/swapon`, `mkswap`, mapper/module reload, memory pressure, partition rewrite or rerun of physical workload. Owner must first read/retain original private diagnostics locally, identify exact first failure and maintain safe rollback; any later physical trial requires distinct explicit new owner authorization and hardware recovery review. Current Round044 worker tasks are independent code/source-CI repairs, no private log required. Don't use `make test` or `make fast_test` to retry physical; run direct `python3 -B` source-specific rootless tests and exact-SHA GitHub original kernel/DM CI only.

**Architecture:** zswap only bounded RAM compressed cache plus native pressure, swapz only preformatted valid SWAPSPACE2 disk-tier 4/8/16KiB packing+GC; no competing reclaim, no compressed bytes as ordinary RAW_4096. Entire first physical 4096-byte SWAPSPACE2 header/UUID/signature, and partition table immutable. `PHASE_A=BLOCKED`, compressed handoff/forced bypass disabled; no loaded-original true source-to-DM evidence.
