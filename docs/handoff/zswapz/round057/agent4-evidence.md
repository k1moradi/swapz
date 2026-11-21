# Round057 Agent4: original LZO first-error source-only fix

Official issue #174 comment 7061417569 and Agent1 checkpoint 7061875421.
Frozen engineering SHA `1c89862e5293b12401923fd092d3753c6797d1aa`;
frozen task SHA `193f9985ecda40b014c02a4f7877fdd83803dcf4`.

Two original LZO workflows were really **RED** on frozen engineering:
[GCC decoder #44892251604](https://github.com/k1moradi/swapz/actions/runs/44892251604)
encountered original `lib/lzo/lzo1x_decompress_safe.c:154,175,195,273,279,283,287`
`-Werror=sign-conversion` after incorrectly giving pristine upstream
source the product-only warning policy (ancestor job 136808017167).
[Clang codec profile #44892251810](https://github.com/k1moradi/swapz/actions/runs/44892251810)
encountered UBSan misaligned `u32 *` store at exact original
`lib/lzo/lzo1x_compress.c:137` (ancestor job 136808017188).

The pinned untouched `lib/lzo/lzodefs.h` uses `COPY8`/`COPY4` with
unaligned loads and stores. Original bytestream output offsets need
not be aligned; buffer-base alignment alone cannot repair the issue.
A separately executed Clang17 `-O1 -fsanitize=address,undefined
-fno-sanitize-recover=all` C reproducer with the original host
adapter and output+1 showed the UBSan fault; replacing the shim
`memcpy` input with `const void *` and output with `void *`
made the same reproducer PASS with sanitizers unchanged. The fix
is strictly to the two host adapter scripts, not to original Linux.

The original decoder script now pins six original per-file Git blobs
and compiles original Linux C separately at native `-Wall -Wextra
-Werror`; own fixture and real `src/kernel/codec.c` remain strict
with `-Wconversion -Wshadow` too. The decoder fixture guarantees
original `unsigned short` compressor workspace alignment.
Each dedicated original workflow must independently prove GCC+Clang
4096-byte CRC/SHA/trailing-input/unchanged-output baseline and
compiled/executed real C mutant rejection. These fresh exact-source
CI results were pending when the source fix was written; do not
claim LZO pass from the local macro reproducer.

Source-mapped authentication=0; Phase A BLOCKED, direct compressed
handoff DISABLED and forced RAW bypass DISABLED. Ordinary RAW_4096
is full uncompressed original 4096. Protect full physical first
4096-byte SWAPSPACE2 and parent partition table. Original 70
genuine KUnit boot success at `1c89862` is independent and does
not authenticate live target ownership or durable lower I/O/ACK.
No owner make/fast tests, privileged or loaded kernel, actual
swap, memory pressure or physical device trials.

## First exact-source CI diagnostic and bounded correction

Initial Agent4 published commit `85c763a653bb5f4b4bcd6086182cf080b94ddbdb`
registered original decoder [run #44901525313](https://github.com/k1moradi/swapz/actions/runs/44901525313),
job `136838254455`. Its actual first error advanced past original
decompressor sign conversion: GCC `gcc/baseline/compile/original-lzo-compressor`
reported `linux/unaligned.h:4` `-Werror=discarded-qualifiers` at the
host `get_unaligned` temporary initialized through `memcpy`. The prior
`__typeof__(*(pointer))` produced a `const u32` local when the pristine
`COPY4` passed a `const u32 *`. Host-only
`__typeof__(*(pointer) + 0)` removes that local const qualification
via integer promotions without weakening upstream warnings or UBSan.
An independent local source-adaptor C reproduction passed GCC 14.2
and Clang 17 with ASan/UBSan and `-Wall -Wextra -Werror`. This is not
a full original LZO proof; report fresh exact-source CI terminal logs.
