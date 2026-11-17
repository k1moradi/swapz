#!/usr/bin/env python3
"""Stage verified zswap stored-writeback provenance in a complete pinned Linux tree.

This is a source mutation tool, NOT a patch generator or a kernel ABI claim.
Callers supply an untouched full torvalds/linux checkout. Nothing is fetched.
Only the six pinned C/H sources are changed; every original blob is verified
before any write. An all-file in-memory plan prevents partial preflight edits.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


LINUX_COMMIT = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
MINIMUM_TRACKED_FILES = 50_000
ORIGINAL_BLOBS = {
    "Makefile": "7e6baa461b91a79d12b5dcbce06795dd0ff37e81",
    "mm/zswap.c": "ae19e301fced7e357a4c7587dfdd6abb890b9163",
    "mm/page_io.c": "c6824fcd483e0aa2c412e14dae0d2a356b17c373",
    "include/linux/swap_ops.h": "57ac6c703f685883d3a15ebc1a5c7f6c298deb1b",
    "include/linux/blk_types.h": "0cc09b975d8ffbd45ca3dc47533a71f8e8164de6",
    "include/linux/bio.h": "7a794ce723b84b2a148f8f9beccf057b266e8ac9",
    "block/bio.c": "b0fcc69de653524479e3b328aa29a37e97945b84",
}


KUNIT_ORIGINAL_BLOBS = {
    "block/Kconfig": "70e4a66d941ff66ecb0ec34f4f7eff7fd1e4be40",
    "block/Makefile": "e7bd320e3d6971a8abf584f5de42776bb54e8216",
}
KUNIT_SOURCE_PATH = "block/swap-bio-origin-kunit.c"

# Git-blob identities of the unmodified pinned producer functions, except
# the staged writeback function which includes our single origin assignment.
# The complete upstream mm/zswap.c blob is also authenticated above. These
# bounds prove real control-flow ordering rather than a caller-set BIO bit.
PINNED_ZSWAP_PRODUCER_SLICES = (
    ("decompress", "static bool zswap_decompress(",
     "/*********************************\n* writeback code",
     "c0e1a14325e1bbee09e65cf6028cd68c68016af8"),
    ("writeback", "static int zswap_writeback_entry(",
     "/*********************************\n* shrinker functions",
     "eab8cd08a630aad73f6d20d48935b83428ebfac4"),
    ("shrinker", "static enum lru_status shrink_memcg_cb(",
     "static unsigned long zswap_shrinker_count(",
     "d24dacab8099ff5ca81ba2f04a3ccba2968b5b33"),
    ("store", "static bool zswap_store_page(",
     "bool zswap_store(struct folio *folio)",
     "3628dacfe6c56773e8703e35bb6126c4a4ab136d"),
)


@dataclass(frozen=True)
class Edit:
    before: str
    after: str


# Anchors copied from actual upstream C/H at the pinned Git blob IDs above.
# Every replacement is exact, unique, and tested against the full source.
EDITS: dict[str, tuple[Edit, ...]] = {
    "include/linux/blk_types.h": (
        Edit(
            "#define BLK_QC_T_NONE\t\t-1U\n\n/*\n * main unit of I/O",
            "#define BLK_QC_T_NONE\t\t-1U\n\n"
            "/* Only a verified zswap stored-entry eviction can set nonzero. */\n"
            "enum swap_bio_origin {\n"
            "\tSWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN = 0,\n"
            "\tSWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK = 1,\n"
            "};\n\n/*\n * main unit of I/O",
        ),
        Edit(
            "\tu8\t\t\tbi_bvec_gap_bit;\n\n\tatomic_t",
            "\tu8\t\t\tbi_bvec_gap_bit;\n"
            "\tu8\t\t\tbi_swap_origin; /* scalar source, never encoding */\n\n"
            "\tatomic_t",
        ),
    ),
    "include/linux/bio.h": (
        Edit(
            "\t(op_is_write(bio_op(bio)) ? WRITE : READ)\n\n"
            "static inline bool bio_flagged(",
            "\t(op_is_write(bio_op(bio)) ? WRITE : READ)\n\n"
            "/* Capability of this *built* kernel; absent from stock headers. */\n"
            "#define BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN 1\n\n"
            "static inline bool bio_is_zswap_stored_writeback(const struct bio *bio)\n"
            "{\n"
            "\treturn bio_op(bio) == REQ_OP_WRITE &&\n"
            "\t\t(bio->bi_opf & REQ_SWAP) &&\n"
            "\t\tbio->bi_swap_origin == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;\n"
            "}\n\n"
            "static inline bool bio_flagged(",
        ),
    ),
    "block/bio.c": (
        Edit(
            "\tbio->bi_bvec_gap_bit = 0;\n\tbio->bi_iter.bi_sector = 0;",
            "\tbio->bi_bvec_gap_bit = 0;\n"
            "\tbio->bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;\n"
            "\tbio->bi_iter.bi_sector = 0;",
        ),
        Edit(
            "\tbio->bi_bvec_gap_bit = bio_src->bi_bvec_gap_bit;\n"
            "\tbio->bi_iter = bio_src->bi_iter;",
            "\tbio->bi_bvec_gap_bit = bio_src->bi_bvec_gap_bit;\n"
            "\tbio->bi_swap_origin = bio_is_zswap_stored_writeback(bio_src) ?\n"
            "\t\tSWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK :\n"
            "\t\tSWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;\n"
            "\tbio->bi_iter = bio_src->bi_iter;",
        ),
        Edit(
            "\tbio->bi_bvec_gap_bit = 0;\n\tatomic_set(&bio->__bi_remaining, 1);",
            "\tbio->bi_bvec_gap_bit = 0;\n"
            "\t/* Same-payload reissue preserves the verified origin tag. */\n"
            "\tatomic_set(&bio->__bi_remaining, 1);",
        ),
    ),
    "include/linux/swap_ops.h": (
        Edit(
            "\tint\t\t\tlen;\n};\n\nstruct swap_io_ctx",
            "\tint\t\t\tlen;\n"
            "\tenum swap_bio_origin\tswap_origin;\n"
            "};\n\nstruct swap_io_ctx",
        ),
        Edit(
            "\tstruct swap_info_struct\t*sis;\n};",
            "\tstruct swap_info_struct\t*sis;\n"
            "\t/* Zero initialized for every ordinary or rejected swap page. */\n"
            "\tenum swap_bio_origin\tswap_origin;\n};",
        ),
        Edit(
            "/*\n * SWAP_OPS_F_REQUIRE_NOFS:",
            "/* Homogeneous only: invalid numeric origins fail closed too. */\n"
            "static inline bool swap_bio_origin_can_merge(\n"
            "\t\tenum swap_bio_origin established,\n"
            "\t\tenum swap_bio_origin incoming)\n"
            "{\n"
            "\treturn established == incoming &&\n"
            "\t\t(established == SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN ||\n"
            "\t\t established == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK);\n"
            "}\n\n/*\n * SWAP_OPS_F_REQUIRE_NOFS:",
        ),
    ),
    "mm/page_io.c": (
        Edit(
            "\tif (ctx->sis != sis)\n\t\treturn false;\n"
            "\treturn sis->ops->can_merge(",
            "\tif (ctx->sis != sis)\n\t\treturn false;\n"
            "\t/* Never combine ordinary and stored-entry writes in one BIO. */\n"
            "\tif (rw == WRITE &&\n"
            "\t    !swap_bio_origin_can_merge(ctx->sio->swap_origin, ctx->swap_origin))\n"
            "\t\treturn false;\n"
            "\treturn sis->ops->can_merge(",
        ),
        Edit(
            "\t\tsio->nr_bvecs = 0;\n\t\tsio->len = 0;\n\t}\n"
            "\tbvec_set_folio(",
            "\t\tsio->nr_bvecs = 0;\n\t\tsio->len = 0;\n"
            "\t\tsio->swap_origin = rw == WRITE &&\n"
            "\t\t\tctx->swap_origin == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK ?\n"
            "\t\t\tSWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK :\n"
            "\t\t\tSWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;\n"
            "\t}\n\tbvec_set_folio(",
        ),
        Edit(
            "\t\t\tREQ_OP_WRITE | REQ_SWAP);\n"
            "\tbio->bi_iter.bi_size = sio->len;",
            "\t\t\tREQ_OP_WRITE | REQ_SWAP);\n"
            "\tbio->bi_swap_origin = sio->swap_origin;\n"
            "\tbio->bi_iter.bi_size = sio->len;",
        ),
    ),
    "mm/zswap.c": (
        Edit(
            "\tfolio_set_dropbehind(folio);\n\n\t/*\n"
            "\t * Drop our reference before starting writeback",
            "\tfolio_set_dropbehind(folio);\n"
            "\t/* Entry identity was checked and decompression succeeded. */\n"
            "\tctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;\n\n"
            "\t/*\n\t * Drop our reference before starting writeback",
        ),
    ),
}



# KUnit registrations are opt-in to preserve existing six-path CI.
KUNIT_EDITS: dict[str, tuple[Edit, ...]] = {
    "block/Kconfig": (
        Edit(
            'source "block/Kconfig.iosched"\n\nendif # BLOCK',
            'source "block/Kconfig.iosched"\n\n'
            'config SWAP_BIO_ORIGIN_KUNIT_TEST\n'
            '\tbool "Test pinned swap BIO origin lifecycle"\n'
            '\tdepends on KUNIT && SWAP\n'
            '\tdefault n\n'
            '\thelp\n'
            '\t  Test authenticated origin, BIO lifecycle and merge rejection.\n\n'
            'endif # BLOCK',
        ),
    ),
    "block/Makefile": (
        Edit(
            "obj-$(CONFIG_BLOCK_HOLDER_DEPRECATED)\t+= holder.o\n",
            "obj-$(CONFIG_BLOCK_HOLDER_DEPRECATED)\t+= holder.o\n"
            "obj-$(CONFIG_SWAP_BIO_ORIGIN_KUNIT_TEST) += swap-bio-origin-kunit.o\n",
        ),
    ),
}
KUNIT_SOURCE = r"""// SPDX-License-Identifier: GPL-2.0
/* Provenance BIO lifecycle regression for the exact pinned Linux tree. */
#include <kunit/test.h>
#include <linux/bio.h>
#include <linux/mm.h>
#include <linux/swap_ops.h>

