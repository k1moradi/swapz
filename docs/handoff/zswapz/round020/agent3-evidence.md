# Round 020 Agent 3 — matched loaded-DM owned-RAM admission/readback evidence

Task: [official Round 020 opening](https://github.com/k1moradi/swapz/issues/137#issuecomment-6921871057),
published task source `de5bc09e80484c60d003e860732ecb736a6c2f0b`.
Agent 3 implementation scope only; Agent 2 owns upstream Linux producer/stager.
Production `src/kernel/dm-target.c` is unchanged; there is no new hot-path
work, on-media format, raw bypass, kernel boot, module load or device mutation.

## Correctness change and explicit trust boundary

The existing rootless owned-RAM comparator did **not** constrain an upper
successful WRITE completion to exactly one: any positive `upper_write_completed_ok`
delta was accepted even when admission and authoritative commit deltas
equalled one. That can hide another writer/owner and misstate one-to-one
causality. The comparator now requires exactly one upper ACK; both zero
and two return `not_exactly_one_upper_success`. Commit and upper success
remain independent evidence, and no offline result is Phase A PASS.

The new `tests/runtime/native/zswap-origin-loaded-evidence-contract.py`
is a nonmutating, standard-library **candidate-only** inspector. Versioned
JSON (8KiB maximum) is parsed with strict duplicate-key rejection and
nofollow bounded regular-file reads, with exact field inventory and typed,
limited identifiers/counters. Candidate identities include exact pinned
modified Linux source `c339f4010dea8b0d754f84ace70cd1b089878ef8`,
claimed kernel booted source/boot ID, measured boot-image SHA-256,
swapz module source SHA, disk/loaded module SHA-256 identity,
kernel release/vermagic and live module, compiled origin carrier,
independent page SHA and nonzero source/generation identity.
Prerequisites include exclusively owner-controlled ephemeral `brd`
RAM backing, exactly one owner, bounded pressure/deadline, owner
permission, cleanup authority and verified teardown; the candidate must
claim actual stored-compressed entry eviction→MM/REQ_SWAP BIO→loaded DM
foreground commit→upper success→4096-byte swap-in. Invalid or missing
claimed prerequisites fail with a safe first cause.

Even all-positive candidate metadata and superficial boot ID/uname/sysfs
matches are **UNTRUSTED**: they do not authenticate actual loaded module
bytes, the MM event, original full-page source, RAM exclusive ownership
or permission. The executable always refuses (exit 2, NOT_RUN markers),
never executes privileged commands or creates a mapper/swaps. No input
can grant permission or make Phase A PASS.

The existing `.github/workflows/phase-a-zswap-origin-prototype.yml`
triggers on both reader sources, runs the existing rootless tests and the
new candidate's real self-test, and requires exit 2 plus four exact
fail-closed labels when inspecting an empty candidate. Kbuild after the
new step is byte-for-byte unchanged: pinned Linux, gcc W=1, both effective
ZSWAP y/n profiles, generated headers, real Linux source blobs/objects,
nonempty Module.symvers, linked dm-swapz.ko SHA, ELF/modinfo/vermagic,
compiled origin marker and original paired source verifier. The existing
`pinned-linux-origin-paired-module-test.py` adds three tests requiring
the new CI trigger, self-test and expected-refusal gate; its real module
artifact verifier is unmodified.

## Actually executed local commands and results

- `PYTHONWARNINGS=error python3 -B zswap-origin-loaded-evidence-contract.py --self-test`:
  **exit 0; 33/33 PASS**, 0.008 seconds. Cases cover pinned/source/
  module/boot digest drift, vermagic, origin carrier, exclusive RAM
  owner, missing owner/cleanup permissions, overflow pressure/deadline,
  stale generation/record, fake stored/REQ_SWAP/upper/READ events,
  duplicated/missing/extra JSON fields, bad input files, and actual
  boot/module mismatch.
- `python3 -B -m py_compile zswap-origin-loaded-evidence-contract.py`:
  **exit 0**.
- `bash -n ci-loaded-candidate-step.sh`: **exit 0** (exact newly
  added Bash step body copied into a disposable directory).
- `RUNNER_TEMP=... GITHUB_SHA=de5bc09... bash ./ci-loaded-candidate-step.sh`:
  **exit 0**; runs 33 source-controlled tests then observes the
  deliberate exit **2**, `first_cause=manifest_file_type_or_size`,
  `LOADED_STORED_ENTRY=NOT_RUN`, `4096_READBACK=NOT_RUN`,
  `PHASE_A=BLOCKED PHASE_B=DISABLED DIRECT_COMPRESSED=DISABLED`.
- Rootless self-consistent synthetic all-positive JSON passed only
  internal candidate coherence, then `--inspect-candidate`
  **refused exit 2**, `first_cause=actual_boot_id_mismatch`;
  not a loaded or owner-authorized trial.
- Git `hash-object` of the actual locally compiled/tested new file:
  `b24678da51f44cc5012c83ad959c52626eae9729`, **exactly
  equal** to its published GitHub source blob after byte verification.
- GitHub-blob source-bound structural tests: **18/18 checks PASS** for
  original Kbuild byte identity, exit-2/NOT_RUN ordering and
  rootless CI triggers, original ELF verifier byte identity, the
  exact-one upper-ACK source change, and 33 new test methods.
  These are static source checks, not execution of the existing full
  Python suite.
- Existing amended owned-RAM self-tests now contain **26 test methods**
  (25 existing plus double-ACK regression) but full amended
  `--self-test` was **NOT_RUN** locally due unavailable complete
  original checkout. The three added paired-workflow mutation methods
  also await actual full-suite execution. Complete YAML parse/all Bash
  blocks, GCC/Clang original production-C source fixtures, and
  complete-tree `git diff --check` are **NOT_RUN** locally.

## First observed issues and disposition

The source-level first gap was an unbounded positive upper ACK delta;
the source was corrected narrowly, with zero/double negative cases.
During source transfer, a nonmatching compressed candidate chunk was
caught by Git blob SHA verification and reconstructed; the actual final
new file's local `git hash-object` exactly matches the submitted
GitHub blob. **No first failed executable regression** remains in the
33-case new suite or copied workflow step.

GitHub cloning was locally unavailable: `git ls-remote
https://github.com/k1moradi/swapz.git refs/heads/main` failed **exit
128**, `Could not resolve host: github.com`. Normal connected GitHub
Git objects and non-force expected-head fast-forward can publish an
actual commit without pretending that `git fetch` or `git push`
ran locally. Record the final main SHA, parent and report link in issue
#137; preserve other workers' main commits and separate standards.

## Distinct qualification categories (do not collapse)

- Source: new 33-case candidate tests actually PASS; 18 source
  structural assertions PASS. Original amended suite NOT_RUN locally.
- Historical KUnit: [#43897628379](https://github.com/k1moradi/swapz/actions/runs/43897628379)
  completed **success** on `01edd17eed37efa312523324b1210efdd46be144`;
  5/5 non-skipped genuine compiled KUnit cases in **each** `y/n`
  as verified in the source task, **not** Round 020 loaded proof.
- Historical matched Linux/module: [#43897628284](https://github.com/k1moradi/swapz/actions/runs/43897628284)
  completed **success** on the same earlier source SHA; not a
  current commit's hosted run or real loaded module.
- Loaded real zswap stored-compressed-entry eviction, MM/REQ_SWAP BIO,
  matched DM module, successful foreground commit/upper ACK and
  genuine original 4096-byte swap-in: **NOT_RUN**.
- Independently owned RAM trial, hardware, physical partition, cgroup
  pressure, kernel module insert, teardown: **NOT_RUN**, no permission
  obtained or mutation performed.

**Phase A BLOCKED; Phase B forced RAW bypass DISABLED; direct compressed
handoff DISABLED. Existing swapz RAW is exactly the original uncompressed
4096-byte page.** Agent 1 independently reviews the published exact
commit, runs hosted CI and owns any future owner-authorized loaded trial.
