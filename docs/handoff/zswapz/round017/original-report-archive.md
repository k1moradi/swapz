# Round 017 — original source worker reports (verbatim)

Original GitHub comments are archived without modification. These reports describe real source changes but do NOT establish loaded Linux zswap eviction/readback or owner physical PASS.

## [Agent 2 REPORT_READY](https://github.com/k1moradi/swapz/issues/134#issuecomment-6915502946)

message: REPORT_READY
round: "017"
agent: 2
status: SOURCE_PUBLISHED_MAIN; HOSTED_KUNIT_IN_PROGRESS; REPOSITORY_POLICY_BLOCKED
source_commit_sha: f7d754e1022c6f64dd986c8ba248bb86d43e35ef
sole_parent_sha: 32c5bb61ca1f7a468fc631bf06e8f21792ad0a3c
branch: main
publication: NON_FORCE_EXPECTED_HEAD_VERIFIED
published_url: https://github.com/k1moradi/swapz/commit/f7d754e1022c6f64dd986c8ba248bb86d43e35ef

Agent 2 completed an actual source change (two owned paths):
- tests/runtime/native/pinned-linux-kunit-uml-config-test.py
- docs/handoff/zswapz/round017/agent2-evidence.md

Historical first failure and boundaries:
- Exact integrated run https://github.com/k1moradi/swapz/actions/runs/43842886936 ; artifact 14214860003 (downloaded and inspected).
- Enabled modified Linux defconfig, modified objects, zswap object and `uml_kunit` all returned 0; four distinct compiled-object SHA-256 identities and independent request/effective/object hashes were recorded. `verify_uml_config_exit=1`, first phase `verify_uml_config`, diagnostic `malformed-config-entry`. No enabled five-case TAP qualification and no completed disabled profile.
- Artifact did not retain either actual Kconfig input file; exact historical line was unavailable. Do not invent it.
- Source-confirmed parser defect: `CONFIG_[A-Z0-9_]+` rejects valid mixed-case symbols `SCSI_DC395x` (pinned Linux drivers/scsi/Kconfig) and `I2C_MUX_PCA954x` (pinned Linux drivers/i2c/muxes/Kconfig). A locally installed Linux 6.12 .config contains both legitimate concrete examples `CONFIG_SCSI_DC395x=m` and `# CONFIG_I2C_MUX_PCA954x is not set`. Previous regex rejects both.
- Fix permits `[A-Za-z0-9_]` option names only in exact set/unset Kconfig syntax; all required CONFIG_SWAP/KUNIT/BLK_CGROUP/CGROUPS and y/n ZSWAP states, duplicate detection and strict five-distinct-case executed TAP validation remain intact.
- Fail-only first-cause diagnostic contains bounded safe option name, request/effective source type, exact line number and full SHA-256 of malformed line. No raw value, full config, absolute runner path or stderr dump. Workflow already captures bounded Python diagnostic via `run_checked`.
- New rootless test methods: two-profile real mixed-case option fixtures; malformed name/empty value/incorrect unset/leading whitespace; exact first-line+digest and no secret/value/path disclosure; duplicate mixed-case fields and wrong disabled ZSWAP. Original safety cases preserved.

