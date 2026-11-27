# Round111 Agent4 — rootless paired eviction codec-cost diagnostic

Frozen engineering `4345f21b1da720e6c8d685c7b232bfcebe635d50`, tree `98cb27a3f57d6482d859a260526edb5614ec7994`; Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`. [Assignment](agent4-codec-cost-p1.md), [contract](frozen-contract.md), [issue #229](https://github.com/k1moradi/swapz/issues/229).

Implementation candidate only; **execution NOT_RUN / hosted source lane pending**. Local container has no GitHub DNS/checkout; no compiler result or measured timings are claimed. No same-round peer dependency. Exact ordinary compression function and score helper extracted from frozen dm-target.c; real codec.c, engine planner, scalar predictor, original LZO C and original LZ4 wrapper with the R052 host liblz4 adapter. LZ4 is not the pinned kernel backend implementation: this limitation precludes kernel CPU claims. Original codec namespace stays separate from historical direct ZSTD=2 and ordinary disk encoding. Same generated pages for both codecs, paired eligible pages only, separate zero/same/over-cap and unsupported controls with ordinary fallback and full readback. A uses ordinary decision, B copies immutable original bytes and hashes; all paired readbacks compared to original. Actual production planner and extent builder are exercised for ordinary records; opaque invalid encoding rejected; fixed-class next-fit totals are models only, no production B extent or lower I/O.

20 alternating pairs after warm-up; GCC/Clang sanitizer builds and separate optimized GCC intended, thread CPU batch ns/page median/p95/p99/stdev. No results until execution. Workflow artifact retains actual JSON and first failure when available. No duplicate dispatch, kernel build, installed caller, device or runtime operation.

Evidence -> Goal implication -> Verdict: source candidate only -> potential measurement of redundant codec work versus payload cost -> **INCONCLUSIVE / diagnostic-only; Agent1 acceptance pending**.

AUTH=0; Phase A BLOCKED; compressed handoff, forced RAW, import OFF; physical NO_GO.