static void swap_bio_origin_authentication_test(struct kunit *test)
{
	struct bio_vec vector = {};
	struct bio bio;

	bio_init(&bio, NULL, &vector, 1, REQ_OP_WRITE | REQ_SWAP);
	KUNIT_EXPECT_EQ(test, bio.bi_swap_origin,
			(enum swap_bio_origin)SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN);
	KUNIT_EXPECT_FALSE(test, bio_is_zswap_stored_writeback(&bio));
	bio.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;
	KUNIT_EXPECT_TRUE(test, bio_is_zswap_stored_writeback(&bio));
	bio.bi_opf = REQ_OP_WRITE;
	KUNIT_EXPECT_FALSE(test, bio_is_zswap_stored_writeback(&bio));
	bio.bi_opf = REQ_OP_READ | REQ_SWAP;
	KUNIT_EXPECT_FALSE(test, bio_is_zswap_stored_writeback(&bio));
	bio.bi_opf = REQ_OP_WRITE | REQ_SWAP;
	bio.bi_swap_origin = (enum swap_bio_origin)2;
	KUNIT_EXPECT_FALSE(test, bio_is_zswap_stored_writeback(&bio));
	bio.bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;
	KUNIT_EXPECT_FALSE(test, bio_is_zswap_stored_writeback(&bio));
	bio_uninit(&bio);
}

static void swap_bio_origin_reset_reuse_reissue_test(struct kunit *test)
{
	struct bio_vec vector = { .bv_len = PAGE_SIZE };
	struct bio bio;

	bio_init(&bio, NULL, &vector, 1, REQ_OP_WRITE | REQ_SWAP);
	bio.bi_vcnt = 1;
	bio.bi_iter.bi_size = PAGE_SIZE;
	bio.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;
#ifndef CONFIG_BLK_CGROUP
	/* A synthetic NULL-bdev BIO is safe to reissue only without blkcg. */
	bio_prepare_reissue(&bio, NULL);
	KUNIT_EXPECT_TRUE(test, bio_is_zswap_stored_writeback(&bio));
	KUNIT_EXPECT_EQ(test, bio.bi_iter.bi_size, (unsigned int)PAGE_SIZE);
	KUNIT_EXPECT_EQ(test, bio.bi_swap_origin,
			(enum swap_bio_origin)SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK);
#endif
	bio_reuse(&bio, REQ_OP_WRITE | REQ_SWAP);
	KUNIT_EXPECT_FALSE(test, bio_is_zswap_stored_writeback(&bio));
	KUNIT_EXPECT_EQ(test, bio.bi_swap_origin,
			(enum swap_bio_origin)SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN);
	KUNIT_EXPECT_EQ(test, bio.bi_iter.bi_size, (unsigned int)PAGE_SIZE);
	bio.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;
	bio_reset(&bio, NULL, REQ_OP_WRITE | REQ_SWAP);
	KUNIT_EXPECT_FALSE(test, bio_is_zswap_stored_writeback(&bio));
	KUNIT_EXPECT_EQ(test, bio.bi_swap_origin,
			(enum swap_bio_origin)SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN);
	bio_uninit(&bio);
}

static void swap_bio_origin_clone_test(struct kunit *test)
{
	struct bio_vec vector = {};
	struct bio original;
	struct bio clone;
	int ret;

	bio_init(&original, NULL, &vector, 1, REQ_OP_WRITE | REQ_SWAP);
	original.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;
	ret = bio_init_clone(NULL, &clone, &original, GFP_KERNEL);
	KUNIT_ASSERT_EQ(test, ret, 0);
	KUNIT_EXPECT_TRUE(test, bio_is_zswap_stored_writeback(&clone));
	bio_uninit(&clone);

	original.bi_opf = REQ_OP_WRITE;
	ret = bio_init_clone(NULL, &clone, &original, GFP_KERNEL);
	KUNIT_ASSERT_EQ(test, ret, 0);
	KUNIT_EXPECT_FALSE(test, bio_is_zswap_stored_writeback(&clone));
	KUNIT_EXPECT_EQ(test, clone.bi_swap_origin,
			(enum swap_bio_origin)SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN);
	bio_uninit(&clone);

	original.bi_opf = REQ_OP_READ | REQ_SWAP;
	ret = bio_init_clone(NULL, &clone, &original, GFP_KERNEL);
	KUNIT_ASSERT_EQ(test, ret, 0);
	KUNIT_EXPECT_FALSE(test, bio_is_zswap_stored_writeback(&clone));
	KUNIT_EXPECT_EQ(test, clone.bi_swap_origin,
			(enum swap_bio_origin)SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN);
	bio_uninit(&clone);

	original.bi_opf = REQ_OP_WRITE | REQ_SWAP;
	original.bi_swap_origin = (enum swap_bio_origin)2;
	ret = bio_init_clone(NULL, &clone, &original, GFP_KERNEL);
	KUNIT_ASSERT_EQ(test, ret, 0);
	KUNIT_EXPECT_FALSE(test, bio_is_zswap_stored_writeback(&clone));
	KUNIT_EXPECT_EQ(test, clone.bi_swap_origin,
			(enum swap_bio_origin)SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN);
	bio_uninit(&clone);
	bio_uninit(&original);
}

