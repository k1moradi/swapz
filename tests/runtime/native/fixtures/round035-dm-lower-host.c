/*
 * Round035: host-owned fake block image only, source-extracted actual
 * production Round030/031/033/035 C. NO source MM authentication, device IO
 * or real BIO ACK. The preexisting fake swapz authority stage/finish/read
 * callbacks alone are mocked, never the byte pipeline/decoder.
 */
/* ROUND035_EMBED_PRIOR_ACTUAL_DM */

#include <stddef.h>
#define BUILD_BUG_ON(condition) _Static_assert(!(condition), "original v1 ABI")
#define MAX_SWAPFILES 30U
#define REQ_OP_WRITE 1U
#define REQ_SWAP 0x100U
#define REQ_PREFLUSH 0x200U
#define SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK 1U
#define SWAPZ_SECTORS 8U
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef uint64_t sector_t;
typedef unsigned long pgoff_t;
typedef struct { unsigned long val; } swp_entry_t;
#define SWP_TYPE_SHIFT 59U
#define SWP_OFFSET_MASK ((1UL << SWP_TYPE_SHIFT) - 1UL)
static swp_entry_t swp_entry(unsigned long type, pgoff_t offset)
{
	swp_entry_t entry = { .val = (type << SWP_TYPE_SHIFT) |
				    (offset & SWP_OFFSET_MASK) };
	return entry;
}
static unsigned int swp_type(swp_entry_t entry)
{
	return (unsigned int)(entry.val >> SWP_TYPE_SHIFT);
}
static pgoff_t swp_offset(swp_entry_t entry)
{
	return entry.val & SWP_OFFSET_MASK;
}
struct bio_vec {
	void *bv_page;
	unsigned int bv_offset, bv_len;
};
struct bio {
	bool lifetime_pinned, full_uncompressed_4096_swap_write;
	struct {
		sector_t bi_sector;
		unsigned int bi_size, bi_idx, bi_offset;
	} bi_iter;
	struct bio_vec *bi_io_vec;
	void *bi_bdev;
	unsigned int bi_vcnt, bi_opf, bi_swap_origin;
};
#define bio_op(source_bio) ((source_bio)->bi_opf & 15U)
#define bio_sectors(source_bio) ((source_bio)->bi_iter.bi_size / 512U)
#define bio_iter_iovec(source_bio, iterator) (*(source_bio)->bi_io_vec)
struct swapz_ci_lz4_owned_view_v1 {
	u64 source_swap_entry, source_slot_epoch, stored_entry_identity;
	u32 compressed_crc32c;
	u16 compressed_length, decoded_length;
	u8 representation_version, codec, original_sha256[32];
};
struct swapz_round032_dm_owned_view_v1 {
	swapz_u64 source_swap_entry, source_slot_epoch, stored_entry_identity;
	swapz_u32 compressed_crc32c;
	swapz_u16 compressed_length, decoded_length;
	swapz_u8 representation_version, codec, original_sha256[32];
};
static struct swapz_ci_lz4_owned_view_v1 original_provider_view;
static u8 source_lz4_bytes[SWAPZ_MAX_COMPRESSED];
static u16 source_lz4_length;
static int provider_calls, injected_provider_errno;
static int swapz_ci_bio_snapshot_lz4_v1(
		const struct bio *source_bio,
		struct swapz_ci_lz4_owned_view_v1 *view,
		u8 *owned_destination, size_t capacity)
{
	++provider_calls;
	if (!source_bio || !source_bio->lifetime_pinned ||
	    !source_bio->full_uncompressed_4096_swap_write)
		return -ESTALE;
	if (injected_provider_errno)
		return injected_provider_errno;
	if (!view || !owned_destination || capacity < source_lz4_length)
		return -ENOSPC;
	memcpy(owned_destination, source_lz4_bytes, source_lz4_length);
	*view = original_provider_view;
	return 0;
}
/* ROUND033_ACTUAL_PRODUCTION_COPY */
/* ROUND035_ACTUAL_PRODUCTION_LOWER */

