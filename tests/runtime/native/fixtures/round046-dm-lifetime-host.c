/*
 * Round046 host-only SYNTHETIC source extraction. Inherit complete genuine
 * Round043 -> Round041 -> Round040 -> Round030 executable chains first.
 * No production I/O, table lease, source owner, loaded DM or positive ACK.
 */
/* ROUND046_INHERIT_REAL_ROUND043_SOURCE */
/* ROUND046_EXTRACT_ACTUAL_LIFETIME_HELPER */

static unsigned int round046_map_observation_calls;

static int round046_traced_lifetime_refusal(
		const struct dm_target *target, const struct swapz_dm *ctx,
		const struct bio *upper_bio,
		const struct swapz_round046_dm_lifetime_report *submitted,
		const struct swapz_round046_dm_lifetime_report *observed)
{
	++round046_map_observation_calls;
	return swapz_round046_dm_lifetime_refuse(
		target, ctx, upper_bio, submitted, observed);
}

static void round046_execute_real_lifetime_callsite(
		struct dm_target *ti, struct swapz_dm *ctx, struct bio *bio)
{
	sector_t count = bio_sectors(bio);

#define swapz_round046_dm_lifetime_refuse round046_traced_lifetime_refusal
/* ROUND046_EXTRACT_ACTUAL_LIFETIME_CALLSITE */
#undef swapz_round046_dm_lifetime_refuse
}

