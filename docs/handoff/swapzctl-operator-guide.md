# swapzctl Operator Guide (read-only preview)

**Scope:** Current main-branch source. This guide does not establish that the executable is installed on Lubuntu or that the currently running mapper has been qualified. Direct current-host verification is required.

## Ownership and safety boundary

Linux owns paging, reclaim, page selection, swapon/swapoff and swap priorities. The swapz Device Mapper target compresses ordinary Linux swap pages onto an **already formatted SWAPSPACE2** partition. The backing partition's first 4096 bytes, UUID and partition table are immutable. Compression descriptors, generations, CRCs, allocation and GC authority live only in bounded RAM: unloading the module cannot restore undisposed swap data.

A valid mapper name, existing DM table, healthy INFO counters or active Linux swap entry **does not authenticate lifecycle ownership**. The protected primary manager and the original development-trial helper must independently authenticate same-boot owner state and exact mapper/partition identity before executing mutating actions. There is no automatic repair, arbitrary mapper adoption or force removal.

## Shipped read-only commands

| Command | Supported view | Important limit |
| --- | --- | --- |
| **swapzctl help** and **swapzctl help inspect** | General or command-specific syntax | No device operation |
| **swapzctl version** | Experimental executable version | Not a qualification statement |
| **swapzctl list** | Target name, index, DM device, logical capacity, kernel health | Ownership is unverified |
| **swapzctl status** | Cumulative foreground compression ratio and page classes, GC separately | Not current occupancy, rates or wear |
| **swapzctl inspect NAME** | Exact mapping name, geometry and lifetime counters | Backing and journal not verified |
| **swapzctl stats NAME** | One cumulative counter snapshot | Watch/rates not implemented |
| **swapzctl health NAME** | Validated kernel failed/error state | No independent I/O liveness proof |
| **swapzctl diagnose NAME** | Read-only diagnosis and safe next step | No automated stop/recovery |

The read-only commands accept **--json**. Name-selecting commands require an exact DM mapping name, not a raw block-device path or prefix. Command-specific help is side-effect-free. Proposed **--watch**, **--bytes** and **--no-headers** flags are **not supported yet**; do not use them in automation.

Successful validated DM observations are read-only; some DM ioctl reads require CAP_SYS_ADMIN. An error suppresses the validated numeric report rather than escalating privileges or issuing a mutating ioctl. The existing snapshot logic bounds allocations, verifies Device Mapper wire records, compares two complete INFO observations and validates a final device list. This detects observed drift, but no combination of those ioctls is atomic across the whole host.

## Machine-readable output

The initial JSON response has a **schema_version** of **1**, a **command** string and a **devices** array. Per-device fields include display-sanitized **name**, zero-based **target_index**, **dm_major**, **dm_minor**, **sector_start**, **sector_length**, and exact integer **logical_capacity_bytes**. The **kernel_health** field is **ok** only after a complete healthy target snapshot; **ownership** remains **unverified**.

The **lifetime** object reports cumulative logical/lower write bytes, GC write bytes, compressed/RAW/zero page counts, and whether the compressed extent bytes are exact. GC must not be mixed silently with the foreground ratio. The **linux_swap** object contains a separately observed **state** (active, not_observed or unknown) and **size_bytes**, **used_bytes**, **priority**, with null for unavailable values. These values are advisory, not an atomic snapshot with the DM information. Name is currently sanitized for safe display and is not an identity-preserving representation for unusual mapper names.

A current namespace lookup of a path found in the kernel swap table may fail after renaming or a mount over the path. Therefore **not_observed does not mean inactive or drained**. Linux swap capacity and usage are distinct from swapz lifetime compression. System-wide PSI and pagefault counters must not be mislabeled as device-specific rates.

## Safe inspection

Typical read-only checks:

    swapzctl version
    swapzctl help inspect
    swapzctl list
    swapzctl status
    swapzctl list --json
    swapon --show
    cat /proc/swaps
    dmsetup info

For a verified name, also use swapzctl inspect NAME, swapzctl health NAME or swapzctl diagnose NAME. Do not automatically attach stop/recover behavior to a wildcard like swapz-demo-physical-*. Never run mkswap on the raw swap partition, force dmsetup remove, blind swapoff or module unload during an uncertain live trial.

## Lifecycle and systemd

The existing **swapzctl primary plan**, **primary qualification-import REPORT**, **primary prepare**, **primary start**, **primary stop**, and **primary recover** delegate to the qualification- and ownership-gated swapz-primary manager. Only a newly created, inactive virtual mapper may be formatted. A stop requires Linux swapoff to drain live pages before exact-owned mapper removal; ENOMEM, an unidentified holder, mismatched backing/header or uncertain state retains recovery responsibility and prohibits removal.

The retained Lubuntu development mapper needs the original private helper's authenticated journal and verified cleanup path. Until this has been audited and qualified, swapzctl can report its runtime state but **cannot safely manage its lifecycle**. A development mapper matching a prefix is never automatically adopted.

The systemd primary mapper service must remain the sole stop/swapoff owner. Its .swap unit is a passive representation, not an independent activator. Cold-boot service arming and source/host/target physical qualification are separate gates and cannot be inferred from CLI success.

## Qualification confidence

- **Rootless/native:** exact-source C11 warning-clean build, adversarial DM/procfs parsers, JSON and no-mutation tests. Not physical proof.
- **Owned RAM-backed loaded:** byte-exact null_blk behavior and teardown. Does not qualify physical media.
- **Physical development:** owner-authorized exact partition identity, immutable SWAPSPACE2 header, swapoff headroom, live mapping ownership, readback and verified same-boot recovery.
- **Production/cold-boot:** separate, current-source, host-bound qualifications and owner arming. CI success is not production acceptance.

The public Make test tiers remain **make fast_test** (development only), **make test** (algorithm/RAM, physical-INCOMPLETE until admitted) and **make test_full** (rootless integration and RAM qualification only). Keep errors categorized as BLOCKED (unproven authority), FAILED (target fault) or UNAVAILABLE (insufficient observation). A healthy kernel INFO flag does not prove the absence of an I/O stall.
