# swapz V1 (experimental)

`swapz` is an experimental Device Mapper target for **dedicated swap partitions on slow storage**.  It targets old HDDs, USB flash drives, SD/eMMC media, and SATA SSDs where storage bandwidth and flash write endurance matter more than high queue-depth NVMe throughput.

The V1 hypothesis is intentionally narrow:

> LZ4-compress 4 KiB swap pages, pack multiple compressed pages into 4 KiB lower-device writes, and rotate append-only write arenas across the backing partition.  This should reduce host bytes written and turn repeated logical swap rewrites into broad sequential LBA writes.

This is a proof-of-concept, not production storage software yet.

## V1 scope

- Linux Device Mapper target name: `swapz`
- module: `dm-swapz.ko`
- **4 KiB PAGE_SIZE only**
- dedicated block partition/device only
- LZ4 only
- one serialized `WQ_MEM_RECLAIM` worker
- volatile in-RAM mapping table; no persistent metadata
- 4 KiB physical packed containers, up to 8 compressed logical pages per container
- raw 4 KiB fallback for pages that do not save at least 512 bytes with LZ4
- append-only arenas rotated over the backing device
- arena compaction is deliberately simple: re-copy live mappings into the next arena
- upper discard is consumed internally when available
- lower discard is auto-detected, optional, and permanently disabled after a runtime failure
- hibernation/resume is unsupported
- encryption and swap-file backing are out of scope
- NVMe/high-concurrency tuning is out of scope

## Why the physical partition is larger than logical swap

V1 reserves 25% raw-page slack inside each arena and requires at least two arenas.  In practice the backing device therefore needs about **2.5x the requested logical swap size**.  `swapzctl` defaults to logical swap equal to one third of the physical device.

Example:

```text
12 GiB dedicated partition -> ~4 GiB logical swapz device
128 GiB SD partition       -> choose 16-32 GiB logical swap for much stronger wear spreading
```

This strong overprovisioning is intentional for the proof-of-concept.  It guarantees that an all-incompressible live set still fits during arena rotation and avoids implementing a complex segment garbage collector before the performance/endurance premise is proven.

## Storage layout

```text
Linux swap 4 KiB logical writes
        |
        v
      swapz
        |
        +-- LZ4 compress
        +-- pack <= 8 records into a 4 KiB container
        +-- raw 4 KiB fallback
        |
        v
append-only current arena
        |
        v
backing partition

arena 0 -> arena 1 -> arena 2 -> ... -> arena N -> arena 0
```

When an arena fills, live logical pages are compacted into the next arena.  All mappings are RAM-only and a reboot starts with an empty target.

## Build

Kernel headers and Device Mapper/LZ4 kernel support are required.

```bash
make
```

Or explicitly:

```bash
make -C kernel KDIR=/lib/modules/$(uname -r)/build W=1
make -C userspace
make -C tests test
```

The current source has been compile-tested with both GCC and Clang against Debian Linux 6.12.96 headers using `W=1`.  The interfaces used (`device-mapper.h`, `dm-io.h`, kernel LZ4, block discard helpers) also exist in Linux 7.0.  Exact 7.0.x build/runtime testing still needs to be done on a 7.0.x machine or VM.

## DKMS

From a source tree installed under `/usr/src/swapz-0.1.0`:

```bash
dkms add -m swapz -v 0.1.0
dkms build -m swapz -v 0.1.0
dkms install -m swapz -v 0.1.0
```

## Manual activation

**The backing partition is scratch storage and will be overwritten.**

```bash
sudo modprobe dm-swapz
sudo swapzctl start /dev/disk/by-partuuid/YOUR-PARTUUID --size 4G
```

`swapzctl` performs:

1. checks that the backing device is a block device, not mounted, and not already active swap;
2. creates `/dev/mapper/swapz0`;
3. runs `mkswap -f` on the mapper device;
4. tries `swapon --discard=pages` so Linux can tell `swapz` which logical pages are dead;
5. falls back to ordinary `swapon` if page-discard activation is unavailable.

Status:

```bash
sudo swapzctl status
sudo dmsetup status swapz0
```

Stop:

```bash
sudo swapzctl stop
```

## DISCARD behavior

Upper and lower discard are independent.

```text
Linux swap --discard=pages
          |
          v
       swapz              always safe to consume internally
          |
          +---- backing DISCARD supported? ---- yes -> use before arena reuse
          |                                  \\-- no -> sequential overwrite
```

The lower device is probed using its block queue limits.  A lower discard error does **not** fail swap I/O; `swapz` logs it once, disables lower discard for the lifetime of that target, and continues with ordinary arena overwrite.

Correctness never depends on lower DISCARD.

If upper discard is unavailable, stale logical mappings remain conservatively live until overwritten.  This can increase arena-compaction traffic but does not change correctness.

## systemd

Copy and edit:

```bash
sudo install -Dm0644 systemd/swapz.service /etc/systemd/system/swapz.service
sudo install -Dm0644 systemd/swapz.conf.example /etc/swapz.conf
sudo systemctl daemon-reload
sudo systemctl enable --now swapz.service
```

Use a stable `/dev/disk/by-partuuid/...` device path in `/etc/swapz.conf`.

## Testing

See [`TESTING.md`](TESTING.md).  At minimum:

```bash
make test
sudo ./scripts/loop-smoke.sh
```

The loop smoke test requires a kernel built for the installed module and uses a temporary 1 GiB loop device; it does not touch a real disk.

For a secondary Codex/test-agent handoff, use [`CODEX_VALIDATION.md`](CODEX_VALIDATION.md).
It defines the V1 invariants, destructive-test safety rules, feature-detection/fallback
requirements, benchmark metrics, and the exact report expected back for primary-fixer
review.  The tester is intentionally not authorized to redesign or push substantive
kernel changes.

## Benchmarking

The key success metric is **lower-device sectors written**, not LZ4 ratio.

On a disposable dedicated test partition:

```bash
sudo ./bench/block-benchmark.sh \
    --backing /dev/sdX3 \
    --size 1G \
    --runtime 60 \
    --iodepth 8 \
    --destroy
```

The benchmark runs a raw-device baseline, the same compressible workload through `swapz`, and an incompressible control.  It samples `/sys/class/block/<device>/stat` before/after each run.

For the first SD/USB tests, run both `--iodepth 1` and `--iodepth 8`.  V1 gets host-byte reduction by **packing concurrently queued compressed pages into one 4 KiB write**, so QD1 is an important negative/control case rather than something to hide.

## Important limitations

- Do not use `swapz` for hibernation/resume.
- Do not put a filesystem on the mapper device.
- Power-loss persistence is deliberately not provided; swap is recreated each boot.
- V1 serializes all target I/O.  This is intentional for slow devices but inappropriate for fast NVMe.
- FUA-specific persistence semantics are not a V1 goal; the target is only intended for disposable swap data.
- Arena rotation can pause while live pages are compacted.  Measuring that tail latency is part of the V1 experiment.
- Host-sector reduction is an endurance proxy.  Actual NAND write amplification is controlled by the device FTL and must be measured with device telemetry where available.