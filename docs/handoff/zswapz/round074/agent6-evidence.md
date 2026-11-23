# Round074 Agent6 — natural eviction lease/copy lock budget

**Source published: exact-source GitHub CI QUEUED / NOT YET EXECUTED.**
Task commit: d62552f7048d5a512c7a0a79b86558fa228b31f2. Expected source single-parent: 39d8642878835868ebc3f7690b4adccc62c46fa7.
Source single-parent code commit: 1868d599c6cf33823a36b93c962847cd6e36d475 (parent 39d8642878835868ebc3f7690b4adccc62c46fa7).
Both mandatory evidence files are published with source; a subsequent
evidence-only main commit must record actual tested SHA/job and terminal CI.
No pending or host-model result is represented as original Linux source AUTH.

## Independent code, bounded preparatory host test

New files: tests/runtime/native/fixtures/round074-eviction-lease-copy-budget.c,
tests/tools/round074-eviction-lease-copy-budget-verify.py, and
.github/workflows/phase-a-round074-eviction-lease-copy-budget-host-noauth.yml.
Canonical docs/testing_standards.md original text remains a literal prefix
with a meaningful same-commit policy addition. No production C changed.

The host-only model receives one already-natural MM eviction notification
rather than triggering reclaim. Pool+entry counted leases, protected original
source lock, unretired original codec and matching slot incarnation precede
the independent exact-byte owned memcpy. Copy work under the modeled source
lock is <=3,568 bytes/event; eight-entry bounded pending capacity is
28,544 bytes. Original source can be erased AFTER the copy, while independently
owned bytes, source original codec tag and slot identity persist until
simulated lower processing. Original LZO1X and raw LZ4 remain different from
ordinary fully-uncompressed RAW_4096. Lower IO, waits and checksum/recompression
under modeled MM/source/queue locks are forbidden. Source erasure before copy,
allocation failure, retirement, duplicate, stale and closed owners, queue
saturation, lock inversion, EIO, failed FUA, cancellation, duplicate callback,
and first-error overwrite are covered with negative checks. No real FUA or ACK
exists in this model.

**Local preparatory smoke only:** GCC 14.2.0 C23 strict -Werror ASan+UBSan
baseline PASS and 25/25 compiled/executed C mutants killed; Clang 17.0.0
C23 strict ASan+UBSan baseline PASS and 25/25 killed (50 total). Counters:
directed=99, owned_copies=9, burst=8, max_owned=28544,
max_under_lock=3568, secondary_reclaim=0, recompression=0. First local error
NONE. The local tests used temporary minimal ABI-compatible header stand-ins;
**full repository-header source-linking and canonical git policy are pending
the exact new GitHub Actions run**, not implied from local smoke.
Original pinned Linux KUnit/JSON/KTAP: NOT_RUN; host JSON/KTAP is model-only.

## Earlier-round completed evidence

Round072 Agent6 source 62f137b838a2434764926a24457f700d0bfb984c
was independently verified SUCCESS in actual CI run 45126975773, job
137533438890 (GCC+Clang ASan/UBSan, 48/48 compiled/executed mutants, canonical
push-base/dispatch policy). Final both committed Round072 evidence files are
at commit 7c1ae38d41afb083345b1d7ec67b2d92d48b843a and
issue #189 comment 7094174911. Agent6 owns no Round073 Agent8–11 task.
Previous hourly check is disabled; no periodic checks newly created.

**Unproven/blocked:** real original Linux swapcache-backed STORED and source
lock, real source authentication, measured latency, genuine lower FUA/flush,
real upper BIO once-only ACK, actual decoder readback, physical swap or
memory-pressure behavior. Linux MM/zswap exclusively retains RAM compressed
pages/natural eviction; swapz retains disk packing and GC. Ordinary RAW_4096
is original fully UNCOMPRESSED 4096. Activation remains OFF:
SOURCE_MAPPED_AUTHENTICATED=0, PHASE_A=BLOCKED,
DIRECT_COMPRESSED_HANDOFF=DISABLED, FORCED_RAW_BYPASS=DISABLED,
imported ACTIVE=0. No privileged, loaded, physical or real-pressure tests.

## Exact source CI registration (not yet a test result)

Source tested SHA: 1868d599c6cf33823a36b93c962847cd6e36d475; GitHub Actions [run 45145752021](https://github.com/k1moradi/swapz/actions/runs/45145752021), host job [137594490455](https://github.com/k1moradi/swapz/actions/runs/45145752021/job/137594490455). Last inspected state: QUEUED, no executed GCC/Clang baseline/mutants, native KUnit or model JSON/KTAP verdict available yet. A prior Round072 success must not be counted as this Round074 run. Source blob IDs: fixture fea06aa1a16b47add55bcf9228e2c4a8c66d2f19; verifier 67c19013e0d8bfe24fb03283a3dc7a9ec237f1fa; workflow 191116df8163aad3aacaa07bdd712a85b98d6f64. First exact-source error: NOT_AVAILABLE_CI_QUEUED. Follow-up after terminal CI is required without periodic checks.


## Agent1 independently verified terminal exact-source CI (COMPLETED_CANCELLED_BEFORE_COMPILER)

This manager terminal audit **supersedes earlier QUEUED status only for this immutable tested SHA**, preserving original source commit `1868d599c6cf33823a36b93c962847cd6e36d475` and previous reports. [Existing Actions run 45145752021](https://github.com/k1moradi/swapz/actions/runs/45145752021), [actual job 137594490455](https://github.com/k1moradi/swapz/actions/runs/45145752021/job/137594490455) is **COMPLETED CANCELLED**. Cancelled after ~15 minutes during 'Install unprivileged host-only C build dependencies': unbounded sudo apt-get update/install; exact-source check completed SUCCESS, actual strict GCC/Clang baseline and 50-mutant verifier SKIPPED. First terminal signal: 'The operation was canceled.' Do not infer source/C failure or CI PASS. Round077 Agent6 owns a bounded dependency/preflight repair and a fresh exact-source CI.

**Scope:** host-source-linked model/fixture only, not authenticated original Linux swapcache STORED, original UML KUnit, physical durable FUA or production once-only upper bio_endio. Source AUTH0; Phase A BLOCKED; direct handoff, forced RAW and import OFF; ordinary RAW_4096 complete ORIGINAL UNCOMPRESSED 4096. No new periodic CI checks. Agent6 Round077 corrects workflow dependency step and runs new exact-source CI; cancellation neither a compiler FAIL nor PASS.
