# Round 001 — Agent 5 bio-abi-safety report (archived GitHub submission)

- **Original GitHub report:** https://github.com/k1moradi/swapz/issues/118#issuecomment-6892193939
- **Task commit:** `b6817ac41f96a0e7df4b0f5f3af258e582723b9e`
- **Frozen source baseline:** `c128ac32374a753a0b27ae0ebec67693355b1b55`
- **Agent-stated task outcome:** PASS (source review/model only; ABI remains blocked)
- **Original issue-comment body SHA-256:** `5150c6ac592f8022902af1d88ec6e99a7d15b2d04dd275815fa99601a76dd2fd` (UTF-8, excluding archival wrapper)
- **Archival date:** 2026-11-15 UTC
- **Evidence boundary:** Reporter results below are attributed to the agent, not independently rerun or Phase A kernel qualification.

---

message: REPORT_READY
round: "001"
agent: 5
task_id: agent5-bio-abi-safety
status: PASS
source_sha: c128ac32374a753a0b27ae0ebec67693355b1b55
task_commit_sha: b6817ac41f96a0e7df4b0f5f3af258e582723b9e
kernel_source_sha: c339f4010dea8b0d754f84ace70cd1b089878ef8
modified_files: []
scratch_artifacts:
  - agent5-bio-abi-safety-report.md
  - agent5_bio_provenance_model.c
tests:
  - command: "gcc -std=c23 -O1 -g -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror -fsanitize=undefined -fno-sanitize-recover=all agent5_bio_provenance_model.c -o build/check-gcc-ubsan && UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 ./build/check-gcc-ubsan"
    exit_code: 0
  - command: "clang -std=c2x -O1 -g -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror -fsanitize=undefined -fno-sanitize-recover=all agent5_bio_provenance_model.c -o build/check-clang-ubsan && UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 ./build/check-clang-ubsan"
    exit_code: 0
  - command: "gcc -std=c23 -O1 -g -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror -fsanitize=address,undefined -fno-sanitize-recover=all agent5_bio_provenance_model.c -o build/check-gcc-asan && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./build/check-gcc-asan"
    exit_code: 0
  - command: "Exact patched Linux Kbuild, KUnit, loaded clone/split and genuine zswap writeback"
    exit_code: NOT_RUN
evidence_class: source-review
additional_evidence_class: rootless
carrier_approval: BLOCKED
phase_a_qualification: BLOCKED
phase_b: DEFERRED
blocking_findings:
  - "B0-3a: header-only capability cannot prove runtime struct bio ABI or kernel provenance"
  - "B0-3b: mixed-origin whole-BIO false positives without producer homogeneity"
  - "B0-3c: real kernel clone/split/requeue/reset/lifetime remains untested"
  - "B0-3d: scalar helper predicate accepts intentionally forged exact tags"
next_round_recommendations:
  - "Agent 1 pin exact source/config/image and enforce module identity"
  - "Agent 2 test producer/BIO in exact patched kernel across config and clone/split"
  - "Agents 3/5/6/8 jointly require source-bound real writeback and negative controls"
fixture_sha256: f8e371d61162ca9f8bf9aeb5d527b5ebe5e93540e1aeab961438c90db6645112
report_markdown_sha256: f1ff8c687f03055ac4f9e6b9a32385de093a3a14c9afd71be2be98a80c293bb8

---

# Agent 5 — Round 001 independent BIO ABI and provenance safety review

**Task result: PASS (source audit and rootless negative probe only).**  
**Concrete carrier approval: NO-GO / BLOCKED. Phase A and Phase B: NOT QUALIFIED.**

## Source identity and independence

