#!/usr/bin/env python3
"""Default-undefined original Linux Round056 BIO-owned STORED snapshot stager.

Only the existing original Round031/032 internal owner and original writeback
are modified under explicit KCFLAGS. No production export/ABI/reclaim/count.
"""
from __future__ import annotations

MACRO = "SWAPZ_ROUND056_PREERASE_SINGLE_OWNER_TEST"
GUARD = """#if defined(SWAPZ_ROUND056_PREERASE_SINGLE_OWNER_TEST) && \\
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \\
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)"""

BIO_C = r"""
/* ROUND056_ORIGINAL_BIO_BOUNDED_OWNER_BEGIN */
#if defined(SWAPZ_ROUND056_PREERASE_SINGLE_OWNER_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
#define SWAPZ_ROUND056_MAX_OWNERS 4
#define SWAPZ_ROUND056_MAX_BYTES 3568U

/* One nonblocking, quota-owned flexible-array allocation. No SG alias,
 * additional slot count or new pressure controller. BIO/clone last put
 * releases the owner; missing/never-dispatched BIO releases it inline.
 */
struct swapz_ci_owned_payload *
swapz_round056_owned_reserve_source_v1(size_t compressed_length,
					const u8 original_sha256[32],
					u64 slot_epoch, u64 source_identity,
					u64 source_swap_entry)
{
	struct swapz_ci_owned_payload *owner;
	size_t allocation_bytes;
	u8 digest_present = 0;
	unsigned int index;

	if (!original_sha256 || !compressed_length ||
	    compressed_length > SWAPZ_ROUND056_MAX_BYTES ||
	    !slot_epoch || !source_identity || !source_swap_entry ||
	    check_add_overflow(sizeof(*owner), compressed_length,
			       &allocation_bytes))
		return NULL;
	for (index = 0; index < 32U; index++)
		digest_present |= original_sha256[index];
	if (!digest_present ||
	    !atomic_add_unless(&swapz_round056_held_owners, 1,
			       SWAPZ_ROUND056_MAX_OWNERS))
		return NULL;
	/* Reserve outside the zsmalloc SG scope; never sleep/reclaim. */
	owner = kzalloc(allocation_bytes, GFP_NOWAIT | __GFP_NOWARN);
	if (!owner) {
		atomic_dec(&swapz_round056_held_owners);
		return NULL;
	}
	memcpy(owner->original_sha256, original_sha256, 32U);
	owner->slot_epoch = slot_epoch;
	owner->source_identity = source_identity;
	owner->source_swap_entry = source_swap_entry;
	owner->compressed_length = (u16)compressed_length;
	owner->owned_capacity = (u16)compressed_length;
	owner->decoded_length = 4096U;
	owner->representation_version = 1U;
	owner->codec = 1U; /* Only pinned dictionary-free lz4-scomp. */
	owner->swapz_round056_budgeted = true;
	refcount_set(&owner->references, 1);
	return owner;
}

u8 *swapz_round056_owned_private_bytes(struct swapz_ci_owned_payload *owner,
				      size_t expected_length)
{
	if (!owner || !owner->swapz_round056_budgeted ||
	    owner->swapz_round056_sealed ||
	    refcount_read(&owner->references) != 1 ||
	    expected_length != owner->compressed_length ||
	    expected_length != owner->owned_capacity)
		return NULL;
	return owner->compressed_bytes;
}

bool swapz_round056_owned_seal_source_v1(struct swapz_ci_owned_payload *owner)
{
	if (!owner || !owner->swapz_round056_budgeted ||
	    owner->swapz_round056_sealed ||
	    refcount_read(&owner->references) != 1 ||
	    !owner->compressed_length ||
	    owner->compressed_length > SWAPZ_ROUND056_MAX_BYTES ||
	    owner->compressed_length != owner->owned_capacity)
		return false;
	owner->compressed_crc32c =
		~crc32c(~0U, owner->compressed_bytes, owner->compressed_length);
	owner->swapz_round056_sealed = true;
	return swapz_ci_owned_valid(owner);
}
#endif /* Round056 test-only source allocation */
/* ROUND056_ORIGINAL_BIO_BOUNDED_OWNER_END */
"""

