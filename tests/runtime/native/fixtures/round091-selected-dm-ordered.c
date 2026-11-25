// SPDX-License-Identifier: GPL-2.0-only
/* Reuse the frozen real shared-authority fixture's arrays and RAM lower
 * callbacks, but replace its modeled decoder with the frozen real bridge.
 * Synthetic selected provenance and upper-owner markers, never kernel AUTH.
 */
#define main round090_storage_fixture_main
#include "round089-shared-original-storage.c"
#undef main
#include "zswap-original-ticket.h"
#include "zswap-original-decoder-bridge.h"
#include "ordered-fragments.h"

static struct swapz_original_decoder_bridge real_bridge;
static struct swapz_ticket_broker broker;
static struct swapz_ticket_slot slots[2];
static swapz_u32 free_indices[2];
static _Alignas(64) swapz_u8 broker_bytes[2U * 3584U];
static swapz_u8 original_page[SWAPZ_BLOCK_BYTES], decode_scratch[SWAPZ_BLOCK_BYTES],
	verified_page[SWAPZ_BLOCK_BYTES], compressed_read[SWAPZ_BLOCK_BYTES];
static pthread_mutex_t queue_lock = PTHREAD_MUTEX_INITIALIZER;
static unsigned int positive_claims, refusals, typed_reads, terminal_owners;

int round085_compress(swapz_u8 codec, const swapz_u8 *page, swapz_u32 length,
	swapz_u8 *compressed, swapz_u32 capacity, swapz_u32 *written);

struct accepted_head {
	struct swapz_ticket_ref ref;
	struct swapz_ticket_key key;
	unsigned int links, attempts;
	bool claimed;
};

/* Synthetic selected-DM adapter, real broker API and actual one-shot state.
 * The frozen header's old link-after-claim requirement prevents live use.
 * This proof exercises the revised same-descriptor transition in isolation.
 */
static int claim_accepted_head(void *opaque, swapz_u32 credit)
{
	struct accepted_head *head = opaque;
	int result;

	CHECK(authority.in_flight && storage.pending_decoder);
	CHECK(credit && authority.active_sequence == credit);
	CHECK(head->links == 1U && !head->claimed);
	CHECK(!pthread_mutex_lock(&queue_lock));
	++head->attempts;
	result = swapz_ticket_claim_under_queue_lock(&head->ref, &head->key);
	if (!result)
		head->claimed = true;
	CHECK(!pthread_mutex_unlock(&queue_lock));
	return result;
}

enum scenario {
	COMMIT_OK, WRONG_KEY, BUSY_BROKER, STALE_GENERATION,
	FLUSH_ERROR, SHORT_WRITE, BAD_DIGEST
};

