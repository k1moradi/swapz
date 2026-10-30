# Receiving x86 continuation — 2026-10-30

The unchanged lifetime repair is qualified on this host. The direct-BIO draft
compiled and passed development checks, but the bounded service pilot did not
justify retaining it. Production `dm-target.c` is restored byte-for-byte to
SHA-256 `8a5ebda7575653ff0807cc89ee958a14602d5f355a6a4f7abc59647ae997870f`.
The tracked patch remains unapplied, with its original hash and actual-body tests.

## Host and baseline qualification

The host is a native Lenovo 82BG with an i7-1185G7, four cores/eight threads,
eight online and affinity CPUs, running `7.0.0-42-generic`. Boot logs report
enabled xstate mask `0x1ae7`, including AVX-512 registers; the loaded module
selected scalar classification and AVX-512 transform/inverse. Native scalar,
SSE2, AVX2 and AVX-512 byte-equivalence/execution checks passed. Native
transform/inverse ns/page were respectively 244/183, 165/264, 78/117 and 79/90;
these exclude the kernel FPU wrapper and do not establish an I/O speedup.

Firmware reports eight 2 GB Micron LPDDR4 devices configured at 4267 MT/s;
Linux exposes 16,099,928 KiB total RAM. This is inventory, not a memory-bandwidth
measurement. The CPU governor was powersave with turbo enabled. Secure Boot is
enabled and the normal module was signed with the configured MOK. No host
power, memory, swap or device-model settings were changed for comparisons.
The [host profile](x86-host-history.json) records domain-separated OS and firmware
identity digests without publishing their raw identifiers.

