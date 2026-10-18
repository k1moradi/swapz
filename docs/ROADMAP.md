# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `e5c172177242e3f7edcc6e470989eb3a71a43e92` remains the
accepted scheduling baseline. It passed all five qualification stages with the
bounded accepted-wave preparation kick, producer-side singular-head cushion,
one-for-one tail credits and both ordered/preparation workqueues unbound.

On the faster RAM model, that baseline reached 23.74 MB/s async mixed WRITE
versus 19.71 MB/s sync, with 874.5 lower WRITE requests, 2.10 ms mixed READ p99
and 60.5 worker-empty deadline closes. The slow model remained neutral at
7.09 MB/s async versus 7.08 MB/s sync. Lower-write byte savings and packed-read
byte savings remained intact.

Source `e199ac5399808fbf3dcf470989eb3a71a43e92` tested CPU-local preparation.
It increased proven LZ4-inside-lower-WRITE overlap on the faster model from
3.8 ms to 6.4 ms and nearly eliminated ordered preparation wait, but the useful
path regressed: async mixed WRITE fell to 20.37 MB/s, lower WRITE requests rose
to 1055, and worker-empty deadline closes rose to 72.5. Faster write-only QD8
also fell below its same-run sync control while request geometry stayed at 520.
The CPU-local placement is therefore rejected and deleted from production.

The next bottleneck is CPU/memory attribution, not another scheduling heuristic.
Current C timing proves lower WRITE remains the largest wall interval and LZ4 is
the largest explicitly timed CPU stage, but explicit BIO/scratch/batch copies,
packing/CRC work and authority processing are not separated. The next source
restores the accepted unbound scheduler and adds kernel-C timing/byte counters
for explicit RAM copies plus engine processing with synchronous lower-I/O wait
subtracted.

Loaded GC victims remain zero, so endurance claims are still proxy-only: fewer
lower bytes/requests are demonstrated, but sustained victim rotation and
physical-block reuse distribution are not yet qualified.

## Immediate work queue

1. Requalify the accepted unbound preparation placement with the new C
   attribution only; do not add another scheduler heuristic in the same run.
2. Measure WRITE explicit-copy wall time/bytes, READ output-copy wall time/bytes,
   write-engine commit non-I/O time and read-engine non-I/O time. Keep LZ4,
   lower-I/O and preparation-wait counters as independent controls.
3. If explicit copy time is material, optimize the common single-4KiB-BIO path
   by feeding LZ4 directly from a mapped BIO page and/or decompressing directly
   into the mapped read BIO, retaining the existing copy path as the fragmented
   BIO fallback. Do not pin producer buffers across window commit merely to
   avoid one memcpy unless bounded-pool pressure is separately proven safe.
4. If commit non-I/O dominates instead, profile the SWZ3 build path as a coarse
   phase before changing CRC, packing or authority logic. Preserve byte-exact
   format, ordering and fail-closed publication.
5. Keep QD1 producer claims at zero and preserve faster-model mixed behavior
   near the accepted 23.74 MB/s / ~875-request / ~60.5-worker-empty result.
   Preserve QD8/QD32 request geometry near 520/~139. Lower-write bytes and
   packed-read tails remain hard gates.
6. After scheduling and CPU/memory attribution stabilize, add kernel-worker CPU
   attribution, statistically repeated matched performance, sustained GC with
   nonzero victims and explicit segment-reuse/wear-distribution evidence, plus
   genuine lower-error coverage.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
