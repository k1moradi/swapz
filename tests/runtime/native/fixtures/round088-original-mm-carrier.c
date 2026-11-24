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
#include "r088-staged-carrier.h"
#include "r088-staged-functions.h"

static unsigned int checks;
#define CHECK(condition) do { \
	++checks; \
	if (!(condition)) { fprintf(stderr, "R088_FIRST_ERROR line=%d %s\n", __LINE__, #condition); return 77; } \
} while (0)

int main(void)
{
	struct swapz_ticket_broker broker = {0};
	struct swapz_ticket_slot slots[1];
	swapz_u32 indices[1];
	_Alignas(64) swapz_u8 payload[3584];
	struct swapz_mm_carrier carrier = {0};
	struct swapz_mm_carrier *producer = &carrier, *ctx = NULL, *sio = NULL;
	struct swapz_ticket_key key = {
		.area_epoch = 1, .store_sequence = 2, .slot_offset = 3,
		.target_session = 4, .table_epoch = 5, .target_epoch = 6,
		.logical_page = 7, .dm_generation = 8, .swap_type = 1,
		.length = 64, .decoded_length = 4096,
		.representation = SWAPZ_TICKET_ORIGINAL, .codec = SWAPZ_TICKET_LZ4,
		.version = 1
	};
	struct swapz_ticket_ref candidate = {0};
	struct swapz_ticket_view view = {0};
	struct swapz_ticket_usage usage;
	struct block_device bdev = {1}, wrong_bdev = {2};
	struct page page = {1}, wrong_page = {2};
	struct bio_vec vec = {&page, 0, 4096};
	struct bio origin = {
		.bi_bdev = &bdev, .bi_iter = {56,4096,0,0}, .bi_vcnt = 1,
		.bi_opf = REQ_OP_WRITE | REQ_SWAP, .bi_io_vec = &vec,
		.bi_swapz_original = &carrier
	};
	struct bio variant;

	CHECK(swapz_mm_profile("lz4", "lz4-scomp") == SWAPZ_TICKET_LZ4);
	CHECK(swapz_mm_profile("lzo", "lzo-scomp") == SWAPZ_TICKET_LZO1X);
	CHECK(!swapz_mm_profile("lzo-rle", "lzo-rle-scomp"));
	CHECK(!swapz_mm_profile("lz4", "other-driver"));
	CHECK(!swapz_mm_profile("lzo", "lz4-scomp"));
	memset(carrier.scratch, 0x5b, sizeof(carrier.scratch));
	key.crc = swapz_crc32c_bytes(carrier.scratch, key.length);
	CHECK(!swapz_ticket_init(&broker, slots, sizeof(slots), payload, sizeof(payload),
		indices, sizeof(indices), 1, 3568, 64, 4, 5));
	CHECK(!swapz_ticket_reserve(&broker, &key, &carrier.lease));
	CHECK(!swapz_ticket_seal(&carrier.lease, carrier.scratch, key.length));
	carrier.bdev = &bdev;
	carrier.page = &page;
	carrier.sector = 56;
	CHECK(!swapz_mm_move(&producer, &producer));
	CHECK(!swapz_mm_move(&ctx, &sio));
	CHECK(swapz_mm_move(&ctx, &producer));
	CHECK(!producer && ctx == &carrier);
	CHECK(swapz_mm_move(&sio, &ctx));
	CHECK(!ctx && sio == &carrier);
	CHECK(!swapz_mm_move(&sio, &producer));
	CHECK(!swapz_mm_bio_matches(NULL, &carrier));
	CHECK(!swapz_mm_bio_matches(&origin, NULL));
	CHECK(swapz_mm_bio_matches(&origin, &carrier));
	CHECK(swapz_mm_candidate_get(NULL, &candidate) == -EINVAL);
	CHECK(swapz_mm_candidate_get(&origin, NULL) == -EINVAL);
#define DECLINE(field, value) do { \
	variant = origin; variant.field = (value); \
	CHECK(swapz_mm_candidate_get(&variant, &candidate) == -EOPNOTSUPP); \
	CHECK(!candidate.broker); \
} while (0)
	DECLINE(bi_bdev, &wrong_bdev);
	DECLINE(bi_iter.bi_sector, 57);
	DECLINE(bi_iter.bi_size, 2048);
	DECLINE(bi_iter.bi_idx, 1);
	DECLINE(bi_iter.bi_offset, 1);
	DECLINE(bi_vcnt, 2);
	DECLINE(bi_vcnt, 0);
	DECLINE(bi_opf, REQ_OP_WRITE);
	DECLINE(bi_opf, REQ_SWAP);
	DECLINE(bi_flags, BIO_CLONED);
	DECLINE(bi_flags, BIO_REMAPPED);
	DECLINE(bi_io_vec, NULL);
	DECLINE(bi_swapz_original, NULL);
	vec.bv_page = &wrong_page;
	CHECK(swapz_mm_candidate_get(&origin, &candidate) == -EOPNOTSUPP);
	vec.bv_page = &page;
	vec.bv_offset = 1;
	CHECK(swapz_mm_candidate_get(&origin, &candidate) == -EOPNOTSUPP);
	vec.bv_offset = 0;
	vec.bv_len = 2048;
	CHECK(swapz_mm_candidate_get(&origin, &candidate) == -EOPNOTSUPP);
	vec.bv_len = 4096;
	CHECK(!swapz_mm_candidate_get(&origin, &candidate));
	CHECK(swapz_mm_candidate_get(&origin, &candidate) == -EINVAL);
	CHECK(!swapz_ticket_view(&candidate, &view));
	CHECK(view.key.store_sequence == 2 && view.key.area_epoch == 1);
	carrier.scratch[0] = 0;
	CHECK(view.bytes[0] == 0x5b);
	CHECK(!swapz_ticket_revoke(&broker, 6));
	origin.bi_swapz_original = NULL;
	CHECK(!swapz_ticket_put(&sio->lease)); /* model worker invokes actual put */
	CHECK(!swapz_ticket_usage(&broker, &usage) && usage.live_slots == 1 && usage.reserved_bytes == 64);
	CHECK(swapz_ticket_close(&broker) == -EBUSY);
	CHECK(!swapz_ticket_view(&candidate, &view) && view.bytes[0] == 0x5b);
	CHECK(!swapz_ticket_put(&candidate));
	CHECK(!swapz_ticket_usage(&broker, &usage) && !usage.live_slots && !usage.reserved_bytes);
	CHECK(!swapz_ticket_close(&broker));
	CHECK(!swapz_ticket_destroy(&broker));
	printf("PASS_HOST_ONLY R088 actual staged carrier helpers checks=%u\n", checks);
	return 0;
}
