// SPDX-License-Identifier: GPL-2.0-only
/*
 * Round079 original pinned zswap pre-erase source contract, HOST MODEL ONLY.
 * The four decision expressions in the generated header are copied verbatim
 * from SHA-verified torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8
 * mm/zswap.c; original zsmalloc SG begin/end source is also SHA-verified.
 *
 * This is NOT a compiled Linux MM/zsmalloc implementation. Every source slot,
 * locked folio, XArray, zpool object, owned copy, decoder and lower FUA/ACK is
 * modeled single-thread state. Real STORED source/DM ownership: UNPROVEN.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include "round079-original-source-predicates.h"

enum { PAGE_SIZE = 4096, IMPORT_COMPRESSED_LIMIT = 3568,
       SOURCE_PAGE_OFFSET = 1024 };
enum original_codec { ORIGINAL_LZ4 = 1, ORIGINAL_LZO1X = 2 };

#define GUARD_XARRAY 1
#define GUARD_SLOT 1
#define GUARD_GENERATION 1
#define GUARD_FOLIO_LOCK 1
#define GUARD_POOL_REFERENCE 1
#define GUARD_HANDLE 1
#define GUARD_PREERASE 1
#define GUARD_ZERO_LENGTH 1
#define GUARD_ABOVE_PAGE 1
#define GUARD_IMPORT_LIMIT 1
#define GUARD_RAW_FALLBACK 1
#define GUARD_CODEC 1
#define GUARD_DECODER_GENERATION 1
#define GUARD_SG_END 1
#define GUARD_EXACT_COPY 1
#define GUARD_RETIRED_READER 1
#define GUARD_LOWER_DURABILITY 1
#define GUARD_ACK_ONCE 1
#define GUARD_PUBLISH_ONCE 1
#define GUARD_SHORT_CAPACITY 1

struct original_entry {
	uint64_t slot;
	uint64_t store_generation;
	size_t length;
	unsigned long handle;
	uint8_t pool_idx;
};

struct original_pool {
	uint8_t idx;
	enum original_codec codec;
	uint64_t decoder_generation;
	unsigned int references;
	bool registered;
	bool handle_live;
	bool sg_read_locked;
};

struct original_xarray {
	struct original_entry *current;
	size_t current_offset;
};

struct original_source {
	struct original_entry entry;
	struct original_pool pool;
	struct original_xarray tree;
	uint8_t page_one[PAGE_SIZE];
	uint8_t page_two[PAGE_SIZE];
	uint64_t requested_slot;
	uint64_t requested_generation;
	uint64_t requested_decoder_generation;
	unsigned long expected_handle;
	bool folio_locked;
	bool erased;
	bool entry_freed;
	unsigned int source_sg_begins;
	unsigned int source_sg_ends;
	unsigned int simulated_slow_work_while_locked;
};

struct immutable_owned {
	uint8_t bytes[PAGE_SIZE];
	size_t length;
	uint64_t slot;
	uint64_t store_generation;
	uint64_t decoder_generation;
	enum original_codec codec;
	unsigned int old_reader_pins;
	bool published;
	bool retired;
	bool freed;
	bool lower_durable;
	bool acked;
};

static const char *current_case;

#define R079_ASSERT(test) do { \
	if (!(test)) { \
		fprintf(stderr, "ROUND079_FIRST_ERROR case=%s line=%d failed=%s\n", \
			current_case, __LINE__, #test); \
		return 3; \
	} \
} while (0)

static struct original_entry *xa_load(const struct original_xarray *tree,
				      size_t offset)
{
	if (!tree || offset != tree->current_offset)
		return NULL;
	return tree->current;
}

/* Test-only model of original zsmalloc read SG lifetime, not kernel code. */
static void model_zs_obj_read_sg_begin(struct original_source *source)
{
	source->pool.sg_read_locked = true;
	++source->source_sg_begins;
}

static void model_zs_obj_read_sg_end(struct original_source *source)
{
	source->pool.sg_read_locked = false;
	++source->source_sg_ends;
}

static void initialize_source(struct original_source *source, size_t length,
			      enum original_codec codec)
{
	size_t index;

