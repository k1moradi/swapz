/* SPDX-License-Identifier: GPL-2.0-only */
/* Compiled native *synthetic-decoder* test of the exact kernel contract.
 * These payloads are deliberately NOT actual Linux zswap LZ4/ZSTD frames.
 * No disk I/O, compression, module load, authority publication or swap.
 */
#include <openssl/sha.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "../../../../src/kernel/zswap-direct-handoff.h"

#if SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED != 0U
#error "Unqualified direct compressed handoff must stay disabled"
#endif

struct test_decoder_context {
	swapz_direct_u8 marker;
	int behavior;
};

struct test_fixture {
	struct swapz_direct_ram_descriptor descriptor;
	struct swapz_direct_read_identity expected;
	struct swapz_direct_decoder decoder;
	struct swapz_direct_integrity integrity;
	struct test_decoder_context decoder_context;
	swapz_direct_u8 payload[4];
	swapz_direct_u8 expected_page[SWAPZ_DIRECT_LOGICAL_BYTES];
	swapz_direct_u8 scratch[SWAPZ_DIRECT_LOGICAL_BYTES];
	swapz_direct_u8 output[SWAPZ_DIRECT_LOGICAL_BYTES];
};

static unsigned int negative_count;
static unsigned int positive_count;
static unsigned int published_authorities;

static int real_crc32c(const swapz_direct_u8 *bytes, swapz_direct_u32 length,
		       swapz_direct_u32 *digest, void *context)
{
	swapz_direct_u32 crc = 0xffffffffU, index, bit;

	(void)context;
	if (!bytes || !digest)
		return -EINVAL;
	for (index = 0; index < length; ++index) {
		crc ^= bytes[index];
		for (bit = 0; bit < 8U; ++bit)
			crc = (crc >> 1U) ^ ((crc & 1U) ? 0x82f63b78U : 0U);
	}
	*digest = ~crc;
	return 0;
}

static int real_sha256(const swapz_direct_u8 *bytes, swapz_direct_u32 length,
		       swapz_direct_u8 digest[SWAPZ_DIRECT_SHA256_BYTES], void *context)
{
	(void)context;
	return SHA256(bytes, length, digest) ? 0 : -EIO;
}

static void make_original_page(swapz_direct_u8 *page, swapz_direct_u8 seed,
			       swapz_direct_u8 stride)
{
	swapz_direct_u32 index;

	for (index = 0; index < SWAPZ_DIRECT_LOGICAL_BYTES; ++index)
		page[index] = (swapz_direct_u8)((index * stride + seed) & 0xffU);
}

/* Only a deterministic test-owned representation; never a zswap decoder. */
static int synthetic_decoder(const swapz_direct_u8 *compressed,
			     swapz_direct_u32 compressed_length,
			     swapz_direct_u8 *page,
			     swapz_direct_u32 page_capacity,
			     swapz_direct_u32 *decoded_length, void *context)
{
	const struct test_decoder_context *decoder_context = context;

	if (!decoder_context || !compressed || !page || !decoded_length ||
	    compressed_length != 4U || page_capacity != SWAPZ_DIRECT_LOGICAL_BYTES ||
	    compressed[0] != decoder_context->marker || compressed[3] != 0x9bU)
		return -EINVAL;
	if (decoder_context->behavior == 3)
		return -EIO;
	make_original_page(page, compressed[1], compressed[2]);
	if (decoder_context->behavior == 4)
		page[17] ^= 1U;
	*decoded_length = decoder_context->behavior == 1 ? 4095U :
			  decoder_context->behavior == 2 ? 4097U : 4096U;
	return 0;
}

