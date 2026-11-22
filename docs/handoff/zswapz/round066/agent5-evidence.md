# Round066 Agent5 — separate test-only native-codec disk ownership

Official source contract: https://github.com/k1moradi/swapz/issues/183
Frozen engineering: 53e843489c0462382ce7400b7fd43f7ad24ef4aa.

## Source and ownership

The existing Round059 diagnostic witness still refuses imported-map publication
and GC with -EOPNOTSUPP. A separate default-UNDEFINED
SWAPZ_ROUND066_IMPORT_DISK_TEST guard adds a caller-preallocated eight-record
volatile LZO1X/LZ4 native-original-codec owner in actual authority.c/.h.
This is neither an ordinary 20-byte swapz_map nor production admission.
Every candidate acquires a genuine swapz_stage allocator reservation;
modeled complete lower/FUA/flush receipt (test-supplied, not physical proof)
transfers the real start to the existing live_records/extent_classes and
closes actual in_flight through swapz_forget_active(..., 1). The ordinary
mapping remains unchanged. Failure consumes the actual reservation through
swapz_abort and abandons/marks possibly programmed bytes conservatively.

Retained volatile readers hold their old physical live start across modeled
GC replacement while the replacement reserves another actual physical extent,
requires strictly greater epoch and identical source/codec/CRC/digest, then
transfers ownership only on full receipt. Last put releases physical liveness
exactly once. Retired extent class remains as a recycle witness. Close fences
new work, waits for callbacks/pins, and requires a second call after drain.
Single serialized authority owner, at most eight records, no per-page heap,
no separate allocator or production fast-path overhead; stale/nonwrapping
ticket checks and no imported native source-to-DM authentication.

Separate automatic CI links genuine authority.c+codec.c with GCC and Clang
strict -Wall -Wextra -Wconversion -Wshadow -Werror, ASan/UBSan, six
positive/negative scenarios, 10 changed-real-source semantic C mutants
per compiler and inherited real Round059 and Round057 suites. GitHub CI
must show exact source SHA, terminal jobs and actual first errors before
scoped REPORT_READY. There is no local full Git checkout due blocked DNS;
isolated source/static evidence is not real linked C qualification.

Linux MM alone owns compressed RAM zswap natural eviction; swapz disk GC only.
Ordinary RAW_4096 stays whole ORIGINAL UNCOMPRESSED 4096. No actual imported
lower BIO/physical durability, native selected decoder lifetime, current
DM accepted source lease, real upper ACK or decoded native READ is claimed.
Only payload/zero padding in bounded 4/8/16KiB extents; physical SWAPSPACE2
first 4096 header/UUID/signature and parent partition table unchanged.
SOURCE_MAPPED_AUTHENTICATED=0, PHASE_A=BLOCKED, direct compressed handoff
DISABLED and forced RAW bypass DISABLED. No owner Make, loaded/privileged,
physical-device or real-pressure tests.
