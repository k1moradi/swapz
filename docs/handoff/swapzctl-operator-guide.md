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
| **swapzctl list** | Reversible encoded name, target index, DM device, whole-mapper bytes and advisory swap usage/priority | Ownership is unverified |
| **swapzctl status** | Cumulative foreground compression ratio and page classes, GC separately | Not current occupancy, rates or wear |
| **swapzctl inspect NAME** | Exact mapping name, geometry and lifetime counters | Backing and journal not verified |
| **swapzctl stats NAME** | One cumulative counter snapshot | Watch/rates not implemented |
| **swapzctl health NAME** | Validated kernel failed/error state | No independent I/O liveness proof |
| **swapzctl diagnose NAME** | Read-only diagnosis and safe next step | No automated stop/recovery |

The read-only commands accept **--json**. Name-selecting commands require an exact DM mapping name, not a raw block-device path or prefix. Command-specific help is side-effect-free. Human-readable views accept **--bytes** for exact decimal byte totals, and `list` additionally accepts **--no-headers** for scripting. These two human-view flags cannot be combined with **--json**. Continuous **--watch** sampling is not yet supported.

Successful validated DM observations are read-only; some DM ioctl reads require CAP_SYS_ADMIN. An error suppresses the validated numeric report rather than escalating privileges or issuing a mutating ioctl. The existing snapshot logic bounds allocations, verifies Device Mapper wire records, compares two complete INFO observations and validates a final device list. This detects observed drift, but no combination of those ioctls is atomic across the whole host.


## Build, install and permissions

Use the source-matched build-local executable after `make`:
`./build/userspace/swapzctl help`. The root Make API builds the C11
userspace utility alongside the kernel module and test tools; Kbuild headers,
a C compiler and module-signing prerequisites are described in
[compile.md](../compile.md). Building does not qualify a live device.
`make install` only admits previously qualified artifacts; it does **not**
rebuild, load the module, create a mapper, call swapon, enable systemd or
authorize a physical trial. The installed primary units remain disabled.
Do not install or arm services just to obtain a status report.

Observational Device Mapper ioctls may require root or `CAP_SYS_ADMIN`.
The CLI never elevates privileges: an EPERM/EACCES observation is
`UNAVAILABLE`, not proof of an absent mapper. Operators with approved
access can run read-only observations in their privileged shell, but must
not grant a monitoring script lifecycle capabilities.

### Return codes and empty/error distinctions

These are the **current observation dispatcher** codes, not codes for
`swapzctl primary` (which delegates to the separate manager):

| Exit code | Meaning | Safe interpretation |
| --- | --- | --- |
| 0 | Help/version or successful validated observation, including allowed empty inventory | No lifecycle/health claim follows from success alone |
| 1 | Invalid/missing exact target, absent module for named commands, invalid/failed snapshot, permission/read error | Reject the view; retain first error and investigate read-only |
| 2 | Unsupported option, malformed invocation or unsupported help topic | Correct syntax; no mapper action attempted |

When `dm_swapz` is not loaded, plain `status` returns zero and prints
`dm-swapz: not loaded (experimental)`; plain `list` returns zero and
prints `swapz targets: none`. Both `status --json` and `list --json`
return `{"schema_version":1,"command":"...","devices":[]}` (with
the appropriate command value). An **empty** inventory is not a failed
observation; a failed collection must not be converted into an empty array.
`inspect NAME`, `stats NAME`, `health NAME` or
`diagnose NAME` return nonzero if the module or exact validated name is
missing. The name selector cannot contain `/` or be empty, and matching
is exact, never prefix-based.

Supported syntax is `status [--json|--bytes]`,
`list [--json|--bytes] [--no-headers]`,
`inspect NAME [--json|--bytes]`, `stats NAME [--json|--bytes]`,
`health NAME [--json|--bytes]`, `diagnose NAME [--json|--bytes]`,
`help [COMMAND]`, `version` and the guarded
`primary plan|qualification-import REPORT|prepare|start|stop|recover`
family. For `list`, `--no-headers` can be used alone or with
`--bytes`, **never with `--json`**. `--watch` and automatic
development-mapper stop/recovery are **PROPOSED, NOT SHIPPED**.


## Machine-readable output

The initial JSON response has a **schema_version** of **1**, a **command** string and a **devices** array. Per-device fields include **name** encoded reversibly as percent-escaped bytes (**name_encoding** = **percent_bytes**), zero-based **target_index**, **dm_major**, **dm_minor**, **dm_event_number**, **sector_start**, **sector_length**, target **logical_capacity_bytes**, and nullable whole-mapper **mapper_logical_capacity_bytes**. **dm_uuid** is percent-byte encoded when present, otherwise null; **backing_identity** remains null. **kernel_health** is **ok** only after a complete healthy target snapshot, **io_liveness** is **unknown**, and **ownership** remains **unverified**.

