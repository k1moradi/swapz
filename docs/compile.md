# Build and Install

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands; the sole owner-approved exception is the development decision loop `make fast_test`, which never qualifies a source, never writes or publishes `test_results.json` and never replaces `make test`. Private scripts and CI jobs are implementation details, not operator interfaces.

## Build

The production kernel source is `src/kernel/`. There is one module:
`dm-swapz.ko`. Kbuild links the DM/codec/authority/engine core plus the
delta64 predictor core. x86_64 also links isolated SSE2, AVX2 and AVX-512
predictor objects; arm64 with kernel-mode NEON links the isolated NEON object.
These are backends inside the same module, not alternate research modules. The
Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`.

Normal artifacts live only under `build/`:

- `build/kernel/experimental/dm-swapz.ko`: normal current-kernel build eligible for owned-RAM qualification.
- `build/kernel/w1/dm-swapz.ko`: W=1 warning build.
- `build/kernel/w2/dm-swapz.ko`: W=2 warning build.
- `build/userspace/`: supported userspace binary.
- `build/tests/native/`: native production-C test executables.
- `build/tests/native/anon-page-analyzer`: private streaming analyzer built
  during `make test` and `make fast_test`; it accepts owner-supplied page data
  only through the ID177 representative-content workflow.

The root `make` target normalizes qualified build-artifact permissions after
building: non-executable inputs are mode 0644 and the userspace/oracle binaries
are mode 0755. The official test report is also written mode 0644. This keeps
the exact-artifact admission checks independent of the caller's umask without
weakening their refusal of group/world-writable files.

The one generated qualification artifact outside `build/` is the root
`test_results.json`. This is UTF-8 JSON with newlines, without compression or indentation. It is
intentionally overwriteable and versioned so
the latest completed PASS/FAIL/BLOCKED/INCOMPLETE result is directly readable from
GitHub; no second report copy is generated.

[`src/kernel/VERSION`](../src/kernel/VERSION) is the release-metadata source. Kbuild generates the version header; DKMS and userspace resolve the same value.

### Kernel-version compatibility evidence

There is no project-approved minimum or maximum Linux kernel release and no
promised kernel-version support interval. The GitHub-hosted production-C
workflow compiles W=1, W=2 and the normal module on x86_64 and ARM64 against
one runner-selected Ubuntu 24.04 HWE `-generic` header per architecture.
The highest installed `linux-headers-*-generic` release is selected after
installing `linux-headers-generic-hwe-24.04`; it is not pinned, and may change
with the runner package repository. The workflow reports the selected header
release, runner architecture, compiler, source SHA, target-source Git blob,
module hash and vermagic. Before treating Kbuild's compiler command-name
notice as non-source noise, CI requires the selected headers to record GCC
and the build GCC major version to match their recorded compiler version. The normal module's
vermagic release must also equal the selected `kernel.release`. The warning
gate rejects swapz-source warnings, excludes the pahole-availability notice,
and reports warnings originating in installed kernel headers separately. This
does not claim the distribution headers are warning-free. A successful job does
**not** cover the oldest
supported kernel, every intermediate kernel, or a future upgrade: none of
those version boundaries is currently defined.

These CI builds are compile-only evidence, not DKMS registration, a
successfully loaded module, real-host Secure Boot acceptance, boot validation
or swap correctness. A kernel update still requires matching headers, new
exact-kernel qualification through `make test` on the actual host and an
explicit qualified install; `AUTOINSTALL="no"` remains in force. A defined
kernel compatibility range and its oldest/current compile matrix require a
separate project policy decision before they can be claimed.

## Root Make API

Exactly five commands are public:

- `make`: build product artifacts without loading them.
- `make install`: admit and install the exact artifacts already qualified by `make test`; it does not rebuild, re-sign, load the module, create a mapper, or activate swap.
- `make uninstall`: remove only the matching owned installation.
- `make test`: execute the complete supported qualification.
- `make fast_test`: development-only decision loop: build the working tree,
  run native/replay contract checks and the selected owned-null_blk scenarios
  (three paired repeats per scenario by default), and print compact raw/swapz,
  critical-path and synchronous-cycle tables. It never qualifies a source or
  writes the report. `make fast_test RESUME=1` reuses matching private,
  input/artifact-fingerprinted native/replay results; it refreshes the
  product build, reruns loaded preflight and starts benchmark pairs fresh.
  `CONTENT=representative` additionally requires the
  owner-supplied `ANON_PAGE_SAMPLE` described under ID177 in the testing
  standards.

No other root aliases or public test targets are permitted.

## Direct-main CI standards co-changes

When a push triggers project-goals, the repository-policy job checks **every
first-parent commit introduced by that push** against that commit's own first
parent, including
changes in `src/`, `tests/`, `packaging/`, `.github/workflows/`,
`Makefile`, and `dkms.conf`. It retains the pushed history needed for this
per-commit comparison, so a later documentation-only commit in the same push
cannot hide an earlier implementation-only violation. Every such implementation
commit must also make a **meaningful update in that same commit** to at least
one canonical standard: `docs/coding_standards.md`,
`docs/testing_standards.md`, `docs/compile.md`, or `docs/benchmark.md`.
Document the changed contract, expectation, or operational implication; a
previous commit's standard, a noncanonical documentation change, and a green
compile or rootless test run do not waive this requirement.

On the permitted `main` branch, stage the implementation and relevant
standard together, inspect the staged diff, and make one focused commit.
Fetch and verify `origin/main` before publication; publish only by a
non-force, head-checked fast-forward. If `main` advances concurrently,
reconcile the unpublished implementation and standard edits against its new
head and recheck before pushing. Do not create a branch or PR or rewrite
published commits. `make test` remains the sole official qualification
command, with `make fast_test` only the nonqualifying development loop.

Documentation-only changes and generated `test_results.json`-only evidence
commits require no extra standards edit. The test reporter labels its
report-only evidence commits `[skip ci]`; that prevents the push-triggered
Actions run. The repository-policy script still treats report-only evidence as
non-implementation, while the exact-SHA conclusion independently inspects the
tested HEAD commit and refuses `[skip ci]`, including an explicit workflow
dispatch. Therefore a report-only or intentionally skipped commit cannot
manufacture a fresh exact-SHA CI PASS. The marker is not a policy exemption for
implementation work. An implementation commit labeled `[skip ci]` remains
noncompliant without a same-commit standard update and must never be used to
bypass the direct-main policy. Rootless CI is partial evidence: the exact-SHA
conclusion rejects failed, skipped, and cancelled dependencies and never
substitutes for owner-run `make test` qualification.

A same-commit policy failure on published history cannot be repaired
retroactively. Its diagnostic must name the offending SHA and path, explain the
reason, and give the safe corrective procedure: do not amend or force-push the
published commit and do not add a documentation-only repair. Future
release-candidate implementation, test, or CI changes must carry a meaningful
canonical standards update in the same new commit, then be published by a
non-force fast-forward to `main` and obtain their own exact-SHA CI result.

CI patch-hygiene checks must inspect each pushed commit against its first
parent. A bare `git diff --check` on a clean checkout only examines uncommitted
working-tree changes and cannot qualify the committed patch. Exact-SHA jobs
that perform the committed-diff check must fetch the parent needed for that
comparison; a separate bare `git diff --check` may remain after tests to catch
whitespace errors introduced into the workspace during execution.

## Incremental builds

Kernel staging compares content before copying so unchanged source does not invalidate all object timestamps. W=1, W=2 and normal builds use separate output directories. Userspace/helper changes should not force unrelated kernel recompilation.

SIMD predictor files are separate translation units so ordinary kernel objects
retain architecture no-FPU flags. x86 SSE2/AVX2/AVX-512 objects opt into
`CC_FLAGS_FPU`; AVX2 adds `-mavx2` and AVX-512 adds `-mavx512f`, with
conflicting no-SIMD flags removed per object. arm64 NEON uses `CC_FLAGS_FPU`
and removes `CC_FLAGS_NO_FPU`. Runtime selection never changes the
single-module artifact.

Device Mapper API compatibility is selected at build time from the installed
kernel header, not from a kernel-version threshold. Kbuild probes `dm-io.h`
for the separate unsupported-operation bitmap ABI and compiles the single
`dm-target.o` wrapper with the matching typed callback/call signature. This
also covers distribution kernels that backport the API before its upstream
release version. Build comments and source contracts should describe this as a
header capability probe rather than embedding a particular version-macro token.

The official test runner may use Make jobserver parallelism for independent compilation, but loaded device phases and benchmark pairs remain sequential.

## Secure Boot module signing

After the normal current-kernel Kbuild finishes, the root `make` path checks
whether firmware Secure Boot is enabled. When it is enabled,
`build/kernel/experimental/dm-swapz.ko` is signed with `kmodsign sha512`
before the build succeeds. The default Ubuntu MOK locations are
`/var/lib/shim-signed/mok/MOK.priv` and
`/var/lib/shim-signed/mok/MOK.der`; `SWAPZ_MOK_PRIVATE_KEY` and
`SWAPZ_MOK_CERT` may select an equivalent enrolled signing key and
certificate. When Secure Boot is enabled, the configured certificate must also
be reported enrolled by `mokutil --ignore-keyring --test-key`; a matching
signature made by an unenrolled certificate is refused. Secure Boot-disabled
and non-EFI hosts do not sign the module.

The signing hook parses the Linux module-signature trailer and verifies the
appended detached PKCS#7/CMS signature over the exact module payload against
the configured certificate. Enrollment is checked separately against the
firmware MOK list with `mokutil --ignore-keyring --test-key`; Mokutil versions
use a status of 1 for the exact `<certificate path> is already enrolled`
response. For the supported mokutil 0.7.2 behavior, status 0 means the key is
not enrolled. The hook accepts only status 1 with that exact certificate-bound
output; empty output, status 0, a different path, localized or mixed output,
and other statuses remain blocked. This command-line result does not claim
current kernel-keyring visibility or module acceptance; those are distinct
runtime facts. `modinfo` signer/key identifiers are metadata and are not
accepted as cryptographic proof. An unchanged module is not signed again only
when its existing signature is already cryptographically valid for the
configured enrolled certificate. A pre-existing malformed, invalid, or
differently signed module is refused instead of receiving another appended
signature.

This verification establishes exact-payload signature validity plus configured
certificate enrollment. It does not by itself claim that the running kernel
accepted the module under its current enforcement policy; that fact requires a
safe, authorized load of the same exact installed bytes. If the private key is
not readable by the invoking user, plain `make` uses `sudo` only for
`kmodsign`. The official `make test` build stage is noninteractive and
therefore uses `sudo -n`; unavailable authorization, missing signing tools/key
material, or an indeterminate EFI Secure Boot state is BLOCKED rather than
silently producing an unloadable qualification module. The warning-only W=1/W=2
artifacts are never loaded and are not signed by this hook.

When non-root `kmodsign` runs through sudo, it can replace the module inode and
leave the build output root-owned. After signature verification, sign mode
restores the artifact to the invoking build user's ownership so the Makefile
can set its final mode and a later incremental build can replace it. This also
repairs a valid already-signed build artifact left root-owned by an interrupted
earlier build. Verification-only mode never changes module ownership.

## Packaging

DKMS uses `AUTOINSTALL="no"`. `make install` is an admission operation rather
than a build operation: it requires an exact five-stage PASS qualification
report whose recorded kernel release is the target running kernel, clean
embedded source provenance, matching userspace/oracle/module SHA-256 values,
current-kernel headers and matching module vermagic. Installed qualification
metadata is rechecked against the exact installed CLI, oracle and both module
copies, so a rewritten local binary manifest cannot rebaseline a different
qualified artifact. On Secure Boot hosts packaging verifies the already-
qualified module signature and never signs or otherwise changes those bytes.

DKMS still performs a current-kernel compatibility build, but that rebuild is
not promoted as the qualified image. After DKMS succeeds, packaging replaces
the DKMS-installed image with the byte-exact qualified `dm-swapz.ko`, hashes it
before and after `depmod`, and requires `modinfo -n dm_swapz` to resolve to
that owned path. Install and both rollback paths normalize a single DKMS-built
compressed or uncompressed candidate before restoring the exact uncompressed
qualified image, so rollback cannot leave a second module candidate behind.
The qualified module digest, the retained package copy, and the module selected
for a later checked load therefore identify the same bytes.

Install/upgrade is serialized and transactional. An identical verified install
is a no-op. A non-identical upgrade refuses a loaded swapz module or existing
swapz mapper, stages replacement files before mutation and durably journals
the private rollback snapshot and each destructive transition. Upgrade revokes
the existing activation entry points before touching DKMS. It publishes the
activation-capable CLI atomically only after the qualified module resolves,
all non-CLI helpers/units are installed and systemd reload has succeeded.
Failure restores the previous verified package with DKMS state, the exact
qualified module, depmod and module-path resolution all proven before the CLI
is restored; rollback re-queries the exact current-kernel DKMS installed state
after rebuilding it rather than trusting the install command's exit status; changed rollback snapshots are refused, and incomplete recovery
keeps activation revoked and later package operations blocked. DKMS status
query failures are uncertainty and block mutation rather than being interpreted
as an empty registration. Abrupt process or host termination can retain a
journal requiring explicit recovery; the installer never guesses that a
partial transaction succeeded.

Uninstall is transactional too. It refuses active/enabled deployment state,
active mapper/module use, recovery ownership, or any ownership/digest mismatch,
then makes and fsyncs a private exact rollback snapshot plus a hash manifest
before deleting anything. Snapshot bytes and their directory entries are
fsynced at the initial `prepared` checkpoint. The private mode-0600 journal
is created exclusively without following a stale temporary pathname, its mode
is applied before its contents are fsynced, and rollback rejects substituted
journal or rollback-directory metadata. Ambiguous stale journal temporaries are
retained for recovery rather than overwritten or blindly cleaned up. Later phase updates recheck every
snapshot hash and metadata record, then fsync the new journal and transaction
directory without repeating fsyncs of the unchanged snapshot. Activation entry
points are removed first; DKMS, source/module removal, depmod and daemon-reload
are journaled destructive transitions. A failure restores the exact source,
DKMS registration, qualified module and package files, with `swapzctl` restored
atomically only after depmod, the remaining files and systemd reload are valid.
An interrupted or failed
rollback retains its independently verifiable transaction state and blocks all
later package operations rather than permitting uncertain activation.

Packaging never unloads a module, removes a mapper, or calls swapon/swapoff.
Production uses the fixed `/usr/local` prefix, trusted system executables,
root-owned package files, a dedicated root-owned mode-0700 transaction
directory outside shared temporary paths, and symlink/path substitution checks.
The shared package lock directory must be trusted and non-writable, and the
single-link mode-0600 lock file must retain the same inode and metadata across
open and nonblocking flock; packaging never chmods an unsafe pre-existing lock
into acceptance.
Existing package source/destination metadata and every current-kernel module
candidate are part of admission, so a stray compressed or uncompressed
`dm-swapz.ko` cannot be silently overwritten. Distribution command symlinks
are accepted only when their canonical executable is root-owned, non-writable
and within trusted system executable directories.

A kernel upgrade is deliberately not automatic deployment: because
`AUTOINSTALL="no"` is retained, the new kernel needs matching headers, a
qualified module for that kernel, and an explicit admission/install cycle.
Additional hermetic regressions deliberately replace the package lock pathname
between descriptor open and flock, reject mode-tampered rollback snapshots
on interrupted upgrade, treat a failing uninstall DKMS status query as
uncertainty, and retain a verifiable `rollback-incomplete` upgrade journal
when the terminal rollback checkpoint cannot be persisted. These checks do
not emulate power loss or prove real-host DKMS registration, kernel module
loading, Secure Boot enforcement or signer acceptance by the running kernel.

Rootless packaging tests exercise repeated install/uninstall, exact-kernel
qualification binding, missing headers, cryptographic signature/enrollment
mismatch, lock/path substitution, foreign and tampered artifacts (including
manifest-rebase attempts), each install/upgrade and uninstall mutation
checkpoint, failed DKMS-state inspection, depmod and daemon-reload, active
upgrade/uninstall refusal, rollback module-resolution ordering, signal rollback,
journaled snapshot tampering, interrupted rollback retention and cleanup. They
are hermetic package contract evidence, not system-install or target-kernel
module-acceptance qualification.

## Removed build paths

The standalone memory-only kernel smoke module and retired C++ model are intentionally absent. They were not shipped or part of the official qualification. Historical reproduction belongs in Git history, not a second current build path.


## Report publication

The test runner keeps `test_results.json` unchanged until qualification
work stops. It then replaces that file and attempts a report-only `[skip ci]`,
non-force commit directly to `main`. If a push fails after `origin/main`
advances, a bounded retry may parent the new remote head only if it descends
from the tested source. Before doing so, it refuses to replace a published
qualification report whose tested source is a descendant of this run's tested
source. The report's `source_sha`/`tested_commit_sha` still identify the tested
source, not the concurrent descendant; the latter is not qualified.

After a successful remote push, the runner refreshes local `main` and the index
when safe. After a concurrent advance it may also refresh the otherwise-clean
checkout to the published descendant; otherwise it reports remote-only
synchronization. Reconcile and verify local and remote `main` before starting
new work.


Because the root `test_results.json` is generated evidence, its local
working-tree/index state is excluded from the privileged loaded-source
cleanliness gate. No other tracked path is exempt. The report is atomically
replaced only after qualification stops; remote publication and safe local
synchronization are separate checks.


Loaded `make test` helpers execute privileged device work through `sudo`, but
Git inspection inside those helpers is read-only and runs with
`GIT_OPTIONAL_LOCKS=0`. The privileged phase must not refresh or replace
`.git/index`; repository/index ownership remains with the invoking operator.
