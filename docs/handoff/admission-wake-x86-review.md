# Out-of-lock owner notification: development-validated candidate

The [candidate bundle](admission-wake-x86.patch) keeps acceptance, FIFO insertion,
preparation references and producer scheduling under `queue_lock`. It caches
BIO-derived notification policy before unlock, then queues only the ordered
owner outside the lock. A non-submitter caller pins its target under the same
admission-close lock and releases that reference as its final target access.
The submitter-owned path retains its existing lane/reference join.

Drain closes admission, cancels the retention timer, joins all notification
references with acquire semantics, then joins submitter tails and drains queues.
No caller can enqueue after this join has passed. A completed/freed upper BIO
need not remain alive during notification: the helper accepts only target and
cached policy. No representation, lower I/O, mapping publication, CRC/generation,
FIFO, allocator, GC or early-ACK contract changes. This is the bounded hypothesis
from ID155's partial hold observations, not a lockless admission rewrite.

Actual-body ASan/UBSan tests cover a queued wake after admission closes, drain
waiting for it, ordinary queue versus immediate modification, and freeing the
target at final release with no later access. Source contracts check reference
publication under lock and cached-policy use after unlock. All 93 source
contracts and the normal kernel build pass. A few preflight assertions still
expected queue calls inside swapz_map; they were redirected to the extracted
helper before any loaded run. Fake primitives do not replace kernel coverage.

Two initial owned pairs/four arm byte oracles passed with zero notification
references afterward; their performance rows were NOISY and are not comparison
evidence. The broader private deployment gate subsequently passed live GC,
DISCARD, suspend/drain, retained WRITE/flush faults, packed placement and later
completion-handoff failure. The handoff gate recorded 197 successful-session
handoffs and 599 before one lower fault, exactly 16,512 successful WRITEs in its
observed pass, and post-failure EIO without a new success. Notification references
were zero after suspend and fault quiescence. Complete logs and reports are in
[the validation packet](admission-wake-x86-validation.json.gz).

The [fixed pilot plan](admission-wake-x86-plan.json) freezes twelve AB/BA rounds,
raw/target order reversal, six workloads, matched input/source/helper hashes,
three primary service endpoints, +3% floor, family-adjusted intervals/sign tests
and exclusions without replacement. Native full-source contracts passed before
the pilot and need not repeat on each block; standard make fast_test native
preflight remains in every block. The fixed comparison is independent of the
initial noisy development checks. A result requires the complete screened pilot;
no product gain, total CPU reduction or equivalence is established yet.

This draft is development-tested, not owner/ID36 qualified. Committed production
remains source `545defa8`; local experiments may apply the patch. Retention needs
useful READ/WRITE, p95/p99, independent lower I/O, GC and resource review plus
exact-source make test. No new qualification plot/history point was generated.
