# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7` remains the
accepted directional performance baseline. Source
`b35a72cb5cc92bbb3bbe58b58a031985b62595a4` also passed all five stages and
is useful exploratory evidence, but is not promoted: QD4 requests fell
materially in async mode while faster-model async QD4 useful throughput also
fell, so request reduction alone does not satisfy acceptance. It retained the 512-entry metadata-LRU random-read savings, reduced
slow mixed-QD32 lower WRITE requests to about 762-764 with only two mean
deadline closes, and recovered write-only QD8 to about 0.89x raw on the slow
model and up to 0.77x raw on the faster model. Faster-model async mixed QD32
reached 22.57 MB/s versus 20.02 MB/s raw in the bounded synthetic model.

QD4 remains the clearest unresolved write-path loss: roughly 2025-2048 lower
WRITE requests for 4096 medium writes, about two lower requests per four-write
wave, with useful throughput only about 0.60-0.70x raw. The write-only pilot is
one pair per mode/QD and has no confidence interval, so these are directional
engineering signals, not confirmatory performance claims. Live GC was not
exercised.

## Completed cleanup after that baseline

- Removed duplicate metadata parsing/CRC work from the compressed read path while retaining current authority, sequence and payload CRC checks.
- Removed the rejected cap=3/uncapped planner-stat diagnostics from the production write hot path, status and official report schema. The accepted-burst production planner remains capped at two cold read blocks per record.
- Removed the standalone research kernel module and retired C++ model.
- Removed historical compatibility, NBD, recall, pressure and obsolete evidence-model infrastructure from the active working tree.
- Made implementation/report/workflow terminology version-neutral; SWZ3 remains only the format identity.

These cleanup revisions, the alignment-aware adjacent lower-run tie-break and the accepted-incoming first-pack tail fix are covered by the owner-loaded `c4539b3...` baseline.

## Immediate work queue

1. Qualify adaptive retained-burst width learned only from finite admitted
   tails observed after synchronous lower writes, with one-deadline downward
   adaptation for a smaller multi-record stream.
2. Report write-only QD window bins plus pack/deadline/idle closures. Accept
   request reductions only when they come with acceptable useful throughput,
   lower bytes, QD1/QD8 behavior, read tails and correctness.
3. Keep the accepted-burst planner read cap at two and physical layout policy
   unchanged. If large windows still issue multiple requests, then investigate
   lower-run/allocator geometry separately.
4. Keep asynchronous-preparation QD1 scheduling as a separate experiment after
   burst closure stabilizes.
5. Add statistically repeated saturation only after policy stabilizes; keep
   sustained live GC, genuine lower errors and resource pressure as open gates.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