Measured current-turn checks:
1. GitHub `compare_commits` baseline-to-published: ahead=1, behind=0, exactly 2 owned changed files; PASS.
2. GitHub commit diff scan: no added lines with trailing whitespace; PASS (NOT local `git diff --check`).
3. Locally executed Python against installed Linux 6.12 `.config`: observed both mixed-case examples; original exact regex rejects each (2/2 demonstrated); PASS, a source-grammar reproduction NOT the new committed Python regression suite.
4. GitHub Git-data non-force update_ref(main, expected_sha=32c5bb61..., force=false) SUCCESS and immediate remote HEAD readback EXACT f7d754e1...; PASS.
5. Full exact-source `python3 -B tests/runtime/native/pinned-linux-kunit-uml-config-test.py`, `python3 -B ...pinned-linux-zswap-origin-stage-test.py`, YAML/embedded Bash, local `git diff --check`: NOT_RUN locally; no complete local swapz source checkout or GitHub network DNS in the tool sandbox. Do not present V8 source inspection as Python execution.
6. Exact pushed source hosted pinned KUnit workflow https://github.com/k1moradi/swapz/actions/runs/43860358473 : IN_PROGRESS (job modified-source-kunit 133275255387; most recent observed step Install Kbuild/UML dependencies). `CONFIG_ZSWAP=y/n` full source compiled+five actual TAP cases NOT VERIFIED, pending source-linked runner.
7. Other exact-SHA CI https://github.com/k1moradi/swapz/actions/runs/43860358467 : Repository policy FAIL on `Require applicable non-whitespace canonical co-change`; task explicitly reserves shared `docs/testing_standards.md` for Agent1, so Agent2 did not override that ownership. Agent1 should reconcile canonical standards in a separate integration commit. Independent rootless production-readiness FAIL in `ProductionReadinessEvaluatorTest.test_artifact_hash_mappings_are_cross_bound_independently` with FileNotFoundError (unrelated to Agent2-owned Kconfig file; requires own-owner review). Rootless primary-lifecycle-audit PASS.
8. Loaded authenticated zswap stored-entry→MM/BIO→DM WRITE and exact 4096-byte READ/physical trial: NOT_RUN, no authorization.

Source note: https://github.com/k1moradi/swapz/blob/f7d754e1022c6f64dd986c8ba248bb86d43e35ef/docs/handoff/zswapz/round017/agent2-evidence.md
Ownership: no branch, PR, fork, additional worktree, force push or physical device writes. GitHub Git Database used for atomic expected-head direct-main publication because local full checkout is unavailable; do not claim a local main checkout/test.
Phase A BLOCKED; Phase B RAW bypass DISABLED; direct compressed handoff DISABLED. Existing swapz RAW is original uncompressed 4096-byte page.
MAIN_WRITE_LEASE_RELEASED

---

## [Agent 3 REPORT_READY](https://github.com/k1moradi/swapz/issues/134#issuecomment-6915531066)

message: REPORT_READY
round: "017"
agent: 3
task_id: agent3-dm-owned-ram-readback
status: SOURCE_PUBLISHED_ENVIRONMENT_NOT_QUALIFIED
remote_main_commit_sha: cd5a18fb44b61a38676806414f8ffe00b9543b9a
source_commit_sha: cd5a18fb44b61a38676806414f8ffe00b9543b9a
source_commit_url: https://github.com/k1moradi/swapz/commit/cd5a18fb44b61a38676806414f8ffe00b9543b9a
sole_parent_sha: f7d754e1022c6f64dd986c8ba248bb86d43e35ef
task_publication_sha: fe7396fe64bf51724e7b70e7a67d58539fdb815e
phase_a: BLOCKED
phase_b_raw_bypass: DISABLED
direct_compressed_handoff: DISABLED
loaded_stored_entry: NOT_RUN
readback_4096: NOT_RUN
owner_authorized_device_mutation: NONE
remote_main_fast_forward: true
first_expected_refusal: matched_module_not_loaded
first_expected_refusal_exit_code: 2

# Agent 3 — Round 017 actual direct-main source delivery and evidence

