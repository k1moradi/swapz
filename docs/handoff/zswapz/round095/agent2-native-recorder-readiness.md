# Agent2 — native observation recorder and direct physical development readiness

> **R095 corrective follow-up:** the lock-based implementation described below
> is the historical baseline at 8c73b49a87b2faffc950effb651dd218e564d6ce.
> The bounded atomic reservation correction at the end supersedes its hot-path
> locking and owner-layout details only; the wire schema and frozen source map
> are unchanged. No native capture or admission qualification follows.

Frozen engineering source ff972661a75ca7f8c3c0458c3feb8b603c185eb8,
original Linux c339f4010dea8b0d754f84ace70cd1b089878ef8; task
20122e158beef6266bd01bb545951a2a4f77d9d5. The R094 offline-only corpus is
accepted (4 tests, 55 semantic negatives, 8 CLI negatives, 7 observed-failure
cases; run 45763872508/job 139719991043/artifact 15090728833). No replay.
R095 adds a **host-test recorder/export prototype**, in tests/tools only;
no native capture producer, no DM/MM edits, no Kbuild or live enablement.
No R095 peer inputs. The existing ordinary helper is unchanged.

## Recorder ownership, wire format and observation limits

Caller preallocates one contiguous array of 1..8192 fixed records and one
owner, initializes with independently supplied canonical scope SHA-256,
then explicitly publishes to test producers. No allocation, hashing,
logging, formatting, file or device access in append/mint; disabled path
checks one atomic enabled flag. Host lock-free atomic bool/unsigned
required at initialization. Mint returns monotonically allocated numeric
run-local tokens (1..8*capacity; never address-derived), append assigns
contiguous event sequence on the single successful trylock. One fixed
record copy, bounded field allowlist and token validation. A failed
trylock, overflow, invalid field or late entered writer sets sticky loss;
record storage never wraps or overwrites, failed observation never
controls product I/O. The linearization is the append lock, NOT an
inferred cross-CPU wall-clock order. Actual producers must emit while
their authoritative transition is observable at its synchronization
point. Do not wait, take new blocking locks, sort or synthesize events
to repair a capture. If the safe point cannot preserve the causal
relationship, report loss/incomplete. Preallocated caller-owned storage
remains live across entry, final copy, stop, seal and export.

**External lifetime prerequisite:** caller revokes and joins all producer
entrants including paused pre-lock entrants before stop/seal/export;
the recorder does not establish that fence. Stop disables; seal refuses
while enabled or locked. A late entered writer marks loss. Export reads
only immutable sealed records with bounded scratch, explicit sink status,
and does not serialize C padding. The owner and storage must not be
reinitialized/freed while an entrant can touch them. A future kernel
adapter needs IRQ-safe trylock/atomic semantics, actual lifecycle fence
and lifetime review. Host C11 atomics/pthread tests are not proof of that.

Wire v2 is one binary envelope (not a disk format): little-endian, 104B
header: magic SWZOBS2 NUL (8), mapping-source SHA ASCII (40), scope digest
(32), count u64, minted high-water u64, capacity u32, record width u32.
Each 296B record is 13 u64 + 24 u32 + three 32B digests, in exact header
macro order; unused fields zero, no raw pointers, payload bytes, sector
addresses, device IDs or host identity. Source slot is logical swap slot
offset, with swap type/area epoch/store and map generation; not a device
number. All identifier roles minted independently, never pointer hashes.
Footer 24B: SWZEND2 NUL (8), count u64, sticky loss u32, reserved zero u32.
No ring overwrite. Max 2,424,960B wire (8192 records + 128B framing);
raw record array 2,424,832B max or 303,104B at 1024 records, plus actual
measured owner/layout/padding. These are arithmetic wire sizes until
host compiler metrics are observed. Actual host test measures append
and disabled calls, contention/loss and sizeof, not kernel hashing,
IRQ latency, scheduling or device performance. No timing pass threshold.

Offline validator reads bounded stdin, expected scope JSON supplied
independently as one argument (exact source, mapping_source, Linux,
kernel/module/workload hashes, run nonce, opaque target, session/epoch/
target_epoch/registration_epoch, first_logical/page_count, M3568);
canonical ASCII sorted-key compact JSON SHA-256 must equal header.
The supplied manifest is not authenticated. Initially empty selected
range, one route incarnation; no inferred existing map. Unknown schema,
field, role alias, noncontiguous sequence, count, footer, loss, truncation
or inconsistent causal history BLOCK. Output only fixed categories,
ordinals, counts and frozen mapping reference; no scope/digest echo.
Exit 0 means consistent recorder observations **only**. Explicit
observed failure or invalid input exits 2, all authorization flags false.
A digest-shaped value cannot prove it was generated from the real bytes,
nor can the reader prove token provenance. Native producer and independent
workload oracle remain required. No source-auth or native collection PASS.

