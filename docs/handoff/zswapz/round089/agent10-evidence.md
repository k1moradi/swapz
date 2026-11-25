# Round089 Agent10 — frozen R088 MM/BIO + DM compile/link only

**Compile-only implementation published; CI QUEUED, actual pinned Linux compilation and linking NOT_RUN.** AUTH0; Phase A BLOCKED; all activation OFF.

## Authority and scope

[ROUND_OPEN](https://github.com/k1moradi/swapz/issues/207#issuecomment-7144215635), [Agent1 technical clarification](https://github.com/k1moradi/swapz/issues/207#issuecomment-7155918424), task commit `0c893ee7a3ffc158d747c11c96b67fcf0b3efa15`, immutable R088 baseline [db9252db73721a768be912965ad4402e332039e8](https://github.com/k1moradi/swapz/commit/db9252db73721a768be912965ad4402e332039e8). Read dedicated prompt, frozen contracts, R088 checkpoint, repository agent/evidence/scheduling rules and relevant operating context. No peer dependency. [New compile lane source d829c93cdf0b061a5b78cd177d7f4a458b9102eb](https://github.com/k1moradi/swapz/commit/d829c93cdf0b061a5b78cd177d7f4a458b9102eb), sole parent `c080db279bbf3f2c2d33d8d08926a04dfc7df4a3`, verified main expected-head single-parent nonforce fast-forward. Only new compile-only script, narrow push workflow and append-only testing standards changed. Full previous standards blob `de44823a377d7f31c0925be3648c4810fda4d7aa` roundtrip verified and prefix retained; new `d95a22312e1fe6c90062dfd859cbbea8461edf8a`. No production or peer patch changes.

- [Verifier](https://github.com/k1moradi/swapz/blob/d829c93cdf0b061a5b78cd177d7f4a458b9102eb/tests/tools/round089-original-composed-compile-verify.py) blob `ef9a1ffc6f508679bdad568e399eeb3165bdb63a`.
- [Workflow](https://github.com/k1moradi/swapz/blob/d829c93cdf0b061a5b78cd177d7f4a458b9102eb/.github/workflows/phase-a-round089-original-composed-compile-noauth.yml) blob `f9ee38ca4c03698e29b71728c4dd208948c43eb9`.

## Actual preflight evidence and prior failure

Retrieved actual prior [Round088 job 138675229125](https://github.com/k1moradi/swapz/actions/runs/45458753262/job/138675229125) logs. First observed error: `tests/tools/round088-original-dm-selected-clone.patch:70: space before tab in indent.` `git diff --check "$SWAPZ_PUSH_BEFORE_SHA" HEAD` exit 2. This occurred before raw git apply and before compiler; not proof of failed staging or C compilation. Frozen DM line70 is normal unified-diff context prefix followed by original tab indentation. No patch representation normalization applied. MM patch has zero-context hunks; dedicated lane uses explicit git apply --unidiff-zero format option with --index and --whitespace=error (no whitespace correction or ignore), and checks exact full pre/post blobs plus staged source diff.

Actual connector byte-level in-memory reconstruction: verified both frozen patch blobs, seven existing pristine original file blobs, every hunk context/deletion and exact line count, independently computed all eight expected postimage Git blobs. One new header has no preimage. No real raw git apply on full pinned checkout yet. Local synthetic rootless test with space-tab unified-diff context: git apply --check --unidiff-zero --whitespace=error then actual git apply on synthetic C file succeeded (Git 2.47.3); not frozen patch execution. Local actual Git connectivity failed: `fatal: unable to access 'https://github.com/k1moradi/swapz.git/': Could not resolve host: github.com`. Container only has nonmatching Linux 6.12 headers, no pinned checkout; no substitute build attempted. No local original compiler invocation, kernel link, module link or runtime test.

Frozen inputs:
- Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`; MM patch `b9a10044c7cd750d908730b5a95a4e945883ec45`; DM patch `e465dacabfb12fc93382143308e7ba1a188f59e6`.
- Pinned scratch Kbuild preimages mm/Makefile `2a3ec53d62eef629486b87736d560b1fa1798096`, mm/Kconfig `afff1b25b5438756f15e464f63dabdbd5ec6102c`.
- Exact product directory census and all 37 per-file pins embedded in verifier, including dm-target.c `cb0b20aa3a52a0a136e2a84e87b838d75a462e28`, ticket.c `dcea7cbc40094fed2997d6704c712ac47aa164a1`, ticket.h `b772cc28755a68719f4dcdabefeefe57b5efea67`, codec.c `d920dcaac6f2b7de1334d4133770bd649719c66d`, codec.h `e89d316b9cf49f82df0b77648c1be1731607987d`. Actual filesystem checks pending CI.

| Patched file | Original Git blob | Predicted postimage Git blob |
|---|---|---|
| `mm/zswap.c` | `ae19e301fced7e357a4c7587dfdd6abb890b9163` | `e3caa72ca37a7a3cdb3ed51639d9507b22fe4e51` |
| `include/linux/swap_ops.h` | `57ac6c703f685883d3a15ebc1a5c7f6c298deb1b` | `a39a1921daf6f272e9812eb63b1aa64fec96c57f` |
| `include/linux/blk_types.h` | `0cc09b975d8ffbd45ca3dc47533a71f8e8164de6` | `0bf866c1571fe6b4d2e49d01b1b2c87fcf2cf04c` |
| `include/linux/bio.h` | `7a794ce723b84b2a148f8f9beccf057b266e8ac9` | `f4c5f1730514cf1816ffd5e9787562439dfae236` |
| `block/bio.c` | `b0fcc69de653524479e3b328aa29a37e97945b84` | `3ba0e12a96ba3235eb909e3b3dd0be44657c6f6e` |
| `mm/page_io.c` | `c6824fcd483e0aa2c412e14dae0d2a356b17c373` | `0b0fe917fa3af5deaef8263274edffbf1a62eedb` |
| `include/linux/swapz_mm_carrier.h` | absent | `7ac3fe204983aa7ba5a291aa756d37e235f8508f` |
| `drivers/md/dm.c` | `1881d86111fb2e655893ad898cf21b88f0e4e7f3` | `59ff578305062e9a63f900a661c6ce0cf3d8a9eb` |

## Source-review correction candidate for Agent3

Frozen DM patch line56 and frozen product dm-target.c (selected guard) reference `bi_iter.bi_bvec_done`. Pinned original [include/linux/bvec.h:105-115](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/include/linux/bvec.h#L105-L115), blob `b63914ff56e33df302055fabf2a84ba490bc8d2c`, declares `bi_offset` instead. Likely source API mismatch; **not an observed compiler diagnostic**. Minimal owner review suggestion: use pinned `bi_offset` zero-offset test (and explicitly audit `bi_idx`, segment geometry and origin lifetime), not compatibility alias or fake stub. No Agent3 source/patch edits. Frozen R088 baseline remains as-is for actual compiler report.

## Actual new CI snapshot and compile boundary

[Run 45577221648](https://github.com/k1moradi/swapz/actions/runs/45577221648), attempt 1, exact source `d829c93cdf0b061a5b78cd177d7f4a458b9102eb`, created 2026-11-25T08:32:46Z, QUEUED. [Job 139078028312](https://github.com/k1moradi/swapz/actions/runs/45577221648/job/139078028312) `frozen-original-x86-compile-link` QUEUED; no step logs yet. First error for NEW CI null pending (not PASS). Actual build attempts observed 0; exact raw apply, actual postimage manifest, effective config, directed original and product objects, full vmlinux, external product .ko, modpost, unresolved-symbol inspection and artifact all pending. One new rootless x86_64 build attempt after actual preflight; no VM, no boot. Verifier first checks exact source/parent and clean SHA, policy, frozen checkout pins, raw git apply --check then actual apply, actual Git blob + SHA256 checks and source diff check, then scratch-only Kconfig and Makefile with real original ticket/codec bytes, x86 minimal Kconfig, three guards (MM Kconfig, broker and selected-DM defines), ZSWAP_DEFAULT_ON and KUNIT disabled. Directed real objects before full vmlinux and modules; external product module uses exact frozen Makefile and source bytes, generated version from VERSION, normal modpost and nm strong imports versus Module.symvers. No replacement APIs, no claimed active route, no duplicate full-link attempt after a failure. Logs and manifest retained in artifact on success/failure, no binary deployment. Full link vs object-only compile reported separately; even successful link is not runtime or source authentication.

No manual dispatch/rerun, no periodic monitoring, no peer source edits. GitHub auto-queued nine inherited workflows by latest source census (including old source-push and mixed routes, A9 owns routing); no manual initiation/cancellation. No new VM qualification authored by Agent10. Source authentication0; Phase A BLOCKED; direct compressed handoff/forced RAW/import OFF. Ordinary RAW_4096 full original uncompressed page, 20-byte ordinary map unchanged; original MM/zswap alone compressed RAM/natural eviction and swapz disk packing/GC. No physical mutation, module load, swap activation or privileged test. Next required evidence is the existing CI job's terminal compile/link diagnostics, not another dispatch.


## Agent1 independent reconciliation
Exact job 139078028312 terminal FAILURE. Independently downloaded artifact 15004369076, inspected raw-stage-manifest and results: raw unmodified patches apply/check/postimages 8/8 PASS, scratch Kbuild and config PASS, one build attempt failed during original-directed-objects: tools/objtool/include/objtool/elf.h:10:10 fatal error gelf.h missing, exit2. Config SHA256 89127024a38ad68dd091c9dd5787bba097b85c8ce69d118cd147a8d7ff4c6d0b. No successful directed object milestone or full kernel/module link; no VM. R090 compile latest frozen R089 candidates with verified prerequisite and explicitly authorized isolated pinned bvec compatibility overlay only if needed; old failure retained.
