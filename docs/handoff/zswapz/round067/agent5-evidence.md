# Round067 Agent5 — real compressed bytes in memory-backed disk extents

Official prompt: https://github.com/k1moradi/swapz/issues/184
Frozen engineering b181201a38dc7dde9d561e2c21a214b6c1e8e1ec,
frozen tasks aeceaf19ddb0499fc01b3251136111f53f4c6eca.

## Scope and exact ownership

Preserves default-disabled Round066 genuine swapz_stage allocator owner.
Under an additional default-UNDEFINED SWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST
guard, actual authority.c/h validates immutable native-selected source
compressed bytes, exact sized memory-backed 4/8/16KiB extent, CRC32C and
deterministic zero padding BEFORE passing a MODELED lower completed/FUA
receipt to the existing real allocator physical liveness transfer.
Read requires a retained exact volatile ticket/generation/sequence/GC-epoch
native-original-codec/CRC/digest/source identity and actual live_records and
extent_classes pin, complete original physical extent read, CRC and zero
padding before it copies any caller-owned compressed bytes. The original
ordinary 20B map and RAW_4096 original uncompressed page are unchanged.

Test-only separately preallocated contiguous ~8MiB lower RAM buffer has
physical [0,4096) immutable SWAPSPACE2 sentinel and data extent physical
offset (1 + start_block) * 4096. Only already-compressed native original
LZO1X_1/liblzo2 or raw LZ4 block bytes are copied; no second compression
on disk write or read. On actual lower modeled read the fixture copies the
whole selected extent into separate 16KiB scratch, calls real C read_pinned,
then independently executes genuine liblzo2 LZO1X or liblz4 decoder to
produce exactly 4096 bytes, real SHA256(full original) and byte-exact original
equality before changing caller output. This qualifies host codec-profile
compatibility, not a loaded original pinned Linux decoder or genuine source
selected LZO STORED producer. Frozen zswap-import-codec.h stays read-only;
its live imported decode requires AUTH and one REAL upper ACK and is NOT
called with fabricated ACK values.

Two real original-profile codecs x three extent classes; torn compressed
bytes, nonzero padding at write/read, partial read/write, missing FUA,
bad codec/GC-epoch/digest/generation/ticket, bounded eight slots, protected
header, old/pinned/new after GC and ordinary full original RAW_4096
are covered by six named standalone genuine C test scenarios.
Ten distinct actually compiled and executed changed-source authority.c
semantic mutants per compiler prove the acceptance/rejection oracles;
preserved Round066/Round059/Round057 exact real C regressions, GCC/Clang
strict -Wall -Wextra -Wconversion -Wshadow -Werror ASan/UBSan and canonical
same-commit standards gate remain mandatory. Local GitHub DNS is unavailable
and no direct full-repository C build is claimed; only exact hosted CI can
make this scoped evidence terminal.

All lower completion/FUA evidence is HOST-MODELED not actual durable
physical I/O, no original MM STORED xarray/folio/current selected DM lease,
independently retained loaded original decoder provider, real upper
bio_endio/ACK, true concurrent lower device GC or authenticated production
READ. The memory-only readback is complete genuine 4096 bytes but is NOT
physical readback. Linux MM alone owns compressed zswap RAM/natural eviction.
swapz only disk packing/GC. SOURCE_MAPPED_AUTHENTICATED=0, PHASE_A=BLOCKED,
DIRECT_COMPRESSED_HANDOFF=DISABLED, FORCED_RAW_BYPASS=DISABLED, all imported
ACTIVE=0. Physical SWAPSPACE2 header and partition table untouched.
No owner Make, loaded, privileged, real device or actual pressure tests.

## Round067 exact inherited Round066 harness first-error correction

Round067 first exact source [run 45024099136 / job 137213194385](https://github.com/k1moradi/swapz/actions/runs/45024099136/job/137213194385)
passed the complete NEW real GCC/Clang original native LZO1X/LZ4
compressed memory lower/4096-byte independent decoder baseline, six named
source cases and ALL TEN genuinely compiled/executed changed-C semantic
mutants per compiler. The next preserved Round066 older script failed
BEFORE compiling its original mutant, at:
`FIRST_ERROR round066-import-disk: nonunique original changed-C mutant duplicate_terminal_callback`.
The new Round067 helper properly introduces a second submitted callback
state guard; the Round066 old mutant selector was an overbroad text anchor.
Narrow its original changed-source predicate exclusively to the existing
`return -ESTALE; /* one lower callback, including requeue/close */`
source-bound real Round066 terminal callback, preserving the exact original
operator flip, named case, strict compile and actual executable semantic
kill. This is NOT a C product behavior or release change. Rerun exact
Round067 + Round066 + Round059 + Round057 hosted jobs, verify genuine
terminal first-parent standards, do not credit old red as green.