- `task_id`: `agent5-bio-abi-safety`; task revision `b6817ac41f96a0e7df4b0f5f3af258e582723b9e`; frozen **swapz source** `c128ac32374a753a0b27ae0ebec67693355b1b55`; [round issue #118](https://github.com/k1moradi/swapz/issues/118).
- Kernel under review: [torvalds/linux `c339f4010dea8b0d754f84ace70cd1b089878ef8`](https://github.com/torvalds/linux/tree/c339f4010dea8b0d754f84ace70cd1b089878ef8), whose unmodified headers **do not contain** Agent 2's custom origin field/helper. Proposal reviewed from [historical #116 producer comment](https://github.com/k1moradi/swapz/issues/116#issuecomment-6890555852), **not** another Round 001 worker report.
- Independent prior risks: [#117 B0-3](https://github.com/k1moradi/swapz/issues/117). Production `swapz` target source was read at the frozen source SHA, not treated as provenance-enabled.
- Execution sandbox kernel `6.18.57`; available `/usr/src` headers `6.12.107+deb13` and `6.12.63+deb13`; **no actual matching 7.3-development patched kernel tree or running image**. Compilation of the producer or module on that source and real kernel instrumentation were **NOT RUN**.
- **No repository files, production C, GitHub branches, commits, PRs, worktrees, mapper, swap, or physical devices were changed.** Scratch fixture stays unpublished. Evidence classes: exact upstream/repository GitHub source review + local C23 model with sanitizers.

## Severity-ranked findings

### B0-3a — BLOCKER: header capability is not runtime BIO ABI proof

Agent 2 proposes `u8 bi_swap_origin` directly after `u8 bi_bvec_gap_bit` in [include/linux/blk_types.h lines 201–240](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/include/linux/blk_types.h#L201-L240), plus an inline header helper and `BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN` macro in [include/linux/bio.h lines 43–51](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/include/linux/bio.h#L43-L51). In the actual **unpatched** kernel neither proposed member nor helper exists.

The independent 64-bit **prefix model** places the newly consumed byte at offset **31**, in padding before `atomic_t __bi_remaining` at offset **32**; both simplified prefix structures remain **48 bytes**. This is *not* a measured offset or `sizeof(struct bio)` from patched Kbuild, especially across configuration and architecture. Critically, **unchanged size would not prove compatibility**. A module compiled with custom headers may read a formerly unused byte while the actual stock kernel's BIO allocator/clone path does not initialize or propagate it. An intentionally seeded former-padding byte produced a false verified-origin result in the model. Matching `UTS_RELEASE`, `vermagic`, module-name or header macro alone cannot prove the runtime kernel has the patched implementation; module symbol-version checks alone must not be used as an origin-propagation proof.

**Required gate:** identify the exact image, generated config/headers, compiler/architecture/4KiB page configuration, `Module.symvers`, and loaded module SHA/source build stamp. Compile producer and consumer from that **same patched kernel tree**. Record full actual `sizeof/offsetof(struct bio, bi_swap_origin/__bi_remaining/bi_max_vecs)`, `BIO_RESET_BYTES`, and `sizeof/offsetof(struct swap_iocb, bio/bvecs)` for selected configs/arches, plus stock-fallback compile with no macro. Reject a positive-origin capability if runtime patch provenance cannot be proven. This gate cannot be replaced by the prefix model.

### B0-3b — BLOCKER: a copied whole-BIO tag does not establish per-page authenticity

Unpatched [mm/page_io.c `swap_can_merge()` around lines 323–340](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/page_io.c#L323-L340) checks swap-device and `sis->ops->can_merge`, **not origin**. Agent 2's proposal adds WRITE-only `ctx->sio->swap_origin != ctx->swap_origin` refusal, stores the origin on the `swap_iocb` when it is allocated, and stamps the backing BIO after `bio_init`. This is a reasonable **conditional** whole-BIO homogeneity scheme but is not in the pinned upstream source and has not passed a real kernel test.

For a homogeneous aggregate of eight 4KiB entries, cloning/splitting can safely propagate the same scalar. For an incorrectly tagged mixed aggregate `Z,UNKNOWN`, every cloned 4KiB child inherits the single `Z` scalar, including the **ordinary** second page. The model reproduced this conditional false positive; copying is fidelity, not authenticity. The producer must split at a provenance boundary, create a separate aggregate, or conservatively downgrade ambiguous pages to UNKNOWN **before any whole-BIO positive tag is assigned**.

**Required gate:** on the exact built kernel, prove both orderings `Z→UNKNOWN` and `UNKNOWN→Z` with `swap_can_merge` flush boundaries, larger/multi-segment folios, bvec offsets, and inherited-only positive tags. Test positive homogeneous `Z→Z`, unknown `UNKNOWN→UNKNOWN`, and negative stale or malformed tags. Use a trace tied to the same validated zswap entry/slot and 4KiB logical page, not just a successful helper call or global `zswpwb`.

### B0-3c — BLOCKER: full BIO clone/split/reset and DM replay are kernel-owned, not header-owned

Actual [block/bio.c `bio_init()` lines 217–261](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/block/bio.c#L217-L261) explicitly initializes existing fields and requires Agent 2's **new assignment** to clear origin. [`bio_reset()` lines 274–286](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/block/bio.c#L274-L286) calls `memset(..., BIO_RESET_BYTES)`, and [`bio_reuse()` lines 304–325](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/block/bio.c#L304-L325) calls reset. The proposed placement is before the reset boundary, so reset should clear it **if built in the same patched layout**.

Actual [`__bio_clone()` lines 876–910](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/block/bio.c#L876-L910) omits origin; the proposed patch adds a copy. [`bio_alloc_clone()` and `bio_init_clone()` lines 918–955](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/block/bio.c#L918-L955) use it. [`bio_split()` lines 1926–1965](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/block/bio.c#L1926-L1965) allocates a clone and advances the original, retaining the latter's fields. The [generic split path](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/block/blk-merge.c#L120-L159) calls `bio_split`; [DM `alloc_io()` and `alloc_tio()`](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/drivers/md/dm.c#L571-L657) call `bio_alloc_clone`, including the embedded first target clone and additional clones. These paths are conditionally covered by the proposed `__bio_clone` copy on this **one** source revision; no claim extends to unrelated kernel versions.

[DM map requeue](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/drivers/md/dm.c#L1413-L1462) frees target clones on `DM_MAPIO_REQUEUE`; a subsequently remapped BIO requires fresh correctly inherited source metadata and descriptor reinitialization. Every upper descriptor admission must reset UNKNOWN *before queue publication*. Completion, error and retry must not retain pointers into the zswap entry, folio or source BIO past the existing ownership lifetime. None of the loaded requeue/recycling/lifetime interactions was executed here.

**Required gate:** exact-image KUnit or source-linked tests exercising initialization, allocation, reset, reuse, cloning, splitting, DM first/additional clone, requeue, plus descriptor reuse and error/abort paths. A source-extracted or hand-written model cannot substitute for real kernel functions.

### B0-3d — HIGH: helper predicate is not a trusted-origin verifier by itself

Agent 2's proposed inline helper merely checks `(bio_op == REQ_OP_WRITE) && REQ_SWAP && (bi_swap_origin == 1)`. It correctly **rejects** READ, missing `REQ_SWAP`, and invalid enum values. However, an **intentionally forged exact value `1` on a REQ_SWAP WRITE passes**; the model asserts this fact. Source authentication comes from controlling all setters and proving the MM stored-entry validation, not from the helper. Treat a forged exact value as an **adversarial negative control**, not a passing safety test.

[mm/zswap.c `zswap_writeback_entry()` lines 1005–1090](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zswap.c#L1005-L1090) checks the entry equals the slot tree's current object, successfully decompresses it, then later invokes `__swap_writeout`. The proposed origin assignment after decompression and before writeout is source-plausible; the `swap_io_ctx ctx = {}` default is UNKNOWN. But this is **not tested** with a real stored-entry eviction. `CONFIG_ZSWAP=n` removes the nonzero origin producer; unsupported headers must leave every origin UNKNOWN without interpreting generic `REQ_SWAP` or reclaim hints.

**Required gate:** independent audit of **every** writer of the new scalar and of all paths that construct/clone/reissue a BIO; instrument the authenticated producer boundary with same-entry correlation and force malformed/forged values in negative kernel tests. Do not present that helper as cryptographically authenticating a BIO.

## Independent rootless fixture — reproduced results

Source file: `agent5_bio_provenance_model.c` (local scratch, SHA-256 recorded below). It models the proposed ABI prefix and key scalar transitions, **does not include kernel headers**. Its scenarios cover tagged/unknown, READ and missing `REQ_SWAP`, malformed scalar, absent capability, cloned and homogeneous split fragments, both mixed-origin boundary orders, stale/reused descriptor, an injected forged tag, a deliberately poisoned old padding byte, and whole-BIO smearing.

```text
GCC 14.2.0 C23, -O1 -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror -fsanitize=undefined: PASS, exit 0
Clang 17.0.0 C2x, same warnings and UBSan: PASS, exit 0
GCC 14.2.0 C23, -fsanitize=address,undefined: PASS, exit 0
Observed model-only: prefix size=48, origin offset=31, remaining offset=32.
The intentionally forged and padding cases are ACCEPTED by the helper, confirming an unsafe outcome if upstream trust/lifecycle gates fail.
```

All statements about origin layout above are expressly limited to a conventional 64-bit *prefix model*. No actual kernel `struct bio` `sizeof`, module runtime layout, `bio_split` or zswap writeback was executed here.

## Minimum acceptance matrix for the next round

| Case | Genuine positive | Genuine negative / expected fallback | Required evidence |
| --- | --- | --- | --- |
| Source | Matched stored entry and decompressed order-0 folio | Initial zswap rejection, stale slot, failed decompression, `CONFIG_ZSWAP=n` | In-kernel zswap/KUnit instrumentation |
| Aggregation | Z→Z homogeneous | Z→UNKNOWN and UNKNOWN→Z split/downgrade; larger folio mixed | Actual `swap_can_merge()` and `swap_iocb` |
| Block | Initialized Z tag copied by kernel `__bio_clone`/`bio_split` | Missing flags, invalid enum, fresh/reused stock BIO | Kernel clone/reset/KUnit |
| DM | Both clone sites preserve genuine 4KiB tag | Neighbor unknown; requeue/descriptor reuse stays unknown | Compiled/loaded DM target + source-bound logs |
| Module ABI | Headers/build image/module agree, tests pass with enabled capability | Stock kernel build compiles to unknown fallback; mismatched image **refused** | Exact kernel image/config/source stamp, Kbuild W=1/W=2, loaded test |
| Passive effect | Verified origin observed at successful logical commit, byte-exact readback | Ordinary/unknown unchanged codec attempts, representation, CRC, generation | Agent 6/8 owned `null_blk` qualification |

**Overall verdict:** **NO-GO for approving this concrete BIO carrier or reporting Phase A integration.** B0-3 is **not independently closed**. The proposed patch is a plausible, constrained starting point after exact-kernel pinning; it is not a stock interface and the capability macro is insufficient runtime proof. Do not implement Phase B or promote current baseline CI to zswap-provenance acceptance.

**Recommendations:** Agent 1 selects a target kernel and image-identity mechanism; Agent 2 supplies exact-image producer+BIO Kbuild/KUnit and mixed-origin traces; Agent 3 keeps default-UNKNOWN fallback; Agent 5 independently rechecks the integrated patch and B0-3; Agent 6 and 8 require genuine-origin, readback and matched module evidence. All remain future-round actions, not dependencies of this report.

## Reproducible standalone fixture (local scratch only)

The following three commands were executed from the local scratch directory containing `agent5_bio_provenance_model.c` and a `build/` subdirectory. Every compilation and execution returned **exit 0**. Compilers: GCC 14.2.0 and Clang 17.0.0.

```sh
gcc -std=c23 -O1 -g -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror -fsanitize=undefined -fno-sanitize-recover=all agent5_bio_provenance_model.c -o build/check-gcc-ubsan && UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 ./build/check-gcc-ubsan
clang -std=c2x -O1 -g -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror -fsanitize=undefined -fno-sanitize-recover=all agent5_bio_provenance_model.c -o build/check-clang-ubsan && UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 ./build/check-clang-ubsan
gcc -std=c23 -O1 -g -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror -fsanitize=address,undefined -fno-sanitize-recover=all agent5_bio_provenance_model.c -o build/check-gcc-asan && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./build/check-gcc-asan
```

Fixture SHA-256: `f8e371d61162ca9f8bf9aeb5d527b5ebe5e93540e1aeab961438c90db6645112`.

<details><summary>Complete independent source-derived fixture (C23)</summary>

```c
/*
 * Agent 5 Round 001: independent SOURCE-DERIVED MODEL for Linux c339f401...
 *
 * Deliberately does NOT include Linux kernel headers, execute kernel BIO
 * clone/split, or prove authentication. Source-pinned kernel implementation
 * is independently reviewed in the accompanying report.
 *
 * This fixture models the edited struct bio prefix on 64-bit architectures
 * and tests the difference between propagating a scalar and proving its
 * origin. It does not qualify a kernel or a kernel module.
 */
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* Sizes chosen from the pinned source field types on a conventional LP64 ABI.
 * Kernel configuration, compiler ABI and actual struct bio layout must
 * separately be checked with Kbuild on each selected target. */
struct stock_bio_prefix {
    void *next;
    void *block_device;
    uint32_t operation_and_flags;
    uint16_t flags;
    uint16_t priority;
    uint32_t write_hint;
    uint8_t write_stream;
    uint8_t status;
    uint8_t gap_bit;
    uint32_t remaining;
    void *vectors;
};

struct patched_bio_prefix {
    void *next;
    void *block_device;
    uint32_t operation_and_flags;
    uint16_t flags;
    uint16_t priority;
    uint32_t write_hint;
    uint8_t write_stream;
    uint8_t status;
    uint8_t gap_bit;
    uint8_t swap_origin;
    uint32_t remaining;
    void *vectors;
};

_Static_assert(sizeof(struct stock_bio_prefix) ==
               sizeof(struct patched_bio_prefix),
               "The one-byte field can occupy padding in this model");
_Static_assert(offsetof(struct stock_bio_prefix, remaining) ==
               offsetof(struct patched_bio_prefix, remaining),
               "Model downstream offsets remain equal");
_Static_assert(offsetof(struct patched_bio_prefix, swap_origin) ==
               offsetof(struct patched_bio_prefix, gap_bit) + 1,
               "Origin immediately follows gap bit");

enum {
    bio_operation_mask = 0xFFu,
    bio_read = 0u,
    bio_write = 1u,
    bio_request_swap = 0x1000u,
    origin_unknown = 0u,
    origin_verified = 1u,
};

static void initialize_patched_bio(struct patched_bio_prefix *bio,
                                   uint32_t operation_and_flags)
{
    /* Analog of the pinned patch's explicit field reset in bio_init().
     * The model's other fields are initialized here for simple isolation. */
    memset(bio, 0, sizeof(*bio));
    bio->operation_and_flags = operation_and_flags;
    bio->swap_origin = origin_unknown;
}

static void reset_patched_bio(struct patched_bio_prefix *bio,
                             uint32_t operation_and_flags)
{
    /* Pinned bio_reset() zeros BIO_RESET_BYTES: the proposed field is
     * before __bi_remaining, which is before the reset boundary. */
    initialize_patched_bio(bio, operation_and_flags);
}

static void clone_patched_bio(struct patched_bio_prefix *destination,
                              const struct patched_bio_prefix *source)
{
    initialize_patched_bio(destination, source->operation_and_flags);
    /* Analog of the proposed single __bio_clone() assignment. */
    destination->swap_origin = source->swap_origin;
}

static int helper_accepts_origin(const struct patched_bio_prefix *bio)
{
    /* The patch's helper is a predicate, not authentication of a producer. */
    return (bio->operation_and_flags & bio_operation_mask) == bio_write &&
           (bio->operation_and_flags & bio_request_swap) != 0 &&
           bio->swap_origin == origin_verified;
}

static uint8_t selected_origin(uint32_t operation_and_flags, uint8_t scalar,
                                int kernel_api_present)
{
    if (!kernel_api_present)
        return origin_unknown;
    struct patched_bio_prefix bio;
    initialize_patched_bio(&bio, operation_and_flags);
    bio.swap_origin = scalar;
    return helper_accepts_origin(&bio) ? origin_verified : origin_unknown;
}

struct aggregated_bio {
    uint8_t origin;
    unsigned pages;
};

static int can_merge(const struct aggregated_bio *aggregate,
                     uint8_t next_origin)
{
    /* The patch's swap_can_merge() extra equality condition for WRITE. */
    return aggregate->origin == next_origin;
}

int main(void)
{
    const uint32_t swap_write = bio_write | bio_request_swap;
    struct patched_bio_prefix tagged;
    struct patched_bio_prefix clone;
    struct patched_bio_prefix remainder;
    struct aggregated_bio aggregate;

    initialize_patched_bio(&tagged, swap_write);
    assert(!helper_accepts_origin(&tagged));
    tagged.swap_origin = origin_verified;
    assert(helper_accepts_origin(&tagged));

    clone_patched_bio(&clone, &tagged);
    assert(helper_accepts_origin(&clone));
    /* A 32 KiB homogeneous BIO split into eight 4 KiB parts: each
     * cloned part keeps the single verified scalar, while the unsplit
     * remainder is independently unchanged. Real bio_split is NOT run. */
    remainder = tagged;
    for (unsigned page = 0; page < 7u; ++page) {
        struct patched_bio_prefix child;
        clone_patched_bio(&child, &remainder);
        assert(helper_accepts_origin(&child));
        assert(helper_accepts_origin(&remainder));
    }

    assert(selected_origin(swap_write, origin_verified, 0) == origin_unknown);
    assert(selected_origin(swap_write, origin_unknown, 1) == origin_unknown);
    assert(selected_origin(swap_write, 2u, 1) == origin_unknown);
    assert(selected_origin(bio_read | bio_request_swap, origin_verified, 1) ==
           origin_unknown);
    assert(selected_origin(bio_write, origin_verified, 1) == origin_unknown);

    aggregate = (struct aggregated_bio){ origin_verified, 1u };
    assert(!can_merge(&aggregate, origin_unknown)); /* verified then ordinary */
    aggregate = (struct aggregated_bio){ origin_unknown, 1u };
    assert(!can_merge(&aggregate, origin_verified)); /* ordinary then verified */
    aggregate = (struct aggregated_bio){ origin_verified, 1u };
    assert(can_merge(&aggregate, origin_verified)); /* homogeneous */
    ++aggregate.pages;
    assert(aggregate.pages == 2u);

    /* Reuse for a *new* transaction must reset a stale tag. A re-submission
     * of the SAME transaction can carry the original scalar unchanged. */
    clone_patched_bio(&clone, &tagged);
    assert(helper_accepts_origin(&clone));
    reset_patched_bio(&clone, swap_write);
    assert(!helper_accepts_origin(&clone));

    /* Critical negative: an exact scalar forged on an otherwise ordinary
     * REQ_SWAP WRITE is accepted by the helper. Producer identity, not the
     * helper itself, must establish provenance. */
    initialize_patched_bio(&clone, swap_write);
    clone.swap_origin = origin_verified; /* forged, no stored zswap entry */
    assert(helper_accepts_origin(&clone));

    /* Whole-BIO smearing: a wrongly marked mixed BIO makes EVERY
     * downstream cloned child a false positive. Correct producer
     * aggregation must split origins or downgrade to UNKNOWN first. */
    const uint8_t true_page_origins[2] = { origin_verified, origin_unknown };
    struct patched_bio_prefix mixed_bio;
    initialize_patched_bio(&mixed_bio, swap_write);
    mixed_bio.swap_origin = origin_verified;
    for (unsigned page = 0; page < 2u; ++page) {
        struct patched_bio_prefix child;
        clone_patched_bio(&child, &mixed_bio);
        assert(helper_accepts_origin(&child));
        if (page == 1u)
            assert(true_page_origins[page] == origin_unknown);
    }

    /* Stock-layout compatibility pitfall: with a same-sized struct, the
     * location where patched code expects the scalar is stock padding.
     * This intentionally writes a chosen byte to MODEL a possible dirty
     * padding value. It is NOT a measurement of stock kernel padding. */
    struct stock_bio_prefix stock = {0};
    stock.operation_and_flags = swap_write;
    const size_t origin_byte = offsetof(struct patched_bio_prefix, swap_origin);
    ((unsigned char *)&stock)[origin_byte] = 1u;
    struct patched_bio_prefix mismatched;
    memcpy(&mismatched, &stock, sizeof(mismatched));
    assert(helper_accepts_origin(&mismatched));

    printf("PASS: independent source-derived ABI/predicate model; "
           "stock/patched prefix bytes=%zu, origin offset=%zu, "
           "remaining offset=%zu; intentional forged/padding "
           "false positives reproduced\n",
           sizeof(stock), origin_byte,
           offsetof(struct patched_bio_prefix, remaining));
    return 0;
}
```

</details>
