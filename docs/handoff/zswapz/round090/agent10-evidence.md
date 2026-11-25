# Round090 Agent10 — latest frozen R089 compile/link only

**Terminal CI FAILURE: 6/6 original directed objects PASS; product compile FAIL; full links NOT_RUN. AUTH0; Phase A BLOCKED; all activation OFF.**

## Terminal CI reconciliation — exact frozen source, attempt 1

**FAILURE at product-directed-object; original directed objects 6/6 PASS, full kernel/module link NOT_RUN.** The snapshot below is historical; this terminal section supersedes its pending fields.

Actual [run 45586120960](https://github.com/k1moradi/swapz/actions/runs/45586120960) / [job 139108048304](https://github.com/k1moradi/swapz/actions/runs/45586120960/job/139108048304) completed failure (exit2). Exact source `d183f5d5127992b406013799bcb81ea3f59e93eb` sole parent `edf44c4417f14b5836b1b5f90157e24916afcde2`. Downloaded [artifact 15008368383](https://github.com/k1moradi/swapz/actions/runs/45586120960/artifacts/15008368383) (28948 bytes), independently verified archive SHA256 `02ce3ad2492be35c9311ac2224072872adf725775b7af7154ea230c72cd36280`, parsed results.json, raw-stage-manifest.json, effective.config and both actual compiler logs. Artifact records object hashes, not object binaries; no independent binary inspection or symbol claim. Raw manifest and final result postimages agree 8/8. Effective config independently hashed `89127024a38ad68dd091c9dd5787bba097b85c8ce69d118cd147a8d7ff4c6d0b`. Compiler GCC 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1), linker GNU ld 2.42. Canonical policy, pristine checkout, raw apply check/application, all 8 raw postimages and compatibility overlays, scratch Kbuild, ELF header/link/userspace execution, OpenSSL prerequisite and config passed. R089 missing gelf.h is resolved on this runner. One build attempt, no repeat.

| Directed object | Actual result | Git blob of object (CI manifest) |
|---|---|---|
| `block/bio.o` | PASS | `38319c8c7f01ab8c5ada67da04a40215cd8e4d95` |
| `drivers/md/dm.o` | PASS | `73a36c7c423a6e816aa8450587f770f31c571d60` |
| `mm/page_io.o` | PASS | `4c0d647e5586e89a3563446ec058731dde7682d0` |
| `mm/round090-swapz/codec.o` | PASS | `bb6b4cbf152d0577e63d8189949904e6fd17037d` |
| `mm/round090-swapz/zswap-original-ticket.o` | PASS | `49d730547a205882e2eaec61a4284b1b967026d3` |
| `mm/zswap.o` | PASS | `b3bc89695b3b008339309ac247fa8c0b76cdda4d` |

Compilation scope: exact frozen originals plus authorized scratch-only three field substitutions in DM/core and target; the raw untouched DM source was not compiled. The directed product invocation attempted dm-target.o and authority.o, both failed; remaining product objects, vmlinux link, .ko link, module modpost and final symbol checks NOT_RUN. Host objtool and host modpost tool compilation is not product modpost qualification.

First actual compiler error (runner absolute paths omitted):

```text
linux/arch/x86/include/asm/current.h:28:17: error: ‘struct swapz_shared_original_record’ has no member named ‘get_current’; did you mean ‘current’?
authority.c:30:29: note: in expansion of macro ‘current’
```

Kernel `#define current get_current()` expands the product member token. Actual subsequent diagnostics at authority.c:57,68,230,2563 and 3759/3769; target inclusion fails on authority.h:834 (field declared as function). Frozen [authority.c](https://github.com/k1moradi/swapz/blob/9f7002c896f86226e93f0523b1f6e935de5c6de9/src/kernel/authority.c#L30) blob `73b3e2dc98c6a47315519d3ab650c3d3b0656de7`, [authority.h](https://github.com/k1moradi/swapz/blob/9f7002c896f86226e93f0523b1f6e935de5c6de9/src/kernel/authority.h#L834) blob `c320498ce530c0887bf498cc4d5b121765bb41f3`. Source readback on main before evidence publication showed these same two blobs. Minimal Agent5 correction recommendation: rename the shared-record member to `is_current` (all access/designated initializer/consumer and fixture references) and the local map pointer in swapz_authority_import_current to `current_mapping` (declaration, assignment and generation references); keep native kernel current macro intact; no warning suppression. No new scratch overlay or peer edits authorized for this error. Do not retry frozen failed source. Future genuinely changed integrated baseline needs separate authorization and compilation. This result does not qualify any same-round peer source or runtime path.

Terminal evidence-only update, no duplicate dispatch, no VM boot/build-for-VM, module load, physical mutation or activation. AUTH0, Phase A BLOCKED, compressed handoff/forced RAW/import OFF.

## Authority and publication

[ROUND_OPEN](https://github.com/k1moradi/swapz/issues/208#issuecomment-7157990926), immutable task `edf44c4417f14b5836b1b5f90157e24916afcde2`, frozen candidate [9f7002c896f86226e93f0523b1f6e935de5c6de9](https://github.com/k1moradi/swapz/commit/9f7002c896f86226e93f0523b1f6e935de5c6de9), original Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`. Read dedicated prompt, frozen contracts, checkpoint, agent/evidence/scheduling policy and relevant operating context. No same-round peer source dependency. [New source d183f5d5127992b406013799bcb81ea3f59e93eb](https://github.com/k1moradi/swapz/commit/d183f5d5127992b406013799bcb81ea3f59e93eb), sole parent `edf44c4417f14b5836b1b5f90157e24916afcde2`; verified fresh-head single-parent nonforce main fast-forward. Only new compile verifier, narrow workflow and append-only testing standards. Prior full standards blob `3bc8692b5f71a5d31c9caba1b858dde8a28ab1f6` roundtrip verified and preserved; new `b3d32260fcd0cc4cb877fc06e3802b5130709678`. No frozen or peer source edits.

- [Verifier](https://github.com/k1moradi/swapz/blob/d183f5d5127992b406013799bcb81ea3f59e93eb/tests/tools/round090-original-composed-compile-verify.py) blob `226da88ee74ca5bce626f164a711548794bfd16f`.
- [Workflow](https://github.com/k1moradi/swapz/blob/d183f5d5127992b406013799bcb81ea3f59e93eb/.github/workflows/phase-a-round090-original-composed-compile-noauth.yml) blob `adbbe58eec60e2e0bf3ebe933eebafa895b59627`.

## Actual prior terminal failure and prerequisite correction

Read actual R089 [job 139078028312 logs](https://github.com/k1moradi/swapz/actions/runs/45577221648/job/139078028312). Raw apply check, raw apply, raw postimage diff, scratch diff and config steps passed. Directed objects build began then failed with actual first error: `linux/tools/objtool/include/objtool/elf.h:10:10: fatal error: gelf.h: No such file or directory`, exit2, no successful directed-object milestone or full link. [R089 artifact 15004369076](https://github.com/k1moradi/swapz/actions/runs/45577221648/artifacts/15004369076) metadata verified, 25381 bytes, digest `sha256:d6de57c65fb59219d79880722d20930e6cb26a37922400583e2ba2fb45fe9107`; artifact contents not independently unpacked this turn. R089 terminal evidence already present on main, not overwritten. Obsolete R088 composition not rerun.

Actual local rootless GCC14.2 probe including gelf.h/libelf.h and linking -lelf failed: `<stdin>:1:10: fatal error: gelf.h: No such file or directory` (exit1). Local git ls-remote failed `Could not resolve host: github.com`; only nonmatching Linux 6.12 headers available. No substitute kernel build. New runner provisions libelf-dev, libssl-dev, compiler/binutils, bc/bison/flex, pkg-config, OpenSSL, Perl, Python, xz/cpio; checks 20 named tools, pkg-config libelf and OpenSSL, strict actual GCC ELF header/link probe and executes the harmless userspace probe against its own ELF file, before Kbuild. Package install uses ephemeral runner package permissions only, no privileged test. Actual new CI prerequisite execution pending; no claim of corrected prerequisite PASS.

## Frozen input and raw/compatible postimages

Actual connector in-memory hunk reconstruction validated old lines, hunk counts and independently computed Git blobs for all eight raw outputs, seven existing preimages and one new header. Verified MM patch `059d1bf29cf4990e22a2f608d5d552abeec3a8d1`, corrected DM patch `3ccbb9eaca06021176d52dd14888ce281af43990`; 39 product directory file identities pinned from frozen census, full map in JSON. Not actual new raw git apply; real CI requires unchanged pristine git apply --index --unidiff-zero --whitespace=error --check and application, exact eight postimages, actual SHA256 and diff check.

| Path | Pristine blob | Predicted raw postimage |
|---|---|---|
| `mm/zswap.c` | `ae19e301fced7e357a4c7587dfdd6abb890b9163` | `8bf7e885376c5ef521adf40b1ec736e062067bff` |
| `include/linux/swap_ops.h` | `57ac6c703f685883d3a15ebc1a5c7f6c298deb1b` | `a39a1921daf6f272e9812eb63b1aa64fec96c57f` |
| `include/linux/blk_types.h` | `0cc09b975d8ffbd45ca3dc47533a71f8e8164de6` | `0bf866c1571fe6b4d2e49d01b1b2c87fcf2cf04c` |
| `include/linux/bio.h` | `7a794ce723b84b2a148f8f9beccf057b266e8ac9` | `f4c5f1730514cf1816ffd5e9787562439dfae236` |
| `block/bio.c` | `b0fcc69de653524479e3b328aa29a37e97945b84` | `3ba0e12a96ba3235eb909e3b3dd0be44657c6f6e` |
| `mm/page_io.c` | `c6824fcd483e0aa2c412e14dae0d2a356b17c373` | `0b0fe917fa3af5deaef8263274edffbf1a62eedb` |
| `include/linux/swapz_mm_carrier.h` | absent | `72100483b42a59db8f522d3f2f4ee10d4f856550` |
| `drivers/md/dm.c` | `1881d86111fb2e655893ad898cf21b88f0e4e7f3` | `59ff578305062e9a63f900a661c6ce0cf3d8a9eb` |

Authorized compatibility-only correction after raw stage: pinned bvec.h `b63914ff56e33df302055fabf2a84ba490bc8d2c` declares bi_offset, not bi_bvec_done. Exactly two obsolete field references in unique core expression and one in unique product target expression replaced in scratch only. No other C source edits. Independent predicted hashes:
- Core raw `59ff578305062e9a63f900a661c6ce0cf3d8a9eb` -> compatible `5dfce1e9dc97fe210c6125a85396e5168eaeb445`.
- Product target raw `1b103767e1783ed48cf79b1c9e5654f8d99f646e` -> compatible `1951989aaf56680a3c1b900cb00d4c6c1ac0fb2d`.

Raw and compatibility manifests kept distinct; CI must check both hash sets. Any compilation is compatibility-stage scope, not untouched raw compile. No claim that this resolves all API issues or makes the selected route valid. Additional scratch Kconfig and Makefile changes only, real ticket/codec bytes built in, real product Makefile augmented for original extent, storage/shared authority and decoder components, actual original/core/target guard enabled. Product C/H except target field overlay remains frozen. No mock APIs or peer changes. Actual kernel and product object compile, vmlinux link, module modpost and symbol inspection required. Feature refusal preserved; not deployed integration.

## Actual new CI snapshot

[Run 45586120960](https://github.com/k1moradi/swapz/actions/runs/45586120960), [job 139108048304](https://github.com/k1moradi/swapz/actions/runs/45586120960/job/139108048304), exact source `d183f5d5127992b406013799bcb81ea3f59e93eb`, attempt1 push main, created 2026-11-25T09:30:53Z, IN_PROGRESS. Actual setup, source checkout, canonical exact source/parent/policy/diff and frozen baseline checkout completed successfully. Linux checkout in progress, package provision and stage/build pending. First new CI error none observed; build attempts observed0. No new actual ELF probe, raw application, compatible stage, directed objects, vmlinux, module, modpost, artifact or unresolved-symbol result yet. One focused native x86 compile/link attempt only after preflight; first actual diagnostic retained, no blind retries. No runtime or VM qualification.

Nine inherited automatic workflow runs on this source push observed, not manually initiated; A9 owns routing. No cancellation or periodic monitoring. No branches, PR, force, peer edits, physical mutation, loaded or privileged test, VM build-for-VM or boot. Linux MM/zswap exclusively owns compressed RAM/natural eviction; swapz disk packing/GC, no recompression, protected SWAPSPACE2 and ordinary 20-byte map preserved. RAW_4096 full original uncompressed page. Source authentication0, Phase A BLOCKED, direct handoff/forced RAW/import OFF. Terminal evidence of this same new run remains required.


## Agent1 independently verified reconciliation
Agent1 independently extracted artifact15008368383, SHA256 02ce3ad2492be35c9311ac2224072872adf725775b7af7154ea230c72cd36280, results.json actual single attempt, original-directed-objects PASS, product-directed-object failed, child_exit2. Actual source namespace collision, not an ELF prerequisite anymore. R091 compile latest immutable R090 candidate (including R090 lifetime overlay and DM patch), authorize only scratch-only exact member/local identifier correction for Linux current macro; no #undef, no peer-file edit. Retain raw-vs-overlay distinction and original build artifacts; no boot.
