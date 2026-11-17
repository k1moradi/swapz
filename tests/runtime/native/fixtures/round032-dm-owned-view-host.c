/* Round032: compile and EXECUTE exact guarded src/kernel/dm-target.c
 * candidate view validation with the prior real guarded Round030/031 C source.
 * Fake only BIO, original producer snapshot, and lower/map authority boundary.
 * Source metadata is synthetic and therefore NEVER authenticated for live IO.
 */
/* ROUND032_EMBED_PRIOR_REAL_DM_AND_MOCK_BOUNDARIES */

/* Minimal host mirror of kernel's BIO structure at its mock boundary. */
#define BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN 1
#define SWAPZ_SECTORS 8U
#define REQ_OP_READ 0U
#define REQ_OP_WRITE 1U
#define REQ_OP_DISCARD 3U
#define REQ_SWAP 0x100U
#define REQ_PREFLUSH 0x200U
typedef uint64_t sector_t;
struct bio_vec {
	void *bv_page;
	unsigned int bv_offset;
	unsigned int bv_len;
};
struct bio {
	struct {
		sector_t bi_sector;
		unsigned int bi_size;
		unsigned int bi_idx;
	} bi_iter;
	const struct bio_vec *bi_io_vec;
	void *bi_bdev;
	unsigned int bi_vcnt;
	unsigned int bi_opf;
	unsigned int bi_swap_origin;
};
#define bio_op(source_bio) ((source_bio)->bi_opf & 15U)
#define bio_sectors(source_bio) ((source_bio)->bi_iter.bi_size / 512U)
#define bio_iter_iovec(source_bio, iteration) (*(source_bio)->bi_io_vec)
static bool bio_is_zswap_stored_writeback(const struct bio *source_bio)
{
	return bio_op(source_bio) == REQ_OP_WRITE &&
		(source_bio->bi_opf & REQ_SWAP) &&
		source_bio->bi_swap_origin == 1U;
}

/* ROUND032_EXACT_DM_CANDIDATE_VALIDATOR */

static void run_round032_actual_c_host(void)
{
	struct swapz_dm ctx = { 0 };
	struct dm_target target = { .len = 256U };
	struct swapz_zswap_admission_transaction transaction = { 0 };
	struct swapz_round030_dm_volatile_descriptor old_descriptor = { 0 };
	struct swapz_round031_dm_sidecar sidecar = { 0 };
	struct swapz_round032_dm_owned_view_v1 view = { 0 };
	struct bio_vec vector = {
		.bv_page = original, .bv_offset = 0U, .bv_len = SWAPZ_BLOCK_BYTES
	};
	struct bio source_bio = {
		.bi_iter = { .bi_sector = 5U * SWAPZ_SECTORS,
			     .bi_size = SWAPZ_BLOCK_BYTES, .bi_idx = 0U },
		.bi_io_vec = &vector,
		.bi_bdev = &target,
		.bi_vcnt = 1U,
		.bi_opf = REQ_OP_WRITE | REQ_SWAP,
		.bi_swap_origin = 1U
	};
	swapz_u8 independent_source_copy[SWAPZ_MAX_COMPRESSED] = { 0 };
	swapz_u8 verification_scratch[SWAPZ_MAX_COMPRESSED] = { 0 };
	swapz_u8 candidate_destination[SWAPZ_MAX_COMPRESSED] = { 0 };
	swapz_u64 owner_token = 0U;
	const swapz_u32 compressed_length = (swapz_u32)LZ4_compress_default(
		(const char *)original, (char *)compressed,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
	swapz_u32 index;
	int result;

	assert(compressed_length > 0U && compressed_length <= SWAPZ_MAX_COMPRESSED);
	initial_state(&ctx, &transaction, &old_descriptor,
		      SWAPZ_BLOCK_BYTES, compressed_length);
	ctx.target = &target;
	ctx.logical_pages = ctx.authority.logical_pages;
	assert(swapz_round031_dm_sidecar_init(&ctx, &sidecar) == 0);
	assert(swapz_round031_dm_commit_with_sidecar(
		&ctx, &sidecar, &transaction, 1234U, compressed,
		compressed_length, lower_image, sizeof(lower_image),
		true, &owner_token) == 0);
	assert(owner_token != 0U && ctx.authority.maps[5].valid);

	view.source_swap_entry = 1234U;
	view.source_slot_epoch = 333U;
	view.stored_entry_identity = 222U;
	view.compressed_crc32c = transaction.record.compressed_crc32c;
	view.compressed_length = (swapz_u16)compressed_length;
	view.decoded_length = SWAPZ_BLOCK_BYTES;
	view.representation_version = 1U;
	view.codec = 1U;
	memcpy(view.original_sha256, transaction.record.original_sha256,
	       sizeof(view.original_sha256));
	memcpy(independent_source_copy, compressed, compressed_length);

#define MECHANICAL() swapz_round032_dm_verify_untrusted_view_v1( \
	&ctx, &source_bio, &view, independent_source_copy, \
	compressed_length, &sidecar, owner_token)
#define COPY_CANDIDATE() swapz_round032_dm_copy_untrusted_for_test( \
	&ctx, &source_bio, &view, independent_source_copy, \
	compressed_length, &sidecar, owner_token, verification_scratch, \
	sizeof(verification_scratch), candidate_destination, \
	sizeof(candidate_destination))
