# Round088 Agent9 — physical-first readiness and VM routing

Status: **PROGRESS — rootless routing PASS; physical qualification BLOCKED / NOT_RUN.** Published source migration: [7afebebe0c968c77a77ebe179f6f88974763d25a](https://github.com/k1moradi/swapz/commit/7afebebe0c968c77a77ebe179f6f88974763d25a), sole parent f654ebf552319a3bd6e6eef260de3fd005681ae8; verified 43 changed paths and non-force expected-head publication. Exact-source CI is QUEUED. Task dcb65dca9a3c2bd990aedb2829181d0c0e015ce2; refreshed routing baseline / expected parent f654ebf552319a3bd6e6eef260de3fd005681ae8. Read the immutable [Round088 contract](https://github.com/k1moradi/swapz/blob/dcb65dca9a3c2bd990aedb2829181d0c0e015ce2/docs/handoff/zswapz/round088/agent9-physical-first-readiness-p0.md), AGENTS.md, AGENT_CONTEXT physical rules, production acceptance and existing helper implementations. No other agent's implementation was used as a dependency.

## Workflow migration and evidence

- Audited 84 original workflow definitions (31 VM-containing); reran against the fresh parent's 87 definitions, including four peer host workflow inputs (one modified and three new), without editing those inputs. The [manifest](agent9-workflow-manifest.json) records every baseline blob, job, route, exact conflict and scenario.
- Seventeen historical original definitions retain complete unchanged jobs and their original manual dispatch semantics. Their former push path filters (including original self, plus companion self) route to new source-push companions containing exactly 21 original non-VM jobs. No job-level skips, weakened checks, altered dependencies, permissions or concurrency. Existing dispatch limitations involving push-before are unchanged; no dispatch attempted.
- One push-only ticket QEMU job retired from automatic execution: byte-identical original definition [archived here](agent9-archived-ticket-qemu.yml); source checkout, true push-before, repository-policy, original stage and diagnostic regression retained as an automatic rootless stage. No fabricated native PASS. Historical R087 Agent11 QEMU evidence remains distinct: [run](https://github.com/k1moradi/swapz/actions/runs/45455624750), [job](https://github.com/k1moradi/swapz/actions/runs/45455624750/job/138664150782), source 67a036d89a1a7412a27f9450df549347146e758f; six cases previously passed, not physical evidence.
- Thirteen mixed lanes retained intact: round084 original store credential, origin KUnit, sideband, and the ten original bio-clone-copy, mm-async-lease-negative, mm-lifetime-owner, mm-route-witness, route-lifetime, sector-domain, store-bio-provenance, stored-bio-source-scope, v1-kunit and writeback-lifetime workflows. Their native jobs embed non-VM host/source/Kbuild checks or independent push-specific staging checks; separating them safely requires additional review. In particular a composer edit can still trigger ten VM jobs. Do not schedule such an edit to exercise VMs. This is not a blanket elimination of future automatic VM runs.
- Mandatory project-goals/repository policy, physical evidence, existing host jobs and peer workflows untouched. Branch read showed protected=false and empty required contexts; repo rulesets empty; detailed protection endpoint inaccessible (403), so no stronger branch-protection claim.
- Rootless exact regression function executed over full immutable workflow blobs in V8, then rerun against refreshed parent: PASS_ROOTLESS_VM_ROUTING, 87 -> 104 definitions, 18 automatic VM jobs retired, 17 manual full workflows preserved, 21 non-VM companion jobs, 611 path witnesses, 7/7 negative mutants, 134162 checks. Node Git-tree wrapper not executed locally (repository checkout DNS unavailable). Replay: node tests/runtime/native/round088-vm-routing-contract-test.mjs <migration-sha>. This is a trigger/job-definition census, not hosted-run completion; matrices and GitHub large-diff exceptions are not modeled.

| Changed paths | VM job definitions before -> after |
|---|---:|
| Ordinary DM source | 3 -> 0 |
| Codec source | 1 -> 0 |
| Ticket source | 1 -> 0 |
| Authority source | 4 -> 0 |
| Original composer | 13 -> 10 |
| Testing standards only | 3 -> 0 |
| Physical helper / evidence only | 0 -> 0 |
| Migration | 18 -> 0 |

Migration predicted 24 workflows, 51 -> 34 job definitions (zero VM). Observed migration registration matches prediction: 24 exact-source workflow runs, all QUEUED at the recorded census; zero identified VM workflow routes. Mandatory [project-goals run 45460996091](https://github.com/k1moradi/swapz/actions/runs/45460996091), [repository-policy job 138683197489](https://github.com/k1moradi/swapz/actions/runs/45460996091/job/138683197489), [native rootless job 138683198413](https://github.com/k1moradi/swapz/actions/runs/45460996091/job/138683198413), [physical-evidence run 45460995520](https://github.com/k1moradi/swapz/actions/runs/45460995520) / [job 138683196285](https://github.com/k1moradi/swapz/actions/runs/45460995520/job/138683196285), [ticket rootless stage run 45460995152](https://github.com/k1moradi/swapz/actions/runs/45460995152) / [job 138683193711](https://github.com/k1moradi/swapz/actions/runs/45460995152/job/138683193711). All exact-source run IDs recorded in results JSON. No terminal remote result or first error observed. Existing runs not cancelled; no manual dispatch or rerun.

## Concrete physical admission correction

The old plain development-only path was guaranteed to refuse at the loaded-RAM gate immediately before insmod, but after fast_test, inspection, ownership and MODULE_PENDING preparation. Move this refusal to run_probe preflight before all such activity. Keep the late defense and fail-closed exit 2. Do not loosen loaded-RAM, source or physical authorization. The CLI's admitted real-swap development route remains gated. Update dedicated tests, including artifact mismatch on the admitted route; production missing-state test preserved. No algorithm wrapper or production C/H change.

Exact original/candidate probe blobs 049d424c6de3bc27754af4649b8a831f8938cdb3 -> 51caaf3a74a79bcf202ecd7381a369bf9be4297f; test blobs 857aa8414052511bbe326929ef6c0f7e5f444f1e -> e2d471bd2b33f6a5cc9fdb6b8cf98cb6f0aa7829. Local Python executed a hash-verified exact run_probe prefix through artifact gate (54063d70337e32beeeb5ed662a1980aa5080bc47) and two exact test methods (8d411c7098ae6628ec0f4ebbf8ed7d82bf5ffaa1), with isolated minimal mock fixture: 2/2 PASS, guard-removal negative rejected 1/1. Initial excerpt transcription hash mismatch refused before test execution and was corrected; final execution no failure. All real side effects forbidden. Full dedicated suite and exact hosted CI not run locally; pending automatic source qualification. No actual host/module/swap/device operation.

## Owner-facing physical-first plan (future only; not an instruction to run now)

Current decision: NO_GO until Agent1 reconciles integrated exact source, artifact provenance, actual owner host and device, and explicitly admits the next phase. Historic report at frozen task has source/tested_commit 4ba067a90c4b102084841ad51627c4a29a0e4f07, all five RAM stages PASS but overall INCOMPLETE, RAM_BACKED_NULL_BLK_ONLY, ALGORITHM_PHYSICAL_PENDING; physical NOT_RUN (physical_source_admission_protocol_not_qualified). Neither this nor historical VM/host evidence binds the current owner host/source. No known authorized live PARTUUID, current device identity, host scope, current-source artifacts or integrated physical source authenticity. Do not select historical device names.

### A. Read-only inspection on the future owner host

```sh
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git status --porcelain --untracked-files=all
git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main
uname -m
getconf PAGE_SIZE
systemd-detect-virt --vm
systemd-detect-virt --container
lsblk --json --tree --bytes --output PATH,TYPE,FSTYPE,UUID,PARTUUID,SIZE,TRAN,MOUNTPOINTS
cat /proc/swaps
grep '^MemAvailable:' /proc/meminfo
```

Require clean sole main, exact current source (only validated report-only history exception), little-endian 64-bit Linux x86_64/aarch64, 4096 page size, bare metal, nonroot checkout owner, independently owner-verified dedicated partition or valid protected shared-root scope. Do not proceed from a bare /dev name, guessed PARTUUID, ambiguous inventory or a VM. Confirm partition topology, no holder/mount, swap UUID, partition-table identity, geometry, parent identity and protected SWAPSPACE2 page zero. Shared-root mode requires root-owned /etc/swapz/primary-target (PARTUUID=...), /etc/swapz/primary-root-parent-scope (0600, schema=swapz-primary-shared-root-v1, scope_sha256 bound to host/root/target/parent/layout); exact source-bound swapzctl primary plan checks these. No creation/replacement of records or disclosure of private identity fields.

Set VERIFIED_PARTUUID only from independently confirmed owner scope:
```sh
: "${VERIFIED_PARTUUID:?owner-verified target missing}"
selector="/dev/disk/by-partuuid/$VERIFIED_PARTUUID"
test -L "$selector" || exit 1
readlink -e "$selector"
```

The probe's plan action is read-only but expects active ordinary swap and rejects shared root by default; exit zero does not mean its printed source gate passed. Campaign-plan is a separate read-only qualified-source/exact PARTUUID/quiescence check, not development admission. Its --partuuid/--source-sha parameters are NOT a run-mode source-binding switch. The interactive algorithm-physical.py wrapper selects an owner-approved partition and requires explicit consent, but calls recover-pending before selection, so it is not a pure inspection command. No invocation in this round.

### B. One conditional ordinary existing-path development trial

Only after Agent1 and owner admit the exact current source/device, and only if an ordinary-path smoke is actually needed, the supported direct command is:

```sh
sudo -- python3 -I -B tests/tools/physical-swap-probe.py run \
  --device "$selector" --confirm-device "$selector" \
  --development-only --algorithm-real-swap
```

This is intentionally NOT the now-early-refused plain --development-only route. The helper itself runs one narrow fresh make fast_test SCENARIOS=fast-mixed REPEAT=1 RESUME=1 under the checkout owner with a fresh nonce and 1200s timeout. Do not run a duplicate fast_test first. Requires exact source/nonce/native PASS and loaded preflight PASS, or the narrowly classified exit-2 unclaimed-null_blk refusal (not a loaded PASS; never remove unclaimed device). Reuse only official same-source private algorithm-ram-evidence.json + nonce pair if already produced by the official runner, mode 0600, one link, correct uid, exact five successful stages, artifact hashes and source; do not manufacture nonce or report. No qualifying reusable evidence observed. No broad make test or fast_test this round.

The helper binds build/source-build-info.h (source SHA, clean flag), build/userspace/swapzctl, build/kernel/experimental/dm-swapz.ko, build/tests/device-roundtrip and exact oracle/workload/policy digests, rechecks clean/head/helper/artifacts immediately before claim; abort on sensitive main drift. The existing ordinary workload requires zswap disabled. Existing real-swap development route is NOT the future original typed stream path. Frozen primary bounds: 384MiB workload, 128MiB resident, 384MiB swap cap, 1GiB minimum available, 128MiB minimum attributed swap traffic, 128MiB verify headroom, 240s timeout, no OOM/kill or byte mismatch; primary acceptance requires two cycles, development is not primary acceptance. Preserve PSI/progress-aware and independent sampling checks. Require sufficient headroom max(1GiB, used+512MiB) for live pages before normal swapoff, 120s timeout and inactive proof, no foreign active partition, preserve unrelated swapfile state. No force removal, no raw formatting/repartition, no page-zero/UUID/table change; only owned mapper may be mkswap'd. Preserve first failure and owned same-boot private journal in /run/swapz/algorithm-physical; recovery-required is not PASS. Never reboot/force-remove to recover.

If a paired baseline is chosen instead, append --compare-raw to that one invocation only, with already-active ordinary selected swap strictly higher priority than unrelated swapfiles; same oracle, raw then swapz, scoped counters, restores original raw and does not offer keep-active. Nonpaired success may offer owner keep ordinary-path swapz vs restore ordinary swap, default restore, keep only if full-capacity supported. No activation of the original path/production install. Development paired smoke is not statistical campaign acceptance. No raw per-I/O p99 is inferred from aggregate counters. Shared-root partition stats are not whole-parent attribution.

### C. Future integrated original-transfer physical qualification: explicit NO_GO now

Current ordinary workload's zswap_disabled requirement cannot prove Linux zswap natural eviction. Do not disable it and claim original compressed transfer; no policy override in this round. Need Agent1-integrated exact MM pre-erase producer and retained original BIO carrier, selected live DM clone/route generation and atomic claim/enqueue, ordered original byte storage/GC, independently authenticated pinned original LZO1X/raw LZ4 and kernel/module source. Trace actual 4KiB source slot/generation/folio SHA, compressed length and original stream CRC/SHA, exact codec identity (3568 ordinary limits; 4095 isolated experimental), accepted bytes identical at handoff/lower and GC (no re-encode or second reclaim/BIO), complete 4096-byte verified decode, extent/padding/header and partition safety, real lower write FUA/flush durability before exactly one upper ACK; preclaim original 4096 RAW fallback, postclaim native error/redirty. Prove decoder/generation/read pins across relocation, scoped counters and actual lower attribution, no guessed success from fixture receipts. Need dedicated bounded natural-pressure protocol and exact same-card/source/kernel/work/geometry/content baseline with appropriate zswap policy, compare verified counters and source-linked results; no conflation with ordinary smoke or frozen production campaign. No physical execution until admitted; any missing identity, byte proof, durability, attribution, integrity or safe teardown blocks.

AUTH=0; Phase A BLOCKED; direct compressed handoff OFF; forced RAW bypass OFF; import OFF. No new VM execution, privileged action, physical mutation, branch, PR, force push, cancellation, duplicate dispatch or periodic monitoring by Agent9.
