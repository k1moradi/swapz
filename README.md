# swapz V2.1 (experimental)

`swapz` is an experimental Device Mapper target for **dedicated swap partitions on slow storage**.  It targets old HDDs, USB flash drives, SD/eMMC media, and SATA SSDs where storage bandwidth and flash write endurance matter more than high queue-depth NVMe throughput.

The V2.1 hypothesis is intentionally narrow:

> LZ4-compress 4 KiB swap pages, pack multiple compressed pages into 4 KiB lower-device writes, append sequentially through 1 MiB segments, and garbage-collect only low-live victim segments.  This should reduce host bytes written without V1's whole-live-set compaction penalty.

This is a proof-of-concept, not production storage software yet.

## V2.1 scope

- Linux Device Mapper target name: `swapz`
- module: `dm-swapz.ko`
- **4 KiB PAGE_SIZE only**
- dedicated block partition/device only
- LZ4 only
- one serialized `WQ_MEM_RECLAIM` worker
- up to 8 consecutive physical 4 KiB output blocks are coalesced into one serialized 32 KiB lower request
- volatile in-RAM mapping table; no persistent metadata
- 4 KiB physical packed containers, up to 8 compressed logical pages per container
- raw 4 KiB fallback for pages that do not save at least 512 bytes with LZ4
- append-only 1 MiB segments rotated over the backing device
- per-block live-record accounting plus low-live victim-segment garbage collection
- one FREE segment is maintained as GC reserve
- GC scans the compact logical map but relocates only mappings resident in the chosen victim segment
- upper discard is consumed internally when available
- lower discard is auto-detected, optional, and permanently disabled after a runtime failure
- hibernation/resume is unsupported
- encryption and swap-file backing are out of scope
- NVMe/high-concurrency tuning is out of scope; batching is intended to improve slow serialized media without adding lower queue depth

## Why the physical partition is larger than logical swap

V2 requires at least **25% of logical capacity plus two 1 MiB segments** as physical GC reserve.  Compression is never required for capacity.

`swapzctl` intentionally keeps the more conservative default of logical swap equal to one third of the backing device.  On SD/USB media, extra physical space means more append distance before a host-LBA region is reused.

Example:

```text
12 GiB dedicated partition -> default ~4 GiB logical swapz device
128 GiB SD partition       -> 16-32 GiB logical swap remains a useful endurance-oriented choice
```

V2.1 can operate with much less overprovisioning than V1, but conservative sizing is still recommended until physical-media benchmarks establish the best endurance/performance tradeoff.

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
        +-- coalesce <= 8 consecutive physical blocks
        |   into one <= 32 KiB serialized lower write
        |
        v
append-only current segment
        |
        v
backing partition

segment 0 -> segment 1 -> ... -> segment N; low-live closed segments are cleaned and reused
```

When a segment fills, allocation advances to a FREE segment.  When the reserve is consumed, only the live mappings in one low-live CLOSED segment are copied into the current segment and that victim becomes FREE.  All mappings are RAM-only and a reboot starts with an empty target.

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

V2 was validated on Ubuntu Linux 7.0.0-34 with randomized block tests, live-GC stress, fault injection, lifecycle testing, and bounded real swap pressure. V2.1 keeps that allocator and adds serialized multi-block lower-write batching; this new write path requires a fresh Linux 7.0.x validation pass.

## DKMS

From a source tree installed under `/usr/src/swapz-0.2.1`:

```bash
dkms add -m swapz -v 0.2.1
dkms build -m swapz -v 0.2.1
dkms install -m swapz -v 0.2.1
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
          +---- backing DISCARD supported? ---- yes -> use after victim cleaning / before segment reuse
          |                                  \\-- no -> sequential overwrite
```

The lower device is probed using its block queue limits.  A lower discard error does **not** fail swap I/O; `swapz` logs it once, disables lower discard for the lifetime of that target, and continues with ordinary sequential segment overwrite.

Correctness never depends on lower DISCARD.

If upper discard is unavailable, stale logical mappings remain conservatively live until overwritten.  This can increase victim-GC traffic but does not change correctness.

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
It defines the current V2 invariants, destructive-test safety rules, feature-detection/fallback
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

For the first SD/USB tests, run both `--iodepth 1` and `--iodepth 8`.  swapz gets host-byte reduction by **packing concurrently queued compressed pages into one 4 KiB write**, so QD1 is an important negative/control case rather than something to hide.

## Important limitations

- Do not use `swapz` for hibernation/resume.
- Do not put a filesystem on the mapper device.
- Power-loss persistence is deliberately not provided; swap is recreated each boot.
- V2 still serializes target I/O.  This is intentional for slow devices but inappropriate for fast NVMe.
- FUA-specific persistence semantics are not a V2 goal; the target is only intended for disposable swap data.
- Segment GC can pause a foreground write while one low-live victim is cleaned.  Measuring that tail latency is a primary V2 test.
- Host-sector reduction is an endurance proxy.  Actual NAND write amplification is controlled by the device FTL and must be measured with device telemetry where available.