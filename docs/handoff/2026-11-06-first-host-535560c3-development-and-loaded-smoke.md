# First-host evidence checkpoint — 2026-11-06

## Project-manager summary

At source `535560c38dde9b001c655da8a58bb9793fc00056`, the first host has a
source-bound, development-only `/dev/sda1` mapper-page PASS and a separate
standalone owned-RAM loaded-smoke PASS. These results move physical and loaded
data-path debugging forward, but they do not qualify ordinary Linux swap.

The next real-swap gate remains closed. Exact-SHA Native Project Goals CI has
three failing rootless subchecks; the official five-stage `make test` has not
been run on this source; the official loaded preflight still rejects the two
pre-existing ownership-ambiguous `null_blk` devices; and the read-only primary
plan has no qualified report or matching installed/live artifacts.

| Milestone | Result at this source |
| --- | --- |
| `/dev/sda1` development mapper oracle | **PASS — development-only** |
| Separate owned-RAM loaded smoke | **PASS — standalone development-only** |
| Required exact-SHA CI | **FAIL** — Native Project Goals workflow |
| Official five-stage `make test` | **NOT RUN** on this SHA |
| Managed Linux anonymous swap-out/in | **NOT RUN** |
| Production readiness | **BLOCKED** |

The two ambiguous pre-existing `null_blk` objects were left untouched. The
unrelated swapfile and other storage were not modified by these tests.

## Source and current host state

- Tested source: `535560c38dde9b001c655da8a58bb9793fc00056`.
- At the smoke runs and status capture, local `main`, `origin/main`, and the
  canonical remote `main` matched this SHA; the source tree was clean.
- Kernel: `7.0.0-42-generic`, x86_64.
- A fresh read-only open of `/dev/sda1` with `O_NOFOLLOW` verified a block
  descriptor at `8:1`, 124,787,884,032 bytes, PARTUUID `f13428f6-01`, start
  sector 2048, no holders, removable parent `8:0` identified as USB
  Multi-Card. The current manager plan also observed it unmounted.
- The independent persistent recovery filesystem is on `8:22`, whose physical
  parent is `8:16`; the SD-card parent is `8:0`. The manager verified that the
  recovery storage is persistent and on a different physical parent.
- Current active swap inventory: zero entries. Current `MemAvailable`:
  2,159,544 KiB; `MemTotal`: 3,863,624 KiB. Memory PSI averages were zero at
  observation.
- After both smokes, `dm_swapz` was unloaded, no swapz mapper was present, and
  the card remained inactive. No official test process was active.

## `/dev/sda1` mapper-page oracle

The existing private physical helper ran in its explicit development-only
mode from 2026-11-06 08:45:47 UTC through 08:47:13 UTC. Its private report is
root-owned and mode 0600; the report SHA-256 is
`a5664b27263081bf24d7cbfe394b3e2b8eb289a47df1aee32120d5e3eb38929b`.

- Oracle phase: `byte-exact-opened-dm`, **1 phase executed**, return code 0.
- It wrote 128 known pages and overwrote 64 pages: 192 logical writes,
  786,432 logical write bytes.
- It made 256 full-page comparisons, verified 1,048,576 bytes, and reported
  zero mismatches.
- Phase-attributed lower I/O: 1,011,712 read bytes / 247 requests and
  749,568 write bytes / 183 requests. The test recorded 386 successful flushes
  and zero failed flushes.
- The original 4 KiB card header was restored byte-exactly. Durable recovery
  finished `COMPLETE`; the card was inactive; the swap row, mapper, module,
  and active partition marker were absent; normal mapper removal and module
  cleanup succeeded.

Artifact SHA-256 values recorded by the helper:

- Helper: `200c50c624eb5fa4e265458a5e0b9c163823ebca43906cde4133aa76bb1a53be`
- `swapzctl` formatter: `48a9a50551b43582785ce752f10d004cb6eae2f3f1a2c4e99705cbfe093f3b89`
- `dm-swapz.ko`: `3624befd0413216dde2d9229824d1796b29845ee93d961c32bed30b7b0a758cc`
- `device-roundtrip`: `871d809976361bcd2d30b91bd4f661da8c712c16e4f5fa584696140261b57f26`

This result proves a bounded byte-exact mapper data path on the physical card.
It did not call `swapon`, did not cause Linux anonymous pages to be swapped,
and is not physical-media acceptance or production qualification.

## Standalone owned-RAM loaded smoke

A separate existing loaded-smoke helper created a fresh 64 MiB RAM-backed
`null_blk` object within its own process, ran the loaded tests, and removed
that test-owned object normally. The root-only session log is mode 0600,
29,812 bytes, SHA-256
`dd7a444fa0e3bb7df595c02004d65f82c807250dd83e47317e3facd42bf6fe71`.
The loaded module was built from source `535560c3…`; its SHA-256 matches the
module artifact above. It is currently unloaded.

