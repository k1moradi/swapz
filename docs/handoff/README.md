# Handoff reference and evidence index

Old "Current" headings, PASS claims, approvals, SHAs and device paths are
history, not device authorization. Start with [AGENTS](../../AGENTS.md),
[current context](../AGENT_CONTEXT.md),
[frozen acceptance](../production-acceptance.json) and the
[latest owner test report](../../test_results.json), whose recorded source SHA
must be checked against the source being evaluated.
[Vision](../VISION.md), [coding standards](../coding_standards.md) and
[testing standards](../testing_standards.md) remain canonical.

## Debugging navigation

- **First dedicated-card host /dev/sda1:** [dedicated-card identity and standing scope](../AGENT_CONTEXT.md#current-production-mission); pathname alone is not identity.
- **Second Lubuntu host /dev/sda4:** [separate host scope](../AGENT_CONTEXT.md#separate-lubuntu-host-scope-for-devsda4)
  is conditional; recovery storage currently shares the target's parent and
  **blocks mutation**. The [retired host record](old-host-physical-and-live-swap-evidence.md)
  and [one-use trial](../live-swap-trial-recovery.md) are historical, not its
  scope record or evidence of admission.
- **Secure Boot:** [MOK enrollment and module signing](../compile.md#secure-boot-module-signing); a valid signature is not kernel-load evidence.
- **Development-only card smoke:** [strict admission](../testing_standards.md#development-only-card-backed-data-path-smoke) and [triage](../README.md#diagnose-the-first-record); `make fast_test` is not qualifying `make test` or real swap.
- **Primary mount namespaces (issue #94):** the early [non-leader task scan change](https://github.com/k1moradi/swapz/commit/7c7bc9743580d7592315be00bdc8eaf7b019a1d2) and [follow-up rootless coverage](https://github.com/k1moradi/swapz/commit/650b9249dd96b70dfbbab28047625b4acdd62181) are historical waypoints, not the current proof boundary. The [canonical contract](../testing_standards.md#primary-cross-namespace-mount-admission-evidence-issue-94) now records pinned-namespace coverage plus explicit `UNPROVEN` post-selector and post-final-snapshot mutation controls. Neither rootless result establishes owner `make test`, loaded kernel-side exclusion or physical admission.
- **Real Linux swap:** [native-host qualification](../testing_standards.md#primary-real-swap-native-host-qualification) covers bounded production-primary anonymous reclaim, swap-out/in attribution, byte-exact readback and normal teardown on the exact target. It is not the full physical performance/capacity campaign.
- **Full physical qualification:** [physical benchmark scope](../benchmark.md#physical-media-and-workload-validity) plus the frozen policy above covers the selected protocol's physical service, sustained maximum-capacity/high-occupancy GC/churn, cold-read and anonymous-swap cohorts. It is separate from boot acceptance and does not directly prove NAND lifetime.
- **Release blockers:** [readiness gates](../AGENT_CONTEXT.md#production-readiness-definition) and [evidence integrity](../testing_standards.md#qualification-discovery-and-release-evidence-integrity); [readiness snapshot](production-readiness.json) is **HISTORICAL**.
- **Exact-source CI:** [same-commit standards](../compile.md#direct-main-ci-standards-co-changes); mandatory [project-goals](../../.github/workflows/project-goals.yml), [product-codec](../../.github/workflows/product-codec.yml) and [systemd/package](../../.github/workflows/systemd-package-readiness.yml). CI is not loaded-host PASS.
- **Owner ARM64/NEON VM:** [development/performance history](../ROADMAP.md) belongs to a third environment, not either physical card; its results do not qualify a physical target.
- **Code de-bloat:** [source-pinned register](verified-debloat-register.md) separates verified repetition from unproved equivalence, names owning agents and specifies deferred regressions.

**Private evidence on each Codex machine:** checkout-local
`build/tests/fast-test/development-evidence.json`,
`build/tests/rootless-failure.*/diagnostic.log` (bounded diagnostics for
pre-captured stderr; direct failures begin attribution-only but may be enriched
by the official reporter; see [first-error triage](../README.md#diagnose-the-first-record)) and
`build/history/<architecture>-<host-digest>/` do not sync through Git.
Root-owned `/var/lib/swapz/physical-recovery/` retains
`swapz-physical-<run_id>/{state.json,results.json}`,
`primary-state.json`, `primary-real-swap-<attempt_id>.json` and
`primary-qualification.json`; boot evidence lives at
`/var/lib/swapz/boot-acceptance/`. These are durable, **not** disposable
temp records. For `PHYSICAL_RESULTS=`, `results.json` may contain
`physical_oracle_phases[]`; setup/recovery failures may instead rely on
`state.json` and `final_recovery_state` without numeric `errno`.
The root `test_results.json` is sanitized public evidence, not this private record.

[Runtime health](systemd-runtime-health.md) is supplementary;
[host-history](host-history.json) feeds descriptive local plots only.

## Historical qualification and physical observations

The 2026-11-06 first-host checkpoint is [development and owned-RAM smoke at
`535560c3`](2026-11-06-first-host-535560c3-development-and-loaded-smoke.md).
It records one source-bound SD-card mapper-page oracle and a separate
standalone owned-RAM loaded smoke. Both are development evidence; neither is
the official five-stage qualification or real anonymous Linux swap.

These 2026-11-05 first-host results are distinct **historical, source-bound**
observations. "Current-source" in a report title means current *when recorded*;
it does not describe today's `main`. The underlying evidence and artifact
hashes stay in their original reports.

- [Mapper smoke at `7c7bc974`](2026-11-05-first-host-current-source-development-smoke.md):
  128-page oracle, restored header and later reporter follow-up.
- [Mapper smoke at `046681b1`](2026-11-05-first-host-046681b1-development-smoke.md):
  128-page oracle and primary-plan BLOCKED observation.
- [Mapper smoke at `fe7ae0e4`](2026-11-05-first-host-fe7ae0e4-development-smoke.md):
  128-page oracle and namespace-fixture CI failure.
- [Mapper smoke at `81ddcfbf`](2026-11-05-first-host-development-smoke.md):
  128-page oracle and mount-namespace CI refusal.

All four are development-only mapper tests with inactive Linux swap and
restored original headers, **not** `make test`, real anonymous swap,
full-card physical qualification or boot acceptance. For subsequent status,
read the timestamp and source SHA in [production status](../production-status.json).
- [Source qualification](historical-source-qualification-snapshots.md) and
  [benchmark narratives](historical-benchmark-qualification-narratives.md):
  prior PASS/FAIL/BLOCKED and tradeoffs.
- [Benchmark experiment memory](historical-benchmark-experiment-memory.md)
- [Old-host physical/live swap](old-host-physical-and-live-swap-evidence.md)
- [Alpha.29 observability](alpha29-loaded-qualification-observability.md)
- [ID73 CPU/cache](id73-cpu-cache-qualification-batch.md)

## Historical debugging and ownership audits

- [Agent 10 source-admission and child-ownership audit](agent10-codex-handoff.md):
  historical same-UID socket-substitution and interrupted-child investigation.
  Its original `BLOCKED` disposition is not a current-main verdict: the
  current helper validates parent PID/start identity, peer credentials and
  pidfd liveness. Neither the old synthetic probe nor this fix qualifies real
  swap; interruption cleanup requires separate source-bound review.
- [Agent 7 real-swap oracle auxiliary controls](agent7-real-swap-oracle-rootless-evidence.txt):
  the historical audit at `b7f5109d` recorded 43/43 auxiliary rootless checks.
  The producer harness self-enforced source binding; the other three
  excerpt-transcription harnesses were externally source-matched, not self-bound.
  The complete terminal qualifier was **NOT RUN**. No mapper, module or real
  Linux swap was exercised. This is not an owner `make test`, loaded-host,
  physical or current-source PASS.
- [Agent 17 DISCARD debugging archive](agent17-discard-debugging/README.md):
  original standalone pre/post-fix models and full-map scan investigation;
  their hashes and historical observations are preserved, not a production-C
  or loaded-device qualification.

## Superseded or rejected work

- [Rejected optimization pilots](historical-rejected-optimization-pilots.md)
- [Old bottleneck ranking](historical-bottleneck-ranking-9123b811-7ff94fd4.md)
- [November 2 retired ID181 queue](2026-11-02-optimization-work-queue.md)
- [Completed lane-gap brief](lane-gap-diagnostics.md) (parser TODO obsolete)
- [Unissued physical-review draft](physical-swap-external-review-prompt.md)

## Deferred research, not current assignments

- [November 1 backlog](2026-11-01-content-concurrency-backlog.md):
  superseded host restrictions and deferred observations.
- [Deferred experiment ideas](historical-benchmark-experiment-memory.md#deferred-idea-evidence):
  reopen with current [ROADMAP decisions](../ROADMAP.md) and fresh evidence.
