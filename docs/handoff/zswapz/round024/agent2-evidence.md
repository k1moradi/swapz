# Round 024 Agent 2 — real pinned zswap compiler-only source boundary

Official issue: https://github.com/k1moradi/swapz/issues/141#issuecomment-6933673371
Task publication: 0f812e51b242b13229cc78f00368eff1f67085a2
Pinned upstream Linux: c339f4010dea8b0d754f84ace70cd1b089878ef8

Actual pinned zswap_store_page() stores zsmalloc handle, pool index,
swap slot and length in its xarray entry, but never saves full
original SHA256 or authoritative slot reuse allocation generation.
zswap_writeback_entry() under locked folio checks current xarray entry,
then decompresses to ordinary original full 4096 WRITE. Its existing
source provenance scalar is NOT a compressed carrier.

A stage-only C gate now asks the actual kernel compiler to emit an
unused source-anchored stored-entry witness with real pool/folio/xarray
types; even credible source fields return EOPNOTSUPP/ESTALE. The
existing Round023 #if 0 carrier and disabled publication stay unchanged.
Compiler-only y/n Kbuild is extended with an opt-in KCFLAGS isolated
mm/zswap.o compile, symbol presence test and default-off restoration,
before matched kernel and DM build. The exact staged function is also
GCC/Clang ASan/UBSan compiled and executed in a synthetic host-negative
fixture. Host mocks cannot qualify genuine stored eviction.

Local container has no Linux checkout and git DNS to GitHub is unavailable;
pinned whole Linux Kbuild and KUnit NOT_RUN locally. Exact final-SHA
GitHub Actions compilation results and first failures must be observed,
not inferred from this source publication.

LIVE_STORED=NOT_RUN; LOADED_KERNEL_SWAPIN=NOT_RUN; PHYSICAL=NOT_RUN;
DIRECT_COMPRESSED=DISABLED; PHASE_A=BLOCKED;
PHASE_B_FORCED_RAW_BYPASS=DISABLED.
SWAPSPACE2 original first 4096/header/UUID/partition-table untouched;
RAW_4096 remains ORIGINAL UNCOMPRESSED 4096.

## Pre-execution test driver correction

The first source review found that the new Python C fixture constructor
contained three double-escaped `\\n` markers (two in the inserted
`main()` call and one after the compiler-profile define), which would
produce invalid C source. Before relying on hosted compiler results, a
follow-up on main replaced them with single Python string escapes so the
compiler receives real line breaks. This was a source-review failure, not
a claimed GCC/Kbuild execution. No kernel, module, swap or physical access.

## First real hosted source-compiler failure and fixture reconciliation

At commit 2ac53e70, pinned Linux source workflow 43992599909 failed in
`Run disabled compressed handoff source/ownership negative regression`
before full Linux Kbuild. The logged Clang errors included generated
`round024-probe.c` C identifiers and, decisively, an undeclared
`round023_stored_allocation_identity_regression` (original C helper from
`round023-producer-proof-identity.c`). The new combined host runner
forgot to include this established fixture. An earlier test-only follow-up
corrected the generated C's three double-escaped newline tokens; this
follow-up includes the unchanged original Round023 C fragment before
`HOST_CASES`, which already calls it. Both failures are author-side test
construction defects, NOT evidence of a live compressed consumer ABI.
The corrected exact-SHA source and pinned CONFIG_ZSWAP y/n Kbuild must
be judged by subsequent workflow results, not by this note.

## Exact hosted first strict compiler diagnostic: pool fixture

At exact source 15824ab7, workflow 43992882311 failed before Linux Kbuild
in the disabled compressed source host test. Both GCC and Clang emitted
`-Werror=missing-field-initializers` for the existing Round023 test's
`struct zswap_pool other_pool = { "lz4", &tree };`: the Round024 host shim
now models original kernel `idx` as a third field for the new original
probe. The follow-up adapts exactly this one **synthetic** initializer in
the new combined test's in-memory fixture text, preserving the original
published Round023 C fixture and full strict -Werror + sanitizers.
No production Linux pool, original page, codec, CRC, kernel ABI, caller,
raw 4096, or runtime behavior is altered. Prior compiler failures remain
honestly recorded; retest at the corrected exact new commit is required.

