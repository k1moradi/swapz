# Round021 — verbatim original GitHub agent REPORT_READY comments

These complete comments were retrieved from official Round021 issue #138. Preserve the distinction between worker isolated/transplanted source smoke and actual full-source exact CI or owner physical/loaded proof. References to unavailable private logs are not their contents.

## Agent4 first publication — [original comment](https://github.com/k1moradi/swapz/issues/138#issuecomment-6924552737)

message: REPORT_READY
round: "021"
agent: 4
status: SOURCE_PUBLISHED_MAIN; EXACT_REPORT_FIRST_CAUSE_PATCH; PHASE_A_BLOCKED
published_main_sha: 8a4485d3a1b638d7dd16a5fb44d525a56cc371d6
parent_sha: eec0d9e881028ac6b0413b97c3df4d039b1cd1f0
publication: NON_FORCE_EXPECTED_HEAD_FAST_FORWARD_VERIFIED
remote_main_verified_at_publication: true
physical_retrial: NOT_RUN
loaded_genuine_stored_entry: NOT_RUN
loaded_original_4096_readback: NOT_RUN
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED

### Source change and actual first finding
- `tests/tools/run-tests.py`: the real physical probe already emitted ten bounded `attribution_observation` values, but the official `parse_algorithm_pageout_diagnostic` field allowlist omitted `attribution` and rejected the whole otherwise source-defined diagnostic. Admit it ONLY for original `swap_attribution` with exact field/type/bounds/round/baseline/initial-mismatch/current signed-gap arithmetic. A zero final gap is admissible as *failure evidence* if only one identical matching snapshot was obtained; no positive gate changed. Print only validated non-atomic numeric fields with explicit no-PASS text.
- `tests/runtime/native/test-report-test.py`: Round021 dedicated rooted-source parser/console regression for negative and zero/positive signed gaps, contradictory/duplicated/malformed/private fields and preserved original nonzero child exit.
- `docs/testing_standards.md`: standalone append-only Round021 Agent4 section; old standards and Round020 sections preserved.
- `docs/handoff/zswapz/round021/agent4-evidence.md`: source first-cause, limitations and safety.
- `tests/tools/qualify-primary-real-swap.py` and `tests/tools/physical-swap-probe.py` UNCHANGED, including exact immutable-baseline byte equality, guarded <=3-second recheck, two identical consecutive exact matching pairs, independent worker/pressure/deadline checks and recovery.

### Measured checks and first failure
- Local checkout `git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main`: EXIT 128, `Could not resolve host github.com`. No local main fetch/fast-forward could be claimed. Used connected GitHub Git objects, a normal single-parent commit, `update_ref(main, expected_sha=eec0d9e..., force=false)`, and a fresh REST remote-ref verification with exact resulting SHA.
- `python3 -B -m unittest /mnt/data/round021_agent4_smoke.py -v`: EXIT 0, 3/3 PASS, 0.001s, running the identical 46-line bounded attribution-admission validation transplanted into an isolated smoke harness, with signed {-4,0,+4} KiB, negative forged/overwide/private records and non-PASS first-error assertion. `python3 -m py_compile /mnt/data/round021_agent4_smoke.py`: EXIT 0. This is a targeted isolated executable check, NOT a claim that the full committed 700KB script/suite ran locally.
- GitHub exact-SHA workflow `Rootless physical evidence adversarial audit` #43922954274: completed SUCCESS, source commit above. `Private kernel debug and static contracts` #43922954273 and `Experimental swapz production C qualification` #43922954454: completed SUCCESS. Other newly triggered workflows were still IN_PROGRESS when checked; do not invent full-suite PASS.
- Unavailable locally: original full `test-report-test.py -k Round021`, all physical / native suites, complete local `git diff --check`, owner host trial, real RAM pressure, full source KUnit rerun or actual loaded DM. Source-level checks during Git object construction verified exact anchors, append-only standards and no production changes.

