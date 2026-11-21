# Round054 Agent4 — first GCC metadata-size red repaired; actual host C execution

## First real error, correction and scope

The previous exact-source codec job [44851393073 / 136683323930](https://github.com/k1moradi/swapz/actions/runs/44851393073/job/136683323930) failed before executing a baseline or mutant. The latest combined source `713541c26f35ed812ebe75bb8c481169bdf98d3b` workflow [44851585788 / 136683938849](https://github.com/k1moradi/swapz/actions/runs/44851585788/job/136683938849) is also terminal FAILURE. The remaining actual GCC `-Werror=conversion` in `swapz_attach_extent_metadata` was caused by the record-size operand's promotion of the expression to size_t before its assignment to swapz_u32. The corrected local variable is size_t, with natural sizeof arithmetic on the existing u8 count; the only consumer remains equality to metadata->length, and the existing static assertion bounds the largest possible descriptor prefix to 4096. No truncation, ABI/layout, data CRC, encoding, 3568 compressed cap, or ordinary uncompressed RAW behavior changes.

## Genuine executed rootless local host evidence (not GitHub or loaded-kernel evidence)

The isolated host compiler sandbox could not resolve github.com for a Git checkout. Actual source files were retrieved using the authorized GitHub connector at exact immutable refs, transferred byte-exact, and verified with Git blob hashes locally before test execution. The local tests used the real product codec.c, codec.h, fixture, runner compile_and_execute, and the exact function body extracted by the runner's function_limits from the byte-verified pristine pinned original crypto/lz4.c blob. The local invocation did not execute the runner's full Git-checkout admission main() because no original checkout was available; CI retains all HEAD, cleanliness and original-source anchor checks intact. Original crypto_acomp/zswap/Kconfig anchors were also checked from pinned remote files. Do NOT claim a local pristine Git checkout or live original kernel execution.

| File | Tested Git blob |
|---|---|
| src/kernel/codec.c (corrected) | `d920dcaac6f2b7de1334d4133770bd649719c66d` |
| src/kernel/codec.h (unchanged) | `e89d316b9cf49f82df0b77648c1be1731607987d` |
| actual codec C fixture (expanded) | `b3da79cb0f7b8cf84a845c85a0eeb590abea6f54` |
| actual runner (updated) | `041d91a6ee496dd8d9c46c1c3fde2c3ea95e4d61` |
| torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8 crypto/lz4.c | `57b713516aefac823f2af9481c828027b42490dd` |

Local GCC 14.2.0 and Clang 17.0.0, liblz4 1.10.0 and OpenSSL 3.5.7. Actual flags: `-std=gnu11 -O1 -g -Wall -Wextra -Wconversion -Wshadow -Werror -fno-omit-frame-pointer -fsanitize=address,undefined -fno-sanitize-recover=all`. No new diagnostic exception; the previous narrowly scoped exact upstream wrapper-only signedness exception remains unchanged. Strict actual product baseline C compilation and execution succeeded under BOTH compilers with empty stderr and each emitted:

```
ROUND052_HOST_RAW_LZ4_SUBSET_PASS seed_cases=96 assertions=52776 source_authenticated=0 physical_io=0
```

Both compilers also actually compiled and executed all thirteen function-scoped changed source variants, nonzero exit **exactly 1** through the genuine fixture CHECK assertion, without compiler errors, sanitizer diagnostics or signals. An independent direct execution additionally captured these first assertion lines (GCC / Clang line differences for multi-line expressions reflect compiler macro location reporting):

| Mutant | First CHECK (GCC/Clang) |
|---|---|
| extent-invalid-class | 257 / 257 |
| append-3568-cap | 278 / 278 |
| append-unknown-encoding | 330 / 331 |
| append-over-capacity | 327 / 328 |
| seal-empty | 264 / 264 |
| seal-cursor | 282 / 282 |
| seal-zero-padding | 285 / 285 |
| read-3568-cap | 308 / 308 |
| read-unknown-encoding | 295 / 295 |
| read-outside-payload | 317 / 317 |
| read-no-generation | 298 / 298 |
| read-crc-invert | 287 / 287 |
| crc32c-implementation | 256 / 256 |

The baseline 96 deterministic patterns include refusal/fallback on incompressible/unadmitted input; never claim all 96 compressed successfully. Every admitted page now additionally passes the ACTUAL swapz RAM extent begin/append/seal/read path, verifies returned record length and CRC32C, then the host raw-block decoder verifies all 4096 original bytes plus SHA256. The original 3568/3569/4096 admission boundary, distinct encoding and framing refusal, exact full uncompressed RAW fallback, 4/8/16 KiB payload-only extent/zero padding and protected header sentinel are retained. New actual metadata tests reject length/count zero, count 255 and length 65535, check scratch sentinel unchanged, detach then correctly attach a valid snapshot and compare the entire 4096-byte image, and refuse reattachment to already-populated scratch without mutating it.

The runner refuses any sanitizer diagnostic including recoverable UBSan errors and any unexpected successful-exit stderr; the actual executed C marker and assertion count are emitted per compiler. All 13 previous mutation definitions are unchanged. The real CI workflow still requires exact pinned original checkout with source-anchor verification; the local successful C executions do not replace terminal exact-new-SHA GitHub CI, same-original-KDIR matched product module builds, native/policy or packaged validation. Progress must be reported until those actual gates execute.

## No authorization

This is strictly HOST_RAW_LZ4_SUBSET, LIVE_KERNEL_COMPRESSOR=NOT_RUN. Kconfig default LZO and runtime selected original crypto_acomp may differ from swapz raw LZ4/delta64/shuf8. Zswap solely bounded compressed RAM naturally evicted by Linux MM; swapz solely existing valid SWAPSPACE2 disk packing and GC. Ordinary RAW_4096 always full original UNCOMPRESSED 4096. No current typed counted source slot incarnation/pre-unuse cancellation owner, current DM table/map/GC/dtr lease, actual lower write, map or genuine ACK/readback proved. First physical 4096 bytes and partition table untouched. SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED FORCED_RAW_BYPASS=DISABLED. No owner make test, make fast_test, privilege, loaded module, physical swap, real MM pressure, or device activation was performed.
