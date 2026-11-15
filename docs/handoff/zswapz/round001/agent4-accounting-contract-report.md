# Round 001 — Agent 4 accounting-contract report (archived GitHub submission)

- **Original GitHub report:** https://github.com/k1moradi/swapz/issues/118#issuecomment-6892196587
- **Task commit:** `b6817ac41f96a0e7df4b0f5f3af258e582723b9e`
- **Frozen source baseline:** `c128ac32374a753a0b27ae0ebec67693355b1b55`
- **Agent-stated task outcome:** PASS (rootless-only, 26 tests)
- **Original issue-comment body SHA-256:** `28fc0e46f7defa14b4251b627268b8be405935675f8049e812c7b39ae81cc81b` (UTF-8, excluding archival wrapper)
- **Archival date:** 2026-11-15 UTC
- **Evidence boundary:** Reporter results below are attributed to the agent, not independently rerun or Phase A kernel qualification.

---

message: REPORT_READY
round: "001"
agent: 4
task_id: agent4-accounting-contract
status: PASS
source_sha: c128ac32374a753a0b27ae0ebec67693355b1b55
task_commit_sha: b6817ac41f96a0e7df4b0f5f3af258e582723b9e
branch: N/A (read-only/source-review and local scratch)
modified_files: []
tests:
  - command: python3 -B /mnt/data/agent4_round001_reconciliation_test.py -v
    exit_code: 0
    outcome: 26/26 PASS (corrected fixture, rootless model only)
evidence_class: rootless
blocking_findings:
  - Selected exact kernel/BIO carrier and authenticated producer not qualified
  - dm-target.c and swapzctl.c provenance status not implemented on frozen source
  - Actual Kbuild, owner-loaded null_blk and real zswap-writeback are NOT_RUN
next_round_recommendations:
  - Agent 1 approve the four-token schema including zswap_origin_schema=1
  - Agent 3 integrate success-only counter at all four existing publication paths
  - Agent 4 implement optional swapzctl reader only after schema approval
  - Agents 5/6/8 independently qualify source-matched ABI and production tests
artifact_url: https://github.com/k1moradi/swapz/issues/118#issuecomment-6892194493
fixture_sha256: 256f4bc77847acdb9c32aecaade3e3a3fb7ae87e0f575924d54b7ce628e03dd5


---

# Agent 4 — Round 001 commit-side provenance accounting contract report

**Task:** `agent4-accounting-contract` · **Round:** `001` · **Task result:** `PASS` (source review + independent rootless reconciliation model ONLY)

**Frozen source baseline:** `c128ac32374a753a0b27ae0ebec67693355b1b55`  
**Immutable Round 001 task commit:** `b6817ac41f96a0e7df4b0f5f3af258e582723b9e`  
**Round issue:** https://github.com/k1moradi/swapz/issues/118  
**Original historical Agent 4 draft:** https://github.com/k1moradi/swapz/issues/116#issuecomment-6890766453  
**Branch:** N/A — read-only remote review + isolated local scratch fixture. **Repository modified files:** `[]`.

## 1. Source-qualified existing accounting

Exact frozen source blobs obtained via GitHub connector:

- [`src/kernel/dm-target.c`](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/kernel/dm-target.c): `746a6349823d8e8f52dfc68f025d29db9942ff2e`; 10,776 lines.
- [`src/userspace/swapzctl.c`](https://github.com/k1moradi/swapz/blob/c128ac32374a753a0b27ae0ebec67693355b1b55/src/userspace/swapzctl.c): `4dcc66cf15b54f659bdfd2c0ad23e45415169bc3`; 2,448 lines.

Existing `u64` per-target counters represent cumulative successful foreground 4 KiB WRITE **operations**, not currently live page mappings, lower requests or zswap pool pages. A successful overwrite counts again; GC writes are separate. The existing status equation is

`N = compressed + raw + zero_elided`, and `logical_write_bytes = 4096 * N`.

The status parser already verifies representation and logical bytes with overflow checks (userspace :525–551), rejects duplicate/noncanonical key tokens (:218–343), and retains a JSON schema v1 status view (:2095, :2130–2198). Unknown INFO keys do not disrupt existing keys (:218). No authenticated origin field or producer ABI exists in this frozen production source.

### All four foreground-success paths — insertion sites for Agent 3

| Representation / existing owner | Frozen source location | Exact successful increment boundary for proposed origin counter |
| --- | --- | --- |
| Detached asynchronous batch, one ordered finalizer | `dm-target.c:2584–2625` | Only within the success branch after `error == 0 && committed == inflight->count`, next to per-BIO `logical_write_bytes` and `raw_pages`/`compressed_pages` increments (:2613–17), before deferred/immediate upper ACK. Error path (:2584–93) must not count. |
| Synchronous batch, ordered owner | `dm-target.c:5409–5458` | Only `index < committed && !READ_ONCE(ctx->failed)`, after any RAW producer wait/error check, beside increments (:5450–54) and before `swapz_complete(bio,0)`. Never count the unsuccessful remainder or solely a submitted/partially finished lower request. |
| Standalone RAW, ordered owner | `dm-target.c:5539–5585` | Only inside `if (!error)` following lower write, RAW verification and `swapz_finish_raw`, beside increments (:5580–83), **not** again in the caller's later ACK. |
| All-zero elision, ordered owner | `dm-target.c:6276–6325` | Only the `else` success arm (:6320–23) after required FUA, mapping invalidation, and any ensuing segment operation, beside existing zero/logical counts, before upper completion. |

**Nuance requiring Agent 5/6 review:** zero-elision calls `swapz_discard_page` (:6309) before a possible later `swapz_discard_dead_segment` (:6311–13), but both existing foreground counters increment only in the final `!error` arm. The proposed origin counter must follow the **same existing terminal-success definition**, not merely observe an intermediate mapping change. This is not a new claim of a demonstrated runtime defect.

Admission (if Agent 1 adopts a separate diagnostic) must occur **under `queue_lock` after the second `ctx->accepting` check** in `swapz_map()` (:8680–8710), before publishing the accepted descriptor to `incoming`. Invalid/requeued/killed/zero-length PREFLUSH traffic cannot count as a 4 KiB foreground origin admission. Proven origin is a scalar copied into each descriptor afresh before publication; it must not alias `preparation_force_raw` or the RAW representation reason.

## 2. Minimal Phase A v1 counter contract proposed for approval

- **Required INFO key:** `foreground_committed_verified_zswap_writeback=<u64 pages>` — target-local, initialized to zero at target creation, monotonic per target lifetime; increment **exactly once** at the four existing final successful foreground representation increments when the descriptor has verified `ZSWAP_STORED_WRITEBACK` origin. GC, failed/aborted/prepared-only work and retries ending in error never count. A deferred ACK does **not** move the counting boundary to ACK delivery.
- **Recommended diagnostic INFO key:** `foreground_admitted_verified_zswap_writeback=<u64 pages>` — count **accepted** tagged 4 KiB writes under admission lock, whether later successful or failed. This is a separate attempted/admitted axis and is **not** committed representation.
- **Required capability INFO key for correct zero interpretation:** `zswap_origin_bio_api_compiled=0|1` — 1 only if consumer compiled with Agent 2's **approved** explicit BIO helper, not a claim that the running kernel matches the headers or the producer is proven. Unsupported builds must emit 0 and never infer authentic origin from `REQ_SWAP`, reclaim, task identity or global `zswpwb`.
- **Proposed additive version INFO key:** `zswap_origin_schema=1` — version the origin-key group and allow all-or-none reader validation. This extra key is a **proposal needing Agent 1/3/4 approval**, not something present in the Agent 3 review artifact or released swapz. A reader encountering a prior artifact with the other three keys but no schema must **not** silently accept it as v1.
- Both counters are cumulative `u64` **pages**; scope is one DM target instance from `kzalloc` creation (:9111) through teardown. Overwrite increments again. No new allocation, clock, status lock, independent publisher or representation path is permitted. The ordered owner writes the committed counter, the existing admission spinlock protects admission increments, and status may use `READ_ONCE` for advisory observation. That does **not** make all INFO fields one atomic snapshot.

**Final status semantics, critical distinction:**

| Kernel INFO and qualification state | Reader's safe origin interpretation |
| --- | --- |
| No origin-key group (old swapz) | `UNAVAILABLE_NO_SCHEMA`; legacy status/ratio remain valid; origin is NOT zero as a fact. |
| Complete group, capability 0, counters 0 | `UNAVAILABLE_NO_CARRIER`; zero is an instrumentation fallback, **not** evidence that no zswap writeback reached the mapper. Positive values with capability 0 are invalid. |
| Complete group, capability 1, but exact runtime kernel/BIO producer & module are not source-qualified | `UNQUALIFIED_RUNTIME_ABI`; counters are diagnostic only, no authenticated empirical claim. |
| Complete group, capability 1, matching patched kernel/build/module source and Agent 5/8-qualified transport | `MEASURED_VERIFIED_SOURCE`; a coherent zero is a measured zero *for this target and observation interval only*. |
| Partial/duplicated, malformed, overflowing, inconsistent or unsupported version | Fail-closed / retry transient live inconsistency; no zero fill-in and no valid Phase A attribution. |

**Proposed reader behavior:** Accept unknown additive INFO keys, require **all four** origin tokens together for v1, require decimal canonical integers `0..2^64-1` and capability in `{0,1}`, reject duplicate tokens, and preserve the present `swapzctl status --json` **root `schema_version:1`**. Only after Agent 4 owns and reviews the userspace change, expose an optional additive per-target `zswap_origin` object with schema/availability and nullable values when unqualified. Existing human/JSON keys stay unchanged; no fake four-bin origin split.

## 3. Reconciliation and snapshot requirements

For each **stable** verified same-target observation:

`N = C + R + Z`  
`logical_write_bytes = 4096*N`  
`0 <= V_committed <= N`  
`0 <= V_committed <= V_admitted`  
`capability == 0 => V_admitted == V_committed == 0` (but origin `UNAVAILABLE`).

For valid before/after intervals under the **same boot, DM target identity, target generation/table event, exact module/source/kernel identity, origin schema and capability**, check all cumulative counters monotonic with no reset/rollover; `Δlogical_write_bytes == 4096*(ΔC+ΔR+ΔZ)` and `0 <= ΔV_committed <= ΔN`. A record admitted before a time window can commit inside it; therefore **do not demand** `ΔV_committed <= ΔV_admitted` for arbitrary live observation windows. For qualification prefer two explicitly drained, source-pinned endpoints, and independently prove neither is torn: a single INFO call or two `READ_ONCE` fields are not a transaction. Fail-closed on unresolved inconsistency; readers may retry bounded transient live incoherence under their existing fail-closed status protocol.

Before doing 4096-byte conversion, check `N <= UINT64_MAX/4096`, and detect additions and multiplication overflow. If an observed counter regresses, do not infer a rollover; invalidate the interval. Require a new source/identity baseline after target recreation or resumption that changes the contract. A physical-parent byte count or global zswap writeback count is not equivalent to the per-mapper foreground count.

**Phase B/C deferred:** `raw_committed_codec_no_fit`, `raw_committed_pressure_not_ready`, `raw_committed_verified_origin_bypass`, `raw_committed_unclassified` remain a proposed separate orthogonal RAW reason vector only. They do not exist in this baseline, are **not** part of this Phase A schema, and Phase B intentional bypass remains forbidden. Ordinary and initially rejected writes share `ORDINARY_OR_UNKNOWN`; do not invent positive distinct bins.

## 4. Rootless evidence and provenance

Scratch fixture: `agent4_round001_reconciliation_test.py` (480 lines)  
SHA-256: `256f4bc77847acdb9c32aecaade3e3a3fb7ae87e0f575924d54b7ce628e03dd5`.  
Host tools: Python **3.13.5**, x86_64.  
Executed: `python3 -B /mnt/data/agent4_round001_reconciliation_test.py -v` → **exit 0; 26/26 PASS**. This is a self-contained Python standard-library contract oracle and proposed INFO reader model, not real `swapzctl` or kernel code. It does not access a device, mapper, swap, or network.

Fixtures cover four final successful representations (two compressed examples), unknown/initial rejection, capability absent, compile-only-vs-runtime trust, overwrite, deferred ACK, duplicate callback, precommit fault, partial successful prefix, GC separation, invalid admission, recycled descriptor, complete INFO parsing, missing/partial origin group, duplicate/noncanonical/overflowing tokens, failed conservation, origin > parent count, u64 wrap rejection, valid interval, cross-boundary admission/commit, source/target drift, reset, torn interval, unavailable capability, Phase B reason absence.

**Test-development trace:** The first local run had 25 PASS and one erroneous assertion in the *fixture's torn-interval test* (the constructed values were individually and incrementally consistent). The fixture was corrected to supply individually plausible but interval-inconsistent values; all 26 subsequently passed. This was a test-fixture defect, not an observed swapz implementation failure. Final test log is preserved separately.

**NOT RUN:** live kernel Kbuild, exact producer/consumer integration, real `swapzctl` parser update, loaded DM/null_blk, real zswap eviction/writeback, KASAN/KCSAN, physical workload, official source-bound `make test`. No source repo checkout or approved runtime ABI. Those tasks remain blocked, even though this Round 001 *contract* task passes.

## 5. Next-round integration handoff

1. **Agent 1:** Approve or revise the four-key origin INFO v1 group (especially the additive `zswap_origin_schema=1`) and explicit runtime evidence requirement; do not authorize Phase B.
2. **Agent 3:** As sole `dm-target.c` production author, fold reviewed counter additions at the four existing successful increment sites and admission lock site into one minimal Phase A consumer change, with stock-header guard. Keep all current comments and owner/completion semantics.
3. **Agent 4:** Own `swapzctl.c` and reader regressions only after Agent 1 approves the schema; preserve JSON v1 and absent/zero/qualification distinctions. Avoid simultaneous `dm-target.c` production editing.
4. **Agents 5/6/8:** Independently validate mixed-origin clone/split/BIO layout on the chosen exact kernel and execute actual source-coupled admission/commit/readback plus ordinary/unknown negatives, FUA, GC, failures, delayed ACK, and source-bound CI on an owner-authorized RAM target.

**Agent 4 final status:** `PASS` for source-anchored reviewable accounting contract and 26 rootless model tests. **PHASE_A=BLOCKED, PHASE_B=DEFERRED; no publication or privileged operations performed.**
