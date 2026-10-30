# Goal prompt: continue swapz development on the active host

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands; the sole owner-approved exception is the development decision loop `make fast_test`, which never qualifies a source, never writes or publishes `test_results.json` and never replaces `make test`. Private scripts and CI jobs are implementation details, not operator interfaces.

Read `docs/context.md`, `docs/coding_standards.md`,
`docs/testing_standards.md`, `docs/VISION.md`, `docs/ROADMAP.md`, and
`docs/benchmark.md`. Work directly on `main`, inspect the current tree and remote
before edits, preserve unrelated work, and use fast-forward updates without
force-pushing. Treat documentation and current source as authoritative; old
handoff files under ignored `build/` can be stale.

Pursue this goal: optimize and debug swapz as a work-conserving, storage-adaptive
LZ4 compression engine for useful swap READ/WRITE service and reduced lower
WRITE bytes/requests, with correct ownership and fair circular allocation.
Dispatch available compressed records with RAW fallback without waiting for
future compression or fuller batches. Compression is not a guarantee of beating
raw on every latency-bound workload; establish improvements with measurements
and report trade-offs candidly.

Keep the existing four-record service threshold, bounded admission/preparation,
one unbound preparation producer, 64-slot reservoir, one immutable lower-WRITE
run, eight bounded READ slots, and serialized lower-success publication.
Preserve independently decodable 4KiB records, 4/8/16KiB extents, CRC/generation
checks, same-page dependencies, PREFLUSH/FUA, DISCARD, GC, suspend/drain and
fail-closed teardown. Ordinary LZ4 acceleration stays 1; default-on delta64 plus
shuffle rescue uses second-pass acceleration 4. Do not add resources or alter
SWZ/early-ACK semantics merely to hide idle time. Preserve the allocator's
circular probe, live-extent protection and GC accounting; logical allocation
spread and host WRITE traffic are proxies, not physical NAND lifetime proof.

Use only newly created, positively identified RAM-backed null_blk devices.
Never activate swap, mount/test physical backing, reboot or force-remove
unrelated devices. Most engineering effort belongs in production kernel C.
Use `make fast_test` for development decisions; it never qualifies a source.
Use exact-source `make test` when qualification/regression gates require it;
it requires a clean tracked source and publishes `test_results.json` and Git
updates, including failed/blocked reports.

Before a performance comparison, declare the hypothesis, primary endpoint
family, practical effect floor, fixed run count, matched content/trace/device
geometry and counterbalanced source order. Preserve exact dirty-source hashes.
Exclude NOISY/UNKNOWN and declared control-drift failures without replacement;
never keep sampling until significance appears. Use paired intervals and an
appropriate direction test with family adjustment. An interval crossing zero
is inconclusive, not equivalence. Report useful READ/WRITE MB/s, p95/p99,
independent lower bytes/requests, GC and resource costs. Partial phase wall and
worker-boundary scheduler deltas are not exact CPU or a removable budget.

Retain only justified changes; remove failed experiments and their hot-path
controls after recording the decision. Keep implementation and governing docs
coherent. Refresh the active host's qualified Git-report history after each
round and display every generated/refreshed plot inline. Keep ARM64/NEON and
x86/SSE2/AVX2/AVX-512 host profiles separate, including absolute raw/swapz rates.
Do not add unqualified trials or make causal claims from historical means.

On the receiving x86 machine, read `docs/handoff/x86-handoff.md` first for the
pending repair, portable direct-BIO draft, earlier AVX-512 report and RAM-model
limits. Qualify the baseline before applying the draft. Do not force AVX-512:
verify actual CPU/xstate/backend execution and retain byte-exact scalar checks.
Use same-host fresh controls; do not import NEON timings or infer RAM type from
the owner's unverified LPDDR4 recollection.
