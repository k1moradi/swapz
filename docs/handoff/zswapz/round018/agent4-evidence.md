# Round 018 — Agent 4 terminal-oracle first-cause extension

**Official task:** [Round 018 Agent 4](https://github.com/k1moradi/swapz/blob/37de56d28af54003954d8b0214fd15baf397bf11/docs/handoff/zswapz/round018/agent4-physical-workload-producer-refusal.md). Publication SHA `37de56d28af54003954d8b0214fd15baf397bf11`. Original host-executed source `9ecb5cc650cc9be9f4efe2bf38c9e3c91f620fa0`.

## Original first failure (not diagnosed underneath)

Owner-host `make test`: five RAM algorithm stages PASS; authorized development physical trial **FAIL**, 171.19 seconds, at `phase=anonymous_workload gate=bounded_primary_workload reason=producer_refused original_errno=unavailable`. Reported cleanup restored ordinary SWAPSPACE2 header/ordinary swap and removed owned mapper/module. The owner's private mode-0600 first exception and full trial log have not been supplied: **the physical producer's underlying first cause remains UNKNOWN**. No private test was rerun.

## Verified source gap and production change

The pinned `qualify-primary-real-swap.py` source emits exact structured terminal errors with `child_exit` (integer, `running`, or `timeout`) and `evidence_complete=false` when an oracle exits before a required phase, times out, fails transport, or violates terminal protocol. Existing `physical-swap-probe.py::_emit_algorithm_workload_failure` mapped unrecognized but legitimate messages to generic `producer_refused`. A 768-character bounded anchored parser now accepts only source-defined terminal events and emits finite child-exit, timeout, transport, protocol, cgroup ownership/swap-limit reasons. Unknown or contradictory strings remain unknown. Optional `oracle` evidence contains only `expected_event` and bounded signed `child_exit`; no raw child text or host identifiers. The original first cause precedes `cleanup also failed` and secondary cleanup errno is not promoted.

The official `run-tests.py` parser now accepts these categories only with exact optional schema, immutable phase/gate and bounded signed child exit. Its human console shows a safe expected event and next action; original nonzero trial exit, private 0600 log retention and automatic recovery authority remain unchanged. **The separately already published slot-release timeout classification** in `cf49aec222c474a4b59ca06b8757ee7e2e177789` and **Agent 2's KUnit integration** in `d623a3c156ff390299f32a6ca2b9891e944bb3d6` are preserved, not overwritten.

## Executed rootless evidence

- `python3 -B /mnt/data/swapz-agent4-round018/oracle_first_cause_excerpt_test.py -v` — initial **exit 1**: a contradictory `child_exit=running` with `exited before ORACLE_WAITING=` was classified as transport. Corrected the classifier and committed this negative regression.
- Re-execution of the isolated, source-excerpt rootless suite — **exit 0**, 2 unittest methods, **26 positive and negative message cases**. Harness SHA256 `54d2686a658228127465c83e4cfc035a5216a8e2c4ac9ae10b13d9c59421db06`.
- `python3 -m py_compile /mnt/data/swapz-agent4-round018/oracle_first_cause_excerpt_test.py` — **exit 0**. This validates the excerpt, **not** the complete production-file Python syntax.
- Full committed `tests/runtime/native/physical-swap-probe-test.py`, `tests/runtime/native/test-report-test.py`, `tests/runtime/native/primary-real-swap-test.py`, local checkout `git diff --check` and hosted CI — **NOT_RUN** in the isolated container: `git ls-remote https://github.com/k1moradi/swapz.git HEAD` returned exit **128**, DNS resolution failure. The GitHub connector permits source blob/tree/commit publication and readback, not execution of the full suite.
- Physical `make test` / module / mapper / cgroup pressure / `mkswap` / `swapon` / `swapoff` / block-device access — **NOT_RUN**, by safety instruction.

The added actual repository tests cover early child exit 1/2/signal, fail-closed preflight, timeout, pipe/EOF, invalid records, OOM, cgroup ownership, basic I/O and digest failures, unknown lookup, privacy, 0600 retention and synthetic official-console nonzero preservation. Their **full imported execution is pending exact-source CI**, never claimed PASS.

**Safety:** Phase A BLOCKED; Phase B RAW bypass DISABLED; direct compressed handoff DISABLED. Existing RAW is original uncompressed 4096-byte page. Rootless source diagnosis does not justify an unsupervised physical rerun.