### Event meanings

Each record has event, sequence and operation token (zero only cleanup).
The C header and Python allowlists define exact remaining fields.
Capture retains typed 0x5a LZ4=1/LZO1X=2 v1 dictionary-free 1..3568
compressed bytes' SHA-256 and original full-page oracle digest, never
payload data. The independent page reference must already be available
at that capture point for this profile; if unavailable, do not invent a
digest, block qualification. Bind records original BIO when it exists,
accept records actual selected clone/descriptor and candidate-retained
flag. A discarded nonaccepted capture has explicit drop and carrier debt
release; cannot fabricate an upper ACK. Dispatch records actual ordered
FIFO head (flag 1) or independent parallel typed read selection (flag 2).
Preparation flags 1/2/4 record real MM full-page decode, ordinary prep
performed and prep discarded, respectively; counts never imply no work
when events are missing. Reserve credit strictly increases, one active
credit; claim is same descriptor/ordered owner generation+1, refuse
before claim, verified tail cancel (flag 1) before fallback. Ordinary
fallback can record an ordinary representation, not forcibly RAW;
RAW tag=0 is full uncompressed page, identical full-page/payload digest.
M4095 remains separate; no assertion of wider packing capacity.

Lower submit carries distinct request ID, extent incarnation, read=1 /
write=2, length and payload digest; lower completion carries exact ID,
actual completed length, normalized 0..255 status, actual observed digest
(zero on failed/short transfer). Typed dedicated extent is 4096 lower
bytes vs exact compressed length. Publish only after full successful
write and observed flush, exact generation advance, typed payload match.
Flush failure/short/error cannot publish. Claimed issued error requires
quarantine and no fallback. GC pin, source read, destination write/flush,
new map generation and GC epoch +1, pin release and internal end, no
upper BIO ACK. Typed read pins authoritative snapshot; independent
parallel read records can interleave and finish out of submission order,
including retained snapshot across newer authority; full 4096-byte
decode and 4096-byte comparison with independently expected digest,
then pin release. No global FIFO for lower completions or deferred work.
Single-page discard records actual generation change, not a lower TRIM.

Clone endio is **not** original upper endio: separate events with actual
descriptor/clone and original tokens, observed status, each once.
Candidate/ carrier releases are independent debt events (may precede
or follow clone/upper endio, even while another operation runs).
A candidate release event marks successful deferred put, not enqueue.
Cleanup last: flags 7 = route revoked/RCU drained/worker drained, caps,
tickets,pins,reservations,bios,maps zero, quarantine count consistent
with observed issued failures. These are producer observations, not
proof that cleanup happened. No sorting, artificial release FIFO, fake
ACK or aggregate-to-per-BIO inference. Partial order covers dedicated
typed extents, explicit flush, one-page operations and parallel typed
reads; shared flush, complex ordinary batching/zero elision, multiple
clones per original, other read paths or unknown transitions remain
unsupported for qualification. Recorder transports event order;
validator is a conservative partial-order witness, not a complete
native state machine or source authentication.

## Frozen actual source map and missing producer seams

All line numbers are at frozen main ff972661a75ca7f8c3c0458c3feb8b603c185eb8.
DM blob 2400ad0ccaf72c2586c4fd1488edb9a00246e213 (corrected R094).
Patch line numbers below are repository patch text, not live kernel proof.

