# V2.2 staged/loaded read metadata validation and compactor scan review

## Scope and identity

The independent main-developer audit started at
`9a4e16824fc5457028005c13d60c6b56d72077bc`, immediately after
the overlap-validation commit. The scoped candidate is
[draft PR #4](https://github.com/k1moradi/swapz/pull/4).
The separate Codex/native-Linux assignment is limited to building and
running known rootless suites at its pinned SHA; it is **not** treated as
test evidence for this newer candidate.

## Confirmed source-level acceptance bugs

Before PR #4, `swapz_read_staged()` branched on the compressed flag bit.
An in-memory staged record with unknown flags such as `0x4` therefore
fell through to copying the whole 4 KiB physical page as if it were raw
data. A forged per-record `record_index` could also diverge from the
staged-reference slot; the read path followed the forged index without
testing slot identity or a maximum count on disk.

The committed mapping decoder similarly treated an otherwise-valid
mapping with unknown flags as raw and accepted disk container counts
greater than the 64-record format limit when the requested record index
was below the forged count.

These are **fault-injected malformed-memory/on-block metadata**
acceptance defects. Ordinary-operation reachability and deployed
device impact have not been demonstrated.

## Production changes

- `swapz_read_staged()` now requires the resident record index to
  equal the staged-reference index and remain within the 64-entry
  capacity. It permits exactly `0` or `SWAPZ_MAP_COMPRESSED` flags,
  validates the raw page's sole 4 KiB record, and requires the compressed
  disk record count to equal its in-memory count. Zero and oversized
  compressed lengths are rejected before decompression.
- `swapz_decode_loaded_mapping()` requires a published mapping's
  flag word to be exactly valid/raw or valid/compressed. Raw mappings
  must contain a full 4 KiB record at index zero. Compressed container
  counts must be nonzero and no greater than 64.
- The previous quadratic per-container overlap scan is replaced by a
  linear pass checking each compressed payload against the preceding
  payload's start. Both pack and repack append compressed extents from
  the end of each 4 KiB page towards the descriptor header in ascending
  record order, so the next payload must finish at or before the
  previous payload's start. This accepts the ordinary packed format and
  rejects overlaps and noncanonical reordered ranges.
- No ABI, persistence format, logical mapping size, stream buffer
  count, new heap allocation, or public API changes are introduced.

The new checks fail reads closed. They do not attempt to repair
corrupt resident or lower-device data, establish arbitrary-corruption
recovery, or prove the kernel/device I/O lifecycle.

## Exact-production-C rootless tests

`tests/runtime/swapz-staged-read-contract-test.py` extracts and
compiles real production functions with isolated bounded ordinary RAM
structures and a minimal deterministic stub for LZ4. It checks valid
staged compressed/raw reads, missing refs, wrong record indices,
unknown flags, contradictory counts, corrupt raw lengths, and valid
loaded mappings. It checks a forged >64 loaded-container record count,
unknown mapping flags and malformed raw mappings.

A second executable removes the relevant guards from exact C and
reproduces acceptance of unknown staged flags, oversized disk counts
and unknown committed mapping flags. This is executable negative
evidence, not a comment-only/regex-only guard.

`tests/runtime/swapz-compaction-container-contract-test.py` also
exercises a malformed nonoverlapping but reordered descriptor layout,
while preserving valid packed adjacent extents and both old-overlap
expansion counterexamples. The GC source decoder test fixture is
updated to correctly set the published-map valid flag, matching the
production mapping contract.

The isolated kernel source workflow, combined source workflow,
and teardown safety workflow are configured to run the new regression
under bounded timeouts. The rootless workflow contract rejects dropping
it from either joint workflow.

## Qualification limits

Review exact revision and four GitHub workflow conclusions before
merging; the code is a candidate until these results exist. Rootless
C tests do not execute real kernel code as a loaded module, Linux swap,
dm-io, LZ4, GC runtime, device fault injection, physical media, or
privileged worker containment. The linear-scan design reduces
worst-case per-container extent comparisons from O(n²) to O(n), but
actual batch throughput, latency, and V2.2 strategy-selection impact
remain unmeasured.

No physical backing release, privileged teardown, real DM/NBD/swap,
module loading, pressure workload, reboot, or destructive operation
occurred during this task. V2.2 strategy and batch winner remain
**UNDETERMINED**.
