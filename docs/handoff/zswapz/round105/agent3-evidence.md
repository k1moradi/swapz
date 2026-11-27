# R105 Agent 3 — source published; focused qualification pending

AUTH=0; Phase A BLOCKED; compressed handoff, forced RAW, import OFF. A1 owns acceptance.

## Provenance

- Frozen source: `ae7dc02e5db07fc6d133e02ffd558cb68c8e3159`; task: `5148f7f941fa9144d01c51b047fec16a7b9e557f`; Linux: `c339f4010dea8b0d754f84ace70cd1b089878ef8`.
- [Actual source commit 19ef78fff9f862fa6774b7580538cffbcf009b7b](https://github.com/k1moradi/swapz/commit/19ef78fff9f862fa6774b7580538cffbcf009b7b), direct main parent `db57f87498a0b20d298136f3f947c42051c899af`, tree `1cae82ed6d60df4e99da9f3c7e93f63a9d040c46`. Fresh HEAD expected-SHA non-force update and immediate remote readback passed. Owned source pins verified again at evidence parent `3678e8573b84826d13c439f87c8a2fe85e49e7a6`. No same-round peer implementations were consumed.
- Standards append: parent blob `e8c8776b482eb31aa7a4ea32dddd7b903ec84f65` round-tripped exactly; appended blob `73c521408da078cea3a87f5983c77baff49015be` read back exactly. All prior bytes retained. R104 historical workflow changed to manual trigger only; historical test logic untouched.

## Actual implementation

- Private built-in begin/retire rendezvous with synchronous registration/withdrawal, transient module references (no permanent self-pin), local target preflight before recorder/MM publication and exact target install validation. Only registration/withdrawal and negative control cross the module boundary. Positive entry has no userspace control or trusted external admission caller. Caller still must independently hold the live table/target and serialize its lifecycle.
- Separate final retirement from normal suspend. Final path requires quiescence and genuine exact external MM/core join and revoke before retiring no-longer-authoritative typed records. Pinned records block retirement; retain identity and retryable debt, preserve first terminal error. Final path blocks resume. Release target cap and broker owner before controller finish. Explicit private recovery of known failed target installation after successful MM publication requires exact MM and old-owner retirement; ambiguous publish/bind failure remains retained. Detached quarantine remains unresolved.
- Added bounded actual DM witnesses for existing standalone RAW/FUA writes, including exact refusal/cancel before fallback, lower submit/complete, actual flush and publication. Single-page discard records actual new generation; postclaim failure emits quarantine only when lower/flush failure and exact allocator abandonment are established. No extra physical write, flush, forced RAW or fallback is introduced. Packed/zero-elided/unsupported ordinary paths, GC and other uncovered shapes remain loss. No synthetic CLEANUP count or complete wire trace claimed.

## Qualification

Local checkout attempt failed with DNS resolution of github.com (git ls-remote exit 128). The exact source push automatically queued [focused run 45965975397](https://github.com/k1moradi/swapz/actions/runs/45965975397), [job 140394630365](https://github.com/k1moradi/swapz/actions/runs/45965975397/job/140394630365), attempt 1. Snapshot: run queued, job queued, conclusion none. No terminal host or directed-object outcome, artifact, compiler count, or first hosted error has been verified. No redispatch. The new harness extracts actual lifecycle functions with modeled dependencies, requests GCC/Clang ASan+UBSan 11 modes each and 8 mutations each, plus lexical DM witness ordering checks; actual DM witness/bridge runtime is not exercised. Directed job requests only controller and target objects against R103+R104 MM overlays, A1 exact-query export overlay and frozen recorder/bridge. No full link or modpost by A3. Existing repository push-triggered workflows also queued automatically; A3 did not manually dispatch them.

## Remaining blockers

Trusted independent admission/lifetime caller and pre-dtr final retirement invocation are missing; no live table/file circular-lifetime resolution can be claimed without that caller. Ambiguous failed startup, detached quarantine recovery, combined byte contract and actual terminal cleanup debt census, native concurrency and final connected qualification remain open. No branches, PRs, force pushes, manual duplicate dispatch, VM, module loading, activation, physical I/O/mutation or A3 connected full build. Report is pending qualification, not PASS.