The historic owner trial's **first physical failure** was `anonymous_workload / swap_attribution` at pinned older source `de5bc09e80484c60d003e860732ecb736a6c2f0b`, with 5/5 RAM stages PASS, full physical time 2721.73s and reported complete recovery. Owner's private original numerical observations remain UNKNOWN; no foreign swap/codec/host cause is inferred. Prior `swap_slot_release` timeout is a distinct historical gate. No physical rerun was authorized/performed. Historical modified Linux KUnit y/n 5/5 and matched module Kbuild PASS are source/build only, NOT loaded original 4096 swap-in. Current RAW is uncompressed ORIGINAL 4096-byte page. Phase A BLOCKED, Phase B bypass and compressed handoff DISABLED.

MAIN_WRITE_LEASE_RELEASED

---

## Agent4 source hardening follow-up — [original comment](https://github.com/k1moradi/swapz/issues/138#issuecomment-6924565381)

message: REPORT_READY
round: "021"
agent: 4
status: PUBLISHED_MAIN_SOURCE_READY_EXACT_HOSTED_ROOTLESS_PENDING
published_main_sha: 72e50d6ea77c5f97a6cb2956061af26a59df929d
source_commit_url: https://github.com/k1moradi/swapz/commit/72e50d6ea77c5f97a6cb2956061af26a59df929d
sole_parent_sha: 8a4485d3a1b638d7dd16a5fb44d525a56cc371d6
task_publication_sha: eec0d9e881028ac6b0413b97c3df4d039b1cd1f0
branch: main
publication: NON_FORCE_EXPECTED_SHA_FAST_FORWARD_VERIFIED
physical: NOT_RUN
loaded_genuine_zswap_bio_dm: NOT_RUN
original_4096_swapin: NOT_RUN
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED

Original owner physical first failure (not a new trial): older source de5bc09e80484c60d003e860732ecb736a6c2f0b had five RAM algorithm stages PASS and physical anonymous_workload/bounded_primary_workload FAIL reason=swap_attribution, original_errno unavailable. Original initial/current private cgroup and mapper counters NOT SHARED, underlying mismatch origin UNKNOWN. Reported recovery COMPLETE, not independently revalidated. This is separate from older swap_slot_release.

