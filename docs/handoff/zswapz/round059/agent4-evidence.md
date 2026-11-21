# Round059 Agent4 — P0 original LZO host inheritance and original DM pin reliability

Official [Round059 ROUND_OPEN](https://github.com/k1moradi/swapz/issues/176#issuecomment-7063951231).
Frozen engineering `95bf756cce4fc203394e97b2cb7e64f420645f0c`,
task `63fd3846325257446cd4c961727b28e95b535a97`.
Source remains dormant/no-auth, no production IO activation.

## Verified inherited first errors (prior-to-fix source)

At the frozen engineering SHA, 23 workflows were terminal with 11 success
and **12 failures**. Eleven had original generic-host
`src/kernel/zswap-import-codec.h:24:10`
`fatal error: linux/lzo.h: No such file or directory`; original
[Round046 job136861476460](https://github.com/k1moradi/swapz/actions/runs/44909299611/job/136861476460)
and [Round043 job136861476804](https://github.com/k1moradi/swapz/actions/runs/44909299643/job/136861476804)
are representative compiled failures. More than header absence,
linking an unconditional `lzo1x_decompress_safe` reference would
break existing LZ4-only host fixtures that never link the original Linux
decoder. Distinguish the separate
[Round048 HTTP429 job136861476454](https://github.com/k1moradi/swapz/actions/runs/44909299633):
`curl: (22) ... 429` on pinned raw.githubusercontent.com.
Agent1's newer docs-only Round048 run 44912889828 did get the source,
then hit the ordinary generic-host missing-LZO error; do not conflate.
[Round057 product job136861475971](https://github.com/k1moradi/swapz/actions/runs/44909299509/job/136861475971)
printed only the included-from prelude, truncating actual missing-header
diagnostic before its first error.

## P0 source and exact negative regressions

The original imported record representation and C decoder API are intact.
`SWAPZ_ZSWAP_IMPORT_HOST_TEST` now exposes **only** raw LZ4 by
default, without including `linux/lzo.h` or referring to any unlinked
`lzo1x_decompress_safe`. A selected LZO1X record with no linked original
decoder returns `-EOPNOTSUPP` while leaving the full upper 4096 output
untouched. Only the existing, pinned-original `round058` C fixture
explicitly defines `SWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST=1`;
the dedicated original `crypto/lzo.c` wrapper, checked six exact Git
blobs and pristine `lib/lzo` C compilation remain as before, as do
CRC32C, SHA256, strict EOF, 1..3568 input bound, zero dictionary,
original whole 4096 copied on verified success, eight offsets, two
compilers and fourteen real executed original-codec mutants.

A separate, **original-LZO-free generic C test**, linked only with
real `src/kernel/codec.c` CRC, OpenSSL SHA, and LZ4 libraries,
checks 4096 byte-exact LZ4, complete output immutability on error,
unsupported selected LZO and independent SHA/CRC/authorization/overlap
defenses for eight alignment offsets under GCC+Clang
`-Wall -Wextra -Wconversion -Wshadow -Werror` and ASan+UBSan.
Five changed-header source C mutants per compiler must actually
compile, LINK without original LZO, execute to a named CHECK failure,
and pass a negative `nm -u` original LZO symbol check. The previous
Round057 actual product authority transaction C remains an independent
real source test, not replaced by generic fixture.

Round048 no longer issues repeated raw unauthenticated HTTP requests.
`actions/checkout@v4` fetches **exact**
`torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`
with non-cone sparse checkout of actual `drivers/md/dm.c`,
`drivers/md/dm-table.c`, `include/linux/device-mapper.h`.
Before the original Round048/049 source audits, independently
require exact Git commit, clean checkout and all three **original
Git blob IDs**, preserving both pre-existing scripts' own byte-hash
checks and all original source semantic negative tests. A transient
`actions/checkout` network failure remains a true failure; no
unpinned branch or fabricated source fallback.

The original transaction tool now chooses the first GCC/Clang
`file:line:column: fatal error/error` rather than an include prelude,
prints a bounded repository-relative source + sanitized diagnostic,
and preserves raw compiler stderr solely in a newly created
repository-relative `.private/round057-transaction-*.log` with
mode `0600` under a `0700` directory **only on failure**.
A deterministic test injects GCC and Clang multi-line diagnostic
streams containing both host paths and a fake secret, checks first
real missing-LZO error and protected full private evidence, and
rejects leaked absolute paths or unrelated later diagnostics.

## Scope and CI disposition

This is ROOTLESS HOST-SOURCE qualification and a pinned original
DM-C **source audit**, not an original source snapshot→accepted DM lease,
surviving actual decoder module pin, durable lower WRITE/flush/ACK,
current volatile authoritative map/GC, loaded target, or physical IO.
Exact changed-commit GitHub Actions first-errors and terminal outcomes
must be added in issue #176; the commit alone is not proof.
No original pinned Linux source blob or product `authority.c/h`,
`dm-target.c`, normal 20-byte map or SWAPSPACE2 physical first
4096 bytes is changed.

```ini
SOURCE_MAPPED_AUTHENTICATED=0
PHASE_A=BLOCKED
DIRECT_COMPRESSED_HANDOFF=DISABLED
FORCED_RAW_BYPASS=DISABLED
```

No owner Make, privilege, loaded-kernel, device, mkswap, actual
pressure or physical operations authorized or performed.
