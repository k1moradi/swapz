/*
 * Round036 HOST boundary only: execute extracted guarded production DM C.
 * Fake lower memcpy is never an actual Linux dm_io, durability or upper ACK.
 * Callback ledger storage outlives every fake callback; owner is serialized.
 */
/* ROUND036_EXTRACT_ALL_PRIOR_SOURCE */
/* ROUND036_EXTRACT_NEW_PRODUCTION_C */

static void round036_check_zeros(const swapz_u8 *bytes, size_t length)
{
	size_t index;

	for (index = 0U; index < length; ++index)
		assert(bytes[index] == 0U);
}

static void round036_check_sentinel(const swapz_u8 *bytes, size_t length,
				   swapz_u8 expected)
{
	size_t index;

	for (index = 0U; index < length; ++index)
		assert(bytes[index] == expected);
}

static void round036_two_phase_case(unsigned int extent_blocks,
				   unsigned int fault)
{
	struct swapz_dm ctx = { 0 };
	struct dm_target target = { .len = 32U * SWAPZ_SECTORS };
	struct swapz_zswap_admission_transaction transaction = { 0 };
	struct swapz_round030_dm_volatile_descriptor unused = { 0 };
	struct swapz_round031_dm_sidecar sidecar = { 0 };
	struct swapz_round036_dm_mock_ledger ledger = { 0 };
	struct swapz_round036_dm_mock_publication publication;
	struct bio_vec vector = {
		.bv_page = original, .bv_offset = 0U, .bv_len = SWAPZ_BLOCK_BYTES
	};
	struct bio pinned_bio = {
		.lifetime_pinned = true,
		.full_uncompressed_4096_swap_write = true,
		.bi_iter = { .bi_sector = 5U * SWAPZ_SECTORS,
			     .bi_size = SWAPZ_BLOCK_BYTES },
		.bi_io_vec = &vector, .bi_bdev = &target,
		.bi_vcnt = 0U, .bi_opf = REQ_OP_WRITE | REQ_SWAP,
		.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK
	};
	swapz_u8 private_compressed[SWAPZ_MAX_COMPRESSED];
	swapz_u8 provider_scratch[SWAPZ_MAX_COMPRESSED];
	swapz_u8 private_stage[4U * SWAPZ_BLOCK_BYTES];
	swapz_u8 fake_readback[4U * SWAPZ_BLOCK_BYTES];
	swapz_u8 private_verified[SWAPZ_BLOCK_BYTES];
	swapz_u8 decoded_scratch[SWAPZ_BLOCK_BYTES];
	swapz_u8 upper_output[SWAPZ_BLOCK_BYTES];
	struct swapz_round032_dm_owned_view_v1 current_source;
	const swapz_u64 source_entry = swp_entry(2U, 39U).val;
	const swapz_u64 callback_cookie = 41U;
	const swapz_u32 extent_bytes = extent_blocks * SWAPZ_BLOCK_BYTES;
	swapz_u32 length;
	swapz_u32 index;
	int error;

	length = (swapz_u32)LZ4_compress_default(
		(const char *)original, (char *)compressed,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
	assert(length > 0U && length <= SWAPZ_MAX_COMPRESSED);
	initial_state(&ctx, &transaction, &unused, extent_bytes, length);
	ctx.target = &target;
	assert(swapz_round031_dm_sidecar_init(&ctx, &sidecar) == 0);
	memcpy(source_lz4_bytes, compressed, length);
	source_lz4_length = (u16)length;
	memcpy(private_compressed, compressed, length);
	transaction.owned_compressed_bytes = private_compressed;
	transaction.payload_capacity = SWAPZ_MAX_COMPRESSED;
	original_provider_view = (struct swapz_ci_lz4_owned_view_v1) {
		.source_swap_entry = source_entry,
		.source_slot_epoch = transaction.record.store_generation,
		.stored_entry_identity = transaction.record.stored_entry_identity,
		.compressed_crc32c = transaction.record.compressed_crc32c,
		.compressed_length = (u16)length,
		.decoded_length = SWAPZ_BLOCK_BYTES,
		.representation_version = 1U, .codec = 1U
	};
	memcpy(original_provider_view.original_sha256,
	       transaction.record.original_sha256, 32U);
	memset(private_stage, 0xbb, sizeof(private_stage));
	memset(private_verified, 0xbb, sizeof(private_verified));
	memset(provider_scratch, 0xbb, sizeof(provider_scratch));
	memset(fake_readback, 0xbb, sizeof(fake_readback));
	memset(decoded_scratch, 0xbb, sizeof(decoded_scratch));
	memset(upper_output, 0xa5, sizeof(upper_output));
	memset(&publication, 0x76, sizeof(publication));
	memset(disk_data, 0, sizeof(disk_data));
	memset(disk_data, 0x36, SWAPZ_BLOCK_BYTES);
	provider_calls = 0;
	injected_provider_errno = 0;

	switch (fault) {
	case 1U: original_provider_view.codec = 2U; break;
	case 2U: original_provider_view.compressed_crc32c ^= 1U; break;
	case 3U: original_provider_view.original_sha256[0] ^= 1U; break;
	case 4U: original_provider_view.source_swap_entry =
			 swp_entry(3U, 39U).val; break;
	case 5U: original_provider_view.source_slot_epoch++; break;
	case 6U: original_provider_view.stored_entry_identity++; break;
	case 7U: pinned_bio.bi_iter.bi_size /= 2U; break;
	case 8U: pinned_bio.lifetime_pinned = false; break;
	case 9U: pinned_bio.bi_iter.bi_sector = 0U; break;
	case 10U: transaction.record.codec = 2U; break;
	case 11U: sidecar.slots[5].owner_token = 99U; break;
	default: break;
	}
	error = swapz_round036_dm_mock_prepare(
		&ctx, &pinned_bio, &sidecar, &transaction, source_entry,
		0U, callback_cookie, 2U, 77U, &ledger,
		private_compressed, provider_scratch,
		private_stage, private_verified);
	if (fault >= 1U && fault <= 11U) {
		assert(error < 0);
		assert(ledger.phase == SWAPZ_ROUND036_EMPTY);
		round036_check_zeros(private_compressed, sizeof(private_compressed));
		round036_check_zeros(provider_scratch, sizeof(provider_scratch));
		goto done;
	}
	assert(error == 0);
	assert(provider_calls == 1);
	assert(ledger.phase == SWAPZ_ROUND036_PREPARED);
	assert(ledger.source.source_swap_entry == source_entry);
	assert(ledger.source.source_slot_epoch ==
	       transaction.record.store_generation);
	assert(transaction.upper_write_ack_count == 0U);
	assert(!ctx.maps[5].valid && lower_writes == 0);
	round036_check_zeros(provider_scratch, sizeof(provider_scratch));
	for (index = 0U; index < extent_bytes; ++index) {
		if (index >= transaction.compressed_payload_offset &&
		    index < transaction.compressed_payload_offset + length)
			assert(private_stage[index] ==
			       source_lz4_bytes[index -
			       transaction.compressed_payload_offset]);
		else
			assert(private_stage[index] == 0U);
	}
	assert(swapz_round036_dm_mock_complete(
		&ctx, &ledger, callback_cookie, 0, extent_bytes,
		fake_readback, extent_bytes, decoded_scratch) == -ESTALE);
	current_source = ledger.source;
	assert(swapz_round036_dm_mock_publish_once(
		&ctx, &sidecar, &transaction, &ledger, callback_cookie,
		77U, &current_source, &publication, upper_output) == -ESTALE);
	assert(swapz_round036_dm_mock_submit(
		&ctx, &ledger, callback_cookie + 1U) == -ESTALE);
	assert(swapz_round036_dm_mock_submit(
		&ctx, &ledger, callback_cookie) == 0);
	assert(ledger.phase == SWAPZ_ROUND036_FAKE_WRITE_IN_FLIGHT);
	assert(transaction.upper_write_ack_count == 0U);
	assert(!ctx.maps[5].valid);

	/* Only this HOST test boundary performs fake lower bytes transfer. */
	memcpy(disk_data + 2U * SWAPZ_BLOCK_BYTES, private_stage, extent_bytes);
	memcpy(fake_readback, disk_data + 2U * SWAPZ_BLOCK_BYTES, extent_bytes);
	if (fault == 14U)
		fake_readback[transaction.compressed_payload_offset] ^= 0x80U;
	if (fault == 15U)
		fake_readback[0] ^= 0x01U;
	if (fault == 16U)
		ledger.source.original_sha256[0] ^= 1U;
	if (fault == 18U)
		swapz_round036_dm_mock_retire(&ledger);
	if (fault == 19U) {
		assert(swapz_round036_dm_mock_complete(
			&ctx, &ledger, callback_cookie + 1U, 0, extent_bytes,
			fake_readback, extent_bytes, decoded_scratch) == -ESTALE);
		assert(ledger.phase == SWAPZ_ROUND036_FAKE_WRITE_IN_FLIGHT);
	}
	error = swapz_round036_dm_mock_complete(
		&ctx, &ledger, callback_cookie,
		fault == 12U ? -EIO : 0,
		fault == 13U ? extent_bytes - 1U : extent_bytes,
		fake_readback, fault == 17U ? 0U : extent_bytes,
		decoded_scratch);
	if (fault == 12U || fault == 13U || fault == 14U ||
	    fault == 15U || fault == 16U || fault == 17U ||
	    fault == 18U) {
		assert(error < 0);
		assert(ledger.phase == SWAPZ_ROUND036_ABORTED);
		assert(transaction.upper_write_ack_count == 0U);
		round036_check_zeros(private_compressed, sizeof(private_compressed));
		round036_check_zeros(private_stage, extent_bytes);
		round036_check_zeros(private_verified, sizeof(private_verified));
		goto done;
	}
	assert(error == 0);
	assert(ledger.phase == SWAPZ_ROUND036_FAKE_READ_VERIFIED);
	assert(transaction.upper_write_ack_count == 0U);
	assert(memcmp(private_verified, original, SWAPZ_BLOCK_BYTES) == 0);
	round036_check_zeros(decoded_scratch, sizeof(decoded_scratch));
	current_source = ledger.source;
	switch (fault) {
	case 20U: current_source.source_swap_entry =
			  swp_entry(3U, 39U).val; break;
	case 21U: current_source.source_slot_epoch++; break;
	case 22U: current_source.stored_entry_identity++; break;
	case 23U: ctx.maps[5].generation++; break;
	case 24U: ctx.gc_recovery.active = true; break;
	case 25U: sidecar.slots[5].owner_token = 222U; break;
	case 26U: transaction.teardown_started = 1U; break;
	case 28U: current_source.compressed_crc32c ^= 1U; break;
	case 29U: current_source.codec = 2U; break;
	case 30U: ctx.accepting = false; break;
	case 31U: private_verified[0] ^= 1U; break;
	case 32U: ctx.authority.gc_destination++; break;
	case 33U: transaction.record.store_generation++; break;
	case 34U: ctx.authority.batch_pending = 1U; break;
	default: break;
	}
	error = swapz_round036_dm_mock_publish_once(
		&ctx, &sidecar, &transaction, &ledger, callback_cookie,
		fault == 27U ? 78U : 77U,
		&current_source, &publication, upper_output);
	if (fault >= 20U && fault <= 34U) {
		assert(error < 0);
		assert(ledger.phase == SWAPZ_ROUND036_ABORTED);
		assert(transaction.upper_write_ack_count == 0U);
		assert(!ctx.maps[5].valid);
		round036_check_zeros(private_compressed, sizeof(private_compressed));
		round036_check_zeros(private_stage, extent_bytes);
		round036_check_zeros(private_verified, sizeof(private_verified));
		goto done;
	}
	assert(error == 0);
	assert(ledger.phase == SWAPZ_ROUND036_SIMULATED_PUBLISHED);
	assert(ledger.hypothetical_ack_count == 1U);
	assert(transaction.upper_write_ack_count == 1U);
	assert(transaction.phase == SWAPZ_ZSWAP_ADMISSION_ACKED);
	assert(transaction.owned_compressed_bytes == NULL);
	assert(publication.hypothetical_ack_count == 1U);
	assert(publication.source_swap_entry == source_entry);
	assert(publication.source_epoch == original_provider_view.source_slot_epoch);
	assert(publication.owner_cookie == callback_cookie);
	assert(publication.fake_start_block == 2U);
	assert(publication.fake_extent_sequence == 77U);
	assert(memcmp(upper_output, original, SWAPZ_BLOCK_BYTES) == 0);
	assert(!ctx.maps[5].valid && sidecar.slots[5].owner_token == 0U);
	assert(lower_writes == 0 && lower_reads == 0);
	round036_check_zeros(private_compressed, sizeof(private_compressed));
	round036_check_zeros(private_stage, extent_bytes);
	round036_check_zeros(private_verified, sizeof(private_verified));
	assert(swapz_round036_dm_mock_complete(
		&ctx, &ledger, callback_cookie, 0, extent_bytes,
		fake_readback, extent_bytes, decoded_scratch) == -ESTALE);
	assert(swapz_round036_dm_mock_publish_once(
		&ctx, &sidecar, &transaction, &ledger, callback_cookie,
		77U, &current_source, &publication, upper_output) == -ESTALE);

done:
	for (index = 0U; index < SWAPZ_BLOCK_BYTES; ++index)
		assert(disk_data[index] == 0x36U);
	if (fault != 0U && fault != 19U && fault != 35U) {
		round036_check_sentinel(upper_output, sizeof(upper_output), 0xa5U);
		round036_check_sentinel((const swapz_u8 *)&publication,
				       sizeof(publication), 0x76U);
	}
	assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
		&ctx, &sidecar) == 0);
	assert(sidecar.closed && !sidecar.slots);
}

