# Round062 Agent4 — pinned original GPL decoder native progress

Scope: https://github.com/k1moradi/swapz/issues/179. Original pinned
Linux SHA: `c339f4010dea8b0d754f84ace70cd1b089878ef8`;
11 immutable original Git blobs, original source/selected codec and real
host semantic mutants remain independently exercised by the existing
workflow. No actual source→DM authenticated handoff.

## Exact previous first error

At last actual engineering source
`0593173cad62192bb89f5ba37c6a993e7bafd0d7`,
[decoder workflow #44945987651](https://github.com/k1moradi/swapz/actions/runs/44945987651)
source-host job136973284607 TERMINAL SUCCESS, while native original
ZSWAP=n job136975869586 and native ZSWAP=y job136975869644 both
TERMINAL FAILURE at `ROUND061_DECODER_FIRST_ERROR clang real libelf
compile/link failed` before kernel build. No actual original vmlinux,
Module.symvers or external GPL modpost was obtained at that source.

## Exact narrow correction

Existing rootless native preflight constructed `clang ... -x c -
-x none -o ... -lelf`. Clang `-Werror` rejects `-x none`
following its final source with
`-Wunused-command-line-argument`, while GCC tolerated it.
Delete only the superfluous language reset and reuse strict
compiler-command construction. Preserve real GCC/Clang + libelf
compile/link/execute in the native host prerequisite.

The revised helper's actual-source local
`python3 -B tests/tools/round061-original-kbuild-host-deps-verify.py
self-test` completed with both GCC and Clang strict C
compile/link/execute and an exact original Clang command negative.
The existing synthetic header absence negatives still pass.
The actual local environment lacks `gelf.h`; its real preflight
correctly refuses with exit 3, which is NOT counted as native proof.
No module load, owner Make or device work performed.

Both original native y/n full `vmlinux`/`modules`,
original matched `Module.symvers`, positive linked GPL module and
deliberate undefined-export negative `modpost` must still pass
on actual new-source hosted CI before `REPORT_READY`.
Even a later compile-only success NEVER proves the acquired loaded
decoder reference surviving original source pool destruction.
`SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`, compressed
handoff and forced RAW bypass DISABLED. Ordinary RAW remains the
full ORIGINAL uncompressed 4096-byte page, SWAPSPACE2 header and
partition table untouched.