The standalone run reported PASS for constructor-failure cleanup, the loaded
oracle profile, compound BIOs (384 verified pages), live GC (5 rounds, 4,096
pages, 18 victim/rotation events, 16 dead-segment reuses), GC pressure,
DISCARD/TRIM, suspend/drain, retained write/read/flush fault paths, codec
errors, packed placement, and completion handoff. This is useful loaded-kernel
debugging evidence, but it is **not** the official Stage 5 result and does not
prove actual Linux swap-in or physical-card behavior.

Two powered `null_blk` configfs device directories remain from before this
smoke and still lack provable creation ownership. They were not adopted,
powered off, removed, or modified. The fresh test-owned device was distinct
and removed by its creating test process. The official loaded preflight remains
blocked on the two existing objects.

## Current CI and official qualification

GitHub Actions ran against the exact source SHA:

- [Production C qualification](https://github.com/k1moradi/swapz/actions/runs/42189650814): **PASS**, including exact C on x86_64 and ARM64.
- [Private kernel debug and static contracts](https://github.com/k1moradi/swapz/actions/runs/42189650899): **PASS**.
- [Physical evidence adversarial audit](https://github.com/k1moradi/swapz/actions/runs/42189650926): **PASS**.
- [Systemd/package readiness](https://github.com/k1moradi/swapz/actions/runs/42189650851): **PASS**.
- [Native kernel-C project goals](https://github.com/k1moradi/swapz/actions/runs/42189650874): **FAIL** in three independent rootless subchecks:
  - `resource-admission-test.py` exits nonzero in Native rootless (Agent 3 owns
    the fixture correction).
  - `test_authenticated_rootless_fixture_compile_stays_private` observes
    `Makefile native and metadata[compile]` where the assertion expects
    `Makefile native and metadata` (Agent 16 owns reporter attribution).
  - `test_nested_campaign_numeric_types_must_remain_exact` fails the
    `target_observation` diagnostic assertion (Agent 10 owns the evaluator
    fixture/assertion).

The latest checked-in `test_results.json` is not current-source evidence. It
reports **FAIL** for source `f763ede786a2dfd28f5780707ad50c01555d48ca`, with
Build PASS and Native/rootless FAIL; later official stages are absent. Its
SHA-256 is `3735088e429efc443f1af86da2abe7e4b62e7242d0b19bcbe7845645d6e86fbc`.
No official `make test` was run at `535560c3`.

## Read-only primary plan and real-swap gate

At 2026-11-06 10:01:06 UTC, the source-bound `swapzctl primary plan` returned
**BLOCKED** with privileged execution disabled. It independently revalidated
the target and recovery identities, found zero active swap entries, confirmed
the target unmounted, and confirmed the mapper and module absent. The immediate
missing proofs were:

- current module build provenance readable and matching the control build;
- a valid exact-source qualification report;
- qualified artifact hashes and matching live/installed artifact hashes.

Therefore no managed activation was attempted. Linux anonymous swap-out,
`pswpout`, swap-in/`pswpin`, cgroup swap charge, mapper and backing-device
traffic during Linux swapping, and real-swap byte-oracle phases are all
**NOT RUN**. The built controller is not installed in `PATH`; `modinfo` does
not find an installed `dm-swapz`; primary runtime and boot-verifier units are
not installed.

## Next actions, in order

1. Consume Agent 3, Agent 16, and Agent 10's fixes on `main`; require the new
   exact-SHA Native Project Goals workflow to pass. Do not duplicate their
   edits.
2. Resolve the protected-selector directory replacement and chroot-filtered
   mount-inventory investigations (Agents 6 and 7). Destructive admission
   remains blocked until these identity checks are proven safe.
3. Resolve official loaded-preflight ownership for a freshly created test
   `null_blk`, without touching the two existing ambiguous devices (Agent 5).
4. After relevant fixes land, run the fresh development loop with
   `make fast_test RESUME=1`; require current source, fresh artifact binding,
   and the correct loaded-preflight result. A fast-test result is still not
   official qualification.
5. Once required exact-SHA CI and owned-RAM admission are green, run one
   source-stable official `make test`; require all five stages, including
   W=1/W=2 and loaded qualification.
6. Build/install only the artifacts qualified by that report. Re-run the
   read-only primary plan and require **PASS** with exact live hashes before
   running the existing bounded managed two-cycle real-swap oracle on the
   revalidated card.
7. For real swap, require positive correlated `pswpout`/`pswpin`, test-cgroup
   swap charge, mapper and physical lower I/O, byte-exact readback, zero
   OOM/mismatches, and ordinary manager-owned `swapoff` and teardown.

No source change or physical mutation was made for this checkpoint. The
evidence is historical at the tested source SHA and must not be represented
as production readiness.
