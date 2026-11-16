# Round 017 Agent 3 — guarded owned-RAM Phase A readback evidence

**Evidence status:** SOURCE_READY; LOADED_STORED_ENTRY=NOT_RUN;
4096_READBACK=NOT_RUN; PHASE_A=BLOCKED; PHASE_B_RAW=DISABLED;
DIRECT_COMPRESSED=DISABLED.

Task and official opening: [issue #134](https://github.com/k1moradi/swapz/issues/134#issuecomment-6913107360),
task publication `fe7396fe64bf51724e7b70e7a67d58539fdb815e`.
Engineering integration baseline `b26c42d1ea7524a78747eafc431e35a1d1e94d35`.
This worker prepared changes from the **actual subsequent remote main**
`32c5bb61ca1f7a468fc631bf06e8f21792ad0a3c`, preserving all newer
committed work. The final published commit and GitHub first-parent SHA are
recorded in the issue's Agent 3 `REPORT_READY`; see the remote main history.

## Production-source audit and scope

Source blob `2d60ec8d6b9db47dc4708d0ba12162ac9d7367a5` of
`src/kernel/dm-target.c` is **unchanged**. In `swapz_map()`, each per-BIO
descriptor begins UNKNOWN and clears `origin_commit_counted` before the
optional checked producer origin. The positive predicate requires genuine
`bio_is_zswap_stored_writeback()`, `REQ_OP_WRITE`, exactly one 4096-byte BIO
and `SWAPZ_SECTORS`; the pinned producer separately requires `REQ_SWAP`
and genuine stored-entry identity. A reject or requeue is checked before
admission counting. The ordered-owner helper checks positive origin and the
once-only bit, sets the bit before counting, and is called only in four
successful foreground-authority paths: synchronous compressed, detached
asynchronous, dedicated RAW and zero-elided. Lower callback, GC and READ do
not create this foreground count. The upper `swapz_complete()` checks
terminal failure and accounts `upper_write_completed_ok/err` separately,
so committed foreground authority must not be described as a guaranteed
successful upper acknowledgment.

No production policy or encoding change was needed: the existing RAW
representation is the original uncompressed 4096-byte page. No direct
zswap compressed transport, CRC32/CRC32C handoff, RAW bypass, memory
pressure controller, module/kernel/device mutation or additional hot-path
allocation/lock was introduced.

## New executable read-only guard and matched CI

`tests/runtime/native/zswap-origin-owned-ram-qualification.py` is an
executable stdlib-only rootless gate with `--self-test`,
`--preflight` and `--offline-compare` modes. Preflight is deliberately
non-authorizing: it checks whether basic read-only boot and module
indicators exist and refuses with `ENVIRONMENT_NOT_QUALIFIED` (exit 2)
because no independent attestation of the **modified-and-booted** Linux
source, exact loaded module SHA/vermagic/source build, exclusive owner-only
RAM backing, legal owner permission, bounded pressure/deadline and
guaranteed cleanup exists here. There is **no mutating execution backend**;
even a fabricated all-positive manifest cannot enable one. It never calls
`dmsetup`, `modprobe`, `swapon`, `swapoff`, `mkswap`, loop/null_blk, GC,
cgroups or a pressure workload.

The offline comparator requires two individually bounded, nofollow
regular-file DM status snapshots with genuine exported fields:
`origin_carrier_compiled=1`,
`verified_zswap_origin_admitted`,
`foreground_committed_verified_zswap_writeback`,
`upper_write_completed_ok/err`,
`endio_write_seen_err` and `endio_write_forced_err`.
It rejects missing/duplicate/noncanonical/overflowing fields, counter
regression, not-exactly-one admitted/committed delta, absent upper success,
new upper/endio errors, missing original page SHA-256, and any byte
mismatch or incorrect page length. The original 4096-byte page is
SHA-256-checked separately and compared to the full recovered page.
Caller-supplied snapshots/bytes can be fabricated, so even a passing
offline consistency comparison returns **exit 2**,
`first_cause=offline_samples_cannot_prove_loaded_origin`, never a loaded
PASS. No host paths, identity, contents or arbitrary child diagnostics are
printed in refusal output.

The existing `.github/workflows/phase-a-zswap-origin-prototype.yml`
now watches this source and executes all self-tests plus an expected,
fail-closed **exit-2** preflight before staged modified-Linux object/module
Kbuild. Unexpected zero exit, missing NOT_RUN labels, absent refusal,
unexpected status or test failure makes the CI step fail. The previous
real pinned build (`CC=gcc`, W=1, y/n effective CONFIG_ZSWAP,
generated headers, exact changed Linux source/blob SHA, actual compiled
objects, `Module.symvers`, ELF64 real linked `dm-swapz.ko`,
modinfo/vermagic, source-build-info, and binary carrier marker
`origin_carrier_compiled=1`) is byte-for-byte unchanged.
The existing `tests/runtime/native/pinned-linux-origin-paired-module-test.py`
retains its full source/blob/config/compiler/hash/ELF/marking checks,
and adds two fail-closed mutations ensuring the new test and its trigger
cannot be silently omitted. This is **not** W=2 or an actual Round 017
hosted build; any W=2 gate must be run separately if required.

## Locally executed commands, exact exits

- `python3 -B zswap-origin-owned-ram-qualification.py --self-test`:
  **exit 0; Ran 25 tests in 0.015s; OK.**
- `python3 -m py_compile zswap-origin-owned-ram-qualification.py`:
  **exit 0**.
- `python3 -B zswap-origin-owned-ram-qualification.py --preflight`:
  **exit 2, expected safe refusal;
  first_cause=matched_module_not_loaded;
  LOADED_STORED_ENTRY=NOT_RUN; 4096_READBACK=NOT_RUN**.
- `bash -n owned-ram-ci-step.sh`: **exit 0**, where the file is the
  actual new CI-step Bash body copied into a local scratch fixture.
- `RUNNER_TEMP=... bash owned-ram-ci-step.sh` from the disposable
  local fixture: **exit 0**, executing self-tests and correctly accepting
  only the expected preflight exit 2; no kernel/device commands.
- `--offline-compare` with independently supplied deterministic
  4096-byte original/readback fixtures and consistent counters:
  **exit 2, first_cause=offline_samples_cannot_prove_loaded_origin**.
  Changed `endio_write_seen_err` before/after delta:
  **exit 2, first_cause=unexpected_error_delta**. Truncated READ and
  malformed/duplicate status controls are also in the 25-case suite.
- `git hash-object zswap-origin-owned-ram-qualification.py`:
  `408362b82ca8c7b1d66153ceaa863d4f6ed2cf65`, identical to the
  created GitHub source blob.
- Local new-file added-line whitespace check had no whitespace diagnostics.
  Whole checkout `git diff --check` is **NOT_RUN**.

**Detected and corrected source-bound first mismatch:** the frozen
production DM source has `ctx->io_failures` internally but does NOT
export `io_failures=` in its status line. Initial local harness used
this nonexistent field; before publication it was corrected to the
actual exported `endio_write_seen_err` and
`endio_write_forced_err` fields, adding the forced-error negative
test. Final 25-case suite and source blob above are the corrected
version, not the initial candidate.

## External and remaining qualification

Historical hosted matched-Linux builds, **not** Round 017:
[run #43834985929](https://github.com/k1moradi/swapz/actions/runs/43834985929)
completed success for `f716a5162a098742ec4bf7ab17b6a6a977bb75d4`,
and [run #43842886913](https://github.com/k1moradi/swapz/actions/runs/43842886913)
completed success for `b26c42d1ea7524a78747eafc431e35a1d1e94d35`.
These are source-linked build successes, **not** a booted modified Linux,
loaded module, real zswap stored-page positive, kernel-backed byte-read,
physical device or owner-authorized RAM run. The full existing native
suite, complete hosted matched-profile build on this new commit, GCC/Clang
full kernel module W=1/W=2, KUnit TAP, loaded stored-entry WRITE, actual
4096-byte swap-in and owner-bound teardown all remain **NOT_RUN** in this
worker session. The local container contains no source checkout; HTTPS
`git ls-remote` fails `Could not resolve host: github.com` (exit 128),
so the requested literal `git fetch`/local-main operations were not
available. GitHub connector can create a normal descendant commit and
perform expected-head guarded non-force main update; that publication
and exact resulting remote SHA are reported separately.

**First runtime refusal is an expected safety boundary, not a positive test.
Phase A BLOCKED; Phase B RAW bypass DISABLED; direct compressed handoff DISABLED.**
