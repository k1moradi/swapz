# V2.2 loaded-kernel smoke harness

`tests/runtime/virtual-smoke.sh` is a narrowly scoped loaded-kernel check for
an **explicitly authorized disposable Linux VM**. It is not a benchmark and its
rootless mocks do not qualify a loaded kernel. No live invocation was made as
part of this change.

## What the live smoke does

The harness first checks root, an exact disposable-VM authorization string,
`systemd-detect-virt --vm`, the checked-out source SHA and kernel-source blob,
the selected module SHA/name/vermagic and protected file path, the absence of
an already-loaded `dm-swapz`, a pre-registered `dm-delay` target, `/dev/shm`
being tmpfs, and a readable `/dev/kmsg` cursor. A failed preflight performs no
fixture, module, loop, or Device Mapper mutation.

Because the script itself runs as root, its full source checkout, `.git`
directory, harness files, and every parent path must also be root-owned and
not group/world writable. A user-owned home-directory checkout or linked
worktree is refused. Use a separately prepared, root-owned full checkout in
the disposable VM, and keep the selected module in a protected directory.

After preflight it creates a private 32 MiB sparse backing image in `/dev/shm`,
attaches that exact file to a loop device, loads only the selected `dm-swapz`
module, and creates UUID-tagged Device Mapper targets. The logical table is
exactly:

```text
0 8 swapz /dev/mapper/<owned-delay-target> staged 64
```

It writes one aligned 4 KiB page containing repeated `0xA5` bytes. The
`dm-delay` table uses a zero-millisecond read delay and a controlled 5-second
write delay. The worker may submit a partially filled stream buffer as soon as
it goes idle; the check therefore waits for status to show all of
`staged_early>0`, `inflight_blocks>0`, and `async_cb>0`. It then reads the same
logical page before that lower write finishes, compares all 4096 bytes, and
requires the actual `staged_hits=` counter to increase while the lower write
is still in flight.

Next, ordinary `dmsetup suspend` invokes swapz's presuspend drain, and ordinary
`dmsetup resume` reopens the target. The harness requires zero in-flight
blocks, callbacks, pending pack records, and stream-buffer blocks, then reads
and compares the page again. This checks a drained read path; it does not claim
power-loss durability.

The production watchdog is read from `kernel/dm-swapz.c` at preflight and is
currently 30 seconds. The controlled write delay is 5 seconds. The combined
write, poll, read, status, suspend, and bounded diagnostic command budget is
checked to remain below the watchdog with at least a one-second margin. Any
command timeout, status uncertainty, data mismatch, warning, unexpected DM
identity, or outstanding callback marks the VM **QUARANTINED**. The harness
records a `QUARANTINED.json` marker under the run directory where possible and
does not attempt teardown after such a failure. Do not reboot or force-remove
anything to clear quarantine; preserve the VM for the authorized operator to
inspect.

The `/dev/kmsg` reader drains records already buffered when it is opened and
reports any pre-existing warning/error records as baseline. It then checks new
records through the smoke and cleanup. The gate uses printk priority as well
as message text, so `DMERR`/`DMWARN` lines such as a swapz I/O error are caught
even when they omit the words `ERROR` or `WARNING`.

On a successful run only, teardown verifies the saved DM UUIDs and exact
tables, zero pending status, no unexpected holders, zero DM open references,
and the loop's unchanged backing-file identity. It uses ordinary `dmsetup remove`, ordinary loop detach,
and ordinary `rmmod` only for resources that this run positively created.
It never invokes `swapon`, `swapoff`, mount, physical-device access,
`dmsetup remove -f`, `rmmod -f`, reboot, or SysRq.

`dmsetup suspend`, `dd`, ordinary DM removal, loop detach, and module unload
can enter kernel waits. Each userspace command has a bound; a timeout is
treated as ambiguous kernel ownership, not proof that the operation stopped.
The VM and any remaining stack must be preserved and quarantined.

## Authorization and proposed operator command

There is no authorization in this document to run the live test. Before a
future invocation, the user or designated VM owner must explicitly authorize:

- the exact disposable VM identity;
- the exact source commit and `dm-swapz.ko` SHA-256;
- creation of one tmpfs-backed loop, one `dm-delay` target and one `swapz`
  target;
- one 4 KiB write/read, ordinary suspend/resume, and ordinary cleanup of only
  those positively owned resources;
- loading and unloading only the selected `dm-swapz` module; and
- the fail-closed quarantine policy, including preserving the VM on any
  timeout, warning, failed status, or ambiguous ownership.

The following are separate VM provisioning actions, outside the smoke
runner's ownership and requiring their own explicit approval:

1. Provision or restore a disposable VM, identify it to the operator, and
   ensure no valuable data or physical storage is exposed to the test.
   `systemd-detect-virt --vm` proves only that the runner sees a VM; it cannot
   authenticate the operator-supplied VM label or verify hypervisor device
   pass-through. The VM owner must confirm those isolation properties outside
   the harness before authorizing it.
