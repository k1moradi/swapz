# x86 LZ4 state-reuse experiment: declined

Production C and all temporary test/development-loop edits are restored to
qualified stateless source `545defa8a1ba21f5dd49cd16a1566806e75b71ec`.
C SHA-256 is `78f2d7de073a644c9c4182a0865e57ebdfce8b6d07cc02a4ae5578a8cd3d569a`.
That source passed all five owner `make test` stages; report
[`3465b4c08987`](https://github.com/k1moradi/swapz/blob/3465b4c08987d6d98592f30622485ad5b872acb0/test_results.json)
was published and automatically generated the three-report/42-point identified
history for this computer. The other host's PASS report `2a40d0973839` on
`61739796ca64` has a different machine digest and remains outside this history.

## Experiment and safety evidence

The candidate used the exported kernel continuation API with an empty
dictionary after every call, and zeroed existing scratch once at allocation.
It replaced all three ordinary/predictor/rescue call sites, preserving timer
scope and clearing source references on capped failure too. It changed hash
mode as well as reset cost; it was not a custom small-table 4 KiB encoder.
All 93 source contracts passed, including actual-helper stub checks and
guarded input reuse/independent decode against liblz4. Native liblz4 tests do
not prove kernel reset performance or kernel long-reuse behavior.

Real-kernel validation separately exercised all scratch-owner classes, capped
failures/RAW fallback, submitter delta64 adoption and independent image/packed
readback. One ordered stream made 294,774 successful timed calls, processing
1,207,394,304 bytes with zero RAW fallbacks. Another balanced run passed with
both compressed results and RAW fallback. The loaded/installed kernel LZ4
source versions matched; its installed binary compares offset to 0x40000000.
The long run crosses that reset threshold. Final images were verified; not
every overwritten intermediate record was decoded. Full candidate W=1/W=2,
fault/lifecycle/ID36 owner qualification and other-host qualification were not
run because the performance screen declined retention.

## Prospective fixed source comparison

Twelve chronological rounds used ABC, ACB, BAC, BCA, CAB, CBA twice, one
observation per source/scenario/block. Raw/candidate replay order reversed
every round. A was qualified stateless code with submitter preparation
disabled; C was that same code with submitter preparation enabled; B was the
state-reuse candidate with submitter preparation enabled. A is a same-source
policy control, not a historical pre-ID150 binary. Content, native trace,
model geometry, warmup and useful operation counts were matched.

Six scenarios covered persistent NVMe5 mixed, SATA mixed, fast mixed and fast
WRITE QD1/4/8. All 216 owned pairs/432 arm oracles passed. The nine-primary
family was three contrasts (B/A, B/C, C/A) on the three mixed workloads.
Endpoint: paired log change in useful WRITE divided by each arm's own raw
control. Practical floor: +3%. Intervals are 99.4444% paired log-t intervals;
exact two-sided sign tests use alpha 0.05/9. Paired-model assumptions and
chronological host-load dependence remain explicit.

Only NVMe5 rounds 1, 6 and 7 were excluded, without replacement: their
three-source raw spreads were 10.40%, 27.47% and 13.86%, beyond 10%. All other
triplets met the declared provenance and host screens. Screening is not proof
of an idle host or physical NVMe fidelity.

| Mixed scenario | Contrast | n | Normalized WRITE change | Family interval | Adjusted sign p |
| :--- | :--- | ---: | ---: | :--- | ---: |
| nvme5-mixed-lanes | B/A | 9 | +11.30% | +5.37..+17.57% | 0.03516 |
| nvme5-mixed-lanes | B/C | 9 | -3.60% | -9.45..+2.63% | 1.00000 |
| nvme5-mixed-lanes | C/A | 9 | +15.46% | +8.82..+22.50% | 0.03516 |
| sata-mixed | B/A | 12 | +7.86% | +3.87..+12.00% | 0.00439 |
| sata-mixed | B/C | 12 | +0.58% | -2.79..+4.07% | 1.00000 |
| sata-mixed | C/A | 12 | +7.24% | +2.77..+11.90% | 0.05713 |
| fast-mixed | B/A | 12 | -0.39% | -1.30..+0.52% | 1.00000 |
| fast-mixed | B/C | 12 | -0.44% | -1.09..+0.21% | 1.00000 |
| fast-mixed | C/A | 12 | +0.05% | -0.72..+0.82% | 1.00000 |

B/C persistent NVMe5 missed the declared floor, so the new API state work is
declined. Its interval includes loss and zero and does not support equivalence
or a regression claim. The positive B/A combination does not demonstrate an
incremental benefit beyond existing submitter preparation. No further samples
or independent confirmation were funded for this variant.

C/A supports a persistent-NVMe5 submitter-policy benefit on this host. Useful
WRITE arithmetic means were 993.07 MB/s disabled versus 1147.49 enabled; own
raw controls were 3611.56 and 3613.77 MB/s. Paired geometric effects differ from
ratios of these rounded means. SATA C/A did not pass the adjusted sign criterion
despite its positive interval. Fast mixed remained inconclusive.

## Guardrails and resource costs

Persistent C/A descriptive secondary effects were READ p95/p99 -16.63/-22.85%,
WRITE p95/p99 -11.44/-12.97%, lower WRITE bytes -0.16% and requests +0.77%.
These secondary intervals are pointwise 95%, not new family-qualified claims.
Fast WRITE QD1/QD4/QD8 C/A effects were -0.24/-0.65/-3.12%; QD8's descriptive
95% interval was -5.31..-0.88%. This is a guard signal, not an unqualified
whole-workload win. All p95/p99, independent lower READ/WRITE/flush counts and
CPU/RSS observations and intervals are in the packets. Lower traffic remains
a host-I/O proxy, not NAND endurance evidence.

Native task system time rose about 57.5% for persistent C/A. Compression now
runs in the measured task rather than excluded kworkers, so this accounting
change cannot establish total kernel CPU cost. Total CPU remains unresolved.
Eight submitter lanes request 134,912 extra bytes for lane structures and LZ4
scratch with delta64 off (448-byte lane verified from module DWARF). Default
delta64 scratch adds 65,536 bytes. These are requested sizes, not allocator or
physical RAM measurements; native RSS excludes kernel allocations. B/C retained
the same requested scratch size. Short comparison runs do not qualify sustained
GC; the restored production revision retains its existing owner GC/fault/drain
and ID36 qualification. No swap activation or physical-backing test occurred.

## Artifacts and next work

- [Readable analysis and hashes](lz4-state-x86-result.json)
- [Complete compressed packet](lz4-state-x86-pilot.json.gz): fixed plan, all 36
  blocks, exclusions, validation data, source/module hashes and analysis scripts.
- [Unapplied experimental bundle](lz4-state-x86.patch): compiled/development-
  tested on this host, not owner-qualified or retained. Verify the base/hash
  before any future reuse. Raw logs and generated binaries remain ignored.

The standard-library state-reuse trial is not a result for a custom small-table
encoder, which remains unimplemented. The next reviewer stage is CPU-targeted
completion delivery (#4), with callback lifetime, offline-CPU fallback, actual
READ/WRITE delivery and drain joins audited first; lighter admission (#3) follows.
Do not revive the removed READ-list-only handoff or treat lock-frame samples as
a removable CPU budget. No unqualified trial was added to performance history.
