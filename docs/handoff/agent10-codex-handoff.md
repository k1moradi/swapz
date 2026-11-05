# AGENT 10 — P0 parent/child evidence authorization handoff

## Source identity and publication

Initial inspected `main`: `9a6ed2bf5edd3dd6f0e878de09aeb6d1779ded26`.
Later observed `main`: `2d43f7f1aefc28268f398eeb04933a037d577c7a`.
Independent debugging audit later inspected `main` at `0d47af66205c4893f8170ba79dc625f263595c08`. The two read-only producer blobs were still unchanged; the scoped regression test was corrected as described below.

Original three scoped file blob SHAs at the first two inspection points:

- `tests/runtime/native/primary-real-swap-parent-ownership-test.py`: `529e0e43047d1009a630180433dda0c1b0d5ab90`
- `tests/tools/qualify-primary-real-swap-parent.py`: `f81991280b2ee835affb15c90f2d75581c9b4bc0`
- `tests/tools/qualify-primary-real-swap.py`: `ab76eecee2fd3c5856d5559e10bd25a6d10adbf1`

During the initial investigation no GitHub write, branch, PR, worktree, force push, physical I/O, or privileged signaling was performed. The handoff and standalone probes are subsequently published to `main`; this does not change producer code or establish canonical execution. Existing repository parent-ownership suite could not be executed locally because a checkout is not available in the rootless execution container and its network cannot access GitHub; the standalone probes below are not substitutes for that canonical suite.

## P0 confirmed: substitute admission server with same UID

- Parent `qualify-primary-real-swap-parent.py:904-913` creates a `0700` UID-owned temporary directory and `0600` Unix socket. The same UID can unlink/rebind the socket pathname.
- Helper `qualify-primary-real-swap.py:200-231` checks socket mode, owner UID and pre/post pathname identity; connected `SO_PEERCRED` PID is retrieved but not compared with a source-bound live parent PID.
- The same UID can replace the pathname **before** the helper's first `lstat`, bind its own stable listener, and return a syntactically valid `PASS` response echoing the helper's nonce (`:297-364`). The genuine parent's listener stays uncontacted. The original predicate-level probe reproduced this with an unrelated controlled subprocess and real kernel-supplied AF_UNIX peer credentials, 12/12 consecutive times. The published probe was subsequently corrected to instantiate the repository's actual `SourceAdmissionClient` and call `require("initial")` against the substitute instead of reimplementing the client's checks. That corrected version must be run from a repository checkout before its result is cited. No privileged helper was executed, so synthetic PASS does not prove actual swap/evidence success.
- Parent `:584-678` independently checks root UID and ancestry for inbound peers but deliberately rejects every source-only request with `physical_admission_identity_missing`. This does **not** authenticate the helper's outbound connection to the purported unprivileged parent. A timeout cleanup at the real parent is not a safe mitigation for a forged admission before that timeout.

**Required producer correction (read-only in this task):** Bind the helper's connected peer PID and live process start identity to the exact originating parent process, supplied over the commit-bound launch context; also reject any change across phases. Preserve the existing UID and pathname checks as defense in depth. A pid number only, without a live identity/lifetime guarantee, is insufficient for PID reuse. Do not assume same-UID filesystem permissions authenticate a process. Ensure no inherited/transferred descriptor defeats the intended peer/write-owner binding. Do not allow PASS from source-only records before complete target/run evidence is authenticated.

## Additional producer-side ownership edge

`qualify-primary-real-swap-parent.py:688-709` performs `child.wait(timeout=45)` outside a `BaseException`-aware ownership finalizer. `KeyboardInterrupt` during that wait propagates out of `main` (`:921-933` only catches `Blocked`, `OSError` and `subprocess.SubprocessError`), after the child is started in its own session (`:798-805`). This has an observable risk of leaving the still-owned child/process group running. A rootless subprocess probe confirmed the basic interrupted-wait lifecycle behavior, but an unmodified upstream executable regression has **not** been run. Producer should add an owned-handle cleanup path preserving the original interrupt and first failure stage. Never signal guessed PIDs or an unanchored/recycled group ID.

## Test-owned cleanup hazard (scoped regression file) — corrected

