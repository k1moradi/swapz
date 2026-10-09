# GNU coreutils `dd` source and worker qualification

## Status

GNU coreutils 9.11 source authentication and one local static build were
verified on the qualification host. The actual resulting GNU `dd` executable
ran the five fixed recall roles through the existing sealed-executable launch
gate, pidfd supervisor, strict descriptor allowlist, parent-death setup, and
seccomp filter against temporary ordinary files. A separate test interrupted
and reaped a long copy through the retained pidfd.

This is a source/build and rootless worker qualification, not production
artifact approval. The two clean builds in the qualification tool are a
same-host repeatability check; they are not an independent builder. No
production Ed25519 key or manifest was installed. Direct mapper admission and
production recall remain disabled pending an administrator-controlled trust
bootstrap, exclusive mapper owner, and independently verified kernel I/O
drain barrier.

## Release provenance

The qualified source release is GNU coreutils 9.11, released on 2026-04-20.
The official GNU announcement identifies release commit
`c01fd163a47468a8296fb369f5233853bb551bb6`, gives the source archive and
release key ID, and names the release-signing key fingerprint
`6C37DC12121A5006BC1DB804DF6FD971306037D9`. It also records the bootstrap
versions for Autoconf, Automake, Gnulib, and Bison. See the [GNU release
announcement](https://lists.gnu.org/archive/html/coreutils-announce/2026-04/msg00000.html)
and [GNU Coreutils release archive](https://ftp.gnu.org/gnu/coreutils/).

The exact `.tar.xz` archive SHA-256 pinned by this helper is
`394024eda0a5955217ceda9cd1201e65dc8fa3aa29c2951135a49521d57c3cc3`. The
helper requires both this published checksum and a detached GPG signature
whose primary fingerprint and signature timestamp match the pinned release
record. The GNU keyring is an input, but an arbitrary keyring cannot substitute
another signer because the full fingerprint is checked. Before using this
process operationally, an administrator should independently cross-check the
fingerprint from the GNU announcement through a separate trusted channel.

The machine-readable build result is recorded in
[`gnu-coreutils-9.11-qualification.json`](gnu-coreutils-9.11-qualification.json).
It records source, detached-signature and GNU keyring digests, GPG verifier
identity, build recipe, host tool versions and hashes, ELF properties, binary
digest, and the two-build comparison. The corresponding actual worker result is in
[`gnu-coreutils-9.11-seccomp-execution.json`](gnu-coreutils-9.11-seccomp-execution.json).
Neither record states that another builder reproduced the output.

## Reproduce source and build qualification

Use a clean, non-privileged temporary directory. Obtain the archive, detached
signature, and GNU keyring from GNU's published locations. Do not install or
replace production trust credentials as part of this procedure.

```bash
python3 tests/runtime/gnu-coreutils-qualification.py verify-source \
  --archive coreutils-9.11.tar.xz \
  --signature coreutils-9.11.tar.xz.sig \
  --keyring gnu-keyring.gpg \
  --version 9.11 \
  --record source-record.json

python3 tests/runtime/gnu-coreutils-qualification.py build-static \
  --archive coreutils-9.11.tar.xz \
  --signature coreutils-9.11.tar.xz.sig \
  --keyring gnu-keyring.gpg \
  --version 9.11 \
  --output-dir ./coreutils-9.11-qualified-build
```

The fixed recipe uses the release tarball's generated `configure`, GNU make,
`/usr/bin/gcc`, `-O2 -g0`, a source path map, `-static`, and disables NLS, ACL,
and SELinux support. `SOURCE_DATE_EPOCH` is set to the signed release's pinned
signature epoch. It builds two separately extracted source trees and compares
the resulting executable hashes. The record includes resolved tool paths,
tool hashes and versions, compiler target, static libc archive path, OS/kernel
identity, build-log hashes, and output ELF facts. The build helper normalizes
the output executable to mode 0755 through its opened descriptor before
inspection; this avoids inheriting a permissive group-write umask.

A matching same-host result is evidence of repeatability on that host, not
independent reproducibility. A second controlled builder should repeat the
process and compare source and binary digests before promoting a binary into a
production manifest. The toolchain binaries and static libc/toolchain inputs
remain part of the builder's trusted computing base. Their recorded hashes
and versions make review possible but do not authenticate the host package
chain by themselves.

## Exercise the real worker boundary

After the source verifier and build succeed, run the produced `src/dd` using
its exact recorded SHA-256:

```bash
python3 tests/runtime/recall-gnu-dd-seccomp-qualification.py \
  --archive coreutils-9.11.tar.xz \
  --signature coreutils-9.11.tar.xz.sig \
  --gnu-keyring gnu-keyring.gpg \
  --binary ./coreutils-9.11-qualified-build/copy-1/source/coreutils-9.11/src/dd \
  --build-record ./coreutils-9.11-qualified-build/qualification-record.json \
  --record worker-execution-record.json -v
```

The runner re-verifies the GNU source archive, pins and inspects the binary,
then creates a disposable application Ed25519 key and signed manifest solely
to exercise the existing production bootstrap API. Its temporary directory
is deleted when the test exits. This key is not a GNU release key and is not
installed as production configuration. The launch-gate test uses a synthetic
mapper verifier over an ordinary temporary file. It checks writer plus A/B
and concurrent A2/B2 reads, exact 4 KiB output against independently generated
page data, actual worker exit/reaping, descriptor allowlisting, and pidfd
cancellation. The test performs no `/dev/mapper`, DM, loop, swap, or block I/O.
The runner checks that the candidate resolves to one of the two build outputs
under the record's directory and that its digest and authenticated source hash
match that record. The record is review evidence generated by the local build
helper; it is not a signed production trust object.

This proves the tested GNU build can execute under the current host's worker
security boundary for these regular-file operations. It does not prove that a
different architecture, kernel, seccomp policy, memfd policy, or OpenSSL
installation will behave the same way.

## Administrator-controlled production bootstrap

The runtime continues to require a separate root-controlled Ed25519
Swapz manifest-signing key at
`/usr/share/swapz/trust/swapz-gnu-dd-manifest-ed25519.pub` and a detached
manifest under `/etc/swapz/trust/gnu-coreutils-dd/`. No code generates or
installs these credentials. A deployment administrator must:

1. Independently verify the GNU signing fingerprint and source archive.
2. Review the complete machine-readable build record and, preferably, obtain a
   matching build from an independent controlled builder.
3. Approve the exact binary digest, release, source digest, executable path,
   and static-link status.
4. Provision the application public key using a root-controlled package or
   equivalent separate trust channel.
5. Sign and install the strict manifest and detached signature with root-owned,
   non-group/world-writable directories and files.
6. Rotate or revoke the application key through a separate trusted update
   process. The `REVOKED` marker blocks admission; replacing a key or manifest
   beside each other is not a trust bootstrap.

The test harness never performs these operations. If trusted source, binary,
key, manifest, metadata inspection, signature verification, executable
sealing, or seccomp support is unavailable, admission must fail closed.

## OpenSSL verifier assumptions

The manifest adapter opens `/usr/bin/openssl` with `O_NOFOLLOW`, checks its
owner, mode, capabilities, type and open-versus-path identity, then executes
that pinned descriptor with a minimal environment, sealed input memfds,
closed unrelated descriptors, and a five-second timeout. The executable is
not independently hashed or sealed. On the qualification host it is a
dynamically linked OpenSSL 3.5.5 binary with the ELF interpreter
`/lib64/ld-linux-x86-64.so.2` and `libssl`, `libcrypto`, `libc`, `libz`, and
`libzstd` dependencies. `OPENSSL_CONF=/dev/null` suppresses an operator config
file, but does not authenticate the interpreter, loader cache, libraries, or
provider modules. The trusted OS package and root-owned loader configuration
are therefore part of the verifier trust boundary. A deployment must inspect
and maintain that closure. If it cannot trust this OS-level closure, it must
use a separately reviewed static verifier or keep admission disabled.

## Qualification layers and remaining gate

Keep these results distinct:

1. **GNU source authenticity:** detached GNU signature, pinned full signer
   fingerprint, official checksum, and release metadata verified.
2. **Local binary qualification:** two same-host static builds compared; the
   exact candidate passed ELF, version, metadata and digest checks. Independent
   builder reproduction is still outstanding.
3. **Worker security boundary:** the exact local static GNU `dd` ran the five
   fixed roles and cancellation case through the actual rootless gate,
   supervisor and seccomp filter on this host.
4. **Real mapper lifecycle:** not run. Production admission remains disabled
   until trusted fixture ownership can exclude privileged table mutation and
   the independent kernel-side I/O-drain barrier has been implemented and
   qualified.
