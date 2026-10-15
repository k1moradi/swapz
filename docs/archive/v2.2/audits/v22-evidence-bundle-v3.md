# V2.2 V3 sidecar-aware evidence bundle — offline schema v2

This is a **self-consistency check**, not a trusted collector, signed
attestation, source authentication, kernel drain proof, or backing-release
authorization. Source-only tests never access real devices or exercise swap.

## Format

The existing `swapz-v22-evidence-bundle-v1` checker remains
unchanged and must reject every V3 observation. Use the separate
`tests/runtime/v22-evidence-bundle-v3.py` command to verify a
sidecar-aware bundle.

The manifest is JSON containing exactly:

```text
schema, source_revision, session_id, collector_id, lower_device_id,
backend, profile, evidence, observations_sha256, runs
```

Its `schema` must equal
`swapz-v22-evidence-bundle-v2`.
Source revision is one 40-character lowercase hexadecimal SHA, and the
observations SHA-256 is lowercase 64-character hex. All other identity
fields must be bounded, nonempty ASCII fields valid under the existing
bundle policy. Evidence may be synthetic, kernel, or physical, but this
label is **self-asserted**, never authenticated. The manifest contains
one ordered run inventory entry per exact LF-terminated JSONL record.

Each run entry has exactly the old v1 run fields:

```text
run_id, line_sha256, source_revision, session_id, collector_id,
lower_device_id, backend, profile, evidence
```

and additionally these three required fields:

- `read_latency_sidecar`: unique exact same-directory
  basename from its V3 JSONL record, ending in `.latbin`
- `read_latency_sha256`: original-byte SHA-256 of that sidecar,
  identical to the V3 JSONL record's digest
- `read_latency_bytes`: positive exact integral sidecar size
  in bytes, divisible by 16, matching the actual input descriptor

Each run entry's session/collector/device/backend/profile/evidence/source
binding must exactly match its enclosing manifest. Each JSONL record must
contain exactly a valid `swapz-drain-observation-v3` object,
and its source/backend/profile/evidence/run ID must match the per-run
manifest entries. Legacy V1 and V2 rows, mixed schema data, unbound sidecar
filenames, repeated run IDs, reused filenames, inconsistent record hashes,
duplicate JSON keys, and silent additions of authorization fields are
rejected. Reordering run entries also invalidates the binding.

## Input ownership and quotas

The observation JSONL and manifest must have **the same exact parent
directory**, and their filenames must be distinct, bounded single
components. One retained directory descriptor is opened with
`O_DIRECTORY | O_NOFOLLOW` before reading either.
The two metadata files are pinned regular files with at most one hard
link, no symlink final component, and size limits of 2 MiB JSONL and
256 KiB manifest. Their descriptor identity is verified after reading.

Every sidecar is opened relative to the **same directory descriptor**.
The existing V3 verifier checks no symlink, single hardlink,
regular-file type, exact strictly increasing positive nanosecond/count
RLE pairs, recomputed nearest-rank p99, claimed read count, actual size,
original byte digest and before/after descriptor metadata.

Each sidecar may carry up to 10 million reads, at most 160 MB of binary
records, and one invocation may process at most 512 MiB of sidecars.
Binary RLE pairs are 16 bytes, big-endian unsigned 64-bit values,
without header/padding. The sidecar parser uses bounded 64-KiB chunks.
A hash match proves only local byte agreement, not an independent
signature or event occurrence.

This does not exclude a host-root actor, prove source authenticity,
prevent all hostile in-place mutation races, or authenticate any kernel
or physical devices. The verifier **never grants** backing release,
production qualification, physical selection, or kernel-drain authority.

## Usage

```bash
python3 -B tests/runtime/v22-evidence-bundle-v3.py \
  --observations /private/test-evidence/observations.jsonl \
  --manifest /private/test-evidence/manifest.json

python3 -B tests/runtime/v22-evidence-bundle-v3-test.py -v
```

Successful output records exact verified sidecar names, counts,
p99 values, original-byte hashes, byte sizes, and bound run/manifest
identities. It explicitly returns all authorization flags as false,
and V2.2 strategy/batch winner as UNDETERMINED.

A future authenticated measurement path still needs an independent
collector trust root, signed producer artifact, kernel/device identity
and postcondition proofs, and authorized disposable-device tests.
This format is an input integrity prerequisite, **not** that qualification.
