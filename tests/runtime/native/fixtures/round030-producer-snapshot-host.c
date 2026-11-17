/* SPDX-License-Identifier: GPL-2.0-only */
/* Round030 genuine pinned zswap writeback snapshot C host ABI shims.
 * The function inserted below is the actual staged original mm/zswap.c
 * helper. All pool, xarray, zsmalloc and allocator boundaries are mocked.
 * This is SOURCE-ONLY; the real original compiler is checked separately.
 */
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <lz4.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE 1
#define SWAPZ_ROUND028_SLOT_EPOCH_SOURCE 1
#define __used __attribute__((used))
#define noinline __attribute__((noinline))
#define GFP_KERNEL 0
#define SHA256_DIGEST_SIZE 32
#define struct_size(pointer, field, count) \
	(sizeof(*(pointer)) + (size_t)(count) * sizeof((pointer)->field[0]))
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef unsigned long pgoff_t;
typedef struct { unsigned long val; } swp_entry_t;
struct zs_pool { unsigned int id; };
struct zswap_pool { struct zs_pool *zs_pool; char tfm_name[32]; };
struct zswap_entry {
	swp_entry_t swpentry;
	unsigned int length;
	unsigned long handle;
	u64 swapz_round028_allocation_epoch;
	u64 swapz_round028_stored_entry_identity;
	u8 swapz_round028_store_sha256[32];
	bool swapz_round028_store_bound;
	struct zswap_pool *pool;
};
struct xarray { struct zswap_entry *stored; };
struct scatterlist { const u8 *bytes; unsigned int length; };

static u64 active_epoch = 17;
static bool change_epoch_during_copy;
static bool fail_allocation;
static unsigned int active_allocations;
static unsigned int read_begin_count;
static unsigned int read_end_count;
static unsigned int scrub_count;

static struct zswap_entry *xa_load(const struct xarray *tree, pgoff_t offset)
{
	assert(offset == 7U);
	return tree->stored;
}
static struct zswap_pool *zswap_entry_pool(struct zswap_entry *entry)
{
	return entry->pool;
}
static u64 swapz_round028_slot_epoch(swp_entry_t slot)
{
	assert(slot.val == 7U);
	return active_epoch;
}
static void *kmalloc(size_t allocation_bytes, int flags)
{
	void *result;
	(void)flags;
	if (fail_allocation)
		return NULL;
	result = malloc(allocation_bytes);
	if (result)
		++active_allocations;
	return result;
}
static void kfree_sensitive(void *allocation)
{
	if (allocation) {
		++scrub_count;
		assert(active_allocations != 0U);
		--active_allocations;
		free(allocation);
	}
}
static void zs_obj_read_sg_begin(struct zs_pool *pool, unsigned long handle,
				struct scatterlist *list, unsigned int length)
{
	assert(pool != NULL && handle != 0U);
	++read_begin_count;
	list[0].bytes = (const u8 *)(uintptr_t)handle;
	list[0].length = length;
}
static void memcpy_from_sglist(void *dst, const struct scatterlist *list,
			       unsigned int offset, unsigned int count)
{
	assert(offset == 0U && count == list[0].length);
	memcpy(dst, list[0].bytes, count);
	if (change_epoch_during_copy)
		active_epoch = 18;
}
static void zs_obj_read_sg_end(struct zs_pool *pool, unsigned long handle)
{
	assert(pool != NULL && handle != 0U);
	++read_end_count;
}
static u32 crc32c(u32 checksum, const u8 *source, unsigned int count)
{
	for (unsigned int index = 0; index < count; ++index) {
		checksum ^= (u32)source[index];
		for (unsigned int bit = 0; bit < 8; ++bit)
			checksum = (checksum >> 1) ^
				   ((checksum & 1U) ? 0x82f63b78U : 0U);
	}
	return checksum;
}

/* ROUND030_EXACT_STAGED_EVICTION_C */