static int setup_fixture(struct test_fixture *fixture, enum swapz_direct_codec codec)
{
	struct swapz_direct_ram_descriptor *descriptor = &fixture->descriptor;

	memset(fixture, 0, sizeof(*fixture));
	fixture->payload[0] = codec == SWAPZ_DIRECT_ZSWAP_LZ4 ? 0xa1U : 0xb2U;
	fixture->payload[1] = 0x5cU;
	fixture->payload[2] = 0x13U;
	fixture->payload[3] = 0x9bU;
	fixture->decoder_context.marker = fixture->payload[0];
	make_original_page(fixture->expected_page, fixture->payload[1],
			   fixture->payload[2]);
	descriptor->version = SWAPZ_DIRECT_HANDOFF_VERSION;
	descriptor->semantic_origin = SWAPZ_DIRECT_AUTHENTICATED_STORED;
	descriptor->representation = SWAPZ_DIRECT_ZSWAP_COMPRESSED;
	descriptor->codec = codec;
	descriptor->payload_lifetime = SWAPZ_DIRECT_IMMUTABLY_OWNED;
	descriptor->logical_bytes = SWAPZ_DIRECT_LOGICAL_BYTES;
	descriptor->compressed_length = sizeof(fixture->payload);
	descriptor->logical_page = 37U;
	descriptor->generation = 9U;
	descriptor->source_record_identity = 0x445566U;
	descriptor->pool_identity = 0x123U;
	descriptor->dictionary_identity = 0U;
	descriptor->codec_generation = 7U;
	descriptor->payload = fixture->payload;
	if (real_crc32c(fixture->payload, descriptor->compressed_length,
			&descriptor->payload_crc32c, NULL) ||
	    real_sha256(fixture->expected_page, SWAPZ_DIRECT_LOGICAL_BYTES,
			  descriptor->expected_page_sha256, NULL))
		return 1;
	fixture->expected.logical_page = descriptor->logical_page;
	fixture->expected.generation = descriptor->generation;
	fixture->expected.source_record_identity = descriptor->source_record_identity;
	fixture->decoder.codec = codec;
	fixture->decoder.pool_identity = descriptor->pool_identity;
	fixture->decoder.dictionary_identity = descriptor->dictionary_identity;
	fixture->decoder.codec_generation = descriptor->codec_generation;
	fixture->decoder.decode = synthetic_decoder;
	fixture->decoder.context = &fixture->decoder_context;
	fixture->integrity.crc32c = real_crc32c;
	fixture->integrity.sha256 = real_sha256;
	memset(fixture->output, 0xa5, sizeof(fixture->output));
	memset(fixture->scratch, 0x77, sizeof(fixture->scratch));
	return 0;
}

static bool all_bytes(const swapz_direct_u8 *bytes, size_t length,
		      swapz_direct_u8 expected)
{
	size_t index;

	for (index = 0; index < length; ++index)
		if (bytes[index] != expected)
			return false;
	return true;
}

static int check_positive(enum swapz_direct_codec codec)
{
	struct test_fixture fixture;
	int status;

	if (setup_fixture(&fixture, codec))
		return 1;
	status = swapz_direct_validate(&fixture.descriptor, &fixture.expected,
				       &fixture.decoder, &fixture.integrity);
	if (status)
		return 1;
	status = swapz_direct_readback(&fixture.descriptor, &fixture.expected,
				       &fixture.decoder, &fixture.integrity,
				       fixture.scratch, fixture.output);
	if (status || memcmp(fixture.output, fixture.expected_page,
			     SWAPZ_DIRECT_LOGICAL_BYTES) != 0 ||
	    !all_bytes(fixture.scratch, sizeof(fixture.scratch), 0U) ||
	    published_authorities != 0U)
		return 1;
	++positive_count;
	return 0;
}

static int check_negative(struct test_fixture *fixture, const char *name)
{
	int status = swapz_direct_readback(&fixture->descriptor,
					  &fixture->expected, &fixture->decoder,
					  &fixture->integrity, fixture->scratch,
					  fixture->output);

	if (status >= 0 || !all_bytes(fixture->output, sizeof(fixture->output), 0xa5U) ||
	    !all_bytes(fixture->scratch, sizeof(fixture->scratch), 0U) ||
	    published_authorities != 0U) {
		fprintf(stderr, "FAIL first_case=%s status=%d\n", name, status);
		return 1;
	}
	++negative_count;
	return 0;
}

