# swapz validation status

Date: 2026-10-06

## V1 historical result

V1 is preserved on branch `v1` at:

```text
025edff9fbe1d402cf6eab294e3ce1627e49a1e9
```

V1 passed Linux 7.0.x correctness validation, but its whole-live-set arena copying caused
approximately 2.86x raw lower-device writes on partial/incompressible churn and roughly
1.03 second rotation-triggering stalls on the 1 ms delayed test stack.

## V2 validated result

The validated V2 allocator is preserved on branch `v2` at:

```text
1e3a0c71b4e514bccae58d79be9f319640478b5c
```

Codex validated that exact revision on Ubuntu 26.04.1 / Linux 7.0.0-34-generic x86_64.

Passed V2 runtime gates included:

- Linux 7.0 GCC W=1 module build;
- five 100,000-operation deterministic randomized runs;
- mixed live-GC stress and victim selectivity;
- packed-container GC;
- injected lower read/write failures;
- 100 create/use/destroy lifecycle cycles;
- lower/upper DISCARD fallback behavior;
- bounded real Linux swap pressure;
- swapoff and a second swapon;
- host-LBA tracing across the complete disposable backing range.

V2 fixed the principal V1 allocator failure:

- partial/incompressible lower writes fell from about 2.86x raw to about 1.00x raw in the
  fixed-I/O virtual comparison;
- measured live-GC tail latency fell from about 1.03 seconds to about 7.662 ms.

The V2 performance limitation was request serialization. On the 1 ms/request virtual lower
stack, partial/incompressible QD8 throughput was about 3.85 MB/s while raw reached about
31 MB/s. This is expected from issuing one synchronous 4 KiB lower request at a time, but
it leaves too much per-request overhead for the intended slow-storage target.

The checked-in V2 model also had a test-fixture defect: its mixed-GC case could choose only
dead victims. A corrected fixture passed normally and under ASan/UBSan. The fixture is fixed
on `main` before V2.1 development.

No physical-media benchmark has yet been authorized or run.

## V2.1 current candidate

`main` is now V2.1.

V2.1 preserves V2 segment GC and adds a preallocated physical write batch:

- up to 8 consecutive 4 KiB output blocks;
- one contiguous lower request of up to 32 KiB;
- lower queue depth remains one;
- mappings are still published only after the entire lower batch succeeds;
- a failed batch leaves previous mappings authoritative;
- raw pages and compressed containers can share the same batch;
- GC replacement blocks use the same batching path;
- ordering barriers (read, discard, flush, PREFLUSH, segment transition) force the pending
  batch to commit first;
- the single-record compression coalescing wait is reduced from 0.5-1 ms to 50-100 us.

V2.1 adds status counters:

```text
physical_write_reqs
multi_write_reqs
max_write_batch
```

The next validation must prove that the new batch path preserves V2 correctness and reduces
lower request count/latency without reintroducing write amplification.
