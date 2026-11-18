/*
 * Round037 host-only fake lower boundary. The production DM source under
 * test is extracted verbatim; no real target, block I/O, map or upper BIO ACK.
 * The heap mailbox outlives its callback and is never freed before join.
 */
/* ROUND037_EXTRACT_ALL_PRIOR_SOURCE */
#include <pthread.h>
#include <stdlib.h>

typedef pthread_mutex_t spinlock_t;
#define spin_lock_init(lock) assert(pthread_mutex_init((lock), NULL) == 0)
#define spin_lock_irqsave(lock, flags) do { \
	(flags) = 0UL; assert(pthread_mutex_lock((lock)) == 0); \
} while (0)
#define spin_unlock_irqrestore(lock, flags) do { \
	(void)(flags); assert(pthread_mutex_unlock((lock)) == 0); \
} while (0)
/* ROUND037_EXTRACT_NEW_PRODUCTION_C */

struct round037_callback_event {
	struct swapz_round037_dm_async_mailbox *mailbox;
	swapz_u64 incarnation_ticket;
	int fake_error;
	swapz_u32 completed_bytes;
	const swapz_u8 *readback;
	swapz_u32 readback_bytes;
	int result;
};

static void *round037_deliver_from_separate_thread(void *event_pointer)
{
	struct round037_callback_event *event = event_pointer;

	event->result = swapz_round037_dm_async_fake_callback(
		event->mailbox, event->incarnation_ticket, event->fake_error,
		event->completed_bytes, event->readback, event->readback_bytes);
	return NULL;
}

static void round037_dispatch_fake_callback(
		struct round037_callback_event *event)
{
	pthread_t callback_thread;

	assert(pthread_create(&callback_thread, NULL,
			      round037_deliver_from_separate_thread, event) == 0);
	assert(pthread_join(callback_thread, NULL) == 0);
}

static void round037_assert_clean(
		const struct swapz_round037_dm_async_mailbox *mailbox)
{
	round036_check_zeros(mailbox->owned_compressed,
			     sizeof(mailbox->owned_compressed));
	round036_check_zeros(mailbox->provider_scratch,
			     sizeof(mailbox->provider_scratch));
	round036_check_zeros(mailbox->staged_extent,
			     sizeof(mailbox->staged_extent));
	round036_check_zeros(mailbox->fake_lower_image,
			     sizeof(mailbox->fake_lower_image));
	round036_check_zeros(mailbox->decoded_original,
			     sizeof(mailbox->decoded_original));
	round036_check_zeros(mailbox->decode_scratch,
			     sizeof(mailbox->decode_scratch));
	round036_check_zeros((const swapz_u8 *)&mailbox->private_transaction,
			     sizeof(mailbox->private_transaction));
}

