# V2.2 V3 exact-latency sidecar (source-only specification)

V3 is an **additive** observation schema named
`swapz-drain-observation-v3`. V1 and V2 continue to parse
unchanged. V2 retains its 256-distinct-exact-latency limitation; do not
round/quantize V2 timestamps to fit it. V3 represents up to 10 million
exact values per independent run without losing nanoseconds or expanding
all samples in RAM.

## Canonical layout and association

A V3 JSONL row has all mandatory V1 fields, except its schema is V3.
It **adds** precisely two fields:

- `read_latency_sidecar`: unique, same-directory basename,
  ASCII alphanumeric start and ASCII alphanumeric/dot/underscore/hyphen
  remainder, ending in `.latbin` (maximum 128 characters).
  No directory separators, absolute paths, `..` traversal,
  symbolic links, extra hardlinks, FIFOs, or special files.
- `read_latency_sha256`: lowercase 64-character hexadecimal
  SHA-256 of the sidecar's **entire original byte stream**, not a
  JSON representation, bucket list, or relabeled summary.

The sidecar consists solely of sequential, 16-byte exact RLE records.
Every record consists of two **unsigned, big-endian, 64-bit integers**:

```text
byte 0..7:   exact positive observed swap-in latency in nanoseconds
byte 8..15:  strictly positive occurrence count of that exact nanosecond value
```

There is no header, padding, framing, compression, footer, rounding,
floating-point representation, units conversion, or sample omission.
Records must be sorted by strictly increasing latency. Duplicate
latencies, zero values, latencies greater than 10^13 ns, empty streams,
partial 16-byte records and any count overflow are fatal.

The sum of occurrence counts must equal the JSONL
`read_count`, which remains between 10,000 and
10,000,000 inclusive. The analyzer recomputes the **exact nearest-rank
p99** by finding the first cumulative count at or above
`ceil(99 * read_count / 100)` using integer arithmetic.
This integer latency must exactly match `read_p99_ns`.
A declared p99 may never substitute for sidecar verification.

A sidecar basename may be bound to **one row only** within a JSONL
document; different rows must use separately named sidecars even if
their contents happen to be equal. Different schemas and evidence labels
never merge into the same plateau series.

## Legacy bundle manifest boundary

The legacy `swapz-v22-evidence-bundle-v1` verifier accepts only the
JSONL artifact and self-reported manifest. It **continues to reject
all V3 rows** rather than falsely claiming their sidecars were read.

A separate, independently tested `swapz-v22-evidence-bundle-v2`
verifier now checks one pinned directory, each exact sidecar byte
stream, the original-byte SHA-256 and size, run-bound JSONL digests
and the claimed session, collector, device and backend/profile IDs.
See [V3 bundle specification](v22-evidence-bundle-v3.md).
All such identities remain caller-supplied; the bundle check does
**not authenticate** their owner or grant production authority.

## Input trust and resource limits

The main JSONL file is limited to 2 MiB and 5000 observations. It and
the sidecars are opened relative to the *same pinned input-directory
descriptor*; each sidecar opens through a retained `O_NOFOLLOW`
regular-file descriptor. The directory's last component cannot be a
symlink. This is not a complete secure-path traversal proof for every
ancestor under an attacker-controlled host root.

Each sidecar is limited by 16 times its declared `read_count`
(maximum 160,000,000 bytes). The sum across one invocation is capped
at 512 MiB. Sidecars are scanned sequentially, using fixed 64-KiB
chunks, with at most a 15-byte trailing carry for short reads.
The validator hashes source bytes as read, verifies length and byte
alignment, and rejects changed inode/device, mode, link count, size,
mtime, or ctime before accepting a result. No table of raw latency
samples, input-sized list of RLE entries, or subprocess is needed.

The validator does not authenticate the origin of the main JSONL,
its claimed source revision, collector, signing authority, raw
measurements, lower-device identity/counters, kernel drain, or
the physical completion semantics of the claimed read latencies.
An attacker with access to both JSONL and sidecar can fabricate
internally consistent rows and hashes. A privileged actor or
concurrent in-place writer cannot be fully excluded by descriptor
pinning and metadata comparisons.

V3 synthetic observations remain **illustrative only**.
A self-reported kernel or physical V3 observation may produce only
a **provisional candidate requiring independent evidence review**.
Neither schema, p99 recomputation nor SHA-256 approves real device
operations, backing release, production admission, or a V2.2 winner.

## Rootless validation and microbenchmark

```bash
python3 -B tests/runtime/v22-drain-plateau-analyze.py \
  --observations /trusted-private-directory/observations.jsonl
python3 -B tests/runtime/v22-latency-v3-test.py -v
```

The adversarial suite covers exact 10,000- and 100,000-distinct-nanosecond
series, the p99 rank boundary, file identity/length/digest, alternative
endianness, duplicated/unordered records, forged counts, symlink/hardlink
and FIFO denial, directory traversal, and cross-schema nonpooling.
A rootless 100,000-unique-value microbenchmark measures elapsed Python
parse time and Python-traced peak memory for a 1.6-MiB synthetic sidecar.
It is a source parser performance check, **not swap or device performance**.

All three existing selection predicates remain unchanged:
at least three independent runs with 10,000 reads, a 10% repeatability
spread bound, and 97%-of-maximum plateau at 256/512/1024 KiB with
worst-run p99 within 10% of the best qualifying plateau size.
No real device commands run as part of this format or its tests.
