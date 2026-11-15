# Round 001 — Agent 7 passive-collector-validation report (archived GitHub submission)

- **Original GitHub report:** https://github.com/k1moradi/swapz/issues/118#issuecomment-6892218817
- **Task commit:** `b6817ac41f96a0e7df4b0f5f3af258e582723b9e`
- **Frozen source baseline:** `c128ac32374a753a0b27ae0ebec67693355b1b55`
- **Agent-stated task outcome:** PASS (passive/rootless only)
- **Original issue-comment body SHA-256:** `dd5146ee3cdc8587f481fcef41dd588ecd59ea497d8c6fa045ecb409f2edc5a9` (UTF-8, excluding archival wrapper)
- **Archival date:** 2026-11-15 UTC
- **Evidence boundary:** Reporter results below are attributed to the agent, not independently rerun or Phase A kernel qualification.

---

message: REPORT_READY
round: "001"
agent: 7
task_id: agent7-passive-collector-validation
status: PASS
source_sha: c128ac32374a753a0b27ae0ebec67693355b1b55
frozen_task_commit_sha: b6817ac41f96a0e7df4b0f5f3af258e582723b9e
round_issue: https://github.com/k1moradi/swapz/issues/118
modified_files: []
evidence_class: rootless
blocking_findings:
  - No matched kernel/module, active source-qualified swapz mapper, authenticated origin counter or genuine stored zswap writeback was available.
  - Optional kernel debug values were absent/unreadable; unavailable is not zero.
next_round_recommendations:
  - Approve and implement a versioned read-only commit-side per-mapper origin counter on the selected exact kernel/source, then validate it across producer/BIO/DM.
  - Correlate source-stamped status snapshots with real stored-entry writeback only on a separately authorized test target; never infer mapper origin from global zswap statistics.
tests:
  - command: python3 -B -m unittest -v test_passive_offline
    exit_code: 0
  - command: python3 -B test_negative_controls.py
    exit_code: 0
  - command: python3 -B passive_baseline.py --output rootless-before.json
    exit_code: 0
  - command: python3 -B passive_baseline.py --output rootless-after.json
    exit_code: 0
  - command: python3 -B analyze_intervals.py interval rootless-before.json rootless-after.json --output rootless-interval.json
    exit_code: 0
  - command: patch --dry-run -p1 < agent7-review-only.patch
    exit_code: 0

# Agent 7 — Round 001 passive collector and interval analyzer validation

**Verdict: PASS for the independent rootless/offline Round 001 task only; Phase A remains BLOCKED and Phase B DEFERRED.** No positive authenticated-origin, loaded kernel, real mapper, performance or physical-media result is claimed.

## Source and assignment identity

