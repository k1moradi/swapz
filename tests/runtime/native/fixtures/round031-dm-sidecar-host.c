/* Host-only Round031 source-extracted C. NO live hardware, BIO or cache. */
#define SWAPZ_ROUND031_DM_LZ4_SIDECAR_TEST 1
#define main swapz_round030_fixture_main
/* ROUND031_EMBED_ROUND030_SOURCE */
#undef main
#include <stdlib.h>
#include <limits.h>

static bool injected_allocation_failure;
static void *round031_test_kvcalloc(size_t count, size_t size, int flags)
{
	(void)flags;
	if (injected_allocation_failure)
		return NULL;
	return calloc(count, size);
}
static void round031_test_memzero_explicit(void *address, size_t size)
{
	volatile unsigned char *bytes = address;
	while (size--)
		*bytes++ = 0;
}
#define kvcalloc round031_test_kvcalloc
#define kvfree free
#define GFP_KERNEL 0
#define memzero_explicit round031_test_memzero_explicit
#define check_mul_overflow(first, second, output) \
	__builtin_mul_overflow((first), (second), (output))

/* ROUND031_EXACT_DM_SIDECAR_SOURCE */

static void prepare_next_generation(
		struct swapz_zswap_admission_transaction *transaction,
		swapz_u64 generation, swapz_u64 store_generation,
		swapz_u64 stored_identity, swapz_u32 extent_bytes,
		swapz_u32 compressed_length)
{
	struct swapz_zswap_admission_mapping mapping = { 0 };
	struct swapz_zswap_import_record record = { 0 };

	mapping.source_swap_slot = 1234U;
	mapping.source_store_generation = store_generation;
	mapping.source_stored_entry_identity = stored_identity;
	mapping.dm_logical_page = 5U;
	mapping.dm_generation = generation;
	mapping.dm_gc_epoch = 444U;
	mapping.physical_extent_bytes = extent_bytes;
	mapping.compressed_payload_offset = extent_bytes - compressed_length;
	mapping.mock_bridge_only = 1U;
	mapping.source_stored_eviction_verified = 1U;
	mapping.compressed_source_owned_copy = 1U;
	mapping.original_sha256_from_store = 1U;
	mapping.post_header_extent_authorized = 1U;
	mapping.deterministic_zero_padding = 1U;
	record.logical_page = 5U;
	record.generation = generation;
	record.stored_entry_identity = stored_identity;
	record.store_generation = store_generation;
	record.gc_epoch = 444U;
	record.compressed_length = compressed_length;
	record.compressed_crc32c = swapz_crc32c_bytes(compressed, compressed_length);
	record.decoded_length = SWAPZ_BLOCK_BYTES;
	record.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
	record.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION;
	record.version = SWAPZ_ZSWAP_IMPORT_VERSION;
	record.immutable_owned_copy = 1U;
	record.stored_eviction = 1U;
	assert(SHA256(original, SWAPZ_BLOCK_BYTES, record.original_sha256));
	assert(swapz_zswap_admission_begin_mock(
		transaction, &mapping, &record, compressed,
		SWAPZ_MAX_COMPRESSED) == 0);
}

static void validate_empty_retirement(
		const struct swapz_round031_dm_sidecar_slot *slot)
{
	const unsigned char *bytes = (const unsigned char *)slot;
	size_t index;
	for (index = 0; index < sizeof(*slot); ++index)
		assert(bytes[index] == 0U);
}

