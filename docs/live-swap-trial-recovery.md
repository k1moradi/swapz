# Experimental live-swap trial and recovery

**Status: implementation prepared for review; live mutations remain disabled.**
This procedure is separate from the completed physical-backed byte-correctness
smoke. It does not authorize a live trial or production use. The CLI accepts a
read-only `plan`; `run` and `recover` fail closed while
`LIVE_SWAP_EXECUTION_ENABLED` is false. Enabling them requires an independent
review of the exact commit and a separate owner authorization record.

## Trial boundary

The proposed experiment uses only `/dev/sda4` (8:4, PARTUUID
`7fb9401d-04`) and limits the swapz mapper to 256 MiB for at most 30 minutes.
It does not reuse the physical-smoke mapper or helper. It is not a performance,
endurance, stress, hibernation or production qualification.

The latest exact-source owner qualification is source
`6ff945e8c5e6671f9ffd6d1920343190ae1e5e28`, published by report-only commit
`d6c1edca3ea21836e01ad0a8c087bfda4aeaf470`. Its five stages passed. The
qualified formatter, module and oracle SHA-256 values are respectively
`7f38c6f4226142ceb0c655009f0917d7370ccd0aac7a5db110148b1a861e00e0`,
`e9001e487e3a86f2404c716f69bb01aa4cc4676f4a5f869201468d1a91850d67`, and
`f47c6f9c9ca97d4d580e0a2d88efcb41cca8d34f4a35e0456a4a4d9a6e85ffe8`.
The qualification used RAM-backed `null_blk`; it did not activate swapz as
Linux swap and is not live-swap performance evidence. Its maximum-capacity
probe checked byte-exact access to only the first and final 4 KiB pages of the
13,742,637,056-byte mapper.

Before a future run, the read-only plan must positively bind the exact source,
canonical `main` HEAD, current CI results, qualified production artifact
hashes, helper hash, target identity and original header, persistent recovery
storage, a fresh one-use owner authorization record, and a separately active
fallback. Do not invent or claim an external review. The plan must see exactly
the intended original swap plus the bound fallback, with the original
partition active at 0 KiB used and priority -1.

The fallback must be a root-owned, mode-0600, allocated regular swapfile on a
persistent filesystem with at least 512 MiB of free swap capacity. It must
already be active at an explicit priority from 0 through 32766. This permits
the default-priority `/dev/sda4` entry to return at -1 after the coordinator
reactivates it. The coordinator does not create or activate the fallback. It
leaves the fallback active after restoring ordinary swap, so the host's swap
inventory remains augmented until an operator verifies that the fallback has
no used pages and removes it.

## F2FS fallback finding

Read-only host observations on 2026-11-02 found `/` on `/dev/sda3` (8:3),
F2FS, running kernel `7.0.0-42-generic`, with `CONFIG_SWAP=y`,
`CONFIG_F2FS_FS=m`, and the matching F2FS module installed. The root mount is
in adaptive mode and has F2FS compression enabled by default for all file
extensions. `/dev/sda3` and `/dev/sda4` both descend from disk 8:0, the same
USB device.

Upstream F2FS implements swapfile activation. It rejects holes and some mount
modes, converts inline data, disables file compression, maps extents, may
migrate blocks for section alignment, and pins the file. Exact behavior of the
installed Ubuntu kernel build and a candidate file has **not** been tested.
Therefore an allocated F2FS swapfile appears feasible in principle but is not
yet a verified fallback. The current production objective also prohibits
changing the root filesystem layout to obtain fallback space, so `/dev/sda3`
is not an eligible fallback under this objective. Even if that boundary were
changed later, a swapfile there would share the target's USB device and could
not protect against loss of that entire device. It also cannot recover pages
whose swapz mapping authority or backing data has been lost.

