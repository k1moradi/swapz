/* Rootless host C runs the identical new original block/bio.c function body.
 * Mocked BIO lifetime is not a native kernel/DM acceptance certificate.
 */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <openssl/sha.h>
#define SHA256_DIGEST_SIZE SHA256_DIGEST_LENGTH

#define SWAPZ_ROUND058_HOST_TEST 1
#define SWAPZ_ROUND058_ORIGINAL_STORED_BIO_CHAIN_TEST 1
#define SWAPZ_ROUND056_PREERASE_SINGLE_OWNER_TEST 1
#define SWAPZ_ROUND056_ORIGINAL_CLONE_PROVENANCE_TEST 1
#define SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY 1
#define SWAPZ_ROUND031_MM_BIO_SOURCE 1
#define SWAPZ_ROUND028_SLOT_EPOCH_SOURCE 1
#define SWAPZ_ROUND025_SIDEBAND_CI_ONLY 1
#define SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK 3U
#define REQ_OP_WRITE 1U
#define REQ_OP_READ 0U
#define REQ_SWAP 16U
#define BIO_CLONED 1U

typedef unsigned char u8;
struct block_device { unsigned int unused; };
struct page { u8 content[4096]; };
struct bio_vec {
	struct page *bv_page;
	unsigned int bv_offset;
	unsigned int bv_len;
};
struct swapz_ci_owned_payload {
	bool swapz_round056_budgeted;
	bool swapz_round056_sealed;
	uint64_t source_swap_entry;
	u8 original_sha256[SHA256_DIGEST_SIZE];
	unsigned int references;
};
struct bio {
	struct block_device *bi_bdev;
	unsigned int bi_opf;
	unsigned int bi_flags;
	unsigned int bi_swap_origin;
	struct swapz_ci_owned_payload *bi_swapz_ci_sideband;
	struct bio_vec *bi_io_vec;
	struct {
		uint64_t bi_sector;
		unsigned int bi_size;
		unsigned int bi_idx;
		unsigned int bi_offset;
	} bi_iter;
	unsigned short bi_vcnt;
};
static unsigned int bio_op(const struct bio *bio)
{
	return bio->bi_opf & 7U;
}
static struct swapz_ci_owned_payload *swapz_ci_owned_get(
	struct swapz_ci_owned_payload *owner)
{
	if (!owner || !owner->references)
		return NULL;
	++owner->references;
	return owner;
}
static void swapz_ci_owned_put(struct swapz_ci_owned_payload *owner)
{
	if (owner)
		--owner->references;
}
static bool swapz_ci_owned_valid(const struct swapz_ci_owned_payload *owner)
{
	return owner && owner->source_swap_entry &&
		owner->swapz_round056_sealed;
}
static void *kmap_local_page(struct page *page)
{
	return page->content;
}
static void kunmap_local(const void *bytes)
{
	(void)bytes;
}
static void sha256(const void *bytes, unsigned int length, u8 result[SHA256_DIGEST_SIZE])
{
	(void)SHA256(bytes, (size_t)length, result);
}
static void memzero_explicit(void *bytes, size_t length)
{
	memset(bytes, 0, length);
}

/* ROUND058_INJECT_SOURCE */

static int fail(unsigned int scenario, const char *reason)
{
	fprintf(stderr, "ROUND058_CHAIN_FIRST_ERROR scenario=%u reason=%s\n",
		scenario, reason);
	return 1;
}

static int run_scenario(unsigned int scenario)
{
	struct page page = {};
	struct bio_vec vector = { .bv_page = &page, .bv_len = 4096U };
	struct block_device device = {};
	struct swapz_ci_owned_payload owned = {
		.swapz_round056_budgeted = true,
		.swapz_round056_sealed = true,
		.source_swap_entry = 13U,
		.references = 1U,
	};
	struct bio source = {
		.bi_bdev = &device,
		.bi_opf = REQ_OP_WRITE | REQ_SWAP,
		.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK,
		.bi_swapz_ci_sideband = &owned,
		.bi_io_vec = &vector,
		.bi_iter = {.bi_sector = 8U, .bi_size = 4096U},
	};

	memset(page.content, 0x37, sizeof(page.content));
	sha256(page.content, 4096U, owned.original_sha256);
	switch (scenario) {
	case 1U: source.bi_vcnt = 1U; break;
	case 2U: source.bi_iter.bi_size = 2048U; break;
	case 3U: source.bi_flags |= 1U << BIO_CLONED; break;
	case 4U: source.bi_iter.bi_sector = 0U; break;
	case 5U: source.bi_iter.bi_sector = 9U; break;
	case 6U: source.bi_bdev = NULL; break;
	case 7U: source.bi_opf = REQ_OP_READ | REQ_SWAP; break;
	case 8U: source.bi_opf = REQ_OP_WRITE; break;
	case 9U: source.bi_swap_origin = 0U; break;
	case 10U: source.bi_io_vec[0].bv_len = 4095U; break;
	case 11U: source.bi_iter.bi_offset = 1U; break;
	case 12U: source.bi_iter.bi_idx = 1U; break;
	case 13U: owned.swapz_round056_sealed = false; break;
	case 14U: owned.original_sha256[0] ^= 0x3aU; break;
	case 15U: page.content[17] ^= 0x3aU; break;
	case 16U: source.bi_swapz_ci_sideband = NULL; break;
	case 17U: source.bi_io_vec = NULL; break;
	case 18U: source.bi_io_vec[0].bv_page = NULL; break;
	default: break;
	}
	const int actual = swapz_round058_source_bio_observe(&source);
	if (owned.references != 1U)
		return fail(scenario, "owner-reference-unbalanced");
	if (scenario == 0U ? actual != 0 : actual == 0)
		return fail(scenario, "source-lifetime-or-content-check");
	return 0;
}

int main(void)
{
	for (unsigned int scenario = 0U; scenario <= 18U; ++scenario)
		if (run_scenario(scenario))
			return 1;
	puts("ROUND058_CHAIN_HOST_ORIGINAL_SOURCE_C_PASS scenarios=19 AUTH0 PHASE_A=BLOCKED");
	return 0;
}