int main(void)
{
	u8 original[4096] = { 0 };
	u8 compressed[3568] = { 0 };
	struct zs_pool zsmalloc_pool = { .id = 1 };
	struct zswap_pool stored_pool = {
		.zs_pool = &zsmalloc_pool, .tfm_name = "lz4",
	};
	struct zswap_entry stored_entry = {
		.swpentry = { .val = 7U },
		.swapz_round028_allocation_epoch = 17,
		.swapz_round028_stored_entry_identity = 19,
		.swapz_round028_store_sha256 = { 0xad },
		.swapz_round028_store_bound = true,
		.pool = &stored_pool,
	};
	struct xarray tree = { .stored = &stored_entry };
	const swp_entry_t slot = { .val = 7U };
	unsigned int previous_reads;
	int compressed_length;

	for (unsigned int index = 0; index < sizeof(original); ++index)
		original[index] = (u8)(index % 5U);
	compressed_length = LZ4_compress_default(
		(const char *)original, (char *)compressed,
		(int)sizeof(original), (int)sizeof(compressed));
	assert(compressed_length > 0 && compressed_length <= 3568);
	stored_entry.length = (unsigned int)compressed_length;
	stored_entry.handle = (unsigned long)(uintptr_t)compressed;
	assert(~crc32c(~0U, (const u8 *)"123456789", 9U) == 0xe3069283U);

	/* Positive: genuine zsmalloc SG already-compressed LZ4 bytes. */
	assert(swapz_round030_snapshot_stored_lz4(
		&stored_entry, slot, &tree, 7U) == 0);
	assert(!stored_entry.swapz_round028_store_bound);
	assert(active_allocations == 0U && read_begin_count == read_end_count);
	assert(read_begin_count == 1U && scrub_count == 1U);
	assert(swapz_round030_snapshot_stored_lz4(
		&stored_entry, slot, &tree, 7U) == -ESTALE);

	/* Fault paths must never borrow, leak, or expose compressed bytes. */
	stored_entry.swapz_round028_store_bound = true;
	previous_reads = read_begin_count;
	strcpy(stored_pool.tfm_name, "zstd");
	assert(swapz_round030_snapshot_stored_lz4(
		&stored_entry, slot, &tree, 7U) == -EOPNOTSUPP);
	strcpy(stored_pool.tfm_name, "lz4");
	stored_entry.length = 3569U;
	assert(swapz_round030_snapshot_stored_lz4(
		&stored_entry, slot, &tree, 7U) == -EMSGSIZE);
	stored_entry.length = 0U;
	assert(swapz_round030_snapshot_stored_lz4(
		&stored_entry, slot, &tree, 7U) == -EMSGSIZE);
	stored_entry.length = (unsigned int)compressed_length;
	active_epoch = 18U;
	assert(swapz_round030_snapshot_stored_lz4(
		&stored_entry, slot, &tree, 7U) == -ESTALE);
	active_epoch = 17U;
	stored_entry.swapz_round028_stored_entry_identity = 0;
	assert(swapz_round030_snapshot_stored_lz4(
		&stored_entry, slot, &tree, 7U) == -ESTALE);
	stored_entry.swapz_round028_stored_entry_identity = 19;
	stored_entry.swapz_round028_store_sha256[0] = 0;
	assert(swapz_round030_snapshot_stored_lz4(
		&stored_entry, slot, &tree, 7U) == -ENODATA);
	stored_entry.swapz_round028_store_sha256[0] = 0xad;
	tree.stored = NULL;
	assert(swapz_round030_snapshot_stored_lz4(
		&stored_entry, slot, &tree, 7U) == -ESTALE);
	tree.stored = &stored_entry;
	fail_allocation = true;
	assert(swapz_round030_snapshot_stored_lz4(
		&stored_entry, slot, &tree, 7U) == -ENOMEM);
	fail_allocation = false;
	change_epoch_during_copy = true;
	assert(swapz_round030_snapshot_stored_lz4(
		&stored_entry, slot, &tree, 7U) == -ESTALE);
	change_epoch_during_copy = false;
	active_epoch = 17;
	assert(active_allocations == 0U);
	assert(read_begin_count == read_end_count);
	assert(read_begin_count == previous_reads + 1U);
	/* No live BIO, no actual DM mapping or synthetic PASS signal. */
	puts("ROUND030_ORIGINAL_EVICTION_OWNED_LZ4_SOURCE_ONLY_PASS");
	return 0;
}