| Event | Frozen actual boundary and missing observation |
| --- | --- |
| Natural eviction, exact compressed bytes, original reference | tests/tools/round091-original-mm-eviction.patch 94bb74549c54a614406b71f28a9e8e8c22527d6a, swapz_mm_eviction_key/capture/preerase (41/129/250); round089-original-mm-carrier.patch 059d1bf29cf4990e22a2f608d5d552abeec3a8d1 source read/candidate get/preerase (185/233/246); R092 module-boundary patch 62db468c14f23b59e7adaae65a11dcb9969f02b3 carrier release and independent candidate pins. Missing bounded actual preerase digest and independent original reference, allocation of opaque IDs and binding to original BIO when constructed. Do not derive ID from a pointer or record later and backdate. |
| Route / accepted clone and descriptor | dm-target.c 13720 snapshot_next_locked, 15170 candidate_get, 15244 map, 15516 retained-candidate result and 15523 actual incoming FIFO link under queue_lock. 13697 authoritative snapshot publication, 13745 worker. Missing stable target/registration scope and minted accepted descriptor IDs; no observation may change acceptance. |
| Preparation / claim | dm-target.c 12558 reserve_claim_commit, 12597 claim_reserved under queue_lock, 12656 process_candidate, 13056 worker_pass. 12587–12589 ordered_claim_permitted returns false. Record actual native MM decompression and ordinary prep/discard separately; no proof overhead eliminated, no successful native claim. |
| Lower / publication / pin | src/kernel/zswap-original-storage.c 1f9030030f5d0fb3b06d0b0a159dd8aa6818f8dd shared_commit (504–541) actual write/completed/flush/finish, read 619–645, relocate 679–704; dm-target.c 3670/3677 flush, 11350 typed read; authority.c 14fe52cf4cf28f18568d3bf2b6ced449c9c182a3 transitions and discard 3034. Missing lower submission/completion identity, actual bytes digest and exact postcommit mapping, independent oracle and pins. Actual target uses old bounded bridge, value/shared provider not integrated at freeze. |
| GC / overwrite / discard | dm-target.c 9208 relocate, 11631 discard, 13056 worker pass and actual authority mutation; storage relocate advances both generation and GC epoch. Missing source/destination extent incarnation tokens, lower read/write/flush association and current-map observations. No aggregate inference. |
| Clone/upper ACK and deferred releases | dm-target.c 2374 release_work performs put at 2379; 2384 release_candidate merely queues at 2395; 2399 swapz_complete queues candidate release at 2431 and calls bio_endio at 2464. Actual clone may complete before or after queued put; do not read recycled per-bio storage in workfn. Carry only opaque descriptor token in the retained release debt. Clone endio is target-side, actual original upper completion must be witnessed at staged Linux DM/block/MM completion path (missing), not inferred from target counter. |
| Setup/revoke/drain | dm-target.c 14766 owner close, 14815 RCU unpublish, 14922 install_owner, 14957 storage/bridge close, 15018 setup, 15654 drain, 15891 dtr. R094 broker overlay e33bb8451210f9e1a97eb6d9bc0423f6b13a2edd + src/kernel/zswap-original-broker-owner.inc 0eda8753b91d3209c55f65eb90014fd9b8c6ad7c open/begin_close/finish_close. Need actual route fence, grace/worker/cap/ticket/decoder/debt quiescence and quarantine observations. External pre-lock entrant join is not proved by counters. |

No native capture hooks are installed. The frozen null_blk-only setup and
hard-false claim cannot produce a positive native integrated handoff.
A future patch needs independently reviewed lock ordering, bounded recorder
owner, actual binary/source scope, nonpointer ID propagation at the exact
call sites, capture loss handling and all terminal paths. Do not add
tracepoints on a live host under this round.

## Direct physical development readiness (checklist, NO_GO now)

This is a design/review checklist only. No device selection, probing,
privilege, module load, tracing, swap activation or physical action here.
Do not use the ordinary zswap-off helper as integrated evidence. A10's
combined native build and A3's composed actual host transaction must
first be qualified at the exact source; native capture producer and
source/runtime observation reviewed separately by Agent1. The current
hard-disabled claim must not be toggled for this work.

- [ ] Agent1 accepts exact integrated native source/kernel/module identity
  (real modpost/link and retained hashes), composed owner/target transaction,
  teardown and runtime observation plan. Running kernel/config and module
  provenance match; no old scratch exports, stale symvers, fake authority
  or inferred native observations. All source/drift checks remain fail-closed.
- [ ] Separately approved future direct physical-development protocol
  for the exact scope, not production activation. Resolve the root-owned
  selector/PARTUUID and verify the independently scoped host, actual
  partition and parent, mounts, swap aliases, namespaces, holders,
  recovery state, exact ownership and exclusive access. Separate
  Lubuntu host exception requires its own exact root-owned scope
  record per AGENT_CONTEXT. Never select from an assumed device path,
  parent disk or siblings. Never echo raw host/device identity in evidence.
- [ ] **Automatic narrow fast_test prerequisite**, once at the future
  admission orchestrator if no still-valid exact-current-source private
  checkpoint exists. Verify source/build/artifact/host/nonce match,
  clean unchanged source for admission, correct actual terminal result
  and bounded policy-required stage; fail closed on stale/missing/error.
  Existing ordinary helper's exact unclaimed_null_blk environmental
  exception is not an integrated authorization. No owner broad
  make test/fast_test invocation now; no duplicate replay when valid.
  fast_test is development evidence, not production qualification.
- [ ] Verify existing SWAPSPACE2 first page/header digest, UUID and
  partition-table identity before admission, at relevant transition
  gates, and after teardown, read-only. Protect page0/parent/siblings.
  Safe exact-owned swapoff with sufficient RAM before any data-area
  access. Only dedicated bounded DATA-relative extents, no format,
  repartition, header/UUID writes or unapproved storage. No automatic
  reactivation or forced removal; unknown state BLOCKS.
