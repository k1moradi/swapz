/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Round026: the EXACT pinned mm/swapfile.c opt-in C probe is injected below.
 * Host swap-table state is synthetic; real allocator generation is absent.
 * A reused slot with identical table bits MUST NOT become "authenticated".
 */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SWAPFILE_CLUSTER 256U
#define SWAPZ_ROUND026_SLOT_EPOCH_PROBE 1

typedef struct { unsigned long val; } swp_entry_t;
struct test_spinlock { bool held; };
struct swap_cluster_info {
	struct test_spinlock lock;
	bool allocated_table;
	unsigned long table_bits;
};
struct swap_info_struct {
	struct swap_cluster_info cluster;
	bool pinned;
};
static struct swap_info_struct real_swap;
static struct swap_info_struct bad_swap;
static unsigned int device_gets;
static unsigned int device_puts;
static unsigned int cluster_locks;
static unsigned int cluster_unlocks;
static unsigned int table_reads;
static bool failed_get;

#define IS_ERR(pointer) ((pointer) == &bad_swap)
#define PTR_ERR(pointer) (-EIO)
#define lockdep_assert_held(lock_pointer) assert((lock_pointer)->held)

static struct swap_info_struct *get_swap_device(swp_entry_t slot)
{
	if (!slot.val)
		return NULL;
	if (failed_get)
		return &bad_swap;
	assert(!real_swap.pinned);
	real_swap.pinned = true;
	++device_gets;
	return &real_swap;
}
static unsigned long swp_offset(swp_entry_t slot)
{
	return slot.val;
}
static struct swap_cluster_info *swap_cluster_lock(
		struct swap_info_struct *swap_info, unsigned long offset)
{
	assert(swap_info == &real_swap);
	assert(swap_info->pinned);
	assert(offset != 0);
	assert(!swap_info->cluster.lock.held);
	swap_info->cluster.lock.held = true;
	++cluster_locks;
	return &swap_info->cluster;
}
static bool cluster_table_is_alloced(const struct swap_cluster_info *cluster)
{
	assert(cluster->lock.held);
	return cluster->allocated_table;
}
static unsigned long __swap_table_get(
		const struct swap_cluster_info *cluster, unsigned long offset)
{
	assert(cluster->lock.held);
	assert(offset < SWAPFILE_CLUSTER);
	++table_reads;
	return cluster->table_bits;
}
static bool swp_tb_is_null(unsigned long state)
{
	return state == 0;
}
static bool swp_tb_is_bad(unsigned long state)
{
	return state == 1;
}
static void swap_cluster_unlock(struct swap_cluster_info *cluster)
{
	assert(cluster->lock.held);
	cluster->lock.held = false;
	++cluster_unlocks;
}
static void put_swap_device(struct swap_info_struct *swap_info)
{
	assert(swap_info == &real_swap && swap_info->pinned);
	assert(!swap_info->cluster.lock.held);
	swap_info->pinned = false;
	++device_puts;
}

/* ROUND026_PINNED_SWAPFILE_SOURCE */

static void verify_no_owner_leak(void)
{
	assert(device_gets == device_puts);
	assert(cluster_locks == cluster_unlocks);
	assert(!real_swap.pinned);
	assert(!real_swap.cluster.lock.held);
}
int main(void)
{
	swp_entry_t same_slot = { .val = 37 };
	unsigned int first_observation_reads;
	real_swap.cluster.allocated_table = true;
	real_swap.cluster.table_bits = 2; /* original allocated folio */
	assert(swapz_round026_allocator_epoch_probe(same_slot) == -EOPNOTSUPP);
	verify_no_owner_leak();
	first_observation_reads = table_reads;
	assert(first_observation_reads == 1);

	/* Original __swap_cluster_free_entries() writes NULL under lock. */
	real_swap.cluster.table_bits = 0;
	assert(swapz_round026_allocator_epoch_probe(same_slot) == -ESTALE);
	verify_no_owner_leak();
	/* Allocator now reissues same slot with IDENTICAL original table bits. */
	real_swap.cluster.table_bits = 2;
	assert(swapz_round026_allocator_epoch_probe(same_slot) == -EOPNOTSUPP);
	assert(table_reads == first_observation_reads + 2);
	verify_no_owner_leak();
	/* Current original table carries no epoch to distinguish the two. */
	real_swap.cluster.table_bits = 1;
	assert(swapz_round026_allocator_epoch_probe(same_slot) == -ESTALE);
	verify_no_owner_leak();

	real_swap.cluster.allocated_table = false;
	assert(swapz_round026_allocator_epoch_probe(same_slot) == -ESTALE);
	real_swap.cluster.allocated_table = true;
	verify_no_owner_leak();
	assert(swapz_round026_allocator_epoch_probe((swp_entry_t){0}) == -ENOENT);
	failed_get = true;
	assert(swapz_round026_allocator_epoch_probe(same_slot) == -EIO);
	failed_get = false;
	verify_no_owner_leak();

	/* A hibernation count or another non-null bit pattern is no proof. */
	real_swap.cluster.table_bits = 3;
	for (unsigned int attempt = 0; attempt < 64; ++attempt) {
		assert(swapz_round026_allocator_epoch_probe(same_slot) == -EOPNOTSUPP);
		verify_no_owner_leak();
	}
	return 0;
}
