# Round 016 — exact original worker REPORT_READY texts

Worker claims archived without editing; direct GitHub comments remain authoritative and are not automatically runtime PASS.

## [Agent 2 original report](https://github.com/k1moradi/swapz/issues/133#issuecomment-6912352591)

message: REPORT_READY
round: "016"
agent: 2
task_id: agent2-pinned-kunit-manifest-fix
status: SOURCE_READY_PENDING_COORDINATOR_HOSTED_KUNIT
source_sha: 5af1e3e0aa03fcbc3091f94042dde270346f138d
sole_parent_sha: f716a5162a098742ec4bf7ab17b6a6a977bb75d4
source_tree_sha: 93659e1fd1e5ff6773cd78e9f6891236bcc6908d
verifier_blob_sha: e5091222a4d8bda0d72ec6605623706f351db13c
testing_standards_blob_sha: d075495e5d786be798a72e70ff2d4b6cfb78c9e7
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED
remote_main_write: NONE

## Source and scope

Real retrievable Git source commit: https://github.com/k1moradi/swapz/commit/5af1e3e0aa03fcbc3091f94042dde270346f138d

GitHub's raw Git commit object was read back: exactly one parent `f716a5162a098742ec4bf7ab17b6a6a977bb75d4`, exactly two owned modified files, no branch, PR, fork, worktree or main ref update. File changes per GitHub compare:

- `tests/runtime/native/pinned-linux-kunit-uml-config-test.py` (+139/-3; real code and source-controlled unittests).
- `docs/testing_standards.md` (+41/-0; independent distinct Round016 Agent 2 section).

The workflow `.github/workflows/phase-a-zswap-origin-kunit.yml`, original staging tool, strict existing five-case TAP verifier, kernel C/H producer and DM consumer are **unchanged**: the original workflow already produced the correct per-object evidence, so the smallest correct fix was in the typed manifest parser.

## Reproduced real first failure

Source-linked hosted run: https://github.com/k1moradi/swapz/actions/runs/43834985711
Retained original artifact: https://github.com/k1moradi/swapz/actions/runs/43834985711/artifacts/14209984320

I unpacked the actual original `enabled.txt` ZIP locally. It records `defconfig_exit=0`, `scripts_config_exit=0`, `olddefconfig_exit=0`, `prepare_exit=0`, `modified_objects_exit=0`, `zswap_object_exit=0`, `uml_kunit_exit=0`, then `verify_uml_config_exit=1`, `first_failure_phase=verify_uml_config`. The four legitimately repeated `object=PATH sha256=DIGEST` lines have valid, distinct 64-hex SHA256 digests for:
`block/bio.o`, `block/swap-bio-origin-kunit.o`, `mm/page_io.o`, `mm/zswap.o`.
The preexisting `parse_manifest()` rejected the *second* `object=` as a duplicate ordinary key, returning `malformed-or-duplicate-manifest` **before validating any effective UML Kconfig or TAP**. No full y/n KUnit PASS follows from the preceding zero-exit commands. The disabled profile was not completed in the retained artifact.

The committed parser now admits repeated **typed object records** only when paths are in the fixed four-object allowlist, identities are unique, and digests match exactly `[0-9a-f]{64}`. Both profiles require the three common objects; only enabled `CONFIG_ZSWAP=y` requires `mm/zswap.o`, while disabled `CONFIG_ZSWAP=n` rejects it. All ordinary manifest keys remain unique; `result` permits only the original `IN_PROGRESS → PASS|FAIL` transition. Missing, wrong-profile, unknown, repeated, malformed/uppercase/truncated object digests and premature/forged success remain failures.

`--verify` now records a canonical sorted `uml_objects_sha256` identity/digest snapshot next to the preexisting request/effective config hashes, refuses repeated digest writes, and `--verify-pair` refuses object-digest changes before checking existing source identity, separate y/n configs, recorded TAP hashes and actual five-case no-skip TAP verifier. The snapshot checks *manifest transition integrity*, **not ELF binary authenticity**; the existing source-bound hosted Kbuild still owns object byte evidence.

## Measured executable tests — all local/rootless, not hosted Linux KUnit