	memset(source, 0, sizeof(*source));
	source->entry.slot = 0x1234U;
	source->entry.store_generation = 0x4567U;
	source->entry.length = length;
	source->entry.handle = 0x777U;
	source->entry.pool_idx = 5U;
	source->pool.idx = 5U;
	source->pool.codec = codec;
	source->pool.decoder_generation = 0x8899U;
	source->pool.references = 1U;
	source->pool.registered = true;
	source->pool.handle_live = true;
	source->tree.current = &source->entry;
	source->tree.current_offset = 0x1234U;
	source->requested_slot = source->entry.slot;
	source->requested_generation = source->entry.store_generation;
	source->requested_decoder_generation = source->pool.decoder_generation;
	source->expected_handle = source->entry.handle;
	source->folio_locked = true;
	for (index = 0U; index < PAGE_SIZE; ++index) {
		source->page_one[index] = (uint8_t)((index * 13U + 7U) & 255U);
		source->page_two[index] = (uint8_t)((index * 11U + 9U) & 255U);
	}
}

/*
 * A future distinct original-compressed owner would have to capture under a
 * valid actual swapcache/XArray/handle/pool/SG lifetime. The current kernel
 * DOES NOT invoke this hook. This model explicitly refuses ambiguous state.
 * No slow SHA, lower I/O or worker dispatch is performed under source locks.
 */
static int capture_preerase_owned(struct original_source *source,
				 struct original_entry *requested,
				 struct immutable_owned *owned,
				 size_t destination_capacity)
{
	struct original_entry *entry = requested;
	struct original_pool *pool;
	struct original_xarray *tree;
	struct immutable_owned staged = { 0 };
	size_t offset, first_length, second_length;
	int comp_ret = 0;
	size_t dlen;

	if (!source || !entry || !owned)
		return -EINVAL;
	pool = &source->pool;
	tree = &source->tree;
	offset = (size_t)source->requested_slot;
	dlen = entry->length;
	if (GUARD_FOLIO_LOCK && !source->folio_locked)
		return -EPERM;
	if (GUARD_PREERASE && (source->erased || source->entry_freed))
		return -ESTALE;
	if (GUARD_XARRAY && R079_ORIGINAL_XARRAY_MISMATCH)
		return -ESTALE;
	if (GUARD_SLOT && entry->slot != source->requested_slot)
		return -ESTALE;
	if (GUARD_GENERATION &&
	    entry->store_generation != source->requested_generation)
		return -ESTALE;
	if (GUARD_POOL_REFERENCE &&
	    (R079_ORIGINAL_POOL_MISSING || !pool->registered ||
	     pool->references == 0U || pool->idx != entry->pool_idx))
		return -ESTALE;
	if (GUARD_HANDLE &&
	    (!pool->handle_live || !entry->handle ||
	     source->expected_handle != entry->handle))
		return -ESTALE;
	/* The pinned original compressor stores the full original PAGE_SIZE
	 * uncompressed when compression fails; never decode it as LZ4/LZO. */
	if (GUARD_RAW_FALLBACK && R079_ORIGINAL_UNCOMPRESSED)
		return -EOPNOTSUPP;
	if (GUARD_ZERO_LENGTH && !dlen)
		return -EMSGSIZE;
	if (GUARD_ABOVE_PAGE && dlen > PAGE_SIZE)
		return -EOVERFLOW;
	if (GUARD_IMPORT_LIMIT && dlen > IMPORT_COMPRESSED_LIMIT)
		return -EMSGSIZE;
	if (GUARD_SHORT_CAPACITY && destination_capacity < dlen)
		return -EMSGSIZE;
	if (GUARD_CODEC && pool->codec != ORIGINAL_LZ4 &&
	    pool->codec != ORIGINAL_LZO1X)
		return -EOPNOTSUPP;
	if (GUARD_DECODER_GENERATION &&
	    pool->decoder_generation != source->requested_decoder_generation)
		return -ESTALE;
	if (GUARD_PUBLISH_ONCE && owned->published)
		return -ESTALE;
	/* This expression is extracted from zswap_compress() exactly and
	 * evaluated in an independent host model, not a kernel path. */
	if (comp_ret != 0 || R079_ORIGINAL_BAD_COMPRESS)
		return -EIO;

	/* Simulate zs_obj_read_sg_begin/end holding a 1- or 2-page mapping.
	 * Source page offset is fixed; lengths 3073..3568 span two pages. */
	model_zs_obj_read_sg_begin(source);
	first_length = PAGE_SIZE - SOURCE_PAGE_OFFSET;
	if (first_length > dlen)
		first_length = dlen;
	second_length = dlen - first_length;
	if (GUARD_EXACT_COPY) {
		memcpy(staged.bytes, source->page_one + SOURCE_PAGE_OFFSET,
		       first_length);
	} else {
		memcpy(staged.bytes, source->page_one + SOURCE_PAGE_OFFSET - 1U,
		       first_length);
	}
	if (second_length)
		memcpy(staged.bytes + first_length, source->page_two,
		       second_length);
	if (GUARD_SG_END)
		model_zs_obj_read_sg_end(source);
	staged.length = dlen;
	staged.slot = entry->slot;
	staged.store_generation = entry->store_generation;
	staged.decoder_generation = pool->decoder_generation;
	staged.codec = pool->codec;
	staged.published = true;
	*owned = staged;
	return 0;
}

