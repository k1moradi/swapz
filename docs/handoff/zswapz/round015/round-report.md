# Round 015 — Agent 1 integrated-source report (CI still being verified)

Official issue: https://github.com/k1moradi/swapz/issues/132
Frozen worker parent: 6d5b40198cfac271e100986fd8bd7637abf40541
Task publication: 8f6a21a3e37c2a9802f7704f3a7915435172620d
Single-writer full source integration: https://github.com/k1moradi/swapz/commit/f716a5162a098742ec4bf7ab17b6a6a977bb75d4
The integration is a real fast-forward expected-HEAD move on the only remote main ref.
All three worker source blobs and all three independently appended testing-standard sections were preserved; 10 files changed by integration.
Workers: Agent 2 source 7ab076291f3d7c6fd031c392a795aee3c667bc9c; Agent 3 c79d8c826c1ac44943959cc115fd1c4409ed5350; Agent 7 893c967269ae52cb16ce13b5c62f75b7adf70f1a.

Evidence classes must not be conflated:
- Worker 2 ran a local isolated rootless C ownership test, not the complete full Linux checkout or loaded writeback.
- Worker 3 ran actual GNU C/UBSan native synthetic-decoder fixtures, not authentic Linux zswap codec interoperability.
- Worker 7 ran six exact helper-excerpt GCC/Clang combinations, not a whole integrated native suite.
- Agent 1 reviewed the source diffs and verified the Git commit graphs, disjoint changed paths, merged standards and final remote HEAD.
- Integrated GitHub CI: source SHA f716a5162a098742ec4bf7ab17b6a6a977bb75d4. Exact linked runs:
  * https://github.com/k1moradi/swapz/actions/runs/43834985537 (private source/static contracts; PASS at initial observation)
  * https://github.com/k1moradi/swapz/actions/runs/43834985699 (rootless physical-evidence audit; PASS at initial observation)
  * https://github.com/k1moradi/swapz/actions/runs/43834985619 (native project goals; IN_PROGRESS at initial observation)
  * https://github.com/k1moradi/swapz/actions/runs/43834985659 (production-C; IN_PROGRESS at initial observation)
  * https://github.com/k1moradi/swapz/actions/runs/43834985929 (full pinned Linux modified source/matched external module; IN_PROGRESS at initial observation)
  * https://github.com/k1moradi/swapz/actions/runs/43834985711 (real Linux BIO KUnit UML; IN_PROGRESS at initial observation)
  * https://github.com/k1moradi/swapz/actions/runs/43834985775 (systemd/package; IN_PROGRESS at initial observation)

Known actual historical first failure: previous real KUnit https://github.com/k1moradi/swapz/actions/runs/43826908357 failed at verify_uml_config with malformed-or-duplicate-manifest. This does NOT qualify five executed y/n KUnit cases; newly running result pending review.
Incompatible disabled direct-compressed prototypes: Agent 2 CRC32 vs Agent 3 CRC32C and independently originated plaintext SHA256; no paired authenticated carrier or safe transfer/decoder.
No real loaded authenticated stored-entry positive eviction and byte-exact 4096-byte swap-in, GC and physical qualification yet.
**Disposition at this checkpoint: SOURCE_INTEGRATED_CI_PENDING. Phase A BLOCKED; Phase B RAW bypass DISABLED; direct compressed handoff DISABLED.**
Close issue only after a subsequent final CI disposition is recorded with exact evidence and blockers.

## Exact integrated-source KUnit first meaningful failure (Agent 1 verified)

Real source SHA f716a5162a098742ec4bf7ab17b6a6a977bb75d4 KUnit run:
https://github.com/k1moradi/swapz/actions/runs/43834985711
retained artifact: https://github.com/k1moradi/swapz/actions/runs/43834985711/artifacts/14209984320

The enabled source-manifest records four distinct legitimate compiled objects: block/bio.o, block/swap-bio-origin-kunit.o, mm/page_io.o and mm/zswap.o. Pinned source staging, defconfig, scripted Kconfig, prepare and modified-object builds, and UML KUnit process returned exit 0. verify_uml_config returned exit 1 with malformed-or-duplicate-manifest. Current parse_manifest() rejects repeated object= lines, so its second object line is the first deterministic parser failure before substantive effective Kconfig or five-case TAP validation. **Classification: SOURCE TEST-EVIDENCE PARSER DEFECT.** Five genuine KUnit cases in both y/n are still **NOT_VERIFIED**, not PASS; the disabled profile did not execute after the enabled failure. The next Agent 2 task now includes this exact cause, distinct identity/hash validation and mandatory no-skip TAP gates.

