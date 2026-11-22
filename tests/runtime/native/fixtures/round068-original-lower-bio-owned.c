// SPDX-License-Identifier: GPL-2.0-only
/*
 * Rootless source-bound lower BIO callback owner. Real linked authority.c
 * stages and owns physical extents; a FAKE memory driver queues BIO-shaped
 * requests and invokes callbacks in chosen order. An independent pinned
 * original-linux KUnit (separate job) proves actual struct bio, page/bvec,
 * REQ_OP_WRITE/FUA/FLUSH/READ and bio_endio execution. No physical IO.
 *
 * Reuse the Round067 genuine original codec fixture and its byte-exact
 * liblzo2/LZ4 libraries; no duplicate/reinterpreted RAW page format.
 */
#define main round067_original_main
#include "round067-import-disk-payload-read.c"
#undef main

static struct swapz_import_lower_bio_owner writer;
static struct swapz_import_lower_bio_owner reader;
/* Caller-owned bvec pages outlive each pending lower WRITE callback. */
static swapz_u8 write_bvec_pages[SWAPZ_MAX_BLOCKS][SWAPZ_BLOCK_BYTES];

static int fake_memory_write(const struct swapz_import_lower_bio_request *request,
			     const struct swapz_tx *transaction,
			     const struct swapz_authority_import_spec *spec)
{
	swapz_u8 *destination;
	swapz_u8 block;

	if (!request || !transaction || !spec ||
	    request->sector != ((swapz_u64)transaction->start_block + 1U) *
			       SWAPZ_IMPORT_LOWER_SECTORS_PER_BLOCK ||
	    request->bytes != (swapz_u32)transaction->extent_blocks *
			      SWAPZ_BLOCK_BYTES ||
	    (request->opf & 0xffU) != SWAPZ_IMPORT_LOWER_OP_WRITE)
		return -EINVAL;
	memset(write_bvec_pages, 0, sizeof(write_bvec_pages));
	memcpy(write_bvec_pages, source_bytes, spec->compressed_length);
	destination = extent_at(transaction->start_block);
	if (!destination)
		return -ERANGE;
	/* Four actual caller-owned, fixed contiguous 4096 bvec payload pages.
	 * Native KUnit owns/iterates genuine Linux struct bio_vec instead. */
	for (block = 0U; block < transaction->extent_blocks; ++block)
		memcpy(destination + (size_t)block * SWAPZ_BLOCK_BYTES,
		       write_bvec_pages[block], SWAPZ_BLOCK_BYTES);
	return 0;
}

static int prepare_queued_write(swapz_u32 logical, swapz_u64 epoch,
				swapz_u8 codec, swapz_u8 blocks,
				swapz_u64 replaces_ticket, int fua_supported,
				struct swapz_tx *transaction, swapz_u64 *ticket,
				struct swapz_authority_import_spec *spec,
				struct swapz_import_lower_bio_request *request)
{
	int error = prepare_spec(logical, epoch, codec, spec);

	if (error)
		return error;
	error = stage_submit(spec, blocks, replaces_ticket, transaction, ticket);
	if (error)
		return error;
	return swapz_import_lower_begin_write(&writer, transaction, *ticket,
					       fua_supported, request);
}

static int finish_queued_write(const struct swapz_import_lower_bio_request *request,
			       const struct swapz_tx *transaction,
			       const struct swapz_authority_import_spec *spec)
{
	int error = fake_memory_write(request, transaction, spec);

	if (error)
		return error;
	return swapz_import_lower_end_write(&writer, request, request->bytes,
					   0, extent_at(transaction->start_block),
					   NULL);
}

/* Exact independent whole-original 4096-byte decode after the complete
 * lower READ callback copied verified compressed bytes to owned scratch. */
