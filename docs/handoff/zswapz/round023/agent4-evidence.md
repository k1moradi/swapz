# Round 023 — Agent 4 independent frozen source cross-ABI audit

Official opener: https://github.com/k1moradi/swapz/issues/140#issuecomment-6928573299
Frozen task baseline: dd08a3dbc8309da266f49f975b6733cd33a25a8d
Current source: Round022 compile-disabled producer + standalone consumer.

This change adds only new owned cross-ABI test files and CI. The Python
test extracts the actual #if0 pinned-Linux producer C from the existing
stager and the actual host shim, compiles it with the original swapz
LZ4 imported decoder and original production codec.c, then executes real
GCC and Clang warning-clean ASan/UBSan C. The separately authored C adapter
must explicitly map mock producer slot and store-generation to distinct
synthetic DM logical page, DM generation and GC epoch. The mapping is
MOCK/UNTRUSTED and has no actual Linux MM/BIO owner or transport authority.

Positive fixture: one genuine userspace LZ4 block of 4096 original bytes
→ source-model zpool entry → copied immutable producer payload
→ original SHA recorded at synthetic store → canonical kernel
~crc32c(~0U) → production swapz_crc32c_bytes → consumer exact
LZ4 block decoded 4096 → separately checked SHA256/memcmp. Reject old
IEEE CRC32 and raw crc32c(0) (9-byte known vector distinguishes them),
missing mock source authority, source slot/epoch/DM generation mismatch,
unsupported codec/version/dictionary, bad length 0/>3568, corrupted
CRC/SHA, partial lower read, no durable write/mapping/upper ACK,
duplicate upper ACK, teardown, aliased buffers and once-only source
completion. No successful upper read or partial output on rejection.

Important source boundary: no original Linux source has authenticated
zswap store-time SHA/generation transport to DM; a rootless mock does
not establish this. Real booted modified Linux, loaded matching DM,
owned ephemeral RAM, real stored eviction or actual 4096 kernel readback
have NOT_RUN status. No physical SWAPSPACE2 header/UUID/partition
operation, module, swap or memory pressure performed. Current RAW is
ORIGINAL UNCOMPRESSED 4096, no compressed handoff/forced RAW bypass
enabled, Phase A BLOCKED.


## Original exact-source CI first failure and correction

The first pinned new workflow on SHA f6bb8f5e8b7c9045e3afb889459f747dd730f9bf,
run #43953308556, genuinely FAILED GCC and Clang compilation:
zswap_swapz_owned_payload_abort was unused in the new excerpt;
existing production codec.c emits size_t→swapz_u32 conversion warnings.
No runtime decoded 4096 result may be claimed for that failed run.
A negative assertion now exercises abort refusal after submit. The Python
compiler pipeline builds unchanged original codec.c separately with
-Werror and explicit -Wno-conversion only on its translation unit;
the extracted producer/consumer C fixture retains strict
-Wall -Wextra -Werror -Wconversion -Wshadow ASan/UBSan.
This isolates existing production warnings without modifying/weakening
new fixture source or touching any kernel/device.
