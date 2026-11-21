# Round053 Agent3 — internally accepted NORMAL 4096 BIO lifecycle: source-extracted negative-only receipt

Scope: current production src/kernel/dm-target.c; starting source frozen at
c6f2bc783d29aa06ee59034cda3888ebd2c0683f; frozen task instructions
140d204b66367f2157d777481df1e93f7fd11bb2; official issue #170.

## Change and true C testing boundary

A new **default-undefined**
SWAPZ_ROUND053_DM_ACCEPTED_BIO_LIFECYCLE_TEST guard adds a receipt to the
already allocated swapz_bio_ref and an observation strictly **after**
ctx->queue_lock admission and list_add_tail(..., &ctx->incoming).
Nothing is allocated or called by the ordinary product build. The C helper
itself is extracted byte-for-byte from that production file into the host
compiler fixture; it never executes submit_bio, dm_io,
bio_endio, queues work, modifies authoritative maps, or grants an external
zswap STORED source handoff.

Separate phases model a still-owned NORMAL uncompressed accepted BIO:
NOT_ACCEPTED -> LOWER_PENDING -> DURABLE -> MAPPED -> COMPLETED, with ABORTED
as terminal failure. **The modeled durability and map are not a real lower
WRITE or real upper ACK.** The host stand-ins for target/GC generation and
lease tokens are synthetic; no genuine DM table lifetime reference, native
original kernel counted swap slot or callback ownership is acquired.
Acceptance requires the complete original 4096 uncompressed bytes, REQ_SWAP,
target-relative eight 512-sector upper BIO geometry and current map pointer;
unproven external original STORED data is refused. Closing future admission
does not invalidate an accepted in-flight worker's modeled lifetime; dtr,
dropped lifetime, epoch mismatch, callback after abort and duplicate ACK fail
closed. A post-terminal event checks only the receipt before examining any
potentially freed DM target/BIO.

## Rootless evidence and first observed errors

Before remote publication, the locally authored guarded C snippet compiled
and executed in an unprivileged host fixture, **GCC and Clang individually**
using strict -std=gnu11 -Wall -Wextra -Wconversion -Wshadow -Werror,
-fsanitize=address,undefined, leak detection and no sanitizer recovery.
Each compiler executed 162 cases: 54 deterministic fault cases times
1/2/4 4096-byte physical extent blocks (4/8/16 KiB), plus **17 actually
changed helper-C hostile binaries each compiler** caught by exact failure
oracles. The original 144/13, 168/22 and prior C suites are left intact.

Initial *development* first errors were a mutant that escaped because its
host case failed another independent sector-count guard, then a hostile
mutation that compiled RED on -Werror=unused-parameter instead of
executing. These were fixed by a 4100-byte whole-sector-count impostor and
retaining a reference to the affected parameter in the mutant. Subsequent
local GCC/Clang 162+17 both completed with the expected first-error oracle.

**Source-extracted CURRENT committed-file C qualification and remote
GitHub Actions are separate evidence:** the source-extracting runner and
existing DM workflow must be executed against the exact published SHA, and
terminal statuses inspected. Do not promote the local snippet results into
original Linux kernel KUnit, loaded module, durable lower I/O, or upper
bio_endio PASS. No original 60 KUnit reproduction was attempted here.

SOURCE_MAPPED_AUTHENTICATED=0; PHASE_A=BLOCKED;
DIRECT_COMPRESSED_HANDOFF=DISABLED; FORCED_RAW_BYPASS=DISABLED.

Linux zswap keeps only bounded native-MM-pressure-managed compressed RAM;
swapz manages preformatted SWAPSPACE2 disk payload-only 4/8/16KiB extent
packing/GC. Ordinary RAW_4096 always contains original **uncompressed**
4096 bytes. The complete original physical first 4096 bytes remain
immutable. No privileged, actual-pressure, loaded-module, swapoff,
physical/media test, make test or make fast_test was performed.
