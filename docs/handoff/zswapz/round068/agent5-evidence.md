# Round068 Agent5 — real lower callback ownership and original kernel BIO execution

Official [Round068 issue #185](https://github.com/k1moradi/swapz/issues/185).
Frozen common engineering baseline `6a52194b5b03c1ae82543dc8420fb4218301bd6d`;
task docs `e55d970830358453324928fd9c20a421eb368ec8`.
Full common and Agent5 prompt read; exclusive authority.c/.h guarded source, no
Agent3 DM or Agent4 independently pinned decoder-owner code change.

## Actual product C: bounded native-codec-tagged lower callback fence

A new DEFAULT-UNDEFINED `SWAPZ_ROUND068_IMPORT_LOWER_BIO_TEST` guard nested
inside the existing DEFAULT-UNDEFINED Round066/067 test-only source owner
adds exactly one fixed-size caller-owned callback/transaction snapshot.
Actual production `swapz_stage` and physical `live_records` accounting,
920-byte 8-record separate volatile original LZO1X/LZ4 codec map, original
C `swapz_import_disk_complete_payload` and
`swapz_import_disk_read_pinned` remain authoritative to this test holder.
No ordinary 20-byte map alteration, hidden native fast-path overhead,
upper ACK, physical block I/O or production compressed admission.

Test-only request captures an exact nonwrapping callback token, real
physical sector `(start_block + 1) * 8` (512-byte sectors; first
physical 4096-byte SWAPSPACE2 protected), expected 4096/8192/16384 byte
count and pinned original kernel REQ_OP_READ=0 / REQ_OP_WRITE=1 /
REQ_OP_FLUSH=2, REQ_FUA=bit17, REQ_PREFLUSH=bit18. Native original pinned
source actual compile independently asserts these op/flag bit positions.

Actual full immutable already-compressed source byte stream and deterministic
zero padding are generated/tested by the unchanged Round067 genuine
liblzo2/LZ4 host data. A callback NEVER borrows `struct swapz_tx` from a
caller stack: a full transaction snapshot is owned across queued events;
bvec/page backing is retained by caller until its terminal lower callback.
Wrong token/sector/opf/length/late/duplicate callback returns ESTALE without
publication or resource release. A successful complete WRITE with modeled
REQ_FUA may transfer the real staged physical allocator record only AFTER
its callback and all Round067 data CRC/padding checks. If FUA is unavailable,
WRITE completion transitions to a separate POST-WRITE
REQ_OP_FLUSH|REQ_PREFLUSH callback. Before complete flush, tagged mapping
remains invisible. PRE-FLUSH is never treated as POSTWRITE persistence.
Any short/error/close/flush failure consumes the real allocator reservation
through the existing abort path, rounds up partial physical writes and
conservatively retains possibly programmed extents. Retained read pin holds
old actual physical start across new GC extent publication and asynchronous
READ callback; full compressed copied bytes then decode SHA256 to exactly
4096 original bytes using independent native-compatible host codec library.
Close refuses new work and returns EBUSY until queued callbacks/pins drain.

One sleepable ordered authority owner serializes all these methods. Kernel
original `bio->bi_end_io` is **NOT** allowed to call these product functions
from arbitrary IRQ context: original native endio records only a bounded
result; the caller's ordered sleepable path invokes authority completion.
No unreviewed IRQ-to-authority state access or fake upper bio_endio.

## Source-exact qualified test tiers

The new independent hosted rootless workflow performs:

1. Real linked `src/kernel/authority.c + codec.c` strict GCC and Clang
   `-Wall -Wextra -Wconversion -Wshadow -Werror` ASan+UBSan and seven
   substantive host-model original LZO1X/LZ4 lower callback scenarios.
   **14 distinct compiled and EXECUTED changed-real-authority-C mutants
   per compiler**, one named semantic first-error case each. Compiler errors
   and sanitizer crashes are not mutant kills. Host lower uses caller-owned
   preallocated 4096-byte modeled bvec pages; **NOT native bio execution**.
2. The complete unchanged Round067 original compressed byte decode, Round066
   real physical allocator/pins, Round059 fail-closed import and Round057
   uncompressed RAW/flush linked actual product suites, plus unchanged
   first-parent canonical testing standards.
3. A genuinely executed separate original pinned Linux
   `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`
   rootless UML KUnit, not a copied struct BIO: verifies pristine original
   `block/bio.c`, `include/linux/bio.h`, `include/linux/blk_types.h`
   Git blobs, append-only isolated KUnit fixture to test-only original
   `block/bio.c` staged checkout, then compile/run genuine
   `bio_alloc`/`bio_add_page`/`bio_for_each_segment`/
   `kmap_local_page`/workqueue `bio_endio`. Actual native tests exercise
   all 4/8/16KiB BIO bvec classes with original FUA bit, postwrite flush
   success/failure, READ, callback IOERR, protected header sentinel, and
   exactly one callback per BIO. **No `submit_bio`, device, disk persistence
   or true upper completion occurs.** Actual native receipt is observed
   by test, not a qualifying physical FUA or integrated product AUTH.

Actual original UML KUnit and direct-host callback source tests are distinct
evidence; neither is a real lower device WRITE nor one-to-one integrated
kernel handoff without a genuine physical lower queue and source/DM/decoder
lease. Original pinned native decoder source/header untouched.

## Safety / non-go claims

Normal RAW_4096 means ORIGINAL FULL UNCOMPRESSED 4096, never LZO/LZ4.
Compressed LZO1X/LZ4 source bytes remain a separate volatile test-only tag
from swapz delta64/shuffle/LZ4 ordinary representation. Linux MM alone
controls compressed zswap RAM residency and natural eviction; swapz disk
packing/GC only, no pressure arbiter. SWAPSPACE2 physical first4096
header/signature/UUID and parent partition table protected; no persisted
metadata. `SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`,
`DIRECT_COMPRESSED_HANDOFF=DISABLED`, `FORCED_RAW_BYPASS=DISABLED`,
all imported ACTIVE0. No owner Make, privileged/loaded kernel, physical
device, real memory pressure, mkswap/swapoff/repartition. The actual source
SHA, parent, run/job first-error and terminal outcomes are posted separately
on the official issue.

## First actual hosted red and independent negative correction

[Exact initial Round068 source #45028972192 / host job137228108114](https://github.com/k1moradi/swapz/actions/runs/45028972192/job/137228108114)
failed AFTER the genuine GCC source-linked seven-case baseline passed:
`FIRST_ERROR round068-import-lower-bio: real semantic mutant escaped gcc close_fence_missing exit=0`.
It did NOT run any native KUnit; dependent native job was SKIPPED.
The test fixture closed both lower callback owner and actual allocator pool
before invoking the lower callback. The pool's independent closing state
masked removal of the callback owner's closing flag. The actual
`authority.c` logic and original changed-real-source mutation remain
unchanged. Correct only the fixture to separately exercise callback-owner
closure and pool closure with their own queued WRITE completions, and adjust
safe first-error formatting to retain mode0600 repository-relative
`.private/` diagnostic path. Require a new exact-source full CI; the
old red job is never evidence of native KUnit or qualified mutants.
