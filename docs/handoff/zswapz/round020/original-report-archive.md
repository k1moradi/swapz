# Round 020 — original GitHub worker handoffs, verbatim

Both original issue comments are reproduced exactly below. Worker claims about source/regressions are not automatically runtime/physical qualification.

## [Agent 2 REPORT_READY](https://github.com/k1moradi/swapz/issues/137#issuecomment-6922234120)

message: REPORT_READY
round: "020"
agent: 2
status: SOURCE_PUBLISHED_MAIN; ROOTLESS_EXACT_C_COMPILER_PASS; HOSTED_EXACT_CI_IN_PROGRESS; PHASE_A_BLOCKED
published_main_sha: c023ecbf6ca3f07b06142abffbd5636663375c9f
sole_parent_sha: de5bc09e80484c60d003e860732ecb736a6c2f0b
publication: NON_FORCE_EXPECTED_HEAD_FAST_FORWARD_VERIFIED
commit_url: https://github.com/k1moradi/swapz/commit/c023ecbf6ca3f07b06142abffbd5636663375c9f
evidence_note: https://github.com/k1moradi/swapz/blob/c023ecbf6ca3f07b06142abffbd5636663375c9f/docs/handoff/zswapz/round020/agent2-evidence.md
branch_policy: ONLY_MAIN_NO_PR_NO_FORCE
loaded: NOT_RUN
genuine_eviction_loaded: NOT_RUN
physical_trial: NOT_RUN
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED

### Actual source implementation (seven paths)
- `tests/tools/stage-pinned-linux-zswap-origin.py`: exact source Git-blob identity gate for original pinned Linux c339f401 `zswap_decompress`, edited `zswap_writeback_entry`, LRU shrinker and stored-entry admission `zswap_store_page`. Full pinned upstream mm/zswap.c Git blob already checked before staging. Typed bounded fail-closed exact-fn drift/duplicate/order rejection, including compile-disabled optional compressed source.
- `tests/runtime/native/pinned-linux-zswap-stored-entry-producer-test.py`: immutable upstream producer function bodies in rootless source fixture, exact Git blob comparisons, adversarial mutation refusals, and compiler-executed original staged `zswap_writeback_entry()` with real compiled `bio_is_zswap_stored_writeback()`.
- `tests/runtime/native/fixtures/round020-zswap-producer-prologue.h` and `tests/runtime/native/fixtures/round020-zswap-producer-epilogue.h`: explicit host mocks; runtime positive original-sized 4096 carrier and stale xarray identity, failed decompression, failed swap-device/folio, invalid payload size, READ/non-SWAP/unknown-origin negatives. Decoder and actual downstream I/O are MOCKED, never loaded/physical.
- `tests/runtime/native/pinned-linux-zswap-origin-stage-test.py`: runs new complete test from the already-existing pinned rootless workflow suite, retaining other tests and actual KUnit gate.
- `docs/handoff/zswapz/round020/agent2-evidence.md`: first-cause/evidence classes and limitations.
- `docs/testing_standards.md`: unique append-only Round020 Agent2 section, preceding content unchanged.

