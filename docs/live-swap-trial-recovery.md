# Live swap trial lifecycle — current contract

> **Superseded design warning (2026-11-09):** older revisions of this file
> described a persistent swap-header backup, a separate recovery filesystem and
> restoration of the raw partition. That design is rejected and must not be
> used for new swapz work. Git history retains those old procedures only as
> historical evidence.

The current normative design is defined by
[AGENTS.md](../AGENTS.md), [AGENT_CONTEXT.md](AGENT_CONTEXT.md),
[ROADMAP.md](ROADMAP.md), [coding_standards.md](coding_standards.md), and
[testing_standards.md](testing_standards.md). This file summarizes the live
trial lifecycle so an old recovery-oriented procedure cannot be mistaken for
current instructions.

## Backing partition contract

A real swapz backing device must already be a valid ordinary Linux
`SWAPSPACE2` partition.

The first 4096-byte Linux swap page is immutable. swapz must not:

- repartition the user's device;
- run `mkswap` on the raw backing partition;
- replace or restore the raw swap header;
- change its swap UUID or partition table;
- publish `SWAPZ001` or another swapz-specific physical format.

After exact device admission and a successful `swapoff`, swapz may use only
the admitted data area following the protected first page. The newly created
Device Mapper device is the only object that may receive `mkswap`.

A byte-exact digest/readback of the protected first page is evidence that the
contract remained intact. It is not a backup image and must never become a
write source.

## Metadata and recovery model

All swapz-specific mapping authority is volatile RAM state: record and extent
descriptors, generations, sequence values, payload offsets and lengths, CRCs,
segment/allocation state, mapping indexes and GC authority. Production lower
extents contain payload bytes plus deterministic zero padding only.

There is therefore no swapz partition metadata to recover after a reboot and
no raw-header restoration step. The ordinary `SWAPSPACE2` header remains
valid throughout the trial.

Current mutable lifecycle ownership is same-boot, root-controlled state under
`/run/swapz`. A separate persistent disk, filesystem or physical parent is
not an admission requirement. Persistent qualification/build evidence may
exist under `/var/lib/swapz/physical-recovery` for compatibility, and an
explicitly selected pre-migration journal may still be inspected for historical
reconciliation, but that location is not current runtime ownership, swap
metadata, a header backup or a recovery image.

## Normal live transition

For an admitted ordinary swap partition, the live transition is:

1. Revalidate the exact PARTUUID/device geometry, current `SWAPSPACE2` first
   page, holders/mount topology, source/artifact identity and current swap
   inventory.
2. If the selected partition has live swapped pages, verify bounded
   `MemAvailable` headroom for those pages plus the configured safety margin.
   Live `Used` pages are not themselves an admission failure.
3. Run `swapoff` on **only the selected partition** and verify it is inactive.
   Unrelated swapfiles or swap partitions remain untouched.
4. Create the swapz Device Mapper device using only the data area after the
   protected first page. Keep all authoritative swapz metadata in RAM.
5. Run `mkswap` only on the mapper when Linux-swap activation is part of the
   trial, then `swapon` the mapper.
6. Run the bounded correctness, concurrency, GC, error-path, capacity and
   performance checks required by the current testing standards.
7. After a successful real-swap trial, ask the owner whether to keep the exact
   verified swapz mapper active or return to ordinary Linux swap.
8. If the owner chooses ordinary swap, `swapoff` the mapper, remove only the
   owned mapper/module, verify the raw first page is unchanged, and reactivate
   the original partition with its recorded activation/priority policy.

No reboot is required for either direction.

## Failure and interruption behavior

Failure cleanup is lifecycle reconciliation, not partition restoration. The
helper may retain a same-boot ownership marker while it verifies or completes
owned mapper/module removal and the selected partition's activation state. It
must fail closed if ownership or live device identity cannot be proven.

The helper must never use an old saved header to "repair" block zero. If the
protected `SWAPSPACE2` page differs from the admitted byte-exact image, treat
that as a contract violation and stop raw writes.

Because mapping authority is RAM-only, an unexpected reboot while swapz owns
live swapped pages can lose those pages. The raw partition still has its
ordinary Linux swap header, but swapz cannot reconstruct lost mappings from
disk. For the same reason, swapz is not a hibernation/resume persistence
format unless a future explicitly approved design changes that contract.

## Historical records

Older handoff files and old commits may mention header backups, "recovery
parents", `SWAPZ001`, persistent trial journals or raw-header restoration.
Those records describe superseded experiments. They do not authorize those
mechanisms for current implementation, testing or production qualification.