References: [upstream F2FS swap activation code](https://code.googlesource.com/linux/torvalds/linux/+/7acf90feab8b009fde7def08ff2c622d0f10e99f/fs/f2fs/data.c),
[F2FS documentation](https://docs.kernel.org/filesystems/f2fs.html), and the
[swapon manual](https://man7.org/linux/man-pages/man8/swapon.8.html).

## Durable state and normal shutdown

All state belongs under
`/var/lib/swapz/physical-recovery/swapz-live-<run_id>/` on the validated
persistent recovery filesystem. The coordinator writes and fsyncs the original
4096-byte header backup, state, bounded result record and exact executable
snapshots before swapoff. It permanently consumes the run ID and holds the
partition lock plus active-recovery marker until restoration is verified.
Evidence contains no page contents.

Normal shutdown checks memory pressure and fallback capacity before calling
swapoff on the exact mapper. It never retries a failed mapper swapoff. If
swapoff fails or pages remain active, it preserves the mapper, module, SWZ
header, fallback and recovery marker for supervised review. It does not force
remove a mapping, unload a module with users, overwrite an ambiguous header,
or remove the fallback.

On successful cleanup, the coordinator removes only its exact mapper without
force, unloads only a same-process-owned module with zero users, verifies no
backing holders remain, restores and rereads the exact original header, and
reactivates only `/dev/sda4`. Completion requires the original major:minor,
size `16777212 KiB`, priority `-1`, absent helper mapper/module, durable
`COMPLETE` state, permanent consumed-run record and released active marker.
Post-restoration swap usage is observation only. The planned `swapon` does not
pass a discard option, and the mutation allowlist rejects explicit discard
requests. `mkswap` is permitted only on the verified mapper and never uses
`--force`.

## Crash and cold-boot recovery

The mapping authority is volatile. If the system crashes or reboots while swapz
is active, previously swapped pages cannot be reconstructed from the saved
header backup. The fallback is only additional capacity while the system is
running; it is neither whole-device redundancy nor a way to restore lost pages.
Do not claim data recovery after loss of that volatile mapping state.

After an unexpected stop, preserve the recovery directory and do not reboot
intentionally, force-remove a mapper, reactivate `/dev/sda4`, or write block
zero merely because a backup exists. First read the saved state, results and
backup; independently identify the live partition, mapper, UUID, exact table,
lower device, open references, module and active swap rows. If the mapper is
still active or any identity/header is unexpected, leave it unchanged and
escalate for review. A live mapper may contain the only readable copy of
swapped pages.

After a cold boot, the former mapper and module may be absent, but the original
swap partition may still contain a zeroed, SWZ-formatted or torn header. Normal
boot does not restore the former swap contents. Preserve the saved evidence;
use only a reviewed, identity-checked recovery operation that accepts the
current header as an explicitly recognized state, restores the exact saved
4096-byte header, rereads it, then verifies ordinary swap size and priority.
If the header is torn, the backup is missing, the partition identity changed,
or recovery state is uncertain, stop for manual review. Never fabricate a
`COMPLETE` state. The `recover` CLI remains disabled and is not a qualified
cold-boot recovery procedure. A disposable VM may exercise this software
recovery path using only substitute disk images that cannot alias host block
devices. That does not restore actual host swap pages or qualify recovery from
physical-device failure. Keep physical-host cold-boot recovery explicitly
unverified unless a safe, positively identified method exercises it. Do not
claim a mock test proves recovery after power loss.

A rootless recovery regression also verifies that a saved
`RECOVERY_REQUIRED` state is not hidden when the standalone cleanup records
`TRIAL_STOPPING`: the recognized original stage remains authoritative for
checking the existing SWZ header. Missing or cyclic stage provenance still
fails closed. This verifies modeled stage handling only, not cold-boot recovery.

## Validation completed for Phase A

The supervisor's mock-only rootless tests cover successful completion,
interrupted activation, original-swapoff failure without retry, active mapper
pages under low memory, mapper-swapoff failure, substituted target, ambiguous
header rejection, exact swap inventory and positive-I/O evidence. They do not
exercise the kernel, an actual fallback swap area, a true cold boot, or a
physical live trial. Those remain qualification gaps. The command interface
remains disabled until the fallback, lifecycle and native-host safety gates
are satisfied.