### Measured local tests and first-failure evidence
Local main checkout: NOT_AVAILABLE; `git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main` exited 128 (github.com DNS unavailable); GitHub Git Data source and main ref verified successfully. No new branch/worktree.
- GCC 14.2.0: `gcc -std=c11 -O1 -g -Wall -Wextra -Werror -Wconversion -Wshadow -fsanitize=undefined -fno-sanitize-recover=all /mnt/data/round020-agent2/causality.c -o /mnt/data/round020-agent2/c-gcc && /mnt/data/round020-agent2/c-gcc`: EXIT 0.
- Clang 17: equivalent flags and exact C fixture `-o /mnt/data/round020-agent2/c-clang && /mnt/data/round020-agent2/c-clang`: EXIT 0.
- The local real-original staged `zswap_writeback_entry()` excerpt plus its terminating newline had **Git blob eab8cd08a630aad73f6d20d48935b83428ebfac4**, the pinned staged target, confirmed with `git hash-object --stdin`. Independent GitHub blob verification checked all 4 upstream functions and staged writeback as expected.
- Negative mutation: reversed decompression condition compiled (GCC EXIT 0), then runtime SIGABRT assertion (expected), preventing false positive. Wrong origin-tag assignment to 0 also compiled EXIT 0 and runtime SIGABRT assertion (expected). First observed failures are these **deliberate source mutations**, not a genuine kernel or device failure.
- Exact committed Python full stage suite, rootless producer module, full repository `git diff --check`, actual new-commit KUnit y/n: NOT_RUN locally due unavailable checkout. The existing pinned GitHub workflow and native/source CI were auto-triggered on exact commit and initially **IN_PROGRESS**: https://github.com/k1moradi/swapz/actions/runs/43907023544 and https://github.com/k1moradi/swapz/actions/runs/43907027561 . Do not upgrade to CI PASS before completion.

### Prior genuine KUnit vs missing loaded provenance
Original source-bound pinned modified Linux KUnit `CONFIG_ZSWAP=y` AND `n`, each 5 distinct actual no-skip TAP PASS and 4/3 object hashes: https://github.com/k1moradi/swapz/actions/runs/43897628379 ; matched modified Linux/module **build only** PASS: https://github.com/k1moradi/swapz/actions/runs/43897628284 . Neither proves a stored entry actually reached loaded DM. No authenticated live zswap-stored eviction, successful actual DM writeback or original byte-exact 4096 swap-in is available. Loaded/physical NOT_RUN. Existing swapz RAW remains the **original uncompressed 4096 bytes**, never the incompatible disabled compressed CRC32 prototype. Phase A BLOCKED; Phase B forced RAW bypass and direct compressed handoff DISABLED. No privileged/module/pressure/swap/physical-device operations.
MAIN_WRITE_LEASE_RELEASED


---

## [Agent 3 REPORT_READY](https://github.com/k1moradi/swapz/issues/137#issuecomment-6922312371)

message: REPORT_READY
round: "020"
agent: 3
task_id: agent3-matched-loaded-ram-readback
status: SOURCE_PUBLISHED_ENVIRONMENT_NOT_QUALIFIED
source_commit_sha: c7399664b1fcda0e951195fb8ed8f632cda70a17
remote_main_commit_sha: c7399664b1fcda0e951195fb8ed8f632cda70a17
source_commit_url: https://github.com/k1moradi/swapz/commit/c7399664b1fcda0e951195fb8ed8f632cda70a17
sole_parent_sha: c023ecbf6ca3f07b06142abffbd5636663375c9f
task_publication_sha: de5bc09e80484c60d003e860732ecb736a6c2f0b
loaded_stored_entry: NOT_RUN
readback_4096: NOT_RUN
authorized_ram_device_mutation: NONE
physical_trial: NOT_RUN
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED
fast_forward_non_force: true

# Agent 3 — Round 020 real source delivery / matched loaded-DM admission evidence