static int decode_completed_original(const struct swapz_authority_import_spec *spec,
				     swapz_u8 *destination)
{
	lzo_uint decoded_length = SWAPZ_BLOCK_BYTES;
	swapz_u8 digest[SHA256_DIGEST_LENGTH];
	int result;

	if (!spec || !destination)
		return -EINVAL;
	if (spec->codec == SWAPZ_AUTHORITY_IMPORT_LZ4) {
		result = LZ4_decompress_safe((const char *)compressed,
				(char *)decoded, (int)spec->compressed_length,
				(int)SWAPZ_BLOCK_BYTES);
		if (result != (int)SWAPZ_BLOCK_BYTES)
			return -EBADMSG;
	} else if (spec->codec == SWAPZ_AUTHORITY_IMPORT_LZO1X) {
		result = lzo1x_decompress_safe(compressed, spec->compressed_length,
					       decoded, &decoded_length, NULL);
		if (result != LZO_E_OK || decoded_length != SWAPZ_BLOCK_BYTES)
			return -EBADMSG;
	} else {
		return -EOPNOTSUPP;
	}
	if (!SHA256(decoded, SWAPZ_BLOCK_BYTES, digest))
		return -EIO;
	if (memcmp(digest, spec->original_sha256, sizeof(digest)) ||
	    memcmp(decoded, original, SWAPZ_BLOCK_BYTES))
		return -EBADMSG;
	memcpy(destination, decoded, SWAPZ_BLOCK_BYTES);
	return 0;
}

static int fake_memory_read(const struct swapz_import_lower_bio_request *request,
			    const struct swapz_import_disk_view *view)
{
	swapz_u8 *source;

	if (!request || !view)
		return -EINVAL;
	source = extent_at(view->start_block);
	if (!source ||
	    request->sector != ((swapz_u64)view->start_block + 1U) *
			SWAPZ_IMPORT_LOWER_SECTORS_PER_BLOCK ||
	    (request->opf & 0xffU) != SWAPZ_IMPORT_LOWER_OP_READ ||
	    request->bytes != (swapz_u32)view->extent_blocks * SWAPZ_BLOCK_BYTES)
		return -EINVAL;
	memcpy(read_extent, source, request->bytes);
	return 0;
}

static int read_owned_ticket(swapz_u64 ticket, swapz_u8 *destination)
{
	struct swapz_import_lower_bio_request request;
	struct swapz_import_disk_view pinned;
	int error;

	error = swapz_import_lower_begin_read(&reader, ticket, &request);
	if (error)
		return error;
	pinned = reader.pinned_view;
	error = fake_memory_read(&request, &pinned);
	if (error)
		return error;
	error = swapz_import_lower_end_read(&reader, &request,
					  request.bytes, 0, read_extent,
					  compressed, sizeof(compressed));
	return error ? error : decode_completed_original(&pinned.spec, destination);
}

static int write_fua_read_both_codecs_and_classes(void)
{
	const swapz_u8 classes[] = { 1U, 2U, 4U };
	const swapz_u8 codecs[] = {
		SWAPZ_AUTHORITY_IMPORT_LZ4, SWAPZ_AUTHORITY_IMPORT_LZO1X
	};
	size_t codec_index, class_index;

	for (codec_index = 0U; codec_index < sizeof(codecs); ++codec_index) {
		for (class_index = 0U; class_index < sizeof(classes); ++class_index) {
			struct swapz_authority_import_spec spec;
			struct swapz_import_lower_bio_request request;
			struct swapz_tx tx;
			swapz_u64 ticket;
			const swapz_u8 blocks = classes[class_index];

			CHECK(initialize() == 0);
			swapz_import_lower_init(&writer, &pool);
			swapz_import_lower_init(&reader, &pool);
			CHECK(prepare_queued_write(3U, 1U, codecs[codec_index],
					blocks, 0U, 1, &tx, &ticket,
					&spec, &request) == 0);
			CHECK(request.opf == (SWAPZ_IMPORT_LOWER_OP_WRITE |
					    SWAPZ_IMPORT_LOWER_REQ_FUA));
			CHECK(!maps[3].valid && !live_records[tx.start_block] &&
			      swapz_import_disk_pin(&pool, ticket,
				&(struct swapz_import_disk_view){ 0 }) == -ESTALE);
			CHECK(finish_queued_write(&request, &tx, &spec) == 0);
			CHECK(swapz_import_lower_end_write(&writer, &request,
					request.bytes, 0, extent_at(tx.start_block),
					NULL) == -ESTALE);
			CHECK(live_records[tx.start_block] == 1U &&
			      authority.committed_blocks == blocks &&
			      !maps[3].valid && header_intact());
			memset(output, 0x74, sizeof(output));
			CHECK(read_owned_ticket(ticket, output) == 0);
			CHECK(!memcmp(output, original, SWAPZ_BLOCK_BYTES));
			CHECK(swapz_import_lower_close(&writer) == 0 &&
			      swapz_import_lower_close(&reader) == 0);
			CHECK(swapz_import_disk_retire(&pool, ticket) == 0);
			CHECK(swapz_import_disk_close(&pool) == 0);
		}
	}
	return 0;
}

