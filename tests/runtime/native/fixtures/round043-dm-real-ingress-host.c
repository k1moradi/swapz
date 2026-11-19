/*
 * Round043 genuine production swapz_map() callsite text + helper C extraction.
 * Host-only GPL v1 provider is intentionally a FAKE value source; the original
 * compiled pin/clone and unique GPL export are proven separately by true KDIR.
 * No live mapping/ACK/lower IO. Inherit every Round041/040/038 source test.
 */
/* ROUND043_INHERIT_REAL_PRIOR_SOURCE */
#define BIO_CLONED 4U
#define GFP_ATOMIC 0x20U
#ifndef READ_ONCE
#define READ_ONCE(value) (value)
#endif

static unsigned int round043_private_allocations;
static unsigned int round043_private_frees;
static unsigned int round043_real_map_observation_calls;
static bool round043_inject_allocation_failure;

static void *round043_host_private_allocate(size_t allocation_size,
					   unsigned int allocation_flags)
{
	assert(allocation_flags == GFP_ATOMIC);
	assert(allocation_size == SWAPZ_MAX_COMPRESSED);
	++round043_private_allocations;
	if (round043_inject_allocation_failure)
		return NULL;
	return malloc(allocation_size);
}

static void round043_host_private_free(void *private_data)
{
	size_t byte_index;

	assert(private_data);
	for (byte_index = 0U; byte_index < SWAPZ_MAX_COMPRESSED; ++byte_index)
		assert(((const swapz_u8 *)private_data)[byte_index] == 0U);
	++round043_private_frees;
	free(private_data);
}

#define kmalloc(size, flags) round043_host_private_allocate((size), (flags))
#define kfree(pointer) round043_host_private_free((pointer))
/* ROUND043_EXTRACT_ACTUAL_DM_INGRESS_HELPER */

static int round043_traced_observe_real_map_v1(
		const struct dm_target *target, const struct swapz_dm *context,
		const struct bio *upper_bio)
{
	++round043_real_map_observation_calls;
	return swapz_round043_dm_observe_real_map_v1(target, context, upper_bio);
}

/*
 * The exact text below is extracted FROM production swapz_map(), not a hand
 * written replacement. This traced wrapper only counts dispatch attempts;
 * it calls the actual extracted helper and never publishes its result.
 */
static void round043_execute_real_map_callsite(
		struct dm_target *ti, struct swapz_dm *ctx, struct bio *bio)
{
	sector_t count = bio_sectors(bio);

#define swapz_round043_dm_observe_real_map_v1 round043_traced_observe_real_map_v1
/* ROUND043_EXTRACT_ACTUAL_SWAPZ_MAP_CALLSITE */
#undef swapz_round043_dm_observe_real_map_v1
}