static void round031_sidecar_host_tests(swapz_u32 compressed_length)
{
	struct swapz_dm ctx = { 0 };
	struct swapz_zswap_admission_transaction transaction = { 0 };
	struct swapz_zswap_admission_transaction next_transaction = { 0 };
	struct swapz_round030_dm_volatile_descriptor legacy_descriptor = { 0 };
	struct swapz_round031_dm_sidecar sidecar = { 0 };
	struct swapz_round031_dm_sidecar large = { 0 };
	struct swapz_round031_dm_sidecar exhausted = { 0 };
	swapz_u64 first_token = 0, second_token = 0;
	swapz_u32 extent_blocks;
	swapz_u32 index;

	for (extent_blocks = 1U; extent_blocks <= 4U; extent_blocks *= 2U) {
		initial_state(&ctx, &transaction, &legacy_descriptor,
			      extent_blocks * SWAPZ_BLOCK_BYTES, compressed_length);
		memset(&sidecar, 0, sizeof(sidecar));
		assert(swapz_round031_dm_sidecar_init(&ctx, &sidecar) == 0);
		assert(sidecar.capacity == ctx.authority.logical_pages);
		assert(sidecar.allocated_bytes ==
		       sidecar.capacity * sizeof(*sidecar.slots));
		assert(!sidecar.slots[5].owner_token);
		assert(swapz_round031_dm_commit_with_sidecar(
			&ctx, &sidecar, &transaction, 1234U, compressed,
			compressed_length, lower_image, sizeof(lower_image),
			true, &first_token) == 0);
		assert(first_token != 0U);
		assert(sidecar.slots[5].owner_token == first_token);
		assert(sidecar.slots[5].representation_tag ==
		       SWAPZ_ROUND031_SOURCE_LZ4_TAG);
		assert(sidecar.slots[5].descriptor.hypothetical_ack_count == 1U);
		assert(transaction.phase == SWAPZ_ZSWAP_ADMISSION_ACKED);
		assert(transaction.upper_write_ack_count == 1U);
		assert(!ctx.round031_defer_hypothetical_ack);
		assert(lower_fua == 1 && lower_writes == 1);
		assert(!maps[5].raw && maps[5].valid);
		for (index = 0U;
		     index < transaction.compressed_payload_offset; ++index)
			assert(disk_data[2U * SWAPZ_BLOCK_BYTES + index] == 0U);
		memset(output, 0x5a, sizeof(output));
		assert(swapz_round031_dm_read_with_sidecar(
			&ctx, &sidecar, &transaction, 5U, first_token,
			lower_image, sizeof(lower_image), scratch, scratch,
			output) == -EINVAL);
		/* A private output scratch must be distinct from the original
		 * source page, since no upper output can alias the authority.
		 */
		{
			swapz_u8 independent_decoded[SWAPZ_BLOCK_BYTES] = { 0 };
			assert(swapz_round031_dm_read_with_sidecar(
				&ctx, &sidecar, &transaction, 5U, first_token,
				lower_image, sizeof(lower_image), scratch,
				independent_decoded, output) == 0);
			assert(memcmp(original, output, sizeof(output)) == 0);
			assert(swapz_round031_dm_read_with_sidecar(
				&ctx, &sidecar, &transaction, 5U, first_token + 1U,
				lower_image, sizeof(lower_image), scratch,
				independent_decoded, output) == -ESTALE);
			assert(swapz_round031_dm_commit_with_sidecar(
				&ctx, &sidecar, &transaction, 1234U, compressed,
				compressed_length, lower_image, sizeof(lower_image),
				false, &second_token) == -ESTALE);
			assert(!second_token);
			assert(lower_writes == 1);
			/* Existing valid source is not retired by a failed newer
			 * lower write: the map and token stay authoritative.
			 */
			prepare_next_generation(&next_transaction, 2U, 334U,
						223U, SWAPZ_BLOCK_BYTES,
						compressed_length);
			fake_next_start_block = 4U;
			next_sequence = 6U;
			lower_write_error = -EIO;
			assert(swapz_round031_dm_commit_with_sidecar(
				&ctx, &sidecar, &next_transaction, 1234U,
				compressed, compressed_length, lower_image,
				sizeof(lower_image), false, &second_token) == -EIO);
			assert(!second_token);
			assert(maps[5].generation == 1U);
			assert(sidecar.slots[5].owner_token == first_token);
			lower_write_error = 0;
			/* Physical extent index still identifies the old block
			 * through the mock's per-block immutable sequence.
			 */
			next_sequence = 5U;
			assert(swapz_round031_dm_read_with_sidecar(
				&ctx, &sidecar, &transaction, 5U, first_token,
				lower_image, sizeof(lower_image), scratch,
				independent_decoded, output) == 0);
			next_sequence = 6U;
			/* The failed transaction is retired; prepare a FRESH
			 * mock source entry for a successful newer commit.
			 */
			memset(&next_transaction, 0, sizeof(next_transaction));
			prepare_next_generation(&next_transaction, 2U, 335U,
						224U, SWAPZ_BLOCK_BYTES,
						compressed_length);
			assert(swapz_round031_dm_commit_with_sidecar(
				&ctx, &sidecar, &next_transaction, 1234U,
				compressed, compressed_length, lower_image,
				sizeof(lower_image), false, &second_token) == 0);
			assert(second_token > first_token);
			assert(sidecar.slots[5].descriptor.record.generation == 2U);
			assert(swapz_round031_dm_forget_on_overwrite(
				&ctx, &sidecar, 5U, first_token) == -ESTALE);
			assert(swapz_round031_dm_read_with_sidecar(
				&ctx, &sidecar, &transaction, 5U, first_token,
				lower_image, sizeof(lower_image), scratch,
				independent_decoded, output) == -ESTALE);
			assert(swapz_round031_dm_read_with_sidecar(
				&ctx, &sidecar, &next_transaction, 5U, second_token,
				lower_image, sizeof(lower_image), scratch,
				independent_decoded, output) == 0);
			disk_data[4U * SWAPZ_BLOCK_BYTES +
				  next_transaction.compressed_payload_offset] ^= 1U;
			memset(output, 0x7a, sizeof(output));
			assert(swapz_round031_dm_read_with_sidecar(
				&ctx, &sidecar, &next_transaction, 5U, second_token,
				lower_image, sizeof(lower_image), scratch,
				independent_decoded, output) == -EBADMSG);
			assert(output[0] == 0x7aU);
			disk_data[4U * SWAPZ_BLOCK_BYTES +
				  next_transaction.compressed_payload_offset] ^= 1U;
			maps[5].start_block = 3U;
			assert(swapz_round031_dm_read_with_sidecar(
				&ctx, &sidecar, &next_transaction, 5U, second_token,
				lower_image, sizeof(lower_image), scratch,
				independent_decoded, output) == -ESTALE);
			assert(output[0] == 0x7aU);
			maps[5].start_block = 4U;
			assert(swapz_round031_dm_forget_on_gc_relocation(
				&ctx, &sidecar, 5U, second_token) == 0);
			validate_empty_retirement(&sidecar.slots[5]);
			assert(swapz_round031_dm_forget_on_discard(
				&ctx, &sidecar, 5U, second_token) == 0);
			assert(swapz_round031_dm_forget_on_abort(
				&ctx, &sidecar, 5U, second_token) == 0);
			assert(swapz_round031_dm_read_with_sidecar(
				&ctx, &sidecar, &next_transaction, 5U, second_token,
				lower_image, sizeof(lower_image), scratch,
				independent_decoded, output) == -ESTALE);
		}
		assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
			&ctx, &sidecar) == 0);
		assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
			&ctx, &sidecar) == 0);
		assert(sidecar.slots == NULL && sidecar.closed);
		memset(&next_transaction, 0, sizeof(next_transaction));
	}

	initial_state(&ctx, &transaction, &legacy_descriptor,
		      SWAPZ_BLOCK_BYTES, compressed_length);
	ctx.authority.logical_pages = UINT32_MAX;
	assert(swapz_round031_dm_sidecar_init(&ctx, &large) == -EOVERFLOW);
	assert(!large.slots && large.capacity == 0U);
	ctx.authority.logical_pages = 32U;
	injected_allocation_failure = true;
	assert(swapz_round031_dm_sidecar_init(&ctx, &exhausted) == -ENOMEM);
	injected_allocation_failure = false;
	assert(!exhausted.slots);
	assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
		&ctx, &large) == 0);
	assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
		&ctx, &exhausted) == 0);
}

int main(void)
{
	int previous = swapz_round030_fixture_main();
	int compressed_length;

	assert(previous == 0);
	compressed_length = LZ4_compress_default(
		(const char *)original, (char *)compressed,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
	assert(compressed_length > 0);
	round031_sidecar_host_tests((swapz_u32)compressed_length);
	puts("ROUND031_DM_ACTUAL_SOURCE_LZ4_SIDECAR_NO_LIVE_PASS");
	return 0;
}
