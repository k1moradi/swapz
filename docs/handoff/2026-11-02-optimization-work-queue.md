# Historical 2026-11-02 optimization work queue

The complete work-queue narrative below is preserved verbatim from
[ROADMAP.md](../ROADMAP.md) at source commit `a9844fb1043f5a46f036c0ff6a5de274ec1359f5`. It includes the
November 2 ID181 cleanup plan, earlier host-specific optimization trials,
qualified and blocked historical runs, and rejected performance observations.
The heading **Current round** belongs to that historical record; it is not
the current task order or proof that those source revisions qualify today's
production tree. The active operating priority, exact-source release gates and
card-specific authorization are authoritative in
[AGENT_CONTEXT.md](../AGENT_CONTEXT.md); the live decision and report index
remains in [ROADMAP.md](../ROADMAP.md) and [README.md](../README.md).

## Immediate work queue

**Current round (2026-11-02, ID181 retirement and clean baseline).**
Owner decision: retire ID181 as a general production candidate without an
ARM64 factorial. The fixed x86 counterbalanced factorial showed no A/B/AB
policy meeting the >=10% normalized useful-WRITE objective, with added
lower-I/O requests in selected arms. This is failed promotion evidence, not
proof of universal regression. ARM64 already passed all five owner stages
with ID181 disabled on exact source `604866c1` (report `e760e91`);
x86 passed exact source `705589f` (report `c56dfdc`). Neither
qualification covers the cleaned removal commit. Preserve the historical
ID181 evidence above, and remove its default-off code, selectors, counters,
factorial tools and dedicated tests. Retain the production ID143/ID175
completion handoff and all other accepted scheduling/authority semantics.

Next work, in order:

1. Run CI on the narrow ID181 cleanup. Then run official owner `make test`
   on both x86 and ARM64 against the **same exact cleaned source SHA**.
   Both full five-stage results and their reports must pass before this
   source is a newly qualified baseline; do not infer PASS from rootless
   checks, older host reports or CI alone.
2. ID177: use the existing `CONTENT=representative` owner-supplied offline
   anonymous-page sampling and aggregate-only analyzer on the available
   host. Compare the same fixture/trace controls; never collect process
   RAM, enable swap, or publish raw representative page data.
3. Diagnose Fast QD4 (ARM64 -10.5% versus x86 +5.6% on the latest
   owner-host observations) before any policy change. Measure admission
   to ordered-owner service, preparation/deferral, window width,
   pages/lower request, ACK and completion delays, host CPU and lower
   service. Cross-host results are descriptive, not causal.
4. Collect ID175/ID169 exact-host evidence on the actual i3 when it is
   available. Preserve both mechanisms and their mixed/QD8 watchpoints.
5. Keep ID179, ID176, ID180 and ID164 closed/deferred. ID179 is weaker
   because measured seal time is small and earlier ID181 dispatch showed
   no material service win. ID162's nondefault hand threshold is a
   **separate possible cleanup**; do not remove it in this commit.

**Previous round (owner plan, after `3478aec`).** Adopted the ID174
per-device-class goals, promoted ID169 and implemented ID175; both now pass
on x86 and ARM64, with the i3 report outstanding.

The old-PC source `3ef72d9f67d6` passed native acquire-race coverage but its owner
`make test` report `fd5ed47e398e` is **BLOCKED at ID36**: the raw control
hit its existing 280-second limit before swapz ran under pressure. Read-only
stack evidence identifies filemap faults and `memory.high` throttling in raw
startup, not a proven swapz I/O stall. After the preserved failure, operator
intervention created this fixture's `pressure.stop` barrier to free ordinary
teardown. The narrow follow-up makes an already-failed owned ID36 pair signal
only its proven private stop barrier **before** starting safe device cleanup;
on success, full pressure remains active through teardown. Rootless simulation
covers failure-only signalling and symlink/unproven-path rejection. This does
not cure the raw startup slowdown, establish unattended privileged cleanup, or
qualify source/performance. Recheck unattended failure teardown on the owner
host, then investigate pre-replay harness fault charging without preloading
away the pressure test or extending its 280/840/960-second bounds.

ARM64 owner report `e73614c` (source `6c33294`, production delta64 +
DELTA64_SHUF8 + LZ4 everywhere) passed all five stages; the loaded delta64
positive path passed its hard gate, and its counts are now persisted as
`PASS_LOADED_DELTA64_POSITIVE`. The fast QD4 change from -25.7% (report
`9d30bf1`) to -12.4%/-12.9% is host load, not code: QD4 runs the sync4 path
with zero deferred ACKs, and host busy fell from 0.52-0.58 to 0.05-0.13 while
sync4 lower time per window fell 191-194 -> 179 us and the reissue gap
54-56 -> 40-41 us. A fast QD4 wave is 179 us lower WRITE + 40 us reissue +
3 us non-I/O; raw is bandwidth-capped at 84 MB/s, so a zero-gap K=1 ceiling is
about 90 MB/s (+7%) and parity needs a gap of 13 us or less. QD1 is latency-bound
(22 MB/s versus the 84 MB/s cap), so compression cannot win it while success
is tied to lower completion. On the SATA/NVMe4/NVMe5 envelopes (QD32 mixed,
compression 1.40-1.44x), the K=1 lane is busy only 64/47/37%, and 51-66 ms per
session pass with the lane idle and no admitted WRITE. Raw NVMe5 (538 MB/s)
below raw NVMe4 (612 MB/s) shows the raw arm is host-bound on this 7-vCPU VM.
The striped (ID160) and hand-threshold (ID162) experiments remain the next measurements.

