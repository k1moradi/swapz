# Agent4 Round060 — genuine original selected decoder GPL export and module-bound linkage

Official [ROUND_OPEN #177](https://github.com/k1moradi/swapz/issues/177#issuecomment-7065333937)
with last actual engineering `55c0eca070cbd21a0e153990e4859ec914d45232`
and task `73bc67e9233ba71b1f460827706cdb26a0996ad2`.
This is **compile-only** and no production module or original Linux source changes.

## Exact original symbol and driver distinction

The pinned exact Linux source contains
`lib/lzo/lzo1x_decompress_safe.c:291 EXPORT_SYMBOL_GPL(lzo1x_decompress_safe)`,
the `CONFIG_LZO_DECOMPRESS` library module
`lib/lzo/lzo_decompress`,
`lib/lz4/lz4_decompress.c:708 EXPORT_SYMBOL(LZ4_decompress_safe)`,
the separate `CONFIG_LZ4_DECOMPRESS` library module
`lib/lz4/lz4_decompress`, and
`lib/crypto/sha256.c:270 EXPORT_SYMBOL(sha256)`.
Original `crypto/lzo.c` calls the same library decoder through
`lzo-scomp`; `crypto/lz4.c` calls the original raw LZ4 decoder
through `lz4-scomp`. The selected source compression transform
is **not** a surviving independent decoder-owner/module reference.
Eleven original Git blobs, header signatures, export macro type,
real original build Makefiles and source driver associations are
checked by SHA and original source semantics before a kernel build.

## Bounded native verification

The new test-only fixture contains the **actual** existing
`swapz_zswap_import_decode` function and real swapz CRC32C
translation unit. Its emitted reference function is compiled
under native pinned Linux Kbuild `W=1 KCFLAGS=-Werror`; there
is no stub/alias fake original decoder and the test module
init unconditionally returns `-EOPNOTSUPP` to refuse activation.
The original pinned Linux x86 ZSWAP=y and ZSWAP=n builds
produce their own vmlinux, modules and `Module.symvers`.
The strict module-side validator demands real symbol CRC/export/
provider/config identity, module external unresolved references
to original LZO/LZ4 and sha256, matched GPL module license/
vermagic and independent ELF `.modinfo` decoder library dependencies
when modules are configured `m`.

A separate **negative** native build deliberately references
one unexported symbol, and may pass only if real original
`modpost` rejects that exact missing-export symbol; missing
kernel tools, C compiler failure or unrelated errors cannot be
counted. Seven additional negative source provider/config/export
cases test the pre-Modpost parser. The existing exact-source
Round059 generic LZ4-only gcc/clang ASan+UBSan and ten executed
changed-code semantic mutants are rerun; the existing real
original LZO1X/LZ4 host reader's 4096-byte CRC/SHA/EOF contract
remains unchanged and explicit LZO opt-in preserved.

## Explicit non-authorized boundary

Even original x86 GPL modpost SUCCESS can prove only that native
kernel decoder symbols can link independently of the original
`crypto_acomp` source compressor. It does **not** prove an
acquired/released live module reference during source-pool teardown,
a currently accepted source+DM BIO lease, durable imported WRITE,
current volatile map/GC/read, single upper ACK or loaded end-to-end
full 4096 read. Kernel module refcount lifetime after retired
pool remains NOT_AUTHENTICATED, NO_GO until separate actual
source-to-target evidence. `SOURCE_MAPPED_AUTHENTICATED=0`,
`PHASE_A=BLOCKED`, compressed handoff and forced RAW bypass
DISABLED; first physical 4096 SWAPSPACE2 and partition table
unchanged. No root or physical/test owner make actions.
