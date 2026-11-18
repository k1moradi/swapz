/*
 * Round034: actual src/kernel/dm-target.c PRE-FLIGHT source C execution.
 * The runner injects the actual prior Round033 GPL consumer and new Round034
 * bodies; only original kernel BIO/authority boundaries are host-faked.
 * Synthetic source+sidecar agreement is NEVER original MM authentication.
 */
#define REQ_OP_READ 0U
#define REQ_OP_WRITE 1U
#define REQ_OP_DISCARD 3U
#define REQ_SWAP 0x100U
#define REQ_PREFLUSH 0x200U
#define SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK 1U
#define SWAPZ_SECTORS 8U
#define SWAPZ_ROUND031_SOURCE_LZ4_TAG 3U
#define MAX_SWAPFILES 30U

struct bio_vec { void *bv_page; unsigned int bv_offset, bv_len; };
struct dm_target { uint64_t len; };
struct swapz_map {
	bool valid, raw;
	swapz_u32 generation, payload_length, payload_crc32c, start_block;
};
struct swapz_source_record {
	swapz_u32 logical_page, generation, compressed_length, compressed_crc32c;
	swapz_u32 dictionary_id, gc_epoch;
	swapz_u64 store_generation, stored_entry_identity;
	bool immutable_owned_copy, stored_eviction;
	swapz_u8 original_sha256[32];
};
struct swapz_source_descriptor {
	struct swapz_source_record record;
	struct swapz_map mapping;
	swapz_u64 source_swap_slot;
	swapz_u32 extent_sequence;
	bool published;
	swapz_u8 hypothetical_ack_count;
};
struct swapz_round031_dm_sidecar_slot {
	struct swapz_source_descriptor descriptor;
	swapz_u64 owner_token;
	swapz_u32 representation_tag;
	swapz_u32 readers;
};
struct swapz_round031_dm_sidecar {
	struct swapz_round031_dm_sidecar_slot *slots;
	swapz_u32 capacity;
	size_t allocated_bytes;
	bool closed;
};
struct swapz_authority {
	struct swapz_map *maps;
	swapz_u32 logical_pages, gc_allocation, batch_pending, batch_replaying;
	swapz_u32 in_flight;
};
struct swapz_dm {
	struct dm_target *target;
	struct swapz_map *maps;
	struct swapz_authority authority;
	struct { bool active; } gc_recovery;
	swapz_u32 logical_pages;
	bool failed, accepting, ordered_owner;
};
typedef struct { unsigned long val; } swp_entry_t;
typedef unsigned long pgoff_t;
#define SWP_TYPE_SHIFT 59U
#define SWP_OFFSET_MASK ((1UL << SWP_TYPE_SHIFT) - 1UL)
static swp_entry_t swp_entry(unsigned long source_type, pgoff_t source_offset)
{
	swp_entry_t entry = { .val = (source_type << SWP_TYPE_SHIFT) |
				       (source_offset & SWP_OFFSET_MASK) };
	return entry;
}
static unsigned int swp_type(swp_entry_t source_entry)
{
	return (unsigned int)(source_entry.val >> SWP_TYPE_SHIFT);
}
static pgoff_t swp_offset(swp_entry_t source_entry)
{
	return source_entry.val & SWP_OFFSET_MASK;
}
#define smp_load_acquire(pointer) (*(pointer))
#define lockdep_assert_held(pointer) assert(*(pointer))
#define bio_op(source_bio) ((source_bio)->bi_opf & 15U)
#define bio_sectors(source_bio) ((source_bio)->bi_iter.bi_size / 512U)
#define bio_iter_iovec(source_bio, iteration) (*(source_bio)->bi_io_vec)
static swapz_u32 current_extent_sequence = 77U;
static int swapz_extent_sequence_lookup(
		const struct swapz_authority *authority, swapz_u32 start_block,
		swapz_u32 *sequence)
{
	(void)authority;
	if (start_block != 2U)
		return -ESTALE;
	*sequence = current_extent_sequence;
	return 0;
}
static bool swapz_zswap_import_ranges_overlap(
		const void *first, size_t first_length,
		const void *second, size_t second_length)
{
	const uintptr_t begin_first = (uintptr_t)first;
	const uintptr_t begin_second = (uintptr_t)second;
	if (!first || !second)
		return false;
	if (first_length > UINTPTR_MAX - begin_first ||
	    second_length > UINTPTR_MAX - begin_second)
		return true;
	return begin_first < begin_second + second_length &&
		begin_second < begin_first + first_length;
}
static struct swapz_dm *mutable_context;
static struct swapz_round031_dm_sidecar_slot *mutable_slot;
static void change_map_after_provider_copy(void)
{
	++mutable_context->authority.maps[5].generation;
}
static void change_owner_after_provider_copy(void)
{
	++mutable_slot->owner_token;
}
/* ROUND034_EXACT_PRODUCTION_SOURCE */

