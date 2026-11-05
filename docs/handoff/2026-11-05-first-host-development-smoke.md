# First-host SD mapper development smoke

**Observed 2026-11-05. Scope: development-only physical mapper data-path
debugging. This is not physical qualification, real Linux swap qualification,
performance or endurance evidence, or production readiness.**

## Bound run

- Tested source and helper Git SHA: `81ddcfbf31bc5ff09efa5ce4b08a31959484af4f`
- Source was clean and synchronized to canonical `main` at admission and at
  the helper's final pre-execution check.
- The helper revalidated the opened authorized removable SD partition and
  bound its exact identity privately. Unique device identifiers, the run ID,
  recovery path and original-header digest are omitted from this public note;
  the root-owned recovery record retains them.
- The development helper, formatter, module and oracle SHA-256 values were
  bound to the run:

  | Artifact | SHA-256 |
  | :--- | :--- |
  | Physical helper source | `026fc956b11b873d5c07d273b6dc1e393b40e0a7d27d13bd90744a50b66b69b7` |
  | `swapzctl` formatter | `02c3a897f5742fb67dd1ecc9c08d65b17c7b654b5e24e6429e6c1f43f10e0847` |
  | `dm-swapz.ko` | `989b9b22b4d77828ee63d5019b0120e6c58dac1597d8c4a59cca2b0473d14beb` |
  | `device-roundtrip` | `871d809976361bcd2d30b91bd4f661da8c712c16e4f5fa584696140261b57f26` |

## Admission and result

The fresh `make fast_test SCENARIOS=fast-mixed REPEAT=1 RESUME=1` evidence
record had a passing build and 59 native/replay checks (one skipped). Loaded
preflight returned the exact environmental refusal
`unclaimed_null_blk`; the helper permits that refusal only for this narrow
development smoke and left those unclaimed resources untouched. A second
helper invocation reused the matching private native/replay PASS checkpoint,
refreshed the product build and loaded preflight, and again encountered that
same preflight refusal before benchmark execution. The helper's fresh nonce
and admission record were not taken from the checkpoint.

The physical helper then returned:

```text
PHYSICAL_DEVELOPMENT_SMOKE=PASS
EVIDENCE_CLASS=DEVELOPMENT_ONLY_NOT_PHYSICAL_QUALIFICATION
```

One `byte-exact-opened-dm` oracle phase ran successfully. The production-C
oracle wrote 128 deterministic 4 KiB pages, flushed them, read and compared
all 128 pages, overwrote 64 pages, then read and compared all 128 pages again:
256 complete page comparisons, zero mismatches. Two explicit oracle flush
barriers completed. The Device Mapper counters recorded 386 successful flush
operations and zero flush errors during the phase.

| Observation | Result during the oracle phase |
| :--- | :--- |
| Target-reported lower READ | 1,052,672 bytes / 257 requests |
| Target-reported lower WRITE | 749,568 bytes / 183 requests |
| Parent block-stat READ | 1,064,960 bytes / 260 requests |
| Parent block-stat WRITE | 749,568 bytes / 183 requests |
| Target-reported flushes | 386 successful / 0 failed |

Parent block statistics are host-visible device counters and can include
unrelated host activity; they are not NAND-wear measurements. Across setup,
oracle and recovery, the parent counters changed by 3,182,592 READ bytes / 363
requests and 761,856 WRITE bytes / 186 requests.

## Recovery and limits

The helper reached durable `COMPLETE`. Its saved and final 4 KiB header hashes
matched exactly. The target remained inactive Linux swap; no `swapon` or
`swapoff` was performed by this development mode. The owned mapper and module
were removed normally, the one-use run claim remained consumed, the active
partition marker was absent, and the unrelated mapper inventory was
unchanged.

This establishes one bounded physical mapper-page round trip on the tested
source and artifacts. It does not establish real anonymous-page swap, a
production lifecycle, full-card capacity or measured RAM fit, sustained GC or
churn, physical-media performance, NAND endurance, deployment readiness, or
production readiness.

## Qualification blockers at observation (historical)

Exact-source GitHub CI for the tested SHA was not fully green. The production-C
workflow failed on x86_64 and arm64 in two primary mount-namespace cases: the
selected partition and selected parent were accepted where the tests expected
refusal in a non-leader thread namespace. The native project-goals workflow
then failed its exact-SHA prerequisite. The physical-evidence adversarial,
systemd/package, and private kernel-debug/static workflows passed. Official
owner `make test` and real anonymous swap were not run as part of this smoke.

This is the 2026-11-05 state for the tested source, not a verdict on later
`main` changes. Check [issue #94](https://github.com/k1moradi/swapz/issues/94)
and [current evidence](../README.md#current-evidence) for subsequent qualification.
The recorded follow-up was to resolve the mount-namespace CI defect, obtain
green exact-source CI, then run official owner `make test`. Only after its
required gates and real-swap admission pass could primary-manager
anonymous-page qualification proceed, with independent
`pswpout`/`pswpin`, cgroup swap charge, mapper and backing-device I/O, byte
oracle, OOM and normal-teardown evidence. Preserve the current unclaimed
`null_blk` refusal; it is not permission to remove or adopt those resources.
