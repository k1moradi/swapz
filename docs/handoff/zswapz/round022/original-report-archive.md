# Round022 — original worker reports and source updates, complete verbatim archive

Fetched from [official Round022 issue #139](https://github.com/k1moradi/swapz/issues/139) at integration closeout. Reports' local isolated/excerpt tests are not claimed full repository imports, loaded kernels or owner physical trials. This is an append-only historical record; full worker text below is retained unchanged.

## Agent2 first publication — [original comment](https://github.com/k1moradi/swapz/issues/139#issuecomment-6926251466)

message: REPORT_READY
round: "022"
agent: 2
status: SOURCE_PUBLISHED_MAIN; LOCAL_SOURCE_EQUIVALENT_C_ASAN_UBSAN_PASS; EXACT_COMMITTED_CI_IN_PROGRESS; PHASE_A_BLOCKED
published_main_sha: 99e8cbdac05f2acb43203050e2da473a890585bb
sole_parent_sha: 71b36e2216163dae77a1bbc62488d066de49580a
task_publication_sha: d12a2465cce64beec87f809d1e21df813b5867c5
publication: NON_FORCE_EXPECTED_HEAD_FAST_FORWARD_VERIFIED
commit_url: https://github.com/k1moradi/swapz/commit/99e8cbdac05f2acb43203050e2da473a890585bb
evidence_note: https://github.com/k1moradi/swapz/blob/99e8cbdac05f2acb43203050e2da473a890585bb/docs/handoff/zswapz/round022/agent2-evidence.md
DIRECT_COMPRESSED_ACTIVE: DISABLED
LOADED_STORED_ENTRY: NOT_RUN
4096_READBACK: NOT_RUN
PHYSICAL: NOT_RUN
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED

Agent 2 tested and published four exclusively assigned paths, preserving Agent3's prior main commit and separate standards:
- `tests/tools/stage-pinned-linux-zswap-origin.py` (+144/-9): compile-disabled original pinned Linux compressed producer proof/binder, exact xarray stored-entry slot/generation and store-time LZ4, independent original full 4096 SHA256, <=3568 owned copied zsmalloc bytes, separate ZSWAP_SWAPZ_REPR_ZSWAP_LZ4_V1 never RAW_4096, payload CRC32C (not CRC32), fail-closed submit/abort/finish lifetime and source mutation/guard. Normal pinned Linux compiled `zswap_decompress()`→REQ_SWAP BIO code and original Git blob allowlist unaffected.
- `tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py` (+135/-25): negative C source mutations, stage/off isolation, GCC+Clang ASan+UBSan compilation of exact staged disabled C in existing hosted source workflow; host mock original SHA known independently from Python SHA256, CRC32C vector, ABA/slot/generation, rejected ZSTD, unknown codec, wrong extent/version/representation, allocation errors, stale borrowed pointer, mutable original zpool bytes, wrong CRC32 polynomial/bit flips, immutable owned copy, duplicate submit/abort, concurrent two-callback exactly once -EIO retention, no double-free. Host atomic cmpxchg stub corrected to return actually observed state. No device operations.
- `docs/handoff/zswapz/round022/agent2-evidence.md` (+29): exact causality/CPU+RAM implications and limitations.
- `docs/testing_standards.md` (+34): unique appended Round022 Agent2 section; whole previously published Agent3 section and other standards preserved.
GitHub compare: 1 commit ahead/0 behind, exactly four paths. GitHub expected_sha=71b36e2216163dae77a1bbc62488d066de49580a, force=false update succeeded, remote main readback verified 99e8cbdac05f2acb43203050e2da473a890585bb. No new branches/PR/forks/worktrees.

Measured rootless local tests (no complete local clone, CLI GitHub DNS unavailable):
- `git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main`: **EXIT 128** (github.com DNS failure); GitHub connector source and ref readbacks succeeded.
- `gcc -std=gnu11 -O1 -g -Wall -Wextra -Wconversion -Wshadow -Werror -fsanitize=address,undefined -fno-sanitize-recover=all -pthread /mnt/data/round022-agent2/producer-host.c -o /mnt/data/round022-agent2/gcc-asan && ASAN_OPTIONS=detect_leaks=1 /mnt/data/round022-agent2/gcc-asan`: **BUILD EXIT 0, RUN EXIT 0**.
- Same C source flags under `clang` 17 to `clang-asan`: **BUILD EXIT 0, RUN EXIT 0**. GCC 14.2.0 used above. These are **manually reconstructed source-equivalent** disabled-prototype C functions plus host mocks; they are NOT the exact complete committed Python module, kernel hashing, or loaded zswap source.
- `git diff --no-index --check /dev/null /mnt/data/round022-agent2/producer-host.c`: no whitespace diagnostics; full repository `git diff --check` **NOT_RUN** locally without checkout.
- First local failure: the initial strict C compile returned nonzero for three **fixture-only** -Wshadow globals; corrected `host_pool`, `host_original_page`, both compilers and ASan/UBSan then EXIT 0. No product C warning suppression.
- Independently inspected source-only Python disabled-prototype guard: 16 exact required semantic tokens occur once, atomic CAS and self-identity each exactly 3 occurrences; active #if1 absent and IEEE crc32(0) forbidden. This is static inspection, not Python runtime.
- Committed `python3 -B tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py`, full stage/producer suites, strict hosted compiler of exact extracted C, complete local py_compile and original Git diff: NOT_RUN locally. Exact source GitHub workflow [#43935827239](https://github.com/k1moradi/swapz/actions/runs/43935827239), native rootless [#43935827180](https://github.com/k1moradi/swapz/actions/runs/43935827180), and pinned KUnit [#43935827188](https://github.com/k1moradi/swapz/actions/runs/43935827188) are **IN_PROGRESS** at publication. Report exact failure if these turn red; do not claim new CI PASS now.

Historical real pinned KUnit enabled/disabled y/n 5/5 distinct no-skip PASS https://github.com/k1moradi/swapz/actions/runs/43897628379 and matched Linux/module Kbuild PASS https://github.com/k1moradi/swapz/actions/runs/43897628284 remain prior source baseline, not stored-entry compressed→loaded-DM authority. Real store-time slot allocator epoch and bounded concurrent-proof quota, consumer ABI/codec compatibility and genuine loaded original-page memcmp still need integration and owner authorization. Current swapz RAW=original uncompressed 4096-byte page; SWAPSPACE2 protected original 4096-byte header/UUID/partition table never accessed/modified. No sudo, kernel/module/cgroup pressure, mkswap, swap activation, null_blk, mapper or physical operations.

MAIN_WRITE_LEASE_RELEASED


---

## Agent3 producer-independent consumer — [original comment](https://github.com/k1moradi/swapz/issues/139#issuecomment-6926339561)

message: REPORT_READY
round: "022"
agent: 3
task_id: compressed-swapz-consumer
status: SOURCE_PUBLISHED_MAIN; HOST_LZ4_C_GCC_CLANG_ASAN_UBSAN_PASS; LIVE_NOT_RUN
published_main_sha: 71b36e2216163dae77a1bbc62488d066de49580a
source_parent_sha: d12a2465cce64beec87f809d1e21df813b5867c5
current_remote_main_includes_source: 8ad53ee4f57c5f8b272ca3ef4fadf1d8cd7cfbc8
publication: NON_FORCE_EXPECTED_HEAD_FAST_FORWARD_VERIFIED
ZSWAP_COMPRESSED_ACTIVE: DISABLED
LOADED_STORED_ENTRY: NOT_RUN
4096_KERNEL_READBACK: NOT_RUN
PHYSICAL: NOT_RUN
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED

## Actual five-file consumer deliverable
- NEW src/kernel/zswap-import-codec.h: separate, UNUSED and explicitly disabled imported zswap LZ4 block decoder (SWAPZ_ZSWAP_IMPORT_ACTIVE=0), volatile RAM-only per-record codec/length/slot/generation/store-entry identity/GC epoch, CRC32C, original independent 4096 SHA256, immutable-owned/true-stored provenance flags. Requires previous durable foreground WRITE + published authority, exactly one upper WRITE ACK, still-owned exclusive RAM, no teardown, exact successful lower READ bytes, and scratch/output disjointness. Real LZ4_decompress_safe must yield exactly 4096, SHA256 and optional original-page memcmp must match before output is copied. CRC32, SHA, wrong codec/version/dictionary, bad lengths, stale/ABA, errors, duplicate ACK, corrupt bytes, frame/block mismatch and overlap reject with negative errno and no partial output. No production include, no new kernel ABI, no on-media header.
- NEW tests/runtime/native/fixtures/round022-consumer-codec.c: compiler-executable LZ4 block payload, original full page 4096 memcmp, CRC32C against CRC32 and diverse negative source mutations. Intended rootless link uses the actual existing src/kernel/codec.c CRC32C.
- NEW tests/runtime/native/zswap-compressed-consumer-test.py: original-code source guard plus exact GCC/Clang strict -Werror/-Wconversion/-Wshadow ASan/UBSan compile+run for above fixture + production codec.c.
- NEW docs/handoff/zswapz/round022/agent3-evidence.md and separate append-only Round022 Agent3 docs/testing_standards.md section. Published before Agent2's separate main work; all prior content preserved.

## Actually executed and first failures
- GCC and Clang: gcc/clang -std=gnu11 -O1 -g -Wall -Wextra -Werror -Wconversion -Wshadow -fsanitize=address,undefined -fno-sanitize-recover=all -I/mnt/data/round022 /mnt/data/round022/consumer.c /mnt/data/round022/codec.c -llz4 -lcrypto -o /mnt/data/round022/consumer-asan-gcc|clang; ASAN_OPTIONS=detect_leaks=1 respective executables: both COMPILE EXIT 0 and EXECUTE EXIT 0, printed ROUND022_CONSUMER_ROOTLESS_SOURCE_ONLY_PASS. NOTE: /mnt/data/round022/codec.c was a local source-equivalent subset/shim; original full codec.c was NOT compiled locally.
- python3 -B /mnt/data/round022/testroot/tests/runtime/native/zswap-compressed-consumer-test.py -v: EXIT 0, 2/2 PASS, 0.623s. A first run against a deliberately minimal local codec.h shim initially failed because it lacked SWAPZ_CODEC_METADATA_ON_MEDIA; adding the actual production contract constant to that shim produced 2/2 PASS. This is NOT full exact repository source execution.
- gcc and clang 17 strict ASan/UBSan host fixture repeated PASS after pointer-range overlap negative.
- Local git hash-object header = 8c496c53546462ae14ade8990231d3cdaca3294e, fixture = a7a46f6a0384597145de0bf5c0efcf0bfcd6036c, Python regression = 2701415fb75146079877c0447d8ef73fc321888c; GitHub exact committed blob SHAs verified equal.
- Local git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main: EXIT 128 (github.com DNS unavailable). No local full main checkout; used GitHub connector create_blob/tree/commit and non-force update_ref main with expected source HEAD, then exact REST ref verification. NO branch/PR/worktree/force.
- Full committed original-code Python source suite, full actual linked codec.c regression, production loaded Linux/KUnit current SHA, 4096 kernel readback, owner-RAM and physical trial NOT_RUN locally. Agent1 to verify source CI.
- First cross-track integration finding during reconciliation: producer crc32c(0,...) raw seed incorrectly diverged from actual production swapz ~crc32c(~0U,...); a separate non-force correction on main 8ad53ee4f57c5f8b272ca3ef4fadf1d8cd7cfbc8 aligns the disabled producer and its test to the consumer. Canonical CRC32C of 123456789 = 0xe3069283; kernel raw seed0 = 0x58e3fa20. No transport enabled.

Historical genuine pinned Linux y/n KUnit 5/5 and matched module build are SOURCE/BUILD only, not real compressed stored entry→MM/BIO→loaded DM→original 4096 swap-in. Current RAW retains original UNCOMPRESSED 4096; SWAPSPACE2 original header/UUID/partition table untouched; only RAM-side metadata and payload-only lower area are architecturally allowed. No sudo, module load, pressure, swap, null_blk or physical operation performed.

MAIN_WRITE_LEASE_RELEASED

---

## Agent2 source CRC32C correction — [original comment](https://github.com/k1moradi/swapz/issues/139#issuecomment-6926349390)

message: REPORT_READY
round: "022"
agent: 2
report_kind: NONFORCE_MAIN_CHECKSUM_CORRECTION_TO_PRIOR_AGENT2_REPORT
original_agent2_report: https://github.com/k1moradi/swapz/issues/139#issuecomment-6926251466
correction_published_main_sha: 8ad53ee4f57c5f8b272ca3ef4fadf1d8cd7cfbc8
sole_parent_sha: c3dc9a476ff5014df8a6863bdbfc7d356efb9098
publication: NON_FORCE_EXPECTED_HEAD_FAST_FORWARD_VERIFIED
direct_compressed_active: DISABLED
loaded_stored_entry: NOT_RUN
4096_kernel_readback: NOT_RUN
physical: NOT_RUN
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED

## First independently reproduced integration failure
The published Agent2 #if0 producer originally used crc32c(0, payload, length) while the existing production swapz consumer's swapz_crc32c_bytes is ~crc32c(~0U, payload, length). Linux's raw seed-zero Castagnoli state is not the standard CRC32C checksum: on "123456789" raw seed0 = 0x58e3fa20 versus production CRC32C = 0xe3069283. Therefore a seemingly correct stored compressed payload would fail CRC verification even if all codec/slot/generation bytes matched. The original source producer's IEEE CRC32 was also obsolete and its retained Python test was initially stale; a peer earlier fixed the stale test, and this follow-up preserves that peer work while matching the exact consumer CRC32C seed/final convention.

## Changed five owned files, current main
- tests/tools/stage-pinned-linux-zswap-origin.py: only #if 0 producer CRC32C calculation/verification and frozen source assertions now use ~crc32c(~0U,...); exact pinned original mm/zswap.c functions, KUnit and ordinary decompressed BIO remain unchanged.
- tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py: host-kernel crc32c() raw-state semantics corrected, all test calls/source negative mutations updated to the production complemented checksum; LZ4 store-time proof, original page SHA, identity/lifetime/error callbacks retained.
- tests/runtime/native/pinned-linux-zswap-stored-entry-producer-test.py: source-bound default-disabled regression now requires the corrected Castagnoli call, never old IEEE CRC32.
- docs/testing_standards.md: unique append-only Round022 Agent2 checksum-seed correction, all older sections and peer sections preserved.
- docs/handoff/zswapz/round022/agent2-evidence.md: append-only original first-cause/contract reconciliation.

## Actually executed verification
- Python inline 9-byte CRC32C reference-vector check: EXIT 0. Raw kernel state(0, b"123456789") == 0x58e3fa20; production ~state(0xffffffff, bytes) == 0xe3069283, with explicit inequality assertion. This is a deterministic source-equivalent reference, not loaded kernel evidence.
- gcc -std=c11 -Wall -Wextra -Wconversion -Wshadow -Werror -fsanitize=undefined,address -fno-sanitize-recover=all -O1 /mnt/data/round022/crc-integration.c -o /mnt/data/round022/crc-gcc; execution: COMPILE EXIT 0, RUN EXIT 0, ROUND022_CRC32C_SEED_INTEROP_SOURCE_ONLY_PASS.
- clang equivalent flags/input with separate crc-clang: COMPILE EXIT 0, RUN EXIT 0, same marker, both ASan/UBSan PASS.
- Earlier independent source-derived producer.c compiler spot check: gcc and clang -std=gnu11 -O1 -g -Wall -Wextra -Werror -Wconversion -Wshadow -fsanitize=address,undefined -fno-sanitize-recover=all /mnt/data/round022/producer.c -lcrypto -o /mnt/data/round022/producer-gcc|clang; both COMPILE EXIT 0, RUN EXIT 0. Explicit source-derived model, NOT byte-exact committed source. Original Agent2 independently reported a compiled source-equivalent producer fixture PASS; see original report for details.
- Full exact committed original Python suite and newly triggered KUnit y/n/module workflow: NOT_RUN locally (GitHub DNS unavailable for local checkout; full current-SHA CI in progress when observed). GitHub connector verified only existing main was moved from exact c3dc9a476ff5014df8a6863bdbfc7d356efb9098 to 8ad53ee4f57c5f8b272ca3ef4fadf1d8cd7cfbc8 using expected-head, force=false, then re-read actual remote main SHA. No branch, fork, PR, worktree or history rewrite.
- At latest check exact-SHA #43936506238 Rootless physical evidence adversarial audit SUCCESS; pinned source prototype #43936506271 and pinned original BIO KUnit #43936506342 IN_PROGRESS. Other current-SHA workflows QUEUED. Do not label full new commit CI/KUnit PASS.

Unchanged SWAPSPACE2 original first 4096 header/UUID, normal original UNCOMPRESSED 4096 RAW, disk payload-only extents and volatile RAM metadata, Linux zswap small bounded cache/real eviction control. No physical trial, sudo, swap, pressure, module load or owner device mutation. Phase A BLOCKED; Phase B RAW bypass/direct compressed handoff DISABLED.

MAIN_WRITE_LEASE_RELEASED

---

## Agent2 three-commit closeout — [original comment](https://github.com/k1moradi/swapz/issues/139#issuecomment-6926351882)

message: REPORT_READY
round: "022"
agent: 2
status: SOURCE_PUBLISHED_MAIN_THREE_FF_COMMITS; FIRST_CI_FAILURE_FIXED; INTEGRATION_CRC32C_SEED_CORRECTION_PUBLISHED; EXACT_HOSTED_QUALIFICATION_IN_PROGRESS
agent2_last_published_sha: c3dc9a476ff5014df8a6863bdbfc7d356efb9098
agent2_publication_chain: [99e8cbdac05f2acb43203050e2da473a890585bb, 0fdb8a6a031b2e0fec60d784841249b8cb36afe6, c3dc9a476ff5014df8a6863bdbfc7d356efb9098]
agent2_last_parent: 0fdb8a6a031b2e0fec60d784841249b8cb36afe6
post_agent2_integrated_head_observed: 8ad53ee4f57c5f8b272ca3ef4fadf1d8cd7cfbc8
peer_and_integration_ancestry: FAST_FORWARD_NO_REWRITE
publication: EXPECTED_HEAD_NON_FORCE_FAST_FORWARD_VERIFIED_EACH_SOURCE_COMMIT
commit_url: https://github.com/k1moradi/swapz/commit/c3dc9a476ff5014df8a6863bdbfc7d356efb9098
current_integrated_commit_url: https://github.com/k1moradi/swapz/commit/8ad53ee4f57c5f8b272ca3ef4fadf1d8cd7cfbc8
evidence_note: https://github.com/k1moradi/swapz/blob/8ad53ee4f57c5f8b272ca3ef4fadf1d8cd7cfbc8/docs/handoff/zswapz/round022/agent2-evidence.md
DIRECT_COMPRESSED_ACTIVE: DISABLED
LOADED_STORED_ENTRY: NOT_RUN
4096_READBACK: NOT_RUN
PHYSICAL: NOT_RUN
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED

Agent2 implemented and published ONLY assigned files, retaining Agent3's first published commit 71b36e2216163dae77a1bbc62488d066de49580a and its canonical standards:
- tests/tools/stage-pinned-linux-zswap-origin.py: compile-disabled original-pinned zswap stored LZ4 proof from authenticated xarray/folio/slot generation and store-time SHA256 of original 4096 page; distinct ZSWAP_LZ4_V1 representation (never RAW_4096), bounded copied immutable <=3568 payload, CRC32C, once-only submission/finish/abort, no active BIO compressed transport or changes to original KUnit source.
- tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py: strict source-bound GCC/Clang host C, negative generation/ABA/stale memory, codec/extent, original-page SHA/CRC, duplicate completion/concurrency, false decoder format, force-off test; triggered exact pinned modified Linux source workflow.
- tests/runtime/native/pinned-linux-zswap-stored-entry-producer-test.py: corrected the **actual first failing** outdated Round020 CRC32 assertion to source-only CRC32C and explicit legacy CRC32 rejection, preserving source admission/decompression/origin proof checks.
- docs/handoff/zswapz/round022/agent2-evidence.md: actual source/testing/first failure and ABI limits.
- docs/testing_standards.md: distinct append-only Round022 Agent2 sections; Agent3 and all earlier standards untouched.
GitHub compare task publication SHA d12a2465 -> Agent2 c3 shows 4 fast-forward commits including Agent3's earlier one; Agent2's 3 publications were each non-force with expected-head recheck/readback. No extra branch/PR/fork/worktree or device mutation.

**Measured local rootless compiler tests** (no full local main checkout):
`git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main` EXIT 128 due github.com DNS failure.
`gcc -std=gnu11 -O1 -g -Wall -Wextra -Wconversion -Wshadow -Werror -fsanitize=address,undefined -fno-sanitize-recover=all -pthread /mnt/data/round022-agent2/producer-host.c -o /mnt/data/round022-agent2/gcc-asan && ASAN_OPTIONS=detect_leaks=1 /mnt/data/round022-agent2/gcc-asan`: build EXIT 0 / run EXIT 0.
Same flags `clang` 17 and `clang-asan`: build EXIT 0 / run EXIT 0. Tests are a **manually reconstructed source-equivalent** disabled-prototype excerpt with host mocked SHA and zpool, not actual loaded/kernel/physical operations. Repeated after the integrated CRC32C seed correction (kernel raw crc32c seeded ~0U and finalized bitwise NOT): GCC/Clang build/run both EXIT 0 again, CRC32C 123456789 standard vector = e3069283. The host original-page SHA fixture is independently derived with Python `hashlib.sha256`; C SHA engine is mocked. Full exact committed Python/Git diff --check NOT_RUN locally due no checkout. A local `git diff --no-index --check` on the C excerpt had zero whitespace diagnostics.

**First failures:** Initial local -Wshadow compile refused fixture-only globals, then fixed and passed. The first real exact-commit pinned Linux source run [43935827239](https://github.com/k1moradi/swapz/actions/runs/43935827239) reported source-controlled staging regression EXIT 1 because an older `pinned-linux-zswap-stored-entry-producer-test.py` assertion expected obsolete `crc32(0,...)` and absence of CRC32C. The corrected expectation now requires CRC32C and rejects CRC32 without weakening the production/stager gate. Corrective test commit alone was not watched by workflow path filters; a meaningful compile-disabled source-test assertion was added in watched compressed-handoff test to trigger exact-source [run 43936346468](https://github.com/k1moradi/swapz/actions/runs/43936346468), IN_PROGRESS at last observed check.

**Integration review:** a later separate published main commit [8ad53ee4](https://github.com/k1moradi/swapz/commit/8ad53ee4f57c5f8b272ca3ef4fadf1d8cd7cfbc8) descends from Agent2 c3 and corrected a further genuine CRC32C *seed/final-XOR interoperability mismatch*: raw kernel crc32c(0,..) does NOT equal production swapz_crc32c_bytes' ~crc32c(~0U,..). It updated the disabled producer and source tests, without enabling it. I did not overwrite this newer integration commit; locally retested the equivalent corrected seed vector and GCC/Clang sanitizer cases exit 0. Exact integrated source [pinned workflow run 43936506271](https://github.com/k1moradi/swapz/actions/runs/43936506271) IN_PROGRESS at last check; do not claim CI/KUnit success prematurely. Historical real pinned KUnit y/n five each PASS and matched build PASS remain independent source gates, never loaded proof.

**Safety:** No authorization or operation on physical SWAPSPACE2; original 4096-byte header/signature/UUID intact; compressed bytes never labeled RAW, existing RAW remains the full original uncompressed 4096-byte page. No module load, cgroup pressure, swap activation, null_blk or physical disk. No genuine booted compressed stored-entry to loaded DM committed WRITE or byte-exact original 4096 swap-in; Phase A BLOCKED, Phase B forced RAW bypass DISABLED and direct compressed handoff DISABLED. Coordinator retains CI acceptance/closeout.
MAIN_WRITE_LEASE_RELEASED


---

## Agent2 corrected CI update — [original comment](https://github.com/k1moradi/swapz/issues/139#issuecomment-6926360650)

message: SOURCE_UPDATE
round: "022"
agent: 2
source_sha: c3dc9a476ff5014df8a6863bdbfc7d356efb9098
integrated_main_sha_observed: 8ad53ee4f57c5f8b272ca3ef4fadf1d8cd7cfbc8
exact_run: https://github.com/k1moradi/swapz/actions/runs/43936346468
status: FIRST_CI_FAILURE_REPAIRED_ROOTLESS_SOURCE_STEPS_PASS; KBUILD_IN_PROGRESS
loaded: NOT_RUN
physical: NOT_RUN
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED

The source-exact pinned Linux prototype job on Agent2 SHA c3dc9a now reports **COMPLETED SUCCESS** for three relevant actual hosted steps:
1. `Run source-controlled rootless staging regression` (previous first-failure CRC32 expectation fixed).
2. `Run actual DM origin and compiled once-only foreground-commit source regressions`.
3. `Run disabled compressed handoff source/ownership negative regression` (compiles actual guarded staged producer C in GCC/Clang per committed test).
The workflow is now executing `Build modified Linux and matched source-linked swapz module for both configurations`; no final y/n build success is asserted yet. Separately integrated CRC32C-seed reconciliation at 8ad53ee4 is tested in local source-equivalent GCC/Clang ASan+UBSan and awaits its own exact source run https://github.com/k1moradi/swapz/actions/runs/43936506271. No compressed transport or physical/loaded action was enabled. This update supplements the previously posted REPORT_READY and does not change its verified publication SHAs.
