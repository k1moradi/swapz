// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-decode.h"
#include <stdio.h>
#include <stdlib.h>

#define BUFFER_BYTES 4608U
#define CHECK(name, condition) do { if (!(condition)) { \
	fprintf(stderr, "FIRST_ERROR %s\n", name); exit(1); } } while (0)

/* Test-only compressor adapter: exact pinned Linux in qualification runner.
 * Never used for a production accepted original compressed stream. */
int round085_compress(swapz_u8 codec, const swapz_u8 *page, swapz_u32 length,
	swapz_u8 *compressed, swapz_u32 capacity, swapz_u32 *written);

static swapz_u8 input[BUFFER_BYTES], candidate[BUFFER_BYTES];
static swapz_u8 page[SWAPZ_BLOCK_BYTES], random_page[SWAPZ_BLOCK_BYTES];
static swapz_u8 scratch[SWAPZ_BLOCK_BYTES], output[SWAPZ_BLOCK_BYTES];
static swapz_u8 marker[SWAPZ_BLOCK_BYTES];
static struct swapz_zswap_import_decoder_owner owners[2];
static struct swapz_zswap_import_decoder_lease leases[2];
static swapz_u32 small_lengths[2], large_lengths[2];

static struct swapz_original_decode_record descriptor(swapz_u8 codec,
	swapz_u32 length)
{
	struct swapz_original_decode_record record = {
		.compressed_length = length, .decoded_length = SWAPZ_BLOCK_BYTES,
		.compressed_crc32c = swapz_crc32c_bytes(input, length),
		.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
		.codec = codec, .version = 1U,
	};
	CHECK("fixture_sha", !swapz_zswap_import_sha256(page, record.original_sha256));
	return record;
}

static void reject(const char *name,
	const struct swapz_zswap_import_decoder_lease *lease,
	const struct swapz_original_decode_record *record, swapz_u32 ceiling,
	swapz_u32 input_capacity, swapz_u32 scratch_capacity,
	swapz_u32 output_capacity, int expected)
{
	memcpy(output, marker, sizeof(output));
	CHECK(name, swapz_original_decode(lease, record, ceiling, input,
		input_capacity, scratch, scratch_capacity, output, output_capacity) == expected);
	CHECK("failure_output_immutable", !memcmp(output, marker, sizeof(output)));
}

static void expect_failure(const char *name,
	const struct swapz_zswap_import_decoder_lease *lease,
	const struct swapz_original_decode_record *record, int expected)
{
	reject(name, lease, record, SWAPZ_ORIGINAL_DECODE_M4095, sizeof(input),
		SWAPZ_BLOCK_BYTES, SWAPZ_BLOCK_BYTES, expected);
}

static void positive(const char *name,
	const struct swapz_zswap_import_decoder_lease *lease,
	const struct swapz_original_decode_record *record, swapz_u32 ceiling)
{
	memcpy(output, marker, sizeof(output));
	CHECK(name, !swapz_original_decode(lease, record, ceiling, input,
		record->compressed_length, scratch, sizeof(scratch), output, sizeof(output)));
	CHECK("positive_exact_page", !memcmp(page, output, sizeof(page)));
}

/* Deterministic bounded search; retain the largest *real* encoded block
 * below 4096. Geometry at exact endpoints is checked independently. */
static swapz_u32 corpus(swapz_u8 codec, int large)
{
	swapz_u32 prefix, length, best = 0U, best_prefix = 0U;
	const swapz_u32 last_prefix = large ? SWAPZ_BLOCK_BYTES : 64U;

	for (prefix = 0U; prefix <= last_prefix; ++prefix) {
		memset(page, 0, sizeof(page));
		memcpy(page, random_page, prefix);
		CHECK("fixture_compress", !round085_compress(codec, page,
			SWAPZ_BLOCK_BYTES, candidate, sizeof(candidate), &length));
		if (length > best && length < SWAPZ_BLOCK_BYTES &&
		    (!large || length > SWAPZ_ORIGINAL_DECODE_M3568)) {
			best = length;
			best_prefix = prefix;
			memcpy(input, candidate, length);
		}
	}
	CHECK("corpus_found", best != 0U);
	memset(page, 0, sizeof(page));
	memcpy(page, random_page, best_prefix);
	return best;
}

