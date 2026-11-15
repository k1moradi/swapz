# Round 001 — Agent 3 stock-kernel-fallback report (archived GitHub submission)

- **Original GitHub report:** https://github.com/k1moradi/swapz/issues/118#issuecomment-6892181733
- **Task commit:** `b6817ac41f96a0e7df4b0f5f3af258e582723b9e`
- **Frozen source baseline:** `c128ac32374a753a0b27ae0ebec67693355b1b55`
- **Agent-stated task outcome:** BLOCKED (real kernel build unavailable; rootless checks passed)
- **Original issue-comment body SHA-256:** `68c363ddb83b84651d4acb39c99d4926c1334a3ee11f84442bf453c1dabff8e8` (UTF-8, excluding archival wrapper)
- **Archival date:** 2026-11-15 UTC
- **Evidence boundary:** Reporter results below are attributed to the agent, not independently rerun or Phase A kernel qualification.

---

message: REPORT_READY
round: "001"
agent: 3
task_id: agent3-stock-kernel-fallback
status: BLOCKED
source_sha: c128ac32374a753a0b27ae0ebec67693355b1b55
task_commit_sha: b6817ac41f96a0e7df4b0f5f3af258e582723b9e
round_issue: https://github.com/k1moradi/swapz/issues/118
modified_files: []
local_scratch_files:
  - tests/run_stock_fallback.py
  - tests/pinned_map_admission_excerpt.c
  - evidence/gcc-ubsan.txt
  - evidence/clang-ubsan.txt
  - evidence/tamper-negative.txt
  - evidence/build-host.txt
tests:
  - command: "python3 -B tests/run_stock_fallback.py --compiler gcc --sanitize"
    exit_code: 0
    evidence_class: rootless-source-excerpt
  - command: "python3 -B tests/run_stock_fallback.py --compiler clang --sanitize"
    exit_code: 0
    evidence_class: rootless-source-excerpt
  - command: "python3 -B -m py_compile tests/run_stock_fallback.py"
    exit_code: 0
    evidence_class: rootless-syntax
  - command: "mutate a temporary copy of the pinned admission fixture, then rerun the script"
    exit_code: 1
    expected: true
    evidence_class: rootless-negative-control
  - command: "make -s -C src/kernel KDIR=<matched-kbuild-tree> W=1 all"
    exit_code: NOT_RUN
    evidence_class: build-unavailable
  - command: "make -s -C src/kernel KDIR=<matched-kbuild-tree> W=2 all"
    exit_code: NOT_RUN
    evidence_class: build-unavailable
evidence_class: source-review + rootless
blocking_findings:
  - "No complete local swapz source checkout or matching running-kernel build headers."
  - "No actual compiled consumer or authenticated custom BIO producer on a matched kernel."
next_round_recommendations:
  - "Compile the unmodified module on Agent 1-selected exact kernel/header tree with W=1/W=2 and generated source stamp."
  - "Re-run the pinned source-excerpt test on the actual frozen checkout, then retarget it to the reviewed integrated consumer source."
  - "Do not enable Phase B RAW bypass; add passive attributable per-commit observation separately."

# Agent 3 — Round 001 stock-kernel fallback report

**Task outcome: BLOCKED for a real local module Kbuild; source review and rootless negative fixture PASS.** This reports the assigned investigation, *not* Phase A qualification. No new producer ABI, source-origin reader, privileged operation or main publication was performed.

## 1. Frozen identities and independence