MM_C = r"""
/* ROUND056_ORIGINAL_MM_PREERASE_BEGIN */
#if defined(SWAPZ_ROUND056_PREERASE_SINGLE_OWNER_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
/* Called AFTER genuine current locked folio/xa validation and original
 * zswap_decompress() success, BEFORE xa_erase/zswap_entry_free. There is no
 * independently retained swap-slot count, folio ref or deferred MM callback.
 * Native PG_writeback before unlock owns the existing slot through IO.
 */
static __used noinline struct swapz_ci_owned_payload *
swapz_round056_mm_bio_create(struct zswap_entry *entry, swp_entry_t source_slot,
			     struct xarray *tree, pgoff_t offset,
			     struct folio *folio)
{
	struct zswap_pool *pool;
	struct crypto_acomp_ctx *acomp_ctx;
	struct scatterlist compressed_sg[2];
	struct swapz_ci_owned_payload *owner = NULL;
	const u8 *decoded;
	u8 decoded_sha256[SHA256_DIGEST_SIZE];
	u8 *destination;
	u64 allocation_epoch, stored_identity;
	unsigned int length;

	if (!folio || !folio_test_locked(folio) ||
	    !folio_test_swapcache(folio) || folio_nr_pages(folio) != 1U ||
	    PAGE_SIZE != 4096U || folio->swap.val != source_slot.val ||
	    !source_slot.val || sizeof(source_slot.val) > sizeof(u64))
		return NULL;
	if (!entry || !tree || xa_load(tree, offset) != entry ||
	    entry->swpentry.val != source_slot.val ||
	    !entry->swapz_round028_store_bound ||
	    !entry->swapz_round028_allocation_epoch ||
	    !entry->swapz_round028_stored_entry_identity ||
	    !entry->handle || !entry->length || entry->length > 3568U)
		return NULL;
	pool = zswap_entry_pool(entry);
	if (!pool || !pool->zs_pool || !pool->acomp_ctx ||
	    strcmp(pool->tfm_name, "lz4"))
		return NULL;
	/* Pool name alone is not a selected-driver/format certificate. */
	acomp_ctx = raw_cpu_ptr(pool->acomp_ctx);
	if (!acomp_ctx || IS_ERR_OR_NULL(acomp_ctx->acomp) ||
	    strcmp(crypto_acomp_alg_name(acomp_ctx->acomp), "lz4") ||
	    strcmp(crypto_acomp_driver_name(acomp_ctx->acomp), "lz4-scomp"))
		return NULL;
	decoded = kmap_local_folio(folio, 0);
	sha256(decoded, PAGE_SIZE, decoded_sha256);
	kunmap_local(decoded);
	if (memcmp(decoded_sha256, entry->swapz_round028_store_sha256,
		   sizeof(decoded_sha256)))
		goto no_owner;
	allocation_epoch = swapz_round028_slot_epoch(source_slot);
	if (!allocation_epoch ||
	    allocation_epoch != entry->swapz_round028_allocation_epoch)
		goto no_owner;
	length = entry->length;
	stored_identity = entry->swapz_round028_stored_entry_identity;
	owner = swapz_round056_owned_reserve_source_v1(
		length, decoded_sha256, allocation_epoch, stored_identity,
		(u64)source_slot.val);
	if (!owner)
		goto no_owner;
	destination = swapz_round056_owned_private_bytes(owner, length);
	if (!destination)
		goto release_owner;

	/* Copy exactly once from current original zsmalloc SG into the sole
	 * private BIO owner; no allocation or sleep while SG is mapped.
	 */
	zs_obj_read_sg_begin(pool->zs_pool, entry->handle, compressed_sg, length);
	memcpy_from_sglist(destination, compressed_sg, 0, length);
	zs_obj_read_sg_end(pool->zs_pool, entry->handle);

	if (entry != xa_load(tree, offset) ||
	    entry->swpentry.val != source_slot.val ||
	    !entry->swapz_round028_store_bound ||
	    entry->swapz_round028_allocation_epoch != allocation_epoch ||
	    entry->swapz_round028_stored_entry_identity != stored_identity ||
	    zswap_entry_pool(entry) != pool || entry->length != length ||
	    allocation_epoch != swapz_round028_slot_epoch(source_slot) ||
	    !swapz_round056_owned_seal_source_v1(owner))
		goto release_owner;
	memzero_explicit(decoded_sha256, sizeof(decoded_sha256));
	return owner;
release_owner:
	swapz_ci_owned_put(owner);
no_owner:
	memzero_explicit(decoded_sha256, sizeof(decoded_sha256));
	return NULL;
}
#endif /* Round056 CI-only pre-erase source snapshot */
/* ROUND056_ORIGINAL_MM_PREERASE_END */
"""