static void swap_bio_origin_split_test(struct kunit *test)
{
	struct bio_vec vector = {};
	struct bio original;
	struct bio *split;
	struct page *page = alloc_page(GFP_KERNEL);

	KUNIT_ASSERT_NOT_NULL(test, page);
	vector.bv_page = page;
	vector.bv_len = PAGE_SIZE;
	bio_init(&original, NULL, &vector, 1, REQ_OP_WRITE | REQ_SWAP);
	original.bi_vcnt = 1;
	original.bi_iter.bi_size = PAGE_SIZE;
	original.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;

	/* bio_split() counts 512-byte sectors, not bytes or KiB. */
	split = bio_split(&original, PAGE_SIZE >> (SECTOR_SHIFT + 1),
			  GFP_KERNEL, &fs_bio_set);
	if (IS_ERR_OR_NULL(split)) {
		KUNIT_FAIL(test, "bio_split could not allocate a source-owned clone");
		goto out;
	}
	KUNIT_EXPECT_TRUE(test, bio_is_zswap_stored_writeback(split));
	KUNIT_EXPECT_TRUE(test, bio_is_zswap_stored_writeback(&original));
	KUNIT_EXPECT_EQ(test, split->bi_iter.bi_size, (unsigned int)PAGE_SIZE / 2);
	KUNIT_EXPECT_EQ(test, original.bi_iter.bi_size, (unsigned int)PAGE_SIZE / 2);
	KUNIT_EXPECT_EQ(test, split->bi_iter.bi_sector, (sector_t)0);
	KUNIT_EXPECT_EQ(test, original.bi_iter.bi_sector,
			(sector_t)(PAGE_SIZE >> (SECTOR_SHIFT + 1)));
	bio_put(split);
out:
	bio_uninit(&original);
	__free_page(page);
}

static void swap_bio_origin_merge_reject_test(struct kunit *test)
{
	KUNIT_EXPECT_TRUE(test, swap_bio_origin_can_merge(
		SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN,
		SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN));
	KUNIT_EXPECT_TRUE(test, swap_bio_origin_can_merge(
		SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK,
		SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK));
	KUNIT_EXPECT_FALSE(test, swap_bio_origin_can_merge(
		SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN,
		SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK));
	KUNIT_EXPECT_FALSE(test, swap_bio_origin_can_merge(
		SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK,
		SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN));
	KUNIT_EXPECT_FALSE(test, swap_bio_origin_can_merge(
		(enum swap_bio_origin)2, (enum swap_bio_origin)2));
	KUNIT_EXPECT_FALSE(test, swap_bio_origin_can_merge(
		(enum swap_bio_origin)2,
		SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK));
	KUNIT_EXPECT_FALSE(test, swap_bio_origin_can_merge(
		SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN,
		(enum swap_bio_origin)2));
}

static struct kunit_case swap_bio_origin_cases[] = {
	KUNIT_CASE(swap_bio_origin_authentication_test),
	KUNIT_CASE(swap_bio_origin_reset_reuse_reissue_test),
	KUNIT_CASE(swap_bio_origin_clone_test),
	KUNIT_CASE(swap_bio_origin_split_test),
	KUNIT_CASE(swap_bio_origin_merge_reject_test),
	{}
};

static struct kunit_suite swap_bio_origin_suite = {
	.name = "swap_bio_origin",
	.test_cases = swap_bio_origin_cases,
};

kunit_test_suite(swap_bio_origin_suite);

MODULE_LICENSE("GPL");
"""

# Optional direct-compressed reference is never compiled or submitted.
# The pinned Linux BIO ABI has no authenticated compressed representation.
COMPRESSED_HANDOFF_SOURCE = r"""/*
 * Research-only bounded zswap -> swapz compressed-payload ownership model.
 * This deliberately compiles to nothing: this pinned Linux tree has no
 * authenticated compressed-representation BIO or matching consumer ABI.
 * Normal zswap_writeback_entry() still decompresses before swap I/O.
 *
 * CPU cost if a real transport is later reviewed: at most 3568 bytes copied
 * from zsmalloc and 3568 bytes checksummed; no zpool pointer may escape the
 * folio-locked identity-check interval. The descriptor remains allocated and
 * exclusively owned by the caller until callbacks are quiescent.
 */
#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */
#include <linux/crc32c.h>
#include <crypto/sha2.h>

#define ZSWAP_SWAPZ_COMPRESSED_MAX 3568U
#define ZSWAP_SWAPZ_LOGICAL_BYTES 4096U
#define ZSWAP_SWAPZ_DIGEST_BYTES 32U
#define ZSWAP_SWAPZ_RECORD_VERSION 1U

enum zswap_swapz_proto_codec {
	ZSWAP_SWAPZ_CODEC_UNKNOWN = 0,
	ZSWAP_SWAPZ_CODEC_LZ4 = 1,
	ZSWAP_SWAPZ_CODEC_ZSTD = 2,
};

/* Dedicated volatile-RAM representation; NEVER the existing RAW_4096. */
enum zswap_swapz_proto_representation {
	ZSWAP_SWAPZ_REPR_INVALID = 0,
	ZSWAP_SWAPZ_REPR_RAW_4096 = 1,
	ZSWAP_SWAPZ_REPR_ZSWAP_LZ4_V1 = 2,
};

enum zswap_swapz_proto_state {
	ZSWAP_SWAPZ_PAYLOAD_EMPTY = 0,
	ZSWAP_SWAPZ_PAYLOAD_OWNED = 1,
	ZSWAP_SWAPZ_PAYLOAD_CHECKING = 2,
	ZSWAP_SWAPZ_PAYLOAD_SUBMITTED = 3,
	ZSWAP_SWAPZ_PAYLOAD_RELEASED = 4,
};

/*
 * Source-only store-time certificate. This is NOT a public ABI or permission
 * to forge a stored entry: a real integration must call the binder only after
 * zswap_store_page() publishes an entry while holding the original folio lock,
 * with generation from an authoritative swap-slot allocator. Caller-created
 * host fixtures do not establish kernel provenance.
 */
struct zswap_swapz_stored_proof {
	struct zswap_swapz_stored_proof *self;
	const struct zswap_entry *stored_entry;
	const struct zswap_pool *stored_pool;
	unsigned long stored_handle;
	unsigned int stored_length;
	swp_entry_t slot;
	u64 generation;
	enum zswap_swapz_proto_codec stored_codec;
	u8 original_sha256[ZSWAP_SWAPZ_DIGEST_BYTES];
	bool admitted;
};

struct zswap_swapz_owned_payload {
	swp_entry_t entry_identity;
	u64 slot_generation;
	unsigned int representation_version;
	enum zswap_swapz_proto_representation representation;
	u8 original_sha256[ZSWAP_SWAPZ_DIGEST_BYTES];
	struct zswap_swapz_owned_payload *self; /* Reject descriptor clones. */
	u8 *owned_allocation; /* Only this exact allocation is released. */
	const u8 *owned_bytes; /* Never a zpool mapping or borrowed entry. */
	unsigned int compressed_length;
	unsigned int decoded_length;
	u32 payload_crc32c;
	enum zswap_swapz_proto_codec codec;
	bool semantic_stored_writeback;
	bool representation_compressed;
	atomic_t owner_state;
	int completion_error;
};

static enum zswap_swapz_proto_codec
zswap_swapz_codec_from_tfm(const char *tfm_name)
{
	if (!tfm_name)
		return ZSWAP_SWAPZ_CODEC_UNKNOWN;
	if (!strcmp(tfm_name, "lz4"))
		return ZSWAP_SWAPZ_CODEC_LZ4;
	if (!strcmp(tfm_name, "zstd"))
		return ZSWAP_SWAPZ_CODEC_ZSTD;
	return ZSWAP_SWAPZ_CODEC_UNKNOWN;
}

/* Fixed-size digest validity only; cannot manufacture missing store proof. */
static bool zswap_swapz_digest_present(const u8 *digest)
{
	u8 nonzero = 0;
	unsigned int index;

	for (index = 0; index < ZSWAP_SWAPZ_DIGEST_BYTES; ++index)
		nonzero |= digest[index];
	return nonzero != 0;
}

