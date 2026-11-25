# Round090 Agent7 — dormant independent original decoder-lease bridge

**Disposition at publication: SOURCE_PUBLISHED_CI_QUEUED / NO_GO_LIVE.** Task [edf44c4417f14b5836b1b5f90157e24916afcde2](https://github.com/k1moradi/swapz/commit/edf44c4417f14b5836b1b5f90157e24916afcde2), frozen baseline 9f7002c896f86226e93f0523b1f6e935de5c6de9 and original Linux c339f4010dea8b0d754f84ace70cd1b089878ef8. ROUND_OPEN issue #208. Agent7 independently owns the new bridge and source-linked host test. No same-round peer API usage or production activation.

## Exact publication

- Initial source [dbb947ca895916cedbd20e93422722f1dde5b510](https://github.com/k1moradi/swapz/commit/dbb947ca895916cedbd20e93422722f1dde5b510), sole parent ca95fa592eced5056a9209103c700d109c3d78ab. Published by expected-HEAD nonforce main fast-forward. Original six changed paths: new bridge C/H, fixture, verifier, host-only workflow and testing standards.
- Corrected source [70fbbe12c84db56283b5e0812faf1fc8032bbae4](https://github.com/k1moradi/swapz/commit/70fbbe12c84db56283b5e0812faf1fc8032bbae4), sole parent dbb947ca895916cedbd20e93422722f1dde5b510; fresh expected-HEAD nonforce main FF. One historical trailing-space removal in restored standards and an explicit standards-prefix source preflight. This is a changed source revision, not an unchanged rerun.
- Source blob pins: `src/kernel/zswap-original-decoder-bridge.c` 9324a581e27bad62d4e2d9c90192f6ad8b96faca; `.h` 507b25debe0ca7b30b57ed6a350dab4868dced51; fixture 81b6990707b8dd65ec1e6e54c6a0bfa7269f6ebe; verifier e7c78d9e44fd2c28e392bfa4b30beb8b8cbeb7ee; final workflow 5795c9c2c18aafa9d4425b0c01179dcd94c1428c; final standards 245d52f2160410ff719f0584f86dd248c9d59cf7.
- An independent fresh-head read found **preexisting historical testing-standards prefix loss**: at main ca95fa592eced5056a9209103c700d109c3d78ab, standards blob ed028e01f353332154a9435e74e6e6f70bbfd33e had 7,989 bytes and began with Round090 notes rather than `# Testing Standards`. Frozen standards blob 3bc8692b5f71a5d31c9caba1b858dde8a28ab1f6 had the 1,785,082-byte prefix. Agent7 source reconstituted **full frozen prefix + all contemporary 7,989 bytes + Agent7 append-only note**, preserving the entire current suffix; final correction removed one trailing space at restored historical line16489, otherwise retained content. No peer source-file changes. The initial restoration's whitespace is expected to trigger `git diff --check` at the first source revision; **do not mark that revision PASS**. Corrected revision alone is the new qualification target.

## Real adapter and ownership scope

`swapz-original-decoder-bridge.c/h` implements the *frozen existing* `swapz_original_storage_ops.decoder_get/decoder_put` signature and preserves real lower write/read/flush callbacks without synthesizing completions. Two independently initialized, codec/version-matched original LZ4/LZO1X decoder owners provide retained record tokens, distinct from a temporary exclusive per-read owner lease. Source address tokens are bounded to 64 **nonreused per lifecycle**; false-ABA/stale pointers and exhausted sessions fail closed. Reference acquisition/release and a read counter are serialized with a short bridge lock; no CRC/SHA or decompression while holding it. A read decodes with the existing `swapz_original_decode`, checks exact 4096 bytes, CRC and SHA, rejects capacity/alias/representation/version/dictionary errors and writes caller output only after successful lease put. Close rejects live record tokens/readers without waiting under a foreign lock, then drains both owned codec references. No on-hot-read allocation or per-page module_get/put. Externally authenticated current source, real module owner hard-ref and full lifetime contract are NOT implemented by this adapter; do not treat a source descriptor or pointer as authentication.

The **64 total nonreused callback tokens** are intentionally bounded and insufficient for steady-state production overwrite/GC. A generation-bearing frozen callback ABI or demonstrably safe reuse protocol and real module lifetime binding are required before live integration. No Kbuild wiring. The original zswap/MM RAM owner, original full-page fallback, selected DM admission, durable lower write and upper ACK remain outside this scope.

## Tests and first error

Local container checkout of pinned Linux was **NOT_RUN** because native GitHub DNS was unavailable, so there is **no local actual original-kernel object compile or runtime claim**. Local exact new C fixture/bridge against a deliberately *minimal synthetic header only*: GCC 14.2.0 and Clang 17.0.0 each passed `-std=c2x -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror -fsyntax-only` on two TUs (four syntax-only checks total); Python 3 verifier bytecode compile PASS. This excludes genuine source linkage, module symbols and runtime.

Focused workflow [run 45588178607](https://github.com/k1moradi/swapz/actions/runs/45588178607), [job 139115074685](https://github.com/k1moradi/swapz/actions/runs/45588178607/job/139115074685), **QUEUED at evidence snapshot, actual GCC/Clang executed tests 0, first new error none observed, artifact unverified**. It is rooted in actual corrected main source 70fbbe12..., checks real `github.event.before`, pristine pins and source policy, stages reversible R089 compressor/decompressor corrections only in disposable host copies, then compiles actual original Linux LZO1X/LZ4 translation units plus existing typed decoder, bridge and fixture under strict GCC/Clang ASan/UBSan. Planned evidence covers original codec 1/2, 4096 output, CRC/SHA/malformed/alias, M3568 and isolated M4095, four concurrent readers, bounded 64 tokens, ABA rejection, failure output, lower callback propagation and no live activation. Pending is NOT success. First actual CI error, if any, must be recorded without suppression or blind rerun.

No VM qualification, boot, physical mutation, privileged/loaded swap action, manual dispatch, PR, branch, force push, production or upstream Linux change. **AUTH=0; Phase A BLOCKED; direct compressed handoff OFF; forced RAW bypass OFF; import OFF.** GO dormant source review only; NO_GO live until exact CI and integration authority/lifetime/ABI blockers resolved.

## Exact failed first source and new corrective source (no duplicate dispatch)

Initial corrected source `70fbbe12c84db56283b5e0812faf1fc8032bbae4` ran at
[run 45588178607 / job 139115074685](https://github.com/k1moradi/swapz/actions/runs/45588178607/job/139115074685):
**FAIL at repository policy preflight, before original checkout or any compiler**.
Actual first error was
`SOURCE_CONTRACT_MISMATCH`, path
`.github/workflows/phase-a-round090-original-decoder-lease-host-noauth.yml`,
reason **missing same-commit non-whitespace applicable testing-standards update**;
exit 1 at preflight line 11. The initial source's standards restoration
was followed by a workflow-only correction, and a previous-commit standards
edit cannot qualify the workflow's own source revision. The first error
does not demonstrate a C compiler failure or a decoder defect.
Actual pinned GCC/Clang executions **0**, artifact **none**.

**New independent corrective source**
[a240810314b5951a618619049654c2887e14d2d4](https://github.com/k1moradi/swapz/commit/a240810314b5951a618619049654c2887e14d2d4),
sole parent `edbbe54e32dc02e64e054dc78cb0423a1228dc5a`,
published directly to main by fresh expected-HEAD nonforce single-parent
fast-forward. Two changed files only: actual host fixture
`tests/runtime/native/fixtures/round090-original-decoder-bridge.c`
blob `651986d5e70bf96dd7f7652ffc772a46997fe6e5`
and applicable `docs/testing_standards.md`
blob `3ae03a457a3af62d8e5149cfe305c87e741c50ac`.
The test source adds **six independent source-linked negative requests**:
null compressed source, null record token, short scratch, short verified,
short output, and aliased scratch/verified working pages. Both null-pointer
cases check every output byte remains untouched. New standards state their
exact required refusal semantics and strict pinned-codec host qualification.
No decoder production code, frozen interfaces, peers' source paths, Kbuild,
original Linux or sanitizer settings were modified. The previous failure
remains in evidence; this is a new source qualification, not a rerun of
unchanged source or an evidence-only policy evasion.

[Automatic new source run 45591425899](https://github.com/k1moradi/swapz/actions/runs/45591425899),
[job 139126333980](https://github.com/k1moradi/swapz/actions/runs/45591425899/job/139126333980),
**QUEUED at recorded inspection**: GCC/Clang source-linked execution
NOT_RUN, results/case counts unverified, artifact none and no new first
error yet. No manual dispatch, rerun, VM, physical action or periodic
monitoring. Historical R089 corrected isolated original codec sanitizer
PASS is unchanged and not counted toward this bridge qualification.

**Current Agent7 disposition: CORRECTIVE_SOURCE_PUBLISHED_CI_QUEUED /
NO_GO_LIVE.** Genuine independent module-owner hard refs, generation-
bearing nonrecycled decoder handles, actual selected-source auth and
integrated Kbuild/link/durable upper ACK remain unqualified. AUTH=0,
Phase A BLOCKED, compressed handoff/forced RAW bypass/import OFF.
