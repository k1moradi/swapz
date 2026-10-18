# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7` remains the
accepted directional performance baseline. Source
`6330cb5d264a7cf563f4a161c29ac9ccd1d3e08b` passed all five stages and is
qualified exploratory evidence, but is not promoted.

The persistent preparation-credit experiment solved producer starvation without
damaging write-only geometry. QD1 async still recorded zero producer claims.
On the faster model QD4/QD8/QD32 producer-tail claims rose to
2026/2071/2142, while QD8 retained 520 lower WRITE requests and QD32 retained
138. Faster QD32 sync also improved to 45.45 MB/s after moving the serialized
ordered worker to `WQ_UNBOUND`.

The remaining preparation problem is now directly measured as head collision.
Faster-model blocking waits were 943/1373/1941 against
2029/2074/2164 handoffs at QD4/QD8/QD32: roughly 46%/66%/90%. A nominal tail
claim on a singular preparation list is the FIFO head, so staggered arrivals
turn the intended two-ended scheme into ordered-worker completion waits.

Mixed behavior exposes a second bounded issue. Slow mixed remained efficient at
about 544.5 async lower WRITE requests with only 4.0 worker-empty deadlines.
Faster mixed async rose to 1155 lower WRITE requests, 77.8 worker-empty
deadlines and 160.2 one-page PACK_READY closes, while useful WRITE throughput
was 20.40 MB/s. Read/fence evidence is therefore surviving a dry-tail nonempty
close long enough to authorize later singleton closes in the same worker pass.

The write-only pilot remains one pair per mode/QD with no confidence interval,
and the loaded run again reported zero GC victims. No physical-media or
endurance claim is permitted.

## Immediate work queue

1. Keep the `6330cb5` credit lifetime, unbound worker placement, retained
   targets, extent planning, lower-byte policy, read policy and GC unchanged.
2. Outside `lower_write_active`, never consume a preparation token when
   `preparation_incoming` is singular. Leave the sole FIFO head and its credit
   for ordered inline steal; claim only a true tail behind at least one head.
3. Preserve the credit when the producer rejects a singular queue so the next
   admitted companion can create an eligible two-entry head/tail split.
4. Consume `retained_window_read_bypasses` and
   `retained_wave_interrupted` after a real nonempty close at a refreshed dry
   tail. Keep the existing zero-count early return so empty READ/ZERO processing
   cannot erase retained evidence prematurely.
5. Acceptance requires QD1 producer claims to remain zero, QD8/QD32 lower
   requests to stay near 520/~138, producer-tail work to remain substantial,
   and blocking waits to fall sharply below handoffs. Faster mixed async lower
   WRITE requests and one-page PACK_READY closes should move back toward the
   prior ~950-1040/~90-140 range without increasing lower WRITE bytes or
   degrading packed-read tails.
6. Do not claim a performance improvement from the one-pair write-only sweep.
   Statistically repeated saturation, sustained GC, genuine lower errors,
   kernel-worker CPU attribution and long-run resource pressure remain release
   gates.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
