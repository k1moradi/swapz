# Round 015 — original worker REPORT_READY archive

Original authoritative GitHub reports: https://github.com/k1moradi/swapz/issues/132
Original bodies below are copied verbatim inside fenced blocks, not reconstructed summaries.
Agent 1 integrated the source blobs and all three independent testing-standard appendices in
https://github.com/k1moradi/swapz/commit/f716a5162a098742ec4bf7ab17b6a6a977bb75d4.

## Agent 2 — original comment 6911584157
GitHub original: https://github.com/k1moradi/swapz/issues/132#issuecomment-6911584157
Detached source commit: https://github.com/k1moradi/swapz/commit/7ab076291f3d7c6fd031c392a795aee3c667bc9c

~~~~~markdown
message: REPORT_READY
round: "015"
agent: 2
task_id: agent2-optional-pinned-zswap-compressed-producer
status: SOURCE_READY_PENDING_COORDINATOR_CI
source_sha: 7ab076291f3d7c6fd031c392a795aee3c667bc9c
source_parent_sha: 6d5b40198cfac271e100986fd8bd7637abf40541
source_tree_sha: d8d0a5533c8c8097bc48382f01fb7c632e5028b1
upstream_linux_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
upstream_zswap_blob: ae19e301fced7e357a4c7587dfdd6abb890b9163
phase_a: BLOCKED
phase_b: DISABLED
direct_compressed_handoff: DISABLED

# Agent 2 Round 015 — actual source-controlled compile-disabled Linux producer prototype

