# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `c6d15ca56753610ed21d805333a49b6a291a36cb` passed all
five qualification stages with the accepted unbound scheduling policy and new
kernel-C copy/non-I/O attribution. Slow-model mixed async remained effectively
neutral versus sync at 7.12 versus 7.06 MB/s with 544 lower WRITE requests.
Faster-model mixed async reached 21.04 MB/s versus 20.04 sync with 1027 lower
WRITE requests and 2.38 ms READ p99. Faster write-only QD8 remained the clearest
directional async opportunity at 23.73 versus 19.87 MB/s (+19.5%) with 524 lower
WRITE requests; QD1 still had zero producer claims.

The new attribution identifies two concrete write-side costs. Faster-model mixed
spent 83.6 ms in LZ4, 22.4 ms copying 59.4 MiB explicitly in dm-target, and
46.2 ms in write-engine commit work after subtracting synchronous lower WRITE.
Packed-read output copying was only 1.1-1.4 ms and is not a current priority.
Source inspection also shows that engine commit copies compressed payloads again
into `bulk_scratch`, computes payload CRC32C while packing, then revalidates
metadata/payload CRCs during authoritative publication. Batch pause/resume also
hashes transaction snapshots. Those validations remain correctness barriers
until timing proves which portion is worth redesigning.

The next candidate therefore changes only two evidence-backed areas: the common
single-segment 4KiB WRITE BIO is mapped directly for LZ4/zero scanning instead
of first copying into an input scratch page, while multi-segment BIOs and RAW
lifetime fallbacks retain the existing copy path; and the engine reports
separate planner, pack and post-I/O publication wall times. No scheduling,
extent geometry, mapping publication, lower-I/O or GC policy changes accompany
this experiment.

Loaded GC victims remain zero, so endurance claims are still proxy-only: lower
bytes/requests are demonstrated, but sustained victim rotation and physical
reuse distribution are not yet qualified.

## Immediate work queue

1. Qualify direct single-bvec WRITE input. It should reduce
   `write_copy_wall_ns`/bytes while preserving LZ4 results, lower WRITE
   geometry, useful throughput and all fail-closed behavior. Report direct-input
   page hits so a no-effect run can be distinguished from a missed fast path.
2. Split `window_commit_nonio_wall_ns` into engine planner, pack and publish
   phases. Planner measures bounded extent selection; pack measures
   begin/append/seal including the payload copy and first CRC; publish measures
   batch resume plus finish/revalidation/mapping publication after lower I/O.
   Their sum must not exceed total commit non-I/O time; the residual remains
   stage/pause/allocation/hole-clear/loop overhead.
3. Do not remove payload/metadata revalidation or precompute-and-trust CRCs until
   the new phase counters prove publish/CRC cost is material and a replacement
   preserves exactly the same fail-closed authority checks.
4. Do not add multi-credit or multi-worker scheduling in this run. The QD8
   directional gain makes those ideas worth revisiting later, but first isolate
   copy/commit effects from scheduling effects.
5. Keep QD1 producer claims at zero and preserve QD8/QD32 request geometry near
   ~520/~139. Lower-write bytes, packed-read tails and lifecycle correctness
   remain hard gates.
6. After copy/commit attribution stabilizes, add kernel-worker CPU attribution,
   then evaluate N=1/2/4 preparation workers, NUMA locality, sustained GC with
   nonzero victims, segment-reuse distribution and safe lower discard/TRIM.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
