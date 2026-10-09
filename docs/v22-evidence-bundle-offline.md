# V2.2 offline measurement bundle integrity gate

**Status: rootless data-consistency check only.** No privileged runtime,
device I/O, swap transitions, physical throughput data, kernel drain,
or backing cleanup is involved.

`tests/runtime/v22-evidence-bundle-check.py` checks one exact JSONL artifact
and a separately supplied manifest. The existing
`v22-drain-plateau-analyze.py` checks each observation's throughput
inputs and exact-value latency histogram; the bundle checker reuses its
strict row validation without invoking any device or benchmark.

## Usage

```sh
python3 -B tests/runtime/v22-evidence-bundle-check.py \
  --observations /path/to/offline-observations.jsonl \
  --manifest /path/to/offline-bundle-manifest.json
```

The CLI is **read-only**. It exits nonzero on a malformed manifest, missing
input, symlink, oversized file, duplicate JSON key, corrupt row, mismatched
hash, record mismatch or conflicting identity. It prints JSON on success
with `physical_selection_authorized: false`,
`authenticated_collector: false`, `kernel_drain_proved: false`,
`independent_device_identity_proved: false`, and
`backing_release_authorized: false`. These are hard-coded negative
safety statements, not conditional passes.

## Manifest schema: `swapz-v22-evidence-bundle-v1`

The manifest must contain **exactly** these top-level properties:

| Property | Format / meaning |
| --- | --- |
| `schema` | `swapz-v22-evidence-bundle-v1` |
| `source_revision` | Exactly 40 lowercase hexadecimal characters; a **claim**, not Git verification |
| `session_id` | 1–128 printable restricted ASCII identity characters |
| `collector_id` | 1–128 restricted ASCII identity characters |
| `lower_device_id` | 1–128 restricted ASCII identity characters; a **claim**, not independently observed device identity |
| `backend`, `profile` | Restricted identities; must match each JSONL observation |
| `evidence` | `synthetic`, `kernel`, or `physical`; remains self-reported |
| `observations_sha256` | Exact SHA-256 of the original complete JSONL file |
| `runs` | Ordered nonempty list of entries, exactly one per JSONL row |

Each ordered `runs` entry must contain exactly `run_id`,
`line_sha256`, and all seven fields
`source_revision,session_id,collector_id,lower_device_id,backend,profile,evidence`.
Every entry must exactly match the corresponding top-level field.
`line_sha256` is SHA-256 of the **original row bytes including its LF**
(not of reserialized JSON). All run IDs are unique. Every record must
match the existing strict plateau-observation schema and the record's
`run_id`, `source_revision`, `backend`, `profile` and `evidence`
must match manifest claims. Labelled `kernel` and `physical`
observations must use the existing V2 exact-latency distribution
schema; legacy V1 self-reported p99 cannot enter a measured bundle.
Synthetic V1 data may still demonstrate syntax but never qualify
real performance.

The observations file is at most **2 MiB**, has at most **5,000**
records, and must use exact LF-terminated nonblank JSONL. The manifest
must be at most **256 KiB**. Inputs are pinned with `O_NOFOLLOW` and
read from one regular-file descriptor each with before/after metadata
checks; no symlink, nonregular input or oversized read is accepted.

## What the checker cannot establish

A file SHA-256 protects against an **inconsistent** manifest, not against
a malicious or mistaken producer that writes matching fabricated files.
The manifest's collector session, lower-device identity, Git revision,
evidence class, and input digest are all caller-supplied. The original
observation JSONL schema contains no authenticated collector/session/
device field. This checker therefore cannot prove those declared
identities correspond to a real collector, a particular kernel, or a
physical device; it only ensures that the declared metadata is
consistent across the submitted bundle and row artifact.

For authentic performance qualification a separately trusted
collector must obtain kernel/device measurements, bind complete
source and device identities, protect its private key/attestation
and preserve independently reviewable raw samples. Later independent
review must authenticate those records and prove reproducibility.
Even a passing manifest **cannot** nominate a production batch size,
authorize a direct mapper, detach an NBD device, or delete backing
storage. V2.2 strategy and batch winner remain **UNDETERMINED**.

## Synthetic qualification

```sh
python3 -B tests/runtime/v22-evidence-bundle-check-test.py -v
```

This suite fabricates regular-file JSONL and manifest bytes, including
contradictory session/collector/device/revision/run inventories,
tampered bytes and histograms, and CLI failure behavior. It is
mandatory in both combined and teardown rootless CI, with no real
DM/loop/NBD/swap operations.
