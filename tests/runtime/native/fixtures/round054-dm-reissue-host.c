/* Round054: same-address reissue tests; scalar observations only, no kernel lease. */
static void require_case(bool condition, unsigned int blocks,
		unsigned int fault, const char *stage)
{
	if (!condition) {
		fprintf(stderr, "ROUND054_DM_FIRST_ERROR blocks=%u fault=%u stage=%s\n",
			blocks, fault, stage);
		exit(1);
	}
}

static void run_reissue(unsigned int blocks, unsigned int fault)
{
	struct dm_target target = {.begin = 4096U, .len = 256U};
	swapz_u32 maps[32] = {0};
	struct swapz_dm context = {.target = &target, .accepting = true,
		.logical_pages = 32U, .physical_blocks = 512U, .maps = maps,
		.authority = {.maps = maps}};
	struct bio upper = {.bi_opf = REQ_OP_WRITE | REQ_SWAP,
		.bi_iter = {.bi_sector = 8U, .bi_size = SWAPZ_BLOCK_BYTES}};
	struct bio next_clone = upper;
	struct swapz_round053_internal_receipt old_receipt = {0}, current = {0};
	struct swapz_round053_internal_observation old = {
		.target = &target, .context = &context, .upper_bio = &upper,
		.target_relative_sector = 8U, .map_generation = 7U, .gc_epoch = 9U,
		.extent_start_block = 16U, .extent_blocks = blocks,
		.synthetic_lease_token = 19U, .original_uncompressed_bytes = 4096U,
		.synthetic_live_lease = true, .worker_owns_bio = true,
	};
	struct swapz_round053_internal_observation next;
	int status;

	target.private = &context;
	if (fault == 4U)
		old.extent_blocks = blocks == 1U ? 2U : 1U;
	require_case(swapz_round053_internal_receipt_step(&old_receipt, &old,
		SWAPZ_ROUND053_ACCEPT, false, 0) == 0, blocks, fault, "old-accept");
	require_case(swapz_round053_internal_receipt_step(&old_receipt, &old,
		SWAPZ_ROUND053_ABORT, false, -ECANCELED) == -ECANCELED,
		blocks, fault, "old-owner-abort");
	next = old;
	switch (fault) {
	case 0U: next.target_relative_sector = 16U; upper.bi_iter.bi_sector = 16U; break;
	case 1U: next.map_generation++; break;
	case 2U: next.gc_epoch++; break;
	case 3U: next.extent_start_block++; break;
	case 4U: next.extent_blocks = blocks; break;
	case 5U: next.synthetic_lease_token++; break;
	case 6U: next.upper_bio = &next_clone; break;
	case 7U: next.map_generation++; next.gc_epoch++; next.synthetic_lease_token++; break;
	default: exit(2);
	}
	require_case(swapz_round053_internal_receipt_step(&current, &next,
		SWAPZ_ROUND053_ACCEPT, false, 0) == 0, blocks, fault, "new-accept");
	context.accepting = false;
	/* The old callback arrives after a newer admitted worker's lower event. */
	require_case(swapz_round053_internal_receipt_step(&current, &next,
		SWAPZ_ROUND053_LOWER_COMPLETE, true, 0) == 0,
		blocks, fault, "current-durable-after-close");
	require_case(swapz_round053_internal_receipt_step(&old_receipt, NULL,
		SWAPZ_ROUND053_LOWER_COMPLETE, true, 0) == -EALREADY,
		blocks, fault, "old-late-callback");
	status = swapz_round053_internal_receipt_step(&current, &old,
		SWAPZ_ROUND053_ABORT, false, -ECANCELED);
	require_case(status == -ESTALE, blocks, fault, "stale-abort");
	require_case(current.phase == SWAPZ_ROUND053_DURABLE &&
		current.lower_callbacks == 1U && current.map_publications == 0U &&
		current.upper_ack_attempts == 0U && current.terminal_releases == 0U,
		blocks, fault, "stale-abort-no-effects");
	if (fault == 7U) {
		next.dtr_started = true;
		next.synthetic_live_lease = false;
		require_case(swapz_round053_internal_receipt_step(&current, &next,
			SWAPZ_ROUND053_PUBLISH, true, 0) == -ESHUTDOWN,
			blocks, fault, "teardown-no-map");
		/* A trusted receipt owner may cancel without dereferencing DM/BIO. */
		require_case(swapz_round053_internal_receipt_step(&current, NULL,
			SWAPZ_ROUND053_ABORT, false, -ECANCELED) == -ECANCELED,
			blocks, fault, "teardown-owner-abort");
		require_case(current.map_publications == 0U && current.upper_ack_attempts == 0U,
			blocks, fault, "teardown-no-publication-or-ack");
	} else {
		require_case(swapz_round053_internal_receipt_step(&current, &next,
			SWAPZ_ROUND053_PUBLISH, true, 0) == 0,
			blocks, fault, "current-map");
		require_case(swapz_round053_internal_receipt_step(&current, &next,
			SWAPZ_ROUND053_ACK, true, 0) == 0,
			blocks, fault, "current-ack");
		require_case(current.map_publications == 1U && current.upper_ack_attempts == 1U,
			blocks, fault, "one-map-one-synthetic-ack");
	}
	require_case(old_receipt.terminal_releases == 1U && current.terminal_releases == 1U,
		blocks, fault, "one-terminal-per-receipt");
	require_case(swapz_round053_internal_receipt_step(&current, NULL,
		SWAPZ_ROUND053_ACK, true, 0) == -EALREADY,
		blocks, fault, "late-ack-no-dereference");
}

int main(void)
{
	unsigned int cases = 0U;
	for (unsigned int blocks = 1U; blocks <= 4U; blocks *= 2U) {
		for (unsigned int fault = 0U; fault < 8U; ++fault) {
			run_reissue(blocks, fault);
			++cases;
		}
	}
	require_case(cases == 24U, 0U, 0U, "count");
	puts("ROUND054_DM_24_REISSUE_C_CASES_PASS AUTH0 PHASE_A=BLOCKED");
	return 0;
}
