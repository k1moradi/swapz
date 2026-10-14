> **Supplemental/historical evidence — not current engineering policy.**
> Version-specific replay rationale; benchmark.md governs comparisons.
> The authoritative standards are [coding_standards.md](../../coding_standards.md),
> [testing_standards.md](../../testing_standards.md),
> [compile.md](../../compile.md), and
> [benchmark.md](../../benchmark.md), alongside README.md and VISION.md.
> Do not use dated branch/reset/active-swap instructions as new permission.

# Three-way swapz benchmark: identical logical data and operations

**Stage: source/rootless contract; no loaded three-way run performed yet.**
Never reboot, use swapon/swapoff, access active /dev/sdb1 or /swapfile, run
on physical/unowned media, or force-remove test devices.

## What "swapz off" means

The **off** arm directly performs uncompressed 4KiB logical I/O against
a freshly created *owned RAM-backed null_blk*. It is the no-compression,
no-DM block-path reference, NOT a Linux VM experiment with swap disabled.
Do not disable host swap. V2.2 and V3 use uniquely UUID-owned DM mappings
to otherwise identically configured fresh memory-backed null_blk. The
two DM modules must be loaded **sequentially**. The upper 4096-page
logical address range, underlying queue profile, operation plan and
content must be the same across all arms.

## One immutable source and one immutable workload plan

Generate *one* fixture once, for example:

    python3 tests/runtime/anon-page-fixture.py --pages 1024 \
      --seed 0x51a0a9 --output-prefix /tmp/swapz-anon-shared

Create *one* immutable trace per workload:

    python3 tests/runtime/threeway-swap-replay.py prepare \
      --fixture /tmp/swapz-anon-shared.bin \
      --output-dir /tmp/swapz-plan-a \
      --seed 0x1234 --logical-pages 4096 \
      --writer-pages 1024 --reader-start 2048 --reader-pages 1024 \
      --layout disjoint --qd 8 --read-pct 20 \
      --warmup-ops 40000 --measure-ops 150000 --iops 5000

Both operation counts must be multiples of QD. The immutable plan
contains a trace.jsonl with exact global sequence number, wave number,
operation type, logical page, input fixture-page index, warmup or measured
phase and expected latest read generation. Each QD-wide wave uses
unique logical pages; all operations in a wave complete before the
next wave. Therefore concurrent completion ordering *within a wave*
cannot change the expected next-wave image. This deliberately controls
dependencies and may not reproduce organic asynchronous timing.

The manifest.json pins:
- The source fixture's SHA256 and exact 4096-byte pages.
- The canonical trace SHA256, random seed and total operation counts.
- SHA256 across every full 4096-byte input WRITE with logical offset,
  operation sequence number and fixture index.
- The initial full logical-image SHA256 and the final image SHA256.
- Read/write counts, QD, regions, offered IOPS and warmup/measurement.

All three candidates must consume the same exact fixture and exact
trace; they are never allowed to regenerate candidate-specific random
operations. The run command validates source hashes before it opens
the target and byte-verifies all READs and all logical pages afterward.
Independent backing-device sysfs statistics are captured only around
the measured phase, excluding prefill, warmup and final verification.

## Strict owned-block gate

The replay program defaults to refusing block writes. For a safely
preflighted block test it requires:
- --owned-nullblk-name nullb_swapz_<unique>
- --expected-lower-dev <actual lower major:minor>
- --expected-dev <actual upper major:minor>
- --expected-dm-uuid <exact test-only SWZ-prefixed UUID> for V2.2/V3.

For the off arm, the upper and lower identities must be the identical
owned null_blk and NO DM UUID must be supplied. For each DM arm, the
device must have the exact expected DM UUID and the *single* backing
sysfs slave must be the owned null_blk. The null_blk must be powered
and memory_backed=1; test target and lower device cannot be mounted or
active swap. Preflight all other DM mapping/module ownership externally.
Never use a physical or active storage device.

Example, with values obtained independently from the test host:

    python3 tests/runtime/threeway-swap-replay.py run \
      --fixture /tmp/swapz-anon-shared.bin \
      --trace /tmp/swapz-plan-a/trace.jsonl \
      --manifest /tmp/swapz-plan-a/manifest.json \
      --candidate v3 --source-sha <PINNED_V3_COMMIT> \
      --device /dev/dm-<TRIAL_DEVICE_NUMBER> \
      --owned-nullblk-name nullb_swapz_<UNIQUE> \
      --expected-lower-dev <NULLB_MAJOR:MINOR> \
      --expected-dev <DM_MAJOR:MINOR> \
      --expected-dm-uuid <OWNED_SWZ_UUID> \
      --result /tmp/swapz-v3-a.json

Repeat independently with frozen V2.2, and with the direct owned
null_blk for off. A separate experiment may compare PR #57 and PR #59,
but *label* its V3 source accurately. A script cannot credibly claim
which production implementation was loaded without module SHA/vermagic,
target type, table and UUID evidence.

Compare:

    python3 tests/runtime/threeway-swap-replay.py compare \
      --reports /tmp/swapz-off-a.json /tmp/swapz-v22-a.json \
                /tmp/swapz-v3-a.json

The comparator **refuses** missing arms, corrupted READs, different
fixture/trace/payload SHA256, different warmup or measured operation
counts, differing READ/WRITE counts, QD, rate, region layout or final
oracle SHA256.

For source/CI-only proof, run the rootless test on specifically named
scratch regular files under the temporary directory:

    python3 tests/runtime/threeway-swap-replay-test.py

The test's off/v22/v3 labels use the SAME rootless file replay code, not
the actual loaded kernel modules. It proves the trace and oracle only;
it is NEVER evidence of a V2.2/V3 performance or loaded correctness win.

## Realistic interpretation

Anonymous heap/stack/dirty COW, zero, strings, text buffers resident
in anonymous process memory, decoded raster buffers and medium-entropy
buffers are better *synthetic hypotheses* than assuming every swapped
page shrinks to 56 bytes. All high-entropy pages remain important
negative controls. A clean file-backed HTML/BMP/ELF page may simply
be dropped instead of swapped. The exact kernel codec output length
histogram from the separate PR #61 instrumentation must be reported
before claiming realism. Its synthetic profile weights are NOT a
statistically measured Linux swap population.

The existing alpha.7 code already chooses RAW fallback when LZ4 cannot
fit a valid payload within 3568 bytes. An upstream zswap instance may
alter which pages reach the DM target. Never modify active swap/zswap
to acquire measurements.

Primary objective: exact verified operation stream and **matched useful
IOPS**; report real backing read/write requests and bytes, read p99,
GC overhead, useful throughput, CPU and memory. Saturated totals at
different achieved work are a secondary experiment, not a matched
comparison. The controlled wave barrier can cap achievable throughput
and MUST be declared in the results. It is not an alternative to later
representative Linux anonymous swap *reclaim* testing.

Known unresolved kernel issues (not fixed by this work): alpha.8 bypass
did not beat frozen V2.2 on matched 5000-IOPS trials; V3 singleton
windows dominate at many matched loads; actual device-originated faults,
worker CPU and async buffer error provenance remain incomplete.