- `python3 -B tests/runtime/native/pinned-linux-kunit-uml-config-test.py`: **exit 0**, **9 unittest methods PASS**, including replay of the actual four original hosted object lines, y/n positive profile manifests, 9 independently mutated malformed/duplicate/unknown/bad-hash object lines, per-profile absent/extra object cases, repeated verifier refusal without duplicate digest writes, forged PASS, config/hash drift, and reused/missing/bad five-case TAP.
- The above tests executed the *exact committed Python source bytes*; local `git hash-object` = `e5091222a4d8bda0d72ec6605623706f351db13c`, independently confirmed equal to the GitHub-created/read-back blob. Because the full 882-line unrelated existing staging test could not be mounted from GitHub in the DNS-restricted sandbox, its **verbatim strict KUnit TAP validation function** was used as a local subprocess helper for the verifier's two-profile TAP test. The **complete existing staging regression file was NOT_RUN** locally; this helper is not part of the commit and cannot be called a full unmodified suite PASS.
- Actual retained hosted `enabled.txt` through the exact committed `parse_manifest` plus profile object-inventory gate: **exit 0**, all four identities and 64-hex digests accepted; it still honestly records the historical `result=FAIL`, since its recorded original config was not retained.
- `python3 -m compileall -q tests/runtime/native/pinned-linux-kunit-uml-config-test.py`: **exit 0**.
- Independently reconstructed **byte-for-byte exact frozen workflow** (original Git blob `da8533f0cfb151aee8fd5f2060fcc97c3f2c3038`) parsed under PyYAML 6.0.3; both embedded workflow Bash `run` blocks passed `bash -n`: **2/2 exits 0**. Structural check for separate y/n loop, source-staged object evidence, `run_checked verify_uml_config`, mandatory `run_checked verify_real_tap`, and final `run_checked verify_profile_pair`: **PASS**. No workflow text modification was needed.
- Added-line whitespace: `git diff --no-index --check /dev/null` on both modified source excerpt and standards fragment reported **no whitespace diagnostics** (Git exit 1 was due to file differences from `/dev/null`, not a whitespace failure); GitHub actual two-file diff independently scanned with **zero added-line trailing-whitespace faults**.
- Exact repository-tree `git diff --check`: **NOT_RUN** (no full local swapz Git checkout; GitHub DNS failed in sandbox). This limit is not represented as a PASS.

## Qualification limits and handoff

