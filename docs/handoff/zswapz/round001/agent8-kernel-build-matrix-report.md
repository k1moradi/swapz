# Round 001 — Agent 8 kernel-build-matrix report (archived GitHub submission)

- **Original GitHub report:** https://github.com/k1moradi/swapz/issues/118#issuecomment-6892181424
- **Task commit:** `b6817ac41f96a0e7df4b0f5f3af258e582723b9e`
- **Frozen source baseline:** `c128ac32374a753a0b27ae0ebec67693355b1b55`
- **Agent-stated task outcome:** PASS (baseline compilation audit only)
- **Original issue-comment body SHA-256:** `3cd31d4014f2ffa472ba5fe73600b4dda3cf4db8f05f2bf774cf1c10e7badb59` (UTF-8, excluding archival wrapper)
- **Archival date:** 2026-11-15 UTC
- **Evidence boundary:** Reporter results below are attributed to the agent, not independently rerun or Phase A kernel qualification.

---

message: REPORT_READY
round: "001"
agent: 8
task_id: agent8-kernel-build-matrix
status: PASS
source_sha: c128ac32374a753a0b27ae0ebec67693355b1b55
task_commit_sha: b6817ac41f96a0e7df4b0f5f3af258e582723b9e
modified_files: []
evidence_class: source-review
tests:
  - command: "GitHub Actions: make -s -C src/kernel KDIR=\"$KDIR\" -j2 W=1 all; same W=2; same normal"
    exit_code: 0
    source_sha: b6817ac41f96a0e7df4b0f5f3af258e582723b9e
    scope: "existing module; CI compile-only; both architectures"
  - command: "GitHub Actions: make -C tests/suites SANITIZE=1 test-all and native source-contract checks"
    exit_code: 0
    source_sha: b6817ac41f96a0e7df4b0f5f3af258e582723b9e
    scope: "rootless/native only"
  - command: "GitHub Actions: git diff --check HEAD^ HEAD"
    exit_code: 2
    source_sha: b6817ac41f96a0e7df4b0f5f3af258e582723b9e
    scope: "Systemd/package CI patch hygiene, 4 whitespace findings"
  - command: "Matched patched Linux kernel build, KUnit, real writeback, make test, loaded null_blk"
    exit_code: NOT_RUN
    scope: "missing approved matched source and owner-qualified host"
blocking_findings:
  - "No target test kernel/config/BIO carrier approved; source-reviewed Linux 7.3 development patch is not an Ubuntu 7.0 runtime ABI."
  - "No combined producer+consumer candidate, matching loaded module, genuine stored-zswap eviction trace or 4KiB readback evidence."
  - "Round task commit b6817ac: Systemd/package run 43696447848 FAIL on trailing spaces in round001/README.md lines 3-6."
next_round_recommendations:
  - "Agent 1 selects a real exact-source test kernel, config and ABI; owner-host evidence must be identified before approving the carrier."
  - "Coordinator publishes a focused main-only whitespace correction and reruns exact-SHA CI; keep original frozen task SHA in ROUND_OPEN."
  - "Agent 8 qualifies the subsequently integrated MM/BIO/DM candidate on matched headers and owner-authorized null_blk, not from old module CI."

# Agent 8 — Round 001 exact-kernel/build/CI qualification report

**Task disposition: PASS for source-pinned evidence audit only; Phase A: BLOCKED; Phase B: DEFERRED; production promotion: NO-GO.** No product/module/kernel code, repository branch, PR or main revision was written by Agent 8. No module load, device access, root operation, swapon/swapoff, host stress or new benchmark was performed.

## 1. Immutable source boundary

