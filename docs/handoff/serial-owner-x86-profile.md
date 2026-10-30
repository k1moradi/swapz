# x86 owner attribution and copy-counter correction

## Qualification and scope

Exact source `df861f744bcbd3a6bf990989a79c92b5c630be44` passed all five
owner `make test` stages. Report `3162abea3a4b1fcd013634e6f286f8d3a8d22191`
was published after preserving remote advance `2a40d0973839`. Automatic
identity selection generated two-report, 28-point history for this computer;
other and unidentified reports remain excluded. These reports share production
C and do not establish an optimization gain.

## Serial-owner diagnostic

The [packet](serial-owner-x86-profile.json) preserves the prospective fixed
three-pair persistent NVMe5 plan, exact C/module/script hashes, scripts,
complete byte-oracle/latency/lower-I/O/CPU/RSS reports and sample summaries.
There are six complete GO-to-final-fsync gates, no overlaps, matching emitted
versus BPF sample counts, and no unresolved swapz module frames. All six
loaded arms passed readback. The first capture had stale module symbolication
and also saw build-time regular-file contracts. It is technically invalid and
remains ignored under `build/optimization-round/serial-owner/`. The corrected
capture gates on root replay tasks, retains raw instruction pointers and
resolves the exact module ELF against live sysfs section snapshots. No
additional samples were collected after this corrected three-pair run.

All three corrected pairs are NOISY for performance: raw-repeat spread was
14.1%. Their normalized throughput mean differs from the earlier untraced
diagnostic by +5.1%; that is context, not a paired effect or proof that
profiling is free. No gain, regression or equivalence claim is supported.

Scheduler-clipped `swapz_worker` on-CPU intervals were 39.18, 38.93 and
38.62 ms within 49.12, 49.00 and 47.99 ms gates: 2.39, 2.38 and
2.36 us/mixed-op for 16,384 operations. These include probe and IRQ/softirq
time and are not exact uninstrumented owner CPU. Completion-work on-CPU
intervals were 15.45, 16.08 and 16.01 ms and overlap the owner; never add them
to form a serialized budget.

The 955 hardware-cycle samples with `swapz_worker` in their stack partition
exclusively into other 346, pack/stage 263, READ 121, decode 54, lock/IRQ-restore
82, CRC 52, interrupts 20 and plan/sort 17. Inlining leaves substantial
unclassified work. Lock/unlock frame presence does not prove contention or
removable lock cost. Samples are cycle-weighted observations, not nanosecond
phase partitions. None contains LZ4 compression in the ordered owner.

Across 2,901 samples with any swapz ancestor, 263 are memset under
LZ4_compress_fast and 355 are other LZ4 compression. Installed kernel-object
disassembly shows a 0x4020-byte memset at entry to LZ4_compress_fast_extState.
This identifies a bounded state-work opportunity (about 9% of these sampled
swapz stacks), not a 9% total-I/O opportunity or a 5 us serialized CPU ceiling.
The [Linux LZ4 interface](https://raw.githubusercontent.com/torvalds/linux/v7.0/include/linux/lz4.h)
permits a zero-length dictionary load which forgets prior input. The
[implementation](https://raw.githubusercontent.com/torvalds/linux/v7.0/lib/lz4/lz4_compress.c)
can avoid a normal per-block table clear, but uses a different hash mode and
periodic state resets. A candidate must prove independent 4 KiB decoding,
failure-to-success reuse, wrap/reset behavior, source lifetime and resource
bounds, then measure encoding/packing and lower-I/O effects. No stream or custom
encoder change has been applied. Do not infer a host RAM bottleneck.

## Concrete telemetry repair

Source review found both preparation paths incrementing direct-LZ4 input
counts before copying into `prepared->raw_bytes`, then unmapping the BIO and
compressing the copy. The repaired production counters distinguish mapped
snapshot inputs from ordered codec calls receiving mapped BIO input. Ordered
forced-RAW bypasses no longer increment the latter counter. Payload,
ownership, snapshot publication, allocation, lower I/O and failure contracts
are unchanged. The loaded development check observed 12,301 submitter pages,
12,301 mapped snapshots, zero direct LZ4 inputs, 50,384,896 submitter copy bytes
and byte-exact readback. This check is validation, outside the profiling sample
family; it is not a new performance comparison.

Source contracts guard the distinction and the parser tests its new counter
epoch delta. Full exact-source owner qualification of the repair remains
pending. The next performance experiment remains the reviewer's combined
LZ4-state work with submitter preparation, followed by completion delivery and
lighter admission. Retention requires a declared matched confirmation against
the appropriate control, not these diagnostic means.
