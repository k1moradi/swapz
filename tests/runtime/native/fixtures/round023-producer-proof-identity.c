// SPDX-License-Identifier: GPL-2.0
/*
 * Round023 Agent2 addendum: exact staged C store-time zpool allocation proof
 * and typed source-only carrier. Included AFTER the real disabled C body.
 * Host entries/slot/folio are MOCKED; no loaded Linux or DM is exercised.
 */
static void round023_stored_allocation_identity_regression(void)
{
	struct zswap_entry stored_entry = {
		.swpentry = { .val = 71 },
		.length = 120,
		.handle = 31,
	};
	struct zswap_entry newer_entry = {
		.swpentry = { .val = 71 },
		.length = 120,
		.handle = 32,
	};
	struct zswap_pool other_pool = { "lz4", &tree };
	swp_entry_t original_slot = { .val = 71 };
	struct folio locked_folio = { true };
	struct zswap_swapz_stored_proof stored_proof = { 0 };
	struct zswap_swapz_owned_payload source_owner = { 0 };
	struct zswap_swapz_compressed_carrier_v1 carrier = { 0 };
	struct zswap_swapz_compressed_carrier_v1 late_carrier = { 0 };
	const int previous_allocations = allocations;
	const int previous_releases = freed;
	const struct zswap_pool *saved_pool;
	unsigned int saved_length;
	unsigned long saved_handle;

	tree.ptr = &stored_entry;
	host_pool.tfm_name = "lz4";
	for (unsigned int byte_index = 0; byte_index < PAGE_SIZE; ++byte_index)
		zpool_bytes[byte_index] = (u8)(byte_index % 251U);

	assert(zswap_swapz_bind_stored_entry(
		&stored_proof, &stored_entry, original_slot, 21, &locked_folio,
		host_original_page, PAGE_SIZE) == 0);
	assert(stored_proof.stored_entry == &stored_entry);
	assert(stored_proof.stored_pool == &host_pool);
	assert(stored_proof.stored_handle == 31);
	assert(stored_proof.stored_length == 120);
	assert(stored_proof.generation == 21);
	saved_pool = stored_proof.stored_pool;
	saved_length = stored_proof.stored_length;
	saved_handle = stored_proof.stored_handle;

	/* A reused zpool allocation cannot inherit an older stored proof. */
	stored_entry.handle = 32;
	assert(zswap_swapz_capture_owned_payload(
		&source_owner, &stored_entry, original_slot,
		&locked_folio, &stored_proof, 21) == -ESTALE);
	stored_entry.handle = 31;
	stored_entry.length = 119;
	assert(zswap_swapz_capture_owned_payload(
		&source_owner, &stored_entry, original_slot,
		&locked_folio, &stored_proof, 21) == -ESTALE);
	stored_entry.length = 120;
	stored_proof.stored_handle = 32;
	assert(zswap_swapz_capture_owned_payload(
		&source_owner, &stored_entry, original_slot,
		&locked_folio, &stored_proof, 21) == -ESTALE);
	stored_proof.stored_handle = saved_handle;
	stored_proof.stored_length = 119;
	assert(zswap_swapz_capture_owned_payload(
		&source_owner, &stored_entry, original_slot,
		&locked_folio, &stored_proof, 21) == -ESTALE);
	stored_proof.stored_length = saved_length;
	stored_proof.stored_pool = &other_pool;
	assert(zswap_swapz_capture_owned_payload(
		&source_owner, &stored_entry, original_slot,
		&locked_folio, &stored_proof, 21) == -ESTALE);
	stored_proof.stored_pool = saved_pool;
	tree.ptr = &newer_entry;
	assert(zswap_swapz_capture_owned_payload(
		&source_owner, &stored_entry, original_slot,
		&locked_folio, &stored_proof, 21) == -ENOENT);
	tree.ptr = &stored_entry;
	assert(zswap_swapz_capture_owned_payload(
		&source_owner, &stored_entry, original_slot,
		&locked_folio, &stored_proof, 22) == -ESTALE);

	/* An isolated fixture may borrow only the separately copied payload. */
	assert(zswap_swapz_capture_owned_payload(
		&source_owner, &stored_entry, original_slot,
		&locked_folio, &stored_proof, 21) == 0);
	assert(source_owner.owned_bytes != zpool_bytes);
	assert(zswap_swapz_carrier_snapshot_source_only(&carrier, &source_owner)
	       == -ESTALE); /* No snapshot before owner submit. */
	assert(zswap_swapz_owned_payload_submit(&source_owner));
	assert(zswap_swapz_carrier_snapshot_source_only(&carrier, &source_owner)
	       == 0);
	assert(carrier.source_only_untrusted);
	assert(carrier.stored_slot.val == original_slot.val);
	assert(carrier.store_generation == 21);
	assert(carrier.immutable_payload == source_owner.owned_bytes);
	assert(zswap_swapz_carrier_publish_disabled(
		&carrier, true, true, true, true, true) == -EOPNOTSUPP);
	carrier.source_only_untrusted = false; /* Fake authority remains rejected. */
	assert(zswap_swapz_carrier_publish_disabled(
		&carrier, true, true, true, true, true) == -EOPNOTSUPP);
	assert(zswap_swapz_carrier_publish_disabled(
		&carrier, true, false, true, true, true) == -EOPNOTSUPP);
	assert(zswap_swapz_carrier_publish_disabled(
		&carrier, true, true, false, true, true) == -EOPNOTSUPP);
	assert(zswap_swapz_carrier_publish_disabled(
		&carrier, true, true, true, false, true) == -EOPNOTSUPP);
	assert(zswap_swapz_carrier_publish_disabled(
		&carrier, true, true, true, true, false) == -EOPNOTSUPP);
	assert(zswap_swapz_owned_payload_finish(&source_owner, -EIO));
	assert(source_owner.completion_error == -EIO);
	assert(!zswap_swapz_owned_payload_finish(&source_owner, 0));
	assert(zswap_swapz_carrier_snapshot_source_only(&late_carrier, &source_owner)
	       == -ESTALE);
	assert(zswap_swapz_carrier_publish_disabled(
		&carrier, true, true, true, true, true) == -EOPNOTSUPP);
	assert(allocations == previous_allocations + 1);
	assert(freed == previous_releases + 1);
}
