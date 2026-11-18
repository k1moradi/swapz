/*
 * Round038 source-extracted REAL production DM C fake lower READ.
 * Round037's independently executed original LZ4 WRITE callback precedes
 * this test: only its PRIVATE mock publication and owned postheader bytes
 * are used. No real BIO, map, lower I/O, pressure or physical swap device.
 */
/* ROUND038_EXTRACT_ALL_PRIOR_SOURCE */
/* ROUND038_EXTRACT_NEW_PRODUCTION_C */

struct round038_read_event {
	struct swapz_round038_dm_read_mailbox *mailbox;
	swapz_u64 ticket;
	int lower_error;
	swapz_u32 completed_bytes;
	const swapz_u8 *lower_image;
	swapz_u32 image_capacity;
	int result;
};

static void *round038_read_callback_thread(void *event_pointer)
{
	struct round038_read_event *event = event_pointer;

	event->result = swapz_round038_dm_read_fake_callback(
		event->mailbox, event->ticket, event->lower_error,
		event->completed_bytes, event->lower_image,
		event->image_capacity);
	return NULL;
}

static void round038_dispatch_read(struct round038_read_event *event)
{
	pthread_t thread;

	assert(pthread_create(&thread, NULL, round038_read_callback_thread,
			      event) == 0);
	assert(pthread_join(thread, NULL) == 0);
}

static void round038_assert_private_scrubbed(
		const struct swapz_round038_dm_read_mailbox *mailbox)
{
	round036_check_zeros(mailbox->fake_lower_image,
			     sizeof(mailbox->fake_lower_image));
	round036_check_zeros(mailbox->decoded_original,
			     sizeof(mailbox->decoded_original));
	round036_check_zeros(mailbox->verified_original,
			     sizeof(mailbox->verified_original));
	round036_check_zeros((const swapz_u8 *)&mailbox->record,
			     sizeof(mailbox->record));
}