/*
 * This 4096-byte SHA256 cost is charged at genuine store time, not eviction.
 * The outer zswap caller must independently cap RAM proof count and populate
 * a nonzero slot generation from the real swap-slot allocator. None of these
 * hooks are wired into live MM while the compressed transport is disabled.
 */
static int zswap_swapz_bind_stored_entry(
		struct zswap_swapz_stored_proof *proof,
		const struct zswap_entry *entry, swp_entry_t swpentry,
		u64 generation, const struct folio *locked_folio,
		const u8 *original_page, size_t original_length)
{
	struct zswap_pool *pool;

	if (!proof || !entry || !locked_folio || !original_page ||
	    !folio_test_locked(locked_folio) ||
	    original_length != ZSWAP_SWAPZ_LOGICAL_BYTES || !generation ||
	    proof->self || proof->admitted)
		return -EINVAL;
	if (entry != xa_load(swap_zswap_tree(swpentry), swp_offset(swpentry)) ||
	    entry->swpentry.val != swpentry.val)
		return -ESTALE;
	if (!entry->length || entry->length > ZSWAP_SWAPZ_COMPRESSED_MAX)
		return -EMSGSIZE;
	pool = zswap_entry_pool((struct zswap_entry *)entry);
	if (!pool || zswap_swapz_codec_from_tfm(pool->tfm_name) != ZSWAP_SWAPZ_CODEC_LZ4)
		return -EOPNOTSUPP;

	/* Original-page SHA, never a hash of compressed zpool bytes. */
	sha256(original_page, ZSWAP_SWAPZ_LOGICAL_BYTES, proof->original_sha256);
	if (!zswap_swapz_digest_present(proof->original_sha256))
		return -ENODATA;
	proof->self = proof;
	proof->stored_entry = entry;
	proof->stored_pool = pool;
	proof->stored_handle = entry->handle;
	proof->stored_length = entry->length;
	proof->slot = swpentry;
	proof->generation = generation;
	proof->stored_codec = ZSWAP_SWAPZ_CODEC_LZ4;
	proof->admitted = true;
	return 0;
}

/* Caller owns the locked swap-cache folio throughout this capture. */
static int zswap_swapz_capture_owned_payload(
		struct zswap_swapz_owned_payload *transfer,
		const struct zswap_entry *entry, swp_entry_t swpentry,
		const struct folio *locked_folio,
		const struct zswap_swapz_stored_proof *proof, u64 generation)
{
	struct zswap_pool *pool;
	struct scatterlist input[2];
	enum zswap_swapz_proto_codec codec;
	u8 *owned_bytes;

	if (PAGE_SIZE != ZSWAP_SWAPZ_LOGICAL_BYTES)
		return -EOPNOTSUPP;
	if (!transfer || !entry || !locked_folio ||
	    !folio_test_locked(locked_folio))
		return -EINVAL;
	if (!proof || proof->self != proof || !proof->admitted ||
	    proof->stored_entry != entry || !generation ||
	    proof->generation != generation ||
	    proof->slot.val != swpentry.val ||
	    proof->stored_codec != ZSWAP_SWAPZ_CODEC_LZ4 ||
	    !zswap_swapz_digest_present(proof->original_sha256))
		return -ESTALE;
	if (atomic_read(&transfer->owner_state) != ZSWAP_SWAPZ_PAYLOAD_EMPTY ||
	    transfer->self || transfer->owned_allocation || transfer->owned_bytes)
		return -EBUSY;
	/* Compare the pointer before reading entry: an old entry can be freed. */
	if (entry != xa_load(swap_zswap_tree(swpentry), swp_offset(swpentry)))
		return -ENOENT;
	if (entry->swpentry.val != swpentry.val)
		return -ESTALE;
	if (!entry->length || entry->length > ZSWAP_SWAPZ_COMPRESSED_MAX)
		return -EMSGSIZE;
	/* Verify the published storage allocation still matches store-time. */
	if (entry->length != proof->stored_length ||
	    entry->handle != proof->stored_handle)
		return -ESTALE;
	pool = zswap_entry_pool((struct zswap_entry *)entry);
	if (!pool)
		return -ENOENT;
	if (pool != proof->stored_pool)
		return -ESTALE;
	codec = zswap_swapz_codec_from_tfm(pool->tfm_name);
	/* Never reinterpret an old ZSTD entry after a pool/codec switch. */
	if (codec != ZSWAP_SWAPZ_CODEC_LZ4 || codec != proof->stored_codec)
		return -EOPNOTSUPP;
	owned_bytes = kmalloc(entry->length, GFP_KERNEL);
	if (!owned_bytes)
		return -ENOMEM;

	/* The folio lock protects identity; the zpool mapping is only borrowed
	 * inside this bounded, synchronous read. It never reaches a BIO.
	 */
	zs_obj_read_sg_begin(pool->zs_pool, entry->handle, input, entry->length);
	memcpy_from_sglist(owned_bytes, input, 0, entry->length);
	zs_obj_read_sg_end(pool->zs_pool, entry->handle);
	transfer->entry_identity = swpentry;
	transfer->slot_generation = generation;
	transfer->representation_version = ZSWAP_SWAPZ_RECORD_VERSION;
	transfer->representation = ZSWAP_SWAPZ_REPR_ZSWAP_LZ4_V1;
	memcpy(transfer->original_sha256, proof->original_sha256,
	       ZSWAP_SWAPZ_DIGEST_BYTES);
	transfer->self = transfer;
	transfer->owned_allocation = owned_bytes;
	transfer->owned_bytes = owned_bytes;
	transfer->compressed_length = entry->length;
	transfer->decoded_length = ZSWAP_SWAPZ_LOGICAL_BYTES;
	transfer->codec = codec;
	transfer->payload_crc32c = ~crc32c(~0U, owned_bytes, entry->length);
	transfer->semantic_stored_writeback = true;
	transfer->representation_compressed = true;
	transfer->completion_error = 0;
	atomic_set(&transfer->owner_state, ZSWAP_SWAPZ_PAYLOAD_OWNED);
	return 0;
}

static bool zswap_swapz_owned_payload_is_valid(
		const struct zswap_swapz_owned_payload *transfer)
{
	return transfer && transfer->self == transfer &&
		transfer->owned_bytes == transfer->owned_allocation &&
		transfer->owned_bytes &&
		transfer->semantic_stored_writeback &&
		transfer->representation_compressed &&
		transfer->slot_generation != 0 &&
		transfer->representation_version == ZSWAP_SWAPZ_RECORD_VERSION &&
		transfer->representation == ZSWAP_SWAPZ_REPR_ZSWAP_LZ4_V1 &&
		zswap_swapz_digest_present(transfer->original_sha256) &&
		transfer->decoded_length == ZSWAP_SWAPZ_LOGICAL_BYTES &&
		transfer->compressed_length >= 1 &&
		transfer->compressed_length <= ZSWAP_SWAPZ_COMPRESSED_MAX &&
		transfer->codec == ZSWAP_SWAPZ_CODEC_LZ4 &&
		~crc32c(~0U, transfer->owned_bytes, transfer->compressed_length) ==
		transfer->payload_crc32c;
}

/* One submission owner; the pointed-to descriptor cannot be cloned. */
static bool zswap_swapz_owned_payload_submit(
		struct zswap_swapz_owned_payload *transfer)
{
	if (!transfer || transfer->self != transfer ||
	    atomic_cmpxchg(&transfer->owner_state,
			ZSWAP_SWAPZ_PAYLOAD_OWNED,
			ZSWAP_SWAPZ_PAYLOAD_CHECKING) != ZSWAP_SWAPZ_PAYLOAD_OWNED)
		return false;
	/* An abort cannot free the buffer during checksum verification. */
	if (!zswap_swapz_owned_payload_is_valid(transfer)) {
		atomic_set(&transfer->owner_state, ZSWAP_SWAPZ_PAYLOAD_OWNED);
		return false;
	}
	atomic_set(&transfer->owner_state, ZSWAP_SWAPZ_PAYLOAD_SUBMITTED);
	return true;
}

