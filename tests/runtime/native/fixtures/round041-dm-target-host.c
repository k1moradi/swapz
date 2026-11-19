/*
 * Round041: REAL source-extracted DM target interval/extent/GC read-only
 * nonauthority probe. Fake postheader lower images, no physical IO or BIO ACK.
 * Inherit ALL Round030..040 original source tests and source LZ4/SHA checks.
 */
/* ROUND041_EXTRACT_ALL_PRIOR_SOURCE */
/* ROUND041_EXTRACT_TARGET_BACKING_CONVERSION */
/* ROUND041_EXTRACT_NEW_PRODUCTION_C */

static void round041_target_negative_case(unsigned int extent_blocks,
					 unsigned int fault)
{
	struct swapz_dm context = { 0 };
	struct dm_target target = { .begin = 64U,
				    .len = 32U * SWAPZ_SECTORS };
	struct dm_target other_target = { .begin = 64U,
					  .len = 32U * SWAPZ_SECTORS };
	struct bio upper = {
		.bi_iter = { .bi_sector = 64U + 5U * SWAPZ_SECTORS,
			     .bi_size = SWAPZ_BLOCK_BYTES },
		.bi_opf = REQ_OP_WRITE | REQ_SWAP
	};
	struct swapz_round038_dm_read_record record = { 0 };
	struct swapz_round032_dm_owned_view_v1 source = { 0 };
	struct swapz_round041_dm_target_claim claim = { 0 };
	struct swapz_round041_dm_target_observed observed = { 0 };
	struct swapz_round038_dm_read_mailbox *verifier =
		calloc(1U, sizeof(*verifier));
	struct swapz_map map_snapshot;
	swapz_u8 plaintext[SWAPZ_BLOCK_BYTES];
	swapz_u8 compressed[SWAPZ_MAX_COMPRESSED];
	swapz_u8 mock_upper[SWAPZ_BLOCK_BYTES];
	swapz_u8 mock_upper_snapshot[SWAPZ_BLOCK_BYTES];
	swapz_u8 *fake_lower = calloc(32U, SWAPZ_BLOCK_BYTES);
	swapz_u8 *fake_lower_snapshot = calloc(32U, SWAPZ_BLOCK_BYTES);
	const swapz_u32 extent_bytes = extent_blocks * SWAPZ_BLOCK_BYTES;
	swapz_u32 compressed_length;
	int read_count_before = lower_reads;
	int write_count_before = lower_writes;
	int result;

	assert(verifier && fake_lower && fake_lower_snapshot);
	memset(maps, 0, sizeof(maps));
	memset(plaintext, 0x7d, sizeof(plaintext));
	plaintext[0] = 0x31U;
	plaintext[SWAPZ_BLOCK_BYTES - 1U] = 0x62U;
	compressed_length = (swapz_u32)LZ4_compress_default(
		(const char *)plaintext, (char *)compressed,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
	assert(compressed_length > 0U &&
	       compressed_length <= SWAPZ_MAX_COMPRESSED);

	context.target = &target;
	context.maps = maps;
	context.authority.maps = maps;
	context.authority.logical_pages = 32U;
	context.authority.physical_blocks = 32U;
	context.authority.gc_destination = 7U;
	context.data_start_block = 1U;
	context.accepting = true;
	context.ordered_owner = 1;
	target.private = &context;
	other_target.private = &context;

	source.source_swap_entry = swp_entry(2U, 39U).val;
	source.source_slot_epoch = 33U;
	source.stored_entry_identity = 55U;
	source.compressed_crc32c =
		swapz_crc32c_bytes(compressed, compressed_length);
	source.compressed_length = (swapz_u16)compressed_length;
	source.decoded_length = SWAPZ_BLOCK_BYTES;
	source.representation_version = SWAPZ_ZSWAP_IMPORT_VERSION;
	source.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
	assert(SHA256(plaintext, sizeof(plaintext), source.original_sha256));

	record.source = source;
	record.logical_page = 5U;
	record.target_identity = (unsigned long)&target;
	record.target_length = target.len;
	record.fake_start_block = 6U;
	record.fake_extent_sequence = 100U;
	record.extent_bytes = extent_bytes;
	record.payload_offset = extent_bytes - compressed_length;
	record.write_ticket = 8080U;

	maps[5].valid = true;
	maps[5].raw = false;
	maps[5].generation = 77U;
	maps[5].start_block = 6U;
	maps[5].extent_blocks = (swapz_u8)extent_blocks;
	maps[5].payload_length = (swapz_u16)compressed_length;
	maps[5].payload_crc32c = source.compressed_crc32c;
	memset(fake_lower, 0, 32U * SWAPZ_BLOCK_BYTES);
	memset(fake_lower, 0x36, SWAPZ_BLOCK_BYTES);
	memcpy(fake_lower + (1U + 6U) * SWAPZ_BLOCK_BYTES +
		       record.payload_offset, compressed, compressed_length);

	/* This is the ACTUAL Round038 production C CRC, dictionary-free LZ4
	 * decode and ORIGINAL STORE-time full 4096 SHA, not another codec.
	 * It is strictly a content witness, NOT a current source/DM lease.
	 */
	verifier->record = record;
	memcpy(verifier->fake_lower_image,
	       fake_lower + (1U + 6U) * SWAPZ_BLOCK_BYTES, extent_bytes);
	verifier->phase = SWAPZ_ROUND038_GC_OWNER_REVALIDATED;
	assert(swapz_round038_dm_read_verify_private(verifier) == 0);
	assert(!memcmp(verifier->verified_original, plaintext,
		       SWAPZ_BLOCK_BYTES));
	swapz_round038_dm_read_scrub(verifier);

	claim.source = source;
	claim.original_area_cookie = 0x421U;
	claim.original_bdev_cookie = 0x521U;
	claim.original_physical_sector = 800U; /* NONLINEAR source sector */
	claim.dm_device_cookie = 0x621U;
	claim.table_epoch = 11U;
	claim.lifetime_epoch = 19U;
	claim.callback_ticket = 8080U;
	claim.target_begin = target.begin;
	claim.target_length = target.len;
	claim.relative_sector = 5U * SWAPZ_SECTORS;
	claim.expected_lower_sector = (1U + 6U) * SWAPZ_SECTORS;
	claim.logical_page = 5U;
	claim.map_generation = maps[5].generation;
	claim.gc_destination = context.authority.gc_destination;
	claim.extent_start_block = maps[5].start_block;
	claim.extent_sequence = record.fake_extent_sequence;
	claim.target_identity = (unsigned long)&target;
	claim.private_identity = (unsigned long)&context;
	observed.original_area_cookie = claim.original_area_cookie;
	observed.original_bdev_cookie = claim.original_bdev_cookie;
	observed.original_physical_sector = claim.original_physical_sector;
	observed.dm_device_cookie = claim.dm_device_cookie;
	observed.table_epoch = claim.table_epoch;
	observed.lifetime_epoch = claim.lifetime_epoch;
	observed.callback_ticket = claim.callback_ticket;

	/* 48 distinct deterministic target/domain/ABA/GC/teardown faults
	 * per legal fake extent size: 3 * 48 = 144 source-executed negatives.
	 */
	switch (fault) {
	case 0U: break; /* even fully matching synthetic fields: NO AUTH */
	case 1U: context.target = &other_target; break;
	case 2U: target.private = &other_target; break;
	case 3U: observed.original_area_cookie++; break;
	case 4U: observed.original_bdev_cookie++; break;
	case 5U: observed.original_physical_sector += SWAPZ_SECTORS; break;
	case 6U: observed.dm_device_cookie++; break;
	case 7U: observed.table_epoch++; break;
	case 8U: observed.lifetime_epoch++; break;
	case 9U: claim.target_identity = (unsigned long)&other_target; break;
	case 10U: claim.private_identity = (unsigned long)&other_target; break;
	case 11U: target.begin += SWAPZ_SECTORS; break;
	case 12U: target.len -= SWAPZ_SECTORS; break;
	case 13U: upper.bi_iter.bi_sector = target.begin - SWAPZ_SECTORS; break;
	case 14U: upper.bi_iter.bi_sector =
				target.begin + target.len - 4U; break;
	case 15U: target.begin = ~(swapz_u64)0 - 3U; break;
	case 16U: upper.bi_iter.bi_sector = ~(swapz_u64)0 - 3U; break;
	case 17U: upper.bi_iter.bi_sector++; break;
	case 18U: claim.relative_sector += SWAPZ_SECTORS; break;
	case 19U: upper.bi_iter.bi_size -= 512U; break;
	case 20U: upper.bi_opf = REQ_OP_READ | REQ_SWAP; break;
	case 21U: claim.source.source_swap_entry = 0U; break;
	case 22U: source.source_swap_entry = ~(swapz_u64)0; break;
	case 23U: observed.original_area_cookie = 0U; break;
	case 24U: claim.source.source_slot_epoch++; break;
	case 25U: claim.source.stored_entry_identity++; break;
	case 26U: claim.source.original_sha256[0] ^= 1U; break;
	case 27U: claim.source.compressed_crc32c ^= 1U; break;
	case 28U: maps[5].generation++; break;
	case 29U: maps[5].start_block++; break;
	case 30U: context.authority.gc_destination++; break;
	case 31U: context.gc_recovery.active = true; break;
	case 32U: context.accepting = false; break;
	case 33U: context.failed = true; break;
	case 34U: /* identical absolute sector, replaced target instance */
		target.private = NULL; break;
	case 35U: /* identical target/private address, newer dtr epoch */
		observed.lifetime_epoch += 2U; break;
	case 36U: /* same numeral but original backing bdev was remapped */
		observed.original_bdev_cookie += 2U; break;
	case 37U: /* arbitrary real swapfile physical LBA not DM LBA */
		claim.original_physical_sector = upper.bi_iter.bi_sector;
		observed.original_physical_sector = claim.original_physical_sector;
		break;
	case 38U: maps[5].raw = true; break;
	case 39U: maps[5].valid = false; break;
	case 40U: /* would touch the protected first entire 4096 */
		context.data_start_block = 0U;
		maps[5].start_block = 0U;
		record.fake_start_block = 0U;
		claim.extent_start_block = 0U;
		break;
	case 41U: record.fake_extent_sequence++; break;
	case 42U: record.target_identity = (unsigned long)&other_target; break;
	case 43U: record.target_length++; break;
	case 44U: record.logical_page++; break;
	case 45U: maps[5].payload_length++; break;
	case 46U: maps[5].payload_crc32c ^= 1U; break;
	case 47U: /* dirty ZERO padding rejected by real Round038 verifier */
		verifier->record = record;
		memcpy(verifier->fake_lower_image,
		       fake_lower + (1U + 6U) * SWAPZ_BLOCK_BYTES,
		       extent_bytes);
		verifier->fake_lower_image[0] = 0x8bU;
		verifier->phase = SWAPZ_ROUND038_GC_OWNER_REVALIDATED;
		assert(swapz_round038_dm_read_verify_private(verifier) ==
		       -EBADMSG);
		swapz_round038_dm_read_scrub(verifier);
		break;
	default: assert(0);
	}

	map_snapshot = maps[5];
	memcpy(fake_lower_snapshot, fake_lower, 32U * SWAPZ_BLOCK_BYTES);
	memset(mock_upper, 0xa5, sizeof(mock_upper));
	memcpy(mock_upper_snapshot, mock_upper, sizeof(mock_upper));
	/* Hypothetical ACK stays exactly zero. No callback is scheduled.
	 * A stale ref or dtr cannot escape the caller-owned stack objects.
	 */
	result = swapz_round041_dm_target_interval_refuse(
		&context, &target, &upper, &record, &source, &claim, &observed);
	assert(result < 0);
	if (fault == 0U || fault == 37U || fault == 47U)
		assert(result == -EOPNOTSUPP);
	else
		assert(result != -EOPNOTSUPP);
	assert(!memcmp(&map_snapshot, &maps[5], sizeof(map_snapshot)));
	assert(!memcmp(mock_upper_snapshot, mock_upper, sizeof(mock_upper)));
	assert(!memcmp(fake_lower_snapshot, fake_lower,
		       32U * SWAPZ_BLOCK_BYTES));
	round040_check_header(fake_lower);
	assert(lower_reads == read_count_before &&
	       lower_writes == write_count_before);

	memzero_explicit(verifier, sizeof(*verifier));
	memzero_explicit(compressed, sizeof(compressed));
	memzero_explicit(plaintext, sizeof(plaintext));
	memzero_explicit(mock_upper, sizeof(mock_upper));
	memzero_explicit(fake_lower, 32U * SWAPZ_BLOCK_BYTES);
	free(verifier);
	free(fake_lower);
	free(fake_lower_snapshot);
}

int main(void)
{
	unsigned int extent_blocks, fault;

	assert(round040_fixture_main() == 0);
	for (extent_blocks = 1U; extent_blocks <= 4U; extent_blocks *= 2U)
		for (fault = 0U; fault < 48U; ++fault)
			round041_target_negative_case(extent_blocks, fault);
	puts("ROUND041_ACTUAL_DM_TARGET_INTERVAL_TABLE_GC_TEARDOWN_144_NO_AUTHORITY_PASS");
	return 0;
}