static int fallback_postwrite_flush_and_duplicate(void)
{
	struct swapz_authority_import_spec spec;
	struct swapz_import_lower_bio_request write_request, flush_request;
	struct swapz_tx tx;
	swapz_u64 ticket;

	CHECK(initialize() == 0);
	swapz_import_lower_init(&writer, &pool);
	swapz_import_lower_init(&reader, &pool);
	CHECK(prepare_queued_write(5U, 1U, SWAPZ_AUTHORITY_IMPORT_LZ4, 2U,
				   0U, 0, &tx, &ticket, &spec,
				   &write_request) == 0);
	CHECK(write_request.opf == SWAPZ_IMPORT_LOWER_OP_WRITE);
	CHECK(fake_memory_write(&write_request, &tx, &spec) == 0);
	CHECK(swapz_import_lower_end_write(&writer, &write_request,
				  write_request.bytes, 0,
				  extent_at(tx.start_block),
				  &flush_request) == -EINPROGRESS);
	CHECK(writer.phase == SWAPZ_IMPORT_LOWER_POSTFLUSH_PENDING &&
	      !live_records[tx.start_block] && !maps[5].valid);
	CHECK(flush_request.opf ==
	      (SWAPZ_IMPORT_LOWER_OP_FLUSH | SWAPZ_IMPORT_LOWER_REQ_PREFLUSH));
	CHECK(flush_request.bytes == 0U &&
	      flush_request.token != write_request.token &&
	      flush_request.sector == write_request.sector);
	CHECK(swapz_import_lower_end_write(&writer, &write_request,
				  write_request.bytes, 0,
				  extent_at(tx.start_block),
				  NULL) == -ESTALE);
	CHECK(swapz_import_lower_end_flush(&writer, &flush_request, 0,
					  extent_at(tx.start_block)) == 0);
	CHECK(swapz_import_lower_end_flush(&writer, &flush_request, 0,
					  extent_at(tx.start_block)) == -ESTALE);
	CHECK(live_records[tx.start_block] == 1U && !maps[5].valid);
	CHECK(read_owned_ticket(ticket, output) == 0);
	CHECK(!memcmp(output, original, SWAPZ_BLOCK_BYTES));
	CHECK(swapz_import_disk_retire(&pool, ticket) == 0);
	return 0;
}

static int wrong_callback_token_sector_op_length(void)
{
	struct swapz_authority_import_spec spec;
	struct swapz_import_lower_bio_request request, forged;
	struct swapz_tx tx;
	swapz_u64 ticket;

	CHECK(initialize() == 0);
	swapz_import_lower_init(&writer, &pool);
	CHECK(prepare_queued_write(6U, 1U, SWAPZ_AUTHORITY_IMPORT_LZ4, 1U,
				   0U, 1, &tx, &ticket, &spec, &request) == 0);
	CHECK(fake_memory_write(&request, &tx, &spec) == 0);
	forged = request;
	forged.token++;
	CHECK(swapz_import_lower_end_write(&writer, &forged, forged.bytes, 0,
				  extent_at(tx.start_block), NULL) == -ESTALE);
	forged = request;
	forged.sector -= SWAPZ_IMPORT_LOWER_SECTORS_PER_BLOCK;
	CHECK(swapz_import_lower_end_write(&writer, &forged, forged.bytes, 0,
				  extent_at(tx.start_block), NULL) == -ESTALE);
	forged = request;
	forged.opf = SWAPZ_IMPORT_LOWER_OP_READ;
	CHECK(swapz_import_lower_end_write(&writer, &forged, forged.bytes, 0,
				  extent_at(tx.start_block), NULL) == -ESTALE);
	forged = request;
	forged.bytes--;
	CHECK(swapz_import_lower_end_write(&writer, &forged, forged.bytes, 0,
				  extent_at(tx.start_block), NULL) == -ESTALE);
	CHECK(!maps[6].valid && !live_records[tx.start_block] &&
	      authority.in_flight == 1U);
	CHECK(swapz_import_lower_end_write(&writer, &request, request.bytes,
				  0, extent_at(tx.start_block), NULL) == 0);
	CHECK(swapz_import_disk_retire(&pool, ticket) == 0);
	CHECK(header_intact());
	return 0;
}

