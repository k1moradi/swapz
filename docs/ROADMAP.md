# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `d63ab97c6cb104dc99c4792c207805e97e22d233` passed all
five qualification stages. Direct single-bvec BIO-to-LZ4 input remains a
validated win: faster-model explicit WRITE-copy cost is about 4.0 ms / 11.0 MiB
versus 22.4 ms / 59.4 MiB before that optimization. Faster mixed async reached
20.87 MB/s versus 19.73 sync (+5.8%, preliminary) with 1078 lower WRITE
requests; write-only QD8 reached 27.00 versus 19.58 MB/s (+37.9%) with 524
lower requests. These one/two-pair performance results remain directional.

The serialized commit split is stable: faster-model non-I/O commit is 48.5 ms,
with 5.2 ms plan, 16.5 ms pack, 18.5 ms publish and 8.4 ms residual. Explicit
source review shows pack still scans each compressed payload for CRC before
copying it into `bulk_scratch`, while publish independently validates the final
`bulk_scratch` image and its payload CRCs before mapping authority changes.

The attempted per-callback kernel-worker CPU metric based on
`task_cputime_adjusted()` is rejected as a portable measurement. Short
nonblocking preparation callbacks can complete before scheduler accounting
commits their current slice on some kernel accounting configurations. Direct
`current->se.sum_exec_runtime` has the same pending-slice problem, while the
scheduler helper that explicitly includes the live slice is not an exported
module API. Production therefore must not report either value as exact worker
CPU.

The next candidate replaces that misleading metric with portable callback-active
wall upper bounds. Ordered active wall subtracts the already measured
synchronous lower READ/WRITE and preparation-completion waits; preparation active
wall has no intentional sleep. These values can still include preemption, so
they are evidence bounds rather than CPU time.

The same candidate safely precomputes payload CRC32C during foreground
compression and passes it into SWZ3 packing. This removes only the source-buffer
CRC rescan in pack. Publish still recomputes CRC over the final
`bulk_scratch` image after lower completion, preserving the fail-closed
copy/integrity boundary. Additional diagnostic subsets separate stage,
batch-pause/hash, hole clear, resume/hash, initial publish validation, repeated
lookup validation and mapping mutation.

A diagnostic-only PACK_READY probe records the delay from a dry-close decision
to the first later WRITE admission. It does not wait, recheck or change close
policy. This will test whether request fragmentation is caused by microsecond
userspace wave-submission gaps before any new credit/retention heuristic is
introduced.

Loaded GC evidence is now a mandatory owned-RAM gate in the next candidate. A
fresh 16MiB swapz mapping on the positively identified `null_blk` lower is
filled and then subjected to deterministic scattered overwrite pressure. The
oracle tracks each logical page's latest generation and verifies all 4096 pages
afterward. Qualification requires at least four completed live-victim rotations,
nonzero relocation reads/writes, multiple victim and destination segments, and a
nonfailed target. Per-segment victim/destination counts provide initial reuse
distribution evidence. This is still synthetic RAM evidence, not a physical
flash-endurance claim.

## Immediate work queue

1. Qualify foreground precomputed payload CRC. Acceptance requires lower pack
   time or ordered active-wall work without weakening final-image CRC
   verification, lower-request geometry, read tails or lifecycle correctness.
2. Use publish sub-attribution to determine whether repeated metadata validation
   inside `swapz_lookup()`, payload CRC itself, liveness checks or mapping
   mutation dominate the 18-22 ms publish phase. Do not remove any fail-closed
   check until an equivalent validated-once path is separately qualified.
3. Use stage/pause/hash/hole/resume sub-attribution to explain the residual
   commit bucket before changing transaction snapshot protection.
4. Use dry-close arrival histograms to validate or refute the wave-chopping
   hypothesis. Only if many later WRITE admissions cluster shortly after
   PACK_READY closes should a bounded credit/retention experiment be attempted.
5. Keep bound/CPU-local preparation and "maximize overlap" experiments rejected
   and absent. More preparation workers remain blocked until evidence shows
   eligible backlog rather than merely insufficient credits.
6. Require sustained loaded GC rotations and byte-exact verification in every
   complete qualification. After rotation/reuse distribution is stable, test
   dead-segment DISCARD/TRIM as a separate lower-device/endurance experiment.
7. Add statistically repeated matched mixed/QD8 trials before confirmatory
   performance claims.

## Deployment topology roadmap

For one shared backing device, retain one global ordered swapz storage authority:
one physical allocator, extent packer, mapping publisher, barrier/FUA owner and
GC/reuse authority. Future NUMA work may use page-home preparation domains with
node-local LZ4 work memory and prepared-page pools feeding that single authority;
it must be tested on real multi-node hardware before becoming policy.

For systems with physically node-local NVMe devices/PCIe roots, one complete
swapz target per NUMA node and local backing device is an explicit future
deployment topology. That arrangement can isolate both RAM and storage traffic,
but it is a deployment/hardware experiment rather than a reason to split one
shared device into independent authorities.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