## Commit and scope
- **[Verified retrievable Git source commit](https://github.com/k1moradi/swapz/commit/7ab076291f3d7c6fd031c392a795aee3c667bc9c)**, with exactly one parent `6d5b40198cfac271e100986fd8bd7637abf40541`, Git tree `d8d0a5533c8c8097bc48382f01fb7c632e5028b1`. A detached Git commit only: no remote `main` move, branch, PR, worktree or fork. Agent 1 handles serial integration.
- `tests/tools/stage-pinned-linux-zswap-origin.py` — blob `eb33dd062cc45c0c5f004ee05c39c8d03c0eae62`, opt-in `--with-compressed-handoff-prototype`, exact anchored and compile-disabled C staging only in verified full-source `mm/zswap.c`. No default transform, original six-file `EDITS`, pinned exact source SHA/fingerprints, optional KUnit behavior, or ordinary provenance semantics changed.
- `tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py` — new blob `a88b1500ab888a52e10358ed4c82848b17c45a33`, host compilation of the exact guarded C bytes and negative lifecycle fixtures, including racing completion.
- `.github/workflows/phase-a-zswap-origin-prototype.yml` — blob `04dcac6bcf6b0e745e91c1ce81f142cc674ba6c1`, independently invokes rootless regression with fail-only bounded diagnostics, before unchanged matched Linux/module build, **without** passing experimental staging flag.
- `docs/testing_standards.md` — blob `670beb9428305485e1408f9af1912637b034a779`, append-only unique `## Round 015 — Agent 2 pinned zswap direct-payload source and lifetime` section, for Agent 1 to preserve alongside Agent 3 and 7 additions.

GitHub diff readback: four owned paths only; **added-line whitespace and conflict-marker scan PASS**, sole-parent identity PASS. Source-bound explicit negative/static checks: 10 invariants checked; 9 passed initially, one *checker false alarm* (C block begins with preserved explanatory comment before `#if 0`). Follow-up exact byte inspection confirmed one matching `#if 0` and the corresponding closing `#endif` (correct). Upstream pinned `mm/zswap.c` blob and unique writeback-source anchor confirmed; original six-file `EDITS` byte-equal to frozen version; original `docs/testing_standards.md` is exact prefix of append-only updated file.

## First actual upstream ownership/ABI blocker
Pinned `mm/zswap.c` `zswap_writeback_entry()` checks `entry == xa_load(tree, offset)` while the swap-cache folio is locked, then **decompresses** the stored entry to a 4096-byte folio, erases/frees the entry, and calls regular `__swap_writeout()/swap_write_submit()`. The entry owns a zsmalloc handle, and `zs_obj_read_sg_begin/end` exposes short-lived borrowed scatterlists; the pool has compressor name in `tfm_name`. Pinned BIO has **no independent authenticated compressed-representation metadata, codec/owned-buffer transport ABI, nor matching end-to-end swapz decoder/READ authority**. Cannot safely enable no-copy direct compressed transfer. The semantic BIO origin bit alone is *not* a compressed-format assertion.

## Real optional source implementation (off by default)
The optional pinned `mm/zswap.c` staging insertion is fully enveloped by:
`#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */`
through its matching `#endif`. It has no `REQ_ZSWAP_WRITEBACK`, no `submit_bio()` and no enabled direct I/O path. Ordinary decompression, 4096-byte swap writeback, semantic provenance and existing swap-in are preserved.

The guarded C source validates a locked folio and `xa_load` entry identity **before** dereferencing entry fields, exact `swp_entry_t` slot, `PAGE_SIZE == 4096`, 1..3568 compressed bytes, *actual pool codec identity* exactly `lz4` or `zstd` (unknown/incompatible rejected), a non-null source and allocation. It synchronously copies at most 3568 bytes out of borrowed zsmalloc SG to private allocated RAM, ends SG access, records CRC32 and keeps independent semantic origin and compressed representation. Bounded copy and CRC each cost O(payload length) CPU/cache bandwidth, plus a bounded allocated buffer. That tradeoff is intentional until an independent safe zero-copy ownership proof exists.

The address-stable descriptor keeps its allocation identity (self pointer and original allocation). Atomic lifecycle protects OWNED→CHECKING→SUBMITTED, SUBMITTED→RELEASED on success/error exactly once, or OWNED→RELEASED on pre-submit abort; clone, forged pointer, double completion, requeue after submission, early abort and corruption are rejected. Descriptor lifetime across competing callbacks must still be externally retained by any eventual real transport (none exists here). No asynchronous zpool borrowed pointer is retained.

## Measured tests (exact evidence class)
- `python3 -B /mnt/data/round015_agent2/tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py -v` — **exit 0, 5/5 PASS** using isolated rootless source-linked shim, not a full checked-out committed swapz Python stager. The compiled C fragment is the literal 6641-byte disabled source embedded in the actual GitHub stager blob, and its host code exercises the exact owner functions.
- Inside that rootless test: GCC and Clang with `-std=gnu11 -Wall -Wextra -Wconversion -Werror -fsanitize=undefined -fno-sanitize-recover=all -pthread -O1` — both **compile PASS, executable PASS**. Cases include unlocked/null/stale-entry and wrong slot, zero or 3569 length, incompatible compressor, allocation failure, stable copy after zpool buffer mutation, wrong CRC, forged allocation pointer, descriptor memcpy clone, double submit, requeue/early-abort refusal, **two concurrent competing completion callbacks with one release**, exact `zstd`/3568 length abort, and `lz4`/1 length successful completion.
- `python3 -m py_compile /mnt/data/round015_agent2/compact_compressed_test.py` — exit **0** on the locally mirrored exact new regression test Python source.
- GitHub final source diff plus pinned source structural comparisons — **PASS** on commit `7ab07629...`, four files only, source hashes and default `EDITS` unchanged.

**NOT_RUN / not claimed**: exact full committed swapz checkout's original `pinned-linux-zswap-origin-stage-test.py`; actual optional full pinned Linux stage into complete clean checkout (sandbox cannot obtain pinned Linux checkout); exact full-workflow YAML and embedded Bash parsing; repository-local `git diff --check` (GitHub added-line scan is *not* local git diff); hosted modified Linux Kbuild with opt-in C compilation, KUnit, matched loaded MM→BIO→DM positive payload transfer, 4096-byte consumer readback, GC/recovery, physical device tests. None of these follow from the rootless shim or Git commit alone. The new GitHub CI step will exercise the committed test after Agent 1 integrates the source and can expose any remaining environment/contract discrepancy.

## Qualification and ownership
Normal zswap fallback is unchanged. The guarded source is an intentionally **nonfunctional direct-BIO experiment** until a real owner-authenticated codec/representation transport, 4096-byte consumer decode and lifecycle authority can be jointly compiled and loaded-verified. Phase A remains BLOCKED, Phase B RAW bypass stays DISABLED, and direct-compressed handoff stays DISABLED. No live swap, mapper, module or physical operations performed.

**Agent 2 report delivered.** No shared `main` lease exercised; Agent 1 exclusively integrates this detached frozen-parent commit.
~~~~~


## Agent 3 — original comment 6911437687
GitHub original: https://github.com/k1moradi/swapz/issues/132#issuecomment-6911437687
Detached source commit: https://github.com/k1moradi/swapz/commit/c79d8c826c1ac44943959cc115fd1c4409ed5350

~~~~~markdown
message: REPORT_READY
round: "015"
agent: 3
task: agent3-swapz-guarded-compressed-consumer
status: SOURCE_READY_PENDING_COORDINATOR_CI
source_commit_sha: c79d8c826c1ac44943959cc115fd1c4409ed5350
frozen_parent_sha: 6d5b40198cfac271e100986fd8bd7637abf40541
final_task_publication_sha: 8f6a21a3e37c2a9802f7704f3a7915435172620d
production_compressed_handoff: DISABLED
phase_a: BLOCKED
phase_b: DISABLED
module_or_loaded_qualification: NOT_RUN
remote_main_updated: false

# Agent 3 — Round 015 actual guarded compressed consumer/readback source

**Source commit:** https://github.com/k1moradi/swapz/commit/c79d8c826c1ac44943959cc115fd1c4409ed5350 — verified via GitHub commits and compare endpoints, sole parent `6d5b40198cfac271e100986fd8bd7637abf40541`, exactly one commit ahead, only five Agent 3-owned paths, no added trailing whitespace. Remote `main` remained at the task-publication SHA `8f6a21a3e37c2a9802f7704f3a7915435172620d` when verified. No branch, PR, fork, new worktree or remote-main push.

## Actual source changes and Git blob identity

| Owned path | Git blob |
| --- | --- |
| `src/kernel/zswap-direct-handoff.h` (NEW, disabled by default) | `864abf9a12071b98f5c157a44f4ed0c04d4a594c` |
| `tests/runtime/native/codec/zswap-direct-handoff.c` (NEW, compiled and executed) | `e9b1010ab5eb304fa2f9cff247171bae60ab7aac` |
| `.github/workflows/product-codec.yml` | `5c4dea02d013039b19d94f42b3edf71f3ec5b5bf` |
| `docs/coding_standards.md` (unique append-only section) | `9e5b37d1ce14b34139c6085c707c18a8f46ecfd9` |
| `docs/testing_standards.md` (unique append-only section, Agent 1 to reconcile with other workers) | `88c6d15904b72902c5430d7c89274352f584a8d6` |

**Implementation:** Kernel-compatible GNU C11 header holds a separate volatile-RAM versioned descriptor (not existing swapz RAW or LZ4/delta64). It checks independent semantic origin `0|1`, representation `0|1`, codec `UNKNOWN|ZSWAP_LZ4|ZSWAP_ZSTD`, exact logical 4096-byte page and compressed size `1..3568`, immutable-owned payload claim, independent logical-page/generation/record identity, matching decoder codec/pool/dictionary/generation and nonzero expected SHA-256. Readback checks real callback CRC32C on compressed payload *before* decode, requires exactly 4096 decoded bytes, independently verifies page SHA-256, and only then copies into output. Error paths preserve output and clear private scratch; kernel build uses `memzero_explicit`. Neither the header nor fixture allocates/publishes a physical extent or completes I/O. **`SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED 0U`** is compile-time asserted by the native fixture.

**No change to `src/kernel/dm-target.c`:** The frozen source does not contain a qualified actual zswap compressed producer-to-DM buffer-ownership, codec identity and decoder release interface. A misleading compile-disabled reference there could imply integration safety; the isolated tested kernel header is the complete independent source contract for this round. No new active codec, public knob, on-media record or partition-header change.

**Actual source-linked CI change:** Existing `product-codec.yml` `exact-c` matrix already runs on x86_64 and ARM64. Its new step invokes real `gcc` and `clang` on the new checked-in C fixture with `-std=gnu11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow -Wformat=2 -Wstrict-prototypes -fsanitize=undefined -fno-sanitize-recover=all`, links native test-only `libcrypto` (prerequisite `libssl-dev` added), and executes both resulting binaries. No kernel production OpenSSL dependency.

## Commands and measured results — actual local code

Working source was created in `/mnt/data/round015_agent3/`; Git blob SHA for each new C/header source was computed locally and verified identical after GitHub blob upload.

- `gcc -std=gnu11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow -Wformat=2 -Wstrict-prototypes -fsanitize=undefined -fno-sanitize-recover=all -o gcc-direct-handoff-test tests/runtime/native/codec/zswap-direct-handoff.c -lcrypto` — **exit 0**; `./gcc-direct-handoff-test` — **exit 0**, `PASS native_source_header synthetic_readback=2 rejected=30 authority_publications=0`.
- Same exact options with `clang` and `clang-direct-handoff-test` — **compile exit 0, execution exit 0**, same **2 positive / 30 negative**, zero authority publications.
- `bash -n /mnt/data/round015_agent3/ci-step.sh` — **exit 0**, followed by `bash ./ci-step.sh` from local source tree — **exit 0**, built/reran GCC+Clang tests with both PASS. This is the CI shell command body transcribed from the committed new workflow step; not a completed hosted workflow run.
- `git hash-object src/kernel/zswap-direct-handoff.h tests/runtime/native/codec/zswap-direct-handoff.c` — **exit 0**; exact SHA values above. GitHub REST commit/compare — **PASS**, sole frozen parent, five expected changed paths, no added trailing whitespace.
- `git diff --no-index --check /dev/null <new_source_file>` — **exit 1** (expected for differing/new files); **no whitespace diagnostics**. This is not a claim that `git diff --check` on an entire repository was executed.

**Negative tests:** unrecognized/unsupported codec and numeric enums; ordinary/invalid semantic origin; full-page RAW substitution; wrong logical length, zero or over-limit compressed size, null and borrowed payload; incorrect descriptor version; stale read generation/GC source-record identity and wrong logical address; missing/mismatched pool, dictionary and codec generation; unsupported/mismatched decoder; absent integrity callback; altered compressed CRC/data; missing/fake-nonzero expected page SHA; short/expanding decode, decoder failure and wrong plaintext. Each negative verified the output page unchanged, scratch zeroed and no authority publication. Both positive callback decodes use **test-owned deterministic four-byte inputs**, OpenSSL SHA-256 and real CRC32C, compare the full 4096-byte original page and zero scratch.

**Unavailable / NOT_RUN:** Full frozen checkout was not available in the local runtime and GitHub network cloning failed with `Could not resolve host: github.com`. Therefore `python3 -B tests/runtime/native/zswap-origin-producer-consumer-abi-test.py -v`, `make -C tests/suites SANITIZE=1 test-all`, complete-tree `git diff --check`, entire committed workflow YAML parse and the actual hosted x86_64/ARM64 CI job are **NOT_RUN**, not PASS. The new CI shell fragment and exact source text were reviewed but the full workflow execution and validation belong to Agent 1's serial integrated-source CI.

**First local test failure:** NONE in GCC+Clang compiled/UBSan rootless fixture and CI-body rerun. **Qualification blocker:** There is no reviewed actual originating zswap compressed-buffer lifetime/matching LZ4 or ZSTD decoder API in the frozen consumer. The two synthetic decoders are NOT real Linux codec-interoperability evidence. No actual kernel module build, matched source producer/KUnit, loaded zswap stored-entry eviction, 4096-byte swap-in/readback, GC/reuse, physical media or swap device operation was run.

**Safety gates:** ordinary 4096-byte writeback and byte-exact swap-in remain unchanged; compressed direct transport and Phase B forced RAW remain disabled. Phase A stays BLOCKED until genuinely paired and loaded acceptance. Agent 1 must reconcile the shared append-only standards and integrate this worker commit serially without force, then run source-exact hosted CI.
~~~~~


## Agent 7 — original comment 6911439103
GitHub original: https://github.com/k1moradi/swapz/issues/132#issuecomment-6911439103
Detached source commit: https://github.com/k1moradi/swapz/commit/893c967269ae52cb16ce13b5c62f75b7adf70f1a

~~~~~markdown
message: REPORT_READY
round: "015"
agent: 7
task_id: agent7-zswap-swapz-cooperative-scheduling
status: SOURCE_READY_PENDING_COORDINATOR_CI
frozen_engineering_source_sha: 6d5b40198cfac271e100986fd8bd7637abf40541
task_publication_sha: 8f6a21a3e37c2a9802f7704f3a7915435172620d
source_commit_sha: 893c967269ae52cb16ce13b5c62f75b7adf70f1a
source_commit_url: https://github.com/k1moradi/swapz/commit/893c967269ae52cb16ce13b5c62f75b7adf70f1a
source_parent_sha: 6d5b40198cfac271e100986fd8bd7637abf40541
modified_files:
  - src/kernel/window-policy.h
  - tests/runtime/native/io/window-policy.c
  - docs/testing_standards.md
evidence_class: rootless-compiled-source-excerpt + read-only-GitHub-commit-verification
tests:
  - command: "gcc -std=gnu11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow -pedantic /mnt/data/round015-agent7-policy-local.c -o /mnt/data/round015_gcc_warnings && /mnt/data/round015_gcc_warnings"
    exit_code: 0
    test_groups: 5
  - command: "clang -std=gnu11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow -pedantic /mnt/data/round015-agent7-policy-local.c -o /mnt/data/round015_clang_warnings && /mnt/data/round015_clang_warnings"
    exit_code: 0
    test_groups: 5
  - command: "gcc and clang; identical strict flags with -fsanitize=undefined -fno-sanitize-recover=all; compile and execute separately"
    exit_codes: [0, 0]
    test_groups_each: 5
  - command: "gcc and clang; identical strict flags with -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer; compile and execute separately"
    exit_codes: [0, 0]
    test_groups_each: 5
  - command: "GitHub exact frozen-parent compare + Git data commit parent verification"
    exit_code: 0
    modified_file_count: 3
    added_diff_lines: 551
    trailing_whitespace_additions: 0
  - command: "make -C tests/suites SANITIZE=1 test-lower-io"
    exit_code: NOT_RUN
    reason: "Full frozen Git checkout unavailable locally; exact committed native executable requires coordinator CI"
  - command: "git diff --check <frozen source>..<source commit>"
    exit_code: NOT_RUN
    reason: "No local complete Git repo; checked actual GitHub commit unified diff for trailing whitespace instead"
  - command: "Matched patched Linux Kbuild/KUnit; loaded zswap eviction+4096-byte swap-in/readback; physical"
    exit_code: NOT_RUN
negative_controls:
  malformed_or_forged_metadata_and_fences: 34
  executed_under_compiler_configurations: 6
first_failure: "During local harness development, missing old raw-hand stub caused compiler failure, and a test erroneously expected direct compression with UNKNOWN origin. Both test-harness failures were repaired before all six final runs. No final compiler/sanitizer failure."
release: "Phase A BLOCKED; Phase B RAW bypass DISABLED; direct compressed zswap handoff DISABLED"

# Round 015 Agent 7 — source-committed default-unused cooperation policy

**Final retrievable one-parent commit:** [893c967269ae52cb16ce13b5c62f75b7adf70f1a](https://github.com/k1moradi/swapz/commit/893c967269ae52cb16ce13b5c62f75b7adf70f1a), solely descended from frozen engineering source `6d5b40198cfac271e100986fd8bd7637abf40541`. GitHub reports only the three agent-owned paths: **240 added header lines, 239 added native-test lines, and 72 appended testing-standards lines, with no deletions**. The prior unattached draft `0a2cb07170cc82f22260d947943b4ab168e01eb5` is superseded and **must not be integrated**. No remote branch, PR, fork, extra worktree or remote-main update.

## Implementation

The real `src/kernel/window-policy.h` now provides an *additive, default-unused* `swapz_window_zswap_cooperative_choose()` static-inline policy and fixed-size input/cost records. Existing `swapz_window_raw_hand_pays()`, all previously shipped window primitives, live compression/RAW routing, 64-slot authority and worker logic remain unchanged. No callsite invokes the new helper in production. There is no device access, allocation, asynchronous task, new parameter, mutex, BIO mutation or early completion.

1. **Fail-closed provenance/representation.** Direct compressed path is possible *only hypothetically* if separately authenticated stored-entry writeback, compressed representation, 4096 original logical bytes, nonzero length ≤3568, exact originating zswap LZ4/ZSTD decoder identity and availability, verified digest, owned immutable producer buffer, no preparation/fence and explicit *future* `direct_handoff_qualified` all hold. That flag is never set by production. Ordinary or unknown origin, fake REQ_SWAP/codec, initial store rejection, unverified compressed payload, borrowed pointer, mismatched or failed decoder always return existing normal compression. Zswap's stored RAM cache is not swapz committed foreground data.
2. **Emergency full-page RAW is separate.** Only a future opt-in, truly imminent reclaim deadline, `representation=FULL_PAGE`, independently verified immutable **uncompressed 4096-byte** snapshot, no in-flight prep and no FUA/flush/GC/teardown/error/reissue fence can return RAW. A zswap compressed blob is *never* treated as full-page RAW. Invalid/missing readiness falls back to ordinary compression, without inventing a secondary queue or waiting for other agents.
3. **Bounded 4/8/16KiB and cold-read cost.** No heap, heap pointer, unbounded iteration or locks. The function computes marginal actual 4096-block lower WRITE bytes and newly added lower requests for an already-planned extent (a fitting candidate can incur 0 new requests), plus measured per-block/request latency, hypothetical zswap decompression/swapz compression CPU, bounded CPU pressure and 0..64 anticipated cold READs with decoder costs. It uses saturated add/multiply, quotient/remainder CPU-pressure scaling to avoid overflow underestimation, and guarded extent subtraction; equality/saturation defaults to normal compression. Source-device *class* is not inferred from labels (NVMe/SD); only explicit service samples are inputs. The policy does not provide a benchmark or guarantee future pack geometry.
4. **Two decisive deterministic estimates** (synthetic, not device measurements):
   - Empty extent: compressed zswap 1024 bytes, estimated swapz 1536 bytes, 1 future READ, 100,000 ns/physical 4KiB block + 15,000 ns/request, CPU 500,000 ns decompress + 700,000 ns compress: **normal 1,430,500 ns vs direct 231,500 ns**, hypothetical direct choice only with full source proof and future opt-in.
   - Planned 8KiB extent already holding 7200 bytes: normal 800-byte candidate fits with **0 incremental lower bytes/requests**, direct 2500-byte candidate spills another 4096 physical bytes/1 request. Slow 10,000,000 ns/block + 1,000,000 ns/request and maximum CPU-pressure input: **normal 6,000 ns vs direct 11,000,000 ns**, choose safe normal even under high CPU pressure and with no imminent deadline.
   - The native fixture also exercises 4KiB/16KiB boundaries, LZ4/ZSTD, 0/3568/3569 length, zero timing samples, malformed enum/size/codec, absent decoder/digest/owned buffer, repeated cold reads and six independent fence conditions.

## Actual measured tests and limits

Six separate strict compiler configurations executed successfully on Linux against the **byte-exact newly committed C helper and five test functions** in a standalone no-device test translation unit. Tested GCC and Clang, each under plain warning-clean build, UBSan, and combined ASan/UBSan. Each executable printed `ROUND015_AGENT7_COOPERATIVE_POLICY_TESTS_PASS=5` and returned **0**. The fixture contained 34 deliberate negative source/input cases. The helper bytes are independently confirmed by Git blob SHA `84041249ee2c8a2c363ebee71ac5880928de0c42`; the five test-function bytes by Git blob `48792e5aedb31af9ea025791a7541742ce9bb6db`. These exact snippets are in the actual committed files, alongside the unchanged original tests and original `swapz_window_raw_hand_pays` function. Local fixture stubs only `SWAPZ_BLOCK_BYTES=4096`, `SWAPZ_MAX_COMPRESSED=3568`, `SWAPZ_MAX_RECORDS=64` (confirmed against the pinned real `src/kernel/codec.h`) and includes the original raw predicate's exact body.

**This is NOT execution of the entire 39KiB prior `tests/runtime/native/io/window-policy.c` plus the new source in its full repository environment.** The complete `make -C tests/suites SANITIZE=1 test-lower-io`, official owner `make test`, exact integrated hosted CI, Linux Kbuild, actual compressed transport/read-side decoder, physical media and authenticated loaded swap-in remain **NOT_RUN**. Inspection of `tests/suites/Makefile` shows there is no `test-native` goal; the existing supported comprehensive lower-I/O target is `test-lower-io`. A read-only GitHub commit unified-diff review found **0 trailing-whitespace additions across 551 inserted lines**, but the actual local `git diff --check` command was not run because the complete frozen repo was not mounted in this execution environment.

The main source remains unchanged, and workers 2/3 have no dependency on this policy. **Agent 1** should independently review the source commit, append this uniquely headed `docs/testing_standards.md` section alongside the other workers' distinct sections without dropping any, then run the entire native test and sanitizer targets and exact-source hosted checks before considering a future producer/consumer integration. Even a full native PASS would **not** authorize compressed handoff or physical trial.

**Disposition:** `SOURCE_READY_PENDING_COORDINATOR_CI`; Phase A **BLOCKED**; Phase B forced RAW **DISABLED**; compressed zswap→swapz handoff **DISABLED**.
~~~~~

