# Round025 Agent3 — authentic DM mapping-generation seam, no live importer

Opening: https://github.com/k1moradi/swapz/issues/142#issuecomment-6939041436
Frozen source: 7c3b087e8af3a428b2703902653140ed4c9e7a5f
Round024 pinned source: c2469a86107f632dc795f4957113234f5bac62f6

Actual DM authority is a worker-owned volatile array of
`struct swapz_map` entries with generation, valid, raw, payload length
and CRC. Real lower completion `swapz_engine_complete_batched_run`
publishes mapping before upper ACK in the ordered worker; a synthetic
transaction cannot take that authority. There is no actual separate
authenticated source BIO owner, source-slot epoch or DM GC epoch that
could be deduced from caller-provided values.

New opt-in source C probe reads the real `ctx->authority.maps`, refuses
stale map generation, immutable length/CRC mismatch, forged GC epoch,
early ACK, teardown, wrong upper 4096 or lower IO failure, and ALWAYS
refuses compressed publication even if a synthetic input looks good.
GCC and Clang `-Werror -fsanitize=address,undefined` compiled fixture
negative paths EXIT 0 locally; see C fixture and Python exact-source
extractor. This is NOT booted or full module Kbuild evidence.
The existing production C GitHub workflow compiles and links a real
kernel `dm-swapz.ko` x86-64/ARM64 opt-in profile, requiring both
Round024 and Round025 function symbols. Its exact source SHA, compiler
outcomes and first error must be checked after publication.

LOADED=NOT_RUN; 4096_KERNEL_SWAPIN=NOT_RUN; PHYSICAL=NOT_RUN;
LIVE_COMPRESSED=DISABLED; PHASE_A=BLOCKED; PHASE_B_RAW_BYPASS=DISABLED.
SWAPSPACE2 protected header/UUID/table untouched; ordinary RAW original
uncompressed 4096 semantics retained, no physical write occurred.

## First true hosted source regression and correction

At 382ef9fbe06a6f2a6ced726300ca7364e862e7ad, GitHub Actions
`Experimental swapz production C qualification` run 44041248220 and
`Round023 source-only zswap compressed cross-ABI` run 44041248021
failed their actual Python test before compiler execution: existing
Round024 test observed two source compile guards, expected one
(`AssertionError: 2 != 1`), and the Round025 function extractor
used a double-escaped newline and found zero matching source anchors
(`AssertionError: 0 != 1`). New follow-up on peer-advanced sole main
corrects these *test only* defects, preserving all original kernel C,
existing comments, and all peer commits. Exact compiled C and Kbuild
outcomes must be checked on the corrected commit. No loaded success.
