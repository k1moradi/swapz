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
