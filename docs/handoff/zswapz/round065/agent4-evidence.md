# Round065 Agent4 — actual native diagnosis and narrow verifier correction

Official #182, ROUND_OPEN 7075223683. Pristine original Linux
`c339f4010dea8b0d754f84ace70cd1b089878ef8`; no Linux/product/fixture
source edits. Prior exact source 180f310978815a4767d99b481b2b5444f6ff981a.

## Actual native evidence

Both [original diagnostic run #44991824557](https://github.com/k1moradi/swapz/actions/runs/44991824557)
native jobs 137114479192/y and 137114479171/n and
[integrated run #44992035145](https://github.com/k1moradi/swapz/actions/runs/44992035145)
native jobs 137117590339/y and 137117590349/n are terminal FAILURE
only at the previous strict positive symbol parser. Each matrix:
- Original defconfig, olddefconfig, vmlinux, modules, external positive GPL
  modpost and genuine Kbuild preprocessor PASS.
- Actual saved command compile_only=1 werror=1 host_test_macro=0,
  source_header_dependency=1 original_lz4_header_dependency=1.
  y command hash 67f92b602816809b01fe97a43f197609c41a119e6d09335417d3f9a496410734;
  n command hash 2d186945bad490929cff56c15425b768e0e66acd57e73530c17594635742ea7b.
- Actual preprocessed LZ4 and LZO1X once each, tag1 and tag2 compared.
  SHA256 is via the existing helper and retained in ELF.
- Original LZO_DECOMPRESS=y, LZ4_DECOMPRESS=y, MODULES=y; both
  original decoder providers vmlinux; LZO1X EXPORT_SYMBOL_GPL and
  LZ4 EXPORT_SYMBOL, SHA256 EXPORT_SYMBOL. Both configs actual
  same-kernel CRC fields 0x00000000.
- Real consumer, combined and final ELF: for each selected LZO1X,
  LZ4 and SHA256, undefined=1 text_relocations=1 defined=0.
  Product CRC defined=1 in codec.o and final link, undefined=0 final.
- Real native missing-export negative modpost rejected specifically
  absent original decoder export; actual staged source LZ4 omission
  mutation retains other selected original refs, but LZ4 undefined=0
  text_relocations=0 defined=0 in consumer and final.
- All four exact native jobs: ROUND064_NATIVE_RESULTS
  positive=1 diagnostics=0 missing_export_negative=0 omitted_branch_negative=0.
  First error: compiled module did not retain original decoder link
  LZ4_decompress_safe retained=lzo1x_decompress_safe,sha256 missing=LZ4_decompress_safe.

## Root cause and correction

Prior run_checked() strips global leading whitespace. Prior nm -u
regex requires one or more leading whitespace characters per record.
GNU nm sorts uppercase LZ4_decompress_safe first; the leading whitespace
of that record alone is stripped. Real native diagnostics proved the
actual reference is present through all link stages. Rootless actual
GCC and Clang consumer symbol controls independently reproduced this
specific parser false rejection. No evidence of any LZ4 code-generation
or final-link loss. Change only exact strong undefined record parsing in
existing strict verifier: split line into exactly two fields, strong U
type and complete selected name. Preserve all other gates, actual
kernel consumer source, fixture, diagnostic inspector and workflow.

## Targeted rootless test

Strict GCC and Clang each compiled three actual objects, baseline,
omission and similarly named LZ4_decompress_safe_partial substitution.
Actual nm -u and readelf -rW both check exact refs; old regex fails first
record on each baseline, corrected gate accepts both, rejects all four
real exact-symbol negatives. Three additional parser controls reject
defined, weak or extra-token records.
ROUND065_NM_FIRST_RECORD_REGRESSION_PASS real_objects=6 exact_symbol_negatives=4 record_negatives=3.
Structural symbol test only, not full native or actual codec C semantic
test. Added to existing source-host self-test; existing genuine GCC/Clang
ASan/UBSan ten executed original codec mutants and all four native gates
remain mandatory. Corrected exact-source CI pending. No duplicate rerun
or cancellation of existing builds. No runtime/module-life or production
AUTH admitted, no owner Make, privilege, loaded, physical or actual
pressure. AUTH0/Phase A BLOCKED/direct and forced RAW disabled,
RAW_4096 whole original uncompressed page, protected SWAPSPACE2.
