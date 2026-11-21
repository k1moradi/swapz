# Round056 Agent6 — exact-source CI coverage and rootless first-error audit

**Scope and outcome:** Independent rootless/read-only inspection of the official Round056 frozen engineering source and its GitHub Actions evidence. **NO_CHANGE** to source, fixtures, workflows, production, or physical admission gates: no authenticated producer-specific reporting defect could be demonstrated from the historical owner evidence. This document is the evidence-only Agent6 delivery, not a production authorization.

- Official authorization: [issue #173 Round056 ROUND_OPEN](https://github.com/k1moradi/swapz/issues/173#issuecomment-7060046353).
- Frozen engineering: `1484efd1324feda5a8871e1a2c015393b3d1a435`.
- Frozen task/handoff: `7056741b12eac407314151a8f38e45e77a505603` (parent `1484efd1324feda5a8871e1a2c015393b3d1a435`).
- Actual pinned original Linux: `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`.
- Scope restrictions: no `make test`, `make fast_test`, root/sudo, loaded module, block device, physical swap, real memory pressure, swapoff/swapon, mkswap, mapper activation, null_blk, or reboot.

## Exact-source registered CI — verified terminal results

At frozen engineering `1484efd1324feda5a8871e1a2c015393b3d1a435`, GitHub Actions registered **17 workflow runs: 17 completed SUCCESS; 0 failure; 0 queued; 0 in progress** at inspection. Representative run IDs:

| Evidence | Run | Terminal |
| --- | --- | --- |
| Native project-goal/source-policy, make interface, 7 jobs | [44885212685](https://github.com/k1moradi/swapz/actions/runs/44885212685) | SUCCESS |
| Product C/codec | [44885212617](https://github.com/k1moradi/swapz/actions/runs/44885212617) | SUCCESS |
| Genuine product DM table/GC lifetime | [44885212541](https://github.com/k1moradi/swapz/actions/runs/44885212541) | SUCCESS |
| Independent natural-pressure/scheduler model | [44885212689](https://github.com/k1moradi/swapz/actions/runs/44885212689) | SUCCESS |
| Codec interop source subset | [44885212599](https://github.com/k1moradi/swapz/actions/runs/44885212599) | SUCCESS |
| Systemd and package rootless | [44885212607](https://github.com/k1moradi/swapz/actions/runs/44885212607) | SUCCESS |
| Synthetic physical-evidence safety and RAM source lease | [44885212665](https://github.com/k1moradi/swapz/actions/runs/44885212665) | SUCCESS |
| Other 10 registered native/DM/kernel workflows | Same exact SHA, Actions run inventory | 10 SUCCESS |

The historical original-kernel [run 44882263788](https://github.com/k1moradi/swapz/actions/runs/44882263788), source `d52ac8d12a8f4de5c60d68731f4b2e93fd59240d`, has **both actual jobs terminal SUCCESS**: original `CONFIG_ZSWAP=y` UML **66/66 genuine C KUnit** and full original Linux x86 `CONFIG_ZSWAP=y/n` with real GPL probe and matching DM module. Repaired raw-LZ4 original host-subset [run 44882508681](https://github.com/k1moradi/swapz/actions/runs/44882508681) at `31adfb7ff57cc5c061304beae749b485d093130b` is also terminal SUCCESS. Those are **ancestor-specific evidence**, not a fresh original-KUnit invocation on frozen engineering.

At frozen task/handoff source `7056741b12eac407314151a8f38e45e77a505603`, **four workflows registered: two terminal SUCCESS, two terminal FAILURE**:

| Workflow / run | Terminal | Actual first error |
| --- | --- | --- |
| [Project-goals 44885703834](https://github.com/k1moradi/swapz/actions/runs/44885703834) | SUCCESS | None observed |
| [Product-codec 44885703879](https://github.com/k1moradi/swapz/actions/runs/44885703879) | SUCCESS | None observed |
| [Original DM source/GC 44885703840](https://github.com/k1moradi/swapz/actions/runs/44885703840) / job `136790394825` | FAILURE, exit 2 | `git diff --check HEAD^ HEAD`: `docs/handoff/zswapz/round055/original-report-archive.md:94: trailing whitespace.`; then `...:160: new blank line at EOF.` |
| [Systemd/package 44885703844](https://github.com/k1moradi/swapz/actions/runs/44885703844) / job `136790395747` | FAILURE, exit 2 | Same first `original-report-archive.md:94: trailing whitespace.`; then line 160 extra EOF blank |

The failed commands were **patch-hygiene checks** on the newly added Round055 archived report, not original Linux compilation, runtime kernel or codec errors. Earlier actual test steps in those two jobs completed successfully. Preserve both failures and first-error order; do not relabel the handoff SHA all-green. The report is an original archive, so this independent lane does **not** silently rewrite it or suppress `git diff --check`.

## CI source-binding boundary and future minimal trigger decision

The original pinned 66-KUnit/full-x86 workflow `.github/workflows/phase-a-zswap-original-stored-bio-source-scope.yml` uses a **push `paths:` allowlist** (its workflow, actual original source compositor and selected Round038–054 verifier/fixture paths). That list does **not** include general `src/kernel/` product source edits, future Round056 new original fixture/verification paths, or the first-error harness. Thus **no original 66/full-x86 run was registered** for the frozen engineering/handoff SHAs. One may not substitute ancestor success for current-source CI coverage.

The original compositor file `tests/tools/stage-pinned-linux-zswap-composed.py` has identical Git blob SHA `47141947eba1f09a58d77554e08c50b7151767cc` at both the historical original success `d52ac8d...` and frozen engineering `1484efd...`. The compare from that original success to engineering is six direct descendant commits; relevant newly changed product file is `src/kernel/codec.c`, while newer independent scheduler/codec test paths change. The handoff commit changes documentation only. The file-level equivalence is useful **source consistency evidence**, but is **not** a new kernel boot, executable end-to-end test or current-SHA status check.

If a future Round056 original source composer or verifier changes, Agent2's original workflow should be reviewed for a narrow new path trigger or a separately authorized exact-SHA manual dispatch. Do not duplicate dozens of expensive original-kernel workflows, widen unrelated CI indiscriminately, or modify another agent's owned original workflow from this lane. The always-on `project-goals.yml` and `product-codec.yml` do register on main regardless of source paths; that does not replace actual pinned-original KUnit/y-n evidence.

## Rootless historical producer_refused investigation — no unproven diagnosis

The prior owner physical `make test` returned `producer_refused`. Its **underlying producer first cause remains UNKNOWN**; owner-reported recovery is not an independently checked hardware fact. No original owner private workload log, private mode-0600 source record or real child terminal envelope was supplied to this lane. Without one, inferring a codec, cgroup, RAM pressure, swap, target or hardware failure would be fabricated.

Read-only source trace:

1. `tests/tools/qualify-primary-real-swap.py` is the pinned original private producer; `physical-swap-probe.py::_algorithm_real_swap_workload` byte-compares it to the admitted Git tree before execution. No second pressure or reclaim controller is introduced.
2. `tests/tools/physical-swap-probe.py::_classify_algorithm_workload_first_cause` permits only literal source-defined safe classes or bounded/validated terminal-oracle envelopes. `_emit_algorithm_workload_failure` strips `; cleanup also failed:` so cleanup never supplies a counterfeit first errno, takes bounded first-error numeric observations from the causal chain, and emits one `PHYSICAL_ALGORITHM_DEBUG=` JSON marker. Unknown, oversized, partial or private producer text correctly falls back to **`producer_refused`**, not a guessed specific diagnosis.
3. `tests/tools/run-tests.py::parse_algorithm_pageout_diagnostic` requires exact schema and enumerated fields/reasons, bounded integer/enum observations, and exactly one marker. `print_algorithm_workload_diagnostic` prints first phase, gate, safe reason and original errno; for `producer_refused` it explicitly prints **first producer cause UNKNOWN** and retains private evidence without echoing arbitrary device identifiers, paths or stderr.
4. `tests/tools/run-tests.py::run_stage` retains failed stage output through its existing owner-only mode-0600 private stage log, prints an allowed repository-relative evidence location, a bounded source-located first failure where authenticated, and safe next actions. `tests/tools/algorithm-physical.py` emits source-identity pre-consent refusal through a separately validated stderr marker. Dirty tracked source, incomplete canonical identity and missing exact artifact evidence remain blocking source admission; no silent source reconciliation in `make test`.
5. Real rootless fake-producer regressions already exist in `tests/runtime/native/physical-swap-probe-test.py` (notably the source-defined oracle terminal/refusal and secret-redaction cases around lines 990–1082) and `tests/runtime/native/test-report-test.py` (schema, duplicate marker, private value and `producer_refused` UNKNOWN tests around lines 6931–7047). `tests/tools/ci-failure-diagnostics-test.py` covers first failure/cleanup precedence, authenticated child exit, secret suppression and private report location. Source does not automatically promote arbitrary private messages to public diagnoses.

Actual exact engineering GitHub rootless evidence: physical-evidence job `136788918504` in run `44885212665` **SUCCESS** with synthetic physical-campaign adversarial tests, RAM source-lease/selector nonadmission and separate offline classifier checks. The always-on project-goals run `44885212685` **SUCCESS** includes CI first-error diagnostic unit tests. These are CI rootless checks, **not a locally performed physical trial**. No physical exercise, owner `make test`, manual private traceback extraction or invented failure-mode fixture was used for this audit.

**Test-harness disposition: NO_CHANGE.** Existing intentional unknown-cause fallback and private safe first-error provenance do not demonstrate a fixable concrete historical defect without its missing first producer record. No synthetic test should upgrade that unknown historical cause to a named fault.

## Separate future owner authorization checklist (NOT requested now)

Any later owner-consented physical attempt requires an independently reviewed clean exact local source/manifest and qualified artifact hashes; actual first source-defined producer failure captured in pre-existing private mode-0600 evidence; safe bounded first-error summary with validated source, phase, original exit and cleanup precedence; independently verified prior same-boot ownership/recovery/partition identity; distinct prior-stage RAM qualification and unchanged physical `SWAPSPACE2` first full 4096-byte header/signature/UUID plus partition table. This checklist is a gate, **not** authorization to re-run owner tests or touch devices.

The architectural verdict remains `SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`, direct compressed handoff **DISABLED**, forced RAW bypass **DISABLED**, loaded/physical **NOT_RUN**. Linux zswap exclusively owns bounded compressed RAM and native MM natural-pressure eviction; swapz exclusively owns already-valid disk compression, packing and GC. Ordinary `RAW_4096` remains the entire original **uncompressed 4096-byte page**. No complete real original source-to-target ownership, stable retired-pool-independent decoder, durable lower write, one authoritative map, one genuine ACK and full original-page verified readback has been established.

**Publication contract:** Documentation-only report. No source, fixture or workflow edit; entire existing `docs/testing_standards.md` remains byte-for-byte unchanged. Any subsequent source/fixture/workflow change must carry its own substantive standards appendix in the same commit.