# No new KUnit suite/count: extend one already-registered original block/bio.c
# C KUnit case with actual allocator, budget, invalid-before-seal and last put.
KUNIT_C = r"""
/* ROUND056_ORIGINAL_KUNIT_OWNER_BEGIN */
#if defined(SWAPZ_ROUND056_PREERASE_SINGLE_OWNER_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
static void swapz_round056_owned_budget_kunit(struct kunit *test)
{
	struct swapz_ci_owned_payload *owners[SWAPZ_ROUND056_MAX_OWNERS] = {};
	struct swapz_ci_owned_payload *reused;
	u8 original_sha256[32] = { 0x39 };
	u8 payload[48];
	u8 *destination;
	unsigned int index;

	KUNIT_EXPECT_EQ(test, atomic_read(&swapz_round056_held_owners), 0);
	KUNIT_EXPECT_PTR_EQ(test, swapz_round056_owned_reserve_source_v1(
			    0U, original_sha256, 1U, 2U, 3U), NULL);
	KUNIT_EXPECT_PTR_EQ(test, swapz_round056_owned_reserve_source_v1(
			    3569U, original_sha256, 1U, 2U, 3U), NULL);
	KUNIT_EXPECT_PTR_EQ(test, swapz_round056_owned_reserve_source_v1(
			    sizeof(payload), original_sha256, 0U, 2U, 3U),
			    NULL);
	memset(payload, 0x51, sizeof(payload));
	for (index = 0; index < ARRAY_SIZE(owners); index++) {
		owners[index] = swapz_round056_owned_reserve_source_v1(
			sizeof(payload), original_sha256, 1U, 2U,
			(u64)index + 3U);
		if (!owners[index]) {
			KUNIT_FAIL(test, "bounded nonblocking reservation failed");
			goto cleanup;
		}
		destination = swapz_round056_owned_private_bytes(
			owners[index], sizeof(payload));
		if (!destination) {
			KUNIT_FAIL(test, "private one-allocation bytes missing");
			goto cleanup;
		}
		memcpy(destination, payload, sizeof(payload));
		KUNIT_EXPECT_FALSE(test, swapz_ci_owned_valid(owners[index]));
		KUNIT_EXPECT_TRUE(test,
			swapz_round056_owned_seal_source_v1(owners[index]));
		KUNIT_EXPECT_TRUE(test, swapz_ci_owned_valid(owners[index]));
		KUNIT_EXPECT_PTR_EQ(test, swapz_round056_owned_private_bytes(
				    owners[index], sizeof(payload)), NULL);
		KUNIT_EXPECT_FALSE(test,
			swapz_round056_owned_seal_source_v1(owners[index]));
		KUNIT_EXPECT_EQ(test, memcmp(owners[index]->compressed_bytes,
					     payload, sizeof(payload)), 0);
	}
	KUNIT_EXPECT_EQ(test, atomic_read(&swapz_round056_held_owners),
			SWAPZ_ROUND056_MAX_OWNERS);
	KUNIT_EXPECT_PTR_EQ(test, swapz_round056_owned_reserve_source_v1(
			    sizeof(payload), original_sha256, 1U, 2U, 7U),
			    NULL);
	swapz_ci_owned_put(owners[0]);
	owners[0] = NULL;
	reused = swapz_round056_owned_reserve_source_v1(
		sizeof(payload), original_sha256, 1U, 2U, 7U);
	KUNIT_EXPECT_NOT_NULL(test, reused);
	swapz_ci_owned_put(reused);
cleanup:
	for (index = 0; index < ARRAY_SIZE(owners); index++)
		swapz_ci_owned_put(owners[index]);
	KUNIT_EXPECT_EQ(test, atomic_read(&swapz_round056_held_owners), 0);
}
#endif
/* ROUND056_ORIGINAL_KUNIT_OWNER_END */
"""