static void run_round034_real_source_host(void)
{
	struct dm_target target = { .len = 512U };
	struct swapz_map maps[64] = { 0 };
	struct swapz_round031_dm_sidecar_slot slots[64] = { 0 };
	struct swapz_round031_dm_sidecar sidecar = {
		.slots = slots, .capacity = 64U, .allocated_bytes = sizeof(slots)
	};
	struct swapz_dm context = {
		.target = &target, .maps = maps,
		.authority = { .maps = maps, .logical_pages = 64U },
		.logical_pages = 64U, .accepting = true, .ordered_owner = true
	};
	struct bio_vec source_vector = {
		.bv_page = source_lz4_bytes, .bv_offset = 0U,
		.bv_len = SWAPZ_BLOCK_BYTES
	};
	struct bio original_bio = {
		.lifetime_pinned = true,
		.full_uncompressed_4096_swap_write = true,
		.bi_iter = { .bi_sector = 5U * SWAPZ_SECTORS,
			     .bi_size = SWAPZ_BLOCK_BYTES,
			     .bi_idx = 0U, .bi_offset = 0U },
		.bi_io_vec = &source_vector, .bi_bdev = &target,
		.bi_vcnt = 0U, .bi_opf = REQ_OP_WRITE | REQ_SWAP,
		.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK
	};
	struct swapz_round032_dm_owned_view_v1 owned_view = { 0 };
	struct swapz_round032_dm_owned_view_v1 final_view = { 0 };
	struct swapz_round034_dm_source_observation observation = { 0 };
	struct swapz_round034_dm_source_observation observation_before = { 0 };
	swapz_u8 original_page[SWAPZ_BLOCK_BYTES];
	swapz_u8 owned_bytes[SWAPZ_MAX_COMPRESSED], byte_before[SWAPZ_MAX_COMPRESSED];
	swapz_u8 final_bytes[SWAPZ_MAX_COMPRESSED], final_before[SWAPZ_MAX_COMPRESSED];
	swapz_u8 provider_copy[SWAPZ_MAX_COMPRESSED];
	swapz_u8 provider_scratch[SWAPZ_MAX_COMPRESSED];
	swapz_u8 mechanical_candidate[SWAPZ_MAX_COMPRESSED];
	struct swapz_round031_dm_sidecar_slot *slot = &slots[5];
	const swapz_u64 token = 4412U;
	const swp_entry_t original_entry = swp_entry(2U, 39U);
	unsigned int check_index;
	int compressed_length;
	int status;

	assert(original_entry.val != 5U && swp_type(original_entry) == 2U);
	assert(swp_offset(original_entry) == 39U);
	memset(original_page, 0x19, sizeof(original_page));
	original_page[21] = 0x42U;
	original_page[3022] = 0x67U;
	compressed_length = LZ4_compress_default(
		(const char *)original_page, (char *)source_lz4_bytes,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
	assert(compressed_length > 0 && compressed_length <= 3568);
	source_lz4_length = (swapz_u16)compressed_length;
	original_provider_view.source_swap_entry = original_entry.val;
	original_provider_view.source_slot_epoch = 9001U;
	original_provider_view.stored_entry_identity = 7009U;
	original_provider_view.compressed_length = source_lz4_length;
	original_provider_view.decoded_length = SWAPZ_BLOCK_BYTES;
	original_provider_view.compressed_crc32c = swapz_crc32c_bytes(
		source_lz4_bytes, source_lz4_length);
	original_provider_view.representation_version = 1U;
	original_provider_view.codec = 1U;
	assert(SHA256(original_page, SWAPZ_BLOCK_BYTES,
		      original_provider_view.original_sha256) != NULL);
	maps[5].valid = true;
	maps[5].raw = false;
	maps[5].generation = 105U;
	maps[5].start_block = 2U;
	maps[5].payload_length = source_lz4_length;
	maps[5].payload_crc32c = original_provider_view.compressed_crc32c;
	slot->owner_token = token;
	slot->representation_tag = SWAPZ_ROUND031_SOURCE_LZ4_TAG;
	slot->descriptor.published = true;
	slot->descriptor.hypothetical_ack_count = 1U;
	slot->descriptor.mapping = maps[5];
	slot->descriptor.extent_sequence = current_extent_sequence;
	slot->descriptor.source_swap_slot = original_entry.val;
	slot->descriptor.record.logical_page = 5U;
	slot->descriptor.record.generation = maps[5].generation;
	slot->descriptor.record.compressed_length = source_lz4_length;
	slot->descriptor.record.compressed_crc32c = original_provider_view.compressed_crc32c;
	slot->descriptor.record.store_generation = original_provider_view.source_slot_epoch;
	slot->descriptor.record.stored_entry_identity = original_provider_view.stored_entry_identity;
	slot->descriptor.record.dictionary_id = 0U;
	slot->descriptor.record.gc_epoch = 11U;
	slot->descriptor.record.immutable_owned_copy = true;
	slot->descriptor.record.stored_eviction = true;
	memcpy(slot->descriptor.record.original_sha256,
	       original_provider_view.original_sha256, 32U);
	mutable_context = &context;
	mutable_slot = slot;
	/* The fake provider can race the post-copy map/owner snapshot;
	 * no real worker thread or production BIO is used by this fixture. */

#define PREFLIGHT() swapz_round034_dm_source_mechanical_preflight( \
	&context, &original_bio, &sidecar, token, &owned_view, \
	owned_bytes, sizeof(owned_bytes), &observation, \
	provider_copy, sizeof(provider_copy), \
	provider_scratch, sizeof(provider_scratch))
#define AUTHENTICATE() swapz_round034_dm_try_authenticate_source_slot( \
	&context, &original_bio, &sidecar, token, &final_view, \
	final_bytes, sizeof(final_bytes), \
	mechanical_candidate, sizeof(mechanical_candidate), \
	provider_copy, sizeof(provider_copy), \
	provider_scratch, sizeof(provider_scratch))
