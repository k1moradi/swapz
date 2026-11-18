/*
 * Round040 host executes ACTUAL source-extracted production DM C:
 * TWO different original STORED source objects at ONE original swap slot,
 * separate independently scheduled WRITE/GC/READ fake callbacks and
 * private 4/8/16KiB afterheader payload images. Never real block I/O.
 */
/* ROUND040_EXTRACT_ALL_PRIOR_SOURCE */
/* ROUND040_EXTRACT_NEW_PRODUCTION_C */

static void round040_check_header(const swapz_u8 *fake_lower)
{
	unsigned int byte_index;

	for (byte_index = 0U; byte_index < SWAPZ_BLOCK_BYTES; ++byte_index)
		assert(fake_lower[byte_index] == 0x36U);
}

static void round040_test_reissue(unsigned int extent_blocks,
				 unsigned int fault)
{
	struct swapz_dm context = { 0 };
	struct dm_target original_target = { .len = 32U * SWAPZ_SECTORS };
	struct dm_target other_target = { .len = 32U * SWAPZ_SECTORS };
	struct swapz_zswap_admission_transaction original_transaction = { 0 };
	struct swapz_zswap_admission_transaction new_transaction = { 0 };
	struct swapz_round030_dm_volatile_descriptor descriptor = { 0 };
	struct swapz_round031_dm_sidecar sidecar = { 0 };
	struct swapz_round037_dm_async_mailbox *old_write =
		calloc(1U, sizeof(*old_write));
	struct swapz_round037_dm_async_mailbox *new_write =
		calloc(1U, sizeof(*new_write));
	struct swapz_round038_dm_read_mailbox *old_read =
		calloc(1U, sizeof(*old_read));
	struct swapz_round038_dm_read_mailbox *new_read =
		calloc(1U, sizeof(*new_read));
	struct swapz_round039_dm_chain *old_chain =
		calloc(1U, sizeof(*old_chain));
	struct swapz_round039_dm_chain *new_chain =
		calloc(1U, sizeof(*new_chain));
	struct swapz_round040_dm_reissue_witness *reissue =
		calloc(1U, sizeof(*reissue));
	struct swapz_round038_dm_read_record old_record = { 0 };
	struct swapz_round038_dm_read_record new_record = { 0 };
	struct swapz_round032_dm_owned_view_v1 old_source = { 0 };
	struct swapz_round032_dm_owned_view_v1 new_source = { 0 };
	struct bio_vec original_vector = {
		.bv_page = original, .bv_offset = 0U, .bv_len = SWAPZ_BLOCK_BYTES
	};
	struct bio original_bio = {
		.lifetime_pinned = true,
		.full_uncompressed_4096_swap_write = true,
		.bi_iter = { .bi_sector = 5U * SWAPZ_SECTORS,
			     .bi_size = SWAPZ_BLOCK_BYTES },
		.bi_io_vec = &original_vector, .bi_bdev = &original_target,
		.bi_vcnt = 0U, .bi_opf = REQ_OP_WRITE | REQ_SWAP,
		.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK
	};
	struct bio_vec new_vector = { 0 };
	struct bio new_bio = original_bio;
	struct round037_callback_event old_write_event = { 0 };
	struct round037_callback_event new_write_event = { 0 };
	struct round038_read_event old_read_event = { 0 };
	struct round038_read_event new_read_event = { 0 };
	struct round039_gc_event old_gc_event = { 0 };
	struct round039_gc_event new_gc_event = { 0 };
	swapz_u8 *new_original = calloc(1U, SWAPZ_BLOCK_BYTES);
	swapz_u8 *fake_lower = calloc(32U, SWAPZ_BLOCK_BYTES);
	swapz_u8 new_compressed[SWAPZ_MAX_COMPRESSED];
	swapz_u8 mock_old_write[SWAPZ_BLOCK_BYTES];
	swapz_u8 mock_new_write[SWAPZ_BLOCK_BYTES];
	swapz_u8 mock_old_read[SWAPZ_BLOCK_BYTES];
	swapz_u8 mock_new_read[SWAPZ_BLOCK_BYTES];
	const swapz_u64 original_entry = swp_entry(2U, 39U).val;
	const swapz_u64 area_cookie = 0xabc711U;
	const swapz_u64 old_ticket = 4001U;
	const swapz_u64 new_ticket = 4002U;
	const swapz_u64 old_read_ticket = 6001U;
	const swapz_u64 new_read_ticket = 9001U;
	const swapz_u64 old_gc_ticket = 7001U;
	const swapz_u64 new_gc_ticket = 8001U;
	const swapz_u32 extent_bytes = extent_blocks * SWAPZ_BLOCK_BYTES;
	const swapz_u32 old_block = 2U;
	const swapz_u32 new_block = 8U;
	const swapz_u32 new_gc_block = 14U;
	const swapz_u32 old_gc_block = 20U;
	const swapz_u32 old_sequence = 77U;
	const swapz_u32 new_sequence = 78U;
	const swapz_u32 new_gc_sequence = 80U;
	swapz_u8 *old_extent;
	swapz_u8 *new_extent;
	swapz_u8 *new_gc_extent;
	swapz_u8 *old_gc_extent;
	swapz_u32 old_length;
	swapz_u32 new_length;
	swapz_u64 current_gc_generation;
	bool early_old_ack = fault == 1U || fault == 2U;
	bool new_write_rejected = fault >= 7U && fault <= 22U;
	bool new_gc_rejected = fault >= 25U && fault <= 34U;
	bool new_read_rejected = (fault >= 35U && fault <= 49U) ||
		fault == 51U;
	int result;

	assert(old_write && new_write && old_read && new_read &&
	       old_chain && new_chain && reissue && new_original && fake_lower);
	old_extent = fake_lower + (1U + old_block) * SWAPZ_BLOCK_BYTES;
	new_extent = fake_lower + (1U + new_block) * SWAPZ_BLOCK_BYTES;
	new_gc_extent = fake_lower + (1U + new_gc_block) * SWAPZ_BLOCK_BYTES;
	old_gc_extent = fake_lower + (1U + old_gc_block) * SWAPZ_BLOCK_BYTES;
	old_length = (swapz_u32)LZ4_compress_default(
		(const char *)original, (char *)compressed,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
	assert(old_length >= 1U && old_length <= SWAPZ_MAX_COMPRESSED);
	initial_state(&context, &original_transaction, &descriptor,
		      extent_bytes, old_length);
	context.authority.physical_blocks = 32U;
	context.target = &original_target;
	assert(swapz_round031_dm_sidecar_init(&context, &sidecar) == 0);
	memset(new_original, 0x5a, SWAPZ_BLOCK_BYTES);
	new_original[0] = 0x33U;
	new_original[SWAPZ_BLOCK_BYTES - 1U] = 0x71U;
	new_length = (swapz_u32)LZ4_compress_default(
		(const char *)new_original, (char *)new_compressed,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
	assert(new_length >= 1U && new_length <= SWAPZ_MAX_COMPRESSED);
	assert(old_length != new_length ||
	       memcmp(compressed, new_compressed, old_length));
	memset(fake_lower, 0, 32U * SWAPZ_BLOCK_BYTES);
	memset(fake_lower, 0x36, SWAPZ_BLOCK_BYTES);
	memset(disk_data, 0, sizeof(disk_data));
	memset(disk_data, 0x36, SWAPZ_BLOCK_BYTES);
	memset(mock_old_write, 0xa5, sizeof(mock_old_write));
	memset(mock_new_write, 0xa5, sizeof(mock_new_write));
	memset(mock_old_read, 0xa5, sizeof(mock_old_read));
	memset(mock_new_read, 0xa5, sizeof(mock_new_read));
	source_lz4_length = (u16)old_length;
	memcpy(source_lz4_bytes, compressed, old_length);
	original_provider_view = (struct swapz_ci_lz4_owned_view_v1) {
		.source_swap_entry = original_entry,
		.source_slot_epoch = original_transaction.record.store_generation,
		.stored_entry_identity =
			original_transaction.record.stored_entry_identity,
		.compressed_crc32c =
			original_transaction.record.compressed_crc32c,
		.compressed_length = (u16)old_length,
		.decoded_length = SWAPZ_BLOCK_BYTES,
		.representation_version = 1U, .codec = 1U
	};
	memcpy(original_provider_view.original_sha256,
	       original_transaction.record.original_sha256, 32U);
	provider_calls = 0;
	injected_provider_errno = 0;
	swapz_round037_dm_async_initialize(old_write);
	swapz_round037_dm_async_initialize(new_write);
	swapz_round038_dm_read_initialize(old_read);
	swapz_round038_dm_read_initialize(new_read);
	swapz_round039_dm_chain_initialize(old_chain);
	swapz_round039_dm_chain_initialize(new_chain);
	swapz_round040_dm_reissue_initialize(reissue);

	/* A owns its staged compressed source and completion independently. */
	assert(swapz_round037_dm_async_prepare(
		&context, &original_bio, &sidecar, &original_transaction,
		original_entry, 0U, old_ticket, old_block,
		old_sequence, old_write) == 0);
	assert(swapz_round038_dm_read_snapshot_write(
		&context, &old_write->ledger, &old_record) == 0);
	old_source = old_write->ledger.source;
	memcpy(old_extent, old_write->staged_extent, extent_bytes);
	assert(swapz_round040_dm_reissue_arm(
		&context, reissue, 0U, &old_record, &old_source,
		area_cookie, old_ticket) == 0);
	assert(swapz_round037_dm_async_submit(
		&context, old_write, old_ticket) == 0);
	old_write_event.mailbox = old_write;
	old_write_event.incarnation_ticket = old_ticket;
	old_write_event.readback = old_extent;
	old_write_event.completed_bytes = extent_bytes;
	old_write_event.readback_bytes = extent_bytes;

	/* The already-completed A is a valid historical ACK; B must not
	 * retrospectively retract it, nor double-count it on B reissue.
	 */
	if (early_old_ack) {
		context.ordered_owner = 0;
		round037_dispatch_fake_callback(&old_write_event);
		context.ordered_owner = 1;
		assert(old_write_event.result == 0);
		assert(swapz_round040_dm_reissue_finish_write(
			&context, &sidecar, reissue, 0U, area_cookie,
			&old_source, old_write, mock_old_write) == 0);
		assert(reissue->hypothetical_ack_count[0] == 1U);
		assert(!memcmp(mock_old_write, original, SWAPZ_BLOCK_BYTES));
		assert(swapz_round039_dm_chain_accept_write(
			&context, &sidecar, &old_source, &old_record,
			&reissue->publication[0], old_chain) == 0);
		if (fault == 1U) {
			/* A GC is in-flight when B becomes the current object. */
			assert(swapz_round039_dm_chain_gc_prepare(
				&context, &sidecar, &old_source, old_chain,
				old_gc_ticket, old_gc_block, 100U,
				old_extent, extent_bytes) == 0);
			memcpy(old_gc_extent, old_chain->staged_relocation,
			       extent_bytes);
			old_gc_event.chain = old_chain;
			old_gc_event.gc_ticket = old_gc_ticket;
			old_gc_event.readback = old_gc_extent;
			old_gc_event.completed_bytes = extent_bytes;
			old_gc_event.capacity = extent_bytes;
		} else {
			/* A asynchronous READ callback will arrive after B. */
			assert(swapz_round038_dm_read_prepare(
				&context, &sidecar, &reissue->publication[0],
				&old_source, &old_record, old_sequence,
				old_read_ticket, old_read) == 0);
			assert(swapz_round038_dm_read_submit(
				&context, &sidecar, &reissue->publication[0],
				&old_source, old_sequence,
				old_read_ticket, old_read) == 0);
			old_read_event.mailbox = old_read;
			old_read_event.ticket = old_read_ticket;
			old_read_event.lower_image = old_extent;
			old_read_event.completed_bytes = extent_bytes;
			old_read_event.image_capacity = extent_bytes;
		}
	}

	/* Reissue B to exactly the same FULL original type+offset with
	 * a different allocator epoch, STORE object, compressed CRC and
	 * independent original full 4096 SHA (not from forged read bytes).
	 */
	new_transaction = original_transaction;
	new_transaction.record.store_generation++;
	new_transaction.record.stored_entry_identity++;
	new_transaction.record.compressed_crc32c =
		swapz_crc32c_bytes(new_compressed, new_length);
	new_transaction.record.compressed_length = new_length;
	new_transaction.compressed_payload_offset = extent_bytes - new_length;
	assert(swapz_zswap_import_sha256(
		new_original, new_transaction.record.original_sha256) == 0);
	new_vector = (struct bio_vec) {
		.bv_page = new_original, .bv_offset = 0U,
		.bv_len = SWAPZ_BLOCK_BYTES
	};
	new_bio.bi_io_vec = &new_vector;
	original_provider_view.source_slot_epoch =
		new_transaction.record.store_generation;
	original_provider_view.stored_entry_identity =
		new_transaction.record.stored_entry_identity;
	original_provider_view.compressed_crc32c =
		new_transaction.record.compressed_crc32c;
	original_provider_view.compressed_length = (u16)new_length;
	memcpy(original_provider_view.original_sha256,
	       new_transaction.record.original_sha256, 32U);
	source_lz4_length = (u16)new_length;
	memcpy(source_lz4_bytes, new_compressed, new_length);
	assert(swapz_round037_dm_async_prepare(
		&context, &new_bio, &sidecar, &new_transaction,
		original_entry, 0U, new_ticket, new_block,
		new_sequence, new_write) == 0);
	assert(swapz_round038_dm_read_snapshot_write(
		&context, &new_write->ledger, &new_record) == 0);
	new_source = new_write->ledger.source;
	assert(new_source.source_swap_entry == old_source.source_swap_entry);
	assert(new_source.source_slot_epoch != old_source.source_slot_epoch);
	assert(new_source.stored_entry_identity !=
	       old_source.stored_entry_identity);
	assert(memcmp(new_source.original_sha256,
		      old_source.original_sha256, 32U));
	memcpy(new_extent, new_write->staged_extent, extent_bytes);
	assert(swapz_round040_dm_reissue_arm(
		&context, reissue, 1U, &new_record, &new_source,
		area_cookie + 1U, new_ticket) == -ESTALE);
	{
		/* The same original full type+offset may NOT turn B's
		 * different plaintext into A's old epoch/STORE incarnation.
		 */
		struct swapz_round038_dm_read_record alias_record = new_record;
		struct swapz_round032_dm_owned_view_v1 alias_source = new_source;

		alias_source.source_slot_epoch = old_source.source_slot_epoch;
		alias_source.stored_entry_identity =
			old_source.stored_entry_identity;
		alias_record.source = alias_source;
		assert(swapz_round040_dm_reissue_arm(
			&context, reissue, 1U, &alias_record, &alias_source,
			area_cookie, new_ticket) == -ESTALE);
	}
	assert(swapz_round040_dm_reissue_arm(
		&context, reissue, 1U, &new_record, &new_source,
		area_cookie, new_ticket) == 0);
	assert(reissue->active_candidate == 1U);
	assert(swapz_round037_dm_async_submit(
		&context, new_write, new_ticket) == 0);
	new_write_event.mailbox = new_write;
	new_write_event.incarnation_ticket = new_ticket;
	new_write_event.readback = new_extent;
	new_write_event.completed_bytes = extent_bytes;
	new_write_event.readback_bytes = extent_bytes;

	if (fault == 3U) old_write_event.fake_error = -EIO;
	if (fault == 4U) old_write_event.fake_error = 1;
	if (fault == 5U) old_write_event.completed_bytes--;
	if (fault == 6U)
		assert(swapz_round037_dm_async_cancel(
			&context, old_write, old_ticket) == 0);
	if (fault == 7U) new_write_event.fake_error = -EIO;
	if (fault == 8U) new_write_event.fake_error = 1;
	if (fault == 9U) new_write_event.completed_bytes--;
	if (fault == 10U)
		assert(swapz_round037_dm_async_cancel(
			&context, new_write, new_ticket) == 0);
	if (fault == 19U) new_extent[0] = 1U;
	if (fault == 20U)
		new_extent[new_record.payload_offset] ^= 1U;

	/* B lower completion arrives before A; no witness is accessed by
	 * either separately scheduled callback thread.
	 */
	context.ordered_owner = 0;
	round037_dispatch_fake_callback(&new_write_event);
	context.ordered_owner = 1;
	if (fault >= 7U && fault <= 10U)
		assert(new_write_event.result == (fault == 10U ?
						 -ESTALE : -EIO));
	else
		assert(new_write_event.result == 0);
	switch (fault) {
	case 12U: new_source.source_swap_entry = swp_entry(3U, 39U).val;
		  break;
	case 13U: new_source.source_slot_epoch++; break;
	case 14U: new_source.stored_entry_identity++; break;
	case 15U: new_source.original_sha256[0] ^= 1U; break;
	case 16U: context.target = &other_target; break;
	case 17U: context.authority.gc_destination++; break;
	case 18U: sidecar.slots[5].owner_token++; break;
	case 21U: new_source.compressed_crc32c++; break;
	case 22U: new_source.compressed_length = 0U; break;
	default: break;
	}
	result = swapz_round040_dm_reissue_finish_write(
		&context, &sidecar, reissue, 1U,
		fault == 11U ? area_cookie + 1U : area_cookie,
		&new_source, new_write, mock_new_write);
	if (new_write_rejected) {
		assert(result < 0);
		assert(reissue->hypothetical_ack_count[1] == 0U);
		round036_check_sentinel(mock_new_write,
				       sizeof(mock_new_write), 0xa5U);
		assert(!context.maps[5].valid);
		if (new_write->phase == SWAPZ_ROUND037_LOWER_COMPLETION_OK ||
		    new_write->phase == SWAPZ_ROUND037_LOWER_COMPLETION_ERROR)
			assert(swapz_round037_dm_async_cancel(
				&context, new_write, new_ticket) == 0);
		goto drain_old;
	}
	assert(result == 0);
	assert(reissue->hypothetical_ack_count[1] == 1U);
	assert(!memcmp(mock_new_write, new_original, SWAPZ_BLOCK_BYTES));
	assert(swapz_round040_dm_reissue_finish_write(
		&context, &sidecar, reissue, 1U, area_cookie,
		&new_source, new_write, mock_new_write) == -ESTALE);
	assert(swapz_round039_dm_chain_accept_write(
		&context, &sidecar, &new_source, &new_record,
		&reissue->publication[1], new_chain) == 0);
	assert(!context.maps[5].valid);

drain_old:
	if (!early_old_ack) {
		if (fault == 50U)
			context.accepting = false;
		context.ordered_owner = 0;
		round037_dispatch_fake_callback(&old_write_event);
		context.ordered_owner = 1;
		if (fault == 50U)
			context.accepting = true;
		assert(old_write_event.result ==
		       (fault == 6U ? -ESTALE :
			(fault >= 3U && fault <= 5U ? -EIO : 0)));
		assert(swapz_round040_dm_reissue_finish_write(
			&context, &sidecar, reissue, 0U, area_cookie,
			&old_source, old_write, mock_old_write) == -ESTALE);
		assert(swapz_round037_dm_async_cancel(
			&context, old_write, old_ticket) == 0 ||
		       old_write->phase == SWAPZ_ROUND037_EXPIRED);
		assert(reissue->hypothetical_ack_count[0] == 0U);
		round036_check_sentinel(mock_old_write,
				       sizeof(mock_old_write), 0xa5U);
	} else if (fault == 1U && !new_write_rejected) {
		context.ordered_owner = 0;
		round039_dispatch_gc(&old_gc_event);
		context.ordered_owner = 1;
		assert(old_gc_event.result == 0);
		assert(swapz_round040_dm_reissue_gc_finish(
			&context, &sidecar, &old_source, reissue,
			0U, area_cookie, old_chain, old_gc_ticket) == -ESTALE);
		assert(swapz_round039_dm_chain_cancel_gc(
			&context, old_chain) == 0);
	} else if (fault == 2U && !new_write_rejected) {
		context.ordered_owner = 0;
		round038_dispatch_read(&old_read_event);
		context.ordered_owner = 1;
		assert(old_read_event.result == 0);
		assert(swapz_round040_dm_reissue_read_finish(
			&context, &sidecar, &old_source, reissue,
			0U, area_cookie, old_chain, 1U, old_read_ticket,
			mock_old_read, old_read) == -ESTALE);
		round036_check_sentinel(mock_old_read,
				       sizeof(mock_old_read), 0xa5U);
		assert(swapz_round038_dm_read_cancel(
			&context, old_read_ticket, old_read) == 0);
	}
	if (new_write_rejected)
		goto complete;
	if (fault == 23U) {
		assert(swapz_round037_dm_async_fake_callback(
			old_write, old_ticket, 0, extent_bytes,
			old_extent, extent_bytes) == -ESTALE);
	}
	if (fault == 24U) {
		assert(swapz_round037_dm_async_prepare(
			&context, &original_bio, &sidecar, &original_transaction,
			original_entry, 0U, old_ticket, old_block,
			old_sequence, old_write) == -EBUSY);
	}

	/* A GC cannot replace B's current mock record, even if the old
	 * callback completes. B's actual Round039 CRC/LZ4/SHA GC is reused.
	 */
	assert(swapz_round039_dm_chain_gc_prepare(
		&context, &sidecar, &new_source, new_chain,
		new_gc_ticket, new_gc_block, new_gc_sequence,
		new_extent, extent_bytes) == 0);
	memcpy(new_gc_extent, new_chain->staged_relocation, extent_bytes);
	new_gc_event.chain = new_chain;
	new_gc_event.gc_ticket = new_gc_ticket;
	new_gc_event.readback = new_gc_extent;
	new_gc_event.completed_bytes = extent_bytes;
	new_gc_event.capacity = extent_bytes;
	if (fault == 25U) new_gc_event.completed_bytes--;
	if (fault == 26U) new_gc_event.error = 1;
	if (fault == 27U) new_gc_event.error = -EIO;
	if (fault == 28U) new_gc_extent[0] = 1U;
	if (fault == 29U)
		assert(swapz_round039_dm_chain_cancel_gc(
			&context, new_chain) == 0);
	context.ordered_owner = 0;
	round039_dispatch_gc(&new_gc_event);
	context.ordered_owner = 1;
	if (fault >= 25U && fault <= 29U)
		assert(new_gc_event.result == (fault == 29U ?
					      -ESTALE : -EIO));
	else
		assert(new_gc_event.result == 0);
	if (fault == 30U) context.authority.gc_destination++;
	if (fault == 31U) context.target = &other_target;
	if (fault == 32U) new_source.source_slot_epoch++;
	if (fault == 34U) new_source.original_sha256[0] ^= 1U;
	result = swapz_round040_dm_reissue_gc_finish(
		&context, &sidecar, &new_source, reissue, 1U,
		fault == 33U ? area_cookie + 1U : area_cookie,
		new_chain, new_gc_ticket);
	if (new_gc_rejected) {
		assert(result < 0);
		assert(new_chain->current_record.fake_start_block == new_block);
		if (new_chain->phase == SWAPZ_ROUND039_CHAIN_GC_CALLBACK_OK)
			assert(swapz_round039_dm_chain_cancel_gc(
				&context, new_chain) == 0);
		goto complete;
	}
	assert(result == 0);
	assert(new_chain->gc_generation == 2U);
	assert(new_chain->current_record.fake_start_block == new_gc_block);
	assert(reissue->hypothetical_ack_count[1] == 1U);
	assert(!context.maps[5].valid);
	current_gc_generation = new_chain->gc_generation;
	assert(swapz_round039_dm_chain_read_prepare(
		&context, &sidecar, &new_source, new_chain,
		current_gc_generation, new_read_ticket, new_read) == 0);
	assert(swapz_round038_dm_read_submit(
		&context, &sidecar, &new_chain->current_publication,
		&new_source, new_gc_sequence, new_read_ticket, new_read) == 0);
	new_read_event.mailbox = new_read;
	new_read_event.ticket = new_read_ticket;
	new_read_event.lower_image = new_gc_extent;
	new_read_event.completed_bytes = extent_bytes;
	new_read_event.image_capacity = extent_bytes;
	if (fault == 35U) new_read_event.completed_bytes--;
	if (fault == 36U) new_read_event.lower_error = -EIO;
	if (fault == 37U) new_read_event.lower_error = 1;
	if (fault == 38U)
		new_gc_extent[new_chain->current_record.payload_offset] ^= 1U;
	if (fault == 39U) new_gc_extent[0] = 1U;
	context.ordered_owner = 0;
	round038_dispatch_read(&new_read_event);
	context.ordered_owner = 1;
	if (fault >= 35U && fault <= 37U)
		assert(new_read_event.result == -EIO);
	else
		assert(new_read_event.result == 0);
	if (fault == 51U) {
		/* A REAL second source-extracted Round039 fake GC moves B
		 * again AFTER the old READ callback, BEFORE output commit.
		 * No generation-only synthetic mutation can substitute for
		 * the completed new extent stage/callback/map transition.
		 */
		struct round039_gc_event second_gc_event = { 0 };

		assert(swapz_round039_dm_chain_gc_prepare(
			&context, &sidecar, &new_source, new_chain,
			new_gc_ticket + 1U, old_gc_block,
			new_gc_sequence + 1U,
			new_gc_extent, extent_bytes) == 0);
		memcpy(old_gc_extent, new_chain->staged_relocation,
		       extent_bytes);
		second_gc_event.chain = new_chain;
		second_gc_event.gc_ticket = new_gc_ticket + 1U;
		second_gc_event.readback = old_gc_extent;
		second_gc_event.completed_bytes = extent_bytes;
		second_gc_event.capacity = extent_bytes;
		context.ordered_owner = 0;
		round039_dispatch_gc(&second_gc_event);
		context.ordered_owner = 1;
		assert(second_gc_event.result == 0);
		assert(swapz_round040_dm_reissue_gc_finish(
			&context, &sidecar, &new_source, reissue, 1U,
			area_cookie, new_chain, new_gc_ticket + 1U) == 0);
		assert(new_chain->gc_generation ==
		       current_gc_generation + 1U);
		assert(new_chain->current_record.fake_start_block ==
		       old_gc_block);
		assert(new_chain->mock_read_publications == 0U);
	}
	switch (fault) {
	case 40U: new_source.source_slot_epoch++; break;
	case 41U: new_source.stored_entry_identity++; break;
	case 42U: new_source.original_sha256[0] ^= 1U; break;
	case 43U: new_chain->gc_generation++; break;
	case 44U:
		/* Forging compressed CRC cannot forge original STORE SHA. */
		memset(new_read->fake_lower_image +
		       new_chain->current_record.payload_offset, 0,
		       new_chain->current_record.source.compressed_length);
		new_read->record.source.compressed_crc32c =
			swapz_crc32c_bytes(
				new_read->fake_lower_image +
				new_chain->current_record.payload_offset,
				new_chain->current_record.source.compressed_length);
		new_chain->current_record.source.compressed_crc32c =
			new_read->record.source.compressed_crc32c;
		new_source.compressed_crc32c =
			new_read->record.source.compressed_crc32c;
		break;
	case 45U: context.target = &other_target; break;
	case 46U: new_source.source_swap_entry = swp_entry(3U, 39U).val;
		  break;
	case 47U: new_source.codec++; break;
	case 48U: new_chain->current_record.source.compressed_length = 0U;
		  break;
	case 49U:
		new_chain->current_record.source.compressed_length =
			SWAPZ_MAX_COMPRESSED + 1U;
		break;
	default: break;
	}
	result = swapz_round040_dm_reissue_read_finish(
		&context, &sidecar, &new_source, reissue, 1U, area_cookie,
		new_chain, current_gc_generation, new_read_ticket,
		mock_new_read, new_read);
	if (new_read_rejected) {
		assert(result < 0);
		round036_check_sentinel(mock_new_read,
				       sizeof(mock_new_read), 0xa5U);
		if (new_read->phase == SWAPZ_ROUND038_FAKE_READ_OK ||
		    new_read->phase == SWAPZ_ROUND038_FAKE_READ_ERROR)
			assert(swapz_round038_dm_read_cancel(
				&context, new_read_ticket, new_read) == 0);
	} else {
		assert(result == 0);
		assert(!memcmp(mock_new_read, new_original, SWAPZ_BLOCK_BYTES));
		assert(new_chain->mock_read_publications == 1U);
		assert(swapz_round040_dm_reissue_read_finish(
			&context, &sidecar, &new_source, reissue, 1U,
			area_cookie, new_chain, current_gc_generation,
			new_read_ticket, mock_new_read, new_read) == -ESTALE);
	}
complete:
	round040_check_header(fake_lower);
	assert(!context.maps[5].valid);
	assert(original_transaction.upper_write_ack_count == 0U);
	assert(new_transaction.upper_write_ack_count == 0U);
	assert(lower_reads == 0 && lower_writes == 0);
	assert(old_write->callback_references == 0U);
	assert(new_write->callback_references == 0U);
	assert(old_read->callback_references == 0U);
	assert(new_read->callback_references == 0U);
	assert(old_chain->callback_references == 0U);
	assert(new_chain->callback_references == 0U);
	assert(swapz_round040_dm_reissue_retire(
		&context, reissue, old_write, new_write,
		old_read, new_read, old_chain, new_chain) == 0);
	assert(reissue->closed);
	round036_check_zeros((const swapz_u8 *)reissue->record,
			     sizeof(reissue->record));
	round036_check_zeros((const swapz_u8 *)reissue->source,
			     sizeof(reissue->source));
	assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
		&context, &sidecar) == 0);
	/* All callback references are drained before caller-owned scratch
	 * memory, original SHA witnesses and mock lower images are scrubbed.
	 */
	swapz_round039_dm_chain_scrub_relocation(old_chain);
	swapz_round039_dm_chain_scrub_relocation(new_chain);
	assert(pthread_mutex_destroy(&old_write->callback_lock) == 0);
	assert(pthread_mutex_destroy(&new_write->callback_lock) == 0);
	assert(pthread_mutex_destroy(&old_read->callback_lock) == 0);
	assert(pthread_mutex_destroy(&new_read->callback_lock) == 0);
	assert(pthread_mutex_destroy(&old_chain->gc_callback_lock) == 0);
	assert(pthread_mutex_destroy(&new_chain->gc_callback_lock) == 0);
	assert(pthread_mutex_destroy(&old_chain->gc_verifier.callback_lock) == 0);
	assert(pthread_mutex_destroy(&new_chain->gc_verifier.callback_lock) == 0);
	memzero_explicit(old_chain, sizeof(*old_chain));
	memzero_explicit(new_chain, sizeof(*new_chain));
	memzero_explicit(old_write, sizeof(*old_write));
	memzero_explicit(new_write, sizeof(*new_write));
	memzero_explicit(old_read, sizeof(*old_read));
	memzero_explicit(new_read, sizeof(*new_read));
	memzero_explicit(&old_record, sizeof(old_record));
	memzero_explicit(&new_record, sizeof(new_record));
	memzero_explicit(&old_source, sizeof(old_source));
	memzero_explicit(&new_source, sizeof(new_source));
	memzero_explicit(&original_transaction, sizeof(original_transaction));
	memzero_explicit(&new_transaction, sizeof(new_transaction));
	memzero_explicit(new_original, SWAPZ_BLOCK_BYTES);
	memzero_explicit(new_compressed, sizeof(new_compressed));
	memzero_explicit(fake_lower, 32U * SWAPZ_BLOCK_BYTES);
	/* The stub uses pthread locks only; destruction above occurs
	 * after the last fake callback, before explicit private scrubbing.
	 */
	free(old_write);
	free(new_write);
	free(old_read);
	free(new_read);
	free(old_chain);
	free(new_chain);
	free(reissue);
	free(new_original);
	free(fake_lower);
}

int main(void)
{
	unsigned int extent_blocks;
	unsigned int fault;

	assert(round039_fixture_main() == 0);
	for (extent_blocks = 1U; extent_blocks <= 4U; extent_blocks *= 2U)
		for (fault = 0U; fault <= 51U; ++fault)
			round040_test_reissue(extent_blocks, fault);
	puts("ROUND040_ACTUAL_DM_SAME_SLOT_REISSUE_2_SOURCE_SHA_GC_READ_NO_GO_PASS");
	return 0;
}
