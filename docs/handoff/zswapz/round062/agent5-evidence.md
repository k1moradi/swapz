# Round062 Agent5 — standalone Round057 directory-versus-file mutant oracle

Official scope: https://github.com/k1moradi/swapz/issues/179
Frozen engineering source: `0593173cad62192bb89f5ba37c6a993e7bafd0d7`.
Frozen task baseline: `cd8b6e9fa1349289b381dc5472765d133322bd55`.

## Exact first failing job

Original [Round057 run 44945987536 / job 136973284092](https://github.com/k1moradi/swapz/actions/runs/44945987536/job/136973284092)
terminated **failure** with:
`AssertionError: ROUND061_MUTANT_WORKSPACE_FIRST_ERROR mutant escaped compiler-owned directory`.
This happened in the new workspace-control unit regression *before* actual
production C compilation, not in `authority.c` or `codec.c`.
`altered_header` is already a directory at `compiler/mutant-N`;
`altered_source` is a file under that directory. The previous unconditional
`Path(altered).parent` incorrectly rejected correct header overrides.

## Rootless correction and negative oracles

The Round061 test now distinguishes source FILE from header DIRECTORY and
checks that each is the expected type, that workspace parent is the correct
GCC/Clang compiler directory, and that resolved directory identity prevents
a symlink escape. The actual test executes the full unchanged runner control
flow: two baseline invocations, ten independently numbered mutated-source
compilation calls and ten semantic runtime observations (stubbed only inside
this *workspace/control-flow* test). Distinct genuine escaped header directory,
escaped mutated C file, and symlink redirected header directory must produce
the *exact* `mutant escaped compiler-owned directory` error, never a later
content error or false positive. The top-level unit test now prints a single
finite first-error class and relative mode-0600 private log location rather
than an absolute host traceback, including deliberate secret-path checks.

Local unprivileged isolated Python smoke exercised 20 positive file/directory
cases, three escape negatives and independent mode-0700/0600 private evidence,
plus symlink refusal; it did **not** execute repository-linked production C
from a local checkout because GitHub DNS checkout is unavailable in the
container. Authentic original `tests/tools/round057-transaction-product.py`
remains **unchanged**: full real `authority.c + codec.c` GCC+Clang
`-Wall -Wextra -Wconversion -Wshadow -Werror`, ASan+UBSan and exactly
five compiled/executed genuine semantic source mutants for each compiler
are mandatory hosted CI, not credited to the stubbed control-flow regression.
The existing Round059 inherited LZ4 + linked product job 136973283990 was
independently SUCCESS at the frozen previous engineering SHA, but new
exact-source CI is required for both workflows.

**Status at publication: PROGRESS until original Round057 AND inherited
Round059 exact-source jobs both terminal successful.** Their actual job IDs
and first errors must be added to issue #179 after inspection.

No original Linux native compressed-source ownership, source-to-current DM
BIO lease, independently loaded decoder reference, compressed durable
WRITE/GC/read or upper ACK was authenticated. Linux MM alone owns compressed
RAM/natural eviction. RAW_4096 remains full original *uncompressed* 4096.
Protected SWAPSPACE2 header/UUID/partition table unchanged.
`SOURCE_MAPPED_AUTHENTICATED=0`, `PHASE_A=BLOCKED`,
direct compressed handoff DISABLED and forced RAW bypass DISABLED.
No owner Make, privileged, loaded module, physical device, swap/pressure tests.
