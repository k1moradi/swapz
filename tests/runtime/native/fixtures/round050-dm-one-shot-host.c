/*
 * Round050: execute the ACTUAL default-off production C negative observer.
 * This host supplies only scalar stand-ins for real Linux types. It cannot
 * create a genuine original counted swap slot, DM table lease or lower IO.
 */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint64_t sector_t;
typedef uint64_t swapz_u64;
typedef uint32_t swapz_u32;

#define __used __attribute__((used))
#define READ_ONCE(value) (value)
#define smp_load_acquire(pointer) (*(pointer))
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_SECTORS 8U
#define SWAPZ_MAX_COMPRESSED 3568U
#define REQ_OP_READ 0U
#define REQ_OP_WRITE 1U
#define REQ_SWAP 16U

struct dm_target {
	void *private;
	sector_t begin;
	sector_t len;
};
struct swapz_dm {
	struct dm_target *target;
	bool accepting;
	bool failed;
	swapz_u32 logical_pages;
	swapz_u32 physical_blocks;
	swapz_u32 *maps;
	struct {
		swapz_u32 *maps;
	} authority;
};
struct bio {
	unsigned int bi_opf;
	struct {
		sector_t bi_sector;
		unsigned int bi_size;
	} bi_iter;
};

static unsigned int bio_op(const struct bio *bio)
{
	return bio->bi_opf & 7U;
}

static sector_t bio_sectors(const struct bio *bio)
{
	return (sector_t)bio->bi_iter.bi_size / 512U;
}

/* ROUND050_INJECT_REAL_PRODUCT_NEGATIVE_HELPER */

static unsigned int round050_observation_count;
static int round050_observation_status;

static int round050_count_negative_observation(
		const struct dm_target *target, const struct swapz_dm *ctx,
		const struct bio *upper_bio,
		const struct swapz_round050_dm_pending_report *submitted,
		const struct swapz_round050_dm_pending_report *observed)
{
	++round050_observation_count;
	return swapz_round050_dm_one_shot_refuse(
		target, ctx, upper_bio, submitted, observed);
}

static void round050_execute_real_map_callsite(
		struct dm_target *ti, struct swapz_dm *ctx, struct bio *bio)
{
	sector_t count = bio_sectors(bio);

#define swapz_round050_dm_one_shot_refuse(...) \
	(round050_observation_status = \
	 round050_count_negative_observation(__VA_ARGS__))
/* ROUND050_INJECT_REAL_PRODUCT_MAP_CALLSITE */
#undef swapz_round050_dm_one_shot_refuse
}