2. Provide the running kernel's matching headers and the build tools. If they
   are absent, installing packages with the VM's privileged package manager is
   a separate authorized operation.
3. Ensure the `delay` Device Mapper target is registered before the runner.
   If `dm-delay` is not built into the kernel, an administrator must run
   `modprobe dm-delay` (which may also load its `dm-mod` dependency). This
   changes the VM's loaded-module set; it is not done or undone by the smoke
   harness, and must be included in the provisioning authorization. Check
   `dmsetup targets` afterward and confirm that it lists `delay`.
4. Create a full, root-owned checkout at
   `/root/swapz-smoke/source`, pin it to the reviewed commit, and ensure the
   checkout, `.git` directory, harness files, and parent path components are
   not group/world writable. The live preflight rejects user-owned checkouts,
   linked worktrees, or writable source paths.
5. Build `dm-swapz.ko` from that exact checked-out source against the running
   kernel's headers, then place the selected module at
   `/root/swapz-smoke/dm-swapz.ko` with root ownership and non-writable parent
   paths. Record `git rev-parse HEAD`, `sha256sum` of the module,
   `modinfo -F name`, and `modinfo -F vermagic` independently. The runner
   checks the full source SHA, selected module SHA-256, module name, and first
   vermagic token against the running kernel before loading it. These checks
   bind the approved identities; the operator remains responsible for
   building the artifact from the approved source SHA.

The harness itself runs as root and performs only the separately approved
operations listed in its authorization string: create one `/dev/shm`-backed
loop device, `insmod` the selected `dm-swapz.ko`, create the UUID-tagged
`dm-delay` and one-page `swapz` targets, perform one aligned 4 KiB write/read,
query status, ordinarily suspend/resume, then ordinarily remove those exact
owned targets, detach the owned loop, and `rmmod dm_swapz`. It never owns or
unloads the provisioned `dm-delay` module. If the harness times out, sees a
warning, finds ambiguous ownership, or cannot prove a drained state, it leaves
the remaining resources in place and marks the VM quarantined. Any later
forensic cleanup or VM reset needs a new, separately scoped authorization;
there is no automatic cleanup path for quarantine.

The 32 MiB backing image is 65,536 sectors, or 8,192 4 KiB blocks. That gives
32 complete 1 MiB segments. The production constructor rounds physical
capacity down to complete segments and requires at least three segments plus
the larger of 25% of the one-page logical size or two segments of reserve.
Here the reserve is 512 blocks, so the 8,192-block `dm-delay` mapping exceeds
the constructor minimum. The loop is verified against the exact 32 MiB image;
the `dm-delay` table is verified to cover all 65,536 sectors. Only the swapz
logical table is one page (`0 8` sectors).

After that separate approval, the operator can run this command, replacing the
example VM label and approved identities:

```bash
SOURCE_ROOT=/root/swapz-smoke/source
VM_ID=disposable-swapz-v22-20261010
SOURCE_SHA='<approved exact commit SHA in SOURCE_ROOT>'
MODULE=/root/swapz-smoke/dm-swapz.ko
MODULE_SHA256='<approved recorded SHA-256>'
AUTH="I AUTHORIZE swapz V2.2 smoke only on disposable VM $VM_ID with source $SOURCE_SHA and module SHA-256 $MODULE_SHA256; permitted operations are one /dev/shm-backed loop device, one dm-delay target, one swapz target, one aligned 4 KiB write/read, ordinary suspend and resume, ordinary removal of resources positively created by this run, and insmod/rmmod of only the selected dm-swapz module; no swap activation, mount, physical storage, forced removal, or host reboot."
sudo "$SOURCE_ROOT/tests/runtime/virtual-smoke.sh" \
  --run-live \
  --vm-id "$VM_ID" \
  --source-sha "$SOURCE_SHA" \
  --module "$MODULE" \
  --module-sha256 "$MODULE_SHA256" \
  --authorization "$AUTH"
```

Do not run this command until the exact VM and operation list above have been
explicitly authorized. The script independently refuses bare metal, mismatched
source/module identities, an existing `dm-swapz` module, missing prerequisites,
or an authorization-string mismatch.

## Rootless validation scope

Run the checked-in mocks with:

```bash
bash -n tests/runtime/virtual-smoke.sh
timeout 25s python3 -B tests/runtime/virtual-smoke-test.py -v
```

The mocks cover successful staged-hit/read/drain ownership order, confirmed
partial creation failures, command timeout, callback/status uncertainty,
unexpected warnings, byte mismatch, failed removal, authorization refusal,
and status-field validation. They exercise the same orchestration with fake
operations; they do not issue `insmod`, `dmsetup`, `losetup`, or block I/O and
do not establish real kernel or device correctness.
