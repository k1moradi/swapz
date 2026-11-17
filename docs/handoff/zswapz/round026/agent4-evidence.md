# Round 026 — Agent 4: executed pinned-Linux UML BIO KUnit verdict

Official ROUND_OPEN: https://github.com/k1moradi/swapz/issues/143#issuecomment-6942777129

Frozen task SHA: \`3219d1b6d9eb43c27778e72836c6b7627d845650\`.
Engineering code baseline: \`0dfcd58b2a993d04de50256ae9e49577718d3e99\`.
Exact pinned upstream: \`torvalds/linux\`
\`c339f4010dea8b0d754f84ace70cd1b089878ef8\`.

## Source-backed ownership assessment

The actual pinned Linux \`block/bio.c\` original \`__bio_clone\` shares the
BIO iterator and \`bi_io_vec\`, but no typed compressed owner. The
original \`bio_init_clone\` error path calls \`bio_uninit\`;
\`bio_split\` uses \`bio_alloc_clone\` and creates TWO 2048-byte
ordinary BIO halves from one original 4096-byte upper \`REQ_SWAP\`.
Original \`bio_reset\` calls \`bio_uninit\` and clears the reset region,
\`bio_reuse\` preserves \`bi_private\`/completion, while
\`bio_prepare_reissue\` preserves the BIO but cannot magically
reauthenticate a prior source slot allocation epoch. Blind pointer
copying, guessing a source epoch from slot number or using end-I/O's
\`bi_private\` as an owned compressed descriptor would risk UAF,
ABA, double release or wrong original-page attribution. The existing
Round025 opt-in descriptor has independent bytes, refcount, exact
allocation capacity, canonical CRC32C and a digest field but
still lacks source-authenticated allocation epoch/store SHA and
DM logical-generation/GC/ACK ingress.

## Agent 4 implementation only

Preserve pinned upstream source blob SHA-1 gates, exact two-file
\`include/linux/blk_types.h\`/\`block/bio.c\` staging, and default-OFF
\`SWAPZ_ROUND025_SIDEBAND_CI_ONLY\` build flag. Add KUnit execution
coverage for original clone, real split, reuse/reset, reissue,
bad owned-capacity/CRC/codec/epoch, failed clone cleanup and
dead-ref non-resurrection. Source code has no production admission
caller and \`swapz_ci_live_compressed_admit\` returns
\`-EOPNOTSUPP\` regardless of supplied epoch. No variable compressed
bytes are inserted into the ordinary 4096-byte BIO.

A NEW independent strict KUnit evidence parser checks **actual**
pinned kernel \`tools/testing/kunit/kunit.py\` JSON together with its
raw \`test.log\` KTAP, not source string assertions: one suite, exactly
seven named cases, explicit PASS for all, no skipped/errored/crashed
or missing events, source UML \`arch=um\`, and no kernel panic or
sanitizer diagnostics. Self-tests inject missing suite/case,
SKIP/FAIL/ERROR, JSON count mismatch, duplicates, wrong arch,
empty/faked log, kernel panic, KASAN/UBSAN. An actual kernel KUnit
boot that fails, times out, panics, or never emits cases is
\`KUNIT_EXECUTED=NOT_QUALIFIED\`, **not** a safe success.

\`.github/workflows/phase-a-zswap-sideband.yml\` retains the
existing exact pinned Linux original-Kbuild GCC CONFIG_ZSWAP=y/n
plus KUnit suite **compile** job, and adds a second, separate
\`pinned-bio-uml-executed-kunit\` job. The added job installs
hosted Ubuntu compiler/tool prerequisites, verifies exact SHA,
runs GCC/Clang ASan/UBSan native regressions and source stage
preflight, builds a disposable Linux UML userspace kernel via
\`linux/tools/testing/kunit/kunit.py run --arch=um\` with
\`CONFIG_KUNIT=y, CONFIG_SWAP=y, CONFIG_BLOCK=y, CONFIG_ZSWAP=n\`,
then BOOTS and executes the original C KUnit cases. It verifies
matching JSON+KTAP before any positive KUnit_EXECUTED status. The
runner never accesses the owner's host kernel, module, mapper,
SWAPSPACE2 partition, or simulated physical block device.

## Initial qualification and GO/NO_GO

Known Round025 exact-SHA host evidence at engineering baseline:
https://github.com/k1moradi/swapz/actions/runs/44042667994
COMPLETED SUCCESS: 5/5 rootless Python/GCC/Clang sanitizer
regressions, and actual kernel \`block/bio.o\` GCC CONFIG_ZSWAP=y/n
KUnit **COMPILED**. That result did **not** boot the KUnit suite,
so it cannot establish KUnit_EXECUTED.

New Round026 exact-SHA UML KUnit runner/result must be taken
from a separate hosted workflow run; **until that result exists,
KUNIT_EXECUTED=NOT_RUN / UNKNOWN**, and neither host C
model nor nm KUnit case symbols qualify it. First actual
compiler/runner/kernel error, if any, must be preserved in the
Round026 issue report rather than hidden under model success.
No local full Linux checkout is available in this container
(\`git ls-remote\` cannot resolve github.com); use pinned GitHub
Git-blob staging and hosted runner, not a fabricated local
kernel test. Local test commands when available:

\`\`\`sh
python3 -B tests/runtime/native/fixtures/round026-sideband-kunit-verdict.py --self-test
python3 -B tests/runtime/native/pinned-linux-zswap-sideband-test.py
\`\`\`

**COMPRESSED MM→BIO→DM ARCHITECTURE VERDICT = NO_GO** even if
KUnit_EXECUTED eventually PASS. No verified source-owned swap-slot
allocator reuse epoch+original STORE digest has been bound to a
live separate compressed carrier and actual DM current mapping,
GC relocation and exactly-once ACK/read authority. Source-refcount
KUnit correctness does not establish identity/authenticated end-to-end
compressed transport. Existing ordinary original 4096-byte zswap
decompress/WRITE fallback remains mandatory. No authorized
physical/private trial is requested or executed; preserve the
SWAPSPACE2 header, UUID and partition table.

\`PHASE_A=BLOCKED\`; \`FORCED_RAW_BYPASS=DISABLED\`;
\`DIRECT_COMPRESSED_HANDOFF=DISABLED\`;
\`LOADED_ORIGINAL_4096=NOT_RUN\`;
\`PHYSICAL_SWAPSPACE2=NOT_RUN\`.


## First executed pinned UML KUnit run: kernel cases PASS; strict verifier falsely refused

At exact SHA
\`4a08e782a33f827e50eb7cf51b98c285b2aeebb9\`,
[hosted run 44048321459](https://github.com/k1moradi/swapz/actions/runs/44048321459)
demonstrated a genuine boot of original pinned Linux UML. Upstream
KUnit stdout reported all seven named source cases PASSED:
\`swapz_ci_clone_lifetime_kunit\`,
\`swapz_ci_split_lifetime_kunit\`,
\`swapz_ci_reuse_and_abort_kunit\`,
\`swapz_ci_reject_invalid_kunit\`,
\`swapz_ci_invalid_clone_kunit\`,
\`swapz_ci_reuse_private_kunit\`, and
\`swapz_ci_abort_dead_ref_kunit\`. Upstream summary:
\`Testing complete. Ran 7 tests: passed: 7\`; reported
\`0.060s running\`, after build. Its existing separate pinned
\`CONFIG_ZSWAP=y/n\` kernel KUnit **compilation** job passed.
The overall run nevertheless completed FAILURE because our additional
kernel-log verifier returned exit 2:
\`first_cause=missing_or_duplicate_kernel_case:swapz_ci_reuse_private_kunit\`.
That name is the first unordered case checked; it is NOT evidence
that the one case failed in the original kernel.

Root cause confirmed in the actual original pinned source:
\`lib/kunit/test.c::kunit_print_ok_not_ok()\` prints
\`"%s %zd %s"\`, e.g. \`ok 6 swapz_ci_reuse_private_kunit\`,
not necessarily \`ok 6 - swapz_ci_reuse_private_kunit\` as our
stricter homemade \`KTAP_CASE\` regex assumed. The pinned original
\`kunit_parser.TEST_RESULT\` accepts an OPTIONAL \`"-"\`, as KTAP
permits. This is a source parser mismatch, not a compiler/runtime
panic, bad refcount, loaded swap-in, or physical pass. We updated
only Agent4's KTAP verifier (both valid source-defined grammars,
self-test authentic no-hyphen samples) and workflow fail-only bounded
raw kernel case diagnostics. A later exact-SHA workflow must
separately establish the correction PASS. Regardless, actual
MM/BIO/DM compressed handoff remains NO_GO and DISABLED, with
loaded 4096 swap-in and physical SWAPSPACE2 NOT_RUN.
