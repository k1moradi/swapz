/*
 * Round039 exact guarded production DM C chain. The underlying source
 * fragments (036/037/038/039) are extracted from src/kernel/dm-target.c.
 * All lower areas are caller-owned RAM; no real map, pressure or bio_endio.
 */
/* ROUND039_EXTRACT_ALL_PRIOR_SOURCE */
/* ROUND039_EXTRACT_NEW_PRODUCTION_C */

struct round039_gc_event {
	struct swapz_round039_dm_chain *chain;
	swapz_u64 gc_ticket;
	int error;
	swapz_u32 completed_bytes;
	const swapz_u8 *readback;
	swapz_u32 capacity;
	int result;
};

static void *round039_gc_completion_thread(void *opaque)
{
	struct round039_gc_event *event = opaque;

	event->result = swapz_round039_dm_chain_gc_fake_callback(
		event->chain, event->gc_ticket, event->error,
		event->completed_bytes, event->readback, event->capacity);
	return NULL;
}

static void round039_dispatch_gc(struct round039_gc_event *event)
{
	pthread_t callback_thread;

	assert(pthread_create(&callback_thread, NULL,
			      round039_gc_completion_thread, event) == 0);
	assert(pthread_join(callback_thread, NULL) == 0);
}

static void round039_test_chain(unsigned int extent_blocks,
			       unsigned int fault)
{
	struct swapz_dm context = { 0 };
	struct dm_target target = { .len = 32U * SWAPZ_SECTORS };
	struct dm_target replacement_target = { .len = 32U * SWAPZ_SECTORS };
	struct swapz_zswap_admission_transaction transaction = { 0 };
	struct swapz_round030_dm_volatile_descriptor descriptor = { 0 };
	struct swapz_round031_dm_sidecar sidecar = { 0 };
	struct swapz_round037_dm_async_mailbox *write_mailbox =
		calloc(1U, sizeof(*write_mailbox));
	struct swapz_round038_dm_read_mailbox *read_mailbox =
		calloc(1U, sizeof(*read_mailbox));
	struct swapz_round039_dm_chain *chain =
		calloc(1U, sizeof(*chain));
	struct swapz_round038_dm_read_record original_write = { 0 };
	struct swapz_round036_dm_mock_publication write_publication = { 0 };
	struct swapz_round032_dm_owned_view_v1 current_source;
	struct bio_vec vector = {
		.bv_page = original, .bv_offset = 0U,
		.bv_len = SWAPZ_BLOCK_BYTES
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
	struct round039_gc_event gc_event = { 0 };
	swapz_u8 *lower_area = calloc(16U, SWAPZ_BLOCK_BYTES);
	swapz_u8 mock_write[SWAPZ_BLOCK_BYTES];
	swapz_u8 mock_read[SWAPZ_BLOCK_BYTES];
	const swapz_u32 extent_bytes = extent_blocks * SWAPZ_BLOCK_BYTES;
	const swapz_u64 source_swap_entry = swp_entry(2U, 39U).val;
	const swapz_u64 write_ticket = 4097U;
	const swapz_u64 gc_ticket = 7001U;
	const swapz_u64 read_ticket = 9001U;
	const swapz_u32 original_block = 2U;
	const swapz_u32 relocated_block = 8U;
	const swapz_u32 original_sequence = 77U;
	const swapz_u32 relocated_sequence = 78U;
	swapz_u8 *original_extent;
	swapz_u8 *relocated_extent;
	swapz_u32 compressed_length;
	swapz_u64 captured_generation;
	unsigned int byte_index;
	int error;

	assert(write_mailbox && read_mailbox && chain && lower_area);
	original_extent = lower_area + (1U + original_block) * SWAPZ_BLOCK_BYTES;
	relocated_extent = lower_area + (1U + relocated_block) * SWAPZ_BLOCK_BYTES;
	compressed_length = (swapz_u32)LZ4_compress_default(
		(const char *)original, (char *)compressed,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
	assert(compressed_length >= 1U &&
	       compressed_length <= SWAPZ_MAX_COMPRESSED);
	initial_state(&context, &transaction, &descriptor, extent_bytes,
		      compressed_length);
	/* The inherited Round035 host has only eight fake physical blocks.
	 * This chain owns TWO nonoverlapping four-block postheader extents;
	 * expand only its bounded fake geometry, never the actual DM target.
	 */
	context.authority.physical_blocks = 16U;
	context.target = &target;
	assert(swapz_round031_dm_sidecar_init(&context, &sidecar) == 0);
	memcpy(source_lz4_bytes, compressed, compressed_length);
	source_lz4_length = (u16)compressed_length;
	original_provider_view = (struct swapz_ci_lz4_owned_view_v1) {
		.source_swap_entry = source_swap_entry,
		.source_slot_epoch = transaction.record.store_generation,
		.stored_entry_identity = transaction.record.stored_entry_identity,
		.compressed_crc32c = transaction.record.compressed_crc32c,
		.compressed_length = (u16)compressed_length,
		.decoded_length = SWAPZ_BLOCK_BYTES,
		.representation_version = 1U, .codec = 1U
	};
	memcpy(original_provider_view.original_sha256,
	       transaction.record.original_sha256, 32U);
	memset(lower_area, 0, 16U * SWAPZ_BLOCK_BYTES);
	memset(lower_area, 0x36, SWAPZ_BLOCK_BYTES);
	memset(mock_write, 0xa5, sizeof(mock_write));
	memset(mock_read, 0xa5, sizeof(mock_read));
	memset(disk_data, 0, sizeof(disk_data));
	memset(disk_data, 0x36, SWAPZ_BLOCK_BYTES);
	provider_calls = 0;
	injected_provider_errno = 0;
	swapz_round037_dm_async_initialize(write_mailbox);
	swapz_round038_dm_read_initialize(read_mailbox);
	swapz_round039_dm_chain_initialize(chain);

	/* The ACTUAL prior Round037 copied source C stages a separate LZ4
	 * representation, not an ordinary RAW uncompressed 4096 record.
	 */
	assert(swapz_round037_dm_async_prepare(
		&context, &source_bio, &sidecar, &transaction,
		source_swap_entry, 0U, write_ticket, original_block,
		original_sequence, write_mailbox) == 0);
	assert(swapz_round038_dm_read_snapshot_write(
		&context, &write_mailbox->ledger, &original_write) == 0);
	memcpy(original_extent, write_mailbox->staged_extent, extent_bytes);
	assert(swapz_round037_dm_async_submit(
		&context, write_mailbox, write_ticket) == 0);
	write_event.mailbox = write_mailbox;
	write_event.incarnation_ticket = write_ticket;
	write_event.readback = original_extent;
	write_event.completed_bytes = extent_bytes;
	write_event.readback_bytes = extent_bytes;
	if (fault == 1U)
		write_event.completed_bytes--;
	if (fault == 2U)
		write_event.fake_error = 1;
	if (fault == 3U)
		write_event.fake_error = -EIO;
	if (fault == 4U)
		assert(swapz_round037_dm_async_cancel(
			&context, write_mailbox, write_ticket) == 0);
	context.ordered_owner = 0;
	round037_dispatch_fake_callback(&write_event);
	context.ordered_owner = 1;
	if (fault >= 1U && fault <= 4U) {
		assert(write_event.result == (fault == 4U ? -ESTALE : -EIO));
		assert(swapz_round037_dm_async_finish(
			&context, &sidecar, write_ticket, original_sequence,
			&original_write.source, &write_publication,
			mock_write, write_mailbox) < 0);
		assert(write_publication.hypothetical_ack_count == 0U);
		assert(chain->phase == SWAPZ_ROUND039_CHAIN_EMPTY);
		goto complete;
	}
	assert(write_event.result == 0);
	current_source = write_mailbox->ledger.source;
	assert(swapz_round037_dm_async_finish(
		&context, &sidecar, write_ticket, original_sequence,
		&current_source, &write_publication,
		mock_write, write_mailbox) == 0);
	assert(write_publication.hypothetical_ack_count == 1U);
	assert(!memcmp(mock_write, original, SWAPZ_BLOCK_BYTES));
	assert(transaction.upper_write_ack_count == 0U);
	assert(swapz_round037_dm_async_finish(
		&context, &sidecar, write_ticket, original_sequence,
		&current_source, &write_publication,
		mock_write, write_mailbox) == -ESTALE);
	assert(swapz_round039_dm_chain_accept_write(
		&context, &sidecar, &current_source, &original_write,
		&write_publication, chain) == 0);
	assert(swapz_round039_dm_chain_accept_write(
		&context, &sidecar, &current_source, &original_write,
		&write_publication, chain) == -ESTALE);
	assert(chain->hypothetical_write_acks == 1U);
	assert(!context.maps[5].valid);
	round037_assert_clean(write_mailbox);

	/* These are mutations to the current original source / GC witness
	 * before GC PREPARE. No current MOCK map may change.
	 */
	switch (fault) {
	case 5U: current_source.source_slot_epoch++; break;
	case 6U: current_source.stored_entry_identity++; break;
	case 7U: current_source.source_swap_entry = swp_entry(3U, 39U).val;
		 break;
	case 8U: sidecar.slots[5].owner_token++; break;
	case 9U: context.target = &replacement_target; break;
	case 10U: context.authority.gc_destination++; break;
	case 11U: original_extent[original_write.payload_offset] ^= 1U;
		  break;
	case 12U: original_extent[0] = 1U; break;
	case 13U: chain->current_record.source.original_sha256[0] ^= 1U;
		  break;
	default: break;
	}
	error = swapz_round039_dm_chain_gc_prepare(
		&context, &sidecar, &current_source, chain,
		gc_ticket, relocated_block, relocated_sequence,
		original_extent, extent_bytes);
	if (fault >= 5U && fault <= 13U) {
		assert(error < 0);
		assert(chain->hypothetical_write_acks == 1U);
		assert(chain->current_record.fake_start_block == original_block);
		goto complete;
	}
	assert(error == 0);
	assert(chain->callback_references == 1U);
	/* The fake new lower image is a separate postheader destination. */
	memcpy(relocated_extent, chain->staged_relocation, extent_bytes);
	gc_event.chain = chain;
	gc_event.gc_ticket = gc_ticket;
	gc_event.readback = relocated_extent;
	gc_event.completed_bytes = extent_bytes;
	gc_event.capacity = extent_bytes;
	if (fault == 14U)
		gc_event.completed_bytes--;
	if (fault == 15U)
		gc_event.error = 1;
	if (fault == 16U)
		gc_event.error = -EIO;
	if (fault == 17U)
		relocated_extent[0] ^= 1U;
	if (fault == 18U)
		assert(swapz_round039_dm_chain_cancel_gc(
			&context, chain) == 0);
	context.ordered_owner = 0;
	round039_dispatch_gc(&gc_event);
	context.ordered_owner = 1;
	assert(swapz_round039_dm_chain_gc_fake_callback(
		chain, gc_ticket, 0, extent_bytes,
		relocated_extent, extent_bytes) == -ESTALE);
	if (fault >= 14U && fault <= 18U) {
		assert(gc_event.result == (fault == 18U ? -ESTALE : -EIO));
		if (fault == 18U)
			assert(chain->phase == SWAPZ_ROUND039_CHAIN_ABORTED);
		else
			assert(swapz_round039_dm_chain_gc_finish(
				&context, &sidecar, &current_source,
				chain, gc_ticket) == -EIO);
		assert(chain->current_record.fake_start_block == original_block);
		goto complete;
	}
	assert(gc_event.result == 0);
	if (fault == 19U)
		current_source.source_slot_epoch++;
	if (fault == 20U)
		context.authority.gc_destination++;
	if (fault == 21U)
		context.target = &replacement_target;
	if (fault == 22U)
		sidecar.slots[5].owner_token++;
	if (fault >= 19U && fault <= 22U) {
		assert(swapz_round039_dm_chain_gc_finish(
			&context, &sidecar, &current_source,
			chain, gc_ticket) == -ESTALE);
		assert(chain->current_record.fake_start_block == original_block);
		goto complete;
	}
	assert(swapz_round039_dm_chain_gc_finish(
		&context, &sidecar, &current_source, chain, gc_ticket) == 0);
	assert(chain->gc_generation == 2U);
	assert(chain->current_record.fake_start_block == relocated_block);
	assert(chain->current_record.fake_extent_sequence ==
	       relocated_sequence);
	assert(chain->hypothetical_write_acks == 1U);
	assert(write_publication.hypothetical_ack_count == 1U);
	assert(!context.maps[5].valid);
	assert(swapz_round039_dm_chain_gc_finish(
		&context, &sidecar, &current_source,
		chain, gc_ticket) == -ESTALE);
	captured_generation = chain->gc_generation;
	if (fault == 23U)
		captured_generation--;
	if (fault == 24U)
		current_source.source_swap_entry = swp_entry(3U, 39U).val;
	if (fault == 25U)
		current_source.source_slot_epoch++;
	error = swapz_round039_dm_chain_read_prepare(
		&context, &sidecar, &current_source, chain,
		captured_generation, read_ticket, read_mailbox);
	if (fault >= 23U && fault <= 25U) {
		assert(error == -ESTALE);
		goto complete;
	}
	assert(error == 0);
	assert(swapz_round038_dm_read_submit(
		&context, &sidecar, &chain->current_publication,
		&current_source, chain->current_record.fake_extent_sequence,
		read_ticket, read_mailbox) == 0);
	read_event.mailbox = read_mailbox;
	read_event.ticket = read_ticket;
	read_event.lower_image = relocated_extent;
	read_event.completed_bytes = extent_bytes;
	read_event.image_capacity = extent_bytes;
	if (fault == 26U)
		read_event.completed_bytes--;
	if (fault == 27U)
		read_event.lower_error = -EIO;
	if (fault == 28U)
		read_event.lower_error = 1;
	if (fault == 29U)
		relocated_extent[chain->current_record.payload_offset] ^= 1U;
	if (fault == 30U)
		relocated_extent[0] = 1U;
	context.ordered_owner = 0;
	round038_dispatch_read(&read_event);
	context.ordered_owner = 1;
	assert(swapz_round038_dm_read_fake_callback(
		read_mailbox, read_ticket, 0, extent_bytes,
		relocated_extent, extent_bytes) == -ESTALE);
	if (fault >= 26U && fault <= 28U)
		assert(read_event.result == -EIO);
	else
		assert(read_event.result == 0);
	/* Revalidation AFTER independently scheduled callback, BEFORE the
	 * mock upper 4096-byte copy, must reject any changed identity/map.
	 */
	switch (fault) {
	case 31U: current_source.stored_entry_identity++; break;
	case 32U: context.target = &replacement_target; break;
	case 33U: chain->gc_generation++; break;
	case 34U: chain->current_record.fake_extent_sequence++; break;
	case 35U: context.authority.gc_destination++; break;
	case 36U: sidecar.slots[5].owner_token++; break;
	case 37U: current_source.codec++; break;
	case 38U: current_source.representation_version++; break;
	case 39U: chain->current_record.source.compressed_length = 0U; break;
	case 40U:
		chain->current_record.source.compressed_length =
			SWAPZ_MAX_COMPRESSED + 1U;
		break;
	case 41U: chain->current_record.source.original_sha256[0] ^= 1U;
		  break;
	case 42U:
		/* Recomputed compressed CRC cannot invent a STORE SHA. */
		memset(read_mailbox->fake_lower_image +
		       chain->current_record.payload_offset, 0,
		       chain->current_record.source.compressed_length);
		read_mailbox->record.source.compressed_crc32c =
			swapz_crc32c_bytes(
				read_mailbox->fake_lower_image +
				chain->current_record.payload_offset,
				chain->current_record.source.compressed_length);
		chain->current_record.source.compressed_crc32c =
			read_mailbox->record.source.compressed_crc32c;
		current_source.compressed_crc32c =
			read_mailbox->record.source.compressed_crc32c;
		break;
	case 43U:
		/* GC map is not permitted to slide back to the old extent. */
		chain->current_record.fake_start_block = original_block;
		break;
	case 44U:
		assert(swapz_round038_dm_read_cancel(
			&context, read_ticket, read_mailbox) == 0);
		break;
	default: break;
	}
	error = swapz_round039_dm_chain_read_finish(
		&context, &sidecar, &current_source, chain,
		captured_generation, read_ticket, mock_read, read_mailbox);
	if (fault == 0U) {
		assert(error == 0);
		assert(!memcmp(mock_read, original, SWAPZ_BLOCK_BYTES));
		assert(chain->mock_read_publications == 1U);
		assert(chain->hypothetical_write_acks == 1U);
		assert(swapz_round039_dm_chain_read_finish(
			&context, &sidecar, &current_source, chain,
			captured_generation, read_ticket, mock_read,
			read_mailbox) == -ESTALE);
	} else {
		assert(error < 0);
		round036_check_sentinel(mock_read, sizeof(mock_read), 0xa5U);
		/* Early generation/GC rejection leaves a private callback result;
		 * cancel that mailbox before its final caller-owned release.
		 */
		if (read_mailbox->phase == SWAPZ_ROUND038_FAKE_READ_OK ||
		    read_mailbox->phase == SWAPZ_ROUND038_FAKE_READ_ERROR)
			assert(swapz_round038_dm_read_cancel(
				&context, read_ticket, read_mailbox) == 0);
	}
complete:
	for (byte_index = 0U; byte_index < SWAPZ_BLOCK_BYTES; ++byte_index)
		assert(lower_area[byte_index] == 0x36U);
	if (fault != 0U)
		round036_check_sentinel(mock_read, sizeof(mock_read), 0xa5U);
	assert(transaction.upper_write_ack_count == 0U);
	assert(lower_reads == 0 && lower_writes == 0);
	assert(write_mailbox->callback_references == 0U);
	assert(read_mailbox->callback_references == 0U);
	assert(chain->callback_references == 0U);
	assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
		&context, &sidecar) == 0);
	/* The host owns every private witness, fake lower byte and mock page.
	 * Retire them only after both async callback references are drained.
	 */
	swapz_round039_dm_chain_scrub_relocation(chain);
	memzero_explicit(&chain->current_record, sizeof(chain->current_record));
	memzero_explicit(&chain->current_publication,
			 sizeof(chain->current_publication));
	memzero_explicit(&original_write, sizeof(original_write));
	memzero_explicit(&current_source, sizeof(current_source));
	memzero_explicit(mock_write, sizeof(mock_write));
	memzero_explicit(mock_read, sizeof(mock_read));
	memzero_explicit(lower_area, 16U * SWAPZ_BLOCK_BYTES);
	round036_check_zeros((const swapz_u8 *)&chain->current_record,
			     sizeof(chain->current_record));
	round036_check_zeros((const swapz_u8 *)&chain->current_publication,
			     sizeof(chain->current_publication));
	round036_check_zeros(chain->staged_relocation,
			     sizeof(chain->staged_relocation));
	assert(pthread_mutex_destroy(&write_mailbox->callback_lock) == 0);
	assert(pthread_mutex_destroy(&read_mailbox->callback_lock) == 0);
	assert(pthread_mutex_destroy(&chain->gc_callback_lock) == 0);
	assert(pthread_mutex_destroy(&chain->gc_verifier.callback_lock) == 0);
	free(write_mailbox);
	free(read_mailbox);
	free(chain);
	free(lower_area);
}

int main(void)
{
	unsigned int extent_blocks;
	unsigned int fault;

	assert(round038_fixture_main() == 0);
	for (extent_blocks = 1U; extent_blocks <= 4U; extent_blocks *= 2U)
		for (fault = 0U; fault <= 44U; ++fault)
			round039_test_chain(extent_blocks, fault);
	puts("ROUND039_ACTUAL_DM_WRITE_GC_READ_ORIGINAL_4096_SHA_NO_DUPLICATE_ACK_NO_GO_PASS");
	return 0;
}
