/* SPDX-License-Identifier: GPL-2.0-only */
/* The REAL Round031 original mm/zswap.c emitted C body is injected below.
 * Host mocks only zsmalloc, xarray and BIO malloc/refcount boundaries.
 * No synthetic value is claimed to authenticate a real kernel BIO.
 */
#define SWAPZ_ROUND031_MM_BIO_SOURCE 1
#define SWAPZ_ROUND028_SLOT_EPOCH_SOURCE 1
#define SWAPZ_ROUND025_SIDEBAND_CI_ONLY 1
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <lz4.h>
#include <openssl/sha.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef unsigned long pgoff_t;
typedef struct { unsigned long val; } swp_entry_t;
#define PAGE_SIZE 4096U
#define GFP_KERNEL 0U
#define __used __attribute__((used))
#define noinline __attribute__((noinline))
struct scatterlist { const u8 *source; unsigned int length; };
struct zs_pool { int serial; };
struct zswap_pool { struct zs_pool *zs_pool; char tfm_name[24]; };
struct zswap_entry {
	swp_entry_t swpentry;
	unsigned int length;
	unsigned long handle;
	bool swapz_round028_store_bound;
	u64 swapz_round028_allocation_epoch;
	u64 swapz_round028_stored_entry_identity;
	u8 swapz_round028_store_sha256[32];
	struct zswap_pool *pool;
};
struct xarray { struct zswap_entry *entry; };
struct swapz_ci_owned_payload {
	unsigned int references;
	u64 source_epoch;
	u64 source_identity;
	u8 sha[32];
	u32 crc;
	size_t compressed_length;
	u8 bytes[3568];
};
static u64 active_epoch = 23U;
static bool inject_epoch_during_copy;
static bool inject_malloc_failure;
static unsigned int pool_begins, pool_ends, allocations, free_count;
static unsigned int constructor_count;
static unsigned int source_copy_count;
static struct zswap_entry *xa_load(struct xarray *tree, pgoff_t offset)
{
	assert(offset == 5U);
	return tree->entry;
}
static struct zswap_pool *zswap_entry_pool(struct zswap_entry *entry)
{
	return entry->pool;
}
static u64 swapz_round028_slot_epoch(swp_entry_t slot)
{
	assert(slot.val == 5U);
	return active_epoch;
}
static void *kmalloc(size_t size, unsigned int gfp)
{
	void *memory;
	(void)gfp;
	if (inject_malloc_failure)
		return NULL;
	memory = malloc(size);
	if (memory)
		++allocations;
	return memory;
}
static void kfree_sensitive(void *memory)
{
	if (memory) {
		assert(allocations != 0U);
		--allocations;
		++free_count;
		free(memory);
	}
}
static void zs_obj_read_sg_begin(struct zs_pool *pool,
				unsigned long handle,
				struct scatterlist *sg,
				unsigned int length)
{
	assert(pool && handle && length);
	++pool_begins;
	sg[0].source = (const u8 *)(uintptr_t)handle;
	sg[0].length = length;
}
static void memcpy_from_sglist(void *destination,
			       const struct scatterlist *sg,
			       unsigned int offset, unsigned int count)
{
	assert(offset == 0U && count == sg[0].length);
	memcpy(destination, sg[0].source, count);
	++source_copy_count;
	if (inject_epoch_during_copy)
		++active_epoch;
}
static void zs_obj_read_sg_end(struct zs_pool *pool, unsigned long handle)
{
	assert(pool && handle);
	++pool_ends;
}
static u32 crc32c(u32 crc, const u8 *source, unsigned int length)
{
	for (unsigned int index = 0; index < length; ++index) {
		crc ^= source[index];
		for (unsigned int bit = 0; bit < 8; ++bit)
			crc = (crc >> 1) ^ ((crc & 1U) ? 0x82f63b78U : 0U);
	}
	return crc;
}
static struct swapz_ci_owned_payload *swapz_ci_owned_create(
	const u8 *source, size_t capacity, size_t length,
	const u8 original_sha256[32], u64 epoch, u64 identity,
	u8 version, u8 codec, u32 checksum, unsigned int gfp)
{
	struct swapz_ci_owned_payload *owner;
	u8 digest_nonzero = 0;
	(void)gfp;
	++constructor_count;
	if (!source || !original_sha256 || !capacity || length > capacity ||
	    length > 3568U || !length || !epoch || !identity ||
	    version != 1U || codec != 1U)
		return NULL;
	for (unsigned int index = 0; index < 32U; ++index)
		digest_nonzero |= original_sha256[index];
	if (!digest_nonzero || ~crc32c(~0U, source, (unsigned int)length) != checksum)
		return NULL;
	owner = malloc(sizeof(*owner));
	if (!owner)
		return NULL;
	memset(owner, 0, sizeof(*owner));
	owner->references = 1U;
	owner->compressed_length = length;
	owner->crc = checksum;
	owner->source_epoch = epoch;
	owner->source_identity = identity;
	memcpy(owner->sha, original_sha256, 32);
	memcpy(owner->bytes, source, length);
	return owner;
}
static void swapz_ci_owned_put(struct swapz_ci_owned_payload *owner)
{
	if (owner) {
		assert(owner->references);
		if (--owner->references == 0U)
			free(owner);
	}
}

