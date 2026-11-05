# First-host current-source SD mapper development smoke

**Observed 2026-11-05. Scope: bounded physical mapper data-path debugging only.
This is not Linux anonymous-swap qualification, physical acceptance,
performance/endurance evidence, or production readiness.**

## Source and artifact binding

- Tested source and helper Git SHA: `7c7bc9743580d7592315be00bdc8eaf7b019a1d2`.
- The checkout was clean and matched canonical `main` at helper admission and
  the final pre-execution check. `main` advanced after this completed run; this
  record remains bound to the tested SHA and is not re-labelled as evidence for
  a later commit.
- The helper bound the intended dedicated removable SD target. Device paths,
  UUIDs, parent serials, run ID, recovery pathname and original-header digest
  remain in the private root-owned record.
- The helper generated fresh nonce-bound `make fast_test RESUME=1` evidence.
  Build and native/replay checks passed using a matching checkpoint. Loaded
  preflight was `BLOCKED` only at `unclaimed_null_blk`; the helper permits this
  exact refusal for the narrow development smoke. The ambiguous `null_blk`
  objects were left untouched, and no loaded benchmark was claimed.

| Bound artifact | SHA-256 |
| :--- | :--- |
| `physical-swap-probe.py` | `026fc956b11b873d5c07d273b6dc1e393b40e0a7d27d13bd90744a50b66b69b7` |
| `swapzctl` formatter | `6749ae42260c0316f60f33d34d9eec67263284f666d19062adde848386f0e297` |
| `dm-swapz.ko` | `42abf3be69cd02c05cdb94a4d149d43d5b6f7344a264767f327cca42c5330d6f` |
| `device-roundtrip` | `871d809976361bcd2d30b91bd4f661da8c712c16e4f5fa584696140261b57f26` |

## Physical mapper oracle

The helper recorded one successful `byte-exact-opened-dm` phase. The existing
production-C oracle wrote and flushed 128 deterministic 4 KiB pages, read and
compared all 128, overwrote 64 pages, flushed, and read and compared all 128
again. That is 192 logical page writes (786,432 bytes) and 256 full-page
comparisons (1,048,576 bytes verified), with zero mismatches. Both readback
loops completed; the oracle exits on the first byte mismatch.

| Observation | Result |
| :--- | :--- |
| Oracle phase | 1; `byte-exact-opened-dm` PASS |
| Mapper logical WRITE | 786,432 bytes |
| Mapper logical READ | 1,650,688 bytes |
| Mapper lower WRITE | 749,568 bytes / 183 requests |
| Mapper lower READ | 1,052,672 bytes / 257 requests |
| Mapper flushes | 386 successful / 0 failed |
| Mapper error counters | failed=0, error=0 |
| Header recovery | Exact original 4 KiB header restored |
| Final target state | Inactive swap; no mapper or module remains |

The mapper counters provide target-attributed lower-I/O observations. The
separate parent-device counters changed by 3,182,592 READ bytes / 363 requests
and 761,856 WRITE bytes / 186 requests across setup, oracle and recovery; those
host counters can include unrelated activity and do not measure NAND wear.

## Recovery and limits

The private root-owned run record reached durable `COMPLETE`, confirmed the
saved and final header bytes matched, and recorded normal mapper removal and
module cleanup. The target remained absent from the kernel swap inventory.
Development mode did not call `swapon` or `swapoff`. The original header hash,
unique target identifiers and full raw telemetry remain in the private record.

This proves one bounded mapper-page round trip on source
`7c7bc9743580d7592315be00bdc8eaf7b019a1d2`. It does not prove real anonymous
swap-out/in, full-card capacity, measured full-capacity RAM, sustained GC or
churn, physical-media acceptance, deployment readiness, or production
readiness.

At the time exact-SHA CI completed, both x86_64 and ARM64 production-C jobs
passed, as did the rootless production-readiness, lifecycle-audit,
source-contract, make-interface, repository-policy, systemd/package,
physical-evidence-audit and private kernel-debug/static jobs. The native
rootless job failed in `rootless-direct-evidence-test.py`: its synthetic marker
included `test=unavailable`, while the reporter did not preserve that
authenticated first-failure attribution. Commit `8ae66d20` corrected the
reporter and added regressions. The focused
`rootless-direct-evidence-test.py` then passed on source
`464128c4e02e4ddb8627f73c74baafa2c91f9307`. Exact-head GitHub CI for that
later source was queued when this record was updated; it is not presumed to
have passed.

Next: require green exact-source CI, then qualify the current exact source with
the official owner-host path. The first host's loaded preflight still refuses
the existing unclaimed `null_blk` instances; obtain demonstrably owned
RAM-backed test storage without adopting or removing those instances. Only
after loaded qualification and real-swap admission pass should the existing
Linux anonymous-swap acceptance path proceed, with independent
`pswpout`/`pswpin`, cgroup, mapper/backing-I/O and byte-oracle evidence.
