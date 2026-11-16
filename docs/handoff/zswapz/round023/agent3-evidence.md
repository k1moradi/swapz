# Round023 Agent 3 — disabled DM typed LZ4 import transaction

Frozen contract: docs/handoff/zswapz/round023/frozen-cross-component-contract.md
Official issue: https://github.com/k1moradi/swapz/issues/140#issuecomment-6928573299

The actual src/kernel/dm-target.c contains a #if0 import boundary only;
the existing compiled ordinary 4096 original-page BIO admission, RAW,
LZ4/delta64/SHUF8 codec, lower-write completion, mapping publication,
GC/discard and exact upper ACK are unchanged. No production import
decoder invocation/flag/transport is enabled. A new independent header
zswap-import-admission.h builds a strictly mock-only staged transaction
with source↔DM slot generation translation, immutable compressed LZ4
record, CRC32C, independent full-page SHA256, existing 4/8/16KiB
payload-only deterministic-zero padded lower extent and correct lower
full-extent byte completion. Upper ACK is authorized only after
successful complete lower write and RAM mapping publication. A full
lower READ plus current GC/slot identity permits existing exact
LZ4-decode+SHA original 4096 readback; errors do not expose partial
output or claim a successful completion.

The true live admission helper unconditionally returns -EOPNOTSUPP
even when a test presents a credible mock slot mapping. The host fixture
under tests/runtime/native/fixtures/round023-consumer-admission.c
runs the exact new helper functions and original imported decoder,
real codec.c CRC32C, liblz4 and OpenSSL SHA256 under GCC/Clang strict
warnings+sanitizers. Negative tests cover fake authority, wrong slot,
different source and DM generations, invalid extent/offset/header guard,
partial/failed lower WRITE, early/duplicate ACK, stale GC, partial/
failed READ, corrupted compressed CRC/SHA, original byte mismatch,
discard/teardown and output sentinel integrity.

The source has no real kernel-authenticated compressed carrier,
known real zswap store-time original SHA, source epoch ownership across
clones, loaded DM authority, or real 4096 kernel swap-in. All new
positive fixtures use synthetic user-space identities explicitly
MOCK/UNTRUSTED. No module, swap, pressure, RAM-device or SWAPSPACE2
physical trial performed. Phase A BLOCKED; Phase B forced RAW bypass
and direct compressed transport DISABLED; current RAW original
UNCOMPRESSED full 4096. Physical SWAPSPACE2 first header/UUID/table
untouched; codec/GC mapping only bounded volatile RAM.
