# First-host physical mapper smoke on `fe7ae0e4`

**Observed 2026-11-05.** This is a development-only, source-bound physical
mapper data-path result. It is not real Linux anonymous-swap qualification,
full-card acceptance, or a production-readiness PASS.

## Source and build identity

- Branch: `main`; tested source: `fe7ae0e4f2800150ea1c13a843519945e4f5c789`.
- The helper checked that local `main`, `origin/main`, and canonical remote
  `main` matched before the physical write. A fetch after teardown confirmed
  that `main` still matched this source.
- The checkout was clean at admission and remained clean after the run.
- `physical-swap-probe.py` SHA-256:
  `026fc956b11b873d5c07d273b6dc1e393b40e0a7d27d13bd90744a50b66b69b7`.
- Formatter SHA-256:
  `2f05ee70fd69d14e7c8714dd43dc2ac4dc3cca635541388d80fb93c12b4cb44d`.
- `dm-swapz.ko` SHA-256:
  `75f0048d5b86afc45d821776630b2e4cd8bd6354918035e3ce769b001c324007`.
- `device-roundtrip` SHA-256:
  `871d809976361bcd2d30b91bd4f661da8c712c16e4f5fa584696140261b57f26`.
- The private root-owned run record binds the selected removable card, exact
  partition and physical parent. Unique device identifiers, recovery paths,
  run ID, raw telemetry, and original-header digest remain private.

## Development prerequisite and physical oracle

The helper generated fresh nonce-bound `make fast_test RESUME=1` evidence.
Build and native/replay checks passed, reusing a matching checkpoint and
refreshing the product build. Loaded preflight reported only
`unclaimed_null_blk` (`expected_proof=creation_authority`,
`observed_proof=token_name_only`). Those objects were left untouched. The
helper permits this exact loaded-preflight block for the narrow development
smoke; it does not qualify loaded tests.

The helper then completed one `byte-exact-opened-dm` oracle phase:

- The existing production-C oracle wrote 128 deterministic 4 KiB pages,
  flushed, read and compared all pages, overwrote 64 pages, flushed, and read
  and compared all 128 pages again.
- Total logical writes were 192 pages / 786,432 bytes.
- The two complete readback passes performed 256 full-page byte comparisons /
  1,048,576 verified bytes, with zero mismatches.
- Device Mapper counters attributed 1,052,672 lower READ bytes / 257 requests
  and 749,568 lower WRITE bytes / 183 requests to the target. The target also
  recorded 386 successful flushes, zero failed flushes, and zero error/failed
  counters.
- The parent block-stat delta during the oracle was 1,060,864 READ bytes /
  259 requests and 749,568 WRITE bytes / 183 requests. These parent counters
  can include host activity; they are not NAND-wear measurements.

## Recovery and limits

The original first-block bytes matched after recovery. The durable recovery
record reached `COMPLETE`; normal mapper removal and module cleanup succeeded.
The selected target was inactive, absent from `/proc/swaps`, and had no mapper
or `dm_swapz` module remaining. No `swapon` or `swapoff` was performed by this
development-only run.

At the post-run check, swap inventory was empty and `MemAvailable` was about
2.14 GiB. No test process remained active. The unrelated swap file and other
storage were not modified.

This proves one bounded direct-I/O round trip through the tested swapz mapper
on the selected removable card at the source SHA above. It does not prove
Linux swap-out or swap-in, `pswpout`/`pswpin`, cgroup swap accounting, the
frozen two-cycle anonymous-swap acceptance, full-card capacity, full-capacity
RAM, sustained GC/churn, performance acceptance, or production readiness.

## Exact-source CI and next gates

For this source, production-C x86_64/ARM64 and systemd/package qualification
passed. The Native rootless GitHub job failed in
`swapzctl-active-swap-provenance-test.py`, test
`test_bind_overmount_can_diverge_rendered_name_from_lookup`.
The first failure was fixture setup: `unshare` could not write
`/proc/self/uid_map` (`Operation not permitted`), and the fixture's namespace
setup skip matcher did not recognize that exact diagnostic. The test owner
should correct the environment-failure recognition without weakening the
overmount assertion.

The owner-host `make fast_test RESUME=1` was run through the physical helper;
its loaded preflight remains blocked on unclaimed `null_blk` ownership. The
official `make test` has not passed on this source. Do not activate real Linux
swap until exact-source official qualification and the current real-swap
admission checks pass. The next gates are the rootless fixture correction,
demonstrable ownership of a safe loaded-test device without touching the
unclaimed objects, then official exact-source qualification. Only afterward
should the existing two-cycle anonymous-swap oracle be attempted.
