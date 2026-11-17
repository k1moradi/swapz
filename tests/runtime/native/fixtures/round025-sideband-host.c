/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Round025 host-only negative fixture. The driver prepends exact CI_HELPERS
 * from the committed pinned-source stager; all host services below are mocks.
 * Real kernel lifecycle must be separately compiled via pinned Kbuild/KUnit.
 */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef struct { atomic_uint count; } refcount_t;
struct swapz_ci_owned_payload;
struct bio { struct swapz_ci_owned_payload *bi_swapz_ci_sideband; };
#define SWAPZ_ROUND025_SIDEBAND_CI_ONLY 1
#define IS_ENABLED(variable) 0
#define __maybe_unused __attribute__((unused))
static unsigned int freed_allocations;
static void refcount_set(refcount_t *reference, unsigned int count)
{
	atomic_init(&reference->count, count);
}
static unsigned int refcount_read(const refcount_t *reference)
{
	return atomic_load_explicit(&reference->count, memory_order_relaxed);
}
static bool refcount_inc_not_zero(refcount_t *reference)
{
	unsigned int count = atomic_load_explicit(&reference->count,
						  memory_order_acquire);
	while (count) {
		if (count == UINT32_MAX)
			return false;
		if (atomic_compare_exchange_weak_explicit(&reference->count,
			&count, count + 1U, memory_order_acq_rel,
			memory_order_acquire))
			return true;
	}
	return false;
}
static bool refcount_dec_and_test(refcount_t *reference)
{
	const unsigned int old = atomic_fetch_sub_explicit(
		&reference->count, 1U, memory_order_acq_rel);
	assert(old > 0U);
	return old == 1U;
}
static void kfree_sensitive(void *allocation)
{
	if (allocation) {
		++freed_allocations;
		free(allocation);
	}
}
static u32 crc32c(u32 value, const void *buffer, unsigned int size)
{
	const u8 *bytes = buffer;
	for (unsigned int index = 0; index < size; ++index) {
		value ^= bytes[index];
		for (unsigned int bit = 0; bit < 8; ++bit)
			value = (value >> 1) ^
				((value & 1U) ? 0x82f63b78U : 0U);
	}
	return value;
}

/* ROUND025_EXACT_CI_HELPERS */

/* These are deliberately NOT Linux bio_clone/split/reuse entry points.
 * Source-authentic helper ownership is exercised independently of full
 * Kbuild testing that must cover the real pinned source hooks. */
static struct swapz_ci_owned_payload *fixture_owner(unsigned int length)
{
	struct swapz_ci_owned_payload *owner;
	assert(length >= 1 && length <= 3568);
	owner = calloc(1, sizeof(*owner) + length);
	assert(owner);
	refcount_set(&owner->references, 1U);
	owner->slot_epoch = 17U;
	owner->source_identity = 29U;
	owner->codec = 1U;
	owner->representation_version = 1U;
	owner->decoded_length = 4096U;
	owner->compressed_length = (u16)length;
	owner->original_sha256[0] = 0xb2U;
	for (unsigned int index = 0; index < length; ++index)
		owner->compressed_bytes[index] = (u8)(index & 0xffU);
	owner->compressed_crc32c =
		~crc32c(~0U, owner->compressed_bytes, length);
	return owner;
}
static int fixture_clone(const struct bio *parent, struct bio *clone)
{
	struct swapz_ci_owned_payload *owner = parent->bi_swapz_ci_sideband;
	if (owner && !swapz_ci_owned_valid(owner))
		return -EOPNOTSUPP;
	clone->bi_swapz_ci_sideband = swapz_ci_owned_get(owner);
	return owner && !clone->bi_swapz_ci_sideband ? -ESTALE : 0;
}
static void denied(int result)
{
	assert(result < 0);
}

int main(void)
{
	const u8 vector[] = { '1', '2', '3', '4', '5', '6', '7', '8', '9' };
	assert(~crc32c(~0U, vector, 9U) == 0xe3069283U);
	assert(~crc32c(0U, vector, 9U) != 0xe3069283U);
	for (unsigned int round_index = 0; round_index < 32U; ++round_index) {
		struct bio original = { 0 }, clone = { 0 }, split = { 0 };
		struct swapz_ci_owned_payload *owner = fixture_owner(3568);
		original.bi_swapz_ci_sideband = owner;
		assert(swapz_ci_owned_valid(owner));
		assert(fixture_clone(&original, &clone) == 0);
		assert(fixture_clone(&clone, &split) == 0);
		assert(refcount_read(&owner->references) == 3U);
		assert(clone.bi_swapz_ci_sideband == owner);
		assert(split.bi_swapz_ci_sideband == owner);
		assert(!swapz_ci_bio_merge_allowed(&original, &clone));
		assert(swapz_ci_bio_merge_allowed(&(struct bio){0},
						 &(struct bio){0}));
		denied(swapz_ci_live_compressed_admit(&clone, 17U));
		swapz_ci_bio_detach(&original);
		assert(refcount_read(&owner->references) == 2U);
		swapz_ci_bio_detach(&clone);
		assert(refcount_read(&owner->references) == 1U);
		swapz_ci_bio_detach(&split);
		swapz_ci_bio_detach(&split);
	}
	assert(freed_allocations == 32U);
	for (unsigned int invalid = 0; invalid < 8U; ++invalid) {
		struct bio original = { 0 }, attempted = { 0 };
		struct swapz_ci_owned_payload *owner = fixture_owner(8U);
		original.bi_swapz_ci_sideband = owner;
		switch (invalid) {
		case 0: owner->slot_epoch = 0; break;
		case 1: owner->source_identity = 0; break;
		case 2: owner->codec = 2; break;
		case 3: owner->representation_version = 2; break;
		case 4: owner->compressed_length = 0; break;
		case 5: owner->compressed_length = 3569; break;
		case 6: owner->decoded_length = 4095; break;
		default: owner->compressed_crc32c ^= 1U; break;
		}
		/* Reject before dereferencing forged length > allocation. */
		assert(!swapz_ci_owned_valid(owner));
		denied(fixture_clone(&original, &attempted));
		assert(attempted.bi_swapz_ci_sideband == NULL);
		swapz_ci_bio_detach(&original);
	}
	assert(freed_allocations == 40U);
	puts("ROUND025_SIDE_BAND_HOST_SOURCE_ONLY_PASS");
	puts("LIVE_COMPRESSED=DISABLED LOADED_4096=NOT_RUN PHYSICAL=NOT_RUN");
	return 0;
}
