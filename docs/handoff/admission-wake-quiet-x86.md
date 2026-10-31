# Native-host admission-wake comparison: prospective plan

**Final disposition:** the fixed comparison completed and the candidate was
declined/restored. See [the result](admission-wake-quiet-x86-result.md).
The text below preserves the pre-sample plan.

The owner reported low host load. Live checks confirmed the competing tracing
benchmark had exited and three quiet windows passed the existing thresholds.
Additional pre-declaration windows measured 4.4..8.2% busy with low CPU PSI and
zero steal. This is a native x86_64 Lenovo 82BG/i7-1185G7 host;
systemd-detect-virt reports none. The standard CPU counter reader includes steal
as a field on native machines too; its presence is not evidence of a VM.
RAM-backed null_blk still provides configured service models rather than
physical NVMe fidelity.

[The new prospective plan](admission-wake-quiet-x86-plan.json) declares twelve
AB/BA rounds on six workloads, with raw/target order reversal and immutable
source/helper/input hashes. The three mixed useful-WRITE/raw primary endpoints
retain a +3% practical floor, 98.3333% paired log-t intervals, family-adjusted
exact sign tests and minimum nine usable pairs. Latency, independent lower I/O,
GC and resource costs remain part of retention review. Exclusions are fixed,
without replacement. A quiet-entry check runs again before the first sample;
normal per-pair screens remain mandatory afterward.

The source candidate is unchanged from the development-validated admission-wake
draft: C SHA-256 60de23cda5f6c81ce87d4d3f6154e238e8a3c1685097b00b758ea874497c7896.
Its loaded correctness and concurrent lifetime review remain supporting evidence;
retention still requires justified performance and exact-source make test.
Committed production remains qualified source 545defa8. No source promotion,
new qualification report or plot is claimed by this plan.

The preceding 24-block noisy pilot and its 71/72 exclusions remain intact in
[their original result](admission-wake-x86-result.md). The verified host-load
change motivates a new prospective study; no observations are pooled, replaced
or selectively reused from that completed pilot. Results are pending at this
plan's publication.

Before any performance sample, two entry attempts rejected their first startup
window while subsequent windows were low. Both preflight records are preserved
locally; neither created a device or a benchmark observation. The entry protocol
now includes a fixed two-second interpreter/import settling interval before all
three quiet windows, matching the distinction between initialization and quiet
measurement. Thresholds and the fixed performance sample count are unchanged;
this amendment precedes every performance sample in the new series.
