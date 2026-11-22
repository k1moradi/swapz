# Round066 Agent4 — original selected decoder source-independent reader lifetime

Official [issue #183](https://github.com/k1moradi/swapz/issues/183),
ROUND_OPEN 7076130990; frozen task
5a4c18fe9c5eef2311d88f3561f7b80d667d776f, last prior engineering
53e843489c0462382ce7400b7fd43f7ad24ef4aa.
Previous resolved decoder ELF P0 original [#44997018549](https://github.com/k1moradi/swapz/actions/runs/44997018549)
and integrated [#44997424261](https://github.com/k1moradi/swapz/actions/runs/44997424261)
both native zswap=y/n and source-host 3/3 terminal SUCCESS.
Integrated native jobs 137133790847(y),137133790825(n), all four
positive/diagnostic/missing-export/omission statuses zero. **Do not
repeat or reinterpret the resolved LZ4 symbol parser failure.**

## Original source-grounded provider contract

Original Linux pinned commit c339f4010dea8b0d754f84ace70cd1b089878ef8:
crypto/lzo.c uses direct lzo1x_decompress_safe and owns a separate
lzo-scomp crypto allocation; crypto/lz4.c uses raw
LZ4_decompress_safe and a separate lz4-scomp context. Neither context
is borrowed by the new owner. Original kernel/module/main.c
resolve_symbol() calls ref_module(), which returns for NULL built-in
provider, otherwise strong_try_module_get() and add_module_usage(),
and module_unload_free() returns module_put(). Exact provider lifetime
is a consumer MODULE dependency, not per-page crypto allocation.
Previously compiled original configurations selected LZO_DECOMPRESS=y
and LZ4_DECOMPRESS=y: they do NOT prove a modular-provider runtime
unload. Existing native original verifier requires .modinfo depends
on original actual module when config says m.

## New dormant source and actual ownership

- src/kernel/zswap-import-decoder-owner.h/.c: selected tag/profile
  initialized once, bounded in-flight reader leases under kernel spinlock,
  close admission latch and sleepable wait queue drain, no dynamic
  allocation or source-pool pointers, caller keeps owner alive until
  all get callers quiesced. Get/put/read retain exact profile and call
  real swapz_zswap_import_decode; no fake ref or stub decoder.
- tests/runtime/native/fixtures/round060-original-decoder-module.c:
  rooted *never executed* real owner API consumer; module_init still
  always returns -EOPNOTSUPP; original y/n GPL/ELF checks retain LZO,
  LZ4, SHA256 and actual product CRC and new owner definitions.
- tests/runtime/native/fixtures/round066-original-decoder-owner.c:
  host C simulation frees original source compressed buffer before
  selected decode on independently sealed original stream. Uses original
  public LZO1X wire ABI through userland liblzo2 (NOT original Linux
  source execution) and raw LZ4 through liblz4, real product CRC and
  SHA256; exact 4096 compare, malformed input/corruption, output
  unchanged, wrong profile, ref overflow/double get and put, threaded
  concurrent close and existing reader, post-close rejection.
  Synthetic read-authority fixture is not real durable lower READ.
- tests/tools/round066-original-decoder-owner-verify.py:
  pin check actual original Linux lzo.h git blob and module loader
  source contract, same-source strict GCC/Clang ASan/UBSan baselines
  and nine *actually compiled/executed* changed-C mutants EACH.
  Any compile failure, sanitizer report or timeout is NOT mutant kill.
  Existing pristine original decoder workflow source-host now installs
  ephemeral CI libraries and runs this exact real-source test.
  Full pinned native original kernel y/n matched GPL remains required.

Local isolated GCC14/Clang17 -std=gnu11 -Wall -Wextra -Wconversion
-Wshadow -Werror ASan/UBSan **PASS**, with two host compatibility
baselines and 18 individually compiled/executed semantic mutants;
no compiler-only or sanitizer kill was counted. Original selected
LZO1X and LZ4 4096 output plus stale/close/CRC/SHA/short-input
negatives pass. Local preliminary build intentionally used temporary
compatibility codec.h, LZO declarations and CRC implementation because
GitHub checkout was unavailable to the container; it does NOT
establish exact product C or native kernel provenance. Exact pinned
host CI with real repository product codec.c and actual original
Linux public LZO header, plus true native original y/n builds, must
be observed separately. Pinned Linux source/module proof is not
loaded pool teardown; no runtime module loading or physical I/O.

**Production unchanged:** source-mapped authentication 0, Phase A
BLOCKED, direct compressed handoff and forced RAW bypass DISABLED,
import ACTIVE 0. Ordinary RAW_4096 whole original uncompressed page,
no new persistent metadata, and physical SWAPSPACE2 header and
parent partition table untouched. Native MM sole owner compressed RAM
and natural pressure eviction; swapz disk work only. No owner Make,
privilege, loaded kernel, actual pressure or device trial.
