# Acquire READY after a lost RAW-selection compare/exchange

The ordered consumer initially acquires the preparation state. If that read
sees PREPARING, the producer can publish READY before the consumer attempts
its PREPARING-to-RAW compare/exchange. The failed operation then returns READY
without guaranteeing acquisition of the producer's payload, length, CRC,
encoding or per-page compression-cost metadata.

The [Linux atomic API ordering contract](https://docs.kernel.org/core-api/wrappers/atomic_t.html)
does not guarantee ordering on conditional RMW failure. The old native shim
used acquire failure ordering and therefore gave this path a stronger contract
than portable kernel code may rely on. No corruption was observed on the x86
qualification host; the issue is an API-level ordering gap, not a measured
hardware failure.

The fix adds an acquire reread only after the RAW-selection CAS loses.
The consumer still holds its prepared-page reference, so READY cannot recycle
before that read. Ordinary READY observations and successful RAW claims keep
their existing one-acquire path. There is no new wait, retry loop, reference,
worker, buffer, codec policy, extent geometry or lower-I/O depth.

The native test deterministically inserts release publication between the
initial PREPARING read and compare/exchange for both READY_COMPRESSED and
READY_RAW. It requires a READY acquire observation and checks that the ordinary
READY and RAW-win paths add no read. The shim now uses relaxed failed-CAS
ordering. The old production header compiles but fails this regression; the
fixed header passes, while a separately compiled relaxed-reread mutant fails.
The complete native program also passes 8192 threaded transfers and
AddressSanitizer/UndefinedBehaviorSanitizer. These checks do not constitute
an LKMM proof or establish a throughput improvement.

Private logs and mutant binaries are under
`build/optimization-round/preparation-ready-acquire/`. The development loop passes its native checks and module build, followed by
three byte-exact, drained owned-RAM pairs (fast QD4, QD8 and mixed) with
the required compression stack enabled. All three pass the existing noise
screen; these single observations are not a source A/B or performance claim.
Exact-source owner qualification is pending. The previous estimator fix's
owner report does not qualify this new header change.