- [ ] Native zswap enabled with original codec/profile and natural
  isolated pressure only, same accepted FIFO descriptor and original
  BIO, exact stable slot/store/generation, exact compressed digest/
  length, no second BIO or recompression after claim. Record existing
  MM decode/prep overhead honestly. Bound selected range, ticket/extent
  capacity, work/cgroup limits, duration and pressure/recovery guards
  per frozen policy; no claims of production capacity/packing.
- [ ] Actual lower full completion and flush precede authoritative map
  publication, true original upper ACK once, independent full original
  page oracle (byte equality of all 4096 bytes), current typed readback,
  GC/overwrite/discard and refusal/error/debt evidence. Require zero
  recorder loss/overflow/truncation, matched independently measured
  lower bytes/requests, same useful workload, CPU/RAM and cleanup; no
  aggregate inference or invented success. Protect active unrelated
  pages, do not fault-inject on live physical swap.
- [ ] On any stale identity, mismatch, unbounded pressure, error,
  incomplete drain or uncertain cleanup: stop new admission, preserve
  original failure/evidence, follow exact-owned safe recovery policy.
  Drain accepted I/O and references, revoke route, join RCU/worker and
  decoder pins, verify no pending debt; no force-unload or header
  restoration writes. Verify immutable header/UUID/table and target
  inactive, confirm owner choice before ordinary swap restoration or
  keeping swapz active under a separately approved trial.
- [ ] Retain private mode-0600 evidence and bounded redacted report:
  exact source/artifact/run scope, first true failure, actual per-BIO
  records, loss/cleanup and matched accounting. Separate development
  pass from production acceptance; no physical authentication from
  host fixtures, synthetic scope or green compile.

Every item above is unestablished for R095 native/physical admission.
AUTH=0, Phase A BLOCKED, compressed handoff, forced RAW and import OFF.

## Corrective follow-up — concurrent reservation, unchanged wire format

The R095 initial actual host job 139744356343 recorded 2048/4096 successful
Clang threaded appends (sticky contention loss). Keep that immutable
failure-to-capture result and its successful fail-closed qualification;
no accepted corpus replay. Owner-exclusive follow-up within the existing
R095 recorder lane, explicitly requested continuation, no peer outputs.

Use separate saturating atomic unsigned counters for sequence and token
reservation. Both must be lock-free with the enabled and loss atomics;
one shared CAS per successful reservation, at most 64 strong-CAS attempts,
no global lock across field validation or copy, no counter wrap. A producer
that pauses after reservation owns only its private slot; later slots can
complete without waiting for it. Retry exhaustion sets sticky contention
loss; saturation sets sticky overflow and cannot increment a saturated
counter. No allocation, hashing, formatting or I/O in mint/append.
The disabled path remains one enabled check. The per-run token limit
is precomputed at initialization. Initialization clears only sequence
markers; record data stays private until written. Write the unique
record's sequence marker last. No simultaneous readers, ring reuse, sort,
fabricated sequence or ACK. Sequence reservation CAS is the linearization
point; actual native producers must still establish authoritative
transition order at their synchronization sites. Host program-order
preservation is not evidence of a native cross-CPU causal contract.

The external producer revoke/join is still mandatory, including paused
pre-reservation and reserved-but-not-copied entrants. Seal is a
post-quiescence scan of all sequence markers; a hole or corrupt count
sets invalid loss and refuses export instead of reading partial slots.
Stop is not a replacement for that join. On an observed late stop a
reserved writer finishes its private copy and marks loss; that observation
does not make racing teardown safe. No additional per-slot allocation,
side table or wire change. The sequence marker is ordinary memory, never
read concurrently. Caller cannot alias input with writable recorder
storage, mutate immutable input during append, reinitialize concurrently,
or allow export callbacks to mutate storage. Owner/array lifetime remains
external; no native implementation or kernel atomic portability claim.

Changed-source host qualification only: actual same recorder C compiled
under strict GCC/Clang ASan/UBSan, synchronized 2/4/8 producers, four
separate full-capacity trials per thread count; each thread mints distinct
tokens, writes private slots, checks uniqueness, exact counts and
per-producer order, and validates actual wire sequence/token/count/loss.
Separate concurrent record and token saturation scenarios, deliberate
post-join abandoned reservation negative, reinit/disabled checks. Require
zero unexpected loss in these bounded trials; retain actual failure if
the 64-attempt budget is exhausted. Measure observed host elapsed time
including joins, not a kernel latency or speedup claim. The prior
accepted parser fixture/corpus remains intact but is not replayed by
this changed-reservation workflow. No duplicate workflow or native lane.
A finite retry budget remains a loss path under extreme contention;
zero loss in tested schedules is not a universal wait-free guarantee.

All direct physical checklist entries remain unestablished. AUTH0
Phase A BLOCKED; compressed handoff, forced RAW and import OFF.
