# Round060 Agent5 — P0 actual authority strict conversion / GC and map safety

Source base: frozen engineering `55c0eca070cbd21a0e153990e4859ec914d45232`, task `73bc67e9233ba71b1f460827706cdb26a0996ad2`. Official issue [#177](https://github.com/k1moradi/swapz/issues/177); unique ROUND_OPEN comment `7065333937`. Agent 5 only owns `src/kernel/authority.c/h`, rootless real production authority tests/fixtures, and this evidence; other three source agents work independently.

## Verified old first errors (not mislabeled as three separate codec bugs)

Agent1 all 25 exact frozen-engineering workflows: 22 terminal SUCCESS / 3 terminal FAILURE. GCC strict `-Wconversion -Werror` first three at real authority [run 44920461390, job 136895149946](https://github.com/k1moradi/swapz/actions/runs/44920461390/job/136895149946):

- `authority.c:2755:24` size_t / ulong metadata byte-size expression narrowed to `swapz_u32`.
- `authority.c:3087:33` unsigned GC segment minimum-live-block subtraction narrowed to `swapz_u16`.
- `authority.c:3151:42` dynamic `swapz_u8` extent class assigned to 3-bit in-RAM map bitfield.

The same :2755 product C source first error also failed the [Round057 actual production linked product transaction](https://github.com/k1moradi/swapz/actions/runs/44920461369) and [Round059 generic LZ4-only host plus inherited real product transaction](https://github.com/k1moradi/swapz/actions/runs/44920461267); the original LZO host header/link issue was already fixed by a separate Agent4.

## Exact surgical production edits

- Real `swapz_finish()` legacy-only metadata arithmetic uses an unsigned 64-bit wide expression and checks against the full `swapz_u32 bytes_total` size before the explicit, proven-safe narrowing. A too-short legacy extent returns `-EUCLEAN` before any map/GC publication; production compressed payload-only still carries zero metadata.
- The actual destination segment GC minimum-live-block base uses a `swapz_u32` temporary (no narrowing) with a pre-subtraction `-EUCLEAN` check against the already accumulated loss. Existing max-`u16` capacity/overflow proof before atomic map publication remains unchanged.
- The real `swapz_is_active()` already checks `swapz_legal_class()` against exactly 1/2/4 blocks; `swapz_finish()` now expresses the bitfield representation using just those constant 1/2/4 alternatives. No dynamic 8-bit→3-bit narrowing or new hot-loop scan. Exact `struct swapz_map` remains 20 bytes.

No new decoder, native source MM→DM BIO lease, GC scheduler, imported product map or lower durable handoff. The Round059 import witness still has capacity eight, at most two staged, a monotonic ticket, pinned diagnostic descriptor and `swapz_authority_import_try_publish() == -EOPNOTSUPP` always. No imported ACK, decoded read or FUA claim.

## Rootless evidence scope

The actual product C fixture `tests/runtime/native/fixtures/round059-authority-import-lifetime.c` now tests regular product compressed data-only `swapz_stage/bind/mark/finish` on ALL 1/2/4 legal classes and a product CRC-validated payload read, including corrupted read rejection. These fixture compressed bytes are descriptor integrity inputs, **not** authenticated native zswap stored bytes and not demonstrated decoder output. Its original ordinary full-uncompressed 4096-byte RAW CRC and full physical header protection assertions remain. The own runner `tests/tools/round059-authority-import-lifetime.py` remains strict GCC+Clang GNU11 `-Wall -Wextra -Wconversion -Wshadow -Werror` with ASan+UBSan, genuine `src/kernel/authority.c`+`codec.c` linked and executed, preserving seven Round059 mutant kills and adding 1/2/4 class + normal compressed read CRC mutation checks. Compilation or sanitizer failures are **not** valid semantic mutant kills.

The same changed source must separately make three already-existing rootless workflows terminal SUCCESS: Round059 authority source, Round057 actual product transaction, and Round059 generic LZ4 host inherited transaction. Each exact run/job/first error is reported on issue #177, not inferred from a registered workflow. No owner `make test`/`make fast_test`, privileged, physical, loaded kernel, real pressure, swapoff, device header or partition table mutation.

**Absolute gates:** Linux native MM alone owns zswap RAM reclamation and natural pressure eviction; swapz handles disk payload packing/GC only. `RAW_4096` always the full ORIGINAL UNCOMPRESSED page. Entire first physical SWAPSPACE2 4096 and parent partition table are immutable. `SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`, `DIRECT_COMPRESSED_HANDOFF=DISABLED`, `FORCED_RAW_BYPASS=DISABLED`. No positive authenticated compressed handoff or release from this source C fix.
