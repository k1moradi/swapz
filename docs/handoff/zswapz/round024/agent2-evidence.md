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
