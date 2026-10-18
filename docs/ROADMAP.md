# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `39e7787b784410140cf90d3fe3a08ad4d674f4f2` passed all
five qualification stages. Direct single-bvec BIO-to-LZ4 input hit 12,301
foreground pages in each mixed regime and reduced explicit write copying from
22.4 ms / 59.4 MiB to 3.9 ms / 11.0 MiB on the faster model and from 32.8 ms /
57.5 MiB to 4.7 ms / 9.1 MiB on the slower model. Faster mixed async reached
21.22 MB/s versus 19.89 sync (+6.7%, preliminary) with 1051.5 lower WRITE
requests and 2.69 ms READ p99. Faster write-only QD8 reached 25.50 versus
19.84 MB/s (+28.5%) with 520 lower requests. QD1 remained producer-free.

This is a qualified CPU/memory-path improvement over `c6d15ca`, but it has not
recovered the stronger historical faster-model mixed result from `e5c1721`
(23.74 MB/s, 874.5 lower WRITE requests, 2.10 ms READ p99). Request aggregation
and scheduling therefore remain open performance work even though the copy
optimization itself succeeded.

Commit attribution now resolves the faster-model 48.5 ms non-I/O envelope into
5.2 ms planner, 16.4 ms pack, 18.9 ms publish and 8.0 ms residual. The slower
model reports 6.1 / 22.3 / 21.7 / 9.4 ms respectively. Pack includes the
batch-to-bulk payload copy plus initial payload/metadata CRC work. Publish
includes transaction resume, SWZ3 validation/payload CRC checks and authority
publication. Residual also includes staging, batch pause, alignment-hole clears
and loop/control work; it must not be labeled as CRC alone without additional
attribution.

Source review found one remaining avoidable RAW bounce in the inline
single-bvec path: an incompressible mapped page was copied to `input_page`
before unmap and then copied again to `batch_bytes` in bulk mode. The next
candidate stages bulk RAW directly into its batch slot once. In non-bulk mode it
unmaps without a preliminary copy and lets `swapz_raw_write()` perform the
single required BIO copy after older windows drain.

The next candidate also adds scheduler-accounted task CPU time for the ordered
and preparation workqueue callbacks using the exported
`task_cputime_adjusted()` API. This is diagnostic task CPU time, not wall time,
and excludes callback sleep according to scheduler CPU accounting. It avoids
direct dependency on `current->se.sum_exec_runtime`, whose raw value can omit
the currently executing slice.

Loaded GC victims remain zero, so endurance claims are still proxy-only: lower
bytes/requests are demonstrated, but sustained victim rotation and physical
reuse distribution are not yet qualified.

## Immediate work queue

1. Qualify the inline RAW no-bounce change. Explicit write-copy bytes/time
   should fall only to the extent RAW inline pages occur; compressed behavior,
   request geometry and lifecycle semantics must remain unchanged.
2. Collect ordered-worker and preparation-worker task CPU deltas in the mixed
   path. Keep these separate from wall counters; do not add worker CPU to LZ4,
   commit or lower-I/O elapsed time.
3. Use the 39e7787 commit split to decide the next serialized-path experiment.
   Publish (18.9 ms faster-model) and pack (16.4 ms) are the leading measured
   phases. Add isolated CRC/copy attribution before removing transaction or
   payload validation; preserve fail-closed generation and authority checks.
4. The QD8 +28.5% directional result keeps multi-credit and N=1/2/4 producer
   experiments alive, but do not stack them with this RAW/CPU-attribution run.
   Kernel-worker CPU evidence comes first.
5. Keep QD1 producer claims at zero and preserve QD8/QD32 lower-request
   geometry near ~520/~139. Lower bytes, packed-read tails and lifecycle
   correctness remain hard gates.
6. After CPU/CRC attribution stabilizes, run repeated matched statistics, then
   evaluate bounded multi-worker/NUMA locality. Separately force sustained GC
   with nonzero victims before testing segment reuse distribution or lower
   DISCARD/TRIM.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
