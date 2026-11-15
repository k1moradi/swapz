# Round 001 — Agent 6 phase-a-negative-tests report (archived GitHub submission)

- **Original GitHub report:** https://github.com/k1moradi/swapz/issues/118#issuecomment-6892191674
- **Task commit:** `b6817ac41f96a0e7df4b0f5f3af258e582723b9e`
- **Frozen source baseline:** `c128ac32374a753a0b27ae0ebec67693355b1b55`
- **Agent-stated task outcome:** PASS (rootless fixture only)
- **Original issue-comment body SHA-256:** `61a202b4c35a44873951772d28316d433dea3b34a33192edde05d7a33eba43da` (UTF-8, excluding archival wrapper)
- **Archival date:** 2026-11-15 UTC
- **Evidence boundary:** Reporter results below are attributed to the agent, not independently rerun or Phase A kernel qualification.

---

message: REPORT_READY
round: "001"
agent: 6
task_id: agent6-phase-a-negative-tests
status: PASS
source_sha: c128ac32374a753a0b27ae0ebec67693355b1b55
task_commit_sha: b6817ac41f96a0e7df4b0f5f3af258e582723b9e
modified_files: []
tests:
  - command: "python3 -B agent6_phase_a_negative_tests.py --matrix A00-A09-results.json"
    exit_code: 0
  - command: "gcc/clang C23 -Wall -Wextra -Wpedantic -Wconversion -Werror -fsanitize=undefined -fno-sanitize-recover=all, with/without test-only origin macro"
    exit_code: 0
  - command: "python3 -m py_compile agent6_phase_a_negative_tests.py"
    exit_code: 0
  - command: "python3 -B agent6_phase_a_negative_tests.py --source <deliberately mismatched fixture>"
    exit_code: "1 (EXPECTED FAIL-CLOSED)"
  - command: "python3 -B agent6_phase_a_negative_tests.py --source src/kernel/dm-target.c (actual complete repo checkout)"
    exit_code: NOT_RUN
evidence_class: rootless
blocking_findings:
  - "No compiled and loaded matched MM producer/DM consumer"
  - "No genuine zswap writeback, real BIO clone/split, or production codec-equivalence test"
next_round_recommendations:
  - "Port A00/A01/A03/A06/A07 tests to actual compiled producer/consumer on pinned kernel"
  - "Exercise A02/A04/A05/A08/A09 in authorized KUnit and owned null_blk"
---

# swapz — zswapz Round 001, Agent 6: Phase A negative-path source fixture

**Task:** `agent6-phase-a-negative-tests`  
**Round issue:** https://github.com/k1moradi/swapz/issues/118  
**Frozen source baseline:** `c128ac32374a753a0b27ae0ebec67693355b1b55`  
**Round task commit:** `b6817ac41f96a0e7df4b0f5f3af258e582723b9e`  
**Frozen production file:** `src/kernel/dm-target.c`, Git blob `746a6349823d8e8f52dfc68f025d29db9942ff2e`  
**Status:** **PASS (rootless source-excerpt negative checks ONLY). Phase A remains BLOCKED.**  
**Host:** x86_64 Linux 6.18.57 container, GCC 14.2.0, Clang 17.0.0, Python 3.13.5. Neither matching kernel build tree nor a source checkout was present.  
**Safety:** no branch, PR, fork, main push, loaded module, mapper/swap manipulation, device I/O, or physical testing.

## Inputs, scope and precise source binding