Real modified pinned Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8` hosted Kbuild/UML KUnit y/n on **this new source commit**: **NOT_RUN**. The old failing hosted artifact is historical, not a new pass. Both profiles must still independently build and execute all five distinct `swap_bio_origin` KUnit cases with authentic no-skip PASS TAP and effective config/request equality before qualification. Matched loaded MM→BIO→DM stored-entry writeback, byte-exact 4096-byte readback, teardown/GC and physical/swap/mapper devices: **NOT_RUN / NOT_AUTHORIZED**. Phase A BLOCKED; Phase B RAW bypass and compressed direct handoff remain disabled.

Agent 1 is the only authorized shared `main` integrator; the worker commit is a retrievable frozen-parent Git object, not published to or fast-forwarded onto `main`.

---

## [Agent 3 original report](https://github.com/k1moradi/swapz/issues/133#issuecomment-6912327102)

message: REPORT_READY
round: "016"
agent: 3
task_id: agent3-dm-origin-qualification
status: SOURCE_READY_PENDING_COORDINATOR_CI
source_commit_sha: 3c269221e53adca79c0c56c404b36a87ef52d80f
source_commit_url: https://github.com/k1moradi/swapz/commit/3c269221e53adca79c0c56c404b36a87ef52d80f
frozen_engineering_source_sha: f716a5162a098742ec4bf7ab17b6a6a977bb75d4
task_publication_sha: 1af7cf6518f8fadccc095e7aea02929d9295b84d
production_dm_blob_sha: 2d60ec8d6b9db47dc4708d0ba12162ac9d7367a5
consumer_test_blob_sha: 6b73bde6c0082fa58dad357a36421fa31250ccd1
producer_consumer_abi_test_blob_sha: ea53adb05e200bf4bb83cd60a92b7213e542a1bb
paired_module_verifier_blob_sha: 6493130fcba264f89591aacdd26e9d70072a6f01
matched_workflow_blob_sha: 4b7b9b31ea1927077bc991e180b85cfc31fb9fdb
testing_standards_blob_sha: 3ec07b6a46b27f9137c5766dc6a95a29bbefab4c
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED
remote_main_modified: false

# Agent 3 — Round 016: production DM observational origin idempotence and source-exact matched CI

**Actual retrievable worker Git source commit:** https://github.com/k1moradi/swapz/commit/3c269221e53adca79c0c56c404b36a87ef52d80f

Exact **sole parent** `f716a5162a098742ec4bf7ab17b6a6a977bb75d4`, verified via GitHub REST commits and one-commit compare; **one ahead / zero behind**, six Agent 3-owned changed files, no added trailing-whitespace lines. Remote `main` remained on task publication `1af7cf6518f8fadccc095e7aea02929d9295b84d` when checked. No remote-main update, new branch, PR, fork, additional worktree, privileged/kernel or device mutation.

## Actual edited source and safety boundary

1. `src/kernel/dm-target.c`: add one per-BIO `bool origin_commit_counted`, reset to false next to the existing default `ORDINARY_OR_UNKNOWN` admission snapshot. The **existing** authenticated optional origin carrier, exact `REQ_OP_WRITE`, one `SWAPZ_SECTORS`/4096-byte page and `bio_is_zswap_stored_writeback()` gate are unchanged; the frozen producer helper independently requires `REQ_SWAP` and an authenticated stored-entry tag. Nonaccepted/requeued/READ/BIO-reuse paths remain UNKNOWN. The existing foreground-only commit helper now returns for either ordinary origin or an already-counted BIO, otherwise sets the bit before the single atomic64 counter increment. This runs only under the existing serialized `ordered_owner` before upper completion; a lower callback wakes the owner but never modifies the bit. The four original post-success authority sites (detached async, synchronous compressed, dedicated RAW, zero-elided) are unchanged. No added lock, allocation, scan, scheduling change, compression selection, RAW override, on-media metadata or upper-completion adjustment; the flag cannot make a failed authority successful.
2. `tests/runtime/native/zswap-origin-consumer-source-test.py`: validate the actual C once-only guard, its per-admission reset and order; keep the previous 20 source mutants and add four new ones (missing reset, premarked reset, removed repeated-success guard, mark after increment). Introduce a **real production-C helper extractor** that compiles the unmodified helper body with only kernel type/counter stubs using available GCC/Clang, strict GNU C11 warnings and UBSan. Host fixture tests ordinary=0, repeated positive=1, reset/reused ordinary unchanged, next authenticated positive=2. This is serialized rootless source evidence, not real Linux concurrency or zswap I/O.
3. `tests/runtime/native/zswap-origin-producer-consumer-abi-test.py`: adjust the exact expected DM classifier source for the new reset, preserve all producer staging/clone/mixed-origin checks, require 24 distinct consumer mutations, and add a direct compiler-execution test of the extracted production commit helper.
4. `.github/workflows/phase-a-zswap-origin-prototype.yml`: push filter now explicitly includes actual `dm-target.c` plus both consumer ABI source tests. Add a **fail-closed source/ABI regression step before the expensive matched Linux build**, preserving the original test's nonzero exit (not `if !` masked status), bounded last-35-line error output and no success log. The entire existing matched Linux y/n Kbuild step is **byte-for-byte unchanged**: pinned `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`, staged original C/H and exact source SHA, effective Kconfig, GCC/W=1, real objects, exported `Module.symvers`, source-linked `dm-swapz.ko` SHA/ELF/modinfo and actual compiled `origin_carrier_compiled=1` marker before PASS.
5. `tests/runtime/native/pinned-linux-origin-paired-module-test.py`: keep the existing full actual-file/hash/ELF/modinfo/profile/origin-carrier verifier unchanged, add contract assertions that DM changes trigger matched CI and both rootless source tests precede Kbuild. Add two mutation regressions to reject missing DM trigger and bypassed source ABI script. Existing premature PASS and fake/no carrier negative gates stay intact.
6. `docs/testing_standards.md`: unique **append-only** 63-line `Round 016 Agent 3 — authenticated DM origin exactly-once committed accounting` subsection; Agent 1 must preserve Agent 2's independent same-round appendix.

## Commands, measured tests and first failure

- `gcc -std=gnu11 -O2 -Wall -Wextra -Werror -Wconversion -Wshadow -Wformat=2 -Wstrict-prototypes -fsanitize=undefined -fno-sanitize-recover=all /mnt/data/round016_agent3/actual_origin_commit.c -o /mnt/data/round016_agent3/gcc-origin-test && /mnt/data/round016_agent3/gcc-origin-test` — **compile exit 0, run exit 0**, stdout `PASS exact production C helper ordinary=0 repeated=1 reused=2`.
- Same exact compiler options with **`clang`** — **compile exit 0, run exit 0**, identical output. Local GCC 14.2.0, Clang 17.0.0; **the fixture contains the exact helper C from the committed production Git blob**, with stubs for Linux descriptor and atomic64 types only. Both executions are serialized and unprivileged.
- `bash -n /mnt/data/round016_agent3/ci-consumer-source-contract.sh` (the new workflow Bash step body copied exactly) — **exit 0**.
- `RUNNER_TEMP=... bash ci-consumer-source-contract.sh` in a disposable failing-script fixture — **exit 23**, matching the first script's deliberate exit 23, with single bounded fail-only diagnostic and no second script execution; **negative failure propagation PASS**. This does *not* execute the actual full Python tests.
- **24/24 GitHub-blob source-structure assertions PASS** using the actual six new source blob contents: carrier/reset/ordering, four hook positions, no Phase B bypass, ABI mutation-list length **24**, compiler fixture inclusion, CI source triggers, full matched Linux build-script byte identity, verifier gates and section presence. This is connector-side **structural** testing, not execution of the 24 Python mutation cases.
- GitHub REST `GET /commits/<sha>` and `compare/<frozen>...<sha>`: sole frozen parent, six authorized modified files, additions/deletions, **one commit ahead**, and **zero added trailing-whitespace lines** — PASS.

**NOT_RUN, and not described as PASS:** the entire `python3 -B tests/runtime/native/zswap-origin-consumer-source-test.py` (24 Python negative cases), full `python3 -B tests/runtime/native/zswap-origin-producer-consumer-abi-test.py -v`, full `pinned-linux-origin-paired-module-test.py --self-test`, full project `make -C tests/suites SANITIZE=1 test-all`, complete committed-workflow YAML parse/all embedded Bash scripts, `git diff --check` in a complete local checkout, and the actual matched Linux y/n module Kbuild, KUnit, modpost, load or runtime I/O. The full frozen source checkout is absent; outbound Git clone fails with DNS `Could not resolve host: github.com`. The targeted C extraction and workflow shell fixture are not a substitute for those complete suites.

**Historical/latest hosted evidence:** independently checked [integrated matched-source run #43834985929](https://github.com/k1moradi/swapz/actions/runs/43834985929), job `133189276334`: still **IN_PROGRESS**, on `f716a5162a098742ec4bf7ab17b6a6a977bb75d4`, not this unreferenced worker commit, so **no qualifying PASS or newly observed failure** is attributed to Agent 3's change. Agent 2's separate KUnit manifest parsing failure is outside Agent 3 source ownership. First failed local command: **none** for compiler and syntax tests; deliberate negative fixture exited **23 as required**. No authenticated loaded stored-entry positive WRITE/readback was observed.

**Integration gate:** Agent 1 must serially integrate this source with Agent 2's disjoint KUnit fix and append-only testing-standard section, run existing exact integrated source CI, and require both modified Linux profiles (correct source/header identity, Kconfig y/n, full exported symbols, real linked `dm-swapz.ko`, valid ELF/modinfo SHA and compiled origin carrier), then KUnit and genuine loaded MM→BIO→DM stored-entry writeback and byte-exact **4096-byte swap-in** before Phase A qualification. Ordinary writeback and existing 4096-byte RAW remain unchanged. **Phase A BLOCKED, Phase B RAW bypass DISABLED, direct compressed handoff DISABLED.**

