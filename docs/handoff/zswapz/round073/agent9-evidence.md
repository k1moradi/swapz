# Round073 Agent9 — SWAPSPACE2 header, geometry and 20-byte map

- **State:** IN_PROGRESS; exact-source GitHub Actions host qualification not yet terminal.
- **Task publication:** 5f4d74f1ea538187e37fa0cdec2babb49186c59d; engineering baseline 7c1ae38d41afb083345b1d7ec67b2d92d48b843a.
- **Source/test SHA and parent:** to be recorded in an evidence-only follow-up after exact-source CI; no unrun test is marked PASS.
- **Owned additions:** new Agent9 rootless fixture, verifier, dedicated workflow, report and JSON; same-commit canonical testing-rule appendix.
- **Exact read-only production inputs:** src/kernel/authority.h, src/kernel/superblock.h, src/kernel/codec.h, src/kernel/dm-target.c. Checker compiles unmodified headers, verbatim extracts the two production range/sector helpers, and hashes the source snapshots.
- **Boundary:** in-memory header and partition-table sentinels, not a selected real partition, actual lower WRITE, original Linux KUnit, physical safety admission or a loaded kernel. Payload padding is modeled after source-linked checks; neither real SWAPSPACE2 media nor any kernel is tested.
- **Coverage:** 20B volatile map static assertions, normal/swapped Linux swap header and negatives, 4/8/16KiB payload-only zero padding, immutable first 4096, sparse bad-page segment remap, exact-end boundaries, two reserve GC segments plus separate 256-block COW headroom, near-UINT32_MAX capacity rejection.
- **Mutation budget:** 15 different compiler-executed changed C semantics for each GCC and Clang with strict C2x, -Werror and ASan/UBSan if CI runs; pending, never counted as a PASS before execution.
- **First verified error:** none yet; run not terminal.
- **Release gates:** SOURCE_MAPPED_AUTHENTICATED=0, PHASE_A=BLOCKED, DIRECT_COMPRESSED_HANDOFF=DISABLED, FORCED_RAW_BYPASS=DISABLED, IMPORT_ACTIVE0. Ordinary RAW_4096 denotes all 4096 original uncompressed bytes. Linux MM/zswap solely controls compressed RAM natural eviction; swapz disk packing/GC only.
- **Next:** inspect exact immutable source CI once available, publish terminal separate evidence-only main commit and issue #190 message with BOTH commit-pinned file links; no periodic checks.