static int short_error_torn_write_and_requeue(void)
{
	struct swapz_authority_import_spec spec;
	struct swapz_import_lower_bio_request request;
	struct swapz_tx tx;
	swapz_u64 ticket, old_token;

	CHECK(initialize() == 0);
	swapz_import_lower_init(&writer, &pool);
	CHECK(prepare_queued_write(7U, 1U, SWAPZ_AUTHORITY_IMPORT_LZ4, 4U,
				   0U, 1, &tx, &ticket, &spec, &request) == 0);
	CHECK(fake_memory_write(&request, &tx, &spec) == 0);
	old_token = request.token;
	CHECK(swapz_import_lower_end_write(&writer, &request, 13U, 0,
				  extent_at(tx.start_block), NULL) == -EIO);
	CHECK(authority.abandoned_blocks == 4U && !maps[7].valid &&
	      !live_records[tx.start_block] &&
	      extent_classes[tx.start_block] == 4U);
	CHECK(swapz_import_disk_abort(&pool, ticket) == 0);
	CHECK(prepare_queued_write(7U, 1U, SWAPZ_AUTHORITY_IMPORT_LZ4, 4U,
				   0U, 1, &tx, &ticket, &spec, &request) == 0);
	CHECK(request.token > old_token);
	CHECK(fake_memory_write(&request, &tx, &spec) == 0);
	CHECK(swapz_import_lower_end_write(&writer, &request, request.bytes,
				  -EIO, extent_at(tx.start_block), NULL) == -EIO);
	CHECK(swapz_import_disk_abort(&pool, ticket) == 0);
	CHECK(prepare_queued_write(7U, 1U, SWAPZ_AUTHORITY_IMPORT_LZ4, 4U,
				   0U, 1, &tx, &ticket, &spec, &request) == 0);
	CHECK(fake_memory_write(&request, &tx, &spec) == 0);
	extent_at(tx.start_block)[2] ^= 0x40U;
	CHECK(swapz_import_lower_end_write(&writer, &request, request.bytes,
				  0, extent_at(tx.start_block), NULL) == -EBADMSG);
	CHECK(swapz_import_disk_abort(&pool, ticket) == 0);
	CHECK(authority.committed_blocks == 0U && header_intact());
	return 0;
}