static void round036_reuse_after_abort_case(void)
{
	struct swapz_dm ctx = { 0 };
	struct dm_target target = { .len = 32U * SWAPZ_SECTORS };
	struct swapz_zswap_admission_transaction transaction = { 0 };
	struct swapz_round030_dm_volatile_descriptor descriptor = { 0 };
	struct swapz_round031_dm_sidecar sidecar = { 0 };
	struct swapz_round036_dm_mock_ledger ledger = { 0 };
	struct swapz_round032_dm_owned_view_v1 current_source;
	struct swapz_round036_dm_mock_publication publication = { 0 };
	struct bio_vec vector = {
		.bv_page = original, .bv_offset = 0U, .bv_len = SWAPZ_BLOCK_BYTES
	};
	struct bio pinned_bio = {
		.lifetime_pinned = true,
		.full_uncompressed_4096_swap_write = true,
		.bi_iter = { .bi_sector = 5U * SWAPZ_SECTORS,
			     .bi_size = SWAPZ_BLOCK_BYTES },
		.bi_io_vec = &vector, .bi_bdev = &target,
		.bi_vcnt = 0U, .bi_opf = REQ_OP_WRITE | REQ_SWAP,
		.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK
	};
	swapz_u8 private_compressed[SWAPZ_MAX_COMPRESSED];
	swapz_u8 provider_scratch[SWAPZ_MAX_COMPRESSED];
	swapz_u8 stage[SWAPZ_BLOCK_BYTES];
	swapz_u8 readback[SWAPZ_BLOCK_BYTES];
	swapz_u8 verified[SWAPZ_BLOCK_BYTES];
	swapz_u8 scratch[SWAPZ_BLOCK_BYTES];
	swapz_u8 upper[SWAPZ_BLOCK_BYTES];
	const swapz_u64 source_entry = swp_entry(2U, 39U).val;
	swapz_u32 length = (swapz_u32)LZ4_compress_default(
		(const char *)original, (char *)compressed,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);

	assert(length > 0U && length <= SWAPZ_MAX_COMPRESSED);
	initial_state(&ctx, &transaction, &descriptor, SWAPZ_BLOCK_BYTES, length);
	ctx.target = &target;
	memcpy(source_lz4_bytes, compressed, length);
	source_lz4_length = (u16)length;
	original_provider_view = (struct swapz_ci_lz4_owned_view_v1) {
		.source_swap_entry = source_entry,
		.source_slot_epoch = transaction.record.store_generation,
		.stored_entry_identity = transaction.record.stored_entry_identity,
		.compressed_crc32c = transaction.record.compressed_crc32c,
		.compressed_length = (u16)length,
		.decoded_length = SWAPZ_BLOCK_BYTES,
		.representation_version = 1U, .codec = 1U
	};
	memcpy(original_provider_view.original_sha256,
	       transaction.record.original_sha256, 32U);
	assert(swapz_round031_dm_sidecar_init(&ctx, &sidecar) == 0);
	transaction.owned_compressed_bytes = private_compressed;
	transaction.payload_capacity = SWAPZ_MAX_COMPRESSED;
	memcpy(private_compressed, compressed, length);
	assert(swapz_round036_dm_mock_prepare(
		&ctx, &pinned_bio, &sidecar, &transaction, source_entry,
		0U, 41U, 2U, 77U, &ledger, private_compressed,
		provider_scratch, stage, verified) == 0);
	assert(swapz_round036_dm_mock_submit(&ctx, &ledger, 41U) == 0);
	swapz_round036_dm_mock_retire(&ledger);
	assert(swapz_round036_dm_mock_complete(
		&ctx, &ledger, 41U, 0, SWAPZ_BLOCK_BYTES, stage,
		SWAPZ_BLOCK_BYTES, scratch) == -ESTALE);
	memcpy(private_compressed, compressed, length);
	assert(swapz_round036_dm_mock_prepare(
		&ctx, &pinned_bio, &sidecar, &transaction, source_entry,
		0U, 42U, 2U, 78U, &ledger, private_compressed,
		provider_scratch, stage, verified) == 0);
	assert(swapz_round036_dm_mock_submit(&ctx, &ledger, 42U) == 0);
	assert(swapz_round036_dm_mock_complete(
		&ctx, &ledger, 41U, 0, SWAPZ_BLOCK_BYTES, stage,
		SWAPZ_BLOCK_BYTES, scratch) == -ESTALE);
	memcpy(readback, stage, SWAPZ_BLOCK_BYTES);
	assert(swapz_round036_dm_mock_complete(
		&ctx, &ledger, 42U, 0, SWAPZ_BLOCK_BYTES, readback,
		SWAPZ_BLOCK_BYTES, scratch) == 0);
	current_source = ledger.source;
	assert(swapz_round036_dm_mock_publish_once(
		&ctx, &sidecar, &transaction, &ledger, 42U, 78U,
		&current_source, &publication, upper) == 0);
	assert(publication.owner_cookie == 42U);
	assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
		&ctx, &sidecar) == 0);
}

int main(void)
{
	unsigned int extent_blocks, fault;

	assert(swapz_round035_fixture_main() == 0);
	for (extent_blocks = 1U; extent_blocks <= 4U; extent_blocks *= 2U)
		for (fault = 0U; fault <= 35U; ++fault)
			round036_two_phase_case(extent_blocks, fault);
	round036_reuse_after_abort_case();
	puts("ROUND036_REAL_DM_C_FAKE_LOWER_TWO_PHASE_LZ4_4096_SHA_ONE_MOCK_ACK_NO_GO_PASS");
	return 0;
}
