> **Supplemental/historical evidence — not current engineering policy.**
> Version-specific fixture and codec diagnostic record; benchmark.md governs claims.
> The authoritative standards are [coding_standards.md](../../docs/coding_standards.md),
> [testing_standards.md](../../docs/testing_standards.md),
> [compile.md](../../docs/compile.md), and
> [benchmark.md](../../docs/benchmark.md), alongside README.md and VISION.md.
> Do not use dated branch/reset/active-swap instructions as new permission.

# V3: actual swap-page compressibility, not file-extension heuristics

**Experimental; source/CI qualification only until fresh owned-null_blk
loaded testing. Do not run swapoff, swapon, reboot, or write to any active
swap, physical media, or unowned mapping.**

## What reaches swap?

Linux generally discards reclaimable **clean file-backed** pages instead
of writing them to a swap device. This often includes clean executable
ELF text, source/HTML, and decoded file mappings, even though they are
resident in RAM. The main swap population is evicted **anonymous and
swap-backed shmem/tmpfs** pages: heaps, stacks, dirty private mappings,
COW data and application buffers. These can contain structured,
compressible bytes **and** encrypted/compressed media/archives,
random-like buffers and previously compressed data. A Device Mapper
target sees a 4KiB BIO; it cannot infer the original file type or
whether it held executable code. A file-extension-based compression
choice is impossible at this layer and would be unreliable.

Zswap/zram, when configured, can change which pages ultimately reach
the backing swap device; do not claim that a direct-I/O DM benchmark
measures the page population after an active upstream zswap cache.
Never change the user's active swap/zswap just to collect data.

## Existing selective compression vs an early predictor

The V3 foreground path already calls
`LZ4_compress_fast(input, output, 4096, SV3_MAX_COMPRESSED=3568, 1)`.
If it cannot produce a payload <=3568 bytes, the page is placed via
the authenticated, whole-4096-byte raw fallback. This is **already a
lossless compression-vs-raw decision** based on actual content, rather
than extension, filename or guessed entropy.

A new high-entropy early-skip heuristic could save LZ4 CPU work on
some raw pages, but can falsely classify highly compressible pages,
increasing backing I/O/GC cost. Do not make it default, or implement
it before there is enough evidence of its actual gain. No estimator is
authorized to skip bytes, reduce CRC coverage, or change the 4KiB raw
mapping semantics.

## Production observability added on this branch

`dmsetup status` exposes foreground attempted-input bins:
- `lz4_attempts`: one per successful copied foreground WRITE BIO that
  reached LZ4, including writes later aborted or failed.
- `lz4_accepted_bytes`: sum of actual LZ4 payload lengths for attempts
  whose result fits the 3568B cap.
- `lz4_size_le256`, `lz4_size_257_1024`,
  `lz4_size_1025_2048`, `lz4_size_2049_3072`,
  `lz4_size_3073_3568`: successful codec result bins.
- `lz4_raw_fallback`: the codec could not fit a valid payload under
  the limit, and the existing raw path was selected.

The six bucket counters should sum to `lz4_attempts`. They are
**attempts, not committed windows, media writes, logical swap events
or unique resident pages**. GC, reclaim rotation and readback do not
add foreground LZ4 samples. Actual page samples must never be logged,
and counters must not be conflated with backing-device writes.

## Reproducible synthetic test input

`tests/runtime/anon-page-fixture.py` emits regular file fixtures with
a SHA-256 manifest and actual userspace liblz4 4096B/3568B/accel=1
size histogram. The default fixed-seed profiles:
- zero-filled pages;
- partially filled heap-like tagged object tables;
- text *buffers held in anonymous memory* (not clean source-file cache);
- simulated dirty private/COW code/data pages;
- decoded raster RGBA application buffers;
- mixed random/pattern/zero heap buffers;
- incompressible random-like control pages.

These profiles are constructed, not sampled from any host process,
and the default weights are **illustrative**, not an empirical Linux
swap-page distribution. Do not label them typical without
independently sourced measurements. Run, for example:

```sh
python3 tests/runtime/anon-page-fixture.py \
  --pages 1024 --seed 0x51a0a9 \
  --output-prefix /tmp/swapz-anon-demo
```

The emitted `.bin` holds complete 4096B pages and can replace the
prior sustained helper's fixture input; the `.json` records profile
counts, LZ4 size histogram, payload sum, and fixture hash. Scripts
never inspect live process memory, live swap, or physical media.
Use a fresh test-owned and verified RAM-backed null_blk for any loaded
I/O and strict owned-resource teardown. If liblz4 is absent, install
only an ordinary userspace runtime library or mark generation BLOCKED.

## Correctness/performance measurement gate

1. Verify that normal production `lz4_raw_fallback` is observed for
   high-entropy pages while never corrupting input or CRC on readback.
   Exercise verify=0/1, lower_bulk=0/1/2, mixed raw/compressed
   overwrites, FUA/PREFLUSH, discard, suspend, and rotating GC.
2. Cross-check actual kernel admission bins against input fixture
   class histogram on a **write-once** 1024-page trial; a deterministic
   fixture file is not itself evidence about kernel compression sizes.
   For repeated overwrites use actual write-issue counts, not counts
   of unique fixture pages.
3. Run matched-rate and saturation comparisons for the **same fixture
   and same successful logical operations**, always including frozen
   V2.2 and alpha.7 bulk=1 default=0 controls. Independently count
   backing read/write bytes, requests, read amplification and GC
   traffic, plus achieved IOPS, p50/p95/p99 and kernel + user CPU.
4. Sweep _measured_ compressed-size distributions rather than
   assuming 56B pages or fixed 80/20 raw. Include at least: mostly
   small, mostly medium, structured text/heap, realistic mixed,
   and deliberately hard-to-compress negative control. Consider
   read-mostly, sequential swap-out/swap-in and cold-page access, not
   only 30-second hot overwrites of a 1024-page writer region.
5. Only after a measured, convincing CPU bottleneck from raw attempts
   exists, prototype a low-cost optional prefilter on a separate
   branch; evaluate false positives and measure added costs to
   compressible pages. No premature default change.
6. Keep the 56B 819-compressed/205-raw PR #56 burst only as a
   **highly compressible stress/packing control**. It is not the
   estimate of page-size distribution in practical swap.

## Prior independent result

PR #60 on alpha.8 (`68dca6fcd2b322524555becfd54d475cdaf973e1`)
showed alpha.8 read-bypass-on did not lower backing I/O versus
bypass-off at matched QD8 / 5000 IOPS / 150,000 operations:
**119512 vs 119438** backing write requests (V2.2: **118782**),
on its fixed synthetic 80/20 input. At saturation the bypass can
enlarge windows but increased reads and did not beat V2.2.
Alpha.8 should remain **opt-in and unmerged**, pending causal evidence.

The new observability branch is based instead on PR #57 alpha.7;
it does **not** adopt the unproved alpha.8 read-bypass code. Its
compression path and on-disk SWZ3 format are unchanged.
