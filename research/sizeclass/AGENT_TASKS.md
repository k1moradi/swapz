# Reviewer implementation contracts

All work is in this repository. Read `README.md`, `RESEARCH.md`, and the five RED tests before writing code. Post discussion in the corresponding GitHub issue and submit a draft PR.

## Assignment A — Corrected size-class allocator

Implement byte-accurate 4/8/16/64 KiB aligned extents with a single validated wire layout, a descriptor table that does **not** move already-assigned payload offsets, and exact serialized readback. Define bounded staged RAM, partial flushes, deadlines, mapping identity, generation checks, and separate staged / in-flight / disk-committed states. Publish new authoritative disk mappings **only after the entire lower write successfully completes**; error/partial write leaves prior committed mapping valid or fails closed. Overwriting one shared-extent record must preserve its siblings. Include raw 4 KiB fallback and block-size/alignment checks.

Represent the actual current swapz sequential pack/repack algorithm faithfully; compare with offline best-fit and a bounded causal window at identical flush points. Test the 8x2200 then 8x1600 clustered trace (source-shape sequential=12 bins versus unconstrained offline best-fit=8 bins), 2072-byte uniform traces, 1048-byte traces, shorter forced flushes, collisions and overwrite generations. No future-lookahead or unbounded waiting under memory pressure.

Acceptance: updated, independently runnable tests must turn the applicable legacy failures GREEN; exact round-trip bytes; no disk mapping before success; no latent reads from uncommitted media.

## Assignment B — Deterministic GC and failure simulation

Consume the validated allocator contract from A, or build an independent implementation with identical serialization/readback invariants. Use swapz's current **1 MiB physical segments** for comparable baseline runs; separately label any proposed alternative segment geometry. Enforce finite capacity and a reserve, count successful foreground bytes separate from **GC physical relocation bytes**, and implement a nonrecursive, bounded GC policy. Victim eligibility and selection must use actual liveness, not global capacity alone. Relocate siblings and surviving generations safely; a victim segment cannot be released until all necessary copy writes and mapping updates have completed.

Implement failure injection for partial multi-block write, timeout, interrupted GC, stale generation, reserve exhaustion, map corruption, sibling invalidation. Failed user writes are **never counted as completed logical bytes**; no success claim after partial writes. Track actual read blocks (including metadata blocks if needed), physical write submission/completion and explicit upper completion semantics.

Run identical deterministic traces for 4 KiB baseline, reordered 4 KiB, 8/16/64 KiB candidates: uniform 2072, uniform 1048, clustered 2200/1600, random mixed, hot/cold overwrites, scarce reserve and partial batches. Report physical foreground bytes, GC bytes, net ratio, read blocks and failure status. No fixed WAF factors masquerading as a GC simulation.

## Joint acceptance

- Exact pinned source commit, seeds, commands, signed-off run logs and test cases.
- Fix all five reproduced defects, plus adverse cases.
- Explicit distinctions between theoretical geometry, event-driven simulation, and actual kernel measurements.
- Bounded CPU/RAM budget, I/O alignment, write completion, partial-flush behavior, read amplification, and GC reserve impact.
- Recommend or reject a 4/8/16 KiB adaptive allocator with a falsifiable break-even condition.
- No packaging, no kernel changes, no privileged test operations; communicate through GitHub branches/issues/PRs only.
