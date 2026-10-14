# Device geometry and swap I/O: normative V3 design and measurement standard

## Do not confuse these quantities

| Layer | Meaning | Examples / implications |
| --- | --- | --- |
| Linux memory/swap page | Memory transfer unit currently supported by swapz V3 | `PAGE_SIZE=4096` on our tested x86-64 kernel; **not universal across Linux** |
| Device **logical** block | Smallest independently host-addressable sector; `/sys/block/<disk>/queue/logical_block_size` | 512 B, 4096 B; required I/O offset and length alignment |
| Device **physical** block | Device-reported physical sector size; `physical_block_size` | 512 B, 4096 B or other; may exceed logical-sector size |
| Device preferred transfer | `minimum_io_size`, `optimal_io_size`, alignment offset, maximum request limits | Possibly 4, 16, 64, 128 KiB or other values; a preference, NOT the same as a logical sector |
| Filesystem block/cluster | Filesystem allocation and mapping granularity | Often 4KiB, may be larger; DOES NOT set drive sectors or Linux swap page size |
| Controller/media granularity | Flash/NAND program and erase, FTL, SD-card erase group, HDD internal operations | May be undisclosed; never infer physical NAND writes from host-sector totals |

**512n:** usually 512-byte logical and physical sectors. Valid lower
requests can be smaller than 4KiB. **512e:** 512-byte logical sectors
emulating 4KiB physical ones; sub-4KiB or misaligned writes *may* cause
internal read-modify-write. **4Kn:** 4KiB logical and physical sectors;
ordinary host I/O must be 4KiB aligned and sized in multiples of 4KiB.
A filesystem with a 64KiB cluster on any such device does NOT turn its
physical sector or swap memory page into 64KiB.

**Current implementation restriction, not an industry fact:** swapz
V3.0-alpha uses a fixed 4096-byte format/allocation unit and aligned
4/8/16KiB extents, supports only `PAGE_SIZE=4096`, and rejects
backing devices whose logical block exceeds 4096 or does not divide
4096. Its alpha constructor also admits only test-owned `null_blk`.
A real-device enablement review MUST also check the physical-sector
size, alignment offset, minimum/optimal sizes, device max transfer,
partition offset, FUA/cache/discard behavior, capacity and zone type.
If a device exposes a physical sector larger than the 4096-byte
allocation, the present layout may cause RMW and is NOT automatically
qualified by its logical-sector compatibility check.

## Swap partitions versus swap files

A dedicated **swap partition** is a direct region of a block device
initialized by `mkswap`. It has NO filesystem “cluster size” setting.
The `swapon` kernel still swaps logical memory pages subject to the
target block device's addressing and alignment.

An ordinary **swap file** occupies filesystem extents. The kernel must
be able to access those extents directly with safe, stable mappings;
holes, delayed allocation and copy-on-write filesystem semantics are
restricted. Filesystem allocation size does NOT change `PAGE_SIZE` or
the physical sector size of the underlying drive. Swap-file behavior
depends on filesystem support and configuration. **swapz V3's current
dedicated block-target design does not implement swap-file backing.**
Do not imply that `swapz` currently supports an arbitrary swap file.

## Correctly interpret lower-device statistics

Linux `/sys/block/<device>/stat` read/write-sector fields always count
standard **512-byte accounting sectors**, including for a drive with
4096-byte *logical* or *physical* sectors. These are NOT necessarily
hardware sectors. Therefore:

```text
lower_read_bytes     = delta_read_sectors  × 512
lower_write_bytes    = delta_write_sectors × 512
4KiB_read_equiv      = delta_read_sectors  ÷ 8
4KiB_write_equiv     = delta_write_sectors ÷ 8
```

A single aligned **16KiB** lower write is **one request**, **16KiB**
of host-visible transferred data, and **four 4KiB equivalents**. It is
**NOT four physical I/O operations**. Device command merging, split
BIOs, caches, FTL wear leveling, remaps and internal RMW mean host
request/byte counters may not reveal flash program counts or HDD platter
activity. `stat` sectors are accounted on completion; track separately
submitted/attempted lower BIOs, failures, completed requests, merges,
flushes, discards and drain state. On an errored device, host counters
may show partial/attempted operations with different semantics from
swapz's successfully completed-extent counters.

The primary measurements are **actual read and write BYTES (or 512-byte
stat-sector deltas) AND request COUNTS**, separately, measured against
an independently verified *owned lower backing device*, including GC
relocation reads/writes. Keep 4KiB-equivalent values as a convenient
normalization ONLY, not a claimed hardware minimum. Include achieved
IOPS, p50/p95/p99, CPU, write-window occupancy, read amplification,
flush/FUA and GC pressure. Independent device/firmware telemetry is
needed for any genuine NAND wear or internal program-erase claims.

## Device-specific performance qualification

- Profile `logical_block_size`, `physical_block_size`,
  `minimum_io_size`, `optimal_io_size`, block alignment offset,
  `max_sectors_kb`, queue depth, rotational/flash attributes,
  caches/FUA, discard geometry and partition start.
- Treat the **4KiB-first** V3 layout as a testable policy, not a
  universal optimum. On 512n a smaller aligned host I/O may be possible;
  on 512e sub-4KiB writes can be costly; on 4Kn 4KiB is the ordinary
  minimum; on devices with larger preferred I/O a 16KiB packed extent
  may be more efficient than scattered 4KiB commands.
- Keep the same useful completed logical swap work, actual LZ4 payload
  histogram, hot/cold activity, achieved reader IOPS, and cache/flush
  conditions for the loaded V2.2 and V3 comparison. Observe both lower
  read AND write bytes/requests, plus GC traffic and latency.
- Never erase a potential read-regression by summing read and write
  bytes without a declared workload/device objective; report the
  multidimensional tradeoff and choose a policy on the Pareto frontier.
- Qualify physical SD, SSD and HDD individually. A loaded `null_blk`
  test proves only the host-visible kernel IO path in that RAM device.
  The alpha constructor **must remain null_blk-only** until the live
  correctness and physical-device safety gates are independently met.
  Never touch active swap or reboot.

## Authoritative references

- [Linux block queue sysfs ABI](https://www.kernel.org/doc/html/latest/admin-guide/abi-stable.html)
- [Linux block stat accounting, including 512-byte sector units](https://www.kernel.org/doc/html/latest/block/stat.html)
- [swapon(8) swap-file restrictions](https://man7.org/linux/man-pages/man8/swapon.8.html)

This document defines the *measurement semantics*; [VISION.md](../VISION.md)
defines success and [V3_GOALS.md](ROADMAP.md) defines algorithmic priorities.