## Follow-up original Round023 compiler test strict diagnostic

Hosted exact-SHA 84c68821 workflow 43993167178 reached compiled negative
cases: the **new Round024** GCC/Clang executable test passed, but the
unchanged **legacy Round023** GCC/Clang compiled test now failed with the
same `-Werror=missing-field-initializers` at the old two-field synthetic
pool constructor. Both tests share the newly source-faithful host pool
structure with `idx`. The test-only follow-up adds exactly the same
single zero `idx` initializer when composing the original GCC/Clang
compiler fixture, without editing its stored original C file, dropping
-Werror or changing pinned Linux source. The genuine Linux Kbuild step was
SKIPPED at that failing source SHA; its outcome remains NOT_RUN until an
exact succeeding host suite reaches it. No loaded/physical claim.

## Agent2 supplemental exact-source LZ4 provenance and -Werror Kbuild

The prior Agent2 Round024 source, GCC/Clang strict-host test harness, original
test fixture compatibility correction, real GCC `CONFIG_ZSWAP=y/n`
`mm/zswap.o` symbol probe and normal source/KUnit/provenance gates
remain intact; this commit does **not** introduce a second carrier or
change the ordinary decompressed 4096-byte BIO path.

In the actual pinned kernel `struct zswap_pool`, `tfm_name` is the
per-pool compressor identity. A previously retained zswap entry selected
for eviction must therefore reject ZSTD/unknown codec even when the slot
and xarray entry pointer appear current. The existing
`zswap_swapz_round024_producer_kbuild_probe` remains **compile-only**,
unchanged name/signature/flags, and adds a real
`strcmp(stored_pool->tfm_name, "lz4")` mismatch refusal. The static
source validator rejects mutation/removal of that test; the exact pinned
C body is compiled in GCC/Clang strict native tests and the new negative
fixture explicitly switches the host pool to ZSTD. This still is NOT
an authenticated *codec-at-store-time generation*, not a real slot epoch
and not a real original-page SHA256. Every branch continues returning a
negative result, even for a forged otherwise valid source claim.

The existing true pinned GCC `mm/zswap.o` Kbuild opt-in recompile now
adds `-Werror` to
`KCFLAGS="-DSWAPZ_ROUND024_ZSWAP_KBUILD_PROBE=1 -Werror"`
and its default-off restoration uses `KCFLAGS=-Werror`, retaining
`W=1`, exact source SHA, `CONFIG_ZSWAP=y/n` and module matching.
A full Linux object, not a mock host C, must emit the probe and then
prove absence after default restoration. GCC/Clang synthetic host fixture
warnings still fail rather than being disabled.

Real first failures from earlier exact hosted workflows remain as recorded
above: [#43992599909](https://github.com/k1moradi/swapz/actions/runs/43992599909)
`EXIT=1` from malformed generated C newlines/missing original Round023
fixture and [#43992882311](https://github.com/k1moradi/swapz/actions/runs/43992882311)
`EXIT=1` from `-Werror=missing-field-initializers` of the synthesized
pool fixture. Those were corrected in previously published commits. The
current commit must be judged on its own **exact-SHA** CI results; neither
earlier source-host failure reached the complete pinned kernel build.

No checkout is mounted locally and CLI GitHub DNS is unavailable
(`git ls-remote ...` exit 128), so full source Python suite and pinned
Linux/Kbuild/KUnit are **NOT_RUN locally**. The real hosted compiler
commands and their first errors remain the qualification authority.
`LIVE_STORED=NOT_RUN`, `LOADED_KERNEL_SWAPIN=NOT_RUN`,
`4096_READBACK=NOT_RUN`, `PHYSICAL=NOT_RUN`,
`DIRECT_COMPRESSED=DISABLED`, `PHASE_A=BLOCKED`.
Phase B forced RAW bypass DISABLED, SWAPSPACE2 protected header/UUID/table
untouched, and current RAW remains original uncompressed 4096 bytes.