static int read_retained_gc(const struct immutable_owned *owned,
			    uint8_t *destination, size_t capacity)
{
	if (!owned || !destination)
		return -EINVAL;
	if (GUARD_RETIRED_READER &&
	    (!owned->old_reader_pins || owned->freed))
		return -ESTALE;
	if (capacity < owned->length)
		return -EMSGSIZE;
	memcpy(destination, owned->bytes, owned->length);
	return 0;
}

static int model_upper_ack_once(struct immutable_owned *owned)
{
	if (!owned || !owned->published)
		return -ESTALE;
	if (GUARD_LOWER_DURABILITY && !owned->lower_durable)
		return -EIO;
	if (GUARD_ACK_ONCE && owned->acked)
		return -ESTALE;
	owned->acked = true;
	return 0;
}

static int test_owned_before_original_free(void)
{
	struct original_source source;
	struct immutable_owned owned = { 0 };
	uint8_t expected[IMPORT_COMPRESSED_LIMIT];
	uint8_t copied[IMPORT_COMPRESSED_LIMIT];
	size_t index;
	const size_t first_length = PAGE_SIZE - SOURCE_PAGE_OFFSET;

	current_case = "owned-byte-exact-before-original-xa-erase-free";
	initialize_source(&source, IMPORT_COMPRESSED_LIMIT, ORIGINAL_LZ4);
	memcpy(expected, source.page_one + SOURCE_PAGE_OFFSET, first_length);
	memcpy(expected + first_length, source.page_two,
	       IMPORT_COMPRESSED_LIMIT - first_length);
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == 0);
	R079_ASSERT(owned.published && owned.length == sizeof(expected));
	R079_ASSERT(!source.pool.sg_read_locked);
	R079_ASSERT(source.source_sg_begins == 1U &&
		    source.source_sg_ends == 1U);
	R079_ASSERT(!memcmp(owned.bytes, expected, sizeof(expected)));
	/* Source XArray erase, handle free, pool put, then poison occur only
	 * AFTER standalone owned snapshot exists. No borrowed pointer. */
	source.tree.current = NULL;
	source.erased = true;
	source.entry_freed = true;
	source.pool.handle_live = false;
	source.pool.references = 0U;
	source.pool.registered = false;
	memset(source.page_one, 0xa5, sizeof(source.page_one));
	memset(source.page_two, 0x5a, sizeof(source.page_two));
	for (index = 0U; index < sizeof(expected); ++index)
		R079_ASSERT(owned.bytes[index] == expected[index]);
	R079_ASSERT(source.simulated_slow_work_while_locked == 0U);
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -ESTALE);
	owned.old_reader_pins = 1U;
	owned.retired = true;
	R079_ASSERT(read_retained_gc(&owned, copied, sizeof(copied)) == 0);
	R079_ASSERT(!memcmp(copied, expected, sizeof(expected)));
	owned.old_reader_pins = 0U;
	owned.freed = true;
	R079_ASSERT(read_retained_gc(&owned, copied, sizeof(copied)) == -ESTALE);
	return 0;
}

