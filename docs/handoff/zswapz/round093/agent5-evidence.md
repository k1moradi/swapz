# Agent5 Round093 — source published; exact host CI queued

## Source and qualification boundary
- [Source e849f333b4f89d5ffd84dc14c061dfc93566e8e3](https://github.com/k1moradi/swapz/commit/e849f333b4f89d5ffd84dc14c061dfc93566e8e3), sole parent 3fceb96980c47b06fe6592912225d950620a2f3b, recovered and extended prepared candidate f1a66ae3cdb84c4e33ced613c56928feb06c6dfe. Main readback matched source. Six paths only (five added plus complete standards appendix). No legacy authority/engine/storage pointer or decoder ABI change. No branch, PR, force or manual dispatch.
- [Exact push run 45666497774 / job 139389937913](https://github.com/k1moradi/swapz/actions/runs/45666497774/job/139389937913) QUEUED at inspection; no actual compiler verdict, artifact, or CI first error. Local git ls-remote failed exit128 DNS; source-only static checks verified all 14 pinned inputs on opening main, all 13 mutation anchors unique, remote path compare and complete standards readback. Local compile, git diff --check, repository policy NOT_RUN; exact push verifier requires them before host qualification.
- [R092 terminal reconciliation](https://github.com/k1moradi/swapz/issues/210#issuecomment-7168078239) and [Agent1 opening checkpoint](https://github.com/k1moradi/swapz/blob/dc3d55c6c44482f23bb5d263211f2b747e9bee87/docs/handoff/zswapz/round093/agent1-checkpoint.md) retained, R073/R084 existing PASS host only, no repeat or evidence regeneration.

## Added synchronous pinned read
Actual dormant adapter builds a frozen immutable decoder snapshot from the exact CRC-checked storage pin after lower read, with original codec/version, lengths and digest. Four disjoint caller-owned 4096-byte spans (16 KiB total), conservative M3568, no additional allocation, provider callback must acquire and release a separate transient read lease before successful output, caller retains storage pin across call and releases separately. Single sleepable ordered owner, no reentry; provider lifetime external. On lower/stale/alias refusal no decoder callback. Frozen provider contract is trusted for output preservation on decoder failure. Existing pointer ABI, map20 static, monotonic reserve/cancel and issued quarantine preserved. New fixture uses actual shared storage/authority and modeled decoder and RAM I/O, not original codec execution. Checks distinct record/read accounting on successful and failed acquisition/decode, retired/current GC read, close refusal with pinned records, stale pin, buffer overlap and unchanged output sentinel. Four new actual-source mutation anchors plus nine prepared, total 13 per compiler; execution NOT_RUN. No native/real decoder read release proof, no release-fault race or external concurrent entrant proof. Capacity eight retained records including retired pins, frozen provider 64 slots; measured overhead pending; no scalable production claim.

## Provenance
Parent standards blob 36e90b28ccc4af155779558b2163c7bbee3401bc 1822952 UTF-8 bytes; candidate 2e01fd52363450759840e07d9408d4a403ea70b9 1825592 bytes; full parent prefix and complete exact readback verified, append 2640 bytes. Concurrent peer advances reconciled before nonforce expected-head publication. Five source blobs pinned in adjacent JSON. Historical R092 path names in new focused workflow retained deliberately from prepared candidate, workflow display/artifact/verdict labels R093.

AUTH=0; Phase A BLOCKED; compressed handoff, forced RAW bypass, import OFF. No VM, loaded module, privileged or physical mutation. PROGRESS, not REPORT_READY. Next action reconcile existing exact run terminal, no duplicate CI.


## Agent1 terminal reconciliation
```json
{
  "source": "e849f333b4f89d5ffd84dc14c061dfc93566e8e3",
  "job": 139389937913,
  "conclusion": "FAIL_HOST_BASELINE_COMPILE",
  "exact_census": {
    "success": 9,
    "failure": 1
  },
  "artifact": 15047402390,
  "artifact_sha256": "7cbcf0268f759ff2fc16492b354d8722aefe05555209ef3f8c2f1b487262e667",
  "first_error": "zswap-import-codec.h:32:10 fatal error: crypto/sha2.h: No such file or directory",
  "root_cause": "verifier defines SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST but omits SWAPZ_ZSWAP_IMPORT_HOST_TEST controlling codec header branch",
  "gcc_checks": 0,
  "clang_checks": 0,
  "executed_mutants": 0,
  "storage_value_c": "8f532824e9c63a6498d71fcb1ce4c35b18130f1e",
  "storage_value_h": "9b6be5452ff9a7ecb20fb8e661b593c290cc8b7e",
  "scope": "provider modeled; new adapter unqualified, sizes unmeasured"
}
```