static void round038_test_one(unsigned int extent_blocks,
			     unsigned int fault)
{
	struct swapz_dm ctx = { 0 };
	struct dm_target target = { .len = 32U * SWAPZ_SECTORS };
	struct dm_target remapped_target = { .len = 32U * SWAPZ_SECTORS };
	struct swapz_zswap_admission_transaction transaction = { 0 };
	struct swapz_round030_dm_volatile_descriptor descriptor = { 0 };
	struct swapz_round031_dm_sidecar sidecar = { 0 };
	struct swapz_round037_dm_async_mailbox *write_mailbox =
		calloc(1U, sizeof(*write_mailbox));
	struct swapz_round038_dm_read_mailbox *read_mailbox =
		calloc(1U, sizeof(*read_mailbox));
	struct swapz_round038_dm_read_record read_record = { 0 };
	struct swapz_round036_dm_mock_publication write_publication = { 0 };
	struct swapz_round032_dm_owned_view_v1 current_source;
	struct bio_vec vector = {
		.bv_page = original, .bv_offset = 0U, .bv_len = SWAPZ_BLOCK_BYTES
	};
	struct bio source_bio = {
		.lifetime_pinned = true,
		.full_uncompressed_4096_swap_write = true,
		.bi_iter = { .bi_sector = 5U * SWAPZ_SECTORS,
			     .bi_size = SWAPZ_BLOCK_BYTES },
		.bi_io_vec = &vector, .bi_bdev = &target,
		.bi_vcnt = 0U, .bi_opf = REQ_OP_WRITE | REQ_SWAP,
		.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK
	};
	struct round037_callback_event write_event = { 0 };
	struct round038_read_event read_event = { 0 };
	swapz_u8 mock_write_output[SWAPZ_BLOCK_BYTES];
	swapz_u8 mock_read_output[SWAPZ_BLOCK_BYTES];
	swapz_u8 fake_lower_storage[8U * SWAPZ_BLOCK_BYTES];
	const swapz_u64 source_entry = swp_entry(2U, 39U).val;
	const swapz_u64 write_ticket = 4097U;
	const swapz_u64 read_ticket = 8193U;
	const swapz_u32 extent_bytes = extent_blocks * SWAPZ_BLOCK_BYTES;
	const swapz_u32 fake_start_block = 2U;
	const swapz_u32 extent_sequence = 77U;
	swapz_u32 current_extent_sequence = extent_sequence;
	swapz_u32 compressed_length;
	swapz_u8 *post_header_extent =
		fake_lower_storage + (1U + fake_start_block) * SWAPZ_BLOCK_BYTES;
	unsigned int byte_index;
	int result;

	assert(write_mailbox && read_mailbox);
	compressed_length = (swapz_u32)LZ4_compress_default(
		(const char *)original, (char *)compressed,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
	assert(compressed_length > 0U &&
	       compressed_length <= SWAPZ_MAX_COMPRESSED);
	initial_state(&ctx, &transaction, &descriptor, extent_bytes,
		      compressed_length);
	ctx.target = &target;
	assert(swapz_round031_dm_sidecar_init(&ctx, &sidecar) == 0);
	memcpy(source_lz4_bytes, compressed, compressed_length);
	source_lz4_length = (u16)compressed_length;
	original_provider_view = (struct swapz_ci_lz4_owned_view_v1) {
		.source_swap_entry = source_entry,
		.source_slot_epoch = transaction.record.store_generation,
		.stored_entry_identity = transaction.record.stored_entry_identity,
		.compressed_crc32c = transaction.record.compressed_crc32c,
		.compressed_length = (u16)compressed_length,
		.decoded_length = SWAPZ_BLOCK_BYTES,
		.representation_version = 1U,
		.codec = 1U
	};
	memcpy(original_provider_view.original_sha256,
	       transaction.record.original_sha256, 32U);
	memset(fake_lower_storage, 0, sizeof(fake_lower_storage));
	memset(fake_lower_storage, 0x36, SWAPZ_BLOCK_BYTES);
	memset(mock_read_output, 0xa5, sizeof(mock_read_output));
	memset(mock_write_output, 0xa5, sizeof(mock_write_output));
	memset(disk_data, 0, sizeof(disk_data));
	memset(disk_data, 0x36, SWAPZ_BLOCK_BYTES);
	provider_calls = 0;
	injected_provider_errno = 0;
	swapz_round037_dm_async_initialize(write_mailbox);
	swapz_round038_dm_read_initialize(read_mailbox);

	/* Only actual Round036/037 PRODUCTION DM C constructs the staged
	 * dictionary-free original LZ4 and independently verifies original
	 * full 4096 SHA before its earlier private hypothetical write ACK.
	 */
	assert(swapz_round037_dm_async_prepare(
		&ctx, &source_bio, &sidecar, &transaction,
		source_entry, 0U, write_ticket, fake_start_block,
		extent_sequence, write_mailbox) == 0);
	assert(swapz_round038_dm_read_snapshot_write(
		&ctx, &write_mailbox->ledger, &read_record) == 0);
	assert(read_record.source.source_swap_entry == source_entry);
	assert(read_record.source.source_slot_epoch ==
	       transaction.record.store_generation);
	assert(read_record.source.stored_entry_identity ==
	       transaction.record.stored_entry_identity);
	assert(read_record.extent_bytes == extent_bytes);
	assert(read_record.fake_start_block == fake_start_block);
	memcpy(post_header_extent, write_mailbox->staged_extent, extent_bytes);
	assert(swapz_round037_dm_async_submit(
		&ctx, write_mailbox, write_ticket) == 0);
	write_event.mailbox = write_mailbox;
	write_event.incarnation_ticket = write_ticket;
	write_event.readback = post_header_extent;
	write_event.completed_bytes = extent_bytes;
	write_event.readback_bytes = extent_bytes;
	ctx.ordered_owner = 0;
	round037_dispatch_fake_callback(&write_event);
	ctx.ordered_owner = 1;
	assert(write_event.result == 0);
	current_source = write_mailbox->ledger.source;
	assert(swapz_round037_dm_async_finish(
		&ctx, &sidecar, write_ticket, extent_sequence, &current_source,
		&write_publication, mock_write_output, write_mailbox) == 0);
	assert(write_publication.hypothetical_ack_count == 1U);
	assert(!memcmp(mock_write_output, original, SWAPZ_BLOCK_BYTES));
	assert(transaction.upper_write_ack_count == 0U);
	assert(!ctx.maps[5].valid);
	round037_assert_clean(write_mailbox);

	/* PREPARE witnesses deliberately fail before a new callback ref. */
	switch (fault) {
	case 1U: current_source.source_slot_epoch++; break;
	case 2U: current_source.source_swap_entry =
			 swp_entry(3U, 39U).val; break;
	case 3U: sidecar.slots[5].owner_token++; break;
	default: break;
	}
	result = swapz_round038_dm_read_prepare(
		&ctx, &sidecar, &write_publication, &current_source,
		&read_record, current_extent_sequence, read_ticket, read_mailbox);
	if (fault >= 1U && fault <= 3U) {
		assert(result == -ESTALE);
		assert(read_mailbox->phase == SWAPZ_ROUND038_READ_EXPIRED);
		round038_assert_private_scrubbed(read_mailbox);
		goto done;
	}
	assert(result == 0);
	assert(read_mailbox->phase == SWAPZ_ROUND038_READ_PREPARED);
	assert(read_mailbox->callback_references == 0U);
	assert(swapz_round038_dm_read_finish(
		&ctx, &sidecar, &write_publication, &current_source,
		current_extent_sequence, read_ticket, mock_read_output,
		read_mailbox) == -ESTALE);
	assert(swapz_round038_dm_read_submit(
		&ctx, &sidecar, &write_publication, &current_source,
		current_extent_sequence, read_ticket + 1U, read_mailbox)
		== -ESTALE);
	assert(swapz_round038_dm_read_submit(
		&ctx, &sidecar, &write_publication, &current_source,
		current_extent_sequence, read_ticket, read_mailbox) == 0);
	assert(read_mailbox->phase ==
	       SWAPZ_ROUND038_FAKE_LOWER_READ_IN_FLIGHT);
	assert(read_mailbox->callback_references == 1U);
	assert(swapz_round038_dm_read_prepare(
		&ctx, &sidecar, &write_publication, &current_source,
		&read_record, current_extent_sequence, read_ticket + 1U,
		read_mailbox) == -EBUSY);
	read_event.mailbox = read_mailbox;
	read_event.ticket = read_ticket;
	read_event.lower_image = post_header_extent;
	read_event.completed_bytes = extent_bytes;
	read_event.image_capacity = extent_bytes;

	/* A GC move before fake lower completion is still seen after callback;
	 * callback itself never dereferences ctx or its retired target.
	 */
	switch (fault) {
	case 4U: ctx.authority.gc_destination++; break;
	case 5U: ctx.authority.gc_forbidden_victim++; break;
	case 6U: ctx.maps[5].generation++; break;
	case 7U: ctx.gc_recovery.active = true; break;
	case 8U: ctx.accepting = false; break;
	case 9U: ctx.target = &remapped_target; break;
	case 19U: read_event.completed_bytes--; break;
	case 20U: read_event.lower_error = -EIO; break;
	case 21U: read_event.lower_error = 1; break;
	case 22U: read_event.image_capacity--; break;
	case 23U: read_event.lower_image = NULL; break;
	case 24U: post_header_extent[extent_bytes - 1U] = 1U; break;
	case 25U: post_header_extent[read_record.payload_offset] ^= 1U; break;
	case 26U:
		memset(post_header_extent + read_record.payload_offset,
		       0, read_record.source.compressed_length);
		break;
	case 30U:
	case 33U:
		assert(swapz_round038_dm_read_cancel(
			&ctx, read_ticket, read_mailbox) == 0);
		assert(read_mailbox->callback_references == 1U);
		round038_assert_private_scrubbed(read_mailbox);
		ctx.accepting = false;
		ctx.ordered_owner = 0;
		round038_dispatch_read(&read_event);
		assert(read_event.result == -ESTALE);
		assert(read_mailbox->phase == SWAPZ_ROUND038_READ_EXPIRED);
		assert(read_mailbox->callback_references == 0U);
		ctx.accepting = true;
		ctx.ordered_owner = 1;
		round038_assert_private_scrubbed(read_mailbox);
		if (fault == 33U) {
			/* A -> B -> A is forbidden even AFTER the old callback
			 * reference has been drained; stale callback cannot
			 * steal B's outstanding owned reference.
			 */
			assert(swapz_round038_dm_read_prepare(
				&ctx, &sidecar, &write_publication,
				&current_source, &read_record, extent_sequence,
				read_ticket + 1U, read_mailbox) == 0);
			assert(swapz_round038_dm_read_submit(
				&ctx, &sidecar, &write_publication,
				&current_source, extent_sequence,
				read_ticket + 1U, read_mailbox) == 0);
			assert(swapz_round038_dm_read_fake_callback(
				read_mailbox, read_ticket, 0, extent_bytes,
				post_header_extent, extent_bytes) == -ESTALE);
			assert(read_mailbox->callback_references == 1U);
			assert(swapz_round038_dm_read_cancel(
				&ctx, read_ticket + 1U, read_mailbox) == 0);
			assert(swapz_round038_dm_read_fake_callback(
				read_mailbox, read_ticket + 1U, 0, extent_bytes,
				post_header_extent, extent_bytes) == -ESTALE);
			assert(swapz_round038_dm_read_prepare(
				&ctx, &sidecar, &write_publication,
				&current_source, &read_record, extent_sequence,
				read_ticket, read_mailbox) == -EBUSY);
		}
		goto done;
	default: break;
	}
	ctx.ordered_owner = 0;
	round038_dispatch_read(&read_event);
	ctx.ordered_owner = 1;
	if (fault >= 19U && fault <= 23U) {
		assert(read_event.result == -EIO);
		assert(read_mailbox->phase == SWAPZ_ROUND038_FAKE_READ_ERROR);
	} else {
		assert(read_event.result == 0);
		assert(read_mailbox->phase == SWAPZ_ROUND038_FAKE_READ_OK);
	}
	assert(read_mailbox->callback_references == 0U);
	assert(swapz_round038_dm_read_fake_callback(
		read_mailbox, read_ticket, 0, extent_bytes,
		post_header_extent, extent_bytes) == -ESTALE);

	/* The independent phase after callback but BEFORE mock copy can
	 * reallocate the same original slot epoch, remap the target,
	 * retire the segment or overwrite the compressed image.
	 */
	switch (fault) {
	case 10U: current_source.source_slot_epoch++; break;
	case 11U: current_source.stored_entry_identity++; break;
	case 12U: current_source.source_swap_entry =
			  swp_entry(3U, 39U).val; break;
	case 13U: current_source.original_sha256[0] ^= 1U; break;
	case 14U: sidecar.slots[5].owner_token++; break;
	case 15U: current_extent_sequence++; break;
	case 16U: write_publication.fake_extent_sequence++; break;
	case 17U: write_publication.owner_cookie++; break;
	case 18U: read_mailbox->record.source.compressed_length = 0U; break;
	case 27U:
		read_mailbox->record.source.original_sha256[0] ^= 1U;
		current_source.original_sha256[0] ^= 1U;
		break;
	case 28U: ctx.authority.gc_destination++; break;
	case 29U: ctx.target = &remapped_target; break;
	case 31U:
		assert(swapz_round038_dm_read_cancel(
			&ctx, read_ticket, read_mailbox) == 0);
		round038_assert_private_scrubbed(read_mailbox);
		break;
	case 34U:
		/* Correct CRC for malicious compressed data is NOT enough.
		 * The dictionary-free decoder or independent STORE SHA fails.
		 */
		memset(read_mailbox->fake_lower_image +
		       read_record.payload_offset, 0,
		       read_record.source.compressed_length);
		read_mailbox->record.source.compressed_crc32c =
			swapz_crc32c_bytes(
			    read_mailbox->fake_lower_image +
			    read_record.payload_offset,
			    read_record.source.compressed_length);
		current_source.compressed_crc32c =
			read_mailbox->record.source.compressed_crc32c;
		break;
	case 35U: sidecar.slots[5].readers++; break;
	case 36U: ctx.authority.gc_allocation = true; break;
	case 37U: ctx.authority.batch_pending = true; break;
	case 38U: current_source.codec++; break;
	case 39U: current_source.representation_version++; break;
	case 40U:
		read_mailbox->record.source.compressed_length =
			SWAPZ_MAX_COMPRESSED + 1U;
		break;
	case 41U: write_publication.stored_identity++; break;
	case 42U: target.len--; break;
	case 43U: read_mailbox->record.payload_offset = extent_bytes; break;
	case 44U:
		read_mailbox->fake_lower_image[read_record.payload_offset] ^= 1U;
		break;
	default: break;
	}
	result = swapz_round038_dm_read_finish(
		&ctx, &sidecar, &write_publication, &current_source,
		current_extent_sequence, read_ticket, mock_read_output,
		read_mailbox);
	if (fault == 0U || fault == 32U) {
		assert(result == 0);
		assert(read_mailbox->phase ==
		       SWAPZ_ROUND038_MOCK_READ_BUFFER_PUBLISHED);
		assert(!memcmp(mock_read_output, original, SWAPZ_BLOCK_BYTES));
		round038_assert_private_scrubbed(read_mailbox);
		assert(swapz_round038_dm_read_finish(
			&ctx, &sidecar, &write_publication, &current_source,
			current_extent_sequence, read_ticket, mock_read_output,
			read_mailbox) == -ESTALE);
	} else {
		assert(result < 0);
		assert(read_mailbox->phase == SWAPZ_ROUND038_READ_EXPIRED ||
		       read_mailbox->phase == SWAPZ_ROUND038_READ_CANCELLED);
		round038_assert_private_scrubbed(read_mailbox);
		round036_check_sentinel(mock_read_output,
				       sizeof(mock_read_output), 0xa5U);
	}
done:
	/* Protected original SWAPSPACE2 first block remains pristine even
	 * when simulated lower payload/GC is corrupted or cancelled.
	 */
	for (byte_index = 0U; byte_index < SWAPZ_BLOCK_BYTES; ++byte_index)
		assert(fake_lower_storage[byte_index] == 0x36U);
	assert(transaction.phase == SWAPZ_ZSWAP_ADMISSION_PREPARED);
	assert(transaction.upper_write_ack_count == 0U);
	assert(lower_reads == 0 && lower_writes == 0);
	assert(read_mailbox->callback_references == 0U);
	/* Fault 35 owns one synthetic reader. Prove teardown refuses it,
	 * then drain that fixture-owned reference before final teardown.
	 */
	if (fault == 35U) {
		assert(sidecar.slots[5].readers == 1U);
		assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
			&ctx, &sidecar) == -EBUSY);
		sidecar.slots[5].readers--;
	}
	assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
		&ctx, &sidecar) == 0);
	assert(pthread_mutex_destroy(&write_mailbox->callback_lock) == 0);
	assert(pthread_mutex_destroy(&read_mailbox->callback_lock) == 0);
	free(write_mailbox);
	free(read_mailbox);
}

int main(void)
{
	unsigned int extent_blocks, fault;

	assert(round037_fixture_main() == 0);
	for (extent_blocks = 1U; extent_blocks <= 4U; extent_blocks *= 2U)
		for (fault = 0U; fault <= 44U; ++fault)
			round038_test_one(extent_blocks, fault);
	puts("ROUND038_ACTUAL_PRODUCTION_DM_ASYNC_READ_4096_SHA_GC_ABA_OUTPUT_ATOMIC_NO_GO_PASS");
	return 0;
}