def apply(path: str, composed: str, replace_once, *, with_kunit: bool) -> str:
    """Called after Round031..054 on verified pristine original postimages."""
    if path == "include/linux/bio.h":
        return replace_once(
            composed,
            "struct swapz_ci_owned_payload *swapz_ci_owned_create_source_v1(",
            GUARD + """
struct swapz_ci_owned_payload *swapz_round056_owned_reserve_source_v1(
		size_t compressed_length, const u8 original_sha256[32],
		u64 slot_epoch, u64 source_identity, u64 source_swap_entry);
u8 *swapz_round056_owned_private_bytes(
		struct swapz_ci_owned_payload *owner, size_t expected_length);
bool swapz_round056_owned_seal_source_v1(
		struct swapz_ci_owned_payload *owner);
#endif
struct swapz_ci_owned_payload *swapz_ci_owned_create_source_v1(""",
            path, "round056-private-original-header")
    if path == "block/bio.c":
        composed = replace_once(
            composed, "\tu64 source_swap_entry; /* FULL original MM value before first ref. */\n",
            "\tu64 source_swap_entry; /* FULL original MM value before first ref. */\n" +
            GUARD + """
	bool swapz_round056_budgeted;
	bool swapz_round056_sealed;
#endif
""", path, "round056-owner-budget-tags")
        composed = replace_once(
            composed, "\tu8 compressed_bytes[];\n};\n",
            "\tu8 compressed_bytes[];\n};\n" + GUARD + """
static atomic_t swapz_round056_held_owners = ATOMIC_INIT(0);
#endif
""", path, "round056-bounded-four-owner-counter")
        valid_header = (
            "static bool swapz_ci_owned_valid("
            "const struct swapz_ci_owned_payload *owner)\n{\n")
        composed = replace_once(
            composed, valid_header,
            valid_header + GUARD + """
	if (owner && owner->swapz_round056_budgeted &&
	    !owner->swapz_round056_sealed)
		return false;
#endif
""", path, "round056-refuse-unsealed-owner")
        composed = replace_once(
            composed,
            "/* Refcount acquisition requires a live parent BIO as external owner. */",
            BIO_C +
            "\n/* Refcount acquisition requires a live parent BIO as external owner. */",
            path, "round056-original-bio-reserve-copy-seal")
        old_put = """void swapz_ci_owned_put(struct swapz_ci_owned_payload *owner)
{
	if (owner && refcount_dec_and_test(&owner->references))
		kfree_sensitive(owner);
}"""
        new_put = """void swapz_ci_owned_put(struct swapz_ci_owned_payload *owner)
{
	if (owner && refcount_dec_and_test(&owner->references)) {
""" + GUARD + """
		bool budgeted = owner->swapz_round056_budgeted;
#endif
		kfree_sensitive(owner);
""" + GUARD + """
		/* Return admission only AFTER memory is freed, not before. */
		if (budgeted)
			atomic_dec(&swapz_round056_held_owners);
#endif
	}
}"""
        composed = replace_once(composed, old_put, new_put,
                                path, "round056-one-last-put-unwind")
        if with_kunit:
            kunit_header = (
                "static void swapz_round034_v1_owned_copy_kunit("
                "struct kunit *test)\n")
            composed = replace_once(
                composed, kunit_header, KUNIT_C + kunit_header,
                path, "round056-inherited-registered-C-test")
            composed = replace_once(
                composed, "\tKUNIT_ASSERT_NOT_NULL(test, fixture);\n"
                          "\tKUNIT_EXPECT_EQ(test, fixture->bio.bi_vcnt, 0U);",
                "\tKUNIT_ASSERT_NOT_NULL(test, fixture);\n" + GUARD +
                """
	swapz_round056_owned_budget_kunit(test);
#endif
	KUNIT_EXPECT_EQ(test, fixture->bio.bi_vcnt, 0U);""",
                path, "round056-C-real-original-registration-unchanged")
        return composed
    if path == "mm/zswap.c":
        composed = replace_once(
            composed, "static int zswap_writeback_entry(struct zswap_entry *entry,\n",
            MM_C + "\nstatic int zswap_writeback_entry(struct zswap_entry *entry,\n",
            path, "round056-original-preerase-SG-ownership")
        # Round030's older pre-decode diagnostic consumes
        # entry->swapz_round028_store_bound=true on success. With the
        # Round056 producer moved AFTER native decompression, that
        # diagnostic must not retire the same proof before capture.
        # Keep it byte-for-byte active for every older/default guard.
        old_diagnostic = (
            "\t(void)swapz_round030_snapshot_stored_lz4("
            "entry, swpentry, tree, offset);\n")
        composed = replace_once(
            composed, old_diagnostic,
            "#if !defined(SWAPZ_ROUND056_PREERASE_SINGLE_OWNER_TEST)\n" +
            old_diagnostic + "#endif\n",
            path, "round056-disable-predecode-consuming-diagnostic")
        # Preserve the original pre-decode owner for older/default profiles.
        # Under Round056 only the post-decode, pre-erase owner is eligible.
        composed = replace_once(
            composed,
            "\tctx.swapz_round031_owned =\n"
            "\t\tswapz_round031_mm_bio_create(entry, swpentry, tree, offset);\n",
            "#if !defined(SWAPZ_ROUND056_PREERASE_SINGLE_OWNER_TEST)\n"
            "\tctx.swapz_round031_owned =\n"
            "\t\tswapz_round031_mm_bio_create(entry, swpentry, tree, offset);\n"
            "#endif\n",
            path, "round056-legacy-owner-only-without-guard")
        # The native decompression may fail. Capture only its successful
        # original full 4096-byte folio, before xa_erase/entry_free.
        successful_decode = (
            "\tif (!zswap_decompress(entry, folio)) {\n"
            "\t\tret = -EIO;\n"
            "\t\tgoto err;\n"
            "\t}\n\n")
        return replace_once(
            composed, successful_decode,
            successful_decode + GUARD + """
\tctx.swapz_round031_owned =
\t\tswapz_round056_mm_bio_create(entry, swpentry, tree, offset,
\t\t\t\t\t    folio);
#endif
""", path, "round056-after-original-decompress-before-erase")
    return composed
