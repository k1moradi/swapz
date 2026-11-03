# Historical draft prompt: independent review for physical swap testing

**Status: historical evidence for the previous computer.** This prompt was
prepared for the 2026-11-02 one-use physical-swap review process. It is not a
current approval gate and must not be refreshed or sent as a requirement for
the dedicated SD-card mission. Standing authorization and current technical
gates are canonical in [AGENT_CONTEXT.md](../AGENT_CONTEXT.md).

At the time, this was a copyable request for an external, independent code and
safety reviewer. It was a draft only: it was not an approval, did not authorize
physical writes, and did not replace the signed review gate then in effect. The
historical workflow paired it with local ignored files under
`build/physical-swap-review/` containing computer- and device-specific review
state.

The source and artifact values below were current on 2026-11-02 and are
intentionally preserved rather than refreshed. The review questions remain
useful as a record of what was checked, not as current operator instructions.

## Prompt to send

You are being asked to perform an independent, read-only safety and correctness
review of the code path intended for one bounded byte-exact round trip through
an explicitly selected real Linux swap partition.

Do not run swapoff, swapon, the physical helper, dmsetup, a formatter, or any
command that writes to a block device. Do not modify the repository or claim
that a physical test has passed. Do not review or suggest optimization work;
the scope is correctness, recovery, and safe physical-test admission.

### Pinned review context

- Repository: https://github.com/k1moradi/swapz
- Production/code source to review: fb1f6f12bf24a08ebcf1f1f2cfd88ca83bf508b9
- Current main when this prompt was prepared: 0aa318287caf96339b443f01ec8deee438fc745c
- The commits after the pinned source were report publications changing only
  test_results.json at preparation time. Verify this before relying on it.
- Physical helper:
  tests/tools/physical-swap-probe.py
- Expected helper SHA-256:
  372a73a5bc90176d77efa0662f2820cfa9379df089010e818ebbe63de91206fb
- The owner’s current packet supplies the selected partition identity,
  latest read-only preflight, source reports, and the artifact hashes. Treat
  those values as stale if they do not match the current read-only plan.

Two distinct same-host, exact-source make test reports were published at
c835377af9958c058f2c0df1e0d08399b7a41123 and
0aa318287caf96339b443f01ec8deee438fc745c. Both report source
fb1f6f12bf24a08ebcf1f1f2cfd88ca83bf508b9 and all five qualification stages
passed. Their device testing used owned RAM-backed null_blk. This evidence
does not test physical media and must not be treated as physical round-trip
evidence.

### Files and behavior to inspect

Inspect the pinned source and the complete relevant call paths, including:

- docs/testing_standards.md, physical backing and physical admission section
- docs/ROADMAP.md, release gates and owner-requested physical smoke section
- tests/tools/physical-swap-probe.py, especially plan, run, recover, target
  identity, signed-review validation, artifact snapshots, header backup,
  writes, cleanup, and swap restoration
- tests/runtime/native/physical-swap-probe-test.py and the physical-admission
  contracts in tests/runtime/native/source-contract-test.py
- tests/tools/run-tests.py, report identity/history checks and qualified
  artifact digests
- src/userspace/swapzctl.c and src/kernel/superblock.h, formatter and media
  header contract
- src/kernel/dm-target.c, physical-backing opt-in, header validation,
  reserved block-zero behavior, and rejection of physical fault injection
- tests/tools/device-roundtrip.c, the exact default oracle write/read range,
  byte verification, and its restrictions to the helper-owned mapper

The helper is private and must remain outside make test. Its selected-device
path is deliberately repeated exactly as /dev/disk/by-uuid/... . The plan and
run gates bind an active zero-used swap partition, stable block identity,
PARTUUID, size, no mounts or holders, a root filesystem outside the selected
partition, exact current x86_64 source reports, and exact artifact bytes.

The intended sequence saves and fsyncs the original 4 KiB header in a
root-owned mode-0700 state directory outside the repository and selected
device; snapshots the reviewed formatter, module, and oracle; rechecks target
identity and swap state; disables only the selected swap partition; clears
and formats block zero; loads the module with physical backing explicitly
enabled; creates a helper-owned 16 MiB device-mapper target; runs the
byte-exact oracle; then removes only the UUID-owned mapper, restores and
verifies the original header, and re-enables only the original swap partition
with its priority. The swapz mapper must never be activated as system swap.
Confirm each statement against the pinned code rather than assuming this
summary is correct.

### Review questions

1. Can any path select or write a device other than the exactly confirmed
   partition, or confuse a stale UUID link, changed major:minor, changed
   PARTUUID, changed size, mapper holder, mounted device, or root-device
   dependency for the intended target?
2. Are the report/source gates sound against stale reports, report replay,
   duplicate report content, a changed source after qualification, remote
   rewrites, host mismatch, and artifact replacement? Do not treat two
   publications alone as cryptographic proof of two independent executions.
3. Does the detached SSH signature authenticate the exact unambiguous JSON
   record, a reviewer other than the operator, the exact source/helper/device,
   and the three qualified artifact digests? Can an unsigned identity,
   operator-controlled trust path, symlink, duplicate JSON key, or mode/owner
   mistake bypass the trust gate?
4. Before every destructive operation, is device identity tied to the actual
   opened block-device descriptor? Identify any check/use race between path
   resolution, header reads/writes, formatter execution, module setup, and
   mapper creation.
5. Is the original header durably saved before swapoff or any write? Are the
   backup, state transitions, fsyncs, and saved identities sufficient across
   process termination, kernel panic, or power loss?
6. Walk every interruption point: before/during/after swapoff; between
   swapoff and stage persistence; during block-zero clearing; while formatting;
   after formatting but before its digest is persisted; during module/mapper
   setup; during the oracle; and during cleanup/recovery. Does recovery restore
   only a recognized exact state, refuse unknown bytes, avoid unsafe forced
   removal, and re-enable only the original swap partition? State any
   manual-recovery-only window clearly.
7. Does the formatter preserve its zero-block refusal and write only its
   intended header? Does the kernel reject missing/mismatched headers,
   reserve data block zero, keep block zero out of all data and discard paths,
   and prohibit physical fault injection?
8. Does the oracle really perform a byte-exact round trip within the mapped
   16 MiB region, and are its write bounds, direct-I/O alignment, verification,
   and error handling correct for this physical backing?
9. Do the rootless tests cover the critical positive and negative state
   transitions, including device substitution, stale/missing identity,
   report replay and host mismatch, signature/trust failures, artifact
   substitution, unknown recovery headers, and swap restoration? List safety
   gaps that remain untested.

### Required review output

Return one of:

- BLOCKED: specific evidence or required information is missing.
- REJECT: one or more safety/correctness blockers exist.
- APPROVE FOR ONE BOUNDED BYTE-EXACT CORRECTNESS SMOKE: no blockers found
  within this scope.

For every finding, give severity, exact file/function (and line if verified),
the triggering state or failure sequence, concrete impact, and the smallest
corrective action or test needed. Separate verified behavior from inference.
State explicitly whether the review is code-only or also covers the attached
device-specific packet. Do not make performance, endurance, or real-media
claims.

An approval is usable by the project only if you are genuinely independent of
the operator and can sign the final exact JSON review record with your own
authenticated SSH identity. The signature namespace is
swapz-physical-review. The public key must be independently provisioned in the
owner’s root-controlled /etc/swapz/physical-review.allowed_signers before the
helper will accept it. If you cannot satisfy those identity and signature
requirements, return findings and a recommendation only; do not invent an
identity, signature, or trust entry. Your review does not itself execute or
authorize a device write.