The official task is [Round 001 Agent 6](https://github.com/k1moradi/swapz/blob/b6817ac41f96a0e7df4b0f5f3af258e582723b9e/docs/handoff/zswapz/round001/agent6-phase-a-negative-tests.md). Round execution was authorized by the [ROUND_OPEN comment](https://github.com/k1moradi/swapz/issues/118#issuecomment-6891942116). The tested C code embeds **verbatim** [production `swapz_map()` admission/descriptor reset at lines 8599–8638](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/kernel/dm-target.c#L8599-L8638) and compiles it in a small, explicitly *mocked* C environment. It is source-excerpt coupled, not a loaded DM execution or complete `dm-target.c` build.

Source identity was independently checked through GitHub at the frozen commit: blob `746a6349823d8e8f52dfc68f025d29db9942ff2e`; raw excerpt length **1,572 bytes** including terminal LF; CRC32 **`8e3d8fb0`**, matching the local fixture byte for byte; excerpt SHA-256 **`05c63b28e2af8246866eaaf5803df8f27eee34dfaa0b0dfe00fea972e2d7093a`**. The self-contained Python test accepts `--source /path/to/src/kernel/dm-target.c` and **requires the complete file's actual Git blob SHA to match** before accepting its embedded prefix; this positive full-file source check is **NOT_RUN** here because there is no local checkout. A deliberately mismatched full-source negative control correctly failed with exit 1 and `AssertionError: source blob differs from frozen main`.

Relevant downstream source also inspected: [preparation FIFO and submitter choices](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/kernel/dm-target.c#L8710-L8753), [prepared/inline codec and RAW selection](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/kernel/dm-target.c#L6070-L6195), [existing terminal completion](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/kernel/dm-target.c#L1642-L1680), and [preparation states and owner transitions](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/kernel/preparation-slots.h). None is a zswap-origin hook in this frozen baseline. `preparation_force_raw` is **existing scheduler state**, not a trusted zswap tag. The old synthetic Phase B oracle is intentionally not used.

## Executed commands and results

| Command / exact flags | Exit | Scope |
|---|---:|---|
| `python3 -B agent6_phase_a_negative_tests.py --matrix A00-A09-results.json` | **0** | 4 C23 compilations and 4 executions; 24 assertions per execution, **96 total** |
| GCC 14.2: `-std=c23 -O1 -g -Wall -Wextra -Wpedantic -Wconversion -Werror -fsanitize=undefined -fno-sanitize-recover=all` | **0/0** compile/run | Without origin macro |
| GCC 14.2, same flags plus `-DBIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN=1` | **0/0** | Test-only macro variant; baseline has no helper/reader |
| Clang 17.0, same flags, without origin macro | **0/0** | Same negative fixture |
| Clang 17.0, same flags, with macro | **0/0** | Same negative fixture |
| `python3 -m py_compile agent6_phase_a_negative_tests.py` | **0** | Python syntax |
| Negative-control `python3 -B agent6_phase_a_negative_tests.py --source <deliberately mismatched local C file>` | **1 (expected)** | Fail-closed full-source Git blob check |

All native C programs returned `PASS: 24 frozen production-admission negative checks`. These tests execute **the actual frozen admission/reset source excerpt** under test-owned mock types. No Linux MM helper, real BIO split/clone, real kernel memory model, full compilation of `dm-target.c`, `make test`, or loaded roundtrip was exercised. Defining the proposed macro alone in the test does **not** validate Agent 2's proposed custom kernel header ABI.

## Machine-readable A00–A09 matrix

| Gate | Executed result | Precisely proven / unproven |
|---|---|---|
| **A00** stock/unsupported ABI | **PASS_ROOTLESS** | Baseline admission code behaves identically with macro absent/present; `CONFIG_ZSWAP=n` real kernel build NOT_RUN |
| **A01** ordinary/rejected/unknown | **PASS_ROOTLESS** | Generic REQ_SWAP and test-only marker `0/1/2/255` do not change admission or scheduler reset; an actual zswap initial rejection was NOT observed |
| **A03** invalid or unrelated BIOs | **PASS_ROOTLESS** | READ, DISCARD, non-swap WRITE, FUA, malformed marker and invalid 4KiB request type are governed solely by frozen admission validation; production origin helper NOT_RUN |
| **A06** reuse/abort boundary | **PASS_ROOTLESS** | For **accepted** entries, `preparation_force_raw`, `preparation_inline`, `prepared_page`, `preparation_error`, submitter-active and publication metadata are reset; closed admission REQUEUE/failed KILL leave descriptor untouched. No existing `write_origin` field exists; kernel `bio_reset` and real requeue NOT_RUN |
| **A07** passive/no bypass | **PARTIAL_STATIC** | Admission prefix has no origin-driven branch or `RAW_SELECTED`, and resets `preparation_force_raw = false`; real LZ4/delta64 attempt counts, committed representations, readback and telemetry equivalence NOT_RUN |
| **A02** positive stored-entry writeback | **BLOCKED** | No approved, matched, compiled MM producer/consumer or loaded zswap eviction |
| **A04** real BIO clone/split | **BLOCKED** | No patched-kernel/KUnit + DM clone path available |
| **A05** mixed-origin aggregation | **BLOCKED** | No real producer homogeneous BIO implementation integrated |
| **A08** authority and byte-exact I/O | **BLOCKED** | No owned loaded test mapper or production-linked integrated candidate |
| **A09** live fault and concurrency | **BLOCKED** | No KASAN/KCSAN, real lower EIO, 64-slot failure or teardown run |

**Negative checks covered in the 24-case C test:** stock writes with ordinary/rejected/untrusted marker values; accepted READ/DISCARD/non-REQ_SWAP WRITE/FUA; descriptor re-admission after nondefault stale preparation values; synchronous/async preparation initializer distinction; invalid zero/512/2048/8192-byte WRITE, unaligned/overflowing sector and logical-page range, unsupported FLUSH opcode versus legal empty PREFLUSH WRITE, valid and oversized DISCARD, and closed-admission REQUEUE versus failed-target KILL. 8KiB tagged WRITE is *rejected by the 4KiB DM target*, not evidence that a genuine 8KiB producer BIO split correctly upstream.

## Artifacts (local scratch; not published to GitHub main)

- `agent6_phase_a_negative_tests.py`: standalone, fail-closed rootless executable incorporating the frozen production admission prefix plus C23 test harness; **SHA-256 `2f0858bca577538474352441a9e58a251363f5d2cd2d87de73c860de19bce7ab`**.
- `A00-A09-results.json`: machine-readable flags, exact compiler invocations, exits, source hashes, status and scope; SHA-256 `223c5425e8547f7d8a901fb6543385be0858f38d6bd73626284f124d54ae2bea`.

The complete fixture is available as a separate artifact for the coordinator to archive or apply later; no production file was edited. On a matching checkout the coordinator can re-run:

```sh
python3 -B agent6_phase_a_negative_tests.py \
  --source src/kernel/dm-target.c \
  --matrix A00-A09-results.json
```

**Do not use that `--source` check on a modified checkout:** the test deliberately fails if the full source blob is not the frozen one. A later Phase A patch requires a **new, independently reviewed fixture and source pin**, not silent relabeling of this baseline PASS.

## Findings / next dependency round

1. **No new baseline correctness defect was found in the tested prefix.** Any claim that `REQ_SWAP`, task identity, dropbehind or a user-supplied marker authenticates zswap is unsupported. Baseline has no write-origin field, so this test cannot prove a stale provenance value is cleared after future implementation.
2. **A07 cannot be promoted based on this fixture.** A verified stored-zswap-origin page in Phase A must still run existing codec and RAW/zero selection without changing attempt counts or committed physical behavior; Phase B zero-attempt RAW bypass must remain disabled.
3. After Agent 1 selects the actual kernel and Agents 2/3 produce a matched producer/consumer, bind A00/A01/A03/A06/A07 to the **actual compiled custom `bio` helper and DM admission**; add negative controls for untrusted/mixed tags, provenance field reinitialization, BIO reset/requeue and matched-build symbols.
4. For A02/A04/A05/A08/A09, use Agent 6/8's exact-source kernel/DM KUnit and authorized owned `null_blk` tests. Trace genuine zswap stored entry → BIO → DM clone → descriptor → successful authoritative commit and byte-exact readback, while verifying unchanged codec behavior and exactly-once BIO completion. Do not treat synthetic tagged BIOs as real provenance.

**Task verdict: PASS for independent rootless negative-fixture preparation; Phase A acceptance remains BLOCKED, Phase B DEFERRED.**
