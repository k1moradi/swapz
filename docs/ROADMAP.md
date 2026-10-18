# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `e5c172177242e3f7edcc6e470989eb3a71a43e92` passed all
five qualification stages and is the current scheduling baseline. It keeps the
bounded accepted-wave preparation kick, the singular-head anti-convoy cushion,
one-for-one tail credits and the compact raw/sync controls.

On the slow RAM model, mixed QD32 async is effectively neutral versus sync:
7.09 versus 7.08 MB/s, with 545.5 lower WRITE requests and 11.82 ms READ p99.
On the faster model, async reaches 23.74 MB/s versus 19.71 MB/s sync, while
lower WRITE requests fall to 874.5 and mixed READ p99 reaches 2.10 ms. Against
the preceding qualified `5aeae47` run, faster-model async useful WRITE is up
about 12%, lower WRITE requests are down about 15%, and worker-empty deadline
closes fall from 70.2 to 60.5 per pair. Lower WRITE bytes and packed-read byte
savings remain intact.

The accepted-wave result is therefore progress for mixed scheduling, but its
idle-time attribution exposes the next bottleneck. Faster-model mixed spends
70.6 ms in LZ4 and 183.9 ms in synchronous lower WRITE service, yet only 3.8 ms
of producer LZ4 is proven wholly inside lower-WRITE waits. Ordered preparation
blocking is only 0.58 ms, so the problem is not a completion convoy; most useful
compression is still scheduled outside the device-wait interval. The
write-only pilot remains directional only: QD8 preserves 520 lower WRITE
requests and async is 18% above its same-run sync control, but its 21.80 MB/s
absolute point is below the earlier 29.75 MB/s one-pair observation and must not
be treated as a confirmed regression. QD1 still has zero producer claims.

Loaded GC victims remain zero, so endurance claims are still limited to the
demonstrated proxy: fewer lower bytes/requests for the same verified logical
workload. Wear distribution and block-reuse behavior are not yet qualified.

## Immediate work queue

1. Keep the accepted-wave ownership policy and change only LZ4 preparation
   placement: use a CPU-local `WQ_MEM_RECLAIM` preparation workqueue while the
   ordered Device Mapper worker remains `WQ_MEM_RECLAIM | WQ_UNBOUND`.
   `queue_work()` then targets the issuing CPU, allowing pending LZ4 work to
   consume that CPU's otherwise-idle interval when the ordered worker sleeps in
   synchronous lower WRITE I/O instead of immediately competing on another CPU.
2. Preserve producer non-reentrance, the singular-head guard, bounded prepared
   slots, one-for-one tail pacing, head-first claims during lower WRITE,
   sole ordered mapping/publication/completion ownership, retained-window
   policy, extent planning, lower-byte/read policy and GC behavior.
3. Accept the CPU-local placement only if faster mixed stays near or above
   23.74 MB/s, lower WRITE requests stay near or below 875, worker-empty
   deadlines stay near or below 60.5, and full LZ4-in-lower-WRITE overlap rises
   above 3.8 ms without materially increasing the 0.58 ms ordered preparation
   wait. Slow-model mixed must remain neutral rather than lose useful WRITE.
4. Keep QD1 producer claims at zero. Preserve write-only QD8/QD32 request
   geometry near 520/~139 and treat their one-pair throughput only as
   directional. Lower WRITE bytes, packed-read byte savings and read-tail
   behavior remain hard gates.
5. If CPU-local placement only trades away same-run async/sync throughput
   without increasing useful lower-I/O overlap, reject it and remove the code;
   do not stack another scheduling heuristic on top of an unqualified one.
6. After scheduling is stable, add release evidence rather than more heuristics:
   kernel-worker CPU attribution, statistically repeated matched performance,
   sustained GC with nonzero victims and explicit reuse/wear-distribution
   evidence, plus genuine lower-error coverage.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
