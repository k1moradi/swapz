# V2.2 direct-`dd` admission policy

**Status: production mapper admission remains disabled.** The normal pidfd
service CLI still admits only its fixed `sleep` and `exit` test workers. No
production recall integration or mapper I/O is enabled. The source-only
changes below provide stricter bootstrap contracts and mock-tested rejection
paths; they do not supply the separately controlled privileged fixture owner
or a real GNU trust anchor required to turn that path on.

## Fixed role interface

The direct-I/O policy accepts only the five fixture roles. IPC supplies a role
string; it cannot choose argv, executable, environment, working directory,
numeric PID, mapper name, source path, or output path.

| Role | Fixed operation |
| --- | --- |
| `writer` | Nine 4 KiB blocks from the pinned `pages.bin` descriptor to the pinned mapper descriptor. |
| `a` | Read page 0 to the exclusive `read-a` output descriptor. |
| `b` | Read page 4 to the exclusive `read-b` output descriptor. |
| `a2` | Concurrent read of page 0 to `read-a2`. |
| `b2` | Concurrent read of page 5 to `read-b2`. |

The writer must be admitted before any reader; each role is one-use. The
service's ordinary CLI and its fixed test-worker allowlist are unchanged.

## GNU executable provenance

`RecallDDLaunchGate` reuses the existing pinned-descriptor hashing and sealed
executable memfd implementation. For a real block mapper, a bare
`expected_executable_sha256` string is rejected. The digest must come from a
strict signed manifest passed through `TrustedGNUCoreutilsDD.from_signed_manifest`.
The signed payload binds all of these fields:

```json
{
  "format": 1,
  "vendor": "GNU Project",
  "package": "coreutils",
  "binary": "dd",
  "version": "<trusted build version>",
  "executable": "/absolute/path/to/dd",
  "sha256": "<binary digest>",
  "source_sha256": "<GNU release source digest>",
  "linkage": "static"
}
```

The verifier callback is deliberately mandatory and has no default. Trusted
bootstrap code must verify the detached signature against a separately
controlled public key or another independently managed build/package trust
root. It must not compute the executable's digest and then sign or accept that
digest as trust configuration. Rootless tests use a fake signature verifier
and synthetic ELF data; those tests prove schema and fail-closed behavior,
not GNU package identity. No trusted GNU manifest or signing key is shipped
by this repository, so the live mapper path stays unavailable.

The gate opens the exact absolute manifest path without `PATH` lookup, checks
the pinned descriptor, rejects setuid/setgid bits and any file-capability
xattr, hashes the pinned bytes against the signed digest, and creates the
existing write-sealed executable memfd snapshot. It also rechecks the source
descriptor and path identity before each role. A replaced pathname or
in-place mutation closes admission permanently. A path check is not treated
as a substitute for the retained descriptor.

Only little-endian static ELF is admitted for mapper I/O. A dynamic executable
would resolve its ELF interpreter (`PT_INTERP`) and shared libraries from the
host at exec time; hashing and sealing only `dd` would not pin those objects.
This prototype rejects dynamic GNU coreutils builds rather than assuming the
loader and library closure are trusted. A future design could admit a
dynamically linked build only after a separately reviewed system-image or
package-closure trust mechanism binds the interpreter and every loaded
library through launch. A matching executable hash alone does not prove GNU
semantics; the signed provenance must identify an actual GNU coreutils build.

The supervisor still starts the direct executable behind its pidfd gate and
passes only explicitly approved close-on-exec descriptors. No shell or
background wrapper is added. No numeric-PID signaling fallback exists.

## Mapper identity and lifecycle

`open_test_mapper_fd` requires an explicit mapper name matching
`swapz-v22-recall-[A-Za-z0-9_-]{1,48}` and a `MapperLifecycleLease` from trusted
fixture bootstrap. The retained descriptor must be a block device whose
major/minor matches the fixture identity. The helper checks kernel sysfs
`dm/name`, `dm/uuid`, and `dev`; before every role the lease's identity reader
must also return the exact mapper name, UUID, device number, and SHA-256 of the
active DM table.

The lease is backed by a private, single-link fixture lock file. The bootstrap
must acquire its exclusive `flock` before creating the mapping, retain it
through every role, and serialize all fixture table, rename, removal, and
recreation operations through that lock. The policy opens the lock path a
second time to verify that the owner lock remains held; if the lock is
released, replaced, unreadable, or cannot be independently checked, admission
is denied. A mismatch in UUID, device number, or table fingerprint permanently
closes role admission.

A table fingerprint detects an observed change. It does not prevent a
privileged actor from replacing a table between the check and the worker's
open. The `flock` is cooperative, not a kernel-enforced DM table lock. The
exclusive-owner assumption is valid only when a separately controlled
privileged fixture owner is the sole authority allowed to create, reload,
rename, or remove this disposable mapping and every such operation obeys the
lease. That owner and its signed GNU build manifest are not implemented here;
the normal service cannot construct this configuration from IPC.

The table identity reader must query the live kernel table (for example,
through a read-only `DM_TABLE_STATUS`/table-status operation) and hash a
canonical, key-safe representation. It must reject incomplete, ambiguous, or
changing output. The sysfs name/UUID/dev checks alone do not identify table
contents. Tests inject a fake reader over ordinary temporary files and never
open `/dev/mapper`. The regular-file mapper branch is accepted only with an
explicit injected synthetic verifier for rootless tests. The default mapper
verifier rejects regular files; this test seam is not a production mapper
configuration.

## Remaining process and descriptor boundaries

The fixed direct child is the intended I/O process; retained pidfds identify
and signal that direct process. pidfds do not contain arbitrary descendants or
automatically kill workers after supervisor crash. The prior seccomp process
creation restrictions and parent-death handling remain relevant, but neither
removes the need for a separately verified process containment and kernel
I/O-drain barrier. A service crash, lost response, descriptor close error,
worker lifecycle error, or unverified mapper identity means preserve the
backing image.

## Tests and qualification limits

`python3 tests/runtime/recall-dd-allowlist-test.py -v` exercises signed-manifest
parsing with a fake verifier, synthetic static/dynamic ELF, digest mismatch,
capability and setid rejection, pinned path mutation/replacement, sealed
snapshots, fake sysfs identities, the fixture lock, table fingerprint changes,
and sticky denial. Existing direct-`dd` worker integration uses only temporary
regular files. These are source-only and rootless checks. They do not prove
that a supplied signature key is trusted, that a particular executable is GNU
coreutils, that a privileged mapper owner enforces the cooperative lock, or
that real DM/loop I/O has drained.
