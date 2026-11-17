/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Round025 — compile/execute actual pinned mm/zswap.c CI-only SHA probe.
 * This host builds the EXACT extracted source but supplies fake kernel
 * types/functions. It proves byte hashing and negative ownership cleanup,
 * NOT an allocator epoch, real eviction, a loaded kernel or physical IO.
 */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <openssl/sha.h>

#define PAGE_SIZE 4096U
#define GFP_KERNEL 0
#define SHA256_DIGEST_SIZE SHA256_DIGEST_LENGTH
typedef uint8_t u8;
typedef uint64_t u64;
typedef struct { unsigned long val; } swp_entry_t;
struct folio { bool locked; bool swapcache; long pages; };
struct zswap_entry {
	swp_entry_t swpentry;
	unsigned int length;
	unsigned long handle;
	u8 pool_idx;
};
struct zswap_pool { u8 idx; char tfm_name[16]; };
struct xarray { struct zswap_entry *entry; };
static struct xarray stored_tree;
static struct zswap_pool *resolved_pool;
static u8 true_original_page[PAGE_SIZE];
static unsigned int sha256_calls;
static unsigned int allocations;
static unsigned int releases;
static unsigned int scrubbed;
static unsigned int maps;
static unsigned int unmaps;
static bool refuse_allocation;
static size_t allocated_bytes;

static bool folio_test_locked(const struct folio *folio)
{
	return folio->locked;
}
static bool folio_test_swapcache(const struct folio *folio)
{
	return folio->swapcache;
}
static long folio_nr_pages(const struct folio *folio)
{
	return folio->pages;
}
static struct xarray *swap_zswap_tree(swp_entry_t slot)
{
	(void)slot;
	return &stored_tree;
}
static unsigned long swp_offset(swp_entry_t slot)
{
	return slot.val;
}
static struct zswap_entry *xa_load(const struct xarray *tree,
				  unsigned long offset)
{
	(void)offset;
	return tree->entry;
}
static struct zswap_pool *zswap_entry_pool(struct zswap_entry *entry)
{
	(void)entry;
	return resolved_pool;
}
static void *kzalloc(size_t bytes, int flags)
{
	(void)flags;
	if (refuse_allocation)
		return NULL;
	void *allocation = calloc(1U, bytes);
	if (allocation) {
		allocations++;
		allocated_bytes = bytes;
	}
	return allocation;
}
static void memzero_explicit(void *memory, size_t bytes)
{
	assert(memory != NULL);
	assert(bytes == allocated_bytes);
	volatile u8 *pointer = memory;
	for (size_t index = 0; index < bytes; ++index)
		pointer[index] = 0;
	scrubbed++;
}
static void kfree(const void *memory)
{
	assert(memory != NULL);
	const u8 *bytes = memory;
	for (size_t index = 0; index < allocated_bytes; ++index)
		assert(bytes[index] == 0);
	releases++;
	free((void *)memory);
}
static const u8 *kmap_local_folio(const struct folio *folio, size_t offset)
{
	assert(folio && folio->locked && folio->swapcache);
	assert(offset == 0U);
	maps++;
	return true_original_page;
}
static void kunmap_local(const void *mapped)
{
	assert(mapped == true_original_page);
	unmaps++;
}
static void sha256(const u8 *plaintext, size_t bytes, u8 digest[SHA256_DIGEST_SIZE])
{
	static const u8 independent_expected_sha256[SHA256_DIGEST_SIZE] = {
		0xd6, 0x7c, 0x65, 0x6e, 0x01, 0x75, 0x66, 0x50,
		0xd7, 0x77, 0x17, 0xb0, 0x83, 0x99, 0x85, 0xa0,
		0x56, 0xec, 0x28, 0xff, 0xe1, 0x74, 0x60, 0x1d,
		0x69, 0x0f, 0xc4, 0x07, 0xa2, 0xce, 0xff, 0xca,
	};
	assert(plaintext == true_original_page);
	assert(bytes == PAGE_SIZE);
	assert(SHA256(plaintext, bytes, digest) == digest);
	assert(memcmp(digest, independent_expected_sha256, SHA256_DIGEST_SIZE) == 0);
	sha256_calls++;
}

/* ROUND025_EXACT_PINNED_STORE_PROBE */

int main(void)
{
	struct zswap_pool lz4_pool = {.idx = 7, .tfm_name = "lz4"};
	struct zswap_pool zstd_pool = {.idx = 7, .tfm_name = "zstd"};
	struct zswap_pool wrong_pool = {.idx = 8, .tfm_name = "lz4"};
	struct zswap_entry entry = {
		.swpentry = {.val = 37}, .length = 256,
		.handle = 51, .pool_idx = 7,
	};
	struct zswap_entry recycled_entry = entry;
	struct folio folio = {.locked = true, .swapcache = true, .pages = 1};
	swp_entry_t slot = {.val = 37};

	for (size_t index = 0; index < PAGE_SIZE; ++index)
		true_original_page[index] = (u8)(index % 251U);
	stored_tree.entry = &entry;
	resolved_pool = &lz4_pool;
	/* Even current actual original digest cannot supply the missing epoch. */
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 0, &entry, slot) == -EOPNOTSUPP);
	assert(sha256_calls == 1 && allocations == 1 && releases == 1);
	assert(scrubbed == 1 && maps == 1 && unmaps == 1);

	/* Reject forged page source, out-of-range page index, NULL and ABA. */
	assert(zswap_swapz_round025_store_digest_probe(
		NULL, 0, &entry, slot) == -EINVAL);
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 0, NULL, slot) == -EINVAL);
	folio.locked = false;
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 0, &entry, slot) == -EINVAL);
	folio.locked = true;
	folio.swapcache = false;
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 0, &entry, slot) == -EINVAL);
	folio.swapcache = true;
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, -1, &entry, slot) == -EINVAL);
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 1, &entry, slot) == -EINVAL);

	stored_tree.entry = &recycled_entry;
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 0, &entry, slot) == -ESTALE);
	stored_tree.entry = &entry;
	entry.swpentry.val = 38;
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 0, &entry, slot) == -ESTALE);
	entry.swpentry.val = 37;
	entry.handle = 0;
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 0, &entry, slot) == -EMSGSIZE);
	entry.handle = 51;
	entry.length = 0;
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 0, &entry, slot) == -EMSGSIZE);
	entry.length = 3569;
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 0, &entry, slot) == -EMSGSIZE);
	entry.length = 256;

	resolved_pool = &wrong_pool;
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 0, &entry, slot) == -ESTALE);
	resolved_pool = &zstd_pool;
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 0, &entry, slot) == -EOPNOTSUPP);
	resolved_pool = &lz4_pool;
	refuse_allocation = true;
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 0, &entry, slot) == -ENOMEM);
	refuse_allocation = false;
	/* Repeated source-only snapshots always scrub, never publish. */
	assert(zswap_swapz_round025_store_digest_probe(
		&folio, 0, &entry, slot) == -EOPNOTSUPP);
	assert(sha256_calls == 2 && allocations == 2 && releases == 2);
	assert(scrubbed == 2 && maps == 2 && unmaps == 2);
	return 0;
}
