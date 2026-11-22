# Round063 Agent4 — actual retained original decoder GPL ELF qualification

Official issue: https://github.com/k1moradi/swapz/issues/180
Original pinned Linux: torvalds/linux@`c339f4010dea8b0d754f84ace70cd1b089878ef8`
(11 original file blob SHAs remain pinned; no original source edits).

## Real prior native results, not inferred

Exact previous engineering `95f046e52a4d7976cf27c0676c12ce61fd09a570`:
[original decoder workflow #44964399878](https://github.com/k1moradi/swapz/actions/runs/44964399878).
Original source-host job137030049616 TERMINAL SUCCESS, including GCC+Clang
ASan+UBSan and ten compiled/executed original codec C semantic mutants.
Genuine original `ZSWAP=n` job137031209840 and
`ZSWAP=y` job137031209846 BOTH have exact native defconfig,
olddefconfig, full vmlinux, all modules and positive GPL modpost PASS,
then failed `ROUND060_DECODER_FIRST_ERROR compiled module did not
retain original decoder link LZ4_decompress_safe` during actual
compiled .ko `nm -u` verification. No negative missing-export
modpost was reached. Verified original Linux
`lib/lz4/lz4_decompress.c` separately exports
`LZ4_decompress_safe` and original `include/linux/lz4.h`
declares a real extern (not an inline alias).

## Narrow actual test-only source fix

The original build fixture had only an uncalled
`noinline __used` static wrapper of the actual imported
`swapz_zswap_import_decode()`. Root that unchanged function
through a retained static function-pointer relocation in the
**compile-only fixture**, and similarly root the intentionally
undefined negative test function. The real decoder C, selected
LZO1X/LZ4 branch logic and module_init always returning
`-EOPNOTSUPP` are unchanged. The native verifier additionally
requires both root and source function in actual `.ko` `nm -a`,
requires `nm -u` retain all original LZO1X/LZ4/SHA256 selected
references, and requires the real missing-export negative modpost
have exactly the expected undefined-symbol first cause without
competing compiler/header/modpost errors.

Local rootless strictly warned GCC and Clang C object test verified
that a `typeof(function)` `__used` function-pointer root
materializes an ELF data symbol and external relocation for both
independent selected codec probes. This mechanism test uses a
self-contained **structural** C fixture, NOT original module linkage.
Only separately completed original pinned kernel y/n CI can prove
the real module.

No loaded-kernel test, new product import admission, real I/O or
module ref lifetime was established. `SOURCE_MAPPED_AUTHENTICATED=0`,
`PHASE_A=BLOCKED`, direct compressed handoff/forced RAW bypass
DISABLED and ordinary RAW_4096 remains whole original uncompressed
4096; protected SWAPSPACE2 header/table unaffected.
