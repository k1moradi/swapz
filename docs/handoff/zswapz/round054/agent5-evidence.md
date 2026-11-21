# Round054 Agent5 — independent rootless native-MM FIFO vs bounded disk packing

Frozen engineering `713541c26f35ed812ebe75bb8c481169bdf98d3b`, frozen task `feb086b499e78a8650fa723a459863fdce6a1c99`. No product, codec, original Linux MM, native policy or peer source changes. Existing Round052/053 fixture and runner preserved exactly; the new comparative fixture and runner Git blobs are `2b24ac2d298dcb08e8bfde0ede5d570cadef195c` and `79669b79d3faca6cec89ed0c6802f15b66e8043c`.

## Local actual compiler executions (not GitHub qualification)

GCC 14.2.0 and Clang 17.0.0: strict C23, -Wall -Wextra -Wconversion -Wshadow -Werror, ASan+UBSan, recovery disabled. Both compiler runs actually execute **48 matched trace pairs (96 policy runs), nine directed cases, and ten separately changed semantic C mutants each**; all mutants compiled then exited 1 with exactly their intended FIRST_ERROR label. The unchanged prior 192-event/21-hostile fixture also executed PASS under both compilers (C2x spelling, same strict sanitizer flags). Local compiler environment used the five exact product geometry macro definitions extracted from frozen codec.h; GitHub CI uses the full checked-out actual header. The local container cannot resolve GitHub for a real full-history Git checkout, so canonical --enforce and git diff --check HEAD^ HEAD must execute against true Git metadata in CI, not fabricated local history.

## Counters from identical deterministic streams, not physical performance

504 accepted arrivals per policy, 435 successes with the identical successful event IDs across all 48 traces, 69 modeled failed writes per policy. Capacities 16/32/64 blocks; data area excludes one protected block and a four-block contiguous rotating synthetic GC reserve. Independent zswap-decode and swapz-compress counters each 504 per policy; upper full original bytes each 2,064,384. Source AUTH is always zero.

| Modeled counter, matched workload | Immediate FIFO | Bounded coalescing |
|---|---:|---:|
| Attempted lower requests | 454 | 314 |
| Attempted lower bytes | 1,859,584 | 1,675,264 |
| Completed padded disk bytes | 1,781,760 | 1,597,440 |
| Completed padding bytes | 518,120 | 333,800 |
| Completed payload bytes | 1,263,640 | 1,263,640 |
| Worst simulated queue wait (ticks) | 0 | 2 |
| Failed accepted events | 69 | 69 |

14/48 traces reduce both padded bytes and requests with identical successful IDs. Aggregate attempted requests decrease by 140; completed padded bytes decrease by 184,320. These are deterministic model counters, **not a production/performance improvement claim**: coalescing increases worst modeled wait and the model assumes instantaneous lower completion within each service tick. No measured CPU cycles, energy, latency, throughput, IOPS or device saturation. The directed GC test separately checks two requested four-block relocations (one injected EIO), one 16,384-byte completed relocation, reserve rotation, all live opaque record prefixes, and stale/ABA cancellation; these relocation bytes are not silently folded into the matched foreground trace table.

## Bounds, decision and limitations

Eight pending full original pages (32,768 bytes of page payload plus fixed metadata), four pages per pack, two-step deadline with bounded drain of at most eight events per tick, 302,000 bytes total modeled static state including fake 64-block disk, header and partition sentinels. Each accepted event gets exactly one terminal ACK in the model, never ACK a refused one, never accept compressed STORED as ordinary RAW_4096. Short/invalid codec length fallback means full original 4096 bytes on the modeled lower RAW path; short disk records are opaque prefixes, not LZ4 or verified full decoded pages. 4/8/16KiB payload extents have checked nonoverlap and zero padding; avoid a 16KiB pack for three pages if it would amplify bytes. If an eligible contiguous pack fails allocation, retry only one page before bounded ENOSPC. Disk reserve is four blocks (16KiB) in this model, deliberately large enough for a largest-class relocation; the directed GC experiment only rotates a whole four-block extent, not a general GC algorithm. No new reclaim, timer feeding MM or ownership acquisition. Reserve, deadline, fairness, never-accepted backpressure, failed durable completion, same-page full 4096 rollback/retry, late token, swapoff/dtr cancellation, ABA and GC epoch mutation checks passed. Mutants target queue capacity, deadline, single-page FIFO, reserve, stale callback, durability, GC epoch, RAW size, cancellation and padding amplification independently. Nonoverlap, header and partition sentinel checks run in the baseline.

If later actual production qualification warrants it, consider a **default-OFF disk-only opt-in** at most eight pending / four records / two synthetic steps translated to a real independently validated finite deadline, preserve sufficient contiguous GC reserve, do not wait for MM arrivals, fail fast or reduce to one normal full page at pressure/capacity limits. This is a conservative model candidate, not an enabled optimization. SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED FORCED_RAW_BYPASS=DISABLED. No owner make test/fast_test, privileged, loaded-module, physical-swap or actual memory-pressure tests. New exact-source CI pending at source commit creation; report its actual terminal results separately.