static void round043_execute_ingress_negative(unsigned int extent_blocks,
					    unsigned int fault)
{
	struct swapz_dm context = { 0 };
	struct dm_target target = {
		.begin = 64U, .len = 32U * SWAPZ_SECTORS
	};
	struct dm_target replacement_target = {
		.begin = 64U, .len = 32U * SWAPZ_SECTORS
	};
	swapz_u8 original_page[SWAPZ_BLOCK_BYTES];
	swapz_u8 mock_upper_output[SWAPZ_BLOCK_BYTES];
	swapz_u8 upper_before[SWAPZ_BLOCK_BYTES];
	swapz_u8 mock_physical_header[SWAPZ_BLOCK_BYTES];
	swapz_u8 header_before[SWAPZ_BLOCK_BYTES];
	struct bio_vec original_vector = {
		.bv_page = original_page, .bv_offset = 0U,
		.bv_len = SWAPZ_BLOCK_BYTES
	};
	struct bio upper = {
		.lifetime_pinned = true,
		.full_uncompressed_4096_swap_write = true,
		.bi_iter = {
			.bi_sector = 5U * SWAPZ_SECTORS,
			.bi_size = SWAPZ_BLOCK_BYTES
		},
		.bi_io_vec = &original_vector,
		.bi_vcnt = 0U,
		.bi_opf = REQ_OP_WRITE | REQ_SWAP,
		.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK
	};
	struct bio bio_before;
	struct swapz_map map_before;
	unsigned int prior_provider_calls;
	unsigned int prior_allocations, prior_frees;
	unsigned int expected_callsite_attempts;
	swapz_u32 compressed_length;
	size_t byte_index;
	int result, expected_error = -EOPNOTSUPP;
	int reads_before = lower_reads, writes_before = lower_writes;

	assert(extent_blocks == 1U || extent_blocks == 2U ||
	       extent_blocks == 4U);
	assert(fault < 30U);
	memset(maps, 0, sizeof(maps));
	for (byte_index = 0U; byte_index < SWAPZ_BLOCK_BYTES; ++byte_index)
		original_page[byte_index] = 0x65U;
	original_page[0] = 0x71U;
	original_page[SWAPZ_BLOCK_BYTES - 1U] = 0x19U;
	compressed_length = (swapz_u32)LZ4_compress_default(
		(const char *)original_page, (char *)source_lz4_bytes,
		SWAPZ_BLOCK_BYTES, SWAPZ_MAX_COMPRESSED);
	assert(compressed_length > 0U &&
	       compressed_length <= SWAPZ_MAX_COMPRESSED);
	source_lz4_length = (swapz_u16)compressed_length;

	original_provider_view = (struct swapz_ci_lz4_owned_view_v1) {
		.source_swap_entry = swp_entry(2U, 39U).val,
		.source_slot_epoch = 41U,
		.stored_entry_identity = 99U,
		.compressed_crc32c = swapz_crc32c_bytes(
			source_lz4_bytes, compressed_length),
		.compressed_length = (swapz_u16)compressed_length,
		.decoded_length = SWAPZ_BLOCK_BYTES,
		.representation_version = 1U,
		.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC
	};
	assert(SHA256(original_page, sizeof(original_page),
		      original_provider_view.original_sha256));
	context.target = &target;
	context.logical_pages = 32U;
	context.authority.logical_pages = 32U;
	context.authority.physical_blocks = 32U;
	context.authority.gc_destination = 7U;
	context.authority.maps = maps;
	context.maps = maps;
	context.accepting = true;
	target.private = &context;
	replacement_target.private = &context;
	maps[5].valid = true;
	maps[5].raw = false;
	maps[5].generation = 13U;
	maps[5].start_block = 6U;
	maps[5].extent_blocks = extent_blocks == 1U ? 1U :
		(extent_blocks == 2U ? 2U : 4U);
	maps[5].payload_length = source_lz4_length;
	maps[5].payload_crc32c = original_provider_view.compressed_crc32c;
	memset(mock_upper_output, 0xc8, sizeof(mock_upper_output));
	memset(mock_physical_header, 0x5d, sizeof(mock_physical_header));
	memcpy(header_before, mock_physical_header, sizeof(header_before));
	memcpy(upper_before, mock_upper_output, sizeof(upper_before));
	injected_provider_errno = 0;
	round043_inject_allocation_failure = false;

	switch (fault) {
	case 0U: break; /* a FAKE valid copy still returns NO_AUTHORITY */
	case 1U: upper.bi_flags |= 1U << BIO_CLONED; break;
	case 2U: upper.bi_iter.bi_size = 2048U; break;
	case 3U: upper.bi_iter.bi_sector++; expected_error = -ERANGE; break;
	case 4U: upper.bi_iter.bi_sector = target.len - 4U;
		expected_error = -ERANGE; break;
	case 5U: upper.bi_iter.bi_sector = ~(sector_t)0 - 3U;
		expected_error = -ERANGE; break;
	case 6U: upper.bi_opf = REQ_OP_WRITE; break;
	case 7U: upper.bi_opf = REQ_SWAP; break; /* actual READ opcode zero */
	case 8U: upper.bi_iter.bi_size = 0U; break;
	case 9U: target.private = &replacement_target;
		expected_error = -ESTALE; break;
	case 10U: context.target = &replacement_target;
		expected_error = -ESTALE; break;
	case 11U: context.accepting = false; expected_error = -ESTALE; break;
	case 12U: context.logical_pages = 31U;
		expected_error = -ESTALE; break;
	case 13U: injected_provider_errno = -ESTALE;
		expected_error = -ESTALE; break;
	case 14U: injected_provider_errno = -EOPNOTSUPP; break;
	case 15U: original_provider_view.source_swap_entry = 0U;
		expected_error = -ESTALE; break;
	case 16U: original_provider_view.source_slot_epoch = 0U;
		expected_error = -ESTALE; break;
	case 17U: original_provider_view.stored_entry_identity = 0U;
		expected_error = -ESTALE; break;
	case 18U: original_provider_view.compressed_length = 0U;
		expected_error = -EMSGSIZE; break;
	case 19U: original_provider_view.compressed_length =
			SWAPZ_MAX_COMPRESSED + 1U;
		expected_error = -EMSGSIZE; break;
	case 20U: original_provider_view.decoded_length--;
		expected_error = -EMSGSIZE; break;
	case 21U: original_provider_view.codec = 0xffU; break;
	case 22U: original_provider_view.representation_version = 2U; break;
	case 23U: memset(original_provider_view.original_sha256, 0,
			 sizeof(original_provider_view.original_sha256));
		expected_error = -ENODATA; break;
	case 24U: original_provider_view.compressed_crc32c++;
		expected_error = -EBADMSG; break;
	case 25U: source_lz4_bytes[0] ^= 0x1U;
		expected_error = -EBADMSG; break;
	case 26U: maps[5].generation++; break; /* GC ABA not an auth lease */
	case 27U: target.begin += 1024U; break; /* table-relative differs */
	case 28U: round043_inject_allocation_failure = true;
		expected_error = -ENOMEM; break;
	case 29U: target.len += 4U; expected_error = -ESTALE; break;
	default: assert(0);
	}
	/* The only value field crosses from original fake-provider to DM; the
	 * real source header/ptr ownership and GPL kernel modpost are separately
	 * checked by original pinned Kbuild. No active source bdev/GC ref exists.
	 */
	map_before = maps[5];
	bio_before = upper;
	prior_provider_calls = (unsigned int)provider_calls;
	prior_allocations = round043_private_allocations;
	prior_frees = round043_private_frees;
	round043_real_map_observation_calls = 0U;

	result = swapz_round043_dm_observe_real_map_v1(&target, &context,
						      &upper);
	assert(result == expected_error);
	expected_callsite_attempts =
		bio_op(&upper) == REQ_OP_WRITE &&
		bio_sectors(&upper) == SWAPZ_SECTORS &&
		upper.bi_iter.bi_size == SWAPZ_BLOCK_BYTES ? 1U : 0U;
	round043_execute_real_map_callsite(&target, &context, &upper);
	assert(round043_real_map_observation_calls ==
	       expected_callsite_attempts);
	assert(result < 0);
	assert(!memcmp(&map_before, &maps[5], sizeof(map_before)));
	assert(!memcmp(&bio_before, &upper, sizeof(upper)));
	assert(!memcmp(upper_before, mock_upper_output,
		       sizeof(mock_upper_output)));
	assert(!memcmp(header_before, mock_physical_header,
		       sizeof(mock_physical_header)));
	assert(lower_reads == reads_before && lower_writes == writes_before);
	assert(round043_private_frees - prior_frees <= 2U);
	assert(round043_private_allocations - prior_allocations <= 2U);
	if (round043_inject_allocation_failure)
		assert(round043_private_frees == prior_frees);
	else
		assert(round043_private_frees - prior_frees ==
		       round043_private_allocations - prior_allocations);
	if (fault == 1U || fault == 2U || fault == 6U ||
	    fault == 7U || fault == 8U)
		assert(provider_calls == (int)prior_provider_calls);
	round043_inject_allocation_failure = false;
	memzero_explicit(original_page, sizeof(original_page));
	memzero_explicit(source_lz4_bytes, sizeof(source_lz4_bytes));
	memzero_explicit(&original_provider_view, sizeof(original_provider_view));
}

int main(void)
{
	unsigned int extent_blocks, fault;

	assert(round041_fixture_main() == 0);
	for (extent_blocks = 1U; extent_blocks <= 4U; extent_blocks *= 2U)
		for (fault = 0U; fault < 30U; ++fault)
			round043_execute_ingress_negative(extent_blocks, fault);
	puts("ROUND043_REAL_PRODUCT_MAP_INGRESS_90_NO_AUTHORITY_PASS");
	return 0;
}
