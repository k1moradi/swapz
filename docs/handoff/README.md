# Handoff reference and evidence index

Old "Current" headings, PASS claims, approvals, SHAs and device paths are
history, not device authorization. Start with [AGENTS](../../AGENTS.md),
[current context](../AGENT_CONTEXT.md),
[frozen acceptance](../production-acceptance.json) and the
[exact-source report](../../test_results.json).
[Vision](../VISION.md), [coding standards](../coding_standards.md) and
[testing standards](../testing_standards.md) remain canonical.

## Debugging navigation

- **First Codex /dev/sda1:** [dedicated-card identity and standing scope](../AGENT_CONTEXT.md#current-production-mission); pathname alone is not identity.
- **Second Codex /dev/sda4:** [retired host record](old-host-physical-and-live-swap-evidence.md) and [live-swap trial](../live-swap-trial-recovery.md) are **historical**, never current card permission.
- **Secure Boot:** [MOK enrollment and module signing](../compile.md#secure-boot-module-signing); a valid signature is not kernel-load evidence.
- **Development-only card smoke:** [strict admission](../testing_standards.md#development-only-card-backed-data-path-smoke) and [triage](../README.md#diagnose-the-first-record); `make fast_test` is not qualifying `make test` or real swap.
- **Real swap/physical:** [native-host qualification](../testing_standards.md#primary-real-swap-native-host-qualification) and [physical benchmark scope](../benchmark.md#physical-media-and-workload-validity); frozen policy above.
- **Release blockers:** [readiness gates](../AGENT_CONTEXT.md#production-readiness-definition) and [evidence integrity](../testing_standards.md#qualification-discovery-and-release-evidence-integrity); [readiness snapshot](production-readiness.json) is **HISTORICAL**.
- **Exact-source CI:** [same-commit standards](../compile.md#direct-main-ci-standards-co-changes); mandatory [project-goals](../../.github/workflows/project-goals.yml), [product-codec](../../.github/workflows/product-codec.yml) and [systemd/package](../../.github/workflows/systemd-package-readiness.yml). CI is not loaded-host PASS.

**Private evidence on each Codex machine:** checkout-local
`build/tests/fast-test/development-evidence.json`,
`build/tests/rootless-failure.*/diagnostic.log` and
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

- [Source qualification](historical-source-qualification-snapshots.md) and
  [benchmark narratives](historical-benchmark-qualification-narratives.md):
  prior PASS/FAIL/BLOCKED and tradeoffs.
- [Benchmark experiment memory](historical-benchmark-experiment-memory.md)
- [Old-host physical/live swap](old-host-physical-and-live-swap-evidence.md)
- [Alpha.29 observability](alpha29-loaded-qualification-observability.md)
- [ID73 CPU/cache](id73-cpu-cache-qualification-batch.md)

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