#define PREPARE_NEGATIVE() do { \
	memset(owned_bytes, 0x5a, sizeof(owned_bytes)); \
	memset(&owned_view, 0x5b, sizeof(owned_view)); \
	memset(&observation, 0x5c, sizeof(observation)); \
	memcpy(byte_before, owned_bytes, sizeof(byte_before)); \
	memcpy(&observation_before, &observation, sizeof(observation)); \
} while (0)
#define ASSERT_NEGATIVE() do { \
	assert(PREFLIGHT() < 0); \
	assert(memcmp(owned_bytes, byte_before, sizeof(owned_bytes)) == 0); \
	assert(memcmp(&observation, &observation_before, sizeof(observation)) == 0); \
	for (check_index = 0; check_index < sizeof(provider_copy); ++check_index) \
		assert(provider_copy[check_index] == 0U); \
} while (0)

	assert(PREFLIGHT() == 0);
	assert(observation.state == SWAPZ_ROUND034_SOURCE_COPY_MECHANICALLY_VALID);
	assert(observation.state != SWAPZ_ROUND034_SOURCE_MAPPED_AUTHENTICATED);
	assert(observation.source_swap_entry == original_entry.val);
	assert(observation.source_swap_type == 2U);
	assert(observation.source_swap_offset == 39U);
	assert(observation.logical_page == 5U);
	assert(observation.source_swap_offset != observation.logical_page);
	assert(observation.map_generation == 105U);
	assert(observation.extent_sequence == current_extent_sequence);
	assert(observation.current_owner_token == token);
	assert(memcmp(owned_bytes, source_lz4_bytes, source_lz4_length) == 0);
	assert(memcmp(owned_view.original_sha256,
		      original_provider_view.original_sha256, 32U) == 0);
	memset(final_bytes, 0x63, sizeof(final_bytes));
	memset(&final_view, 0x64, sizeof(final_view));
	memcpy(final_before, final_bytes, sizeof(final_before));
	assert(AUTHENTICATE() == -EOPNOTSUPP);
	assert(memcmp(final_bytes, final_before, sizeof(final_bytes)) == 0);
	assert(final_view.compressed_length == 0x6464U); /* unchanged */
	for (check_index = 0; check_index < sizeof(mechanical_candidate); ++check_index)
		assert(mechanical_candidate[check_index] == 0U);

	/* This synthetic successful source copy is not type/area/epoch
	 * provenance; hostile wrong packed type with identical offset must
	 * disagree with the old volatile descriptor and refuse.
	 */
	original_provider_view.source_swap_entry = swp_entry(3U, 39U).val;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_provider_view.source_swap_entry = original_entry.val;
	original_provider_view.source_slot_epoch++;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_provider_view.source_slot_epoch--;
	original_provider_view.stored_entry_identity++;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_provider_view.stored_entry_identity--;
	original_provider_view.source_swap_entry = swp_entry(2U, 0U).val;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_provider_view.source_swap_entry = original_entry.val;
	original_provider_view.representation_version = 2U;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_provider_view.representation_version = 1U;
	original_provider_view.codec = 2U;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_provider_view.codec = 1U;
	original_provider_view.compressed_length = 3569U;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_provider_view.compressed_length = source_lz4_length;
	original_provider_view.compressed_crc32c ^= 1U;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_provider_view.compressed_crc32c ^= 1U;
	source_lz4_bytes[0] ^= 1U;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	source_lz4_bytes[0] ^= 1U;
	memset(original_provider_view.original_sha256, 0U, 32U);
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	assert(SHA256(original_page, SWAPZ_BLOCK_BYTES,
		      original_provider_view.original_sha256) != NULL);
	slot->descriptor.hypothetical_ack_count = 2U;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	slot->descriptor.hypothetical_ack_count = 1U;
	slot->owner_token++;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	slot->owner_token--;
	current_extent_sequence++;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	current_extent_sequence--;
	provider_after_copy = change_map_after_provider_copy;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	provider_after_copy = NULL;
	--maps[5].generation;
	provider_after_copy = change_owner_after_provider_copy;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	provider_after_copy = NULL;
	--slot->owner_token;
	maps[5].generation++;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	maps[5].generation--;
	context.gc_recovery.active = true;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	context.gc_recovery.active = false;
	context.authority.in_flight = 1U;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	context.authority.in_flight = 0U;
	original_bio.bi_opf = REQ_OP_READ | REQ_SWAP;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_bio.bi_opf = REQ_OP_WRITE;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_bio.bi_opf = REQ_OP_DISCARD | REQ_SWAP;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_bio.bi_opf = REQ_OP_WRITE | REQ_SWAP;
	original_bio.bi_swap_origin = 0U;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_bio.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;
	original_bio.bi_vcnt = 1U; /* Round032 synthetic, original has zero */
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_bio.bi_vcnt = 0U;
	original_bio.bi_iter.bi_size = 2048U;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_bio.bi_iter.bi_size = SWAPZ_BLOCK_BYTES;
	source_vector.bv_len = 2048U;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	source_vector.bv_len = SWAPZ_BLOCK_BYTES;
	original_bio.bi_iter.bi_sector = 0U; /* SWAPSPACE2 4096 header */
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_bio.bi_iter.bi_sector = target.len; /* non-linear/foreign bound */
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_bio.bi_iter.bi_sector = 5U * SWAPZ_SECTORS + 1U;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_bio.bi_iter.bi_sector = 5U * SWAPZ_SECTORS;
	original_bio.lifetime_pinned = false;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_bio.lifetime_pinned = true;
	slot->descriptor.source_swap_slot = 0U;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	slot->descriptor.source_swap_slot = original_entry.val;
	original_bio.bi_bdev = NULL;
	PREPARE_NEGATIVE(); ASSERT_NEGATIVE();
	original_bio.bi_bdev = &target;

	assert(PREFLIGHT() == 0);
	assert(observation.state == SWAPZ_ROUND034_SOURCE_COPY_MECHANICALLY_VALID);
	assert(AUTHENTICATE() == -EOPNOTSUPP);
	assert(provider_calls > 10);
	puts("ROUND034_ACTUAL_SOURCE_SLOT_SWP_TYPE_OFFSET_MECHANICAL_ONLY_AUTH_NO_GO_PASS");
#undef PREFLIGHT
#undef AUTHENTICATE
#undef PREPARE_NEGATIVE
#undef ASSERT_NEGATIVE
}
int main(void)
{
	run_round034_real_source_host();
	return 0;
}