static int flush_failure_and_close_submitted(void)
{
	struct swapz_authority_import_spec spec;
	struct swapz_import_lower_bio_request write_request, flush_request;
	struct swapz_tx tx;
	swapz_u64 ticket;

	CHECK(initialize() == 0);
	swapz_import_lower_init(&writer, &pool);
	CHECK(prepare_queued_write(8U, 1U, SWAPZ_AUTHORITY_IMPORT_LZO1X, 2U,
				   0U, 0, &tx, &ticket, &spec,
				   &write_request) == 0);
	CHECK(fake_memory_write(&write_request, &tx, &spec) == 0);
	CHECK(swapz_import_lower_end_write(&writer, &write_request,
			write_request.bytes, 0, extent_at(tx.start_block),
			&flush_request) == -EINPROGRESS);
	CHECK(swapz_import_lower_end_flush(&writer, &flush_request,
					  -EIO, extent_at(tx.start_block)) == -EIO);
	CHECK(!maps[8].valid && !live_records[tx.start_block] &&
	      authority.committed_blocks == 0U &&
	      swapz_import_disk_abort(&pool, ticket) == 0);
	CHECK(prepare_queued_write(8U, 1U, SWAPZ_AUTHORITY_IMPORT_LZO1X, 2U,
				   0U, 1, &tx, &ticket, &spec, &write_request) == 0);
	CHECK(fake_memory_write(&write_request, &tx, &spec) == 0);
	/* Isolate the exact callback-owner close fence BEFORE independently
	 * closing the pool. Otherwise the pool's own close check masks the
	 * actual owner-close source mutation (an inert semantic oracle). */
	CHECK(swapz_import_lower_close(&writer) == -EBUSY);
	CHECK(swapz_import_lower_end_write(&writer, &write_request,
			write_request.bytes, 0, extent_at(tx.start_block),
			NULL) == -ECANCELED);
	CHECK(swapz_import_disk_abort(&pool, ticket) == 0);
	CHECK(swapz_import_disk_close(&pool) == 0);
	CHECK(swapz_import_lower_close(&writer) == 0);
	CHECK(!maps[8].valid && authority.in_flight == 0U);

	/* Separately prove real authority pool close while BIO is queued,
	 * without mistaking either independent cancellation fence for the
	 * first case or publishing an upper ACK. */
	CHECK(initialize() == 0);
	swapz_import_lower_init(&writer, &pool);
	CHECK(prepare_queued_write(8U, 1U, SWAPZ_AUTHORITY_IMPORT_LZO1X, 2U,
				   0U, 1, &tx, &ticket, &spec, &write_request) == 0);
	CHECK(fake_memory_write(&write_request, &tx, &spec) == 0);
	CHECK(swapz_import_disk_close(&pool) == -EBUSY);
	CHECK(swapz_import_lower_end_write(&writer, &write_request,
			write_request.bytes, 0, extent_at(tx.start_block),
			NULL) == -ECANCELED);
	CHECK(swapz_import_disk_abort(&pool, ticket) == 0);
	CHECK(swapz_import_disk_close(&pool) == 0);
	CHECK(swapz_import_lower_close(&writer) == 0);
	CHECK(!maps[8].valid && authority.in_flight == 0U &&
	      header_intact());
	return 0;
}

static int held_old_read_during_gc_and_read_failure(void)
{
	struct swapz_authority_import_spec spec;
	struct swapz_import_lower_bio_request write_request, read_request;
	struct swapz_import_disk_view old_view;
	struct swapz_tx old_tx, new_tx;
	swapz_u64 old_ticket, new_ticket;
	swapz_u32 old_start, new_start;

	CHECK(initialize() == 0);
	swapz_import_lower_init(&writer, &pool);
	swapz_import_lower_init(&reader, &pool);
	CHECK(prepare_queued_write(9U, 1U, SWAPZ_AUTHORITY_IMPORT_LZ4, 2U,
				   0U, 1, &old_tx, &old_ticket, &spec,
				   &write_request) == 0);
	CHECK(finish_queued_write(&write_request, &old_tx, &spec) == 0);
	old_start = old_tx.start_block;
	CHECK(swapz_import_lower_begin_read(&reader, old_ticket,
					    &read_request) == 0);
	old_view = reader.pinned_view;
	CHECK(fake_memory_read(&read_request, &old_view) == 0);
	CHECK(prepare_queued_write(9U, 2U, SWAPZ_AUTHORITY_IMPORT_LZ4, 4U,
				   old_ticket, 1, &new_tx, &new_ticket, &spec,
				   &write_request) == 0);
	CHECK(finish_queued_write(&write_request, &new_tx, &spec) == 0);
	new_start = new_tx.start_block;
	CHECK(live_records[old_start] == 1U &&
	      live_records[new_start] == 1U && !maps[9].valid);
	CHECK(swapz_import_disk_pin(&pool, old_ticket,
				&(struct swapz_import_disk_view){ 0 }) == -ESTALE);
	CHECK(swapz_import_lower_end_read(&reader, &read_request,
			read_request.bytes, 0, read_extent,
			compressed, sizeof(compressed)) == 0);
	CHECK(live_records[old_start] == 0U &&
	      live_records[new_start] == 1U);
	CHECK(decode_completed_original(&old_view.spec, output) == 0);
	CHECK(!memcmp(output, original, SWAPZ_BLOCK_BYTES));
	CHECK(read_owned_ticket(new_ticket, output) == 0);
	CHECK(swapz_import_lower_end_read(&reader, &read_request,
			read_request.bytes, 0, read_extent,
			compressed, sizeof(compressed)) == -ESTALE);
	CHECK(swapz_import_lower_begin_read(&reader, new_ticket,
					    &read_request) == 0);
	CHECK(fake_memory_read(&read_request, &reader.pinned_view) == 0);
	memset(compressed, 0x5d, sizeof(compressed));
	CHECK(swapz_import_lower_end_read(&reader, &read_request,
			read_request.bytes - 1U, 0, read_extent,
			compressed, sizeof(compressed)) == -EIO);
	CHECK(compressed[0] == 0x5dU && compressed[SWAPZ_BLOCK_BYTES - 1U] == 0x5dU);
	CHECK(swapz_import_disk_retire(&pool, new_ticket) == 0);
	CHECK(swapz_import_disk_close(&pool) == 0 && header_intact());
	return 0;
}