- Frozen source input: [`swapz@c128ac32374a753a0b27ae0ebec67693355b1b55`](https://github.com/k1moradi/swapz/tree/c128ac32374a753a0b27ae0ebec67693355b1b55).
- Authoritative Round 001 task commit: [`b6817ac41f96a0e7df4b0f5f3af258e582723b9e`](https://github.com/k1moradi/swapz/tree/b6817ac41f96a0e7df4b0f5f3af258e582723b9e); [`ROUND_OPEN`](https://github.com/k1moradi/swapz/issues/118#issuecomment-6891942116).
- Exact reviewed production `src/kernel/dm-target.c` Git blob: `746a6349823d8e8f52dfc68f025d29db9942ff2e` (GitHub file fetch against frozen source SHA). Production `src/kernel/Makefile`: `ed6e19ae28a84a4a3e92117812adc445d5c2e8e5`; `src/kernel/swapz-build-info.h`: `51ce0bc3a5947bb6ff660e4e5bb63aa5477cb226`.
- This round's report does not use any other Round 001 worker result. Historical issues [#116](https://github.com/k1moradi/swapz/issues/116) / [#117](https://github.com/k1moradi/swapz/issues/117) were read as pre-round context only.

## 2. Actual stock source: source-pinned findings

- The inspected **complete source blob** contains **zero** occurrences of `bio_is_zswap_stored_writeback`, `BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN`, and `write_origin`. Therefore the stock module **does not classify authenticated stored zswap writeback** and cannot expose a genuine positive-origin count. **Provenance is UNAVAILABLE**, not empirically zero. Generic `REQ_SWAP`, task state and reclaim hints cannot establish a zswap-stored-entry origin.
- [`swapz_map()` ~L8589–8660](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/kernel/dm-target.c#L8589-L8660) validates ordinary READ/WRITE as 8 sectors (4KiB), sector-aligned and within `ctx->logical_pages`; it permits a zero-length `WRITE|REQ_PREFLUSH` as the real flush representation, and supports page-multiple DISCARD. The accepted descriptor resets `entry->preparation_force_raw = false`, initializes preparation state and error, then queues through existing `queue_lock`/producer paths.
- [`swapz_accept_write()` ~L6070–6185](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/kernel/dm-target.c#L6070-L6185) uses the existing `bool force_raw = entry->preparation_force_raw` and normal prepared/inline pathways. The stock helper `swapz_compress_prepared_page()` calls `swapz_compress_page()`. None of these references carries provenance, and the checked source contains no origin-driven bypass.
- [Constructor ~L9729–9735](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/kernel/dm-target.c#L9729-L9735) sets `ti->per_io_data_size = sizeof(struct swapz_bio_ref)` and `dm_set_target_max_io_len(ti, SWAPZ_SECTORS)`; this constrains accepted target units to 4KiB. It does not authenticate any upstream BIO tag.
- The [kernel Makefile](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/kernel/Makefile) builds a single `dm-swapz.ko` and stages W=1/W=2 outputs; a direct kernel subdirectory build uses `swapz-build-info.h` fallback `SWAPZ_BUILD_SOURCE_SHA="unknown"`, `SWAPZ_BUILD_SOURCE_CLEAN=0`. Such a compile-only artifact cannot be promoted as source-stamped loaded qualification.

**Behavioral conclusion:** With the stock source, there is no stored-writeback positive bit to read and no origin-dependent branch to change LZ4/delta64, pressure RAW, CRC, generation, GC, error or completion decisions. This is a source-review conclusion, *not* evidence that a patched consumer leaves every runtime edge unchanged.

## 3. Rootless executable checks

A local test script uses a **verbatim manually transcribed admission excerpt** from the exact GitHub source, checksum-locked to `9f82bd9c4079b9ba3b4c172d8b930f21bfa439a9297f3ca5451129666873fa65`. It compiles that inspected C code within an explicit **synthetic** minimal `struct bio`, descriptor, target and helper harness. The script has an optional `--source /checkout/src/kernel/dm-target.c` mode which checks the *whole file's Git blob* before extracting and comparing the admission block. This full-source mode was **NOT_RUN** here, because no local checkout exists.

Executed from the rootless scratch packet:

| Command | Result | Exact scope |
|---|---|---|
| `python3 -B tests/run_stock_fallback.py --compiler gcc --sanitize` | **EXIT 0** | GCC 14.2 / C23 / Werror / UBSan; 22 model cases |
| `python3 -B tests/run_stock_fallback.py --compiler clang --sanitize` | **EXIT 0** | Clang 17 / C23 / Werror / UBSan; the same 22 model cases |
| `python3 -B -m py_compile tests/run_stock_fallback.py` | **EXIT 0** | Python syntax only |
| Corrupt an independent temporary copy of `pinned_map_admission_excerpt.c`, then rerun | **EXIT 1 (EXPECTED)** | Integrity pin rejects altered source excerpt |
| `make -s -C src/kernel KDIR=<matched-kbuild-tree> -j2 W=1 all` | **NOT_RUN / BLOCKED** | No complete project checkout or exact Kbuild tree |
| `make -s -C src/kernel KDIR=<matched-kbuild-tree> -j2 W=2 all` | **NOT_RUN / BLOCKED** | Same |

The 22 harness cases include normal WRITE with and without `REQ_SWAP`, synthetic malformed or forged origin values (a fixture-only field), FUA/PREFLUSH, READ, zero-length flush, invalid count/alignment/bounds, DISCARD extent bounds, unsupported op, closed admission/requeue versus failed-kill, and reusing a descriptor with stale `preparation_force_raw=true`. Accepted ordinary writes reset that field to false; no origin-dependent decision exists. A synthetic `untrusted_origin` is **not** a kernel ABI field and proves no MM authentication. These cases do **not** run real `bio_split`, DM `clone`, actual compression, mapping authority or completion.

Fixture hashes (SHA-256):

```text
ff6dd9f4f20fd96f05fcf379f67fdd33205d50ef866a8df81e6fece9718b03e2  tests/run_stock_fallback.py
960bdfc8b9e158c2bcdcc271536ceb45af64821df05b0a88cfb4a9e06acbebb8  tests/pinned_map_admission_excerpt.c
```

## 4. Build environment and independent CI context

The isolated execution environment has `uname -r = 6.18.57`, `uname -m = x86_64`, **no** `/lib/modules/6.18.57/build`, and an installed Debian development header for `6.12.107+deb13-amd64`. GCC is 14.2 and Clang is 17. No complete local `swapz` checkout was present. Direct `raw.githubusercontent.com` fetch failed with DNS error `Could not resolve host`. Neither compiling against a mismatched 6.12 header nor synthesizing a partial kernel source can yield a legitimate module qualification. No `dm-swapz.ko`, source-stamped artifact, actual `modinfo vermagic`, or matched runtime was generated here.

As **separate GitHub CI evidence**, the task publication SHA `b6817ac41f96a0e7df4b0f5f3af258e582723b9e` has a successful [existing production-C compile-only run #43696447900](https://github.com/k1moradi/swapz/actions/runs/43696447900). This is *not* a test I executed and does not test the Round 001 fixture, patched producer, or Phase A real writeback. The same SHA's independent [systemd/package workflow #43696447848](https://github.com/k1moradi/swapz/actions/runs/43696447848) reported failure; triage of that separate workflow is outside the Agent 3 stock-kernel fallback task. Do not conflate successful compile-only CI with all-workflows-green or a matched loaded kernel.

## 5. Later review-only integration implications

When Agent 1 pins the exact target kernel and explicitly approves the carrier, Agent 3 alone can add a new descriptor-local origin value at `swapz_map()` admission, default-unknown **on every entry and re-entry**, and assign positive origin only for an exact 4KiB `REQ_OP_WRITE` for which the *approved, header-guarded* kernel helper authenticates stored zswap writeback. That value must not change `preparation_force_raw`, producer slot claim, compression, ordered authority or completion. A source-derived fixture must then compare the actual integrated C expression on both patched and unpatched kernel configurations; positive-source propagation and clone/split require real kernel tests from later rounds.

For Phase A observability, a descriptor field alone is inadequate: the eventual commit-side per-mapper counter must increment **once per successfully committed foreground 4KiB logical WRITE**, independently of representation, after authority publication; it cannot be inferred from global `zswpwb` or a failed attempt. Agent 4/1 must approve field semantics and coordinate the exclusive production `dm-target.c` edit window. A missing counter is `UNAVAILABLE`, not zero.

**All A00–A09 production-linked gates remain BLOCKED; Phase B stays disabled.** No `dm-target.c` production patch was applied, no branch/PR/worktree was created, no GitHub `main` publication was made, and no `null_blk`, swapon/swapoff, mapping, memory pressure, physical or privileged operation was performed.
