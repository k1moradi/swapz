# Old-PC QD4 reissue diagnostic: capture rejected

The diagnostic ran, but its trace is **invalid for causal attribution**.
No interval partition or production optimization follows from it. Production C,
the private replay and `test_results.json` are restored/unchanged; the latest
owner-qualified production source remains `b336754e3acb`.

## Scope and technical corrections

The plan uses unchanged C at `324fbad227d9`, medium content, delta64 off,
submitter preparation on, hand width eight, and the existing fast WRITE QD4
`make fast_test` scenario. Storage remains newly owned RAM-backed null_blk.

The initial observer incorrectly assumed native replay. The actual protocol
uses Python threaded persistent workers; its report explicitly says
`replay_engine=python-threaded`. That capture has zero measurement gates and
is invalid. A second observer with two temporary one-shot Python boundary
markers also has zero gates. A bounded standalone marker check then proves
that named syscall tracepoints do not fire on this host, while raw syscall
tracepoints observe the same root Python writes. These failed captures are
preserved separately and are never performance replacements.

The final corrected observer uses raw x86_64 syscall events plus generic DM
entry/return, block, workqueue and scheduler events. Fresh untraced controls
bracket it. The two boundary writes are outside per-I/O execution, and the
exact original replay is restored before the post-control. The workload,
device model and production C do not change. Kernel is 7.0.0-38-generic and
bpftrace is 0.25.0; this observation is specific to this host/tool combination.

## Final measurements

| Observation | Raw WRITE MB/s | swapz WRITE MB/s | swapz WRITE p99 ms | Screen |
| --- | ---: | ---: | ---: | --- |
| Pre-control | 74.36 | 37.57 | 0.967 | NOISY |
| Traced | 61.56 | 34.13 | 1.132 | NOISY |
| Post-control | 71.63 | 35.85 | 0.890 | SCREENED |

All six arms pass the complete-image byte oracle with 4,096 measured WRITEs
per arm, zero measured READs, identical scenario fixture/trace hashes and
unchanged effective policy. These are single diagnostic observations, not
paired performance evidence. The traced swapz/raw ratio differs +10.25% from
the geometric mean of the flanking ratios, exceeding the prospective 10%
perturbation screen. This is not a product improvement or an exact profiler
overhead estimate: the host screen also failed for two observations.

## Completeness failure

The final observer stops cleanly and records two nonoverlapping measurement
gates, but bpftrace reports **22,281 lost events**:

| Event | Required raw | Captured raw | Required swapz | Captured swapz |
| --- | ---: | ---: | ---: | ---: |
| WRITE syscall entry | 4096 | 4096 | 4096 | 2072 |
| WRITE syscall return | 4096 | 4096 | 4096 | 1966 |
| Lower request issue | 4096 | 4096 | 1193 | 748 |
| Lower request completion | 4096 | 3786 | 1193 | 943 |

The required lower counts come independently from the benchmark report. Missing
events prevent a complete operation/request population and reliable scheduler
correlation. No claimed CPU budget, GIL attribution, retention share, wakeup
latency distribution or reissue critical path is computed. Even an apparently
plausible subset would be selected from an incomplete capture.

The production `sync4_reissue_gap_ns` timer remains a broad successful
four-record-commit-to-next-commit-start interval. It includes completion,
writer reissue, admission/preparation and retention; it must not be treated as
entirely removable idle or CPU cost. A future capture needs a smoke-proved
engine gate and bounded event transport with complete independent counts and
an acceptable perturbation screen before guiding a C change. No further
capture was collected after this final failed completeness check.

Local artifacts, including invalid captures, corrected plans, module/symbol
snapshots, all benchmark reports, restored-runner copy and `result.json`, are
under `build/optimization-round/qd4-reissue-oldpc/`. `SHA256SUMS` covers 47
files. No diagnostic point enters qualification history and no new plot is
generated; the host history still ends at owner source `b336754e3acb`, report
`8b67a9425025`. All observers have stopped and owned DM mappings are removed.
