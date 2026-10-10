# V2.2 in-flight finalization metadata preflight audit

## Source identity and scope

Main-developer audit based on `4704995c4be35a9c062792c87037c197e4a8ab1a`.
Codex has separately been assigned an unprivileged native Linux
requalification of that source revision; no Codex findings on the new
candidate are presumed before a report is received.

## Defect and boundary

`swapz_finalize_stream_buffer()` previously trusted the in-memory
`block_count`, every block's `record_count`, and every
`record->logical_page` when processing a lower write completion.
The lower asynchronous callback only publishes its I/O error and a
completion token; it does not validate mutable stream metadata.

Under fault-injected post-submission corruption, a forged count could
make the success or error branch index outside the allocated batch,
and an out-of-range logical page could index
`context->generations` via `swapz_stream_record_current()`.
On the successful-lower-write path, a late malformed record could
also be found only after earlier mappings and upper BIO completions
had been published. No ordinary-workload trigger for this internal
metadata corruption was demonstrated.

## Production repair

Before either finalization branch mutates ownership, mappings, staged
references, accounting, or upper BIO completion, finalization now
checks the **entire** resident batch:

- Nonzero block count within both allocated batch capacity and the
  usable physical backing extent.
- Nonzero record count bounded to the fixed 64-record array.
- Each record's logical page inside the allocated generation array.
- Serialized descriptor index matching its in-memory record slot.
- Flags restricted to raw or compressed, with exactly one full-size
  raw record or a nonzero bounded compressed length.

The guard is a linear read-only metadata pass. It does not allocate,
decompress data, access lower storage or change persistent formats.

On malformed metadata the target transitions to failed, retains the
completed stream buffer rather than recycling possible acknowledged
staged data, and returns `-EUCLEAN`. The existing
`swapz_reap_inflight()` error path performs bounded failure
completion for the still-discoverable outstanding upper BIOs.
This prevents partial mapping publication. It does **not** guarantee
recovery from arbitrary memory corruption that has destroyed the
metadata identifying outstanding BIOs or authoritative data.

Uncorrupted success, lower-write error retention, late callback,
watchdog timeout, callback-reference drain, generation staleness,
and one-completion-per-owned-BIO semantics retain their existing
code paths. The additional metadata scan has O(record count)
processing per completion; its production latency impact has not
been measured.

## Rootless execution and adversarial evidence

The mandatory
`tests/runtime/swapz-async-reap-contract-test.py`
compiles the exact production callback, failure completion,
finalizer, generation and reaper C functions using bounded,
ordinary-memory shims. New cases fault-inject block count, descriptor
count, logical page, record index, flags, raw length, physical extent,
and empty count after simulated submission, along with valid
two-block success and early-acknowledged staged readback retention.

A separately compiled executable strips out the finalization
preflight and reproduces actual partial publication: after fault injection
changes a two-block physical extent to cross the target's usable bound,
the old finalizer commits block one before the mapping admission for
block two detects the invalid physical block. The repaired finalizer
rejects the complete batch first and publishes neither mapping. Both the
production executable and deliberately broken variant are required
by the existing mandatory kernel, combined, and teardown source
workflow coverage.

No loaded module, DM, swap, NBD, loop, privileged operation, fault
injection into real devices, physical backing or kernel runtime test
was performed. These rootless tests do not qualify arbitrary-memory
corruption recovery, real kernel I/O lifecycle, power-loss behavior,
or policy/performance selection. V2.2 policy/batch winner remains
**UNDETERMINED**.

## Exact-revision evidence

Record exact PR and post-merge workflow identities and conclusions
before advancing this candidate to a qualified implementation. Native
Linux compilation evidence obtained independently by Codex must be
pinned to the SHA actually tested.
