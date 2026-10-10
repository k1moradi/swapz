# V2.2 upper preflush, FUA and physical-batch completion audit

## Scope

Production source inspected: `kernel/dm-swapz.c`, especially
`swapz_process_bio`, `swapz_process_flush`, `swapz_map`,
`swapz_stage_write_block`, `swapz_submit_stream_buffer`,
`swapz_finalize_stream_buffer`, `swapz_reap_inflight`, and
`swapz_io_worker`. The prior exact-production-C async and
generation tests remain mandatory.

The source audit did **not** demonstrate a new production defect.
Keep the existing kernel implementation unchanged. In particular,
do not claim that an upper BIO's admission into a RAM buffer proves
physical persistence.

## Durability/ownership state transition table

| Upper operation | Prior work before current operation | Lower batch flags / action | Upper completion and limitation |
|---|---|---|---|
| Plain compressed staged write, no FUA | Commit previous generation if necessary | Current record staged in memory; later batch submit | May acknowledge from RAM before lower completion; **not** durable |
| Compressed staged `REQ_FUA` | Per-page prior generation barrier | Include FUA in `buffer->write_flags` and lower dm-io write request | No early completion; remaining BIO completes after lower callback and mapping publication |
| Raw `REQ_FUA` | Same prior generation barrier | Raw block participates in lower FUA flag aggregation | No compressed early-ack path; waits for lower completion |
| Batch containing FUA and non-FUA records | Serialized stage and bounded batch | Bitwise OR FUA into batch; may cause stronger durability semantics for other records | FUA BIO cannot use staged early completion, plain compressed BIO can |
| `REQ_PREFLUSH` plus nonempty write | Flush pending pack, drain lower batch, issue backing flush | Only after successful preflush dispatch the current write, preserving its FUA flag if requested | Failed preflush denies the current write and latches target failure |
| Zero-sector `REQ_OP_WRITE | REQ_PREFLUSH` | Flush pending pack and lower batch, issue backing flush | No current payload write | Complete once on successful flush; earlier barrier error propagates |
| `REQ_OP_FLUSH` | Flush pending pack then batch | Issue backing flush | Complete only after successful lower flush, or once with error |
| Prior lower batch or flush failure | Abort before next current write | No additional backing flush after an earlier failed stage | Fail upper operation and freeze target |
| Async lower write failure | Source data remains resident if previously acknowledged and current | Callback records failure; reaper processes it | Pending non-early upper BIO fails; acknowledged staged data must not be reclaimed |
| Watchdog timeout with late callback | Freeze target but retain lower-owned stream memory | Late callback publishes completion token | No premature buffer recycling, false durability claim, or double upper completion |

The actual durability of `REQ_FUA` depends on the lower block layer,
the device implementing FUA/flush correctly, dm-io honoring submitted
flags, and correctly ordered callbacks. These are *not* validated by
the rootless suite.

## Executable source qualification

`tests/runtime/swapz-flush-fua-contract-test.py` extracts **verbatim**
production `swapz_process_flush`, `swapz_process_bio`, and
`swapz_stage_write_block` C functions and compiles two independent
userspace binaries with `cc -std=c11 -Wall -Wextra -Werror`.

The dispatch harness checks 13 normal/error scenarios, including
preflush-before-write, combined preflush/FUA, empty flush writes,
pack/batch/backing-flush rejection, ordinary write failure after a
successful preflush, FUA without an unrequested preflush, flush
dispatch, discard/read preflush and denial after target failure.

The batch staging harness checks seven scenarios: plain compressed
staged early completion, FUA exclusion from early completion, mixed
FUA/plain compressed records, nonstaged/raw behavior, compaction,
physical-block reservation error, invalid fill owner and FUA priority
flag aggregation.

Six source mutation tests reject dropped lower FUA flags, omitted
preflush, premature FUA early completion, missing flush completion,
or lost empty-preflush admission. Source-order checks bind the
batch-flag propagation to the real dm-io request constructor and the
normal lower callback finalizer.

The suite contains nine Python test methods driving **20 executable C
scenarios** and six negative source mutants. Mocked functions include
BIO admission/completion, backing flush, physical reservation, segment
accounting and lower I/O. No Linux block layer, dm-io, LZ4 or
hardware persistence is executed.

A removed executable gate is rejected by the mandatory rootless
workflow-contract suite. The isolated kernel workflow as well as
rootless combined and teardown run the new bounded gate, and NBD
source safety continues to run independently.

## Exact-revision CI

Qualified executable SHA:
`83d2e41d7d72e7dbedb3ad5860b0dc4359aac988`.

- [Isolated kernel source 38039036487](https://github.com/k1moradi/swapz/actions/runs/38039036487):
  PASS; 9/9 new FUA tests, 22/22 async tests, 21/21 generation,
  15/15 GC compressed, 17/17 GC source and 30/30 range.
- [Combined rootless 38039036567](https://github.com/k1moradi/swapz/actions/runs/38039036567):
  PASS at the identical SHA, new FUA gate and 23/23
  workflow-contract checks; NBD stress 25/25.
- [Teardown rootless 38039036488](https://github.com/k1moradi/swapz/actions/runs/38039036488):
  PASS at the same SHA, new FUA gate and existing safety suite.
- [Standalone NBD source 38039036489](https://github.com/k1moradi/swapz/actions/runs/38039036489):
  PASS on the same SHA.

## Residual blockers

Source-level C tests do not prove actual block media durability,
real asynchronous dm-io scheduling, post-crash recovery, stale
device-cache writeback, or privileged backing release. A separately
authorized disposable kernel/device environment must exercise FUA
and PREFLUSH under real write faults, timeout, power-loss modeling,
raw/compressed mixed batches and repeated suspended/resumed GC.

The trust boundary for genuine GNU dd, privileged process containment
and authenticated DM/loop I/O drain remains Codex/production-owner
work, not the subject of this kernel-only qualification.

No real DM, loop, NBD, swap, module, pressure, reboot, physical
device, or destructive cleanup operation was performed by this task.
V2.2 strategy and batch winner **UNDETERMINED**.