static void round050_run_real_negative(
		unsigned int extent_blocks, unsigned int fault)
{
	swapz_u32 maps[32] = {0};
	struct swapz_dm context = {
		.accepting = true,
		.logical_pages = 32U,
		.physical_blocks = 512U,
		.maps = maps,
		.authority = { .maps = maps },
	};
	struct dm_target target = {
		.private = &context,
		.begin = 64U,
		.len = 32U * SWAPZ_SECTORS,
	};
	struct bio upper_bio = {
		.bi_opf = REQ_OP_WRITE | REQ_SWAP,
		.bi_iter = { .bi_sector = SWAPZ_SECTORS,
			     .bi_size = SWAPZ_BLOCK_BYTES },
	};
	struct swapz_round050_dm_pending_report submitted = {
		.target_identity = (unsigned long)&target,
		.context_identity = (unsigned long)&context,
		.upper_bio_identity = (unsigned long)&upper_bio,
		.target_relative_sector = SWAPZ_SECTORS,
		.original_bdev_cookie = 0xA51U,
		.original_physical_sector = 0x800U,
		.table_epoch = 11U,
		.callback_ticket = 22U,
		.map_generation = 33U,
		.gc_epoch = 44U,
		.extent_start_block = 16U,
		.extent_blocks = extent_blocks,
		.compressed_length = 2048U,
		.lower_write_bytes = extent_blocks * SWAPZ_BLOCK_BYTES,
		.lower_completion_count = 1U,
		.map_publications = 1U,
		.upper_ack_attempts = 0U,
		.compressed_crc_valid = true,
		.lower_write_durable = true,
	};
	struct swapz_round050_dm_pending_report observed = submitted;
	struct swapz_dm original_context;
	struct dm_target original_target;
	struct bio original_upper_bio;
	struct swapz_round050_dm_pending_report original_submitted;
	struct swapz_round050_dm_pending_report original_observed;
	const struct swapz_round050_dm_pending_report *submitted_parameter =
		&submitted;
	const struct swapz_round050_dm_pending_report *observed_parameter =
		&observed;
	int expected = -EOPNOTSUPP;
	int result;
	unsigned int expected_observations;

	context.target = &target;

	/*
	 * The validated baseline has synthetic matching metadata and ZERO
	 * actual owner references: it MUST remain -EOPNOTSUPP even with fake
	 * source/table flags, durable lower/one-map/zero-ACK reports.
	 */
	switch (fault) {
	case 0U: break;
	case 1U: submitted.source_counted_owner_reported = true; break;
	case 2U: submitted.current_table_lease_reported = true; break;
	case 3U:
		submitted.source_counted_owner_reported = true;
		submitted.current_table_lease_reported = true;
		observed = submitted;
		break;
	case 4U: submitted_parameter = NULL; break;
	case 5U: observed_parameter = NULL; break;
	case 6U: submitted.teardown_started = true; expected = -ESHUTDOWN; break;
	case 7U: observed.teardown_started = true; expected = -ESHUTDOWN; break;
	case 8U: context.accepting = false; expected = -ESHUTDOWN; break;
	case 9U: context.failed = true; expected = -ESHUTDOWN; break;
	case 10U: target.private = NULL; expected = -ESTALE; break;
	case 11U: context.target = NULL; expected = -ESTALE; break;
	case 12U: context.authority.maps = NULL; expected = -ESTALE; break;
	case 13U: context.maps = NULL; expected = -ESTALE; break;
	case 14U: upper_bio.bi_opf = REQ_OP_READ | REQ_SWAP;
		expected = -ERANGE; break;
	case 15U: upper_bio.bi_opf = REQ_OP_WRITE;
		expected = -ERANGE; break;
	case 16U: upper_bio.bi_iter.bi_size = SWAPZ_BLOCK_BYTES - 512U;
		expected = -ERANGE; break;
	case 17U: upper_bio.bi_iter.bi_size = SWAPZ_BLOCK_BYTES + 512U;
		expected = -ERANGE; break;
	case 18U: upper_bio.bi_iter.bi_sector = 1U;
		expected = -ERANGE; break;
	case 19U: upper_bio.bi_iter.bi_sector = target.len;
		expected = -ERANGE; break;
	case 20U: target.len = 31U * SWAPZ_SECTORS;
		expected = -ESTALE; break;
	case 21U: submitted.target_identity++;
		expected = -ESTALE; break;
	case 22U: submitted.context_identity++;
		expected = -ESTALE; break;
	case 23U: submitted.upper_bio_identity++;
		expected = -ESTALE; break;
	case 24U: observed.target_identity++;
		expected = -ESTALE; break;
	case 25U: observed.target_relative_sector++;
		expected = -ESTALE; break;
	case 26U: observed.table_epoch++;
		expected = -ESTALE; break;
	case 27U: observed.callback_ticket++;
		expected = -ESTALE; break;
	case 28U: observed.map_generation++;
		expected = -ESTALE; break;
	case 29U: observed.gc_epoch++;
		expected = -ESTALE; break;
	case 30U: observed.extent_start_block++;
		expected = -ESTALE; break;
	case 31U: observed.extent_blocks++;
		expected = -ESTALE; break;
	case 32U: observed.original_bdev_cookie++;
		expected = -ESTALE; break;
	case 33U: observed.original_physical_sector++;
		expected = -ESTALE; break;
	case 34U: submitted.extent_blocks = 3U;
		observed.extent_blocks = 3U;
		expected = -ERANGE; break;
	case 35U: submitted.compressed_length = 0U;
		expected = -ERANGE; break;
	case 36U: submitted.compressed_length = SWAPZ_MAX_COMPRESSED + 1U;
		expected = -ERANGE; break;
	case 37U: submitted.extent_start_block = context.physical_blocks;
		observed.extent_start_block = context.physical_blocks;
		expected = -ERANGE; break;
	case 38U: submitted.compressed_crc_valid = false;
		expected = -EBADMSG; break;
	case 39U: submitted.upper_ack_attempts = 1U;
		expected = -EALREADY; break;
	case 40U: observed.upper_ack_attempts = 1U;
		expected = -EALREADY; break;
	case 41U: submitted.lower_completion_count = 2U;
		expected = -EALREADY; break;
	case 42U: observed.lower_completion_count = 2U;
		expected = -EALREADY; break;
	case 43U: submitted.lower_write_durable = false;
		expected = -EAGAIN; break;
	case 44U: observed.lower_write_durable = false;
		expected = -EAGAIN; break;
	case 45U: submitted.lower_write_bytes--;
		expected = -EAGAIN; break;
	case 46U: observed.lower_write_bytes--;
		expected = -EAGAIN; break;
	case 47U: submitted.lower_completion_count = 0U;
		expected = -EAGAIN; break;
	case 48U: submitted.lower_error = -EIO;
		expected = -EAGAIN; break;
	case 49U: submitted.map_publications = 0U;
		expected = -EUCLEAN; break;
	case 50U: observed.map_publications = 2U;
		expected = -EUCLEAN; break;
	case 51U:
		/* Equal *numeric* source absolute LBA is still no credential. */
		submitted.original_physical_sector =
			submitted.target_relative_sector;
		observed.original_physical_sector =
			submitted.original_physical_sector;
		break;
	case 52U:
		/* Fabricated exact table/slot/GC/ACK state is still a refusal. */
		submitted.source_counted_owner_reported = true;
		submitted.current_table_lease_reported = true;
		observed = submitted;
		break;
	default: assert(0 && "bad Round050 hostile fault selector");
	}

	original_context = context;
	original_target = target;
	original_upper_bio = upper_bio;
	original_submitted = submitted;
	original_observed = observed;
	result = swapz_round050_dm_one_shot_refuse(
		&target, &context, &upper_bio,
		submitted_parameter, observed_parameter);
	if (result != expected) {
		fprintf(stderr,
			"FIRST Round050 actual product negative C failure: "
			"extent_blocks=%u fault=%u returned=%d expected=%d\n",
			extent_blocks, fault, result, expected);
		assert(result == expected);
	}
	assert(result < 0);
	assert(!memcmp(&original_context, &context, sizeof(context)));
	assert(!memcmp(&original_target, &target, sizeof(target)));
	assert(!memcmp(&original_upper_bio, &upper_bio, sizeof(upper_bio)));
	assert(!memcmp(&original_submitted, &submitted, sizeof(submitted)));
	assert(!memcmp(&original_observed, &observed, sizeof(observed)));

	round050_observation_count = 0U;
	round050_observation_status = 0;
	expected_observations =
		bio_op(&upper_bio) == REQ_OP_WRITE &&
		bio_sectors(&upper_bio) == SWAPZ_SECTORS &&
		upper_bio.bi_iter.bi_size == SWAPZ_BLOCK_BYTES ? 1U : 0U;
	round050_execute_real_map_callsite(&target, &context, &upper_bio);
	assert(round050_observation_count == expected_observations);
	if (expected_observations)
		assert(round050_observation_status == -EOPNOTSUPP);
	assert(!memcmp(&original_context, &context, sizeof(context)));
	assert(!memcmp(&original_upper_bio, &upper_bio, sizeof(upper_bio)));
}

int main(void)
{
	unsigned int extent_blocks;
	unsigned int fault;
	unsigned int negative_cases = 0U;

	/* All cases are negative; all three bounded 4/8/16KiB extents. */
	for (extent_blocks = 1U; extent_blocks <= 4U; extent_blocks *= 2U) {
		for (fault = 0U; fault < 53U; ++fault) {
			round050_run_real_negative(extent_blocks, fault);
			++negative_cases;
		}
	}
	assert(negative_cases == 159U);
	puts("ROUND050_REAL_PRODUCT_ONE_SHOT_159_NEGATIVE_C_CASES_PASS");
	puts("ROUND050_SOURCE_TO_CURRENT_DM_AUTHENTICATED=0");
	return 0;
}