/* ROUND031_EXACT_ORIGINAL_MM_C */

int main(void)
{
	u8 original[4096] = { 0 };
	u8 compressed[3568] = { 0 };
	struct zs_pool zsmalloc_pool = { .serial = 8 };
	struct zswap_pool pool = {
		.zs_pool = &zsmalloc_pool, .tfm_name = "lz4",
	};
	struct zswap_entry entry = {
		.swpentry = { .val = 5U },
		.swapz_round028_store_bound = true,
		.swapz_round028_allocation_epoch = 23U,
		.swapz_round028_stored_entry_identity = 24U,
		.pool = &pool,
	};
	struct xarray tree = { .entry = &entry };
	const swp_entry_t slot = { .val = 5U };
	struct swapz_ci_owned_payload *owner;
	size_t index;
	int compressed_length;
	unsigned int before;

	for (index = 0; index < sizeof(original); ++index)
		original[index] = (u8)(index % 29U);
	assert(SHA256(original, sizeof(original),
		      entry.swapz_round028_store_sha256));
	compressed_length = LZ4_compress_default(
		(const char *)original, (char *)compressed,
		(int)sizeof(original), (int)sizeof(compressed));
	assert(compressed_length > 0 && compressed_length <= 3568);
	entry.length = (unsigned int)compressed_length;
	entry.handle = (unsigned long)(uintptr_t)compressed;
	assert(~crc32c(~0U, (const u8 *)"123456789", 9U) == 0xe3069283U);

	/* Real original stored bytes, independent copy, genuine LZ4 and SHA. */
	owner = swapz_round031_mm_bio_create(&entry, slot, &tree, 5U);
	assert(owner && owner->references == 1U && owner->source_epoch == 23U);
	assert(owner->source_identity == 24U);
	assert(owner->compressed_length == (size_t)compressed_length);
	assert(owner->crc == ~crc32c(~0U, compressed, (unsigned int)compressed_length));
	assert(memcmp(owner->bytes, compressed, (size_t)compressed_length) == 0);
	assert(memcmp(owner->sha, entry.swapz_round028_store_sha256, 32U) == 0);
	assert(allocations == 0U && pool_begins == pool_ends);
	/* Verify deep ownership: source may be mutated after owned constructor. */
	compressed[0] ^= 0x80;
	assert(owner->bytes[0] != compressed[0]);
	compressed[0] ^= 0x80;
	swapz_ci_owned_put(owner);

	before = constructor_count;
	active_epoch++;
	assert(swapz_round031_mm_bio_create(&entry, slot, &tree, 5U) == NULL);
	active_epoch--;
	assert(constructor_count == before);
	entry.swapz_round028_stored_entry_identity = 0U;
	assert(swapz_round031_mm_bio_create(&entry, slot, &tree, 5U) == NULL);
	entry.swapz_round028_stored_entry_identity = 24U;
	entry.swapz_round028_store_bound = false;
	assert(swapz_round031_mm_bio_create(&entry, slot, &tree, 5U) == NULL);
	entry.swapz_round028_store_bound = true;
	tree.entry = NULL;
	assert(swapz_round031_mm_bio_create(&entry, slot, &tree, 5U) == NULL);
	tree.entry = &entry;
	entry.length = 3569U;
	assert(swapz_round031_mm_bio_create(&entry, slot, &tree, 5U) == NULL);
	entry.length = 0U;
	assert(swapz_round031_mm_bio_create(&entry, slot, &tree, 5U) == NULL);
	entry.length = (unsigned int)compressed_length;
	strcpy(pool.tfm_name, "zstd");
	assert(swapz_round031_mm_bio_create(&entry, slot, &tree, 5U) == NULL);
	strcpy(pool.tfm_name, "lz4");
	inject_malloc_failure = true;
	assert(swapz_round031_mm_bio_create(&entry, slot, &tree, 5U) == NULL);
	inject_malloc_failure = false;
	inject_epoch_during_copy = true;
	assert(swapz_round031_mm_bio_create(&entry, slot, &tree, 5U) == NULL);
	inject_epoch_during_copy = false;
	--active_epoch;
	memset(entry.swapz_round028_store_sha256, 0, 32U);
	assert(swapz_round031_mm_bio_create(&entry, slot, &tree, 5U) == NULL);
	assert(allocations == 0U && pool_begins == pool_ends);
	assert(pool_begins == source_copy_count);
	assert(free_count == pool_ends);
	printf("ROUND031_REAL_MM_ZSMALLOC_TO_REFCOUNTED_BIO_SOURCE_ONLY_PASS\n");
	return 0;
}
