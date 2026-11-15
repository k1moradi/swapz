# Round 006 — Agent 8 integration checkpoint (not round closeout)

**Status:** One of two independent agents has delivered source. **Agent 8 completed source integration and real hosted LLVM stock-Linux object-build PASS; Agent 7 has NOT submitted an original report. Round 006 is OPEN.**

- Frozen Round 006 base `47a793c1480556c075f23ecbe13a5b465d616916`; unique [`ROUND_OPEN`](https://github.com/k1moradi/swapz/issues/123#issuecomment-6897608738) at task commit `1f0a90621d1ade5ee1d115bc5d96c72c38e8f2f9`.
- **Selected Agent 8 worker source:** [`528a0616363732cc4ec0d975728ea8ba44e1bab7`](https://github.com/k1moradi/swapz/commit/528a0616363732cc4ec0d975728ea8ba44e1bab7). Its actual workflow and additive testing-standard source are on `main` in [`79bb7c0c8bdf055eaeecf81c0fa291d167bd0e61`](https://github.com/k1moradi/swapz/commit/79bb7c0c8bdf055eaeecf81c0fa291d167bd0e61). Non-force, expected-head source integration.
- **Alternative duplicate Agent 8 worker source:** [`a2fcfddb86d8a0e295802fbaeac7869281f35631`](https://github.com/k1moradi/swapz/commit/a2fcfddb86d8a0e295802fbaeac7869281f35631), not merged, not another worker completion.
- **Actual exact-SHA LLVM Kbuild:** [GitHub Actions #43743100361, independent LLVM job 132900365953](https://github.com/k1moradi/swapz/actions/runs/43743100361) **SUCCESS**; full pinned `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8` checkout + LLVM-18 source-object Kbuild step completed, [artifact 14173536534](https://github.com/k1moradi/swapz/actions/runs/43743100361/artifacts/14173536534) retained. This proves only stock Linux LLVM objects, not the GCC linked module or real authenticated stored-entry writeback.
- **Round 005 follow-up:** Native rootless [#43735000085](https://github.com/k1moradi/swapz/actions/runs/43735000085) PASS; real pinned GCC linked-module [#43735000163](https://github.com/k1moradi/swapz/actions/runs/43735000163) FAIL with `Full pinned kernel export table missing; no qualified external module link` before external module was linked. [Exact later-CI addendum](../round005/late-ci-results.md). That known failure has an independent proposed [Round 007 draft repair](../round007/README.md), but Round 007 is **NOT OPEN**.
- **Agent 7:** Missing primary `REPORT_READY` / retrievable source commit on [issue #123](https://github.com/k1moradi/swapz/issues/123). Its original assignment remains outstanding; no accountability sign-off, no fictitious code or report, and no Round 006 closure yet.

## Exact GitHub worker comment archives

| Worker comment | GitHub original | Verbatim archived body | SHA-256 of original UTF-8 body |
| --- | --- | --- | --- |
| Agent 8 selected first | [6897756900](https://github.com/k1moradi/swapz/issues/123#issuecomment-6897756900) | [agent8-selected-original-report.md](agent8-selected-original-report.md) | `30b5e9782fd7aecbb1a6cb82323c6b4b0a31cf6ed247742c50b60e4da6004e21` |
| Agent 8 later alternative | [6897762168](https://github.com/k1moradi/swapz/issues/123#issuecomment-6897762168) | [agent8-alternative-original-report.md](agent8-alternative-original-report.md) | `18ba7b5c95ad552ae8f6fcaf34f8e2b6ae09211dd79c7430d8e48731f09d870d` |

Both original report files contain only their exact original GitHub UTF-8 body bytes. They are **two alternatives for one Agent 8 assignment**; only one integration source and one countable worker result.

**Evidence boundary:** No patched Linux MM→BIO stored-entry provenance producer, matched loaded module, forced zswap reclaim, 4KiB readback or physical media activity is proven. **Phase A BLOCKED, Phase B RAW bypass DISABLED.**
