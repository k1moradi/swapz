# Corrected rootless extent allocator — Issue #33

**Research only.** A deterministic single-worker Python model of aligned compressed extents, byte-exact serialization, staged/in-flight/committed mapping authority, finite space, and explicit write failure. This is **not** a proposed kernel wire-format migration, GC simulator, crash-consistency proof, or real storage benchmark.

## Run

From the repository root (no root privileges, no I/O devices):

```bash
python3 -B research/sizeclass/impl/test_allocator.py -v
python3 -m compileall -q research/sizeclass/impl
```

Tested source files: `allocator.py`, `wire.py`, `test_allocator.py` at Git blob SHAs `30cd5f008c5fd6e9f12e9980cdb2ac0e4c4c4c77`, `30ea5010600b8d76ef6ac1f9952329ee8cee498c`, `9b111eda1af160d83dcb45591fb6b31767ef5457`. Local rootless run: **19 tests passed**, seed `0x5A17` for mixed-overwrite replay. No CI run or independent external-host reproduction is claimed for this branch. The historical `legacy/` scripts were not modified; their five original defect tests remain deliberately red.

## Modeled extent format

All values are little-endian; extents are 4096-byte-block aligned.

- Header: `<IHH`, 8 bytes: magic `0x53575A53`, experimental version `1`, descriptor count.
- Descriptor: `<IHH`, 8 bytes each: 32-bit logical slot, 16-bit absolute payload byte offset, 16-bit compressed payload byte length.
- The complete descriptor table **precedes** all payloads; payload offsets are computed only after final group size is known.
- Allowed compressed extents: 4/8/16/64 KiB, at most 64 records, each compressed payload 1–3568 bytes. A raw fallback requires the full original 4096-byte page and occupies a separate 4 KiB extent.
- Volatile mapping metadata carries the separate generation number and raw flag. No codec ID, CRC or durable restart/recovery protocol is implemented.

## Event and resource contract

`write()` stages an immutable payload and returns a **non-completed** ticket. Count-bounded or tick-deadline flush serializes and submits one or more extents; no authoritative disk mapping is published. `complete()` commits **only after a whole extent succeeds**, marking its upper tickets completed. An explicitly failed/torn extent does not update mappings or acknowledge its upper tickets. Committed older generations survive failures; an out-of-order stale success cannot displace a newer successful generation. Sibling references are independent.

Bounded parameters: `max_staged_records`, `flush_deadline_ticks`, `max_in_flight_extents`, `max_physical_bytes`. Space is conservatively retained even after a simulated failure because GC and safe reuse are not yet modeled. `submitted_physical_bytes` counts submitted full extents; `completed_physical_bytes` counts blocks the failure injector reports completed (including torn extents); `successful_physical_bytes` counts only fully successful extents. `completed_logical_bytes` counts successful upper writes only. These are *modeled*, not measured lower-device counters.

The `sequential` policy and `best_fit` policy see only the same records already staged within the same bounded flush window. With 8×2200-byte then 8×1600-byte synthetic records in one 16-record window, they respectively submit 12 and 8 physical 4 KiB containers. Separating them at an 8-record flush boundary prevents the hypothetical eight pairings. This result is a geometry/model assertion, **not** a kernel improvement measurement.

`read()` reports the number of 4 KiB blocks touched by the mapped **payload byte range only**; any additional metadata fetches, whole-extent reads, lower device overhead, contention and p99 effects are **not** modeled.

## Limitations and next integration gate

The model is intentionally not thread-safe. Tickets are exposed as mutable Python objects and must be treated as borrowed identity/state handles, not adversarially writable input. Simulated completion ordering is caller-controlled; no real BIO, thread scheduling, atomic disk write guarantee or crash/failover mechanism is established. Extents are retained in RAM for exact readback; no segment placement, reclaim, GC reserve, wear, NAND program traffic or latency is modeled. The current `sequential` model represents ordered in-window packing, not the complete kernel's generation-aware compaction pipeline.

Issue #34 must use a separately tested GC/segment lifecycle before any claim of **net physical-write savings**. No kernel changes, production-swap actions, privileged experiments, merges, or real-media endurance conclusions are authorized by this PR.
