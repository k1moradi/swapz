# V2.2 authorized virtual-device and performance qualification gate

**Status: unexecuted checklist, not performance evidence.** Source-only
rootless tests cannot establish Linux Device Mapper quiescence, physical drain
throughput, swap-in p99, or a V2.2 strategy/batch winner.

## Authorization boundary

No fixture in this document authorizes a real operation. A separate operator
approval must identify disposable devices, host, test window, backup and
backing-cleanup policy before invoking `dmsetup`, `losetup`, NBD attach,
`swapon`, `swapoff`, the real recall/pressure scripts, fio against a
device, module operations or host reboot.

Never operate on a host's active swap or an unverified block device.
Inspect actual current mounts, swap entries and backing-file identities
*before* any future explicitly authorized test. An operator must approve
target identity. A failed or ambiguous inspection preserves every backing
object; never attempt force or deferred cleanup as a fallback.

## Gate A — Trusted identity and isolation (must all pass)

- [ ] A separately managed manifest ties an independently trusted GNU
      coreutils `dd` package/build to its expected executable SHA-256.
- [ ] The service binds a descriptor to that exact executable and its
      sealed immutable image, rather than trusting `/usr/bin/dd` or PATH.
- [ ] Test mapper name, DM UUID, major:minor, table state, exclusive
      fixture ownership and table lifecycle cannot be confused with another
      stack or changed concurrently without fail-closed detection.
- [ ] Each direct worker is pidfd-owned, parent-death constrained, unable to
      create untracked descendants, and bound to fixed role arguments.
- [ ] The service binds each readback output *before* worker launch,
      compares its exact pinned inode against independently immutable 4 KiB
      bytes, and cannot be tricked by a replacement pathname.
- [ ] Five roles `writer, a, b, a2, b2` are admitted exactly once, both
      concurrent reader launches precede waits, and the writer lives through
      the completed reader checks.
- [ ] Final cleanup requires complete handle inventory, all waits/reaps,
      exact observed service-process zero exit and verified control-channel
      closure. A crash, timeout, missing receipt or checksum mismatch
      **preserves backing**.
- [ ] Kernel-side I/O drain is independently attested, not inferred from
      process death. Mapper suspend/removal/holder and outstanding-I/O
      checks have bounded, verified, non-force semantics.

## Gate B — Virtual correctness after approval

Use an explicitly created **disposable** virtual stack only. Ensure source
and expected bytes are prepared before any I/O; retain nine separate 4096-B
expected pages. Verify exact writer data, Buffer A/B staged hits, distinct
concurrent phase `a2/b2`, page-6 discard, writer wait, fsync and existing
cancellation/failed counters. Preserve the original 500 ms lower-I/O delay,
300 ms concurrent-read limit and all staging assertions unless a separately
reviewed test protocol changes them.

Inject crashes, table mutation attempts, device-disconnect simulations,
failed waits, data mismatch, slow lower I/O, cleanup interruptions and loss
of IPC. For each negative trial, prove the backing and logs remain available.

## Gate C — Calibrated performance measurements after correctness

### Dimensions

| Dimension | Required sweep |
| --- | --- |
| Batch | 4, 8, 16, 32, 64, 128, 256, 512, 1024 KiB, including actual 512 KiB–1 MiB lower-device behavior |
| Strategy | Immediate, opportunistic, staged/streamed |
| Backend | Calibrated slow-HDD-like, SATA-like and removable-media-like virtual latency/throughput profiles, with explicit actual-device qualification later |
| Load | Idle GC, sustained churn/pressure, GC overlapping reads, bursty reclaim, cancellation |
| Replication | Warm-up; at least 3 independent runs/configuration; record variance and system noise |

Record kernel and module revisions, test device identity, backing path,
clock source, scheduler, page/cache mode, profile parameters, GC state,
thread counts and measurement windows.

### Mandatory metrics

- Logical request completion MiB/s **and independently observed lower-device
  drained MiB/s**. Never use queued/completed-in-memory work as drained bytes.
- Lower-level sector counts, request count and write amplification.
- Swap-in page p50, p95, p99, max and tail-window histograms.
- GC completion, cancellation, batching and pending-byte distributions.
- CPU, RSS and any buffer/cache memory charged to the experiment.
- Throughput variation between warm/cold buffers, zero-queue and saturation.
- End-to-end per-page correctness checksum and run-level data-loss alarms.

If source-only tests are run, tag results `MOCK` or `SYNTHETIC`, never
`KERNEL` or `PHYSICAL`. Missing counters invalidate the performance claim.

### Selection rule

For each comparable and valid backend/strategy series, compute a stable
drain-throughput plateau with enough points to demonstrate saturation.
If no plateau exists, report `PLATEAU NOT REACHED` and do not nominate a
winner. Among qualified configurations, select the **smallest batch** at or
above **97%** of the useful drain plateau whose swap-in **p99 is within
10%** of the best p99 plateau point, while retaining correctness and safe
cleanup. Publish confidence ranges; do not average away p99 regressions.
Document the alternative if the constraints conflict, without silently
relaxing either criterion.

## Offline evidence preflight (rootless only)

The standalone `v22-drain-plateau-analyze.py` is a **read-only**
validator for future independently collected lower-device write-sector
deltas and 10,000+ swap-in samples per run. Its input is a strict
`swapz-drain-observation-v1` JSONL schema, described in
[`v22-drain-plateau-offline.md`](v22-drain-plateau-offline.md).

The existing `streaming-benchmark.sh` reports
`drained_write_mib_s = logical_write_bytes / elapsed`; that metric
**must not be relabeled** as independently measured lower-device drained
throughput. Although it records lower-write sector counters, the script
does not yet emit complete, independently reviewed drain-window and
quiescence attestations for this new schema.

The offline validator requires the full batch sweep (except the immediate
single-batch baseline), three repeats per configuration, 10,000+ actual
swap-in latency samples per repeat, stable lower-device throughput, and
the three largest batches at >=97% of the measured peak before proposing
a plateau candidate. It guards the 10% read-p99 constraint using the
**worst repeat** at each candidate size, not only its mean. Missing,
unstable or contradictory data reports `PLATEAU NOT REACHED`. Synthetic
data never yields an empirical winner. Even `kernel`/`physical`
provenance labels remain self-reported until independently reviewed.

## Gate D — Physical media (distinct authorization)

Only after passing the disposable virtual stack and receiving a separate
explicit approval, test real disposable HDD/USB/SD/eMMC/SATA SSD media. No
physical device is implicitly authorized by any earlier synthetic result.
Collect wear-sensitive write amplification and tail latency separately.

## Evidence ledger

| Gate | Latest supported conclusion |
| --- | --- |
| Rootless pidfd/IPC and synthetic readback | Implemented, source-only regression coverage |
| Crash containment | Rootless Linux process behavior tested; in-flight block I/O not qualified |
| Trusted GNU executable / mapper lifecycle | In progress; no live mapper approval |
| Separate service and real pinned worker fixture | Rootless temporary-file qualification only |
| Authorized virtual correctness and throughput | **NOT RUN** |
| Physical storage throughput and tail latency | **NOT RUN** |
| V2.2 winning strategy / batch | **UNDETERMINED** |
