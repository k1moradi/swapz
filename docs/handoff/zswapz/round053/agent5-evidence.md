# Round053 Agent5 — natural-MM synthetic scheduler policy RED repair and full RAW rollback retry

**Scope:** independent rootless model and its own GitHub Actions workflow only; no original Linux, product dm-target.c, codec or source-to-DM permission changes. Frozen prior engineering `c6f2bc783d29aa06ee59034cda3888ebd2c0683f`, frozen task `140d204b66367f2157d777481df1e93f7fd11bb2`.

## Actual inherited first failure, repaired without bypass

Prior [own workflow #44843580889](https://github.com/k1moradi/swapz/actions/runs/44843580889) first source-bound failure: `SOURCE_CONTRACT_MISMATCH ... first_error=push base SHA unavailable or invalid`; own checkout was shallow (`fetch-depth: 1`) and omitted `SWAPZ_PUSH_BEFORE_SHA`. Source C23 test itself executed and passed on both compilers at that previous SHA. The current change sets real `github.event.before` in the scheduler job and full `fetch-depth: 0`, preserves `persist-credentials: false`, exact `GITHUB_SHA` and main assertions and the existing unmodified canonical policy `--enforce`. No fabricated before SHA, policy skip, or alternate branch.

## Fresh rootless model execution

The actual changed C23 fixture has Git blob `4a179d22fb9c481d12410c3542394ba5f78640c8`. Local rootless direct execution was **PASS** with GCC 14.2.0 and Clang 17.0.0 using `-std=c23 -O1 -g -Wall -Wextra -Wconversion -Wshadow -Werror -fsanitize=address,undefined -fno-omit-frame-pointer`: for **each compiler** `PASS events=192 hostile=21 capacity_blocks=16,32,64 NOT_AUTH=1 PHASE_A=BLOCKED synthetic_only=1`. Local isolated compiler harness used an extracted production codec constant subset; the scheduled real GitHub checkout uses the entire actual product `src/kernel/codec.h`. Source blob SHA was independently matched against the directly tested local file.

The new test preserves previous 192 stream events and 19 hostile gates and exercises two new hostile transitions: old GC epoch replay and recycled counted-slot incarnation. It validates byte-exact all 4096 original RAW bytes after an eight-ticket queue rejection, an accepted EIO write rollback, GC relocation and a successful retry with mutated first/last original bytes. Rejecting unaccepted queue work does not ACK; accepted errors get one ACK; duplicate completion does not ACK twice. The previously committed map stays readable until a successful replacement; in-RAM sentinel protects the synthetic physical first 4096 bytes and partition table. The synthetic compressed representation still compares only opaque payload prefixes; no LZ4 codec equivalence or actual kernel/physical performance is claimed.

| Decision | Current modeled result |
| --- | --- |
| Native Linux MM already emitted an ordinary eviction | Full original 4096-byte upper RAW, optional independent swapz compressor and 4/8/16KiB data-only packing |
| Bounded 8-event queue full | Return `-EAGAIN` without accepting/ACKing the new event |
| Lower `-EIO` or disk `-ENOSPC` | Fail only affected accepted write, retain previously committed mapping |
| Stale GC, slot ABA, synthetic dtr/swapoff cancellation | One terminal failure per accepted event, no stale map publication |
| Hypothetical verified compressed STORED subset | Still NO_AUTH; never enables ordinary RAW-byte bypass or lower handoff |

The model cannot authenticate source slot counts, native Linux pressure, external DM target-table lifetime, actual lower durability, full LZ4 decode or real physical first-page safety. `SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED FORCED_RAW_BYPASS=DISABLED`. No privileged, loaded, physical, real-pressure, `make test` or `make fast_test` run occurred. **New exact-commit CI must be observed independently; queued != PASS.**