static void run_round035_lower_case(unsigned int extent_blocks,
				    unsigned int fault)
{
	struct swapz_dm ctx = { 0 };
	struct dm_target target = { .len = 32U * SWAPZ_SECTORS };
	struct swapz_zswap_admission_transaction transaction = { 0 };
	struct swapz_round030_dm_volatile_descriptor unused_descriptor = { 0 };
	struct swapz_round031_dm_sidecar sidecar = { 0 };
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
	swapz_u8 copied[SWAPZ_MAX_COMPRESSED];
	swapz_u8 private_scratch[SWAPZ_MAX_COMPRESSED];
	swapz_u8 read_lower[4U * SWAPZ_BLOCK_BYTES];
	swapz_u8 decode_scratch[SWAPZ_BLOCK_BYTES];
	swapz_u8 verified_page[SWAPZ_BLOCK_BYTES];
	swapz_u8 candidate[SWAPZ_BLOCK_BYTES];
	swapz_u8 upper_page[SWAPZ_BLOCK_BYTES];
	swapz_u64 owner_token = 0xdeadbeefU;
	const swapz_u64 source_slot = swp_entry(2U, 39U).val;
	swapz_u32 length, index;
	int error;

	length = (swapz_u32)LZ4_compress_default(
		(const char *)original, (char *)compressed,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
	assert(length > 0U && length <= SWAPZ_MAX_COMPRESSED);
	initial_state(&ctx, &transaction, &unused_descriptor,
		      extent_blocks * SWAPZ_BLOCK_BYTES, length);
	ctx.target = &target;
	memcpy(source_lz4_bytes, compressed, length);
	source_lz4_length = (u16)length;
	memcpy(copied, compressed, length);
	transaction.owned_compressed_bytes = copied;
	transaction.payload_capacity = SWAPZ_MAX_COMPRESSED;
	original_provider_view = (struct swapz_ci_lz4_owned_view_v1) {
		.source_swap_entry = source_slot,
		.source_slot_epoch = transaction.record.store_generation,
		.stored_entry_identity = transaction.record.stored_entry_identity,
		.compressed_crc32c = transaction.record.compressed_crc32c,
		.compressed_length = (u16)length,
		.decoded_length = SWAPZ_BLOCK_BYTES,
		.representation_version = 1U,
		.codec = 1U,
	};
	memcpy(original_provider_view.original_sha256,
	       transaction.record.original_sha256, 32U);
	assert(swapz_round031_dm_sidecar_init(&ctx, &sidecar) == 0);
	/* First genuine SWAPSPACE2 4096 physical header stays unchanged. */
	memset(disk_data, 0x36, SWAPZ_BLOCK_BYTES);
	memset(upper_page, 0xa5, sizeof(upper_page));
	memset(private_scratch, 0xce, sizeof(private_scratch));
	provider_calls = 0;
	injected_provider_errno = 0;
	switch (fault) {
	case 1U:
		original_provider_view.codec = 2U;
		break;
	case 2U:
		original_provider_view.original_sha256[0] ^= 1U;
		break;
	case 3U:
		original_provider_view.compressed_crc32c ^= 1U;
		break;
	case 4U:
		original_provider_view.source_swap_entry = swp_entry(3U, 39U).val;
		break;
	case 5U:
		pinned_bio.bi_iter.bi_sector = 0U;
		break;
	case 6U:
		pinned_bio.bi_vcnt = 1U; /* original kernel is zero */
		break;
	case 7U:
		lower_read_error = -EIO; /* after fake lower WRITE */
		break;
	case 8U:
		ctx.gc_recovery.active = true;
		break;
	case 9U:
		transaction.teardown_started = 1U;
		break;
	case 10U:
		original_provider_view.compressed_length = 3569U;
		break;
	case 11U:
		pinned_bio.bi_bdev = NULL;
		break;
	case 12U:
		/* Stale source slot epoch after ABA reuse. */
		original_provider_view.source_slot_epoch++;
		break;
	case 13U:
		/* Source and output cannot alias; output unchanged on error. */
		break;
	default:
		break;
	}

	if (fault == 13U) {
		error = swapz_round035_dm_owned_lz4_lower_roundtrip(
			&ctx, &pinned_bio, &sidecar, &transaction, source_slot,
			copied, private_scratch, lower_image, upper_page,
			decode_scratch, verified_page, candidate, upper_page,
			extent_blocks * SWAPZ_BLOCK_BYTES, &owner_token);
		assert(error == -EINVAL);
	} else {
		error = swapz_round035_dm_owned_lz4_lower_roundtrip(
			&ctx, &pinned_bio, &sidecar, &transaction, source_slot,
			copied, private_scratch, lower_image, read_lower,
			decode_scratch, verified_page, candidate, upper_page,
			extent_blocks * SWAPZ_BLOCK_BYTES, &owner_token);
	}
	for (index = 0U; index < SWAPZ_BLOCK_BYTES; ++index)
		assert(disk_data[index] == 0x36U);
	if (fault) {
		assert(error < 0);
		assert(owner_token == 0xdeadbeefU);
		for (index = 0U; index < sizeof(upper_page); ++index)
			assert(upper_page[index] == 0xa5U);
		if (fault == 7U) {
			assert(lower_writes == 1 && lower_reads == 1);
			assert(transaction.upper_write_ack_count == 1U);
			assert(sidecar.slots[5].owner_token == 0U);
		} else {
			assert(lower_writes == 0);
			assert(transaction.upper_write_ack_count == 0U);
		}
	} else {
		assert(error == 0);
		assert(owner_token != 0U && owner_token != 0xdeadbeefU);
		assert(provider_calls == 1 && lower_writes == 1 &&
		       lower_reads == 1 && lower_fua == 1);
		assert(transaction.upper_write_ack_count == 1U);
		assert(sidecar.slots[5].representation_tag ==
		       SWAPZ_ROUND031_SOURCE_LZ4_TAG);
		assert(!sidecar.slots[5].descriptor.mapping.raw);
		assert(memcmp(upper_page, original, SWAPZ_BLOCK_BYTES) == 0);
		assert(memcmp(disk_data + 2U * SWAPZ_BLOCK_BYTES +
			      transaction.compressed_payload_offset,
			      source_lz4_bytes, length) == 0);
		/* Any replay is stale; never issue second hypothetical ACK. */
		assert(swapz_round035_dm_owned_lz4_lower_roundtrip(
			&ctx, &pinned_bio, &sidecar, &transaction, source_slot,
			copied, private_scratch, lower_image, read_lower,
			decode_scratch, verified_page, candidate, upper_page,
			extent_blocks * SWAPZ_BLOCK_BYTES, &owner_token) == -ESTALE);
		assert(lower_writes == 1 &&
		       transaction.upper_write_ack_count == 1U);
	}
	if (fault != 13U) {
		for (index = 0U; index < sizeof(copied); ++index)
			assert(copied[index] == 0U);
		for (index = 0U; index < sizeof(private_scratch); ++index)
			assert(private_scratch[index] == 0U);
	}
	assert(swapz_round031_dm_forget_on_swapoff_or_teardown(
		&ctx, &sidecar) == 0);
	assert(sidecar.slots == NULL && sidecar.closed);
}
int main(void)
{
	unsigned int extent_blocks, fault;
	assert(swapz_round031_fixture_main() == 0);
	for (extent_blocks = 1U; extent_blocks <= 4U; extent_blocks *= 2U)
		for (fault = 0U; fault <= 13U; ++fault)
			run_round035_lower_case(extent_blocks, fault);
	puts("ROUND035_ACTUAL_ORIGINAL_GPL_OWNED_LZ4_FAKE_LOWER_4096_SHA_NO_GO_PASS");
	return 0;
}
