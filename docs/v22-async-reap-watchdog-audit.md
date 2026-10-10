# V2.2 asynchronous lower write: callback, watchdog and reaper audit

## Source-level state ownership

The dm-io completion callback writes the lower status into the stream
buffer, then publishes the completion token. It may still access the
`swapz_context` (to queue the worker and decrement the async callback
reference) after publishing that token. Consequently the reaper must
not equate one direct completion token with permission to free the
whole context. The destructor separately drains `async_callbacks`
before destroying the context and workqueue.

The reaper's watchdog branch records an error and completes pending
upper BIOs *once*. It leaves `inflight_buffer_id`, the buffer contents
and its INFLIGHT state untouched, because a timed-out lower operation
may still be reading the memory. Subsequent polls or waits cannot
count that timeout again. A late callback publishes a real token;
only then can the reaper finalize or decide to preserve resident
staged data.

The normal success path publishes a mapping only for the current
generation. A failed target prevents publication by
`swapz_install_mapping`. Lower errors preserve resident,
previously acknowledged staged records and fail uncompleted BIOs.

## Executable exact-C qualification

`tests/runtime/swapz-async-reap-contract-test.py` extracts the
production C definitions of seven callback, staged-reference, BIO
completion, mapping finalization and reaper functions and compiles
them with tiny deterministic userspace stand-ins for Linux completion
primitives, workqueues, delayed work, BIO endio, and mapping storage.

The tests exercise normal callback, error callback, polling without
completion, wait and poll watchdog timeouts, sticky repeated timeouts,
completion winning a timeout race, callback after timeout (error or
success), preservation of acknowledged early-staged data, stale
generation publication, exactly-once pending BIO completion and
shutdown suppression of callback requeue.

Adversarial source-contract mutants deliberately add premature
inflight release, omit BIO ownership clearing, omit synchronous
rejection status, delete callback-refcount draining, or discard
acknowledged staged data, and must be rejected.

The harness is **not** the real dm-io implementation, a scheduler
race harness, device flush/FUA qualification, or a kernel runtime
test. It controls scheduling deterministically. The production C
bodies and their source ordering are executed in user mode with
stubbed dependencies. The isolated kernel CI and both mandatory
joint rootless workflows execute the suite; the workflow contract
tests refuse a removed joint execution gate.

No source-level data corruption defect has been demonstrated in the
audited reaper ordering, so the production kernel is unchanged.
The outstanding risks are real kernel asynchronous callback races,
nonreturning lower I/O (teardown must fail closed rather than free
owned memory), FUA/PREFLUSH persistence, allocation/reclaim pressure,
and independent backing-release authorization.

This work uses no module, mapper, swap, loop/NBD device, real backing,
pressure workload, privileged process or destructive cleanup.
Strategy/batch winner: UNDETERMINED.