static void profile(unsigned int index)
{
	const swapz_u8 codec = (swapz_u8)(index + 1U);
	const struct swapz_zswap_import_decoder_lease *lease = &leases[index];
	struct swapz_original_decode_record record, invalid;
	struct swapz_zswap_import_decoder_lease absent = {.codec = codec, .version = 1U};
	swapz_u32 small = corpus(codec, 0), large, short_length;
	union { struct swapz_original_decode_record record; swapz_u8 bytes[SWAPZ_BLOCK_BYTES]; } alias;
	union { struct swapz_zswap_import_decoder_lease lease; swapz_u8 bytes[SWAPZ_BLOCK_BYTES]; } lease_alias;

	record = descriptor(codec, small);
	positive("small_3568", lease, &record, SWAPZ_ORIGINAL_DECODE_M3568);
	positive("small_4095", lease, &record, SWAPZ_ORIGINAL_DECODE_M4095);
	large = corpus(codec, 1);
	record = descriptor(codec, large);
	positive("large_4095", lease, &record, SWAPZ_ORIGINAL_DECODE_M4095);
	reject("large_3568_reject", lease, &record, SWAPZ_ORIGINAL_DECODE_M3568,
		large, sizeof(scratch), sizeof(output), -EMSGSIZE);
	invalid = record; invalid.compressed_length = SWAPZ_BLOCK_BYTES;
	expect_failure("raw_4096_refused", lease, &invalid, -EMSGSIZE);
	invalid = record; invalid.compressed_length = 0U;
	expect_failure("zero_length_refused", lease, &invalid, -EMSGSIZE);
	expect_failure("null_lease", NULL, &record, -EINVAL);
	expect_failure("null_record", lease, NULL, -EINVAL);
	invalid = record; invalid.representation = 0U;
	expect_failure("representation", lease, &invalid, -EOPNOTSUPP);
	invalid = record; invalid.codec = 3U;
	expect_failure("codec", lease, &invalid, -EOPNOTSUPP);
	invalid = record; invalid.version = 2U;
	expect_failure("version", lease, &invalid, -EOPNOTSUPP);
	invalid = record; invalid.dictionary_id = 1U;
	expect_failure("dictionary", lease, &invalid, -EOPNOTSUPP);
	invalid = record; invalid.decoded_length = SWAPZ_BLOCK_BYTES - 1U;
	expect_failure("decoded_size", lease, &invalid, -EMSGSIZE);
	reject("input_capacity", lease, &record, SWAPZ_ORIGINAL_DECODE_M4095,
		large - 1U, sizeof(scratch), sizeof(output), -EMSGSIZE);
	reject("scratch_capacity", lease, &record, SWAPZ_ORIGINAL_DECODE_M4095,
		large, SWAPZ_BLOCK_BYTES - 1U, sizeof(output), -EMSGSIZE);
	reject("output_capacity", lease, &record, SWAPZ_ORIGINAL_DECODE_M4095,
		large, sizeof(scratch), SWAPZ_BLOCK_BYTES - 1U, -EMSGSIZE);
	expect_failure("unretained", &absent, &record, -ESTALE);
	expect_failure("lease_codec", &leases[1U - index], &record, -ESTALE);
	invalid = record; invalid.compressed_crc32c ^= 1U;
	expect_failure("crc", lease, &invalid, -EBADMSG);
	invalid = record; invalid.original_sha256[31] ^= 1U;
	expect_failure("sha", lease, &invalid, -EBADMSG);
	memcpy(output, marker, sizeof(output));
	CHECK("alias", swapz_original_decode(lease, &record,
		SWAPZ_ORIGINAL_DECODE_M4095, input, large, output, sizeof(output),
		output, sizeof(output)) == -EINVAL);
	CHECK("alias_output_immutable", !memcmp(output, marker, sizeof(output)));
	memcpy(alias.bytes, marker, sizeof(alias.bytes));
	alias.record = record;
	memcpy(candidate, alias.bytes, sizeof(alias.bytes));
	CHECK("descriptor_alias", swapz_original_decode(lease, &alias.record,
		SWAPZ_ORIGINAL_DECODE_M4095, input, large, scratch, sizeof(scratch),
		alias.bytes, sizeof(alias.bytes)) == -EINVAL);
	CHECK("descriptor_preserved", !memcmp(alias.bytes, candidate, sizeof(alias.bytes)));
	memset(&lease_alias, 0, sizeof(lease_alias));
	CHECK("lease_alias_get", !swapz_zswap_import_decoder_owner_get(
		&owners[index], &lease_alias.lease));
	memcpy(candidate, lease_alias.bytes, sizeof(lease_alias.bytes));
	memcpy(output, marker, sizeof(output));
	CHECK("lease_alias", swapz_original_decode(&lease_alias.lease, &record,
		SWAPZ_ORIGINAL_DECODE_M4095, input, large, lease_alias.bytes,
		sizeof(scratch), output, sizeof(output)) == -EINVAL);
	CHECK("lease_alias_output_immutable", !memcmp(output, marker, sizeof(output)));
	CHECK("lease_alias_preserved", !memcmp(lease_alias.bytes, candidate, sizeof(lease_alias.bytes)));
	CHECK("lease_alias_put", !swapz_zswap_import_decoder_owner_put(&lease_alias.lease));
	memcpy(candidate, input, sizeof(input));
	CHECK("input_output_alias", swapz_original_decode(lease, &record,
		SWAPZ_ORIGINAL_DECODE_M4095, input, large, scratch, sizeof(scratch),
		input, SWAPZ_BLOCK_BYTES) == -EINVAL);
	CHECK("input_alias_preserved", !memcmp(input, candidate, sizeof(input)));
	CHECK("input_scratch_alias", swapz_original_decode(lease, &record,
		SWAPZ_ORIGINAL_DECODE_M4095, input, large, input, SWAPZ_BLOCK_BYTES,
		output, sizeof(output)) == -EINVAL);
	CHECK("input_scratch_preserved", !memcmp(input, candidate, sizeof(input)));
	CHECK("input_scratch_output_immutable", !memcmp(output, marker, sizeof(output)));
	/* A complete valid compressed block with a trailing byte, CRC updated. */
	(void)corpus(codec, 0);
	record = descriptor(codec, small);
	input[small] = 0U;
	invalid = descriptor(codec, small + 1U);
	expect_failure(codec == 2U ? "lzo_trailing" : "lz4_trailing", lease, &invalid, -EBADMSG);
	invalid = descriptor(codec, small - 1U);
	expect_failure("truncated_input", lease, &invalid, -EBADMSG);
	CHECK("compress_short", !round085_compress(codec, page, SWAPZ_BLOCK_BYTES - 1U,
		input, sizeof(input), &short_length));
	invalid = descriptor(codec, short_length);
	expect_failure(codec == 2U ? "lzo_short_output" : "lz4_short_output",
		lease, &invalid, -EMSGSIZE);
	small_lengths[index] = small;
	large_lengths[index] = large;
}