static int pending_read_close_and_ticket_aba(void)
{
	struct swapz_authority_import_spec spec;
	struct swapz_import_lower_bio_request write_request, read_request, forged;
	struct swapz_tx tx;
	swapz_u64 ticket;

	CHECK(initialize() == 0);
	swapz_import_lower_init(&writer, &pool);
	swapz_import_lower_init(&reader, &pool);
	CHECK(prepare_queued_write(10U, 1U, SWAPZ_AUTHORITY_IMPORT_LZO1X, 1U,
				   0U, 1, &tx, &ticket, &spec,
				   &write_request) == 0);
	CHECK(finish_queued_write(&write_request, &tx, &spec) == 0);
	CHECK(swapz_import_lower_begin_read(&reader, ticket,
					    &read_request) == 0);
	CHECK(fake_memory_read(&read_request, &reader.pinned_view) == 0);
	forged = read_request;
	forged.token++;
	CHECK(swapz_import_lower_end_read(&reader, &forged,
			read_request.bytes, 0, read_extent,
			compressed, sizeof(compressed)) == -ESTALE);
	CHECK(swapz_import_lower_close(&reader) == -EBUSY);
	CHECK(swapz_import_disk_close(&pool) == -EBUSY);
	memset(compressed, 0x5d, sizeof(compressed));
	CHECK(swapz_import_lower_end_read(&reader, &read_request,
			read_request.bytes, 0, read_extent,
			compressed, sizeof(compressed)) == -ECANCELED);
	CHECK(compressed[0] == 0x5dU &&
	      compressed[SWAPZ_BLOCK_BYTES - 1U] == 0x5dU);
	CHECK(swapz_import_lower_end_read(&reader, &read_request,
			read_request.bytes, 0, read_extent,
			compressed, sizeof(compressed)) == -ESTALE);
	CHECK(swapz_import_lower_close(&reader) == 0);
	CHECK(swapz_import_disk_close(&pool) == 0);
	CHECK(swapz_import_lower_begin_read(&reader, ticket,
					    &read_request) == -EBUSY);
	return 0;
}

static const struct case_definition lower_cases[] = {
	{ "write_fua_read_both_codecs_and_classes", write_fua_read_both_codecs_and_classes },
	{ "fallback_postwrite_flush_and_duplicate", fallback_postwrite_flush_and_duplicate },
	{ "wrong_callback_token_sector_op_length", wrong_callback_token_sector_op_length },
	{ "short_error_torn_write_and_requeue", short_error_torn_write_and_requeue },
	{ "flush_failure_and_close_submitted", flush_failure_and_close_submitted },
	{ "held_old_read_during_gc_and_read_failure", held_old_read_during_gc_and_read_failure },
	{ "pending_read_close_and_ticket_aba", pending_read_close_and_ticket_aba },
};

int main(int argc, char **argv)
{
	size_t index, passed = 0U;

	for (index = 0U; index < sizeof(lower_cases) / sizeof(lower_cases[0]);
	     ++index) {
		if (argc == 2 && strcmp(argv[1], lower_cases[index].name))
			continue;
		case_name = lower_cases[index].name;
		if (lower_cases[index].run())
			return 1;
		++passed;
	}
	if (!passed)
		return 2;
	if (argc == 1)
		printf("PASS lower_bio_shaped_callback_cases=%zu "
		       "profiles=2 classes=1,2,4 original_decoded=4096 "
		       "map_bytes=%zu pool_bytes=%zu real_allocator=YES "
		       "bio_kernel_execution=SEPARATE_KUNIT memory_fua=MODELED "
		       "PHASE_A=BLOCKED\n",
		       passed, sizeof(struct swapz_map), sizeof(pool));
	return 0;
}
