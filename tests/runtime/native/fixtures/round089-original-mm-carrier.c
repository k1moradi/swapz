/* SPDX-License-Identifier: GPL-2.0-only */
/* ABI shim only. Actual staged header/functions and real broker linked.
 * No Linux BIO/SG execution or source authentication implied. */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "zswap-original-ticket.h"

typedef uint64_t sector_t;
typedef uint8_t u8;
struct block_device { unsigned int identity; };
struct page { unsigned int identity; };
struct bio_vec {
	struct page *bv_page;
	unsigned int bv_offset, bv_len;
};
struct bio {
	struct block_device *bi_bdev;
	struct {
		sector_t bi_sector;
		unsigned int bi_size, bi_idx, bi_offset;
	} bi_iter;
	unsigned int bi_vcnt, bi_opf, bi_flags;
	struct bio_vec *bi_io_vec;
	struct swapz_mm_carrier *bi_swapz_original;
};
#define REQ_OP_WRITE 1U
#define REQ_SWAP 256U
#define BIO_CLONED 1U
#define BIO_REMAPPED 2U
static unsigned int bio_op(const struct bio *bio) { return bio->bi_opf & 255U; }
static bool bio_flagged(const struct bio *bio, unsigned int flag) { return !!(bio->bi_flags & flag); }

#define CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST 1
#include "r089-staged-carrier.h"