Exact source `a2b556998a8554b4f64960c77d6818fce1d4e811` passed all five
`make test` stages; report-only commit
[`c0feb2127c05ffde1826e250e1ade55918d21448`](https://github.com/k1moradi/swapz/commit/c0feb2127c05ffde1826e250e1ade55918d21448)
was pushed to main. Loaded evidence includes 4,096-page GC readback, 20 distinct
victims/rotations, suspend/drain, retained WRITE/FLUSH faults, 275 ACK handoffs
and exactly 16,512 completed WRITEs, plus 2,048 verified RAW/balanced pages.
ID36 passed with 16 CPU workers, 16,652 memory.high events, no OOM failure and
664,109,056 peak cgroup bytes. No active-swap or physical-backing test was run.

Fresh async mixed observations below use each session's matched raw control.
They are descriptive means, not cross-source confidence results. The serial
and fast models use default rescue-on; the modern envelope mixed arms are LZ4-only.

| Synthetic model | Useful WRITE raw / swapz MB/s | Useful READ raw / swapz MB/s | READ p99 raw / swapz ms | Lower WRITE bytes / requests saved |
| :--- | ---: | ---: | ---: | ---: |
| Serial 10 MiB/s, 1 ms | 2.87 / 14.00 | 0.95 / 4.65 | 33.69 / 14.75 | 30.4% / 91.5% |
| Fast 80 MiB/s, 150 us | 63.01 / 118.08 | 20.92 / 39.19 | 12.76 / 0.395 | 29.5% / 89.1% |
| SD envelope | 23.02 / 82.31 | 7.64 / 27.32 | 4.29 / 1.11 | 30.5% / 91.7% |
| SATA envelope | 425.38 / 303.94 | 141.19 / 100.89 | 0.114 / 0.278 | 30.5% / 91.6% |
| Gen4 envelope | 1397.19 / 554.91 | 463.76 / 184.19 | 0.040 / 0.116 | 30.6% / 91.6% |
| Gen5 envelope | 890.49 / 558.29 | 295.58 / 185.31 | 0.056 / 0.221 | 30.1% / 90.8% |

SATA/NVMe remain service/latency versus lower-I/O trade-offs. Configured caps do
not establish physical NVMe fidelity; achieved raw service is explicit. Neither
the Gen4/Gen5 ordering nor low 4KiB rates identifies RAM bandwidth as the cause.
The earlier `4886c4d7` report still lacks a proven physical-host match and is
not joined to this history; the four-CPU SSE2 report remains separate too.

## Direct-BIO keep/remove decision

The exact portable draft C SHA-256 was
`b34bbb2a7f4741f49912226659bb92be482643d2cd3d469c49c14374a9fb937a`.
The signed x86 kernel build and all 91 target source contracts passed, including
actual callback/submission bodies, inline/delayed completion, error statuses,
construction rollback, bounds and descriptor reuse. To execute these checks
through the supported development entry point, the pilot temporarily added the
source-contract suite to `make fast_test`; that hook is removed with the trial.
The compiled context grew 24,832 -> 25,984 bytes. This is requested structure
size, not a measured allocator/RAM saving or total resource measurement.

The prospective [complete pilot packet](direct-bio-x86-pilot.json) contains the
fixed plan, all 108 raw/swapz pair observations (216 byte-exact arm runs), exact
C/patch and source-manifest hashes, every exclusion and paired round summaries.
Full local logs and manifests remain under `build/handoff-x86/`. The source
sequence was control/candidate, candidate/control, control/candidate; each block
ran two repeats on seven medium scenarios plus balanced SATA and entropy NVMe4.
Repeated observations were averaged in log space within each block; the three
source rounds, not the six repeats, were statistical units. Both repeats in
both source blocks had to be SCREENED, provenance-matched and within 10% paired
raw-WRITE drift. Excluded rounds were not replaced.

Primary endpoint: candidate/control change in useful WRITE divided by its own
raw control. Practical floor: +3%. The three-endpoint family used 98.333% paired
log-effect t intervals and exact two-sided sign tests at 0.05/3. This three-round
pilot cannot satisfy the adjusted direction test even with unanimous signs;
its role was to fund or decline a larger fixed confirmation, not retain code.

| Primary workload | Usable rounds | Normalized WRITE change | Paired interval | Exact sign p |
| :--- | ---: | ---: | ---: | ---: |
| Medium SATA mixed | 2 | -0.38% | -11.95% to +12.70% | 0.50 |
| Medium NVMe5 persistent mixed | 1 | +3.30% | unavailable | 1.00 |
| Medium fast mixed | 3 | -0.41% | -2.02% to +1.23% | 0.25 |

SATA round 3 failed the post-busy screen. Persistent NVMe5 rounds 2/3 failed
within-control repeat spread and paired raw drift. Balanced SATA round 2 and
entropy NVMe4 round 3 failed pre-busy screens. All correctness observations
remain in the packet. These screens do not prove the host was otherwise idle.

Secondary normalized point estimates were +1.28% for matched NVMe5 waves,
+0.05%/+6.11%/+0.10% for fast WRITE QD1/4/8, -4.87% for balanced SATA and
+1.00% for entropy NVMe4. These do not establish gains, regressions or
equivalence. QD1/4 had zero detached runs, while the mixed/QD8 candidate arms
exercised hundreds of direct submissions per repeat. The QD4 estimate therefore
does not demonstrate adapter service benefit.

No lower-I/O or tail-latency benefit justifies retention. In usable fast-mixed
rounds, descriptive lower WRITE requests rose about 0.69% and bytes 0.035%;
WRITE p99 was about 3.56 ms in both arms. Entropy NVMe4 requests rose about
1.99% with equal bytes. Fast QD8 WRITE p99 was 4.73 -> 6.02 ms descriptively,
despite near-zero normalized useful-service effect. These are costs/opportunity
checks, not statistically established regressions. The packet retains READ
rates/p95/p99, independent lower READ/WRITE counters, replay CPU/RSS and host
CPU/PSI observations. Replay CPU does not measure total kernel CPU. The short
pilot does not qualify GC/resource-pressure behavior of the candidate.

**Remove the adapter and its changed source tests.** Keep the immutable draft
as an unapplied artifact and do not reopen it unchanged without a new material
mechanism/workload hypothesis. No candidate exact-source owner qualification,
ARM build or forced-split/genuine split-child-error coverage was completed.
Those remain mandatory before any future retention; passing ordinary byte
oracles is not a substitute. Production returns to the already-qualified
lifetime repair with unchanged ownership, publication, allocator and GC policy.

## Separate history artifacts

The thin history helper now supports an explicit audited x86 host profile and a
distinct `build/history/x86-i7-1185g7-avx512/` output. It requires full selected
report SHAs, host digest, matching CPU count, executable scalar/SSE2/AVX2/AVX-512
evidence and five passing stages. Old matching ISA/CPU counts alone cannot
admit a report. ARM selection, outputs, snapshot immutability and line-break
rules remain covered. Automatic ARM refresh is skipped on x86; receiving-host
refresh uses the explicit profile and never labels ARM points as new x86 data.
Matplotlib was missing here and was installed from the distribution packages
before the pilot; no package installation or plot rendering overlapped it.

All newly rendered plots are displayed inline in the continuation chat. The
stable local index points to immutable image/data snapshots. No unqualified
pilot observation is included in the qualified history or claimed as physical
storage/endurance evidence.