#define REJECT(name, mutation) do { \
	if (setup_fixture(&fixture, SWAPZ_DIRECT_ZSWAP_LZ4)) return 1; \
	mutation; \
	if (check_negative(&fixture, name)) return 1; \
} while (0)

int main(void)
{
	struct test_fixture fixture;

	if (check_positive(SWAPZ_DIRECT_ZSWAP_LZ4) ||
	    check_positive(SWAPZ_DIRECT_ZSWAP_ZSTD)) {
		fputs("FAIL positive deterministic test decoder\n", stderr);
		return 1;
	}
	REJECT("unknown_codec", fixture.descriptor.codec = SWAPZ_DIRECT_CODEC_UNKNOWN);
	REJECT("unknown_origin", fixture.descriptor.semantic_origin = SWAPZ_DIRECT_ORDINARY_UNKNOWN);
	REJECT("invalid_origin", fixture.descriptor.semantic_origin = (enum swapz_direct_origin)3);
	REJECT("raw_full_page_substitution", fixture.descriptor.representation = SWAPZ_DIRECT_FULL_PAGE);
	REJECT("invalid_representation", fixture.descriptor.representation = (enum swapz_direct_representation)3);
	REJECT("wrong_logical_size", fixture.descriptor.logical_bytes = 2048U);
	REJECT("zero_compressed_size", fixture.descriptor.compressed_length = 0U);
	REJECT("oversize_compressed_size", fixture.descriptor.compressed_length = 3569U);
	REJECT("null_payload", fixture.descriptor.payload = NULL);
	REJECT("borrowed_buffer", fixture.descriptor.payload_lifetime = SWAPZ_DIRECT_BORROWED);
	REJECT("wrong_version", fixture.descriptor.version = 9U);
	REJECT("stale_generation", fixture.expected.generation++);
	REJECT("stale_gc_identity", fixture.expected.source_record_identity++);
	REJECT("wrong_logical_page", fixture.expected.logical_page++);
	REJECT("bad_pool", fixture.decoder.pool_identity++);
	REJECT("bad_dictionary", fixture.descriptor.dictionary_identity++);
	REJECT("bad_codec_generation", fixture.decoder.codec_generation++);
	REJECT("unsupported_decoder", fixture.decoder.decode = NULL);
	REJECT("wrong_decoder_codec", fixture.decoder.codec = SWAPZ_DIRECT_ZSWAP_ZSTD);
	REJECT("no_integrity_callback", fixture.integrity.sha256 = NULL);
	REJECT("payload_crc_mismatch", fixture.descriptor.payload_crc32c++);
	REJECT("payload_bytes_changed", fixture.payload[2]++);
	REJECT("missing_page_digest", memset(fixture.descriptor.expected_page_sha256, 0, 32));
	REJECT("fake_verified_digest", fixture.descriptor.expected_page_sha256[8]++);
	REJECT("truncated_decode", fixture.decoder_context.behavior = 1);
	REJECT("expanding_decode", fixture.decoder_context.behavior = 2);
	REJECT("decompress_failure", fixture.decoder_context.behavior = 3);
	REJECT("wrong_plaintext", fixture.decoder_context.behavior = 4);
	REJECT("stale_payload_size", fixture.descriptor.compressed_length = 3U);
	REJECT("unrecognized_numeric_codec", fixture.descriptor.codec = (enum swapz_direct_codec)7);
	if (negative_count != 30U || positive_count != 2U || published_authorities) {
		fprintf(stderr, "FAIL unexpected counts negative=%u positive=%u\n",
			negative_count, positive_count);
		return 1;
	}
	printf("PASS native_source_header synthetic_readback=2 rejected=%u authority_publications=0\n",
	       negative_count);
	return 0;
}