## Final Agent 1 source closeout — explicit CI partial/failure

**All three independent Round 015 worker source tasks have accountable integrated outcomes** on [f716a5162a098742ec4bf7ab17b6a6a977bb75d4](https://github.com/k1moradi/swapz/commit/f716a5162a098742ec4bf7ab17b6a6a977bb75d4): Agent 2's guarded, default-disabled pinned producer; Agent 3's guarded decoder contract/test fixture; Agent 7's default-unused cooperative policy. All original reports are preserved in [original-report-archive.md](original-report-archive.md).

Exact integrated-source GitHub Actions outcomes observed before close (do not conflate classes):

| Run | Outcome at close | Scope |
| --- | --- | --- |
| [43834985537](https://github.com/k1moradi/swapz/actions/runs/43834985537) | PASS | Private/static source contracts |
| [43834985699](https://github.com/k1moradi/swapz/actions/runs/43834985699) | PASS | Rootless physical-evidence audit, not a physical trial |
| [43834985659](https://github.com/k1moradi/swapz/actions/runs/43834985659) | PASS | Hosted production-C matrix |
| [43834985775](https://github.com/k1moradi/swapz/actions/runs/43834985775) | PASS | Package/systemd |
| [43834985711](https://github.com/k1moradi/swapz/actions/runs/43834985711) | **FAIL** | Real pinned Linux KUnit UML, first failure in evidence parser |
| [43834985619](https://github.com/k1moradi/swapz/actions/runs/43834985619) | **IN_PROGRESS** | Native kernel-C/project goals; future evidence must be reviewed |
| [43834985929](https://github.com/k1moradi/swapz/actions/runs/43834985929) | **IN_PROGRESS** | Pinned modified Linux source + matched swapz module; not yet accepted PASS |

**First verified KUnit failure:** Original [artifact 14209984320](https://github.com/k1moradi/swapz/actions/runs/43834985711/artifacts/14209984320) includes four distinct legitimate `object=` entries with hashes (bio.o, origin-KUnit.o, page_io.o, zswap.o). The workflow's `parse_manifest()` incorrectly rejects the second `object=` as a duplicate *field name*; object identities are distinct. Staging, object building and UML KUnit CLI returned zero but effective config/TAP verification did not execute, and disabled profile did not run. **This is an evidence-parser defect, not proof that the five positive KUnit cases passed or failed.** Assigned for real correction to Agent 2 next round; mandatory y/n TAP and duplicate-object protections remain.

**Additional integration gap:** Prototype producer's CRC32 and guarded consumer's CRC32C with independent plaintext SHA-256 do not form a common authenticated compressed handoff. No real pinned BIO carrier transfers verified representation, codec, immutable payload lifetime or matched decompression authority. Compressed zswap bytes cannot be sent as existing full-page RAW.

The additional main commit [5a40895ba79feecd22e847d57b412687da0b7afa](https://github.com/k1moradi/swapz/commit/5a40895ba79feecd22e847d57b412687da0b7afa) is a later independent synthetic READ-fault null_blk test fix (three unrelated paths), not a Round 015 worker contribution or Phase A qualification. Agent 1 recognized concurrent main movement and re-read the newer HEAD; the expected-head gate refused an obsolete parent, and no force/rewrite was performed.

**Closeout state:** `CLOSED_SOURCE_INTEGRATED_CI_PARTIAL_KUNIT_FAIL`: 3/3 actual worker source implementations integrated; exact CI partial with a real harness FAIL and two jobs still pending. Subsequent CI results must retain their original run evidence and be reviewed as late evidence; their completion cannot rewrite this historical checkpoint. Phase A **BLOCKED**; Phase B forced RAW bypass **DISABLED**; compressed direct handoff **DISABLED**. No loaded authenticated genuine stored-entry writeback and byte-exact 4096-byte swap-in or physical-device qualification.

Next source work is independently executable on frozen source f716a5162a098742ec4bf7ab17b6a6a977bb75d4, without any same-round dependency or unsafe device action. Two workers (2 and 3) are sufficient. Authoritative `ROUND_OPEN` on [issue #133](https://github.com/k1moradi/swapz/issues/133) is a distinct coordinator action; publishing documents does not start worker sessions.
