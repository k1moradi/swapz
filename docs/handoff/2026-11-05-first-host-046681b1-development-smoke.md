# First-host physical mapper smoke on `046681b1`

**Observed:** 2026-11-05. This is a source-bound development-only mapper
round-trip on the authorized SD partition. It is **not** Linux anonymous-swap
qualification, physical acceptance, or production readiness.

## Source, build, and admission

- Local `main`, `origin/main`, and canonical remote `main` were
  `046681b1c22086aa8a39a3fda590198414ddc133` at the physical helper's
  admission and post-run checks. The only difference between this commit and
  its parent was the prior production-status documentation snapshot.
- The helper's fresh `make fast_test SCENARIOS=fast-mixed REPEAT=1 RESUME=1`
  evidence was bound to that exact clean main SHA and a one-use nonce. The
  product build and native/replay checks passed; a matching native/replay
  checkpoint was reused and the product build was refreshed.
- Loaded preflight was **BLOCKED** at
  `check=unclaimed_null_blk`: expected creation authority, observed only a
  token-shaped name. The two ambiguous configfs devices were left untouched.
  The development-only helper admits this exact loaded-preflight block for
  this narrow test; it does not turn the block into a loaded qualification
  PASS.
- An initial invocation using `/dev/sda1` directly stopped before recovery
  state or header mutation because the helper requires a `/dev/disk/by-uuid`
  selector. The alias was checked to resolve to the same selected partition;
  the corrected invocation performed the single successful run below.
- Current test artifacts were verified against the built source:

  | Artifact | SHA-256 |
  | :--- | :--- |
  | `dm-swapz.ko` | `de22d72d34ef6c04c03e16e7490b41dda8435b458fdf0909434b5eb3e4e189c4` |
  | `swapzctl` formatter | `000dc45031b91c1ac874db5f904d3e93f65771bc1c956f34b5d74c6acb842acb` |
  | `device-roundtrip` | `871d809976361bcd2d30b91bd4f661da8c712c16e4f5fa584696140261b57f26` |
  | `physical-swap-probe.py` | `026fc956b11b873d5c07d273b6dc1e393b40e0a7d27d13bd90744a50b66b69b7` |

## Target and mapper oracle

At the final read-only host check, the selected path still identified the
expected removable USB SD partition (`8:1`, 124,787,884,032 bytes); it was
unmounted, had no holders, and was absent from the empty `/proc/swaps`
inventory. `MemAvailable` was 2,242,356 KiB. The parent/block identities,
unique identifiers, run ID, private logs, recovery directory, and original
header digest are retained only in the root-owned private recovery record.

One physical oracle phase ran: `byte-exact-opened-dm`. The production-C helper
wrote 128 deterministic 4 KiB pages, flushed, read and compared all pages,
overwrote 64 pages, flushed again, and read and compared all 128 pages again.
That is 192 logical page writes / 786,432 bytes and 256 full-page comparisons
/ 1,048,576 verified bytes, with zero mismatches. The helper exited zero and
reported its owned V3 128-page direct-I/O, flush, full-readback, overwrite
PASS.

The exact Device Mapper target counters for the oracle interval showed:

| Counter | Observed |
| :--- | ---: |
| Lower READ bytes / requests | 1,052,672 / 257 |
| Lower WRITE bytes / requests | 749,568 / 183 |
| Successful / failed flushes | 386 / 0 |

The target's terminal health counters were `failed=0` and `error=0`.

The parent block-stat interval independently showed READ 1,064,960 bytes / 260
requests and WRITE 749,568 bytes / 183 requests. Parent statistics can include
other host activity; the target counters provide the swapz attribution. These
are host-visible block I/O measurements, not NAND-wear measurements.

## Recovery and current production gates

The helper completed normal cleanup. Its durable state is `COMPLETE`; the
original 4 KiB header matches byte-for-byte; the mapper and module are absent;
the active partition marker is absent; the one-use run claim was consumed; and
the target remains inactive. No `swapon` or `swapoff` was performed by this
development-only run. No unrelated swap or storage was modified.

A separate read-only `swapzctl primary plan`, built from the same source, still
reports `BLOCKED` with `privileged_execution_enabled=false`. Module build
provenance, a valid exact-source qualification report, qualified artifact
hashes, and live artifact matching are not established. The displayed
27,080,192-page / 110,920,466,432-byte mapper geometry and 3,385,024-block GC
reserve are arithmetic only; maximum safe capacity and full-capacity memory
remain unmeasured.

Current-source qualification status is also incomplete:

- CI for the unchanged code tree at parent `900e9305` passed [production-C
  x86_64/ARM64](https://github.com/k1moradi/swapz/actions/runs/42106200862) and
  [systemd/package](https://github.com/k1moradi/swapz/actions/runs/42106200873).
  [Native rootless](https://github.com/k1moradi/swapz/actions/runs/42106201009)
  failed before its overmount assertion because user-namespace setup could not
  write `/proc/self/uid_map` (`Operation not permitted`); the fixture did not
  recognize that setup-denial diagnostic. No numeric errno was emitted.
- Official `make test` has **not** passed on this source. The latest tracked
  owner report is from older source `0603d81f` and cannot qualify this main.
- Two configfs `null_blk` instances and one unproven, unpopulated swapz cgroup
  remain untouched. Their ownership must not be inferred from names or lack of
  holders.

Next: the assigned fixture owner should correct the namespace-setup denial
classification while retaining the overmount assertion; the loaded-test owner
must establish a genuinely owned RAM-backed test resource without touching the
ambiguous devices. Then run official `make test` against one exact current
source. Only after the production manager's artifact and lifecycle gates pass
should the existing two-cycle Linux anonymous-swap oracle run. That oracle
must independently prove `pswpout`/`pswpin`, cgroup swap usage, mapper and
backing I/O, byte-exact verification, fresh per-cycle identities, zero OOM
and normal teardown under the frozen acceptance limits.