**PUBLISHED, not merely an unreferenced worker commit:** [`cd5a18fb44b61a38676806414f8ffe00b9543b9a`](https://github.com/k1moradi/swapz/commit/cd5a18fb44b61a38676806414f8ffe00b9543b9a). Direct `main` update used the GitHub connector's **non-force** `update_ref` with **expected-head `f7d754e1022c6f64dd986c8ba248bb86d43e35ef`**; GitHub confirmed `success=true` and subsequent REST read verified `refs/heads/main == cd5a18fb44b61a38676806414f8ffe00b9543b9a`. Sole parent, exactly one new commit ahead and no additional branches/PRs/worktrees. Agent 2 had already pushed disjoint code on `f7d754e1022c6f64dd986c8ba248bb86d43e35ef`, so this work was reparented on the fresh head, checked for conflict and retested; nothing from Agent 2 was overwritten.

**Four exact changed paths:**
- NEW `tests/runtime/native/zswap-origin-owned-ram-qualification.py`, blob `408362b82ca8c7b1d66153ceaa863d4f6ed2cf65`;
- `.github/workflows/phase-a-zswap-origin-prototype.yml`, blob `4bd425e726fea7699ecf189a030d3e3ee4855869`;
- `tests/runtime/native/pinned-linux-origin-paired-module-test.py`, blob `ec63d062681048d32e7022bf65770225818b0ba5`;
- NEW `docs/handoff/zswapz/round017/agent3-evidence.md`, blob `be495f13c48c068a434e512efb2b7726293267ae`.

**Production DM audit:** Existing `src/kernel/dm-target.c` blob `2d60ec8d6b9db47dc4708d0ba12162ac9d7367a5` remains unchanged: default UNKNOWN per admission, positive only for `REQ_OP_WRITE`, one `SWAPZ_SECTORS`/4096-byte page and the producer's authentic stored-writeback origin helper (which additionally checks `REQ_SWAP`), post-admission requeue fence, descriptor-local `origin_commit_counted` idempotence, and exactly four foreground successful-authority accounting hooks (synchronous, detached async, dedicated RAW and zero-elided). The lower callback does not count; GC and READ do not count; upper `swapz_complete` success/error accounting is separate and can distinguish a committed mapping from an upper failure. No C policy, serialization, RAW encoding, completion timing, device authority or kernel producer changed.

**New executable source-controlled read-only owned-RAM gate:** no kernel/module/mapping/swap/pressure mutation backend exists in this program. `--preflight` always fails safely if matched loaded-module identity, independent booted modified-Linux source, authenticated owned RAM, permission, bounded deadline or cleanup authority is absent; in this environment the first cause was `matched_module_not_loaded`. `--offline-compare` checks two bounded nofollow regular-file DM status snapshots with the **actually exported** fields `origin_carrier_compiled=1`, admitted and committed positive-origin counters, separate upper completion and endio error counters; canonical overflow-safe integers; exactly-one deltas; original full 4096 bytes and independent SHA-256; and byte-exact recovered page. It never treats supplied synthetic/caller-captured bytes as a genuine loaded MM→BIO→DM source: even a consistent offline sample yields exit 2 and `offline_samples_cannot_prove_loaded_origin`, not PASS. It enforces no read from a symlink, FIFO or device and prints only bounded categorical first failure without path/content disclosure.

The matched-Linux workflow now watches the new guard, runs its 25 Python cases, and **requires an expected exit-2 `ENVIRONMENT_NOT_QUALIFIED` plus explicit `LOADED_STORED_ENTRY=NOT_RUN`, `4096_READBACK=NOT_RUN`, Phase A/B/off flags before continuing to the original source-linked Kbuild. Every unexpected positive/negative/omitted guard blocks the build step; ordinary warnings, actual config y/n, patched Linux source/blob identity, `Module.symvers`, nonempty SHA-verified `dm-swapz.ko`, ELF/modinfo/vermagic, source-build-info and binary `origin_carrier_compiled=1` remain guarded by the unchanged original build and verifier. The verifier adds two source-bound negative mutations for omitted guard source-trigger and bypassed expected refusal.

## Commands and actual results

- `PYTHONWARNINGS=error python3 -B /mnt/data/round017_agent3/zswap-origin-owned-ram-qualification.py --self-test`: **exit 0, Ran 25 tests in 0.016s, OK** on rerun after observing Agent 2's new remote head. Tests include exact 4096 bytes, independent digest, dropped/doubled admission/commit, upper error after authoritative commit, missing upper ACK, endio seen and forced-error deltas, origin marker absent, status missing/duplicate/overflow/noncanonical, symlink and FIFO denial, read-only environment refusal.
- `python3 -B -m py_compile /mnt/data/round017_agent3/zswap-origin-owned-ram-qualification.py`: **exit 0**.
- `python3 -B zswap-origin-owned-ram-qualification.py --preflight`: **exit 2 (intentional refusal)**, `ENVIRONMENT_NOT_QUALIFIED first_cause=matched_module_not_loaded`, `LOADED_STORED_ENTRY=NOT_RUN` and `4096_READBACK=NOT_RUN`.
- `bash -n /mnt/data/round017_agent3/owned-ram-ci-step.sh`: **exit 0** for the exact new YAML step body replicated locally.
- `RUNNER_TEMP=... bash ./owned-ram-ci-step.sh` in the disposable non-Git fixture: **exit 0**, running the source guard and accepting only the deliberate preflight exit 2 and four explicit fail-closed output markers.
- `--offline-compare` with **matching synthetic 4096-byte original/readback and counters**: **exit 2**, `first_cause=offline_samples_cannot_prove_loaded_origin` (no fabricated loaded PASS); with injected actual DM endio error delta: **exit 2**, `first_cause=unexpected_error_delta`.
- `git hash-object /mnt/data/round017_agent3/zswap-origin-owned-ram-qualification.py`: `408362b82ca8c7b1d66153ceaa863d4f6ed2cf65`, **exactly matching** source blob committed/published.
- GitHub source compare and commit patch scan: **PASS**, sole current-main parent, only four named paths, no added trailing whitespace. Post-publication REST ref/commit verification: **PASS**.

**Identified and fixed first candidate mismatch:** production `dm-target.c` has internal `ctx->io_failures` but does *not* export an `io_failures=` status token. Before publication the guard was corrected to the **real** `endio_write_seen_err` and `endio_write_forced_err` status fields, then the forced-error negative case was added and the full 25/25 suite rerun. No unfixed local test failure.

**External existing build evidence, source-limited:** [older modified-Linux matched build #43834985929](https://github.com/k1moradi/swapz/actions/runs/43834985929) completed `success` at `f716a5162a098742ec4bf7ab17b6a6a977bb75d4`; [Round 016 matched build #43842886913](https://github.com/k1moradi/swapz/actions/runs/43842886913) completed `success` at `b26c42d1ea7524a78747eafc431e35a1d1e94d35`. **Neither is a Round 017 commit build, booted matched Linux, loaded module, KUnit TAP, real stored-entry eviction, or 4096-byte swap-in.**

**Remaining NOT_RUN:** entire existing frozen-tree Python native/ABI suite, entire exact committed YAML parse and all embedded scripts, full native `make test`/W=1/W=2 kernel module warnings, new-sha hosted matched y/n module Kbuild, KUnit, independently owned loaded RAM target, actual compressed zswap stored-entry eviction through MM→BIO→DM, subsequent swap-in and byte-for-byte 4096-page comparison, GC/fault/teardown, and any physical-device check. There was no local Git checkout; a literal `git ls-remote https://github.com/k1moradi/swapz.git refs/heads/main` failed **exit 128** with DNS `Could not resolve host: github.com`; publication used connector-native normal Git objects and the guarded non-force direct-main update, not a claimed local `git push`. All CLI test samples were rootless and synthetic; not source authentication or runtime authority.

**First actual environment refusal: `matched_module_not_loaded` (exit 2, expected). Phase A BLOCKED; Phase B RAW bypass DISABLED; direct compressed handoff DISABLED.** No swapoff/swapon, host swap changes, cgroup pressure, mapper/module insertions, RAM-device/physical-block mutations were authorized or performed. Agent 1 owns hosted CI, actual source/boot/owned RAM authorization, and closeout. Detailed per-agent handoff: [Round 017 Agent 3 evidence](https://github.com/k1moradi/swapz/blob/cd5a18fb44b61a38676806414f8ffe00b9543b9a/docs/handoff/zswapz/round017/agent3-evidence.md).