static void round046_run_synthetic_lifetime_negative(
		unsigned int extent_blocks, unsigned int fault)
{
	struct swapz_map current_maps[32] = { 0 };
	struct swapz_dm context = { 0 };
	struct swapz_dm replacement_context = { 0 };
	struct dm_target target = {
		.begin = 64U, .len = 32U * SWAPZ_SECTORS
	};
	struct dm_target replacement_target = {
		.begin = 64U, .len = 32U * SWAPZ_SECTORS
	};
	swapz_u8 original_page[SWAPZ_BLOCK_BYTES];
	swapz_u8 synthetic_readback[SWAPZ_BLOCK_BYTES];
	swapz_u8 protected_header[SWAPZ_BLOCK_BYTES];
	swapz_u8 header_before[SWAPZ_BLOCK_BYTES];
	unsigned char original_sha256[SHA256_DIGEST_LENGTH];
	unsigned char readback_sha256[SHA256_DIGEST_LENGTH];
	struct bio upper = {
		.bi_iter = {
			.bi_sector = 5U * SWAPZ_SECTORS,
			.bi_size = SWAPZ_BLOCK_BYTES
		},
		.bi_opf = REQ_OP_WRITE | REQ_SWAP
	};
	struct swapz_round046_dm_lifetime_report submitted;
	struct swapz_round046_dm_lifetime_report observed;
	struct bio upper_before;
	struct swapz_map map_before;
	struct dm_target *active_target = &target;
	struct swapz_dm *active_context = &context;
	unsigned int expected_callsite_attempts;
	unsigned int byte_index;
	int expected_error = -EOPNOTSUPP;
	int lower_reads_before = lower_reads;
	int lower_writes_before = lower_writes;
	int result;

	assert(extent_blocks == 1U || extent_blocks == 2U ||
	       extent_blocks == 4U);
	assert(fault < 30U);
	context.target = &target;
	context.logical_pages = 32U;
	context.accepting = true;
	context.maps = current_maps;
	context.authority.maps = current_maps;
	target.private = &context;
	replacement_context.target = &replacement_target;
	replacement_context.logical_pages = 32U;
	replacement_context.accepting = true;
	replacement_context.maps = current_maps;
	replacement_context.authority.maps = current_maps;
	replacement_target.private = &replacement_context;
	current_maps[5].valid = true;
	current_maps[5].generation = 13U;
	current_maps[5].start_block = 6U;
	current_maps[5].extent_blocks = (swapz_u8)extent_blocks;
	for (byte_index = 0U; byte_index < SWAPZ_BLOCK_BYTES; ++byte_index)
		original_page[byte_index] = (swapz_u8)(byte_index & 0xffU);
	memcpy(synthetic_readback, original_page, sizeof(original_page));
	memset(protected_header, 0x5a, sizeof(protected_header));
	memcpy(header_before, protected_header, sizeof(header_before));
	assert(SHA256(original_page, sizeof(original_page), original_sha256));
	assert(SHA256(synthetic_readback, sizeof(synthetic_readback),
		      readback_sha256));
	assert(!memcmp(original_sha256, readback_sha256,
		       sizeof(original_sha256)));
	submitted = (struct swapz_round046_dm_lifetime_report) {
		.target_identity = (unsigned long)&target,
		.context_identity = (unsigned long)&context,
		.target_begin = target.begin,
		.target_length = target.len,
		.target_relative_sector = upper.bi_iter.bi_sector,
		.original_bdev_cookie = 17U,
		.original_physical_sector = 8192U,
		.dm_device_cookie = 23U,
		.table_epoch = 29U,
		.callback_ticket = 31U,
		.map_generation = 13U,
		.extent_start_block = 6U,
		.gc_destination = 7U
	};
	observed = submitted;

	switch (fault) {
	case 0U: break; /* Fabricated perfect report: still NO_AUTH */
	case 1U: context.accepting = false;
		expected_error = -ESTALE; break;
	case 2U: /* After simulated dtr/reload: matching geometry, NEW owner */
		active_target = &replacement_target;
		active_context = &replacement_context;
		expected_error = -ESTALE; break;
	case 3U: target.private = &replacement_context;
		expected_error = -ESTALE; break;
	case 4U: context.target = &replacement_target;
		expected_error = -ESTALE; break;
	case 5U: submitted.target_identity = 0U;
		expected_error = -ESTALE; break;
	case 6U: submitted.table_epoch++;
		expected_error = -ESTALE; break;
	case 7U: observed.table_epoch++;
		expected_error = -ESTALE; break;
	case 8U: submitted.callback_ticket++;
		expected_error = -ESTALE; break;
	case 9U: /* In-flight callback observes newer GC map generation */
		observed.map_generation++;
		expected_error = -ESTALE; break;
	case 10U: /* ABA: same scalar generation after retired/reissued map */
		observed.map_generation = submitted.map_generation;
		break;
	case 11U: observed.extent_start_block++;
		expected_error = -ESTALE; break;
	case 12U: observed.gc_destination++;
		expected_error = -ESTALE; break;
	case 13U: submitted.original_bdev_cookie++;
		expected_error = -ESTALE; break;
	case 14U: observed.original_physical_sector++;
		expected_error = -ESTALE; break;
	case 15U: /* Source absolute LBA happens to equal relative 8-sector LBA */
		submitted.original_physical_sector = upper.bi_iter.bi_sector;
		observed.original_physical_sector = upper.bi_iter.bi_sector;
		break;
	case 16U: target.begin += SWAPZ_SECTORS;
		expected_error = -ESTALE; break;
	case 17U: target.len += SWAPZ_SECTORS;
		expected_error = -ESTALE; break;
	case 18U: /* Incorrectly added DM ti->begin to target-relative BIO */
		upper.bi_iter.bi_sector += target.begin;
		expected_error = -ESTALE; break;
	case 19U: upper.bi_iter.bi_sector++;
		expected_error = -ERANGE; break;
	case 20U: upper.bi_iter.bi_sector = target.len - 4U;
		expected_error = -ERANGE; break;
	case 21U: upper.bi_iter.bi_sector = ~(sector_t)0 - 3U;
		expected_error = -ERANGE; break;
	case 22U: upper.bi_opf = REQ_OP_READ | REQ_SWAP; break;
	case 23U: upper.bi_iter.bi_size = 0U; break;
	case 24U: /* Even equal fabricated original/DM bdev is NO_AUTH */
		submitted.original_bdev_cookie = submitted.dm_device_cookie;
		observed.original_bdev_cookie = submitted.original_bdev_cookie;
		break;
	case 25U: /* Both fake epochs agree but cannot pin current table */
		submitted.table_epoch++;
		observed.table_epoch++;
		break;
	case 26U: submitted.original_bdev_cookie = 0U;
		expected_error = -ESTALE; break;
	case 27U: observed.table_epoch = 0U;
		expected_error = -ESTALE; break;
	case 28U: observed.callback_ticket = 0U;
		expected_error = -ESTALE; break;
	case 29U: context.authority.maps = NULL;
		expected_error = -ESTALE; break;
	default: assert(0);
	}

	map_before = current_maps[5];
	upper_before = upper;
	round046_map_observation_calls = 0U;
	result = swapz_round046_dm_lifetime_refuse(
		active_target, active_context, &upper, &submitted, &observed);
	assert(result == expected_error && result < 0);
	/* The exact extracted real map callsite can only observe and refuse. */
	expected_callsite_attempts =
		bio_op(&upper) == REQ_OP_WRITE &&
		bio_sectors(&upper) == SWAPZ_SECTORS &&
		upper.bi_iter.bi_size == SWAPZ_BLOCK_BYTES ? 1U : 0U;
	round046_execute_real_lifetime_callsite(
		active_target, active_context, &upper);
	assert(round046_map_observation_calls == expected_callsite_attempts);
	assert(!memcmp(&upper_before, &upper, sizeof(upper)));
	assert(!memcmp(&map_before, &current_maps[5], sizeof(map_before)));
	assert(!memcmp(header_before, protected_header, sizeof(header_before)));
	assert(lower_reads == lower_reads_before && lower_writes == lower_writes_before);
	/* Only the in-memory mock roundtrip exists; no real READ or upper ACK. */
	assert(SHA256(original_page, sizeof(original_page), original_sha256));
	assert(SHA256(synthetic_readback, sizeof(synthetic_readback),
		      readback_sha256));
	assert(!memcmp(original_sha256, readback_sha256,
		       sizeof(original_sha256)));
	memzero_explicit(original_page, sizeof(original_page));
	memzero_explicit(synthetic_readback, sizeof(synthetic_readback));
}

int main(void)
{
	unsigned int extent_blocks, fault;

	assert(round043_fixture_main() == 0);
	for (extent_blocks = 1U; extent_blocks <= 4U; extent_blocks *= 2U)
		for (fault = 0U; fault < 30U; ++fault)
			round046_run_synthetic_lifetime_negative(extent_blocks, fault);
	puts("ROUND046_ACTUAL_DM_MAP_TABLE_GC_DTR_90_NO_AUTHORITY_PASS");
	return 0;
}