/* Caller guarantees the descriptor itself outlives all completion callbacks.
 * Exactly one owner may release the copied bytes, on either success or error.
 */
static bool zswap_swapz_owned_payload_finish(
		struct zswap_swapz_owned_payload *transfer, int completion_error)
{
	if (!transfer || transfer->self != transfer ||
	    atomic_cmpxchg(&transfer->owner_state,
			ZSWAP_SWAPZ_PAYLOAD_SUBMITTED,
			ZSWAP_SWAPZ_PAYLOAD_RELEASED) != ZSWAP_SWAPZ_PAYLOAD_SUBMITTED)
		return false;
	transfer->completion_error = completion_error;
	kfree(transfer->owned_allocation);
	transfer->owned_allocation = NULL;
	transfer->owned_bytes = NULL;
	return true;
}

/* Aborts may release only a payload that was never submitted. */
static bool zswap_swapz_owned_payload_abort(
		struct zswap_swapz_owned_payload *transfer)
{
	if (!transfer || transfer->self != transfer ||
	    atomic_cmpxchg(&transfer->owner_state,
			ZSWAP_SWAPZ_PAYLOAD_OWNED,
			ZSWAP_SWAPZ_PAYLOAD_RELEASED) != ZSWAP_SWAPZ_PAYLOAD_OWNED)
		return false;
	transfer->completion_error = -ECANCELED;
	kfree(transfer->owned_allocation);
	transfer->owned_allocation = NULL;
	transfer->owned_bytes = NULL;
	return true;
}
/*
 * Round023 research: typed source-only carrier. The current pinned kernel has
 * NO authority to bind a real store-time slot generation to the downstream
 * cloned/split/reissued 4096-byte BIO. A source-only snapshot can identify
 * bytes and epoch, but cannot make the ordinary BIO transport compressed.
 * The carrier borrows only the separately OWNED producer copy, never zpool.
 */
struct zswap_swapz_compressed_carrier_v1 {
	const struct zswap_swapz_owned_payload *payload_owner;
	const u8 *immutable_payload;
	unsigned int compressed_length;
	unsigned int original_decoded_length;
	unsigned int version;
	swp_entry_t stored_slot;
	u64 store_generation;
	u32 payload_crc32c;
	u8 original_sha256[ZSWAP_SWAPZ_DIGEST_BYTES];
	bool source_only_untrusted;
};

/* Only a host fixture can inspect this borrowed typed descriptor. The
 * source owner must outlive it, including every async callback; a real ABI
 * would need explicit counted references through cloning and reissue.
 */
static int zswap_swapz_carrier_snapshot_source_only(
		struct zswap_swapz_compressed_carrier_v1 *carrier,
		const struct zswap_swapz_owned_payload *owner)
{
	if (!carrier || !owner)
		return -EINVAL;
	if (owner->self != owner ||
	    atomic_read(&owner->owner_state) != ZSWAP_SWAPZ_PAYLOAD_SUBMITTED ||
	    !zswap_swapz_owned_payload_is_valid(owner))
		return -ESTALE;
	if (!owner->slot_generation || owner->codec != ZSWAP_SWAPZ_CODEC_LZ4 ||
	    owner->representation != ZSWAP_SWAPZ_REPR_ZSWAP_LZ4_V1 ||
	    owner->representation_version != ZSWAP_SWAPZ_RECORD_VERSION)
		return -EOPNOTSUPP;
	*carrier = (struct zswap_swapz_compressed_carrier_v1) {
		.payload_owner = owner,
		.immutable_payload = owner->owned_bytes,
		.compressed_length = owner->compressed_length,
		.original_decoded_length = owner->decoded_length,
		.version = owner->representation_version,
		.stored_slot = owner->entry_identity,
		.store_generation = owner->slot_generation,
		.payload_crc32c = owner->payload_crc32c,
		.source_only_untrusted = true,
	};
	memcpy(carrier->original_sha256, owner->original_sha256,
	       sizeof(carrier->original_sha256));
	return 0;
}

/* Every caller, including one presenting forged clone/merge/origin markers,
 * MUST use the already compiled zswap_decompress -> normal 4096-byte WRITE.
 * There is no authenticated MM/BIO -> DM sideband ABI in pinned Linux.
 */
static int zswap_swapz_carrier_publish_disabled(
		const struct zswap_swapz_compressed_carrier_v1 *carrier,
		bool claims_authenticated_origin, bool clones_preserve_owner,
		bool splits_preserve_owner, bool merges_preserve_owner,
		bool retries_preserve_owner)
{
	if (!carrier || !carrier->payload_owner)
		return -EINVAL;
	if (carrier->source_only_untrusted ||
	    !claims_authenticated_origin || !clones_preserve_owner ||
	    !splits_preserve_owner || !merges_preserve_owner ||
	    !retries_preserve_owner)
		return -EOPNOTSUPP;
	/* Even forged "all true" cannot create missing kernel ABI support. */
	return -EOPNOTSUPP;
}
#endif /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */
"""
COMPRESSED_HANDOFF_ANCHOR = (
    "/*********************************\n"
    "* writeback code\n"
    "**********************************/"
)

# Optional compiler-emitted witness in original pinned mm/zswap.c; never live.
ROUND024_ZSWAP_KBUILD_PROBE_SOURCE = r"""/*
 * Round024: real pinned Linux mm/zswap.o compile-only observation. No caller.
 * No authenticated slot-allocation epoch, stored 4096 SHA256 or owned
 * compression-aware MM/BIO sideband is available; NEVER publish a carrier.
 */
