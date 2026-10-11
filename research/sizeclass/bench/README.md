# swapz block-aligned adaptive packing — research benchmark

**Rootless simulator only.** This code is an independent research prototype on PR #32; it does **not** modify the kernel, its disk format, the PR #31 benchmark runner, production swap, or the existing reviewer evidence.

## Purpose

Two ~2072-byte LZ4 records cannot share a 4 KiB physical container with the existing 8-byte header and 8-byte-per-record descriptor: `8 + 2*(8+2072) = 4168 > 4096`. Thus **reordering only in 4 KiB** cannot correct the uniform synthetic 50% fio I/O cliff. Aligned 8/16 KiB multi-block extents can pack three/seven such records at full occupancy, with some reads spanning two 4 KiB physical blocks. The 64 KiB candidate is a research comparator, not the default.

`model.py` compares `ordered4` (one current bin, source-ordered), bounded `bestfit4`, `fixed8`, `fixed16`, `fixed64`, and `adaptive` (choose 4/8/16 KiB to minimize modeled write bytes within the **same finite causal flush window**, tie-breaking toward fewer read blocks). The source-ordered model approximates the kernel's packing *geometry*, not its complete asynchronous BIO and generation-handling implementation.

The rootless model has byte-exact experimental 8+8 little-endian descriptors, volatile generation/checksum mappings, finite 1 MiB physical segments and a free-segment reserve. It charges actual modeled foreground and GC relocation extent writes, performs bounded nonrecursive GC based on observed victim liveness, validates CRC32 on reads, handles overwrite generations, fails closed on malformed descriptors and torn writes, and refuses to free victims until every survivor relocation succeeds. Interrupted GC leaves old authoritative mappings intact and charges successful scratch writes as physical traffic.

**Not yet modeled:** real kernel async callbacks/BIO ownership; production layout/version migration; power-loss persistence; decompression, actual storage/media behavior, 4Kn controller write service or cold-read latency/p99. CRC is **IEEE CRC32, not CRC32C**; actual fio CRC32C verification remains required before any live work. Metadata/payload read blocks are modeled assuming uncached metadata; read-block counts are **not** elapsed latency.

## Exact rootless reproduction

From repository root:

```sh
python3 -B research/sizeclass/bench/test_model.py -v
python3 -B research/sizeclass/bench/run.py --trace fio50 --operations 1536 --window 16 --working-set 384 --segments 6 --seed 12345
python3 -B research/sizeclass/bench/run.py --trace fio75 --operations 1536 --window 16 --working-set 384 --segments 6 --seed 12345
python3 -B research/sizeclass/bench/run.py --trace hotcold --operations 3072 --window 16 --working-set 256 --segments 4 --seed 12345
python3 -B research/sizeclass/bench/run.py --trace fio50 --operations 1536 --window 32 --working-set 384 --segments 8 --seed 12345
```

Optional **payload lengths only** (not original memory or LZ4 recompression) from an independently verified audit TSV:

```sh
python3 -B research/sizeclass/bench/run.py --audit-lengths /path/to/fio-lz4-lengths.tsv --seed 12345
```

TSV columns are exactly `page_index`, `payload_bytes`, `kind`. The runner hashes its TSV source and generates synthetic bytes of matching lengths, keeping audit provenance distinct from the PR #31 live kernel workload. In a CLI comparison, every policy receives identical operation order, window boundaries, seeds, capacity, reserve, and requested reads. A noncomparable case exits **2** rather than selecting a false winner. All six policies must complete the same logical bytes with no failure.

## Executed local rootless observations

Local tests: **23 passed**, Python compilation passed; actual Git blobs for the three Python files match the locally executed source exactly. Synthetic 1536 writes, W16, 384 slots, six 1 MiB segments, one reserve, seed 12345:

| Input | ordered4 | bestfit4 | fixed8 | fixed16 | fixed64 | adaptive |
|---|---:|---:|---:|---:|---:|---:|
| All 2072 bytes (~50%-like) | 1.000× | 1.000× | 1.333× | 1.333× | 1.000× | 1.333× |
| All 1048 bytes (~75%-like) | 2.667× | 2.667× | 2.667× | 2.000× | 1.000× | 2.667× |

The 50%-like adaptive ratio rises to **1.600×** at W32 in this model. The partial-flush penalty makes 64 KiB underperform substantially at W16. The hot/cold case exercises GC and reports **actual modeled** relocation write bytes, without fixed WAF multipliers. These numbers are **neither loaded-kernel nor flash-wear measurements**; do not compare 2.667× rootless directly with the independently reported **2.922× PR #31 actual null_blk** result, because flush/overwrite/arrival behavior differs.

## Gate for downstream work

Independent Codex rootless validation is described in [CODEX_TASK.md](CODEX_TASK.md). Rootless success alone is **not** authorization for a live run. Before benchmarking a loaded kernel, implement and review a separate experimental kernel PR proving actual multi-block read/write alignment, on-disk version compatibility, mapping/BIO authority, bounded progress, CRC32C integrity, GC reserve/reclaim, timeout/error and torn-write semantics. Only then independently build and run the already-guarded disposable null_blk benchmark, with exact-source/module/host ownership preflights and safe ordinary teardown. Never bypass production swap or resource safeguards.
