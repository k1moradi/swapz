# swapz V2.2 (streaming experiment)

`swapz` is an experimental Device Mapper target for **dedicated swap partitions on slow storage**.  It targets old HDDs, USB flash drives, SD/eMMC media, and SATA SSDs where storage bandwidth and flash write endurance matter more than high queue-depth NVMe throughput.

The V2.2 hypothesis is intentionally narrow:

> LZ4-compress 4 KiB swap pages immediately, keep at most two bounded preallocated stream buffers, overlap compression/packing with one asynchronous lower write, and submit whatever is ready instead of sleeping to fill a batch. In staged mode, compressed upper writes may complete from the RAM buffer before disk submission so reclaim can release the original page sooner; swap-in can read directly from either filling or in-flight RAM buffer.

This is a proof-of-concept, not production storage software. V2.1 is the last software-validated baseline. V2.2 is an unvalidated experiment for comparing immediate, opportunistic streaming, and staged streaming policies plus the throughput/latency batch-size plateau.

## V2.2 scope

- Linux Device Mapper target name: `swapz`
- module: `dm-swapz.ko`
- **4 KiB PAGE_SIZE only**
- dedicated block partition/device only
- LZ4 only
- one serialized `WQ_MEM_RECLAIM` worker for upper mapping/state changes
- two preallocated stream buffers; at most one asynchronous lower write is in flight while the other buffer can fill
- selectable policies: `immediate`, `opportunistic`, and `staged`
- configurable batch ceiling from 4 KiB through 1 MiB; the benchmark chooses the plateau rather than assuming a fixed sweet spot
- volatile in-RAM mapping plus generation/staged-reference metadata; no persistent metadata
- compressed records are packed into 4 KiB physical containers; filling buffers can repack live unsent records before submission
- raw 4 KiB fallback for pages that do not save at least 512 bytes with LZ4
- append-only 1 MiB segments rotated over the backing device
- per-block live-record accounting plus low-live victim-segment garbage collection
- one FREE segment is maintained as GC reserve
- GC scans the compact logical map but relocates only mappings resident in the chosen victim segment
- upper discard is consumed internally when available
- lower discard is auto-detected, optional, and permanently disabled after a runtime failure
- hibernation/resume is intentionally deferred for V2.x; it is a required final-version milestone after correctness, performance, deployment, and persistence design are stable
- encryption and swap-file backing are out of scope
- NVMe/high-concurrency tuning is out of scope; the lower stream intentionally keeps physical queue depth near one while overlapping CPU work with device latency

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
      swapz worker
        |
        +-- LZ4 compress immediately
        +-- pack compressed records / raw fallback
        |
        +--> Buffer A: lower write IN_FLIGHT
        |
        \--> Buffer B: FILLING concurrently
                 |
                 +-- read may be satisfied directly from RAM
                 +-- discard/overwrite may invalidate an unsent record
                 +-- repack live records before submission
        |
        v
one asynchronous sequential lower write
(up to configured 4 KiB..1 MiB ceiling)
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

V2.1 passed Linux 7.0.0-34 validation including model/sanitizer tests, randomized block tests, live-GC stress, fault injection, lifecycle testing, and bounded real swap pressure. V2.2 has not yet passed that gate. Its purpose is to determine whether overlapping compression with asynchronous lower I/O and bounded staged completion improves reclaim speed and reaches the real throughput/latency plateau.

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

## V2.2 strategy experiment

Device Mapper table syntax accepts optional policy and batch ceiling:

```text
0 <sectors> swapz <backing> [immediate|opportunistic|staged] [batch_kib]
```

Examples:

```text
... swapz /dev/loop0 immediate 4
... swapz /dev/loop0 opportunistic 256
... swapz /dev/loop0 staged 512
```

`immediate` is the no-streaming control. `opportunistic` overlaps one asynchronous lower
write with filling the second buffer but does not early-complete compressed upper writes.
`staged` additionally lets a compressed page become authoritative in the bounded RAM
buffer before lower submission. Reads can be served from either filling or in-flight
buffers. A READ does not free the swap slot; cancellation/repacking happens only after
DISCARD or overwrite makes that generation stale.

Run the controlled strategy/batch sweep on a kernel with configurable `null_blk`:

```bash
sudo bash tests/runtime/streaming-benchmark.sh
```

The sweep reports both upper-completion throughput and end-to-end physical drain throughput,
plus concurrent read p95/p99/max. It defines the batch plateau as >=97% of the best observed
drain throughput, then chooses the smallest plateau point whose read p99 is within 10% of
the best latency inside that plateau.

The analytical command-latency model is:

```bash
python3 bench/request-plateau.py --bandwidth 20
```

It exists only to determine how far upward the real sweep must go; measured `null_blk` and
physical-device results decide the actual sweet spot.

The staged-buffer race/cancellation regression is:

```bash
sudo bash tests/runtime/buffer-recall.sh
```

It covers reads from the in-flight buffer while the second fills, reads from the filling
buffer while the first is being written, simultaneous reads from both, and invalidation of
an unsent record before lower submission.

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

- Do not use current V2.x `swapz` for hibernation/resume. Resume/hibernate support is deferred, not abandoned: it is planned as a final-version milestone once the core design is stable.
- Do not put a filesystem on the mapper device.
- Power-loss persistence is deliberately not provided; swap is recreated each boot.
- V2.2 keeps at most one lower write in flight but pipelines CPU compression/packing with that write. This is intended for slow serialized devices and is not an NVMe design.
- FUA-specific persistence semantics are not a V2 goal; the target is only intended for disposable swap data.
- Segment GC can still pause foreground progress while a live victim is cleaned; V2.2 must measure GC latency together with staged-read and stream-drain latency.
- Host-sector reduction is an endurance proxy.  Actual NAND write amplification is controlled by the device FTL and must be measured with device telemetry where available.

## Final-version roadmap

Resume and hibernation are **not in scope for V2.x**, but they are part of the intended
final version of `swapz`.

They are deliberately deferred until the volatile swap path has completed:

1. correctness validation;
2. streaming/performance tuning;
3. physical-media qualification;
4. deployment and boot integration;
5. final persistent-state/resume architecture.

The current volatile RAM-only mapping cannot by itself support resume after power loss or a
normal reboot. Final hibernation support will therefore require an explicitly designed and
validated persistence/resume format and boot-time activation path rather than simply
placing the current module in initramfs.

Until that final milestone is implemented and validated, current releases must continue to
reject any claim of hibernation/resume support.