#if defined(SWAPZ_ROUND024_ZSWAP_KBUILD_PROBE)
static __attribute__((used, noinline)) int
zswap_swapz_round024_producer_kbuild_probe(
		struct zswap_entry *stored_entry, swp_entry_t source_slot,
		const struct folio *locked_folio)
{
	struct zswap_pool *stored_pool;

	if (!stored_entry || !locked_folio ||
	    !folio_test_locked(locked_folio))
		return -EOPNOTSUPP;
	if (stored_entry->swpentry.val != source_slot.val ||
	    !stored_entry->handle || !stored_entry->length ||
	    stored_entry->length > 3568U)
		return -EOPNOTSUPP;
	/* xarray identity can reject stale pointers, but cannot supply
	 * the missing authenticated swap-slot allocation generation.
	 */
	if (xa_load(swap_zswap_tree(source_slot),
		    swp_offset(source_slot)) != stored_entry)
		return -ESTALE;
	stored_pool = zswap_entry_pool(stored_entry);
	if (!stored_pool || stored_pool->idx != stored_entry->pool_idx)
		return -ESTALE;
	/* The actual stored pool's immutable codec must be the future v1 LZ4.
	 * Merely matching a source slot or xarray pointer is insufficient.
	 */
	if (strcmp(stored_pool->tfm_name, "lz4"))
		return -EOPNOTSUPP;
	/* This is not a real LZ4 carrier and cannot bypass full 4096 WRITE. */
	return -EOPNOTSUPP;
}
#endif /* SWAPZ_ROUND024_ZSWAP_KBUILD_PROBE */
"""


def validate_round024_probe(source: str) -> None:
    """Reject modified source claiming authenticated compressed publication."""
    required = (
        "#if defined(SWAPZ_ROUND024_ZSWAP_KBUILD_PROBE)",
        "zswap_swapz_round024_producer_kbuild_probe(",
        "folio_test_locked(locked_folio)",
        "stored_entry->swpentry.val != source_slot.val",
        "stored_entry->length > 3568U",
        "xa_load(swap_zswap_tree(source_slot),",
        "stored_pool = zswap_entry_pool(stored_entry);",
        "stored_pool->idx != stored_entry->pool_idx",
        'strcmp(stored_pool->tfm_name, "lz4")',
        "#endif /* SWAPZ_ROUND024_ZSWAP_KBUILD_PROBE */",
    )
    if any(source.count(token) != 1 for token in required):
        raise StagingError("round024-producer-probe-source-drift")
    if (source.count("return -EOPNOTSUPP;") != 4 or
        source.count("return -ESTALE;") != 2 or
        "return 0;" in source or "submit_bio(" in source or
        "bio_endio(" in source or "sha256(" in source):
        raise StagingError("round024-producer-probe-unsafe-publication")


ROUND024_PROBE_EDITS: dict[str, tuple[Edit, ...]] = {
    "mm/zswap.c": (
        Edit(COMPRESSED_HANDOFF_ANCHOR,
             ROUND024_ZSWAP_KBUILD_PROBE_SOURCE + COMPRESSED_HANDOFF_ANCHOR),
    ),
}


COMPRESSED_HANDOFF_EDITS: dict[str, tuple[Edit, ...]] = {
    "mm/zswap.c": (
        Edit(COMPRESSED_HANDOFF_ANCHOR,
             COMPRESSED_HANDOFF_SOURCE + COMPRESSED_HANDOFF_ANCHOR),
    ),
}



def validate_disabled_compressed_contract(source: str) -> None:
    """Freeze the source-only v1 representation, without enabling transport."""
    required = (
        "#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */",
        "#endif /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */",
        "ZSWAP_SWAPZ_COMPRESSED_MAX 3568U",
        "ZSWAP_SWAPZ_LOGICAL_BYTES 4096U",
        "ZSWAP_SWAPZ_RECORD_VERSION 1U",
        "zswap_swapz_bind_stored_entry(",
        "proof->stored_entry != entry",
        "proof->generation != generation",
        "proof->stored_codec != ZSWAP_SWAPZ_CODEC_LZ4",
        "proof->stored_pool = pool;",
        "proof->stored_handle = entry->handle;",
        "proof->stored_length = entry->length;",
        "entry->length != proof->stored_length",
        "entry->handle != proof->stored_handle",
        "pool != proof->stored_pool",
        "sha256(original_page, ZSWAP_SWAPZ_LOGICAL_BYTES, proof->original_sha256);",
        "~crc32c(~0U, owned_bytes, entry->length)",
        "~crc32c(~0U, transfer->owned_bytes, transfer->compressed_length)",
        "transfer->representation_version == ZSWAP_SWAPZ_RECORD_VERSION",
        "transfer->representation == ZSWAP_SWAPZ_REPR_ZSWAP_LZ4_V1",
        "ZSWAP_SWAPZ_REPR_RAW_4096 = 1",
        "zswap_swapz_digest_present(transfer->original_sha256)",
        "transfer->codec == ZSWAP_SWAPZ_CODEC_LZ4",
        "atomic_cmpxchg(&transfer->owner_state,",
        "transfer->self != transfer",
    )
    if (any(source.count(fragment) != 1 for fragment in required if
            fragment not in ("atomic_cmpxchg(&transfer->owner_state,",
                            "transfer->self != transfer")) or
        source.count("atomic_cmpxchg(&transfer->owner_state,") != 3 or
        source.count("transfer->self != transfer") != 3 or
        "crc32(0," in source or
        "submit_bio(" in source or "REQ_ZSWAP_WRITEBACK" in source):
        raise StagingError("disabled-compressed-handoff-contract-drift")


class StagingError(RuntimeError):
    """Refuse a preflight, source transition or publication failure."""

def validate_kunit_source(source: str) -> None:
    """Fail before touching Linux when the compiled KUnit contract drifts.

    The exact tests use real pinned Linux APIs, no mocked BIO implementation.
    The static guard is a negative preflight, never equivalent to Kbuild/KUnit.
    """
    required = (
        "bio_init(&bio, NULL, &vector, 1, REQ_OP_WRITE | REQ_SWAP);",
        "bio.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;",
        "bio_reuse(&bio, REQ_OP_WRITE | REQ_SWAP);",
        "bio_reset(&bio, NULL, REQ_OP_WRITE | REQ_SWAP);",
        "bio_prepare_reissue(&bio, NULL);",
        "bio_init_clone(NULL, &clone, &original, GFP_KERNEL);",
        "bio_split(&original, PAGE_SIZE >> (SECTOR_SHIFT + 1),",
        "KUNIT_EXPECT_EQ(test, original.bi_iter.bi_size, (unsigned int)PAGE_SIZE / 2);",
        "bio_put(split);",
        "bio_uninit(&original);",
        "__free_page(page);",
        "swap_bio_origin_can_merge(",
        "KUNIT_EXPECT_FALSE(test, bio_is_zswap_stored_writeback(&bio));",
        "KUNIT_EXPECT_TRUE(test, bio_is_zswap_stored_writeback(&bio));",
        "MODULE_LICENSE(\"GPL\");",
    )
    expected_cases = (
        "swap_bio_origin_authentication_test",
        "swap_bio_origin_reset_reuse_reissue_test",
        "swap_bio_origin_clone_test",
        "swap_bio_origin_split_test",
        "swap_bio_origin_merge_reject_test",
    )
    if (not source or source.count("KUNIT_CASE(") != len(expected_cases) or
        any(source.count("KUNIT_CASE(" + name + ")") != 1
            for name in expected_cases) or
        any(fragment not in source for fragment in required) or
        "bio_split(&original, PAGE_SIZE >> 10" in source):
        raise StagingError("invalid-kunit-source-contract")


def blob_sha(payload: bytes) -> str:
    """SHA-1 of the exact Git blob; independent of local Git config."""
    header = b"blob " + str(len(payload)).encode("ascii") + b"\x00"
    return hashlib.sha1(header + payload).hexdigest()


def check_preimage(path: str, payload: bytes, expected_hash: str) -> None:
    if blob_sha(payload) != expected_hash:
        raise StagingError(f"original-blob-mismatch:{path}")


def render_source(path: str, original: str, *, compressed_handoff: bool = False,
                  round024_probe: bool = False) -> str:
    """Reject missing, duplicate and overlapping anchors before any mutation."""
    edits = EDITS.get(path, KUNIT_EDITS.get(path))
    if compressed_handoff and round024_probe:
        raise StagingError("incompatible-producer-profiles")
    if round024_probe:
        validate_round024_probe(ROUND024_ZSWAP_KBUILD_PROBE_SOURCE)
        if path != "mm/zswap.c":
            raise StagingError(f"unexpected-round024-probe-path:{path}")
        edits = edits + ROUND024_PROBE_EDITS[path]
    if compressed_handoff:
        validate_disabled_compressed_contract(COMPRESSED_HANDOFF_SOURCE)
        if path != "mm/zswap.c":
            raise StagingError(f"unexpected-compressed-prototype-path:{path}")
        edits = edits + COMPRESSED_HANDOFF_EDITS[path]
    if edits is None:
        raise StagingError(f"unexpected-source-path:{path}")
    spans = []
    for edit in edits:
        if edit.before == edit.after or not edit.before or not edit.after:
            raise StagingError(f"invalid-transition:{path}")
        offset = original.find(edit.before)
        if offset < 0 or original.find(edit.before, offset + 1) >= 0:
            raise StagingError(f"missing-or-duplicate-anchor:{path}")
        if edit.after in original:
            raise StagingError(f"already-staged-or-mixed-source:{path}")
        spans.append((offset, offset + len(edit.before), edit))
    spans.sort(key=lambda span: span[0])
    for previous, current in zip(spans, spans[1:]):
        if previous[1] > current[0]:
            raise StagingError(f"overlapping-anchors:{path}")
    changed = original
    for begin, end, edit in reversed(spans):
        changed = changed[:begin] + edit.after + changed[end:]
    if changed == original:
        raise StagingError(f"no-source-transition:{path}")
    validate_origin_postimage(path, changed)
    return changed



def verify_pinned_zswap_producer(staged_source: str) -> None:
    """Authenticate the actual stored-entry admission, eviction and WRITE gate.

    This static, immutable-source gate does NOT demonstrate a booted eviction,
    a real decompressor output or a loaded DM completion. A compiled host shim
    separately executes the pinned writeback control flow with mocked helpers.
    """
    if not staged_source or len(staged_source) > 1024 * 1024:
        raise StagingError("invalid-pinned-producer-source")

    positions = []
    for label, beginning, ending, expected_blob in PINNED_ZSWAP_PRODUCER_SLICES:
        start = staged_source.find(beginning)
        if start < 0 or staged_source.find(beginning, start + 1) >= 0:
            raise StagingError("missing-or-duplicate-producer:" + label)
        end = staged_source.find(ending, start + len(beginning))
        if end < 0:
            raise StagingError("missing-producer-end:" + label)
        # The prototype is strictly #if 0 and is inserted BEFORE the original
        # writeback banner. Never include it in the decompressor's hash.
        if label == "decompress" and COMPRESSED_HANDOFF_SOURCE in staged_source:
            prototype_start = staged_source.find(COMPRESSED_HANDOFF_SOURCE)
            if prototype_start < start or prototype_start >= end:
                raise StagingError("invalid-disabled-prototype-placement")
            end = prototype_start
        if label == "decompress" and ROUND024_ZSWAP_KBUILD_PROBE_SOURCE in staged_source:
            probe_start = staged_source.find(ROUND024_ZSWAP_KBUILD_PROBE_SOURCE)
            if probe_start < start or probe_start >= end:
                raise StagingError("invalid-round024-probe-placement")
            end = probe_start
        if blob_sha(staged_source[start:end].encode("utf-8")) != expected_blob:
            raise StagingError("pinned-producer-causality-drift:" + label)
        positions.append(start)

    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise StagingError("pinned-producer-causality-order")
    if COMPRESSED_HANDOFF_SOURCE in staged_source and (
        staged_source.count(COMPRESSED_HANDOFF_SOURCE) != 1 or
        staged_source.count("#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */") != 1
    ):
        raise StagingError("disabled-prototype-contract-drift")


def validate_origin_postimage(path: str, staged_source: str) -> None:
    """Check safety-critical emitted C snippets, not only anchor counts.

    A later edit must not silently replace the positive-origin predicate with
    a raw scalar copy, promote a noncanonical context, or remove the merge
    boundary. Whole-file upstream Git blobs are separately pinned.
    """
    required: dict[str, tuple[str, ...]] = {
        "include/linux/blk_types.h": (
            "SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN = 0,",
            "SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK = 1,",
            "bi_swap_origin; /* scalar source, never encoding */",
        ),
        "include/linux/bio.h": (
            "bio_op(bio) == REQ_OP_WRITE &&",
            "(bio->bi_opf & REQ_SWAP) &&",
            "bio->bi_swap_origin == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;",
        ),
        "block/bio.c": (
            "bio->bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;",
            "bio->bi_swap_origin = bio_is_zswap_stored_writeback(bio_src) ?\n"
            "\t\tSWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK :\n"
            "\t\tSWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;",
            "Same-payload reissue preserves the verified origin tag.",
        ),
        "include/linux/swap_ops.h": (
            "enum swap_bio_origin\tswap_origin;",
            "swap_bio_origin_can_merge(",
            "established == incoming &&",
        ),
        "mm/page_io.c": (
            "!swap_bio_origin_can_merge(ctx->sio->swap_origin, ctx->swap_origin)",
            "sio->swap_origin = rw == WRITE &&\n"
            "\t\t\tctx->swap_origin == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK ?\n"
            "\t\t\tSWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK :\n"
            "\t\t\tSWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;",
            "bio->bi_swap_origin = sio->swap_origin;",
        ),
        "mm/zswap.c": (
            "ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;",
        ),
        "block/Kconfig": (
            "config SWAP_BIO_ORIGIN_KUNIT_TEST",
            "depends on KUNIT && SWAP",
        ),
        "block/Makefile": (
            "obj-$(CONFIG_SWAP_BIO_ORIGIN_KUNIT_TEST) += swap-bio-origin-kunit.o",
        ),
    }
    if path not in required or any(
        staged_source.count(fragment) != (
            2 if (path == "include/linux/swap_ops.h" and
                  fragment == "enum swap_bio_origin\tswap_origin;") else 1)
        for fragment in required[path]
    ):
        raise StagingError(f"invalid-origin-postimage:{path}")
    if path == "block/bio.c" and (
        "bio->bi_swap_origin = bio_src->bi_swap_origin;" in staged_source
    ):
        raise StagingError("unguarded-origin-clone:block/bio.c")
    if path == "include/linux/blk_types.h":
        origin_offset = staged_source.find("bi_swap_origin;")
        # The original header also contains unrelated atomic_t fields before
        # struct bio. Check the next member instead of the first in the file.
        next_member = staged_source.find("atomic_t", origin_offset)
        if origin_offset < 0 or next_member <= origin_offset:
            raise StagingError("origin-reset-layout:include/linux/blk_types.h")
        bio_start = staged_source.find("struct bio {")
        if bio_start >= 0:
            preserved_start = staged_source.find("bi_max_vecs;", bio_start)
            if (origin_offset <= bio_start or
                preserved_start <= origin_offset or
                "#define BIO_RESET_BYTES\t\toffsetof(struct bio, bi_max_vecs)"
                    not in staged_source):
                raise StagingError("origin-reset-layout:include/linux/blk_types.h")
    # Existing tiny synthetic edit-anchor fixtures intentionally omit the
    # complete function bodies. Real full pinned Linux has all four functions
    # and is authenticated both by its original Git blob and by this gate.
    if path == "mm/zswap.c" and "static int zswap_writeback_entry(" in staged_source:
        verify_pinned_zswap_producer(staged_source)


def git_output(root: Path, *args: str) -> str:
    try:
        call = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True,
            text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise StagingError("git-preflight-unavailable") from error
    if call.returncode:
        raise StagingError("git-preflight-command-failed:" + args[0])
    return call.stdout.strip()


def validate_checkout(root: Path, *, with_kunit: bool = False) -> None:
    """Require the exact clean, complete upstream checkout before writing."""
    if not root.is_dir() or not (root / ".git").exists():
        raise StagingError("complete-git-checkout-required")
    if Path(git_output(root, "rev-parse", "--show-toplevel")) != root:
        raise StagingError("unexpected-git-top-level")
    if git_output(root, "rev-parse", "HEAD") != LINUX_COMMIT:
        raise StagingError("linux-commit-mismatch")
    if git_output(root, "status", "--porcelain", "--untracked-files=no"):
        raise StagingError("tracked-source-is-dirty")
    if len(git_output(root, "ls-files").splitlines()) < MINIMUM_TRACKED_FILES:
        raise StagingError("incomplete-linux-checkout")
    expected_sources = dict(ORIGINAL_BLOBS)
    if with_kunit:
        expected_sources.update(KUNIT_ORIGINAL_BLOBS)
    for path, expected_hash in expected_sources.items():
        full_path = root / path
        if full_path.is_symlink() or not full_path.is_file():
            raise StagingError(f"missing-or-symlink-source:{path}")
        lines = git_output(root, "ls-files", "--stage", "--", path).splitlines()
        if len(lines) != 1 or not lines[0].startswith("100644 " + expected_hash + " 0\t"):
            raise StagingError(f"index-blob-mismatch:{path}")
        check_preimage(path, full_path.read_bytes(), expected_hash)
    if with_kunit:
        addition = root / KUNIT_SOURCE_PATH
        if (addition.exists() or addition.is_symlink() or
            git_output(root, "ls-files", "--stage", "--", KUNIT_SOURCE_PATH)):
            raise StagingError("kunit-source-already-present")


def write_atomic(destination: Path, payload: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".swapz-origin-", dir=destination.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o644)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)



def rollback_sources(root: Path, originals: dict[str, bytes | None],
                     staged: dict[str, bytes], paths: list[str]) -> list[str]:
    """Restore touched paths, including a write that raised after replacement.

    Never overwrite unexpected third-party bytes. Such interference is a
    reported partial rollback, not a successful source stage.
    """
    failed = []
    for path in reversed(paths):
        try:
            destination = root / path
            if destination.is_symlink():
                raise StagingError("rollback-source-interference")
            try:
                current = destination.read_bytes()
            except FileNotFoundError:
                if originals[path] is None:
                    continue
                raise
            if current == originals[path]:
                continue
            if current != staged[path]:
                raise StagingError("rollback-source-interference")
            if originals[path] is None:
                destination.unlink()
            else:
                write_atomic(destination, originals[path])
        except (OSError, StagingError):
            failed.append(path)
    return failed


def stage_checkout(root: Path, manifest_path: Path, *, with_kunit: bool = False,
                   with_compressed_handoff: bool = False,
                   with_round024_probe: bool = False) -> dict[str, object]:
    try:
        root = root.resolve(strict=True)
    except OSError as error:
        raise StagingError("complete-git-checkout-required") from error
    manifest_path = manifest_path.resolve(strict=False)
    if manifest_path == root or root in manifest_path.parents:
        raise StagingError("manifest-must-be-outside-linux-checkout")
    validate_checkout(root, with_kunit=with_kunit)

    originals: dict[str, bytes | None] = {}
    staged: dict[str, bytes] = {}
    active_edits = dict(EDITS)
    expected_hashes = dict(ORIGINAL_BLOBS)
    if with_kunit:
        active_edits.update(KUNIT_EDITS)
        expected_hashes.update(KUNIT_ORIGINAL_BLOBS)
    for path in active_edits:
        original = (root / path).read_bytes()
        check_preimage(path, original, expected_hashes[path])
        originals[path] = original
        staged[path] = render_source(
            path, original.decode("utf-8"),
            compressed_handoff=with_compressed_handoff and path == "mm/zswap.c",
            round024_probe=with_round024_probe and path == "mm/zswap.c",
        ).encode("utf-8")
    if with_kunit:
        addition = root / KUNIT_SOURCE_PATH
        if addition.exists() or addition.is_symlink():
            raise StagingError("kunit-source-already-present")
        validate_kunit_source(KUNIT_SOURCE)
        originals[KUNIT_SOURCE_PATH] = None
        staged[KUNIT_SOURCE_PATH] = KUNIT_SOURCE.encode("utf-8")

    # Recheck the entire plan before any mutation, then recheck each file
    # immediately before replacement to catch late source interference.
    for path in sorted(staged):
        destination = root / path
        if originals[path] is None:
            if destination.exists() or destination.is_symlink():
                raise StagingError("kunit-source-already-present")
        else:
            if destination.is_symlink() or not destination.is_file():
                raise StagingError(f"missing-or-symlink-source:{path}")
            check_preimage(path, destination.read_bytes(), expected_hashes[path])

    committed: list[str] = []
    attempted: str | None = None
    try:
        for path in sorted(staged):
            destination = root / path
            if originals[path] is None:
                if destination.exists() or destination.is_symlink():
                    raise StagingError("kunit-source-already-present")
            else:
                check_preimage(path, destination.read_bytes(), expected_hashes[path])
            attempted = path
            write_atomic(destination, staged[path])
            committed.append(path)
            attempted = None
    except (OSError, StagingError) as error:
        touched = committed + ([attempted] if attempted is not None else [])
        rollback_errors = rollback_sources(root, originals, staged, touched)
        if rollback_errors:
            raise StagingError("rollback-incomplete:" + ",".join(rollback_errors)) from error
        raise StagingError("publication-failed-rolled-back") from error

    result: dict[str, object] = {
        "schema": "swapz-pinned-linux-zswap-origin-v1",
        "source_repository": "torvalds/linux",
        "source_sha": LINUX_COMMIT,
        "status": "STAGED_SOURCE_ONLY",
        "changed_paths": [
            {
                "path": path,
                "original_git_sha1": expected_hashes.get(path),
                "original_sha256": (hashlib.sha256(originals[path]).hexdigest()
                                    if originals[path] is not None else None),
                "staged_git_sha1": blob_sha(staged[path]),
                "staged_sha256": hashlib.sha256(staged[path]).hexdigest(),
                "bytes": len(staged[path]),
            }
            for path in sorted(staged)
        ],
        "compiled": False,
        "kunit_executed": False,
        "phase_a_qualified": False,
        "phase_b_enabled": False,
    }
    if with_round024_probe:
        result["round024_kbuild_probe"] = "COMPILE_ONLY_NO_LIVE"
        result["direct_compressed_handoff_enabled"] = False
    if with_compressed_handoff:
        result["direct_compressed_handoff_enabled"] = False
        result["compressed_handoff_prototype"] = "COMPILE_DISABLED_SOURCE_ONLY"
    # The manifest is a bounded evidence file *outside* the Linux checkout.
    temporary_manifest = None
    previous_manifest: bytes | None = None
    manifest_text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    manifest_bytes = manifest_text.encode("utf-8")
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            previous_manifest = manifest_path.read_bytes()
        except FileNotFoundError:
            pass
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".linux-origin-manifest-",
            dir=manifest_path.parent, delete=False,
        ) as stream:
            temporary_manifest = Path(stream.name)
            stream.write(manifest_text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_manifest, manifest_path)
        temporary_manifest = None
    except OSError as error:
        # Even an os.replace() that succeeded before a reported failure
        # must not leave manifest evidence claiming rolled-back source edits.
        manifest_rollback_incomplete = False
        try:
            if manifest_path.is_file():
                current_manifest = manifest_path.read_bytes()
                if current_manifest == manifest_bytes:
                    if previous_manifest is None:
                        manifest_path.unlink()
                    else:
                        write_atomic(manifest_path, previous_manifest)
                elif current_manifest != previous_manifest:
                    manifest_rollback_incomplete = True
            elif previous_manifest is not None:
                manifest_rollback_incomplete = True
        except OSError:
            manifest_rollback_incomplete = True
        rollback_errors = rollback_sources(root, originals, staged, committed)
        if manifest_rollback_incomplete:
            rollback_errors.append("manifest")
        if rollback_errors:
            raise StagingError("manifest-failed-rollback-incomplete:" +
                               ",".join(rollback_errors)) from error
        raise StagingError("manifest-write-failed-rolled-back") from error
    finally:
        if temporary_manifest is not None:
            temporary_manifest.unlink(missing_ok=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--with-kunit", action="store_true",
                        help="Stage pinned BIO KUnit C test and registrations")
    parser.add_argument("--with-compressed-handoff-prototype",
                        action="store_true",
                        help="Stage disabled-only copied zswap payload reference")
    parser.add_argument("--with-round024-zswap-kbuild-probe",
                        action="store_true",
                        help="Stage original kernel compile-only producer gate")
    arguments = parser.parse_args()
    try:
        result = stage_checkout(arguments.linux_root, arguments.manifest,
                                with_kunit=arguments.with_kunit,
                                with_compressed_handoff=
                                    arguments.with_compressed_handoff_prototype,
                                with_round024_probe=
                                    arguments.with_round024_zswap_kbuild_probe)
    except (StagingError, OSError, UnicodeError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    # Success remains quiet; structured source evidence is in --manifest.
    assert len(result["changed_paths"]) == (9 if arguments.with_kunit else 6)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
