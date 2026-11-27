# Round 101 — Agent 11 evidence

**PACKAGING_REPAIR_PUBLISHED / QUALIFICATION_PENDING.** Not an acceptance or test-pass report. Agent 1 owns integration and final acceptance. Independent Agent 11 lane only; no Agent 3 Round 101 source was used.

## Immutable identities

- Issue #219; task `f3e2a20dd9b17feb677f732e6f5088ff263822fa`; engineering freeze `28ffacb0a50fede481d010c0b688271badbbae6e`; Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`.
- Source [eb2e4d03f32510864886e78b2b50f110db048e95](https://github.com/k1moradi/swapz/commit/eb2e4d03f32510864886e78b2b50f110db048e95); sole fresh publication parent `e8815d5720289639271d7e2ecb7f6b418d41aeba`; tree `7fc5b688a7d9e0114ffdc2d3af3611f1129a8106`. Main non-force expected-head publication succeeded; ref readback verified. No branch or PR.
- Additive overlay [round101-original-mm-retirement.patch](https://github.com/k1moradi/swapz/blob/eb2e4d03f32510864886e78b2b50f110db048e95/tests/tools/round101-original-mm-retirement.patch) blob `df8881c99dd38bff0e38f9678daf35abe603e91d`. Existing patch chain retained; standards historical bytes preserved as exact prefix.

## Changes and ordering

- Separate capture-admission RCU pointer from ordinary-origin observation lifetime. Exact scope identity stop is one-shot: success, exact already-stopped, busy transition, stale wrong identity are distinct. Cookie publication, route acquisition, candidate acquisition and initial BIO bind check capture admission. Existing retained correlation and ordinary observation survive capture stop.
- Final scope revoke retains ownership on outstanding carrier debt, unpublishes observation only on final teardown, waits for grace outside mutex, checks debt again, puts cap and file; cap-put failure retains ownership. Existing revoke interface invokes stop for compatibility. The controller is still responsible for proving external ingress/area/map/original BIO terminal joins before final revoke. A pre-stop admitted bind/capture may finish; stop is not an I/O completion fence.
- Built-in broker retirement query matches exact session/epoch; active/retiring is busy, wrong identity stale, first quarantine error preserved. Final-debt notification is scheduled under broker lock before destruction can race it, with no target callback and no reverse owner-gate-to-broker nesting. Retirement identity recorded after storage destruction, native workqueue flush outside lifecycle lock with witness-in-progress preventing reopen. Controller must obtain witness before reopen and separately join external provider debt. No reopening used as evidence.
- Changed-case host fixture covers worker-driven retirement and explicit finish with pending retry, modeled RCU stop/join and initial bind geometry, ordinary observation and retained debt. Uses actual staged MM functions and broker/recorder code, not native RCU execution. Native lane is exact full Linux checkout with focused SMP/TREE_RCU configuration, default-off ZSWAP and three objects only: mm/zswap.o, mm/page_io.o and built-in mm/round101-swapz/zswap-original-ticket.o. No DM/core change or build, no final link, no MODPOST.

## Evidence so far

All five raw staged preimages reconstructed from frozen GitHub source and checked against exact Git blob SHA1; overlay roundtrip reproduced predicted postimages. This is reconstruction evidence, not hosted git apply or compiler evidence.

| Path | Verified preimage | Predicted postimage |
|---|---|---|
| `mm/zswap.c` | `cad0d9ba05cd614b95b335ed0c7d70d9e69d00f0` | `fcb2f7487cb7ed02ae8ca9a8d486909f721a2ef6` |
| `include/linux/swapz_mm_carrier.h` | `5e11fe42a9dce147cdaf7f30c43b1c8b6feff59a` | `f50911d4c1ff7f87b502cec042b90968ba3a282f` |
| `src/kernel/zswap-original-ticket.c` | `70109f2c2ce9f60681649bd4807382248d0a41a2` | `e605bb0b8fbf5e6411a4d5d6182cab1a44d48bea` |
| `src/kernel/zswap-original-broker-owner.inc` | `278a93a3fd3fd260444aebc55d4a87112e56f704` | `a6a025b1d56513919ac83f4367e9c306fa12c933` |
| `src/kernel/zswap-original-ticket.h` | `c7f4ff59c11ee3475e7577dcc62f7c8db5a578ea` | `6c79e41cb18082b925311bf62d0cfbed45a9e53b` |

Local clone blocked: `git ls-remote` exited 128, `Could not resolve host: github.com`. Local kernel headers are not the pinned Linux tree; no substitution attempted. Source push automatically triggered [focused run 45921709462, job 140253713602](https://github.com/k1moradi/swapz/actions/runs/45921709462/job/140253713602). Initial snapshot was queued; the original job is now terminal FAIL as recorded below. No verified native compiler outcome, exact hosted apply, host-test count, runtime outcome or artifact. No manual duplicate dispatch. Pending qualification remains a blocker; do not interpret source publication as test success.

## Safety

AUTH=0; Phase A BLOCKED; compressed handoff OFF, forced RAW OFF, import OFF. No VM, activation, load, device mutation, disconnected full build, or live operation. Agent 1 integration and acceptance remain outstanding.

## Continuation: terminal original failure and packaging-only repair

The [original job 140253713602](https://github.com/k1moradi/swapz/actions/runs/45921709462/job/140253713602) completed **FAILURE** during the exact direct-main source and standards prefix step. First diagnostic: `tests/tools/round101-original-mm-retirement.patch:17: space before tab in indent.`. The repository-level diff check rejected tab-indented unified-patch context; subsequent toolchain provisioning, Linux checkout, staged source application, GCC/Clang tests and directed compilation were skipped. No artifacts were uploaded. This is not a native compiler or behavioral failure, and no PASS can be inferred.

Corrected source [1b2b3101c391398587e8725c1ca9afc48e89044a](https://github.com/k1moradi/swapz/commit/1b2b3101c391398587e8725c1ca9afc48e89044a), sole fresh parent `b49015bc13bef402a8a2a171628bddd7376d8f61`, tree `584f35aa9afbebc662f4cc5a320f3d581e3c3069`. New overlay blob `4d34b0d771789c09967b38fdf84b0f2b6513cd60`; verifier `4ead4211a1c33cb003cc75571c7d1e80d06828b8`. Repackaged to zero-context hunks, explicitly enabled --unidiff-zero in actual application, preserved strict --whitespace=error, outer repository diff check and actual staged-source diff check. All five complete frozen preimages and both initial/repackaged postimages reconstructed, hash-verified and byte-identical. No product semantics changed; original fixture unchanged. Full historical standards bytes preserved and append verified by blob readback. Direct-main nonforce expected-head publication verified. Local git DNS failure reconfirmed (exit 128).

New automatic changed-source qualification: [run 45923165383, job 140258377460](https://github.com/k1moradi/swapz/actions/runs/45923165383/job/140258377460), latest **QUEUED**. No manual replay or duplicate dispatch; no terminal compiler/test result yet. Broad existing automatic workflows were also queued by main push, not manually launched by Agent 11.

### Proposed controller interfaces (source-only)

- `int swapz_mm_trial_scope_stop_capture(u64 identity)`: sleepable, exact identity, one-shot; -EALREADY exact stopped; -EBUSY in-progress; -ESTALE wrong/absent. No control mutex over RCU grace. Does not join admitted BIOs.
- `int swapz_mm_trial_scope_revoke(u64 identity)`: existing ABI retained; stop then final revoke only after controller joins external area/map/accepted BIO/terminal ingress; retain file and cap while busy, fail closed on cap put failure. Ordinary observation survives stop, not final unpublication.
- `bool swapz_mm_trial_scope_bind_permitted(const struct swapz_mm_carrier *carrier)`: guarded exact live capture-scope/area/file-backed route cap/lease geometry predicate; not claim or authorization. Already admitted original BIO/candidate correlation survives draining.
- `int swapz_mm_broker_owner_retired(swapz_u64 session, swapz_u64 epoch)`: exact current retired identity; zero only after actual storage destruction and native work join. Busy/debt, wrong identity and quarantine error remain distinct. Controller must obtain witness before reopening and join non-broker provider debt. No lifetime mutex across flush_work. Broker lock may nest owner gate for last-debt scheduling; owner gate never nests broker lock.

No acceptance claim. AUTH0; Phase A BLOCKED; all three switches OFF. No activation, VM, module loading or physical I/O.