static void round037_test_one(unsigned int extent_blocks,
			     unsigned int fault)
{
	struct swapz_dm ctx = { 0 };
	struct dm_target target = { .len = 32U * SWAPZ_SECTORS };
	struct swapz_zswap_admission_transaction transaction = { 0 };
	struct swapz_round030_dm_volatile_descriptor descriptor = { 0 };
	struct swapz_round031_dm_sidecar sidecar = { 0 };
	struct swapz_round037_dm_async_mailbox *mailbox =
		calloc(1U, sizeof(*mailbox));
	struct swapz_round036_dm_mock_publication publication;
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
	struct round037_callback_event callback_event = { 0 };
	swapz_u8 upper_output[SWAPZ_BLOCK_BYTES];
	swapz_u8 fake_image[4U * SWAPZ_BLOCK_BYTES];
	const swapz_u64 source_entry = swp_entry(2U, 39U).val;
	const swapz_u64 callback_ticket = 4097U;
	const swapz_u32 extent_bytes = extent_blocks * SWAPZ_BLOCK_BYTES;
	swapz_u32 compressed_length;
	unsigned int byte_index;
	int error;

	assert(mailbox != NULL);
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
		.representation_version = 1U, .codec = 1U
	};
	memcpy(original_provider_view.original_sha256,
	       transaction.record.original_sha256, 32U);
	memset(upper_output, 0xa5, sizeof(upper_output));
	memset(&publication, 0x76, sizeof(publication));
	memset(disk_data, 0, sizeof(disk_data));
	memset(disk_data, 0x36, SWAPZ_BLOCK_BYTES);
	memset(fake_image, 0xcc, sizeof(fake_image));
	provider_calls = 0;
	injected_provider_errno = 0;
	swapz_round037_dm_async_initialize(mailbox);

	switch (fault) {
	case 1U: original_provider_view.source_swap_entry =
			 swp_entry(3U, 39U).val; break;
	case 2U: original_provider_view.source_slot_epoch++; break;
	case 3U: original_provider_view.codec++; break;
	case 4U: original_provider_view.original_sha256[0] ^= 1U; break;
	case 5U: source_bio.lifetime_pinned = false; break;
	case 6U: source_bio.bi_iter.bi_sector = 0U; break;
	case 7U: sidecar.slots[5].owner_token = 99U; break;
	case 8U: ctx.gc_recovery.active = true; break;
	case 9U: transaction.record.generation++; break;
	case 10U: original_provider_view.compressed_crc32c ^= 1U; break;
	default: break;
	}
	error = swapz_round037_dm_async_prepare(
		&ctx, &source_bio, &sidecar, &transaction, source_entry,
		0U, callback_ticket, 2U, 77U, mailbox);
	if (fault >= 1U && fault <= 10U) {
		assert(error < 0);
		assert(mailbox->phase == SWAPZ_ROUND037_EXPIRED);
		round037_assert_clean(mailbox);
		goto done;
	}
	assert(error == 0);
	assert(mailbox->phase == SWAPZ_ROUND037_PREPARED);
	assert(mailbox->callback_references == 0U);
	assert(provider_calls == 1);
	assert(mailbox->ledger.source.source_swap_entry == source_entry);
	assert(mailbox->private_transaction.owned_compressed_bytes ==
	       mailbox->owned_compressed);
	assert(transaction.upper_write_ack_count == 0U);
	assert(mailbox->private_transaction.upper_write_ack_count == 0U);
	assert(swapz_round037_dm_async_finish(
		&ctx, &sidecar, callback_ticket, 77U,
		&mailbox->ledger.source, &publication, upper_output,
		mailbox) == -ESTALE);
	assert(swapz_round037_dm_async_submit(
		&ctx, mailbox, callback_ticket + 1U) == -ESTALE);
	assert(swapz_round037_dm_async_submit(
		&ctx, mailbox, callback_ticket) == 0);
	assert(mailbox->phase == SWAPZ_ROUND037_FAKE_WRITE_IN_FLIGHT);
	assert(mailbox->callback_references == 1U);
	assert(swapz_round037_dm_async_prepare(
		&ctx, &source_bio, &sidecar, &transaction, source_entry,
		0U, callback_ticket + 1U, 2U, 78U, mailbox) == -EBUSY);
	memcpy(disk_data + 2U * SWAPZ_BLOCK_BYTES, mailbox->staged_extent,
	       extent_bytes);
	memcpy(fake_image, disk_data + 2U * SWAPZ_BLOCK_BYTES, extent_bytes);
	for (byte_index = 0U; byte_index < extent_bytes; ++byte_index)
		if (byte_index < mailbox->ledger.payload_offset ||
		    byte_index >= mailbox->ledger.payload_offset +
				 mailbox->ledger.source.compressed_length)
			assert(fake_image[byte_index] == 0U);
	assert(!memcmp(fake_image + mailbox->ledger.payload_offset,
		       source_lz4_bytes, compressed_length));
	assert(!memcmp(disk_data, "\x36\x36\x36\x36", 4U));

	current_source = mailbox->ledger.source;
	callback_event.mailbox = mailbox;
	callback_event.incarnation_ticket = callback_ticket;
	callback_event.readback = fake_image;
	callback_event.completed_bytes = extent_bytes;
	callback_event.readback_bytes = extent_bytes;
	switch (fault) {
	case 11U:
	case 32U:
		assert(swapz_round037_dm_async_cancel(
			&ctx, mailbox, callback_ticket) == 0);
		assert(mailbox->phase == SWAPZ_ROUND037_CANCELLED);
		assert(mailbox->callback_references == 1U);
		round037_assert_clean(mailbox);
		assert(swapz_round037_dm_async_prepare(
			&ctx, &source_bio, &sidecar, &transaction, source_entry,
			0U, callback_ticket + 1U, 2U, 78U, mailbox) == -EBUSY);
		ctx.accepting = false; /* mock teardown: callback has NO ctx */
		ctx.ordered_owner = 0;
		round037_dispatch_fake_callback(&callback_event);
		assert(callback_event.result == -ESTALE);
		assert(mailbox->phase == SWAPZ_ROUND037_EXPIRED);
		assert(mailbox->callback_references == 0U);
		round037_assert_clean(mailbox);
		ctx.ordered_owner = 1;
		ctx.accepting = true;
		if (fault == 32U) {
			/* New incarnation after old callback quiesces. */
			assert(swapz_round037_dm_async_prepare(
				&ctx, &source_bio, &sidecar, &transaction,
				source_entry, 0U, callback_ticket + 1U,
				2U, 78U, mailbox) == 0);
			assert(swapz_round037_dm_async_submit(
				&ctx, mailbox, callback_ticket + 1U) == 0);
			assert(swapz_round037_dm_async_fake_callback(
				mailbox, callback_ticket, 0, extent_bytes,
				fake_image, extent_bytes) == -ESTALE);
			assert(mailbox->callback_references == 1U);
			assert(swapz_round037_dm_async_cancel(
				&ctx, mailbox, callback_ticket + 1U) == 0);
			assert(swapz_round037_dm_async_fake_callback(
				mailbox, callback_ticket + 1U, 0,
				extent_bytes, fake_image, extent_bytes) == -ESTALE);
			round037_assert_clean(mailbox);
		}
		goto done;
	case 13U: callback_event.completed_bytes--; break;
	case 14U: callback_event.fake_error = -EIO; break;
	case 15U: callback_event.readback_bytes--; break;
	case 16U: fake_image[0] ^= 1U; break;
	case 17U: fake_image[mailbox->ledger.payload_offset] ^= 1U; break;
	case 18U: mailbox->ledger.source.original_sha256[0] ^= 1U; break;
	case 34U: fake_image[mailbox->ledger.payload_offset + 1U] ^= 1U; break;
	case 35U: fake_image[extent_bytes - 1U] ^= 1U; break;
	case 36U: callback_event.completed_bytes /= 2U; break;
	default: break;
	}
	ctx.ordered_owner = 0; /* Actual distinct callback phase/thread. */
	if (fault == 29U) {
		assert(swapz_round037_dm_async_fake_callback(
			mailbox, callback_ticket + 1U, 0, extent_bytes,
			fake_image, extent_bytes) == -ESTALE);
		assert(mailbox->callback_references == 1U);
	}
	round037_dispatch_fake_callback(&callback_event);
	ctx.ordered_owner = 1;
	if (fault == 13U || fault == 14U || fault == 15U || fault == 36U) {
		assert(callback_event.result < 0);
		assert(mailbox->phase == SWAPZ_ROUND037_LOWER_COMPLETION_ERROR);
	} else {
		assert(callback_event.result == 0);
		assert(mailbox->phase == SWAPZ_ROUND037_LOWER_COMPLETION_OK);
	}
	assert(mailbox->callback_references == 0U);
	assert(swapz_round037_dm_async_fake_callback(
		mailbox, callback_ticket, 0, extent_bytes,
		fake_image, extent_bytes) == -ESTALE);
	assert(mailbox->callback_references == 0U);
	assert(transaction.upper_write_ack_count == 0U);
	assert(!ctx.maps[5].valid);
	switch (fault) {
	case 19U: current_source.source_slot_epoch++; break;
	case 20U: current_source.source_swap_entry =
			  swp_entry(3U, 39U).val; break;
	case 21U: current_source.stored_entry_identity++; break;
	case 22U: ctx.maps[5].generation++; break;
	case 23U: ctx.authority.gc_destination++; break;
	case 24U: ctx.gc_recovery.active = true; break;
	case 25U: ctx.accepting = false; break;
	case 26U: sidecar.slots[5].owner_token++; break;
	case 28U: mailbox->private_transaction.record.store_generation++; break;
	case 30U:
		assert(swapz_round037_dm_async_cancel(
			&ctx, mailbox, callback_ticket) == 0);
		round037_assert_clean(mailbox);
		break;
	case 33U: current_source.source_slot_epoch += 2U; break;
	default: break;
	}
	error = swapz_round037_dm_async_finish(
		&ctx, &sidecar, callback_ticket,
		fault == 27U ? 78U : 77U, &current_source,
		&publication, upper_output, mailbox);
	if (fault && fault != 12U && fault != 29U && fault != 31U) {
		assert(error < 0);
		assert(mailbox->phase == SWAPZ_ROUND037_EXPIRED ||
		       mailbox->phase == SWAPZ_ROUND037_CANCELLED);
		assert(!ctx.maps[5].valid || fault == 22U);
		round037_assert_clean(mailbox);
	} else {
		assert(error == 0);
		assert(mailbox->phase == SWAPZ_ROUND037_MOCK_ACKED);
		assert(publication.hypothetical_ack_count == 1U);
		assert(publication.owner_cookie == callback_ticket);
		assert(publication.source_swap_entry == source_entry);
		assert(publication.fake_start_block == 2U);
		assert(memcmp(upper_output, original, SWAPZ_BLOCK_BYTES) == 0);
		assert(mailbox->ledger.hypothetical_ack_count == 1U);
		round037_assert_clean(mailbox);
		assert(swapz_round037_dm_async_finish(
			&ctx, &sidecar, callback_ticket, 77U,
			&current_source, &publication, upper_output,
			mailbox) == -ESTALE);
	}
	assert(transaction.upper_write_ack_count == 0U);
	assert(transaction.phase == SWAPZ_ZSWAP_ADMISSION_PREPARED);
	assert(lower_writes == 0 && lower_reads == 0);
	if (fault && fault != 12U && fault != 29U && fault != 31U) {
		round036_check_sentinel(upper_output, sizeof(upper_output), 0xa5U);
		round036_check_sentinel((const swapz_u8 *)&publication,
				       sizeof(publication), 0x76U);
	}
done:
	assert(mailbox->callback_references == 0U);
	for (byte_index = 0U; byte_index < SWAPZ_BLOCK_BYTES; ++byte_index)
		assert(disk_data[byte_index] == 0x36U);
	assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
		&ctx, &sidecar) == 0);
	assert(pthread_mutex_destroy(&mailbox->callback_lock) == 0);
	free(mailbox);
}

int main(void)
{
	unsigned int extent_blocks, fault;

	assert(swapz_round036_fixture_main() == 0);
	for (extent_blocks = 1U; extent_blocks <= 4U; extent_blocks *= 2U)
		for (fault = 0U; fault <= 36U; ++fault)
			round037_test_one(extent_blocks, fault);
	puts("ROUND037_ACTUAL_PRODUCTION_DM_ASYNC_LATER_CALLBACK_4096_SHA_GC_FENCE_NO_GO_PASS");
	return 0;
}
