# Historical 2026-11-01 content/concurrency backlog

This file preserves the former ROADMAP backlog verbatim from commit `8c81f907638e6ace3b4ebbf89d827f5797282712`.
It contains source- and date-bound instructions whose status later changed.
In particular, its ID62 sentence predates the standing authorization for the
current dedicated SD card and must not be read as current safety policy. The
active dispositions for IDs 38, 58, 59, 61, 62, 65 and 178 live in the
[ROADMAP evidence table](../ROADMAP.md), while current operating authority and
release order are canonical in [AGENT_CONTEXT.md](../AGENT_CONTEXT.md),
[VISION.md](../VISION.md) and [README.md](../README.md).

## Deferred content/concurrency evidence backlog

The alpha.24 policy change only enables the already implemented bounded
`async_prepare` path by default. Do not change its scheduling gates, K=1
ownership, storage format, or ID63 behavior in this step. ID38 remains passive.

- **ID38:** settled for the current product. Lower-WRITE depth is fixed at one;
  the runtime selector, second-slot allocation/append path and routine depth-2
  A/B are retired. Ready-wait telemetry remains passive evidence only. Any
  future K>1 study is a new architecture experiment.
- **ID65:** owner-qualify the synchronous read-path cleanup; do not restore or
  replace the rejected helper workqueue unless new measured evidence requires it.
- **ID58/59:** keep representative-content collection offline.
- **ID61:** add foreground-GC stall/reserve-headroom evidence under bounded useful pressure.
- **ID62:** physical devices remain outside the current development safety scope.

**ID178 instrumentation cost hypothesis (2026-11-01):** ARM64 cross-report
fast-mixed service fell from roughly 71.9 to 69.0 MB/s after ID178, with
suspected per-ACK time/atomic overhead; this is not a same-source controlled
instrumentation A/B. ACK delivery now samples one timestamp per owned delivery
cohort and accumulates dwell bins within that existing loop before a bounded
atomic flush, removing both per-BIO clock reads and per-BIO telemetry atomics
without changing acceptance or ACK timing. Direct unbatched completion keeps
its exact fallback clock. Treat ACK-dwell values across this instrumentation
boundary as comparable only within the bounded delivery-loop timestamp error.
Validate ARM64 performance prospectively; do not claim the 4-6% difference is
proven ID178 overhead.
