# Build and Install

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWAPSPACE2` is the only real backing format. `SWZ` names the internal extent-packing design, not a partition format; serialized legacy extent metadata is fixture-only compatibility, never production media metadata.

**Three-tier test policy:** `make fast_test` is development-only and never qualifies or publishes `test_results.json`; `make test` runs the algorithm/RAM path and returns INCOMPLETE (nonzero) until physical source/run/target admission is qualified; `make test_full` retains all rootless DKMS/systemd integration and RAM qualification. Both privileged tiers report BLOCKED (nonzero) if noninteractive privilege is unavailable. RAM/integration PASS cannot certify physical storage or cold-boot production acceptance. Private scripts and CI jobs are implementation details, not operator interfaces.

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

The generated `build/source-build-info.h` stamps the module and userspace
build with `SWAPZ_BUILD_SOURCE_SHA` and the numeric/string
`SWAPZ_BUILD_SOURCE_CLEAN` flags. At the root of a tracked checkout, the
source SHA selects the latest commit touching any path other than the root
`test_results.json`. Publishing a report-only descendant therefore does not
relabel the source or previously qualified artifacts; a later real source
commit advances the identity. The clean flag is 1 only with a resolved source
SHA and no modified or untracked inputs in the checked kernel, userspace,
Makefile and packaging paths. Unknown source history yields `unknown` and 0.
A copied mock inside ignored `build/` has no clean provenance merely by
inheritance; a test that needs source-bound qualification must create its own
tracked fixture checkout. The Make-interface incremental fixture uses an
isolated synthetic `main` checkout, a tracked `test_results.json`, and a local
bare `origin`. A fixture-only Git shim reports the canonical origin identity
while keeping fetch and report publication on that bare remote. The loaded
mock binds evidence to the latest non-report source commit because earlier
fixture invocations can publish report-only commits. The report's
`source_sha` and `tested_commit_sha` remain the official runner's exact
tested-source identifiers, not the SHA of its report-publication commit.

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
exact-kernel algorithm/RAM qualification and `make test_full` integration
evidence on the actual host, then separate authorized physical acceptance
and an explicit qualified install; `AUTOINSTALL="no"` remains in force. A defined
kernel compatibility range and its oldest/current compile matrix require a
separate project policy decision before they can be claimed.

## Root Make API

Exactly six commands are public:

- `make`: build product artifacts without loading them.
- `make install`: admit the exact artifacts with a five-stage `make test_full` RAM/integration PASS and matching provenance; this is admission-only, not physical or boot acceptance, and it does not rebuild, re-sign, load the module, create a mapper, or activate swap.
- `make uninstall`: remove only the matching owned installation.
- `make test`: source/native, warning and loaded RAM algorithm tests;
  rootless package/DKMS/systemd integration is excluded. Result remains
  INCOMPLETE until physical source/run/target admission is qualified.
- `make test_full`: the prior full rootless integration plus RAM benchmark
  suite; PASS does not certify physical or boot acceptance.

An ordinary `make test` persists private owner-only completed rootless and
kernel-warning checkpoints after the build. `make test RESUME=1` may reuse
only same-source, same-host, same-kernel, same-KDIR and same-rebuilt-artifact
PASS checkpoints, then reruns the loaded stage from its privileged preflight.
The parent strips its resume selector from child test environments, so nested
test fixtures cannot inherit this shortcut. This opt-in is **development-only**:
reused stages display REUSED, the complete run returns INCOMPLETE/nonzero and
never authorizes a physical qualification. A previous run without checkpoints
cannot be resumed from console rows. Use plain `make test` for fresh evidence;
`make test_full` does not accept the resume selector.
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

Build, signature, CI and native checks establish only their own evidence
level; they never admit a production target. Use the
[evidence levels](testing_standards.md#evidence-levels),
[exact-source release rules](testing_standards.md#qualification-discovery-and-release-evidence-integrity),
[first-failure triage](README.md#diagnose-the-first-record) and
[host-scoped authority](AGENT_CONTEXT.md#standing-owner-authorization) before
interpreting any PASS or proceeding to a device operation.

### Legacy synthetic formatter descriptor admission evidence

Public `swapzctl format` rejects raw-device formatting before opening any
partition. The assertions in this section describe only a retired synthetic
formatter fixture: even when its mock SWZ header makes simulated formatting
idempotent, the fixture requires a fresh returned-descriptor
`fcntl(F_GETFL)` access-mode check reporting `O_RDWR` after its final
opened-target identity revalidation. Its refusal is a read-only diagnosis:
`O_RDONLY` or `O_WRONLY` returns `EBADF`, a failed query retains the
originating errno, and neither case writes, syncs, or replaces the header.
The independent final prewrite check remains a synthetic fixture assertion,
not authorization to write an ordinary swap partition header.
Rootless tests with fake block descriptors establish these control-flow
conditions and the `O_EXCL` flags requested by the opener; they cannot
establish loaded-kernel block holder/mount/swapon exclusion or distinguish
a physically substituted card in the same reader.

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
published commits. The public testing tiers are `make fast_test`
(nonqualifying development), `make test` (algorithm/RAM with physical
admission currently INCOMPLETE), and `make test_full` (RAM plus integration).

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
substitutes for owner-run `make test_full` RAM/integration evidence
or separately authorized real-physical acceptance.

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


### Prepublication malformed-extent regression (rootless)

The exact production-C `mapping-authority` and `raw-discard` fixtures
fault-inject a formerly valid logical mapping whose old physical extent now
crosses a 1MiB segment boundary or exceeds physical capacity. Range
prevalidation, direct page DISCARD, RAW completion and compressed completion
must return the original fail-closed errno before reducing old physical
reference counts or changing authoritative generations. A multi-page range
must retain its healthy first mapping and unrelated survivor when its later
page is malformed or its generation overflows. The interrupted write's newly
reserved physical span remains quarantined; rejection must not publish it.
The tests must identify logical ranges, expected generations/references,
corruption classes, returned errnos and whether invalidation was prevented,
without printing physical identities. These are deterministic in-memory
rootless checks, not evidence of loaded Linux swap or real-media DISCARD/GC
correctness. Loaded high-occupancy qualification must additionally verify
serialized lower-write completion, no shared-extent early release, and
stable readback through DISCARD, segment reuse and GC churn.

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
use different exit statuses for the exact
`<certificate path> is already enrolled` response: version 0.7.2 uses status
1, while newer upstream versions use status 0. The hook accepts either status
only with that exact certificate-bound output; status alone, empty output, a
different path, localized or mixed output, and other statuses remain blocked.
This command-line result does not claim
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

Before running source-bound stages, `make test` and `make test_full` acquire a
checkout-local lock, verify the canonical `main` remote, fetch without prompts,
and fast-forward only a clean local main. If the fetched non-report source
changes after the invoking Make parsed its files, the runner restarts the same
Make goal once with the lock and jobserver descriptors preserved. A second
source advance, local-only commit, divergence, changed tracked source, or
untracked path collision blocks the stages. Dirty `test_results.json` bytes
are preserved privately under `.git` before that single generated report path
is restored for the fast-forward.

The test runner keeps `test_results.json` unchanged until qualification
work stops. It then replaces that file and attempts a report-only `[skip ci]`,
non-force commit directly to `main`. The Git result printed after an
authenticated successful upload includes the full 40-character report commit
ID and a permanent `/blob/<report-commit>/test_results.json` link.
When concurrent publication archives a delayed host result while preserving
a stronger canonical report, the link names the intermediate archive commit,
not the restored `main` file. For every received `make test` transcript,
first read the full `Tested Git commit` SHA, then use the full
`report_commit` SHA from `SYNCED_GIT` or `ARCHIVED_GIT` to retrieve that
exact revision of `test_results.json`. Validate that the retrieved report's
`source_sha` and `tested_commit_sha` match the tested source. A
`main/test_results.json` permalink is not historical evidence for a
different source or an archived run. Successful archival is publication, not
a failed upload, and must not overwrite a newer canonical report.
Upload failure names a safe Git failure
category and retains the local report without claiming GitHub publication.
Private raw diagnostics never enter `test_results.json`; only strictly
validated bounded source-owned failure counters may be included with their
explicit evidence scope. If a push fails after `origin/main`
advances, a bounded retry may parent the new remote head only if it descends
from the tested source. Before doing so, it refuses to replace a published
qualification report whose tested source is a descendant of this run's tested
source. The report's `source_sha`/`tested_commit_sha` still identify the tested
source, not the concurrent descendant; the latter is not qualified.

After a successful remote push, the runner refreshes local `main` and the index
when safe. After a concurrent advance it may also refresh the otherwise-clean
checkout to the published descendant. After report publication it performs a
bounded fetch and checked fast-forward when local `main` is a clean ancestor;
it never rewrites or pushes a source commit. Otherwise it reports the exact
synchronization refusal and retains the local evidence. Verify local and remote
`main` before starting new work.


Because the root `test_results.json` is generated evidence, its local
working-tree/index state is excluded from the privileged loaded-source
cleanliness gate. No other tracked path is exempt. The report is atomically
replaced only after qualification stops; remote publication and safe local
synchronization are separate checks.


Loaded `make test` helpers execute privileged device work through `sudo`, but
Git inspection inside those helpers is read-only and runs with
`GIT_OPTIONAL_LOCKS=0`. The privileged phase must not refresh or replace
`.git/index`; repository/index ownership remains with the invoking operator.
