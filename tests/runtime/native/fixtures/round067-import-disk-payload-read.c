// SPDX-License-Identifier: GPL-2.0-only
/* Actual authority.c allocator + genuine original-profile LZO1X/LZ4 bytes,
 * protected-block-zero RAM lower, retained pinned old extent, full 4096 decode.
 * NO physical I/O, original MM source BIO, live decoder lease or upper ACK.
 * Every test transition is serialized by one ordered fixture owner. */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <lz4.h>
#include <lzo/lzo1x.h>
#include <openssl/sha.h>
#include "authority.h"
/* The frozen original codec/profile contract is read-only. Its full decoder
 * admission requires a REAL upper ACK, so we never forge one to call it. */
#include "zswap-import-codec.h"

_Static_assert(sizeof(struct swapz_map) == 20U, "ordinary map ABI changed");
_Static_assert(SWAPZ_BLOCK_BYTES == 4096U, "RAW_4096 must be complete original");
_Static_assert(SWAPZ_LINUX_SWAP_HEADER_BLOCKS == 1U, "physical header lost");
_Static_assert(SWAPZ_IMPORT_DISK_ACTIVE == 0U, "native import activated");
_Static_assert(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U, "native source activated");
_Static_assert(SWAPZ_AUTHORITY_IMPORT_LZ4 ==
	       SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, "original LZ4 profile differs");
_Static_assert(SWAPZ_AUTHORITY_IMPORT_LZO1X ==
	       SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC, "original LZO profile differs");

enum { LOGICAL_PAGES = 64, PHYSICAL_BLOCKS = 2048,
       LOWER_BYTES = (PHYSICAL_BLOCKS + 1U) * SWAPZ_BLOCK_BYTES };
static struct swapz_authority authority;
static struct swapz_map maps[LOGICAL_PAGES];
static swapz_u16 live_records[PHYSICAL_BLOCKS];
static swapz_u8 extent_classes[PHYSICAL_BLOCKS];
static struct swapz_import_disk_pool pool;
static swapz_u8 lower[LOWER_BYTES]; /* first 4096 is protected header */
static swapz_u8 original[SWAPZ_BLOCK_BYTES];
static swapz_u8 source_bytes[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 read_extent[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 compressed[SWAPZ_BLOCK_BYTES];
static swapz_u8 decoded[SWAPZ_BLOCK_BYTES];
static swapz_u8 output[SWAPZ_BLOCK_BYTES];
static lzo_align_t lzo_work[LZO1X_1_MEM_COMPRESS /
			      sizeof(lzo_align_t) + 1U];
static const char *case_name;

#define CHECK(check) do { if (!(check)) { \
	fprintf(stderr, "FIRST_ERROR %s\n", case_name); return 1; \
} } while (0)

static int initialize(void)
{
	size_t index;

	memset(&authority, 0, sizeof(authority));
	memset(maps, 0, sizeof(maps));
	memset(live_records, 0, sizeof(live_records));
	memset(extent_classes, 0, sizeof(extent_classes));
	memset(lower, 0, sizeof(lower));
	memset(lower, 0x5c, SWAPZ_BLOCK_BYTES);
	memset(lzo_work, 0, sizeof(lzo_work));
	for (index = 0; index < sizeof(original); ++index)
		original[index] = (swapz_u8)(
			((index / 31U) * 13U +
			 (index % 31U == 3U ? 17U : 4U)) & 255U);
	if (lzo_init() != LZO_E_OK)
		return -EIO;
	if (swapz_authority_init(&authority, maps, live_records,
				extent_classes, LOGICAL_PAGES, PHYSICAL_BLOCKS))
		return -EIO;
	swapz_import_disk_init(&pool, &authority);
	return 0;
}

