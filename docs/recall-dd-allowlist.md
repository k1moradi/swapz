# V2.2 direct-`dd` admission policy

**Status: production mapper admission remains disabled.** The normal pidfd
service CLI still admits only its fixed `sleep` and `exit` test workers. No
production recall integration or mapper I/O is enabled. The trusted GNU
bootstrap and mapper owner below are source-only policy components. Their
tests use temporary files and injected fake DM operations; they do not prove a
real signing provenance chain or kernel-enforced exclusive DM ownership.

## Fixed role interface

Direct-I/O policy accepts only five fixture roles. IPC supplies a role string;
it cannot choose argv, executable, environment, working directory, numeric
PID, mapper name, source path, or output path.

| Role | Fixed operation |
| --- | --- |
| `writer` | Nine 4 KiB blocks from the pinned `pages.bin` descriptor to the pinned mapper descriptor. |
| `a` | Read page 0 to the exclusive `read-a` output descriptor. |
| `b` | Read page 4 to the exclusive `read-b` output descriptor. |
| `a2` | Concurrent read of page 0 to `read-a2`. |
| `b2` | Concurrent read of page 5 to `read-b2`. |

The writer must be admitted before any reader, and each role is one-use. The
ordinary service CLI and its fixed test-worker allowlist are unchanged.

## GNU trust bootstrap

`TrustedGNUCoreutilsDD.from_trusted_bootstrap()` accepts no caller-supplied
manifest, digest, key, verifier, or path. It reads the detached manifest and
signature from the fixed root-controlled directory
`/etc/swapz/trust/gnu-coreutils-dd/`. The only permitted entries are
`manifest.json`, `manifest.sig`, and an optional `REVOKED` marker. It reads the
separately provisioned Swapz manifest-signing public key from the fixed
package-data path
`/usr/share/swapz/trust/swapz-gnu-dd-manifest-ed25519.pub`. This Ed25519
application key is distinct from GNU's GPG release-signing key. Every path component is
opened descriptor-relatively with `O_NOFOLLOW`; directories and regular files
must be root-owned, single-link where applicable, and not group/world writable.
Files are bounded, checked against their open descriptors, read from pinned
descriptors, and closed successfully. Any missing, revoked, changed,
malformed, or uninspectable item denies admission.

The signature adapter verifies an Ed25519 detached signature using the fixed
`/usr/bin/openssl` executable opened without following symlinks and held by an
inherited descriptor for the verifier subprocess. The manifest, signature,
and key bytes are passed through sealed memfds; no shell or PATH search selects
the verifier. The OpenSSL child receives only those descriptors, a fixed
argument vector, a minimal environment, and a five-second timeout. It rejects
SUID/SGID and file-capability metadata. Verification, descriptor-close, or
timeout errors all fail closed. The old API that accepted a caller verifier is
removed; manifest parsing follows successful verification of the fixed files.

The expected manifest schema remains strict and binds the named GNU coreutils
`dd`, version, executable path and SHA-256, source archive SHA-256, and static
linkage. A manifest label and matching binary digest do not establish GNU
semantics by themselves. The installer of the Ed25519 trust key and signer
must independently establish the source/build chain before signing this
manifest. GNU release announcements publish source archives, detached GPG
signatures, checksums, and the release-signing key fingerprint. The separate
qualification procedure verifies the 9.11 source archive and records its
static build recipe, toolchain, output binary, and worker-boundary run; see
[`gnu-coreutils-qualification.md`](gnu-coreutils-qualification.md) and the
machine-readable [`9.11 qualification record`](gnu-coreutils-9.11-qualification.json).
The two clean builds are same-host repeatability evidence, not independent
builder reproduction. The Ed25519 application public key must still be
provisioned through a separate trusted administrator/package channel, with its
fingerprint checked out of band. Installing a new key beside a manifest and
treating that key as trusted would not meet this contract.

