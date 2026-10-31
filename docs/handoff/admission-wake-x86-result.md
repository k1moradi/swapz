# Admission-wake pilot: performance unusable, candidate not retained

All twelve fixed rounds/24 source blocks/144 owned pairs completed; all 288
raw/target arm byte oracles passed. The noise/provenance screen excluded 71 of
72 scenario-round comparisons. There are **zero usable pairs on every primary
workload**, so no throughput, latency, lower-I/O or CPU effect is established.
The candidate is not promoted. This is not a demonstrated regression or proof
of equivalence. No replacement samples or further confirmation were collected.

Production C and all temporary native, loaded and development-loop changes are
restored exactly to qualified source `545defa8`, report `3465b4c08987`.
C SHA-256: `78f2d7de073a644c9c4182a0865e57ebdfce8b6d07cc02a4ae5578a8cd3d569a`.
The normal restored build succeeds. No owned DM devices remain.

## Evidence and exclusions

The [prospective plan](admission-wake-x86-plan.json) fixed twelve AB/BA rounds,
reversed raw/target order, six matched workloads, a three-primary family,
+3% floor, paired intervals and adjusted signs, and exclusion without replacement.
Source/module/helper and fixture/trace/payload/image hashes remain in the packet.
No source changed during the pilot. Persistent NVMe5, SATA mixed and fast mixed
all have n=0 after screening. Only fast WRITE QD1 round 3 survives as an isolated
secondary observation; n=1 cannot support an interval, repeatability, guardrail
or equivalence claim. Do not aggregate excluded means into a product judgment.

Of 144 source/scenario observations, A was NOISY in 66 and B in 69. Twelve
scenario-round pairs also exceeded the 10% paired raw-WRITE drift screen, with
spreads from 10.62% to 58.63%. Quiet-window busy fractions were frequently
36..38%, above the 25% screen; CPU PSI also caused exclusions. Missing input or
CPU geometry was not the reason. All raw results, p95/p99, independent lower
bytes/requests, resource and internal counters remain available for diagnosis.

A post-pilot live inspection found an unrelated tracing benchmark still running
and consuming about 163% process CPU. This supports the host-load explanation;
it does not attribute every interval exactly. That workload was left untouched.
The fixed pilot was completed and screened as declared, rather than selectively
repeating noisy observations. Before any future performance experiment, require
the external workload to finish and check quiet windows prospectively; a changed
host-load condition and a new fixed plan are necessary. Do not keep sampling this
pilot until significance appears or weaken the screen to recover comparisons.

## Candidate correctness and limits

The [candidate review](admission-wake-x86-review.md) and
[validation packet](admission-wake-x86-validation.json.gz) preserve the ownership
proof and pre-pilot development checks: 93 source contracts, actual helper-body
ASan/UBSan interleavings, normal build, owned readback, live GC, DISCARD,
suspend/resume, retained faults and later completion-handoff failure. The
non-submitter path caches BIO-derived wake policy, pins the target under the
admission-close lock, queues outside it and releases as its final target access.
Drain joins those tails before draining queues. Submitter-lane ownership remains
unchanged. All candidate pilot sessions ended with admission_wakes_active=0 and
no byte-oracle failure. These are development correctness results, not full
candidate owner/ID36 qualification or a performance benefit.

The candidate adds one target atomic counter and its operations, without a new
per-I/O allocation or I/O buffer. Struct/allocator rounding, physical RAM and
CPU effects remain unmeasured. Every pilot timed GC-victim delta was zero;
pre-pilot loaded GC is correctness evidence, not sustained performance. No swap
activation, physical backing, reboot or unrelated device removal occurred.

## Preserved artifacts

- [Complete pilot packet](admission-wake-x86-pilot.json.gz): all 24 blocks,
  source/module/helper/input hashes, screens, status snapshots and scripts.
- [Readable exclusions and unavailable effects](admission-wake-x86-result.json).
- [Unapplied candidate bundle](admission-wake-x86.patch), unchanged from the
  frozen pilot; development-tested, not owner-qualified or retained.

This round generated no owner report/history point or plot. This computer's
qualified history still ends at source `545defa8`, report `3465b4c08987`.
Keep other hosts and this unqualified pilot separate. During competing host
work, continue source/ownership review and bounded non-benchmark work; do not
claim a performance answer from these excluded results.
