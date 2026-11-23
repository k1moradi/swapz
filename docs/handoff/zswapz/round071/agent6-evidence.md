# Round071 Agent6 — cooperative natural-pressure scheduling evidence

**Status:** Host-only deterministic cooperation model; never original Linux MM,
original zswap selected STORED eviction, real source authentication, real DM
upper BIO ownership, physical media, durable lower FUA, or a memory-pressure
benchmark. `PHASE_A=BLOCKED`, source auth=0, direct compressed handoff OFF,
forced RAW bypass OFF, imported codecs ACTIVE0. No production C changes.

## Executable policy and ownership

The exclusive C model includes the real read-only `zswap-import-codec.h`,
`zswap-direct-handoff.h` and `codec.h` at CI checkout. It treats a natural
MM eviction event as *input*, never makes a secondary eviction/reclaim choice,
and refuses synthetic/retired/stale source, invalid codec, lost original lock,
queue overload, or excessive compressed length. A bounded owned memcpy occurs
while the *modeled* source lease exists; lower service, pack, and FUA simulation
are forbidden under both modeled locks. The queue is 8 entries; copied
compressed bytes are bounded by `8*3568=28544` bytes, with actual full 4096
ordinary fallback guarded separately. FIFO selection packs opaque original
LZO1X or raw LZ4 bytes into data-only padded 4/8/16KiB extents; it neither
decodes nor recompresses them. Each transient mapping preserves original codec,
version-agnostic generation, and ORIGINAL_COMPRESSED vs conventional
uncompressed RAW_4096 identity. MM/codec source lifetime and real reader
leases are **not** conferred by this model.

Successful lower-write/FUA is modeled *before* RAM mapping publication and
once-only modeled upper completion; lower failures, missing FUA, allocation
failure, close, duplicate completion and GC with reader pins all fail closed.
Preexisting SWAPSPACE2 first-4096 bytes remain unchanged. C counters are
explicit simulation counters, not kernel telemetry or hardware measurements.

## Reproducible test

```sh
python3 -B tests/tools/round071-natural-pressure-cooperation-verify.py \
  --json round071-evidence/host-policy.json \
  --ktap round071-evidence/host-policy.ktap
```

The runner requires source/gate anchors from original repo headers, compiles
and runs the host fixture with both GCC and Clang in strict C23 mode
(`-Wall -Wextra -Wconversion -Wshadow -Werror`) and ASan+UBSan, then compiles
and **executes** 24 independent source-C mutations per compiler. A mutant
survives if its exact expected `FIRST_ERROR line=... check=...` denial is
not observed, or if a sanitizer/crash/compile failure appears. The produced
JSON and KTAP describe *host-model* cases only and cannot be mistaken for
original pinned Linux KUnit output.

### Independent local preparatory smoke (not exact-source confirmation)

A temporary local header-only stand-in reproducing published ABI constants was
used solely for preliminary fixture compilation. Both GCC and Clang C23
strict ASan+UBSan baseline executed successfully, with `directed=27`,
`burst_events=128`, all 4/8/16KiB extent classes, `copy_bytes=70400`,
`lower_padded_bytes=81920`, `fua=8`, `upper_ack=32`,
`queue_peak=8`, `owned_peak=17600`, zero modeled secondary reclaim/recompression.
24/24 compiled and executed semantic mutants rejected with GCC and 24/24 with
Clang (48 total). **This smoke does not prove original repo-header linking**:
the exact GitHub Actions result must be reported separately after publication.

### Remaining production gates

No genuine original Linux zswap MM decision, swpentry/folio/XArray ownership,
source buffer authentication, original LZO1X/raw LZ4 decoding, codec retirement
lease, real lower FUA/durability, GC reader pin, or real upper BIO ACK is proven
by this host-only model. No package, device, kernel module, swap activation,
real memory pressure or privileged test is executed. The Round070 original
native reader-pin/GC 3/4 blocker remains Agent5-owned; this task does not waive
or repair it.
