# Early submitter snapshot release: fixed old-PC pilot

The unconditional early-release prototype is removed. Its primary fast-QD4
point estimate misses the 5% service floor, usable coverage is insufficient,
and lower bytes rise beyond the 1% guard. This is not a production change.

Source: `1673c024b20e26825e64ccef4ef590980cd368d8`, kernel
`7.0.0-38-generic`, two-core/four-thread i3-M330. Freeze
control/candidate/candidate/restored-control, two repeats each of fast
QD4/QD8/QD32/mixed and serial QD8, with medium content, submitter enabled,
hand eight and delta64 + DELTA64_SHUF8 + LZ4 enabled. No new worker, pool,
encoding, lower-WRITE depth or upper-success contract. The private candidate
publishes the immutable RAW snapshot before optional compression finishes,
retaining a second slot reference and reusing READY/RAW_SELECTED arbitration.

Actual-C native probes pass under ASan/UBSan with the BIO descriptor poisoned
immediately after release. RAW-first, READY-first, zero and copy-error paths
conserve slot references, lane ownership and ready gauges with retention on/off.
Four compiled mutants fail: missing second reference, descriptor reuse,
missing producer put, and rejection of a legitimate RAW winner. These tests
are not LKMM or whole-kernel lifecycle qualification.

All 40 loaded raw/swapz pairs pass the complete-image oracle and exact
preparation-actor accounting. Every drained slot/ready/submitter-active gauge
is zero. The unchanged screens exclude 16 observations; pairwise matching and
raw-drift checks leave only 2/1/2/2/1 usable comparisons for QD4/QD8/QD32/mixed/
serial-QD8 respectively, below the declared three-comparison minimum.

The descriptive QD4 estimate is +4.14% normalized useful WRITE (unadjusted
paired-log 95% interval -8.17% to +18.11%), with lower bytes +2.73%
(+2.52% to +2.94%). Both coverage and practical/byte targets fail. Other
workloads' coverage and guard intervals do not justify retention either. Do
not promote small-sample intervals or infer a statistically established mixed
regression. No observations were replaced or added.

The mechanism engages: first-repeat QD4 submitter claims stay exactly 4096
with zero background claims. Owner deferrals fall from 1150/1159 in the two
controls to 367/313 in the candidate blocks, while RAW-before-ready and late
discard counts rise from zero to 490/461. Less blocking alone is not enough:
the unconditional fallback spends more lower bytes without a proved service win.

Before the final control started, a remote report commit interrupted the
coordinator. Read-only inspection proved the only change was
`test_results.json`; every other tracked byte matched the frozen source.
An administrative resume, recorded before aggregate effect/acceptance analysis,
completed only that unstarted final control on the original local HEAD and
restored control C. It performed no source write, replacement, sample extension
or acceptance change. The interruption and original state are preserved.

This experiment exposes a separate concrete defect: `ordered_lz4_page_ewma_ns`
is zero in every QD4 control despite 4096 submitter compressions and about
25.6–27.0 ms of LZ4 wall. Only inline ordered compression currently teaches
that estimator. ID172 repairs coverage by publishing each asynchronous page's
LZ4 elapsed sample before READY, then observing READY samples in the single
ordered owner. It does not retain the rejected early-release prototype.

ID172's separate dirty development validation passes three loaded pairs with
zero inline work and submitter claims matching all measured WRITEs: QD4
4096/7284 ns, QD8 4096/5222 ns and mixed 12301/4938 ns (claims/EWMA).
Every final image is exact and every ownership gauge drains to zero. Native
actual-body tests reject cumulative lane time and unready-field access. Real
kernel-object DWARF shows the prepared-slot size remains 8256 bytes before/after.
These observations validate cost coverage, not throughput improvement or full
qualification; artifacts are in `build/optimization-round/prepared-cost-coverage/`.

The [machine-readable summary](submitter-snapshot-oldpc.json) preserves all
estimates, exclusions, source identities, administrative resume and diagnostic
actor samples. Full logs, plans, C copies/patch, native probes/mutants,
analysis and SHA-256 manifest remain in
`build/optimization-round/submitter-snapshot-oldpc/`. This development pilot
does not write `test_results.json` or enter qualified history.