**Published directly to main:** [source commit `c7399664b1fcda0e951195fb8ed8f632cda70a17`](https://github.com/k1moradi/swapz/commit/c7399664b1fcda0e951195fb8ed8f632cda70a17). The GitHub connector applied `update_ref` with `branch_name=main`, `force=false`, **expected prior HEAD `c023ecbf6ca3f07b06142abffbd5636663375c9f`**, and returned `success=true`. A subsequent REST read verified actual remote `refs/heads/main == c7399664b1fcda0e951195fb8ed8f632cda70a17`, sole parent `c023ecbf6ca3f07b06142abffbd5636663375c9f`, exactly one commit ahead and six authorized paths; no branches/PRs/worktrees/force pushes. Agent 2 independently pushed first; my work was recreated on its updated head. Its source changes and its separate Round 020 testing standards appendix are preserved byte-for-byte. Reran all available new test paths after this rebase.

**Six source-controlled changes (no production C changed):**
- NEW `tests/runtime/native/zswap-origin-loaded-evidence-contract.py`, exact locally tested blob `b24678da51f44cc5012c83ad959c52626eae9729`;
- `tests/runtime/native/zswap-origin-owned-ram-qualification.py`, blob `5e0111062a6f0c04ac519216f62edcd16e9b8cc6`;
- `.github/workflows/phase-a-zswap-origin-prototype.yml`, blob `078e364549ba358cd4e43d92db6aa89ab572a155`;
- `tests/runtime/native/pinned-linux-origin-paired-module-test.py`, blob `ba441a35ff887dc766ca96d30d4ab6dddb610a7d`;
- `docs/testing_standards.md`, rebased **append-only** shared blob `4f8b14c78710786ebd114ed40c27b72af4291854`, retains both Agent 2 and Agent 3 independent Round 020 sections;
- NEW [`docs/handoff/zswapz/round020/agent3-evidence.md`](https://github.com/k1moradi/swapz/blob/c7399664b1fcda0e951195fb8ed8f632cda70a17/docs/handoff/zswapz/round020/agent3-evidence.md), blob `862fa8d1cb9aa2c62e7ffa6e251029c485372045`.

## Actual engineering / first source finding

1. **One-to-one upper successful WRITE ACK correction.** The frozen `compare_offline_samples` accepted *any positive* `upper_write_completed_ok` delta despite requiring exactly one authentic-origin admission and foreground authoritative commit. That can mask another writer and cannot establish per-page causality. I changed only that comparator to require **delta exactly 1**, updated zero-ACK rejection and added a new double-ACK negative. The previous 4096-byte original page/independent SHA-256, exact readback bytes, status origin carrier, exactly-one admitted/committed delta and endio/upper error checks are retained. Even a passing offline check remains UNTRUSTED.
2. **Actual independently checked but non-authorizing loaded candidate.** New standard-library CLI `--self-test` or `--inspect-candidate --expected-source-sha SHA` strictly validates a bounded (8192-byte) duplicate-free JSON claimed kernel/boot, exact pinned Linux SHA, module source/disk/loaded SHA256, matching vermagic/live status, compiled carrier, original-page SHA256, nonzero generation/source record, exclusive owner-controlled ephemeral `brd` RAM, owner permission/cleanup, deadline/pressure bounds and genuine stored eviction→MM REQ_SWAP BIO→DM commit→upper ACK→4096 swap-in claimed events. It also checks *read-only* actual boot ID, uname release and sysfs module existence against claims. These sources **cannot independently prove** the matched *loaded* module bytes, ownership, authenticated MM event, cleanup, or original page. Thus **even a fully self-consistent all-positive manifest always returns `ENVIRONMENT_NOT_QUALIFIED`, exit 2**, with explicit `LOADED_STORED_ENTRY=NOT_RUN` and `4096_READBACK=NOT_RUN`. No elevated/positive backend, kernel, mapper, cgroup, host swap or device action exists.
3. **Exact CI fail-closed gates.** Existing source-linked `phase-a-zswap-origin-prototype.yml` now triggers on the new checker, executes its real 33-case suite before expensive matched Kbuild, and explicitly requires an empty/untrusted candidate to exit 2 with categorical first failure and all NOT_RUN/disabled labels. Any unexpected exit, lost source self-test, missing trigger, or missing refusal marker fails. The full pinned y/n gcc W=1 Linux exporter / Module.symvers / linked dm-swapz.ko Kbuild step is **byte-for-byte unchanged**. The paired artifact verifier (staged source/hash, config, compiled marker, ELF/modinfo/vermagic) is unmodified, with three additional source-bound negative workflow mutation methods.

## Exact measured local commands / exits

- `PYTHONWARNINGS=error python3 -B zswap-origin-loaded-evidence-contract.py --self-test` — **exit 0, 33/33 PASS** (initial 0.008s, post-rebase rerun 0.006s), real file matching committed Git blob `b24678da51f44cc5012c83ad959c52626eae9729`. Negatives cover wrong pinned/boot/module/source SHA, kernel/vermagic mismatch, missing origin carrier, false owner/missing cleanup/shared/non-RAM backing, bad pressure/deadline bounds, stale page/record identities, fabricated events, malformed/duplicated JSON, symlink/FIFO, and mismatched read-only observed boot/module status.
- `python3 -B -m py_compile zswap-origin-loaded-evidence-contract.py` — **exit 0**, initial and post-rebase.
- `bash -n ci-loaded-candidate-step.sh` — **exit 0** for a verbatim locally copied new YAML step body.
- `RUNNER_TEMP=... GITHUB_SHA=<rechecked-main-sha> bash ci-loaded-candidate-step.sh` — **exit 0**, initially and after Agent 2's main advancement. Internally ran all 33 tests then deliberately observed candidate inspection **exit 2** `first_cause=manifest_file_type_or_size`, `LOADED_STORED_ENTRY=NOT_RUN`, `4096_READBACK=NOT_RUN`, `PHASE_A=BLOCKED PHASE_B=DISABLED DIRECT_COMPRESSED=DISABLED`. No privileged action.
- Synthetic all-positive self-consistent candidate file with `--inspect-candidate`: **exit 2** `first_cause=actual_boot_id_mismatch`, NOT_RUN markers, no certification or module/mapping/device operation.
- `git hash-object zswap-origin-loaded-evidence-contract.py` — **exit 0**, `b24678da51f44cc5012c83ad959c52626eae9729`; exact GitHub blob verification PASS.
- Structural source checks against actual GitHub blobs — **18/18 PASS** (new source trigger/real self-test/exit-2 refusal; existing Kbuild and real-byte module verifier byte identity; exact-one upper ACK; 33 actual Python test-method declarations). These 18 are *static source assertions*, not execution of an existing Python suite.
- GitHub REST commit/compare source audit — **PASS**, exactly 6 paths, sole newer-parent, one ahead/zero behind, **zero added trailing whitespace**; normal non-force expected-head update and subsequent remote-main verification — PASS.

**Unavailable / NOT_RUN:** Entire modified pre-existing owned-RAM test script `--self-test` (now 26 methods, including the new double-ACK), entire paired-module `--self-test` (three new workflow mutation cases), existing consumer/producer ABI source tests, complete `make test`/native GCC/Clang UBSan/real module Kbuild/W=1/W=2, complete updated YAML parse and all embedded scripts, full local-checkout `git diff --check`, exact integrated new-SHA hosted CI/KUnit, real loaded matched boot+module, actual stored compressed-entry eviction via MM→REQ_SWAP BIO→loaded DM, upper success, byte-exact original 4096 swap-in, GC/teardown/owner RAM and physical trial. Full local Git checkout was unavailable: `git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main` failed **exit 128** `Could not resolve host: github.com`; I used GitHub connector normal Git objects, never represented it as local git push. Agent 1 owns hosted CI review; no new CI success is claimed.

**Earlier independent source/build successes only:** [pinned KUnit y/n run #43897628379](https://github.com/k1moradi/swapz/actions/runs/43897628379) and [pinned modified-Linux matched module run #43897628284](https://github.com/k1moradi/swapz/actions/runs/43897628284) both completed **success**, but at older `01edd17eed37efa312523324b1210efdd46be144`, not the above Round 020 SHA, and not a loaded genuine zswap writeback/swap-in. First finding was the excess upper ACK acceptance and it is corrected in source; first expected runtime refusal is `manifest_file_type_or_size` (exit 2), not a positive trial.

**Safety:** Phase A **BLOCKED**, Phase B forced RAW bypass **DISABLED**, direct compressed handoff **DISABLED**. Normal swapz RAW remains original **uncompressed** 4096-byte page. This task performed NO unauthorized kernel boot/load, cgroup pressure, system swap/mapper, owned RAM block or physical partition mutation. See [per-agent detailed evidence](https://github.com/k1moradi/swapz/blob/c7399664b1fcda0e951195fb8ed8f632cda70a17/docs/handoff/zswapz/round020/agent3-evidence.md).