- **Round task commit:** [b6817ac41f96a0e7df4b0f5f3af258e582723b9e](https://github.com/k1moradi/swapz/commit/b6817ac41f96a0e7df4b0f5f3af258e582723b9e), opened by [ROUND_OPEN](https://github.com/k1moradi/swapz/issues/118#issuecomment-6891942116).
- **Source baseline:** [c128ac32374a753a0b27ae0ebec67693355b1b55](https://github.com/k1moradi/swapz/commit/c128ac32374a753a0b27ae0ebec67693355b1b55), a report-only descendant of a87414dc. Comparison a87414dc..c128ac3 changes **only** `test_results.json`; its commit says `[skip ci]`. The GitHub Actions run search for **exact** c128ac3 returned **zero** runs. Do not attribute a874 runs to a direct test of c128ac3.
- Existing baseline production DM target blob: `746a6349823d8e8f52dfc68f025d29db9942ff2e`. The actual [`struct swapz_bio_ref` at c128ac3](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/kernel/dm-target.c#L405-L430) has **no** zswap `write_origin`. No integrated MM producer exists in the swapz repository. No positive origin is source-verified.
- The proposed Linux upstream kernel commit `c339f4010dea8b0d754f84ace70cd1b089878ef8` reports Makefile `VERSION=7 PATCHLEVEL=3` (v7.4 development stream). Agent 2 proposed a custom `BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN` and `bi_swap_origin`, but only source/synthetic checks were reported in [issue #116](https://github.com/k1moradi/swapz/issues/116#issuecomment-6890555852). This is neither a stock upstream/distribution ABI nor a build/load result. The baseline Actions Ubuntu 7.0 headers are different.

## 2. Actual baseline CI — five green workflows belong to a87414dc, not c128ac3

All five exact-source workflows on `a87414dcf610c3ac57fb4eb3c9a2e8014c878352` ran from **2026-11-15 06:47:14 UTC** and finished as follows:

| Workflow | Exact Actions run | Finished UTC | Outcome/evidence limit |
|---|---|---|---|
| Production C/native and module compile | [43687015282](https://github.com/k1moradi/swapz/actions/runs/43687015282) | 06:49:38 | **PASS**, existing module only, both architectures |
| Kernel debug/static/sparse | [43687015277](https://github.com/k1moradi/swapz/actions/runs/43687015277) | 06:48:03 | **PASS**, static/rootless only; **loaded KASAN/KCSAN NOT_RUN** |
| Physical-evidence adversarial | [43687015301](https://github.com/k1moradi/swapz/actions/runs/43687015301) | 06:47:28 | **PASS**, synthetic physical-evidence parser, not real media |
| Native project-goals | [43687015306](https://github.com/k1moradi/swapz/actions/runs/43687015306) | 06:56:45 | **PASS**, native/rootless tests and runner contracts |
| Systemd/package | [43687015311](https://github.com/k1moradi/swapz/actions/runs/43687015311) | 06:54:07 | **PASS**, package and systemd rootless checks |

**Important new evidence after the round opened:** For the task-publication source `b6817ac41f96a0e7df4b0f5f3af258e582723b9e`, GitHub Actions returned **three triggered workflows, not five**:

- [Production C run 43696447900](https://github.com/k1moradi/swapz/actions/runs/43696447900): **PASS**, 4/4 native and compile jobs, including x86_64/ARM64 W=1/W=2/normal modules; finished 08:53:56 UTC.
- [Project-goals run 43696447855](https://github.com/k1moradi/swapz/actions/runs/43696447855): **PASS**, 7/7 rootless/native/Make/repository-policy/CI result jobs; finished 09:03:14 UTC.
- [Systemd/package run 43696447848](https://github.com/k1moradi/swapz/actions/runs/43696447848): **FAIL**, finished 08:56:51 UTC. Its shell syntax, workflow-contract, package-DKMS, systemd runtime-health and diagnostic tests **all passed**; the `Verify patch hygiene` step ran `git diff --check HEAD^ HEAD` and returned **exit 2**, reporting trailing whitespace at `docs/handoff/zswapz/round001/README.md` **lines 3, 4, 5 and 6**. Source-bound [failing job](https://github.com/k1moradi/swapz/actions/runs/43696447848/job/132757934256). **This is a publication/Markdown failure, not a kernel bug.** Agent 1 (single main writer) should remove the four trailing two-space Markdown line breaks in a focused correction, preserve the original frozen task SHA and document the correction, then verify fresh exact-SHA CI; Agent 8 must not push the fix.

Kernel-debug and physical-evidence workflows are **path-filtered** and did **not run** on this documentation-only task commit; historical green cannot be relabeled as current-SHA PASS. These CI runs never load `dm_swapz` or exercise zswap-origin writeback.

## 3. Matched existing-module build matrix, from actual job logs

Both architectures compiled **the same baseline `dm-target.c` blob** (`746a6349823d8e8f52dfc68f025d29db9942ff2e`), against runner-selected `linux-headers-7.0.0-43-generic`, release `7.0.0-43-generic`, GCC **13.3.0**; compiler recorded by the kernel headers also **13.3.0**. These values were emitted by the actual compile jobs (not inferred from release names). **No supported minimum/maximum Linux range** is established.

| CI architecture | Host runner / reported `uname -m` | `W=1` module SHA-256 | `W=2` module SHA-256 | Normal module SHA-256 |
|---|---|---|---|---|
| x86_64 | `ubuntu-24.04` / `x86_64` | `cf0393092990284dd93c241a45e9c07b95c0aa34e3a3bb3a2f7fa27d0e340124` | `6db191e6c7ed45ca6306a28a0e2020a3367e026830bbf794fc8293865bef6d12` | `e4f658c7483b80d2c6694de216ae640a6a905df0b620e628a807ec8f2bd2b450` |
| ARM64 | `ubuntu-24.04-arm` / `aarch64` | `c2ca4f1ac95dc3f8ca6c8260ca5e0ddd31cd6734b0264ca641baf890cc97067f` | `9e9d704034329606a288bf91699d9894d9b821b600193f9e845abc2ec965b86e` | `7633295842f1d7d2a204ebb314349814a9dff4cb2443e11e4b7c4e5ff43f454a` |

These six SHA-256 hashes appear **identically** in the independent a87414dc and b6817ac successful compile logs. W=2 reports **exactly one external installed kernel-header warning per architecture**; the workflow's warning gate rejects module-source warnings and allows this classified external diagnostic. The normal module's `modinfo -F vermagic` **first token was checked equal** to `7.0.0-43-generic` in CI; the **full vermagic string is not printed**, so it is **UNAVAILABLE** in this report.

**Not directly evidenced by the Actions output:** actual running-test-host kernel matching the header tree (runners are compile-only); CONFIG_ZSWAP=y/n state and corresponding tested producer path; full exact kernel source Git SHA; generated `include/generated/autoconf.h` provenance digest; `Module.symvers` hash; detailed page-size/config verification beyond the repo's **little-endian, 4096-byte PAGE_SIZE requirement**; a runtime `sizeof(struct bio)`/offset ABI comparison. These are **UNAVAILABLE/NOT_RUN**, not presumed successful. A Kbuild PASS is not proof that the module may be loaded into a patched `struct bio` runtime.

### Build-info source qualification gap

[`src/kernel/Makefile` at c128ac3](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/kernel/Makefile#L31-L94) uses the checked-in `src/kernel/swapz-build-info.h` **unless** `SWAPZ_BUILD_INFO` was explicitly supplied. That checked-in fallback defines `SWAPZ_BUILD_SOURCE_SHA "unknown"` and `SWAPZ_BUILD_SOURCE_CLEAN 0`. The [production-C Actions workflow](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/.github/workflows/product-codec.yml#L68-L219) calls `make -s -C src/kernel KDIR="$KDIR" -j2 ... all` directly, without supplying `SWAPZ_BUILD_INFO`. Thus its manifest `SOURCE_SHA=$(git rev-parse HEAD)` documents the **CI checkout**, but the emitted `.ko` has fallback **unknown/0** and is not an owner-host source-stamped release candidate. The [root Makefile](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/Makefile#L15-L51) generates a real `build/source-build-info.h` and passes it explicitly for a qualifying owner build. Passing the compiler/header and `vermagic` release checks still does not validate the custom BIO ABI or an actual running kernel.

## 4. Production Phase A gate status — A00 through A09

| Gate | Required producer/consumer evidence | Actual Round 001 outcome |
|---|---|---|
| **A00** | Stock ABI absent, CONFIG_ZSWAP=n matched consumer build, default UNKNOWN, no behavior change | **BLOCKED**: existing stock module compile is not a patched consumer fallback test |
| **A01** | Ordinary/rejected/unsupported write never falsely tagged | **BLOCKED**: actual MM+DM pair not integrated |
| **A02** | Genuine previously stored zswap entry decompressed, tagged, committed and byte-exact 4KiB readback | **BLOCKED**: no owner-qualified loaded evidence |
| **A03** | Invalid/malformed/non-REQ_SWAP/READ/reclaim-only false positives rejected | **BLOCKED**: exact helper+consumer combination unbuilt |
| **A04** | Homogeneous origin across real BIO clone, split and DM 4KiB slices | **BLOCKED**: no patched-kernel KUnit/loaded proof |
| **A05** | Mixed-origin aggregation, large folios, safe downgrade/split | **BLOCKED**: no real source-bound propagation test |
| **A06** | BIO init/reset/requeue and descriptor reuse; no stale positive or borrowed pointer | **BLOCKED**: no patched-kernel lifetime test |
| **A07** | Admission vs authoritative successful-commit attribution, unchanged codecs/requests | **BLOCKED**: Agent 4 field draft is not production instrumentation |
| **A08** | Production-C plus owned-null_blk readback across compression/RAW/zero, overwrite, FUA, DISCARD, GC, completion | **BLOCKED**: no combined Phase A source |
| **A09** | Fault/short I/O/ENOMEM/cancel/suspend, once-only ACK, KASAN/KCSAN where possible | **BLOCKED**: no source-pinned loaded fault evidence |

All positive Phase A production tests are **NOT_RUN**. The existing rootless/native test passes exercise older behavior or synthetic contracts; do not count any of them as A00–A09 production-linked PASS. B01/B02 and RAW bypass stay **DEFERRED**, disabled and unapproved.

## 5. Reproducible qualification plan for the next dependency round (NOT RUN)

**Precondition:** Agent 1 approves an exact host-supported Linux source commit/config/generated headers, matching `Module.symvers` and `kernel.release`, 4KiB page size, toolchain and the concrete carrier. Agent 2 must supply the reviewed producer patch against *that exact source*. Agent 3 must publish only the passive capability-guarded consumer with unchanged representation. Agent 5 independently resolves B0-3, Agent 4 signs commit-side counter semantics, and Agent 6 supplies production-linked negative fixtures. Until then, the following commands are an execution **plan**, not executed evidence.

~~~bash
# Offline source and build provenance (in the authorized matched source trees):
git -C "$LINUX_SOURCE" rev-parse HEAD          # require approved exact kernel commit
git rev-parse HEAD                            # require approved swapz integration commit
test -f "$KDIR/include/config/kernel.release"
test -f "$KDIR/include/config/auto.conf"
test -f "$KDIR/include/generated/autoconf.h"
test -f "$KDIR/Module.symvers"
cat "$KDIR/include/config/kernel.release"
grep -E '^CONFIG_(SWAP|ZSWAP|BLK_DEV_DM|64BIT|CC_VERSION_TEXT)=' "$KDIR/include/config/auto.conf" || true
sha256sum "$KDIR/Module.symvers" "$KDIR/include/generated/autoconf.h"
git -C "$LINUX_SOURCE" diff --check
# On the exact patched kernel, Kbuild CONFIG_ZSWAP=y and CONFIG_ZSWAP=n
# in separate, prepared KDIR configurations; capture first failure and W=1/W=2.
make -C src/kernel KDIR="$KDIR" W=1 -j2 all
make -C src/kernel KDIR="$KDIR" W=2 -j2 all
# Root-generated build info rather than direct compile-only fallback:
make KDIR="$KDIR"
modinfo -F vermagic build/kernel/experimental/dm-swapz.ko
sha256sum build/kernel/experimental/dm-swapz.ko
make -C tests/suites SANITIZE=1 test-all
python3 -B tests/runtime/native/source-contract-test.py -v
make -C tests/suites clean
make -C tests/suites THREAD_SANITIZE=1 test-concurrency
# Owner-authorized only, after target/kernel/mapper/source safety preflight:
make test
make test_full
~~~

The planned kernel KUnit/source-specific coverage must exercise successful zswap **stored-entry** identity and decompression, rejected/ordinary/unknown path, `bio_init`/`bio_reset`/`__bio_clone`, `bio_split` and block/DM clone/split/reissue, multi-page homogeneous vs mixed producer aggregation, fresh per-4KiB descriptor reset, and absence of the capability macro. The loaded tier must use **positively owned RAM-backed null_blk** and observe the same 4KiB event at MM producer, backing BIO, DM clone, mapper admission and **successful foreground commit**, followed by exact readback. Compare codec attempt counts, compressed/RAW/zero representation and lower bytes/requests against an identical untagged control: **Phase A must not skip compression**. Inject error, suspend, GC and overwrite/requeue faults without changing the established authority/ACK path. KASAN/lockdep and KCSAN require separately authorized instrumented kernel boots. Never use a live physical swap mapper or current owner media merely to obtain provenance evidence.

A future owner `make test` can legitimately remain **INCOMPLETE/nonzero** until separate physical source/run/target admission. `make fast_test` is development-only, `make test_full` rootless/RAM integration does not certify real media, and no rootless CI success qualifies physical storage, endurance or boot readiness.

## 6. Decision and handoff

**Evidence → goal implication → verdict:** Historical five-green `a87414dc` and new successful existing-module x86/ARM compilation demonstrate baseline buildability; they do not supply the custom ABI, its runtime layout, a combined Phase A module or authentic zswap writeback. Meanwhile the exact task-publication SHA has a confirmed documentation whitespace CI failure. → Neither technical correctness nor a fully green current workflow is established. → **Agent 8 task AUDIT PASS; Phase A integration/release NO-GO, A00–A09 BLOCKED; Phase B deferred.**

**Priority:** (1) Agent 1 fixes the four whitespace-only lines via one designated main writer, preserving the frozen `ROUND_OPEN` task hash and posting the correction identity; (2) Agent 1/2 select exact kernel and prove real patched producer Kbuild, including config/layout; (3) Agent 3/4 provide the passive source-linked consumer and success-only counter; (4) Agent 5/6 test clone/split/unknown/lifetime and negative paths; (5) Agent 8 reruns exact-source/build and owner-authorized loaded qualification and issues the independent acceptance verdict.

**Tool observations:** Read-only GitHub repository file/commit/compare, issue, Actions-run/job/step and job-log queries succeeded. All reported runs/exit codes came from linked GitHub Actions, not from commands executed on the user's host. Local source checkout with matching kernel headers, owner-qualified null_blk, patched Linux kernel tree and owner-scope evidence were **unavailable**, so no local Kbuild, root `make test`, loaded test or physical run was attempted. This report is a complete GitHub-issue handoff to the **single designated Agent 1 archive writer**.