- Frozen [Agent 7 task](https://github.com/k1moradi/swapz/blob/b6817ac41f96a0e7df4b0f5f3af258e582723b9e/docs/handoff/zswapz/round001/agent7-passive-collector-validation.md); [authoritative ROUND_OPEN](https://github.com/k1moradi/swapz/issues/118#issuecomment-6891942116). Source baseline c128ac32374a753a0b27ae0ebec67693355b1b55 is distinct from the task commit b6817ac41f96a0e7df4b0f5f3af258e582723b9e.
- Baseline [src/userspace/swapzctl.c](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/userspace/swapzctl.c), inspected blob 4dcc66cf15b54f659bdfd2c0ad23e45415169bc3: the observational status --json format is schema_version 1, with DM target identity/event, health and lifetime logical-write, lower/GC and compressed/RAW/zero counters. This API does **not** establish active ownership or zswap provenance.
- Frozen [docs/benchmark.md](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/docs/benchmark.md) blob 31ccdee41f78f9ebc1b619fef993f88783ae4773 and [ROADMAP.md](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/docs/ROADMAP.md) blob b49cec896f6458cfad74936249d410b6ef0869d5 distinguish passive diagnostics from source-linked acceptance.
- Final commands ran as an unprivileged Unix account (UID 1000), Python 3.13.5, running kernel 6.18.57. No selected swapz mapper, installed source-matched module, privileged kernel instrumentation, or host writeback workload was involved.

## Source-only scratch deliverables and fixes

Two previously supplied, **optional, unpublished Agent 7 local scripts** were copied into independent scratch. They are **not present in frozen swapz main**, nor a mandatory same-round agent dependency. The resulting read-only collector, offline parser, 43-case regression suite, 4-case deliberate mutation harness, review-only unified patch and sanitized logs were delivered separately to the owner as a source-only package. All canonical repository paths remain untouched; Agent 1 is the sole archive/publication writer.

The small patch corrects four specific problems in those original local scripts:
1. Collector monotonic end timestamp now occurs **after** boot ID, kernel metadata, and all other read-only snapshot inputs rather than before the final reads; empty /proc/stat is explicitly unavailable, not an exception.
2. Analyzer evidence output is created by O_CREAT|O_EXCL, optionally O_NOFOLLOW, and mode 0600 **at creation**, even with permissive umask. Existing files/symlinks cannot be overwritten.
3. Mapper identity (including target index, major/minor, UUID, DM event, sector extent) and required physical/GC counters are validated; negative unsigned counters, invalid types, missing identity and reset/rollover reject instead of yielding false attribution.
4. A zero-logical-commit interval has a **null overall foreground ratio**, even if unrelated foreground lower-write bytes rise; no false 0% ratio is emitted.

The only optional subprocess command in the collector is the fixed read-only swapzctl status --json. Other access is direct reads of selected /proc, /sys and validated existing cgroup metrics. The only writes are new private local JSON evidence files. No /dev read, sysfs write, daemon, stress load, swapon/swapoff, dmsetup, mkswap or modprobe call is used.

## Exact rootless results

| Check | Exit | Evidence |
|---|---:|---|
| python3 -B -m unittest -v test_passive_offline | **0** | **43/43 PASS**: identity/same boot, generation drift, resets, malformed/sparse values, config drift, zero activity, commit and lower-byte accounting, PSI microsecond totals, 512-byte sectors, 0600/create-only/symlink safeguards, and mocked stock status JSON |
| python3 -B test_negative_controls.py | **0** | **4/4 deliberate source mutations detected** (each isolated mutated test had exit 1): false origin sourced from global zswpwb; fabricated zero-commit ratio; removed O_EXCL overwrite protection; unsafe replacement for the fixed status command |
| python3 -B passive_baseline.py --output rootless-before.json | **0** | One-shot private JSON, mode 0600 |
| python3 -B passive_baseline.py --output rootless-after.json | **0** | Another one-shot private JSON, mode 0600 |
| python3 -B analyze_intervals.py interval rootless-before.json rootless-after.json --output rootless-interval.json | **0** | Schema swapz-agent7-interval-v1, private mode 0600, mapper attribution NOT PROVEN |
| patch --dry-run -p1 < agent7-review-only.patch (against exact two original shared scripts) | **0** | Both patch inputs recognized; no GitHub source patch or commit |

Each read-only observation reported **21 inaccessible/missing optional read sources**; the interval reported **17 missing metric values**. Their absence is retained as null/missing, not silently interpreted as 0. The collector's incomplete-snapshot warning is nonfatal because these metrics are optional. No mapper was selected, so the actual swapzctl subprocess was **not** invoked; stock-schema, bad-schema, duplicate-target and unavailable-status handling were tested with mocks. Private host observations, boot ID and device details are deliberately **not posted** here.

## Schema and metric contract validated

The diagnostic-only snapshot schema is swapz-agent7-passive-v1; the derived interval schema is swapz-agent7-interval-v1 (neither is a production/API change). Each observation records private boot/kernel identity, monotonic start/end encompassing reads, host-global zswap counters/config, optional exact mapper identity/health, optional block major:minor statistics, host PSI totals and missing-field reasons. Snapshot reads are sequential and **not atomic**.

Interval acceptance requires unchanged boot/kernel, nonoverlapping monotonic boundaries, unchanged zswap config, stable mapper identity and no invalid required counters. The exact foreground committed-page condition is:

    delta(logical_write_bytes) = 4096 * [delta(compressed_pages) + delta(raw_pages) + delta(zero_elided_pages)]

Bytes of lower transactions/GC and speculative codec attempts cannot be added as logical commits. Block stat sector deltas are multiplied by **512 bytes/sector**; PSI total deltas are microseconds divided by elapsed monotonic microseconds. Partition and parent block data remain separate scopes and are never summed.

Global /proc/vmstat zswpwb and debugfs written_back_pages **cannot prove per-mapper provenance**. Until an authenticated field is implemented, proven_zswap_writeback_pages, ordinary_backing_pages and zswap_initial_rejection_pages remain **null**. On a healthy mapper with coherent existing commit data, only the total unclassified committed-page count is known. Without a mapper, origin attribution is NOT PROVEN. The proposed foreground_committed_verified_zswap_writeback counter remains **UNAVAILABLE**, not empirically zero.

## Scratch artifact SHA-256 for reproducibility

- passive_baseline.py — 0a8df9225cd4cb43a263d0167fbc3d68424ef64bd68dd43a2c5d7c6113d8092e
- analyze_intervals.py — ef7ca3088139fa4aca6052cc6622110ffd63c96911539005a6ce136139306f7c
- test_passive_offline.py — 00aa5c455db17fb613e9162b13223b6e107611c486f4b88b211e1ff8464dddf6
- test_negative_controls.py — fd8df49771562f2aaebc0a884b30e455bf100f9470cb193acdc58de5c24bb70c
- agent7-review-only.patch — 34ac1b98da4e01472dc2cdf6ffa4704140a8132e82a1b9151e97f948f1f5dd8f

The patch's **pre-round local source** input hashes are 28f52a2b58aca1f83233c5559a5f53da229b05cfa85bc887db9ccaf41fef652e (collector) and 21ce35d8f3fdb58b99c02dbaae887289f67eaddd859bfe0c15530acaab8042dd (analyzer). Do not attempt to apply this local-tool patch to current repository production C. All tests and scripts are provided in a separately delivered owner package; this comment is the durable, source-pinned report for Agent 1 to archive.

## Blocking boundary and next round

A rootless parser PASS does not establish an authenticated producer-to-BIO-to-DM origin, current-source module, loaded null_blk, actual positive zswap writeback, physical device correctness or performance. No active tests were authorized or run. Later, after the selected exact kernel and Agent 4 counter contract are approved/implemented, add a *versioned*, source-stamped status-reader fixture with one count per authoritative 4KiB foreground commit, check 0 <= verified_commits <= total_commits, reject drift/missing fields, and correlate it with a real stored-entry writeback trace only on a separately authorized target. Do not implement Phase B RAW bypass or a four-way RAW reason vector as part of this Round 001 task.

**Final:** Agent 7 Round 001 **PASS (rootless/passive only)**; Phase A **BLOCKED**, Phase B **DEFERRED**, loaded/physical **NOT_RUN**. No repository edits, branches, PRs, commits or device operations.