The qualification host's `/usr/bin/dd` is not accepted as provenance merely
because of its pathname. The actual test used a GNU coreutils 9.11 binary built
from the authenticated release source. The production direct mapper path
remains unavailable because no production application key or manifest is
installed and trusted exclusive DM ownership and kernel I/O-drain qualification
are still outstanding. Disposable Ed25519 application keys in rootless tests
exercise signature mechanics only; they are not production authentication.

### OpenSSL and direct-exec compatibility assumptions

The verifier pins the OpenSSL executable descriptor for its subprocess, but
does not seal or independently hash the host's OpenSSL installation. OpenSSL
is dynamically linked on the tested host; its ELF interpreter, shared
libraries, and provider modules are trusted as part of the root-controlled
host operating-system package set. `OPENSSL_CONF` is fixed to `/dev/null`, and
the application does not permit an IPC caller to select a provider, config,
binary, or library path. A deployment that cannot trust and maintain that OS
closure must replace this bootstrap verifier with a separately reviewed
implementation or keep admission disabled.

The proposed direct worker must be a little-endian static ELF for the same
architecture as the supervisor: currently only x86-64 and AArch64 are
recognized. The launch gate hashes the pinned executable, checks its ELF
machine and absence of `PT_INTERP`, then copies it to a write-sealed executable
memfd requiring `MFD_EXEC` and `F_SEAL_EXEC`. Unsupported kernels, architectures,
memfd policy, or seals deny admission. The existing child seccomp setup permits
`execve` of the already selected descriptor-backed image but blocks process
creation, credential changes, namespace changes, and asynchronous I/O. GNU
coreutils 9.11 was run through this gate on the qualification host against
temporary regular files, including all five fixed roles and pidfd cancellation.
That result is host-specific; see the execution record and procedure. It does
not qualify a different kernel, architecture, memfd policy, or a real mapper.

## Exact mapper owner state controller

`MapperLifecycleOwner` represents one exact mapper identity for one fixture
session: grammar-checked name, UUID, major/minor, and table SHA-256. It requires
a pre-held `MapperLifecycleLease` and injected trusted-owner operations. Its
state sequence is:

```text
NEW
  -> check owner + lease + complete DM inventory
  -> create exact mapping, retain its descriptor
  -> verify descriptor and exact inventory
ACTIVE
  -> recheck owner, lease, descriptor, UUID, device and table before each role
  -> close role admission
ADMISSION_CLOSED
  -> verify session-bound worker reaped + role-descriptor-closed attestation
  -> ordinary DM suspend (no --noflush); require positive drained state
  -> close retained mapper descriptor
  -> verify complete open count is zero and holders are empty
  -> normal exact removal
  -> independently confirm the bound identity is absent
  -> release the lease
MAPPING_RELEASED (mapper-only result; backing must still be preserved)
```

Every failed or ambiguous owner check, inventory, identity comparison,
descriptor operation, removal, or lease operation latches `DENIED`. The owner
does not expose a `cleanup_allowed` property. Its `mapping_released` property
means only that the exact mapping was normally removed and observed absent;
`backing_must_be_preserved` stays true even after that state. It is deliberately
not a backing-file release authority. Duplicate names, UUIDs or device numbers
are rejected. Only the exact configured identity is passed to the injected
create, ordinary suspend, open-count/holder inspection, and normal remove
operations; IPC never selects a device or invokes privileged lifecycle
commands. The owner admits only the five fixed roles, closes role admission
before teardown, and exposes no table-reload operation. A detected table
fingerprint change permanently denies the session. It rejects concurrent
operations and rechecks owner/lease state around inventory observations.