Reconciled already-published Round021 Agent4 main commit 8a4485d3 (which had repaired the official run-tests parser dropping the probe's ten-field attribution evidence) rather than replacing/reverting it. This follow-up commit changes only the eight Agent4-owned paths:
- tests/tools/qualify-primary-real-swap.py: strict bool/negative/uint64/byte-conversion validation, preserve original exact identity and 3s deadline, refuse after-deadline matching reads, finite signed source-derived observational class on first timeout (no acceptance change).
- tests/tools/physical-swap-probe.py: independently require original initial mismatch, finite type/ranges and baseline delta/gap arithmetic, whitelist and redact safe classification; first cause survives later cleanup.
- tests/tools/run-tests.py: preserve published ten-field parser while independently validating optional 11th source classification, reject bad sample/range/overflow/private fields, display bounded class without changing first failure or exit.
- tests/runtime/native/primary-real-swap-test.py: source-imported rootless mock regressions for initial exact, two identical matching pairs, changing exact pair refusal, signed mismatch, deadline, no sample, OOM/PSI guard and invalid/vanished mapper counters.
- tests/runtime/native/physical-swap-probe-test.py: first error over cleanup, class coherence, numeric/private mutation refusal and missing recheck.
- tests/runtime/native/test-report-test.py: backwards-compatible parser/class mutations and whole official synthetic physical failure retaining original nonzero exit=3; preserves the previous Round021 tests.
- docs/testing_standards.md: uniquely headed append-only Agent4 follow-up, preserving all existing Round021 sections.
- docs/handoff/zswapz/round021/agent4-evidence.md: append-only source/rootless evidence and non-mutating owner checklist.

Actual local safe checks (isolated source-excerpt fixtures, NOT complete checked-out imported suites):
python3 -m py_compile /mnt/data/round021_agent4_source_excerpt.py -> EXIT 0
python3 -B /mnt/data/round021_agent4_source_excerpt.py -> EXIT 0, 4/4
python3 -m py_compile /mnt/data/round021_agent4_report_excerpt.py -> EXIT 0
python3 -B /mnt/data/round021_agent4_report_excerpt.py -> EXIT 0, 3/3
git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main -> EXIT 128, DNS Could not resolve host; no local complete checkout.
GitHub compare direct parent..published SHA: ahead=1, 8 owned paths, 500 added diff lines checked with 0 trailing-whitespace findings; no local git diff --check was possible.

Complete repository-imported targeted tests (NOT_RUN locally; exact source CI pending):
python3 -B tests/runtime/native/primary-real-swap-test.py -k round021 -v
python3 -B tests/runtime/native/physical-swap-probe-test.py -k round021 -v
python3 -B tests/runtime/native/test-report-test.py -k round021 -v
python3 -m py_compile tests/tools/qualify-primary-real-swap.py tests/tools/physical-swap-probe.py tests/tools/run-tests.py tests/runtime/native/primary-real-swap-test.py tests/runtime/native/physical-swap-probe-test.py tests/runtime/native/test-report-test.py
git diff --check HEAD^ HEAD

At report time exact SHA CI is in_progress/queued, no hosted test PASS claimed:
https://github.com/k1moradi/swapz/actions/runs/43923553914
https://github.com/k1moradi/swapz/actions/runs/43923553411
Agent1 owns exact-SHA CI/integration acceptance. Do not mistake source-excerpt PASS for a physical loaded PASS.

No physical device, swapon, swapoff, mkswap, cgroup pressure, mapper, module or host state mutation. No branch/PR/fork/worktree/force push. Next owner action is non-mutating review of original retained private first-error numerical pairs, worker exits, cgroup/mapper/PSI/OOM and complete recovery. No physical rerun requested. Existing RAW is original UNCOMPRESSED 4096-byte page.

---

## Agent3 read-only loaded observation — [original comment](https://github.com/k1moradi/swapz/issues/138#issuecomment-6924592209)

message: REPORT_READY
round: "021"
agent: 3
task_id: agent3-boot-module-owned-ram-proof
status: SOURCE_PUBLISHED_MAIN; READ_ONLY_HOST_NEGATIVE_GATES; ENVIRONMENT_NOT_QUALIFIED
published_main_sha: bac045b781c78537afd6b508b44555335e529bbd
parent_sha: 72e50d6ea77c5f97a6cb2956061af26a59df929d
publication: NON_FORCE_EXPECTED_HEAD_FAST_FORWARD_VERIFIED
remote_main_verified: true
task_publication_sha: eec0d9e881028ac6b0413b97c3df4d039b1cd1f0
loaded_stored_entry: NOT_RUN
4096_readback: NOT_RUN
physical_trial: NOT_RUN
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED

### Exact source change (three paths)
1. `tests/runtime/native/zswap-origin-loaded-evidence-contract.py`: new fixed actual-host read-only /proc boot ID, /sys/module/dm_swapz initstate=live and GNU ELF build-ID note checks, nofollow/nonblocking bounded regular-file reads with post-read inode/size/mtime checks, strictly parsed kernel source metadata, new explicit `--inspect-host` refusal. Added `HostReadOnlyTests` to the pre-existing `--self-test` suite, including nofollow symlink/FIFO, invalid/short module build IDs, invalid boot, not-live module, nonexistent/symlink module directory and positive-looking fixtures that still MUST report exit 2/NOT_RUN. No source/host evidence can grant a mutating backend or Phase A PASS. Existing 33 candidate source fixtures and exactly-one upper-write ACK/4096 offline comparison unchanged.
2. `docs/testing_standards.md`: unique append-only Round021 Agent3 section, preserving both earlier rounds and Agent4's TWO independently published Round021 appendices.
3. `docs/handoff/zswapz/round021/agent3-evidence.md`: limits of actual observed sysfs metadata vs unavailable exact boot image/loaded .ko bytes/ownership/full-page swap-in.

A sysfs module ELF build-ID note is only an independently observed **negative cross-check**, NOT the actual linked .ko digest or a cryptographic measurement of the executing module's bytes. The script always refuses actual loaded qualification without independently authenticated source/image, module payload, owner-controlled exclusive ephemeral RAM, teardown and authentic page/event evidence. Even a fully matching synthetic boot/module fixture returns `ENVIRONMENT_NOT_QUALIFIED` exit 2 and `LOADED_STORED_ENTRY=NOT_RUN`, `4096_READBACK=NOT_RUN`. No kernel/device mutation or owner permission is performed or inferred.

### Actual measured tests / first failure
- `python3 -B /mnt/data/round021_agent3_smoke.py -v`: EXIT 0; **4/4 PASS** (0.012s), an isolated Python transplant of the exact modified bounded proc/sysfs/module-note helper logic. Negative symlink, FIFO, overlong, NUL, invalid notes/stale boot/module, and synthetic positive host metadata cases included. `python3 -m py_compile /mnt/data/round021_agent3_smoke.py`: EXIT 0. This is not a claim that the full committed original source suite executed locally.
- After concurrent Agent4 publication, reran `python3 -B /mnt/data/round021_agent3_smoke.py -q`: EXIT 0, **4/4 PASS** (0.007s), and `python3 -B /mnt/data/round021_agent4_smoke.py -q`: EXIT 0, **3/3 PASS**. Original Agent3 source bytes unchanged by rebase.
- Local `git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main`: EXIT 128, `Could not resolve host: github.com`. No local checkout or `git fetch`/full `git diff --check` is claimed. Used official connected GitHub Git data with an exact SHA/ownership check, single parent and non-force `update_ref(main,expected_sha=72e50d6...,force=false)`, then confirmed remote main SHA exactly equals published commit.
- Concurrent Agent4 additional commit `72e50d6ea77c5f97a6cb2956061af26a59df929d` arrived before Agent3 publication. Original stale-parent Agent3 **unpublished** candidate was NOT pushed; only owned changes were recreated on top of new main. All Agent4 physical changes and its appended standards retained, actual host fixture smoke rerun, resulting HEAD verified. No branch, PR, worktree or force operation.
- At first CI poll, exact-SHA run #43923726018 Rootless physical evidence adversarial audit completed SUCCESS; exact-SHA Phase A linked source workflow #43923726108, native project regressions #43923726174 and other workflows were IN_PROGRESS/QUEUED; NO new-KUnit/run-level/loaded-success claim.
- Full committed `--self-test` new candidate + host suite, matched external module build, GCC/Clang production Kbuild, full exact checkout syntax/YAML/Bash and original full offline 4096 suite were **NOT_RUN locally** because no checkout. The independent historic pinned Linux KUnit real 5/5 y/n and linked matched module builds PASS only on an older source commit, not a booted loaded trace.
- First diagnostic remains **missing independently authenticated boot image, truly loaded source-linked dm-swapz.ko bytes and owner-permitted exclusive ephemeral RAM session**. There is NO original loaded 4096 readback first failure because the live loaded trial is NOT_RUN. Current source fixtures reject malformed notes and stale module state as intended.

The distinct earlier owner physical `swap_attribution` failure (older source de5bc09e, private numeric counters unavailable) was NOT rerun or attributed to kernel/codec/host cause. Phase A BLOCKED; Phase B RAW bypass and direct compressed handoff DISABLED. Current RAW remains the ORIGINAL UNCOMPRESSED full 4096-byte page.

MAIN_WRITE_LEASE_RELEASED