The original `primary-real-swap-parent-ownership-test.py:397-409` cleanup used `os.killpg(child.pid, SIGKILL)` after the production cleanup might already have reaped the group leader, then fell back to `os.kill(descendant_pid, SIGKILL)` based only on `/proc` pathname existence. That was not ownership-safe under PID/group-ID reuse. The scoped test was corrected on `main` in `90e9cdfddefbb27d71ff4cb35b5b62f4d57cd151`, with an embedded-child argv typo immediately fixed in `0d47af66205c4893f8170ba79dc625f263595c08`. The finalizer now opens a pidfd for the proven descendant before production cleanup, sends group signals only while the actual session leader is still live, and never signals a stored descendant PID directly. This correction still requires repeat execution of the canonical suite from a non-root checkout.

## Rootless evidence and limits

- `rootless-socket-substitution-probe.py`: the original predicate-level version completed 12/12 synthetic pathname substitutions; unrelated impostor peer PID differed, UID/path predicates passed, forged protocol PASS fields matched, and the original listener accepted zero connections. The corrected published version now imports the actual helper module, instantiates `SourceAdmissionClient`, authenticates the impostor as the connected peer, binds the real control-input inventory/helper digest, and calls `require("initial")`. Because this environment has no executable repository checkout, the corrected version is published but not claimed as executed here.
- `rootless-lifecycle-probes.py`: five repetitions each of early abnormal exit, silent-listener timeout, partial terminal output, nonzero exit following apparent verification, interrupted wait, failure to collect stderr, foreign similarly named evidence path, and signaling an owned session group while its leader is live. These exercise OS behavior, **not** the original repository suite. Its result label was corrected so it no longer overstates that last probe as full descendant group cleanup. No live cgroup or oracle was exercised.
- Static source audit: `_owned_peer_process_lineage` ties incoming root peers to launched sudo process ancestry with `/proc/[pid]/stat` start ticks and child exit checks (`parent:493-549`); group cleanup retains unreaped session leader via `waitid(WNOWAIT)` (`parent:307-325,404-470`). This protects inbound peer substitution and group-ID recycling in the normal path; it does not protect outbound helper server authentication.
- `_oracle_event` rejects incomplete terminal records and `_require_oracle_terminal_exit` demands a zero exit after verification (`helper:2628-2745`); these are read-only Agent 7-owned terminal records and were not edited.
- Persistent evidence files enforce private ownership, no prior attempt-path reuse and a non-PASS initial record (`helper:401-525`). A stored synthetic PASS alone is not physical qualification or real worker ownership evidence.

## Production-readiness debugging only

No feature development is needed for this boundary. Remaining work is bug closure and evidence: authenticate the exact parent process, close interruption cleanup gaps, add source-linked regressions for those bugs, and repeat the canonical rootless suite. Do not expand the protocol beyond the minimum identity fields needed to fix the confirmed authorization defect.

## Required same-commit gate and Codex next action

1. Producer corrects `SourceAdmissionClient` parent process authentication, closes `KeyboardInterrupt` child cleanup gap, and preserves original error/errno plus explicit first phase and retained-resource status in failure-only diagnostics. Do not put private identifiers in public logs.
2. Add source-linked regression in `tests/runtime/native/primary-real-swap-parent-ownership-test.py` using actual sockets and an unrelated same-UID listener replacement. Verify it fails on the current trusted-source code and passes only with the producer correction. Cover interrupted wait with actual controlled Popen ownership and no guessed-PID cleanup. Do not duplicate Agent 7's terminal-record tests.
3. Commit producer fix and passing regression together to the updated `main`, after running the existing parent-ownership suite repeatedly under a non-root account and recording exact commit SHA. No branch, PR, force push, worktree or privileged physical execution is required for this gate.
4. Codex alone may perform privileged real-host execution and establish true oracle process/cgroup provenance, exit code, terminal identity, evidence ownership and physical I/O counters. The above synthetic PASS is **never** equivalent to that proof.

**Disposition:** BLOCKED pending producer correction and canonical suite verification. Publication of these documentation/probe artifacts on `main` is not the required producer correction or canonical suite proof.