The **lifetime** object reports cumulative logical/lower write bytes, GC write bytes, compressed/RAW/zero page counts, and whether the compressed extent bytes are exact. GC must not be mixed silently with the foreground ratio. The **linux_swap** object contains a separately observed **state** (active, not_observed or unknown) and **size_bytes**, **used_bytes**, **priority**, with null for unavailable values. These values are advisory, not an atomic snapshot with the DM information. The percent-byte encoding preserves unusual mapper-name bytes for read-only correlation; it does **not** establish ownership or permission to stop a device.

A current namespace lookup of a path found in the kernel swap table may fail after renaming or a mount over the path. Therefore **not_observed does not mean inactive or drained**. Linux swap capacity and usage are distinct from swapz lifetime compression. System-wide PSI and pagefault counters must not be mislabeled as device-specific rates.


### Script consumption: encoded identity is not lifecycle authority

`--json` is currently a **schema-version-one preview**, not an authenticated
lifecycle-identity interface. Successful output contains
`schema_version`, `command` and `devices` (possibly empty).
`target_index` is **zero-based** in JSON and one-based in human views;
geometry is in 512-byte sectors; capacity and lifetime I/O values are
exact integer **bytes**. Committed page class fields count 4096-byte pages.
The `linux_swap` fields `size_bytes`, `used_bytes` and `priority`
can be null; `linux_swap.state` is advisory and separately sampled.
`kernel_health:"ok"` proves only the collected kernel target flags;
`ownership:"unverified"` must not be promoted to verified by a script.
The JSON `name` and available `dm_uuid` use **reversible percent-byte
encoding**; the `name_encoding` field specifies `percent_bytes`. Decode
to the exact original mapper-name bytes when correlating trusted read-only
observations; never treat the encoded text as a literal shell selector, or
its reversibility as proof of mapper/journal ownership. The whole-mapper
capacity may be null; `io_liveness` remains `unknown` and
`backing_identity` remains null.

For a diagnostic script, check the **process exit code before parsing**,
parse only valid JSON, validate `schema_version == 1` and treat unknown
fields/nulls as unknown evidence. Example (no automatic control):

```sh
./build/userspace/swapzctl list --json > /tmp/swapz-list-preview.json || exit 1
python3 -m json.tool /tmp/swapz-list-preview.json >/dev/null || exit 1
```

This verifies JSON syntax only, not owner identity, liveness or a safe drain.

## Read-only troubleshooting by evidence source

First inspect without changing storage or service state:

```sh
./build/userspace/swapzctl status
./build/userspace/swapzctl list --json
swapon --show
cat /proc/swaps
lsblk -o NAME,MAJ:MIN,TYPE,SIZE,FSTYPE,UUID,PARTUUID
dmsetup info -c
```

`blkid` can be used for read-only inspection **only after** the operator
has separately established the exact intended device identity; its output
does not authenticate swapz ownership. Given a verified exact **mapper
name**, `swapzctl inspect NAME`, `stats NAME`, `health NAME`
and `diagnose NAME` are additional read-only views.

| Observation | Reports | Does not prove |
| --- | --- | --- |
| `status` ratio, page classes | Cumulative foreground logical-versus-lower WRITE accounting | Current swap occupancy, NAND wear, throughput |
| `stats` and GC bytes | Lifetime lower WRITEs, GC accounted separately | Per-second rates, I/O forward progress |
| `/proc/swaps`, `swapon --show` | Linux size/used/priority at one sampling time | Exact current mapper ownership or complete swapoff |
| `health` | Validated target failed/error flags | No stalled I/O, or independently proven liveness |
| PSI, vmstat, pswpin/pswpout | **Host-wide** memory/swap activity | Device-specific swapz I/O rate |

A kernel-retained active swap may refer to a path that has since been
renamed, overmounted, hidden or substituted. Re-resolving the pathname
from `/proc/swaps` may identify a **different** object or no object.
Thus `linux_swap.state=not_observed` or `unknown` can **never**
prove inactive/drained. The DM, Linux swap and systemd observations are
not atomic and no set of status snapshots substitutes for the original
same-boot ownership journal and verified `swapoff` completion.

For the retained development trial, preserve the original helper's
private journal and use only its authenticated same-boot cleanup workflow
after the independent ownership audit/qualification. Never adopt a mapper
merely because it matches `swapz-demo-physical-*`. Do not call
`swapzctl primary stop` on that development mapper. Do not run blind
swapoff, force dmsetup remove, raw-partition mkswap, module unload/reload,
automatic repair or reboot.


## Safe inspection

Typical read-only checks:

    swapzctl version
    swapzctl help inspect
    swapzctl list
    swapzctl status
    swapzctl list --json
    swapzctl list --bytes --no-headers
    swapon --show
    cat /proc/swaps
    dmsetup info

For a verified name, also use swapzctl inspect NAME, swapzctl health NAME or swapzctl diagnose NAME. Do not automatically attach stop/recover behavior to a wildcard like swapz-demo-physical-*. Never run mkswap on the raw swap partition, force dmsetup remove, blind swapoff or module unload during an uncertain live trial.

## Lifecycle and systemd

