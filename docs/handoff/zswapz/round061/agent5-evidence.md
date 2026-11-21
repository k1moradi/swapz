# Round061 Agent5 — linked product GCC/Clang mutant lifetime

Scoped P0: actual linked transaction runner test-only workspace ownership and
fail-only privacy; no product C, import decoder, native BIO or disk changes.

Frozen first errors: Round057 run 44928802841 / job136920672682 and
Round059 inherited LZ4 run 44928802819 / job136920673086 both produced
GCC five real semantic mutant successes, a Clang baseline success, then
FileExistsError for shared GCC/Clang mutant-0 with raw absolute /tmp path.

Correction owns a disjoint GCC vs Clang directory for both binaries and five
actual altered-source mutants, preserves exact real sanitizer/warning flags and
oracle semantics. Separate regression runs the actual runner's workspace and
error-path control flow using stubbed compiler outputs ONLY; the real Round057
runner still must independently compile/execute linked production
authority.c+codec.c and all ten real semantic mutant binaries in the existing
Round057 and Round059 workflows. Private errors retain bounded mode-0600
detail, console emits bounded first error without unsafe /tmp path.

At source publication this remains PROGRESS; require exact corrected-source
two terminal workflow results before REPORT_READY. This test-only fix does not
authenticate source→current DM, release imports or authorize actual storage.
SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED; full original uncompressed
RAW_4096 and protected physical SWAPSPACE2 first 4096 unchanged.