static int header_intact(void)
{
	size_t index;

	for (index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
		if (lower[index] != 0x5cU)
			return 0;
	return 1;
}

static swapz_u8 *extent_at(swapz_u32 start)
{
	if (start >= PHYSICAL_BLOCKS)
		return NULL;
	return lower + ((size_t)start + 1U) * SWAPZ_BLOCK_BYTES;
}

static int prepare_spec(swapz_u32 logical, swapz_u64 epoch, swapz_u8 codec,
			struct swapz_authority_import_spec *spec)
{
	lzo_uint lzo_length = sizeof(source_bytes);
	int result;

	if (!spec)
		return -EINVAL;
	memset(spec, 0, sizeof(*spec));
	if (codec == SWAPZ_AUTHORITY_IMPORT_LZ4) {
		result = LZ4_compress_default((const char *)original,
				(char *)source_bytes, SWAPZ_BLOCK_BYTES,
				(int)sizeof(source_bytes));
		if (result <= 0 || result > (int)SWAPZ_MAX_COMPRESSED)
			return -EMSGSIZE;
		spec->compressed_length = (swapz_u16)result;
	} else if (codec == SWAPZ_AUTHORITY_IMPORT_LZO1X) {
		result = lzo1x_1_compress(original, SWAPZ_BLOCK_BYTES,
					 source_bytes, &lzo_length, lzo_work);
		if (result != LZO_E_OK || !lzo_length ||
		    lzo_length > SWAPZ_MAX_COMPRESSED)
			return -EMSGSIZE;
		spec->compressed_length = (swapz_u16)lzo_length;
	} else {
		return -EOPNOTSUPP;
	}
	spec->source_swap_slot = (swapz_u64)logical + 1U;
	spec->source_entry_identity = 0x1122U;
	spec->source_store_generation = 0x3344U;
	spec->gc_epoch = epoch;
	spec->logical_page = logical;
	spec->compressed_crc32c = swapz_crc32c_bytes(
		source_bytes, spec->compressed_length);
	spec->codec = codec;
	spec->codec_version = 1U;
	spec->requested_fua = 1U;
	return SHA256(original, SWAPZ_BLOCK_BYTES, spec->original_sha256) ?
		0 : -EIO;
}

static int stage_submit(const struct swapz_authority_import_spec *spec,
			swapz_u8 blocks, swapz_u64 replaces_ticket,
			struct swapz_tx *tx, swapz_u64 *ticket)
{
	int error = swapz_import_disk_stage(&pool, spec, blocks,
					    replaces_ticket, tx, ticket);

	return error ? error : swapz_import_disk_submit(&pool, *ticket);
}

static int memory_write(const struct swapz_tx *tx,
			const struct swapz_authority_import_spec *spec)
{
	swapz_u8 *extent = extent_at(tx->start_block);
	size_t extent_bytes = (size_t)tx->extent_blocks * SWAPZ_BLOCK_BYTES;

	if (!extent || !spec || spec->compressed_length > extent_bytes)
		return -EINVAL;
	memset(extent, 0, extent_bytes); /* deterministic zero padding */
	memcpy(extent, source_bytes, spec->compressed_length); /* no recompress */
	return 0;
}

static int receipt(const struct swapz_tx *tx, swapz_u64 ticket,
		   int lower_error, swapz_u8 completed_blocks, int flushed)
{
	return swapz_import_disk_complete_payload(
		&pool, ticket, tx, extent_at(tx->start_block),
		(swapz_u32)tx->extent_blocks * SWAPZ_BLOCK_BYTES,
		lower_error, completed_blocks, flushed);
}

static int create_owned(swapz_u32 logical, swapz_u64 epoch, swapz_u8 codec,
			swapz_u8 blocks, swapz_u64 replaces_ticket,
			struct swapz_tx *tx, swapz_u64 *ticket)
{
	struct swapz_authority_import_spec spec;
	int error = prepare_spec(logical, epoch, codec, &spec);

	if (error)
		return error;
	error = stage_submit(&spec, blocks, replaces_ticket, tx, ticket);
	if (error)
		return error;
	error = memory_write(tx, &spec);
	return error ? error : receipt(tx, *ticket, 0, blocks, 1);
}

/* Pinned volatile exact ticket/generation/GC epoch is authenticated by
 * ACTUAL authority.c against its real physical live-start and model bytes.
 * The independently linked liblzo2/LZ4 decoder then verifies full 4096
 * original SHA256 and byte equality without invented upper ACK. */
static int decode_view(const struct swapz_import_disk_view *view,
		       swapz_u32 actual_read_bytes, swapz_u8 *destination)
{
	swapz_u8 digest[SHA256_DIGEST_LENGTH];
	lzo_uint lzo_length = SWAPZ_BLOCK_BYTES;
	const size_t extent_bytes = (size_t)view->extent_blocks *
				    SWAPZ_BLOCK_BYTES;
	swapz_u8 *extent = extent_at(view->start_block);
	int error, decoded_length;

	if (!view || !destination || !extent ||
	    extent_bytes > sizeof(read_extent) ||
	    actual_read_bytes > extent_bytes)
		return -EINVAL;
	/* Full memory-backed lower READ to a disjoint preallocated buffer. */
	memcpy(read_extent, extent, actual_read_bytes);
	error = swapz_import_disk_read_pinned(
		&pool, view, read_extent, actual_read_bytes,
		compressed, sizeof(compressed));
	if (error)
		return error;
	if (view->spec.codec == SWAPZ_AUTHORITY_IMPORT_LZ4) {
		decoded_length = LZ4_decompress_safe(
			(const char *)compressed, (char *)decoded,
			(int)view->spec.compressed_length, SWAPZ_BLOCK_BYTES);
		if (decoded_length != (int)SWAPZ_BLOCK_BYTES)
			return -EBADMSG;
	} else if (view->spec.codec == SWAPZ_AUTHORITY_IMPORT_LZO1X) {
		error = lzo1x_decompress_safe(
			compressed, view->spec.compressed_length,
			decoded, &lzo_length, NULL);
		if (error != LZO_E_OK || lzo_length != SWAPZ_BLOCK_BYTES)
			return -EBADMSG;
	} else {
		return -EOPNOTSUPP;
	}
	if (!SHA256(decoded, SWAPZ_BLOCK_BYTES, digest))
		return -EIO;
	if (memcmp(digest, view->spec.original_sha256, sizeof(digest)) ||
	    memcmp(decoded, original, SWAPZ_BLOCK_BYTES))
		return -EBADMSG;
	memcpy(destination, decoded, SWAPZ_BLOCK_BYTES);
	return 0;
}

static int decode_ticket(swapz_u64 ticket)
{
	struct swapz_import_disk_view view;
	int error = swapz_import_disk_pin(&pool, ticket, &view);

	if (error)
		return error;
	error = decode_view(&view,
			    (swapz_u32)view.extent_blocks * SWAPZ_BLOCK_BYTES,
			    output);
	if (swapz_import_disk_put(&pool, ticket) && !error)
		return -ESTALE;
	return error;
}

static int original_lz4_classes(void)
{
	const swapz_u8 classes[] = { 1U, 2U, 4U };
	size_t index;

	for (index = 0; index < sizeof(classes); ++index) {
		struct swapz_tx tx;
		swapz_u64 ticket;

		CHECK(initialize() == 0);
		CHECK(create_owned(7U, 1U, SWAPZ_AUTHORITY_IMPORT_LZ4,
				   classes[index], 0U, &tx, &ticket) == 0);
		CHECK(!maps[7].valid && header_intact() &&
		      live_records[tx.start_block] == 1U &&
		      extent_classes[tx.start_block] == classes[index] &&
		      authority.committed_blocks == classes[index]);
		memset(output, 0x73, sizeof(output));
		CHECK(decode_ticket(ticket) == 0);
		CHECK(!memcmp(output, original, SWAPZ_BLOCK_BYTES));
		CHECK(swapz_import_disk_retire(&pool, ticket) == 0);
	}
	return 0;
}

static int original_lzo_classes(void)
{
	const swapz_u8 classes[] = { 1U, 2U, 4U };
	size_t index;

	for (index = 0; index < sizeof(classes); ++index) {
		struct swapz_tx tx;
		swapz_u64 ticket;

		CHECK(initialize() == 0);
		CHECK(create_owned(11U, 1U, SWAPZ_AUTHORITY_IMPORT_LZO1X,
				   classes[index], 0U, &tx, &ticket) == 0);
		CHECK(!maps[11].valid && header_intact() &&
		      live_records[tx.start_block] == 1U &&
		      extent_classes[tx.start_block] == classes[index]);
		CHECK(decode_ticket(ticket) == 0);
		CHECK(!memcmp(output, original, SWAPZ_BLOCK_BYTES));
		CHECK(swapz_import_disk_retire(&pool, ticket) == 0);
	}
	return 0;
}

static int torn_write_and_completion(void)
{
	struct swapz_authority_import_spec spec;
	struct swapz_import_disk_view view;
	struct swapz_tx tx;
	swapz_u64 ticket;
	swapz_u8 *extent;

	CHECK(initialize() == 0);
	CHECK(prepare_spec(13U, 1U, SWAPZ_AUTHORITY_IMPORT_LZ4, &spec) == 0);
	CHECK(stage_submit(&spec, 2U, 0U, &tx, &ticket) == 0);
	CHECK(swapz_import_disk_pin(&pool, ticket, &view) == -ESTALE);
	CHECK(memory_write(&tx, &spec) == 0);
	extent = extent_at(tx.start_block);
	CHECK(extent != NULL);
	extent[SWAPZ_BLOCK_BYTES + 5U] = 0x31U;
	CHECK(receipt(&tx, ticket, 0, 2U, 1) == -EBADMSG);
	CHECK(!maps[13].valid && !live_records[tx.start_block] &&
	      authority.abandoned_blocks == 2U);
	CHECK(swapz_import_disk_abort(&pool, ticket) == 0);
	CHECK(stage_submit(&spec, 2U, 0U, &tx, &ticket) == 0);
	CHECK(memory_write(&tx, &spec) == 0);
	CHECK(receipt(&tx, ticket, 0, 1U, 1) == -EIO);
	CHECK(swapz_import_disk_abort(&pool, ticket) == 0);
	CHECK(stage_submit(&spec, 2U, 0U, &tx, &ticket) == 0);
	CHECK(memory_write(&tx, &spec) == 0);
	CHECK(receipt(&tx, ticket, 0, 2U, 0) == -EIO);
	CHECK(swapz_import_disk_abort(&pool, ticket) == 0);
	CHECK(stage_submit(&spec, 2U, 0U, &tx, &ticket) == 0);
	CHECK(memory_write(&tx, &spec) == 0);
	CHECK(receipt(&tx, ticket, -EIO, 2U, 1) == -EIO);
	CHECK(swapz_import_disk_abort(&pool, ticket) == 0);
	CHECK(authority.committed_blocks == 0U &&
	      !maps[13].valid && header_intact());
	return 0;
}

static int corrupt_lower_and_aba(void)
{
	struct swapz_tx tx;
	struct swapz_import_disk_view view, wrong;
	swapz_u64 ticket;
	swapz_u8 *extent;
	size_t padding_byte;

	CHECK(initialize() == 0);
	CHECK(create_owned(17U, 1U, SWAPZ_AUTHORITY_IMPORT_LZO1X, 4U,
			   0U, &tx, &ticket) == 0);
	CHECK(swapz_import_disk_pin(&pool, ticket, &view) == 0);
	extent = extent_at(tx.start_block);
	CHECK(extent != NULL);
	memset(output, 0x73, sizeof(output));
	extent[5] ^= 0x80U;
	CHECK(decode_view(&view, 4U * SWAPZ_BLOCK_BYTES, output) == -EBADMSG);
	CHECK(output[0] == 0x73U && output[SWAPZ_BLOCK_BYTES - 1U] == 0x73U);
	extent[5] ^= 0x80U;
	padding_byte = (size_t)view.spec.compressed_length + 37U;
	extent[padding_byte] = 0x42U;
	CHECK(decode_view(&view, 4U * SWAPZ_BLOCK_BYTES, output) == -EBADMSG);
	CHECK(output[0] == 0x73U);
	extent[padding_byte] = 0U;
	CHECK(decode_view(&view, SWAPZ_BLOCK_BYTES, output) == -EMSGSIZE);
	wrong = view;
	wrong.spec.gc_epoch++;
	CHECK(decode_view(&wrong, 4U * SWAPZ_BLOCK_BYTES, output) == -ESTALE);
	wrong = view;
	wrong.spec.original_sha256[0] ^= 1U;
	CHECK(decode_view(&wrong, 4U * SWAPZ_BLOCK_BYTES, output) == -ESTALE);
	wrong = view;
	wrong.spec.codec = SWAPZ_AUTHORITY_IMPORT_LZ4;
	CHECK(decode_view(&wrong, 4U * SWAPZ_BLOCK_BYTES, output) == -ESTALE);
	wrong = view;
	wrong.ordinary_generation++;
	CHECK(decode_view(&wrong, 4U * SWAPZ_BLOCK_BYTES, output) == -ESTALE);
	wrong = view;
	wrong.ticket++;
	CHECK(decode_view(&wrong, 4U * SWAPZ_BLOCK_BYTES, output) == -ESTALE);
	CHECK(decode_view(&view, 4U * SWAPZ_BLOCK_BYTES, output) == 0);
	CHECK(!memcmp(output, original, SWAPZ_BLOCK_BYTES));
	CHECK(swapz_import_disk_retire(&pool, ticket) == 0);
	CHECK(decode_view(&view, 4U * SWAPZ_BLOCK_BYTES, output) == 0);
	CHECK(swapz_import_disk_put(&pool, ticket) == 0);
	CHECK(decode_view(&view, 4U * SWAPZ_BLOCK_BYTES, output) == -ESTALE);
	CHECK(header_intact());
	return 0;
}

static int pinned_gc_roundtrip(void)
{
	struct swapz_tx old_tx, new_tx;
	struct swapz_import_disk_view old_view, refused_view;
	swapz_u64 old_ticket, new_ticket;
	swapz_u32 old_start, new_start;

	CHECK(initialize() == 0);
	CHECK(create_owned(19U, 1U, SWAPZ_AUTHORITY_IMPORT_LZ4, 2U, 0U,
			   &old_tx, &old_ticket) == 0);
	CHECK(swapz_import_disk_pin(&pool, old_ticket, &old_view) == 0);
	old_start = old_tx.start_block;
	CHECK(create_owned(19U, 2U, SWAPZ_AUTHORITY_IMPORT_LZ4, 4U,
			   old_ticket, &new_tx, &new_ticket) == 0);
	new_start = new_tx.start_block;
	CHECK(old_start != new_start && !maps[19].valid &&
	      live_records[old_start] == 1U && live_records[new_start] == 1U &&
	      extent_classes[old_start] == 2U &&
	      extent_classes[new_start] == 4U);
	CHECK(swapz_import_disk_pin(&pool, old_ticket, &refused_view) == -ESTALE);
	CHECK(decode_view(&old_view, 2U * SWAPZ_BLOCK_BYTES, output) == 0);
	CHECK(!memcmp(output, original, SWAPZ_BLOCK_BYTES));
	CHECK(decode_ticket(new_ticket) == 0);
	CHECK(swapz_import_disk_put(&pool, old_ticket) == 0);
	CHECK(live_records[old_start] == 0U && live_records[new_start] == 1U);
	CHECK(decode_view(&old_view, 2U * SWAPZ_BLOCK_BYTES, output) == -ESTALE);
	CHECK(swapz_import_disk_retire(&pool, new_ticket) == 0);
	CHECK(swapz_import_disk_close(&pool) == 0 && header_intact());
	return 0;
}

static int exhausted_and_normal_raw(void)
{
	struct swapz_tx tx, raw;
	struct swapz_authority_import_spec spec;
	struct swapz_import_disk_view view;
	swapz_u64 tickets[SWAPZ_IMPORT_DISK_CAPACITY], rejected;
	swapz_u8 index;

	CHECK(initialize() == 0);
	for (index = 0U; index < SWAPZ_IMPORT_DISK_CAPACITY; ++index)
		CHECK(create_owned((swapz_u32)index + 24U, 1U,
				   SWAPZ_AUTHORITY_IMPORT_LZ4, 1U, 0U,
				   &tx, &tickets[index]) == 0);
	CHECK(prepare_spec(40U, 1U, SWAPZ_AUTHORITY_IMPORT_LZ4, &spec) == 0);
	CHECK(swapz_import_disk_stage(&pool, &spec, 1U, 0U, &tx,
				      &rejected) == -ENOSPC);
	CHECK(!authority.in_flight && rejected == 0U);
	CHECK(swapz_import_disk_pin(&pool, tickets[0], &view) == 0);
	CHECK(swapz_import_disk_close(&pool) == -EBUSY);
	CHECK(swapz_import_disk_put(&pool, tickets[0]) == 0);
	CHECK(swapz_import_disk_close(&pool) == 0);
	CHECK(swapz_import_disk_pin(&pool, tickets[0], &view) == -ESTALE);
	CHECK(header_intact());
	CHECK(initialize() == 0);
	spec.logical_page = 41U;
	CHECK(swapz_stage(&authority, &spec.logical_page, 1U, 1U, &raw) == 0);
	CHECK(swapz_finish_raw(&authority, &raw, original, 1U, 0) == 0);
	CHECK(maps[41].raw && maps[41].valid &&
	      maps[41].payload_length == SWAPZ_BLOCK_BYTES &&
	      swapz_verify_raw(&authority, 41U, original) == 0);
	CHECK(swapz_import_disk_stage(&pool, &spec, 1U, 0U, &tx,
				      &rejected) == -EINVAL);
	return 0;
}

struct case_definition { const char *name; int (*run)(void); };
static const struct case_definition cases[] = {
	{ "original_lz4_classes", original_lz4_classes },
	{ "original_lzo_classes", original_lzo_classes },
	{ "torn_write_and_completion", torn_write_and_completion },
	{ "corrupt_lower_and_aba", corrupt_lower_and_aba },
	{ "pinned_gc_roundtrip", pinned_gc_roundtrip },
	{ "exhausted_and_normal_raw", exhausted_and_normal_raw },
};

int main(int argc, char **argv)
{
	size_t index, passed = 0U;

	for (index = 0U; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		if (argc == 2 && strcmp(argv[1], cases[index].name))
			continue;
		case_name = cases[index].name;
		if (cases[index].run())
			return 1;
		++passed;
	}
	if (!passed)
		return 2;
	if (argc == 1)
		printf("PASS memory_lower_native_original_cases=%zu "
		       "profiles=2 full_decoded_bytes=4096 classes=1,2,4 "
		       "map_bytes=%zu pool_bytes=%zu header=UNCHANGED "
		       "modeled_receipt=ONLY AUTH=0 PHASE_A=BLOCKED\n",
		       passed, sizeof(struct swapz_map), sizeof(pool));
	return 0;
}