int main(void)
{
	swapz_u32 state = 0x1ad57f91U;
	unsigned int index;

	CHECK("geometry_ceiling", !swapz_original_decode_length_valid(4094U, 1U));
	CHECK("geometry_zero", !swapz_original_decode_length_valid(4095U, 0U));
	CHECK("geometry_cap", !swapz_original_decode_length_valid(3568U, 3569U));
	CHECK("geometry_valid", swapz_original_decode_length_valid(3568U, 1U) &&
		swapz_original_decode_length_valid(3568U, 3568U) &&
		swapz_original_decode_length_valid(4095U, 3569U) &&
		swapz_original_decode_length_valid(4095U, 4095U) &&
		!swapz_original_decode_length_valid(4095U, 4096U));
	memset(marker, 0xa5, sizeof(marker));
	for (index = 0U; index < sizeof(random_page); ++index) {
		state ^= state << 13U; state ^= state >> 17U; state ^= state << 5U;
		random_page[index] = (swapz_u8)state;
	}
	for (index = 0U; index < 2U; ++index) {
		CHECK("owner_init", !swapz_zswap_import_decoder_owner_init(&owners[index],
			(swapz_u8)(index + 1U), 1U));
		CHECK("owner_get", !swapz_zswap_import_decoder_owner_get(&owners[index], &leases[index]));
	}
	for (index = 0U; index < 2U; ++index)
		profile(index);
	for (index = 0U; index < 2U; ++index) {
		struct swapz_original_decode_record stale = {0};
		CHECK("owner_put", !swapz_zswap_import_decoder_owner_put(&leases[index]));
		expect_failure("released_lease", &leases[index], &stale, -ESTALE);
		CHECK("owner_close", !swapz_zswap_import_decoder_owner_close_and_drain(&owners[index]));
		CHECK("closed_owner_get", swapz_zswap_import_decoder_owner_get(&owners[index],
			&leases[index]) == -ESHUTDOWN);
		CHECK("owner_mutex_destroy", !pthread_mutex_destroy(&owners[index].lock));
		CHECK("owner_cond_destroy", !pthread_cond_destroy(&owners[index].drained));
	}
	for (index = 0U; index < 2U; ++index)
		printf("PROFILE codec=%u small=%u large=%u\n", index + 1U,
			small_lengths[index], large_lengths[index]);
	puts("PASS round085-original-decode AUTH=0 PHASE_A=BLOCKED");
	return 0;
}