The existing **swapzctl primary plan**, **primary qualification-import REPORT**, **primary prepare**, **primary start**, **primary stop**, and **primary recover** delegate to the qualification- and ownership-gated swapz-primary manager. Only a newly created, inactive virtual mapper may be formatted. A stop requires Linux swapoff to drain live pages before exact-owned mapper removal; ENOMEM, an unidentified holder, mismatched backing/header or uncertain state retains recovery responsibility and prohibits removal.

The retained Lubuntu development mapper needs the original private helper's authenticated journal and verified cleanup path. Until this has been audited and qualified, swapzctl can report its runtime state but **cannot safely manage its lifecycle**. A development mapper matching a prefix is never automatically adopted.

The systemd primary mapper service must remain the sole stop/swapoff owner. Its .swap unit is a passive representation, not an independent activator. Cold-boot service arming and source/host/target physical qualification are separate gates and cannot be inferred from CLI success.


## Read-only systemd and deployment-state checks

The `swapz-primary-mapper.service` owns **both** primary `swapon` and
`swapoff` through the guarded primary manager, and refuses manual start/stop.
The `swapz-primary.swap` unit is a **passive non-activator** with refused
manual jobs and a false activation condition: do not enable, start or order
it as a second swap owner. The runtime-health observer is independently
read-only. An `active` monitor means process liveness only; inspect the
most recent `SWAPZ_RUNTIME_HEALTH=` journal event:
`DEGRADED` means incomplete telemetry and `FAIL` means a confirmed
observer problem, **neither** of which triggers safe automatic cleanup.
The boot verifier only records evidence for an owner-admitted, exact-source
boot; installed units and a green CI run never imply boot readiness.

The following commands read state without enabling or changing a unit:

```sh
systemctl show swapz-primary-mapper.service -p LoadState -p UnitFileState -p ActiveState -p SubState
systemctl show swapz-primary.swap -p LoadState -p UnitFileState -p ActiveState -p SubState
systemctl show swapz-primary-runtime-health.service -p LoadState -p UnitFileState -p ActiveState -p SubState
systemctl show swapz-primary-boot-verify.service -p LoadState -p UnitFileState -p ActiveState -p SubState
journalctl -u swapz-primary-runtime-health.service -n 30 --no-pager
journalctl -u swapz-primary-mapper.service -n 30 --no-pager
```

Review/limit journal disclosure before sharing: don't publish host identities,
private run IDs or journal contents. Unit inactivity, missing logs or a
healthy-looking service cannot certify drained swap. Hibernation and
suspend-then-hibernate are unsupported while swapz authority is volatile;
see [systemd runtime-health notes](systemd-runtime-health.md).

## Release-stage acceptance matrix

| Gate | What can pass | What is still **not** proven |
| --- | --- | --- |
| Source/native-rootless | Exact-main C11 warnings, hostile DM/procfs/JSON and no-mutation regressions | Loaded device, real swap or physical safety |
| Owned RAM/`null_blk` | Byte-exact loaded I/O, GC, teardown and fault handling actually exercised | Physical partition, real anonymous Linux swap |
| Physical development | Host-bound partition admission, unchanged SWAPSPACE2 header and actual oracle scope | Full capacity, production qualification, cold boot |
| Production primary | Fresh same-source/target qualification, exact owner journal and real swap lifecycle/physical protocol | Cold-boot acceptance and crash recovery |
| Owner-observed cold boot | Durable verifier evidence from owner reboot on that exact source/host/target | Hibernation or reconstructing lost volatile mappings |

The first host's dedicated SD-card authorization is **not** transferable to
the separately authorized Lubuntu `/dev/sda4` host. Its shared-root-parent
exception cannot reach the parent or sibling partitions, and neither host
scope record is itself a physical qualification. All swapz authoritative
mapping state lives in RAM; reboot or module reload cannot reconstruct it.

Use `BLOCKED` for missing safe admission/owner proof,
`UNAVAILABLE` for absent or unreliable observation,
`DEGRADED` for incomplete runtime telemetry, and `FAIL`/`FAILED`
for confirmed failure. Preserve the original errno (only when emitted),
source SHA, safe state and first failed phase. Do not treat a failure
category or a zero exit as authorization for automatic recovery.
`make fast_test` is development-only; `make test` can remain
INCOMPLETE after RAM success until physical admission; `make test_full`
adds rootless integration but not automatic physical/boot PASS.


## Qualification confidence

- **Rootless/native:** exact-source C11 warning-clean build, adversarial DM/procfs parsers, JSON and no-mutation tests. Not physical proof.
- **Owned RAM-backed loaded:** byte-exact null_blk behavior and teardown. Does not qualify physical media.
- **Physical development:** owner-authorized exact partition identity, immutable SWAPSPACE2 header, swapoff headroom, live mapping ownership, readback and verified same-boot recovery.
- **Production/cold-boot:** separate, current-source, host-bound qualifications and owner arming. CI success is not production acceptance.

The public Make test tiers remain **make fast_test** (development only), **make test** (algorithm/RAM, physical-INCOMPLETE until admitted) and **make test_full** (rootless integration and RAM qualification only). Keep errors categorized as BLOCKED (unproven authority), FAILED (target fault) or UNAVAILABLE (insufficient observation). A healthy kernel INFO flag does not prove the absence of an I/O stall.
