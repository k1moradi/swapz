# Round033 Agent2 — actual original pinned Linux GPL provider export audit and independent same-source modpost

Frozen task source `90069e3bef16a5cc2a1e442a4597551f48f464c6`, original Linux exact `torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8`, accepted earlier composed true original MM+BIO source. Agent2 owns **only** source workflow validation, original provider byte-audit negative fixture, this evidence and a full preserved canonical same-commit testing standards update; no Agent3 DM work or source original C changes absent a demonstrated compiler defect.

## Exact historical first failure — reproduced

[Round032 source run 44168876688](https://github.com/k1moradi/swapz/actions/runs/44168876688), job **134342259183 FAILED exit 3** at the first `CONFIG_ZSWAP=y` original kernel `Module.symvers` GPL export audit. Earlier exact full original source and GCC+Clang strict ASan/UBSan had PASS; real source-built original `vmlinux`, `modules`, original `Module.symvers` generated; original UML source KUnit job 134342258299 **PASS 11/11**. After checking the original source-generated symbol, historical audit printed the plausible canonical raw row `0x00000000<TAB>swapz_ci_bio_snapshot_lz4_v1<TAB>vmlinux<TAB>EXPORT_SYMBOL_GPL<TAB>` and then reported it absent.

**Root cause demonstrated independently:** original awk was split as:

```awk
$2 == "swapz_ci_bio_snapshot_lz4_v1" &&
  $3 == "vmlinux" && $4 == "EXPORT_SYMBOL_GPL"
  { found++ } END { exit(found != 1) }
```

In AWK this is **TWO separate rules**: matched rows are printed implicitly and `{found++}` counts EVERY unrelated symbol row. Local rootless literal-row reproduction: a single target row prints and exits 0, while target + an unrelated genuine original-style symbol row still prints only the target but exits 1. Thus old full Module.symvers job failed whenever more than one kernel symbol was present. This fully explains the printed row plus false `found != 1`; however, the historical full original Module.symvers bytes were not archived, so the row's exact original namespace/count and strict independent modpost remain unproven until a new full exact-SHA CI run. We **do not** claim original GPL probe succeeded in Round032.

## Minimal scoped source fix

- `.github/workflows/phase-a-zswap-composed-source.yml`: keep all genuine original pinned Linux y/n full source/manifest, original C strict Werror, original default-gate negative, actual original vmlinux/modules/Module.symvers, original 11/11 booted UML, and exact source-matched dm-swapz.ko. Replace ONLY the faulty awk audit with strict original binary Module.symvers Python byte validator and phase-bound checked first fatal diagnostic, require exactly one original `vmlinux EXPORT_SYMBOL_GPL` target, print actual original row hex + complete SHA256. Preserve separate GPL probe `round032-bio-probe.c` real modpost; do not fake, allow unresolved or skip.
- `tests/runtime/native/fixtures/round033-provider-symbol-gate.py`: no extra runtime dependency, file-byte validator with exact 5 tab fields, original 8-digit CRC, expected symbol/module/export, explicit empty namespace, duplicate suppression, changed bytes/CRLF/extra columns/truncated row/oversize/swap suffix/invalid CRC fail closed. Rootless self-test includes a byte-exact canonical positive with another unrelated export, all adversarial negatives, and **literal reproduction of historical broken awk script** (false red on 2 rows). Self-tests run before real Linux source build, but only actual kernel's own `$out/Module.symvers` may authorize the source export and modpost.

## Pending exact-source hosted verification

Initial original Round032 red run and first cause remain traceable. The new Round033 exact commit should run genuine source-extracted GCC+Clang ASan/UBSan, full original CONFIG_ZSWAP=y and n source compiler + genuine vmlinux/modules/Module.symvers with actual export row hex and strict independent GPL external `.ko` modpost per profile, actual matched `dm-swapz.ko` ELF and vermagic, plus executed actual original pinned UML 11/11. No success may be asserted for uncompleted jobs; update issue #150 REPORT_READY with actual first new failure, patch lineage and exact source SHAs.

## Safety

`PHASE_A=BLOCKED`, `DIRECT_COMPRESSED_HANDOFF=NO_GO_DISABLED`, `FORCED_RAW_BYPASS=DISABLED`, `LOADED_KERNEL=NOT_RUN`, `PHYSICAL_SWAPSPACE2=NOT_RUN`; original RAW always original uncompressed 4096 bytes and original SWAPSPACE2 first 4096-byte header/UUID and partition table are immutable. zswap alone controls compressed RAM cache and eviction; swapz manages existing disk-backed swap without competing reclaim. Real exported module link is not live source-authenticated compressed data transfer, not real memory pressure eviction, nor physical full readback. No root/loaded/physical/mkswap/swapon/swappoff null_blk/reboot tests.