static int test_original_source_negative_lifetimes(void)
{
	struct original_source source;
	struct original_entry stale_entry;
	struct immutable_owned owned = { 0 };

	current_case = "original-source-xarray-folio-pool-handle-negative";
	initialize_source(&source, 1800U, ORIGINAL_LZO1X);
	stale_entry = source.entry;
	R079_ASSERT(capture_preerase_owned(&source, &stale_entry, &owned,
					   sizeof(owned.bytes)) == -ESTALE);
	source.erased = true;
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -ESTALE);
	source.erased = false;
	++source.entry.slot;
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -ESTALE);
	--source.entry.slot;
	++source.requested_generation;
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -ESTALE);
	--source.requested_generation;
	source.folio_locked = false;
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -EPERM);
	source.folio_locked = true;
	source.pool.references = 0U;
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -ESTALE);
	source.pool.references = 1U;
	source.entry.handle = 0U;
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -ESTALE);
	source.entry.handle = source.expected_handle;
	++source.pool.decoder_generation;
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -ESTALE);
	--source.pool.decoder_generation;
	source.pool.codec = (enum original_codec)7;
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -EOPNOTSUPP);
	source.pool.codec = ORIGINAL_LZO1X;
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   1799U) == -EMSGSIZE);
	R079_ASSERT(!owned.published && !source.pool.sg_read_locked);
	return 0;
}

static int test_original_length_and_raw_fallback(void)
{
	struct original_source source;
	struct immutable_owned owned = { 0 };

	current_case = "original-one-to-4095-and-raw-full-original-fallback";
	initialize_source(&source, 0U, ORIGINAL_LZ4);
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -EMSGSIZE);
	source.entry.length = PAGE_SIZE + 1U;
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -EOVERFLOW);
	source.entry.length = 3569U;
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -EMSGSIZE);
	source.entry.length = PAGE_SIZE - 1U;
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -EMSGSIZE);
	source.entry.length = PAGE_SIZE;
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -EOPNOTSUPP);
	/* Source fallback corresponds to original FULL 4096 bytes, not
	 * opaque original compressed data or SWAPZ disk codec. */
	{
		int comp_ret = 0;
		size_t dlen = PAGE_SIZE;
		struct original_entry *entry = &source.entry;
		R079_ASSERT(R079_ORIGINAL_BAD_COMPRESS);
		R079_ASSERT(R079_ORIGINAL_UNCOMPRESSED);
		R079_ASSERT(comp_ret == 0 && dlen == PAGE_SIZE);
	}
	R079_ASSERT(!owned.published);
	return 0;
}

static int test_once_only_publish_and_lower_ack(void)
{
	struct original_source source;
	struct immutable_owned owned = { 0 };

	current_case = "distinct-owned-publish-lower-fua-and-once-only-upper-ack";
	initialize_source(&source, 3073U, ORIGINAL_LZO1X);
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == 0);
	R079_ASSERT(capture_preerase_owned(&source, &source.entry, &owned,
					   sizeof(owned.bytes)) == -ESTALE);
	R079_ASSERT(model_upper_ack_once(&owned) == -EIO);
	owned.lower_durable = true; /* TEST MODELED ONLY, NOT PHYSICAL FUA */
	R079_ASSERT(model_upper_ack_once(&owned) == 0);
	R079_ASSERT(model_upper_ack_once(&owned) == -ESTALE);
	return 0;
}

int main(void)
{
	if (test_owned_before_original_free() ||
	    test_original_source_negative_lifetimes() ||
	    test_original_length_and_raw_fallback() ||
	    test_once_only_publish_and_lower_ack())
		return 3;
	puts("PASS round079 original_MM_decisions_extracted=4"
	     " source_model_cases=4 original_zsmalloc_SG_lock=MODEL"
	     " original_codec_tag=VOLATILE LZ4_LZO1X=IDENTITY_ONLY"
	     " copied_exact_bytes=3568 original_length_3569_to_4095=BLOCKED"
	     " ordinary_RAW_4096=FULL_UNCOMPRESSED"
	     " modeled_FUA_ACK=ONLY original_KUnit=NOT_RUN AUTH0 PHASE_A=BLOCKED");
	return 0;
}