static unsigned int checks;
#define CHECK(condition) do { \
	++checks; \
	if (!(condition)) { fprintf(stderr, "R089_FIRST_ERROR line=%d %s\n", __LINE__, #condition); return 77; } \
} while (0)

struct race_context {
	pthread_mutex_t queue_lock;
	pthread_barrier_t start;
	struct swapz_ticket_broker *broker;
	struct swapz_ticket_ref *candidate;
	struct swapz_ticket_key key;
	int claim_result, revoke_result;
	unsigned int linked;
};

static void *claim_worker(void *opaque)
{
	struct race_context *race = opaque;
	(void)pthread_barrier_wait(&race->start);
	(void)pthread_mutex_lock(&race->queue_lock);
	race->claim_result = swapz_ticket_claim_under_queue_lock(race->candidate, &race->key);
	if (!race->claim_result)
		++race->linked;
	(void)pthread_mutex_unlock(&race->queue_lock);
	return NULL;
}

static void *revoke_worker(void *opaque)
{
	struct race_context *race = opaque;
	(void)pthread_barrier_wait(&race->start);
	race->revoke_result = swapz_ticket_revoke(race->broker, race->key.table_epoch + 1U);
	return NULL;
}

int main(void)
{
	struct swapz_ticket_broker broker = {0};
	struct swapz_ticket_slot slots[1];
	swapz_u32 indices[1];
	_Alignas(64) swapz_u8 payload[3584];
	swapz_u8 bytes[64];
	struct swapz_ticket_cap cap = {0}, rejected = {0};
	struct swapz_ticket_ref producer = {0}, candidate = {0};
	struct swapz_ticket_view view = {0};
	struct swapz_ticket_usage usage;
	struct swapz_mm_source source = {
		.cookie = 1, .area_epoch = 2, .slot_offset = 3,
		.swap_type = 4, .length = sizeof(bytes), .codec = SWAPZ_TICKET_LZ4
	};
	struct swapz_ticket_key key = {0}, wrong, untouched = {0};
	pthread_mutex_t queue = PTHREAD_MUTEX_INITIALIZER;
	unsigned int linked = 0, race_claimed = 0, race_declined = 0;
	const swapz_u64 session = 17;
	swapz_u64 epoch = 20;

	memset(bytes, 0x5b, sizeof(bytes));
	memset(source.sha256, 0xa5, sizeof(source.sha256));
	source.crc = swapz_crc32c_bytes(bytes, sizeof(bytes));
	CHECK(SWAPZ_MM_SOURCE_SLOTS == 64U);
	CHECK(sizeof(source) <= 80U && sizeof(swapz_u64) == 8U);
	CHECK(swapz_mm_source_index(1) == swapz_mm_source_index(65));
	CHECK(swapz_mm_source_index(UINT64_MAX) == 63U);
	CHECK(!swapz_mm_source_key(&source, 0, 2, 3, 4, 64, &untouched));
	CHECK(!swapz_mm_source_key(&source, 65, 2, 3, 4, 64, &untouched));
	CHECK(!swapz_mm_source_key(&source, 1, 0, 3, 4, 64, &untouched));
	CHECK(!swapz_mm_source_key(&source, 1, 9, 3, 4, 64, &untouched));
	CHECK(!swapz_mm_source_key(&source, 1, 2, 9, 4, 64, &untouched));
	CHECK(!swapz_mm_source_key(&source, 1, 2, 3, 9, 64, &untouched));
	CHECK(!swapz_mm_source_key(&source, 1, 2, 3, 4, 63, &untouched));
	CHECK(!untouched.store_sequence && !untouched.target_session);
	source.codec = 0;
	CHECK(!swapz_mm_source_key(&source, 1, 2, 3, 4, 64, &untouched));
	source.codec = SWAPZ_TICKET_LZ4;
	source.length = 4096;
	CHECK(!swapz_mm_source_key(&source, 1, 2, 3, 4, 4096, &untouched));
	source.length = 0;
	CHECK(!swapz_mm_source_key(&source, 1, 2, 3, 4, 0, &untouched));
	source.length = sizeof(bytes);
	CHECK(swapz_mm_source_key(&source, 1, 2, 3, 4, 64, &key));
	CHECK(key.area_epoch == 2 && key.store_sequence == 1 && key.slot_offset == 3);
	CHECK(key.decoded_length == 4096 && key.crc == source.crc && key.version == 1);
	CHECK(!memcmp(key.sha256, source.sha256, sizeof(key.sha256)));
	CHECK(!key.target_session && !key.table_epoch && !key.target_epoch &&
		!key.logical_page && !key.dm_generation && !key.dictionary);
	source.cookie = 65;
	CHECK(!swapz_mm_source_key(&source, 1, 2, 3, 4, 64, &untouched));
	CHECK(swapz_mm_source_key(&source, 65, 2, 3, 4, 64, &key));
	key.target_session = session;
	key.table_epoch = epoch;
	key.target_epoch = 9;
	key.logical_page = 11;
	key.dm_generation = 13;
	CHECK(!swapz_ticket_init(&broker, slots, sizeof(slots), payload, sizeof(payload),
		indices, sizeof(indices), 1, 3568, sizeof(bytes), session, epoch));
	CHECK(swapz_ticket_broker_try_get(&broker, session + 1, epoch, &rejected) == -ESTALE);
	CHECK(swapz_ticket_broker_try_get(&broker, session, epoch + 1, &rejected) == -ESTALE);
	CHECK(!rejected.broker);
	CHECK(!pthread_mutex_lock(&broker.lock));
	CHECK(swapz_ticket_broker_try_get(&broker, session, epoch, &rejected) == -EAGAIN);
	CHECK(!pthread_mutex_unlock(&broker.lock));
	CHECK(!swapz_ticket_broker_try_get(&broker, session, epoch, &cap));
	CHECK(cap.broker == &broker && cap.session == session && cap.epoch == epoch);
	CHECK(swapz_ticket_broker_try_get(&broker, session, epoch, &cap) == -EINVAL);
	CHECK(!swapz_ticket_reserve(&broker, &key, &producer));
	CHECK(!swapz_ticket_seal(&producer, bytes, sizeof(bytes)));
	CHECK(!swapz_ticket_retain(&producer, &candidate));
	CHECK(!pthread_mutex_lock(&queue));
	CHECK(!pthread_mutex_lock(&broker.lock));
	CHECK(swapz_ticket_claim_under_queue_lock(&candidate, &key) == -EAGAIN);
	CHECK(!pthread_mutex_unlock(&broker.lock));
	wrong = key;
	++wrong.dm_generation;
	CHECK(swapz_ticket_claim_under_queue_lock(&candidate, &wrong) == -ESTALE);
	CHECK(!swapz_ticket_claim_under_queue_lock(&candidate, &key));
	++linked;
	CHECK(swapz_ticket_claim_under_queue_lock(&candidate, &key) == -EALREADY);
	CHECK(!pthread_mutex_unlock(&queue));
	CHECK(linked == 1);
	CHECK(!swapz_ticket_revoke(&broker, ++epoch));
	CHECK(swapz_ticket_claim_under_queue_lock(&candidate, &key) == -ESTALE);
	CHECK(swapz_ticket_broker_try_get(&broker, session, epoch - 1, &rejected) == -ESTALE);
	CHECK(!swapz_ticket_view(&candidate, &view) && view.bytes[0] == bytes[0]);
	CHECK(!swapz_ticket_put(&producer));
	CHECK(!swapz_ticket_put(&candidate));
	CHECK(!swapz_ticket_usage(&broker, &usage) && !usage.live_slots && !usage.reserved_bytes);

	for (unsigned int index = 0; index < 32U; ++index) {
		struct race_context race = {
			.broker = &broker, .candidate = &candidate, .key = key,
			.claim_result = -EINVAL, .revoke_result = -EINVAL
		};
		pthread_t claimant, revoker;
		race.key.table_epoch = epoch;
		race.key.store_sequence += (swapz_u64)index + 1U;
		CHECK(!swapz_ticket_reserve(&broker, &race.key, &producer));
		CHECK(!swapz_ticket_seal(&producer, bytes, sizeof(bytes)));
		CHECK(!swapz_ticket_retain(&producer, &candidate));
		CHECK(!pthread_mutex_init(&race.queue_lock, NULL));
		CHECK(!pthread_barrier_init(&race.start, NULL, 2));
		CHECK(!pthread_create(&claimant, NULL, claim_worker, &race));
		CHECK(!pthread_create(&revoker, NULL, revoke_worker, &race));
		CHECK(!pthread_join(claimant, NULL));
		CHECK(!pthread_join(revoker, NULL));
		CHECK(!race.revoke_result);
		++epoch;
		CHECK(race.claim_result == 0 || race.claim_result == -EAGAIN ||
			race.claim_result == -ESTALE);
		CHECK(race.linked == (race.claim_result == 0 ? 1U : 0U));
		if (!race.claim_result)
			++race_claimed;
		else
			++race_declined;
		CHECK(!pthread_mutex_lock(&race.queue_lock));
		CHECK(swapz_ticket_claim_under_queue_lock(&candidate, &race.key) == -ESTALE);
		CHECK(!pthread_mutex_unlock(&race.queue_lock));
		CHECK(!swapz_ticket_put(&producer));
		CHECK(!swapz_ticket_put(&candidate));
		CHECK(!pthread_barrier_destroy(&race.start));
		CHECK(!pthread_mutex_destroy(&race.queue_lock));
		CHECK(!swapz_ticket_usage(&broker, &usage) && !usage.live_slots && !usage.reserved_bytes);
	}
	CHECK(race_claimed + race_declined == 32U);
	CHECK(swapz_ticket_close(&broker) == -EBUSY);
	CHECK(swapz_ticket_destroy(&broker) == -EBUSY);
	CHECK(swapz_ticket_broker_try_get(&broker, session, epoch, &rejected) == -ESTALE);
	CHECK(!swapz_ticket_broker_put(&cap));
	CHECK(!cap.broker && swapz_ticket_broker_put(&cap) == -EALREADY);
	CHECK(!swapz_ticket_close(&broker));
	CHECK(!swapz_ticket_destroy(&broker));
	CHECK(!pthread_mutex_destroy(&queue));
	printf("PASS_HOST_ONLY R089 actual broker/sparse helpers checks=%u races=32 claimed=%u declined=%u source=%zu cookie=%zu cap=%zu carrier=%zu broker=%zu\n",
		checks, race_claimed, race_declined, sizeof(source), sizeof(swapz_u64),
		sizeof(cap), sizeof(struct swapz_mm_carrier), sizeof(broker));
	return 0;
}