#define REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT() do { \
	memset(candidate_destination, 0x7b, sizeof(candidate_destination)); \
	result = COPY_CANDIDATE(); \
	assert(result < 0); \
	for (index = 0U; index < sizeof(candidate_destination); ++index) \
		assert(candidate_destination[index] == 0x7bU); \
} while (0)

	assert(MECHANICAL() == 0);
	assert(COPY_CANDIDATE() == 0);
	assert(memcmp(candidate_destination, compressed, compressed_length) == 0);
	/* The principal acceptance entrypoint never authenticates a caller
	 * created view or accepts a real compressed upper BIO.
	 */
	assert(swapz_round032_dm_try_accept_owned_view_v1(
		&ctx, &source_bio, &view, independent_source_copy,
		compressed_length, &sidecar, owner_token) == -EOPNOTSUPP);
	assert(transaction.upper_write_ack_count == 1U && lower_writes == 1);
	/* Empty/hostile full packed source identifier must never masquerade
	 * as a DM-relative page. View == page is NOT automatically authentic.
	 */
	view.source_swap_entry = 0U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	view.source_swap_entry = 5U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	view.source_swap_entry = 1234U;
	view.source_slot_epoch = 0U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	view.source_slot_epoch = 334U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	view.source_slot_epoch = 333U;
	view.stored_entry_identity = 0U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	view.stored_entry_identity = 223U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	view.stored_entry_identity = 222U;

	view.representation_version = 2U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	view.representation_version = 1U;
	view.codec = 2U; /* zstd and dictionary require refusal. */
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	view.codec = 1U;
	view.compressed_length = 0U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	view.compressed_length = 3569U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	view.compressed_length = (swapz_u16)compressed_length;
	view.decoded_length = 4095U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	view.decoded_length = SWAPZ_BLOCK_BYTES;

	view.compressed_crc32c ^= 1U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	view.compressed_crc32c ^= 1U;
	independent_source_copy[0] ^= 1U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	independent_source_copy[0] ^= 1U;
	view.original_sha256[0] ^= 1U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	view.original_sha256[0] ^= 1U;
	memset(view.original_sha256, 0, sizeof(view.original_sha256));
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	memcpy(view.original_sha256, transaction.record.original_sha256,
	       sizeof(view.original_sha256));

	source_bio.bi_opf = REQ_OP_READ | REQ_SWAP;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	source_bio.bi_opf = REQ_OP_DISCARD | REQ_SWAP;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	source_bio.bi_opf = REQ_OP_WRITE;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	source_bio.bi_opf = REQ_OP_WRITE | REQ_SWAP | REQ_PREFLUSH;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	source_bio.bi_opf = REQ_OP_WRITE | REQ_SWAP;
	source_bio.bi_swap_origin = 0U; /* scalar source alone insufficient. */
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	source_bio.bi_swap_origin = 1U;
	source_bio.bi_iter.bi_size = 2048U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	source_bio.bi_iter.bi_size = SWAPZ_BLOCK_BYTES;
	source_bio.bi_iter.bi_sector = 5U * SWAPZ_SECTORS + 1U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	source_bio.bi_iter.bi_sector = 0U; /* protected 4096 header page */
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	source_bio.bi_iter.bi_sector = target.len;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	source_bio.bi_iter.bi_sector = 5U * SWAPZ_SECTORS;
	source_bio.bi_iter.bi_idx = 1U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	source_bio.bi_iter.bi_idx = 0U;
	source_bio.bi_vcnt = 2U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	source_bio.bi_vcnt = 1U;
	vector.bv_len = 2048U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	vector.bv_len = SWAPZ_BLOCK_BYTES;
	vector.bv_offset = 1U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	vector.bv_offset = 0U;
	vector.bv_page = NULL;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	vector.bv_page = original;
	source_bio.bi_bdev = NULL; /* owner reset before synchronous call */
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	source_bio.bi_bdev = &target;

	ctx.gc_recovery.active = true;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	ctx.gc_recovery.active = false;
	ctx.authority.gc_allocation = 1U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	ctx.authority.gc_allocation = 0U;
	ctx.authority.in_flight = 1U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	ctx.authority.in_flight = 0U;
	ctx.accepting = false;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	ctx.accepting = true;
	sidecar.slots[5].descriptor.hypothetical_ack_count = 2U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	sidecar.slots[5].descriptor.hypothetical_ack_count = 1U;
	sidecar.slots[5].descriptor.record.dictionary_id = 1U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	sidecar.slots[5].descriptor.record.dictionary_id = 0U;
	sidecar.slots[5].descriptor.record.stored_eviction = 0U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	sidecar.slots[5].descriptor.record.stored_eviction = 1U;
	sidecar.slots[5].readers = 1U;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	sidecar.slots[5].readers = 0U;
	++maps[5].generation;
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	--maps[5].generation;
	++next_sequence; /* physical extent reused with same logical gen */
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	--next_sequence;
	++sidecar.slots[5].owner_token; /* late completion cannot rebind */
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	--sidecar.slots[5].owner_token;

	/* Source buffer and all outputs are separate; no leak on failure.
	 * Refuse a truncated copy, huge declared capacity and any alias.
	 */
	memset(candidate_destination, 0x7b, sizeof(candidate_destination));
	assert(swapz_round032_dm_copy_untrusted_for_test(
		&ctx, &source_bio, &view, independent_source_copy,
		compressed_length - 1U, &sidecar, owner_token,
		verification_scratch, sizeof(verification_scratch),
		candidate_destination, sizeof(candidate_destination)) == -EMSGSIZE);
	assert(candidate_destination[0] == 0x7bU);
	assert(swapz_round032_dm_copy_untrusted_for_test(
		&ctx, &source_bio, &view, independent_source_copy,
		SWAPZ_MAX_COMPRESSED + 1U, &sidecar, owner_token,
		verification_scratch, sizeof(verification_scratch),
		candidate_destination, sizeof(candidate_destination)) == -EMSGSIZE);
	assert(candidate_destination[0] == 0x7bU);
	assert(swapz_round032_dm_copy_untrusted_for_test(
		&ctx, &source_bio, &view, independent_source_copy,
		compressed_length, &sidecar, owner_token,
		candidate_destination, sizeof(candidate_destination),
		candidate_destination, sizeof(candidate_destination)) == -EINVAL);
	assert(swapz_round032_dm_copy_untrusted_for_test(
		&ctx, &source_bio, &view, independent_source_copy,
		compressed_length, &sidecar, owner_token,
		verification_scratch, sizeof(verification_scratch),
		independent_source_copy, sizeof(independent_source_copy)) == -EINVAL);

	/* An independently captured source snapshot outlives the old pool
	 * pointer, but an invalidated current map/token must still refuse.
	 */
	assert(MECHANICAL() == 0);
	assert(COPY_CANDIDATE() == 0);
	assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
		&ctx, &sidecar) == 0);
	assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
		&ctx, &sidecar) == 0);
	REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT();
	assert(transaction.upper_write_ack_count == 1U && lower_writes == 1);
#undef MECHANICAL
#undef COPY_CANDIDATE
#undef REQUIRE_REFUSED_WITH_UNCHANGED_OUTPUT
	puts("ROUND032_DM_FROZEN_V1_TRUE_SOURCE_C_MECHANICS_AND_LIVE_NO_GO_PASS");
}

int main(void)
{
	const int previous_result = swapz_round031_original_host_main();

	assert(previous_result == 0);
	run_round032_actual_c_host();
	return 0;
}