static void exercise(swapz_u8 codec, enum scenario scenario)
{
	struct swapz_original_storage_ops lower = {
		.context = &storage, .write = write_lower, .read = read_lower,
		.flush = flush_lower,
	}, wrapped;
	struct swapz_ticket_ref source = {0};
	struct swapz_ticket_view view = {0};
	struct accepted_head head = { .links = 1U };
	struct swapz_authority_import_spec spec = {0};
	struct swapz_original_extent_input input = {0};
	struct swapz_map predecessor;
	swapz_u32 compressed_length, segment, index;
	unsigned long long abandoned;
	int error = -123;
	bool handled;
	bool claimed = scenario == COMMIT_OK || scenario == FLUSH_ERROR ||
		scenario == SHORT_WRITE || scenario == BAD_DIGEST;

	reset();
	CHECK(!swapz_shared_storage_close(&storage));
	memset(&real_bridge, 0, sizeof(real_bridge));
	CHECK(!swapz_original_decoder_bridge_init(&real_bridge, &lower, &wrapped));
	CHECK(!swapz_shared_storage_init(&storage, &authority, &wrapped));
	raw(0); /* real allocator establishes an OPEN segment and generation 1 */
	predecessor = maps[0];
	abandoned = authority.abandoned_blocks;
	for (index = 0; index < sizeof(original_page); ++index)
		original_page[index] = (swapz_u8)(index % 127U == 0U ? 0x5aU : 0U);
	CHECK(!round085_compress(codec, original_page, SWAPZ_BLOCK_BYTES,
				 bytes, sizeof(bytes), &compressed_length));
	CHECK(compressed_length && compressed_length <= SWAPZ_ORIGINAL_DECODE_M3568);
	memset(&broker, 0, sizeof(broker));
	CHECK(!swapz_ticket_init(&broker, slots, sizeof(slots), broker_bytes,
		sizeof(broker_bytes), free_indices, sizeof(free_indices),
		2U, 3568U, 7136U, 17U, 23U));
	head.key = (struct swapz_ticket_key){
		.area_epoch = 3U, .store_sequence = 4U, .slot_offset = 8U,
		.target_session = 17U, .table_epoch = 23U, .target_epoch = 9U,
		.logical_page = 0U, .dm_generation = 2U, .length = compressed_length,
		.decoded_length = SWAPZ_BLOCK_BYTES,
		.representation = SWAPZ_TICKET_ORIGINAL, .codec = codec, .version = 1U,
		.crc = swapz_crc32c_bytes(bytes, compressed_length),
	};
	CHECK(!swapz_zswap_import_sha256(original_page, head.key.sha256));
	if (scenario == BAD_DIGEST)
		head.key.sha256[0] ^= 1U;
	CHECK(!swapz_ticket_reserve(&broker, &head.key, &source));
	CHECK(!swapz_ticket_seal(&source, bytes, compressed_length));
	CHECK(!swapz_ticket_retain(&source, &head.ref));
	CHECK(!swapz_ticket_view(&head.ref, &view));
	CHECK(!swapz_ticket_put(&source));
	CHECK(slots[head.ref.index].state == SWAPZ_TICKET_SEALED);
	spec = (struct swapz_authority_import_spec){
		.source_swap_slot = view.key.slot_offset,
		.source_entry_identity = view.key.area_epoch,
		.source_store_generation = view.key.store_sequence,
		.gc_epoch = 1U, .logical_page = 0U,
		.compressed_crc32c = view.key.crc,
		.compressed_length = (swapz_u16)compressed_length,
		.codec = codec, .codec_version = 1U, .requested_fua = 1U,
	};
	memcpy(spec.original_sha256, view.key.sha256, sizeof(spec.original_sha256));
	input = (struct swapz_original_extent_input){
		.bytes = view.bytes, .bytes_available = compressed_length,
		.logical_page = 0U, .generation = 2U, .length = compressed_length,
		.decoded_length = SWAPZ_BLOCK_BYTES, .crc32c = view.key.crc,
		.representation = SWAPZ_TICKET_ORIGINAL, .codec = codec, .version = 1U,
	};
	if (scenario == WRONG_KEY)
		head.key.store_sequence++;
	if (scenario == BUSY_BROKER)
		CHECK(!pthread_mutex_lock(&broker.lock));
	if (scenario == STALE_GENERATION)
		input.generation--;
	if (scenario == FLUSH_ERROR)
		fail_flush = -EIO;
	if (scenario == SHORT_WRITE)
		short_write = 1;
	handled = swapz_round091_reserve_claim_commit(&storage, &spec, &input,
						    claim_accepted_head, &head, &error);
	if (scenario == BUSY_BROKER)
		CHECK(!pthread_mutex_unlock(&broker.lock));
	CHECK(head.links == 1U && head.claimed == claimed);
	CHECK(head.attempts == (scenario == STALE_GENERATION ? 0U : 1U));
	CHECK(!authority.in_flight && !storage.pending_decoder);
	CHECK(handled == claimed);
	if (handled) {
		++terminal_owners; /* test owner only, NOT an actual BIO ACK */
		++positive_claims;
		CHECK(slots[head.ref.index].state == SWAPZ_TICKET_CLAIMED);
		CHECK(writes == 1U);
		CHECK(flushes == (scenario == SHORT_WRITE ? 0U : 1U));
	} else {
		++refusals;
		CHECK(slots[head.ref.index].state == SWAPZ_TICKET_SEALED);
		CHECK(!writes && !flushes && !real_bridge.active_tokens);
		CHECK(authority.abandoned_blocks == abandoned +
			(scenario == STALE_GENERATION ? 0U : 1U));
	}
	if (scenario == COMMIT_OK || scenario == BAD_DIGEST) {
		CHECK(!error && maps[0].generation == 2U);
		CHECK(maps[0].state & SWAPZ_MAP_ORIGINAL);
		CHECK(real_bridge.active_tokens == 1U);
		segment = maps[0].start_block / SWAPZ_SEGMENT_BLOCKS;
		memset(output, 0xa5, sizeof(output));
		error = swapz_round091_read_original(&authority, &storage, &real_bridge,
			0U, compressed_read, decode_scratch, verified_page, output);
		if (scenario == BAD_DIGEST) {
			CHECK(error == -EBADMSG);
			for (index = 0; index < sizeof(output); ++index)
				CHECK(output[index] == 0xa5U);
		} else {
			CHECK(!error && !memcmp(output, original_page, sizeof(output)));
			++typed_reads;
			media[maps[0].start_block][0] ^= 1U;
			memset(output, 0xa5, sizeof(output));
			CHECK(swapz_round091_read_original(&authority, &storage, &real_bridge,
				0U, compressed_read, decode_scratch, verified_page, output) == -EBADMSG);
			for (index = 0; index < sizeof(output); ++index)
				CHECK(output[index] == 0xa5U);
			media[maps[0].start_block][0] ^= 1U;
		}
		CHECK(!swapz_shared_original_segment_pinned(&authority, segment));
		CHECK(!real_bridge.active_reads && real_bridge.active_tokens == 1U);
	} else {
		CHECK(!memcmp(&predecessor, &maps[0], sizeof(predecessor)));
		CHECK(!real_bridge.active_tokens);
		if (claimed)
			CHECK(error == -EIO);
	}
	CHECK(!swapz_ticket_put(&head.ref));
	CHECK(!swapz_ticket_close(&broker));
	CHECK(!swapz_ticket_destroy(&broker));
	discard(0);
	CHECK(!real_bridge.active_tokens && !real_bridge.active_reads);
	CHECK(!swapz_shared_storage_close(&storage));
	CHECK(!swapz_original_decoder_bridge_close(&real_bridge));
}

int main(void)
{
	exercise(1U, COMMIT_OK);
	exercise(2U, COMMIT_OK);
	exercise(1U, WRONG_KEY);
	exercise(2U, BUSY_BROKER);
	exercise(1U, STALE_GENERATION);
	exercise(1U, FLUSH_ERROR);
	exercise(2U, SHORT_WRITE);
	exercise(2U, BAD_DIGEST);
	CHECK(positive_claims == 5U && refusals == 3U && typed_reads == 2U &&
	      terminal_owners == 5U);
	CHECK(sizeof(struct swapz_map) == 20U && SWAPZ_SHARED_ORIGINAL_ACTIVE == 0U &&
	      SWAPZ_ORIGINAL_DECODER_BRIDGE_ACTIVE == 0U);
	printf("PASS ROUND091_ORDERED checks=%u claims=%u refusals=%u typed_reads=%u terminal_owners=%u AUTH0\n",
	       checks, positive_claims, refusals, typed_reads, terminal_owners);
	return 0;
}