Before mapper-only release, the owner requires a typed completion report bound
to its random session identifier. It reconciles the exact handles it registered
against reaped handles and per-handle role-descriptor closure, requires an
error-free service exit status of zero, and calls the injected trusted-owner
verifier on the report authenticator. Caller booleans such as
`workers_reaped=True` are no longer accepted. The fixture owner then requires
ordinary suspend with flush semantics, closes its retained mapper descriptor,
checks a complete zero-open-count and empty-holder observation, performs normal
removal, verifies exact name/UUID/device-number absence, and releases its
cooperative lease. Failures preserve the backing and latch denial.

Each admitted role must be paired with exactly one opaque worker handle in
admission order before `close_admission()` succeeds. An admitted role without a
registered worker, a handle without a prior matching role, or a role/handle
inventory mismatch permanently denies release. This prevents an empty worker
receipt from standing in for I/O that was authorized but never entered the
owner's inventory.

This is an injected state controller, not a privileged Device Mapper
implementation. Its fake operations are ordinary test code. The flock lease is
cooperative: it detects a replaced lock file and an owner that released the
lock, but it cannot stop a privileged process that ignores the protocol. Table
fingerprints detect observed changes but cannot prevent a privileged table
reload between verification and use. A future fixture owner needs a dedicated
privileged broker that acquires exclusive lifecycle authority before mapping
creation, retains the only authorized DM control capability, and serializes
create, role admission, ordinary suspend, normal removal, and exact absence
verification. The worker IPC process must have no DM control descriptor or
`CAP_SYS_ADMIN`; only the small owner/broker may hold the privilege required by
the chosen DM control mechanism. Use a root-controlled executable/configuration,
dedicated service credentials, close-on-exec descriptors, and a private
authenticated channel. A mount or device namespace and an ordinary flock do
not exclude host-root. An unrelated host-root actor with sufficient kernel
authority cannot be excluded by a cooperative lock. Until an independently
reviewed credential and exclusive-control boundary exists, live mapper
admission remains disabled.

Mapper-only release and backing release are separate authorities. A new
session-bound evidence policy requires authenticated reports for admission
closure, complete worker/service/descriptor reconciliation, independent swap
inspection, ordinary flushing DM suspend, descriptor closure, complete
open-count and holder checks, normal removal, exact name/UUID/device-number
absence, upper/lower dependency resolution, and normal loop detach followed by
verified absence. Every event has a monotonic sequence and an HMAC over the
session, event, sequence, and canonical payload. The key belongs only to a
future trusted fixture owner and is not accepted over worker IPC. Missing,
stale, conflicting, unauthenticated or failed evidence keeps backing
preservation latched. This HMAC test model does not authenticate real kernel
observations; only a privileged, separately qualified collector can do that.
Successful pidfd reaping is not a kernel I/O barrier. No operation in either
model executes `dmsetup`, opens a real `/dev/mapper` node, or removes a real
mapping.

## Remaining process and storage boundaries

The direct worker is intended to be the actual I/O process, with no shell
wrapper or background function. Retained pidfds bind signals to that direct
child, but do not contain arbitrary descendants or automatically kill workers
after supervisor crash. Seccomp restrictions and parent-death handling remain
useful constraints, not a complete process-tree or kernel-I/O-drain proof. A
service crash, lost response, lifecycle error, close error, unverified mapper
identity, or unavailable drain evidence means preserve the backing image.

## Tests and qualification limits

`python3 tests/runtime/recall-dd-allowlist-test.py -v` checks detached
Ed25519 verification with disposable test keys, wrong-key and malformed
manifest rejection, the separately provisioned-key path, revoked or missing
configuration, synthetic static/dynamic/wrong-architecture ELF, digest
mismatch, setid and capability rejection, pinned path mutation/replacement,
sealed snapshots, fake DM identities, lock replacement, owner loss, inventory
ambiguity, concurrent lifecycle calls, descriptor-close failure, and exact
normal-removal/absence ordering. These policy tests do not independently
reproduce the GNU binary build or prove real exclusive DM authority. The GNU
qualification runner uses the actual authenticated-source build against
temporary regular files; it is not a mapper test.