The follow-up old-PC QD4 reissue diagnostic produced no valid causal timing
partition: the final raw-syscall observer lost 22,281 events, missed independent
operation/lower-request counts, failed host screening and exceeded its 10%
descriptive perturbation screen. Earlier attempts selected the wrong replay
engine and then silent named syscall tracepoints. All final benchmark byte
oracles passed, but these observations cannot select a production optimization.
The broad sync4 reissue timer includes acknowledgment, writer reissue,
admission/preparation and retention. Preserve qualified C; first prove bounded,
complete capture before attributing that whole interval to removable idle.


The old-PC owner run at `09e1cfaa` exposed zero fault-session handoffs.
Inspection found completion handoff using the eight-record dispatch constant,
although its contract requires four published BIOs. The native actual-body
test masked this with a private four-record definition of that dispatch
constant. Restore a dedicated four-BIO completion floor and compile actual
production constants in the regression. Source `b336754e3acb` passed all five
old-PC owner stages (report `8b67a9425025`), observing 16 live handoffs, eight
fault-session handoffs and 16,512 exact successful WRITEs across suspend/drain.
ID36 passed with eight CPU-pressure workers and 23,587 memory.high events.
Remote fixture changes independently permit zero fault-session handoffs while
preserving positive live suspend/drain activity. This qualifies the repair;
it does not establish a causal performance improvement from the threshold.
The fast async mixed arm still records 252 ms accepted-work lower idle,
including 188 ms undersized-batch attribution, and zero K=1 ready-run wait.
It performs no delta64 attempts on the medium fixture. Investigate the small-
batch/owner path before reopening concurrency or blaming delta64 for this
workload's service deficit. The separate five-pair positive-fixture rescue A/B
saves 68.5% lower WRITE bytes (95% CI 67.9..69.2% reduction); useful WRITE
changes +13.1% (CI -3.4..+29.7%), so throughput improvement remains unresolved.

The receiving x86 baseline and ID151 input-copy telemetry are owner-qualified
on modern x86 source `545defa8` (report `3465b4c08987`). The other x86 host passed
on `61739796` (report `2a40d0973839`); its identity/history stay separate. These
are x86 correctness results, not ARM qualification or universal performance.
ID149 direct BIO and ID152 API-based LZ4 state reuse are removed after fixed
pilots did not justify retention. Production remains stateless LZ4 with the
existing bounded submitter policy. ID152's fixed comparison recorded a positive
current-policy persistent-NVMe5 submitter direction and scoped guard/resource
trade-offs; it does not establish a gain on every storage/QD/content arm.

1. The reviewer's ordered sequence is now dispositioned through #3: ID156's
   first fixed pilot was unusable (71/72 exclusions) under the competing host
   workload. After that workload ended, a separately declared native-host
   comparison still missed its retention screen, and qualified production was
   restored. Keep the two studies distinct and do not repeat the same variant
   without a new measured opportunity and prospective plan. Any revisit must
   preserve the ID155 admission-close lifetime pin/join requirement; it is not
   current production behavior.
   ID157 separates null_blk backing allocation from apparent pack/submit
   ancestry. ID158 completed matched both-arm backing sensitivity with no
   product-source change. Profile the backend mechanism and residual owner
   operation before selecting further C work; preserve the canonical protocol.
2. Before timing a candidate, fix source order, samples, matched inputs,
   primary family, practical floor and exclusions. Use service and p95/p99,
   independent lower bytes/requests, GC and resource costs together. Require
   exact-source owner qualification for a retained production change.
3. Any admission measurement must separate lock wait/hold wall from CPU and
   quantify its instrumentation cost before selecting a production C change.
   Preserve exact lower-success/failure and suspend/drain behavior.
4. A custom small-table 4 KiB encoder remains unimplemented; ID152 tested an
   exported-API route, not that encoder. Reopen codec work only for a materially
   new mechanism with stronger measured end-to-end opportunity; do not repeat
   the same state-reuse variant or repeatedly sample it until significance
   appears. Never merge unqualified trials into host history.


The nine-idea review now has direct evidence for first-window lead (ID140)
and mixed barrier sensitivity (ID141); sleep/spin remains the unpromising
ID137 pilot. ID142 identifies ACK-loop interference, and the bounded ID143 handoff is now
qualified with a measured throughput/I/O trade-off. The remaining continuous
NVMe deficit needs fresh attribution; it is not explained by wave barriers. ID144 observes
completion-CPU locality without establishing causality; ID145 counter padding did
not justify retention. A future completion-delivery experiment must first audit
callback lifetime, CPU-hotplug fallback and drain ownership; these observations
do not authorize a cached-READ admission shortcut. ID146 locates the observed
wakeup path but its probe cost is too high for production timing. ID147 READ
notification deferral almost never reached the helper and is removed; entering
a deferred list is not proof of offload. A renewed candidate must explicitly
cover synchronous READ waits and demonstrate actual helper delivery. Selected-wait idle,
accepted post-lower delay and deferred-ACK wall have different scopes and may
overlap other work; never sum them into a CPU total or call the first the whole
device-idle budget. ID150 now tests submitter compression as one bounded candidate; lockless admission remains
conditional and is not a consequence of summing concurrent lock waits.

A dm-linear arm would be a DM calibration reference, not an exact unavoidable
overhead budget: DM has target-specific fast paths, while swapz owns clones,
ordering and completion state. Direct BIO submission and polling are separate
experiments. Upstream Linux v7.0 null_blk polling bypasses its timer completion
path, so enabling it only for swapz would change the device model relative to
raw ([driver source](https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/block/null_blk/main.c)).
A cached READ in admission requires pinned immutable cache/authority views plus
pending same-page WRITE, GC, DISCARD and fence safety; a generation check alone
is insufficient. Early ACK from staging remains a separate unapproved ID164 architecture
question requiring an explicit owner change to the lower-success publication
and failure contract; it is not authorized as a scheduling optimization.
