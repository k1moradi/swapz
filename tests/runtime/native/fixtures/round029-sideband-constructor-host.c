
/* Round029 host checks call the EXACT extracted original block/bio.c helper. */
static void round029_constructor_host_checks(void)
{
	u8 compressed[32] = { 1, 2, 3 }, digest[32] = { 0x5a };
	u8 missing_digest[32] = {};
	const u32 crc = ~crc32c(~0U, compressed, sizeof(compressed));
	struct swapz_ci_owned_payload *owner;
	struct bio parent = { 0 }, clone = { 0 };
	const unsigned int freed_before = freed_allocations;
	owner = swapz_ci_owned_create(compressed, sizeof(compressed),
				     sizeof(compressed), digest, 17, 29,
				     1, 1, crc, GFP_KERNEL);
	assert(owner && swapz_ci_owned_valid(owner));
	assert(owner->compressed_bytes != compressed);
	assert(owner->compressed_bytes[0] == 1);
	assert(owner->compressed_length == 32 && owner->owned_capacity == 32);
	assert(owner->compressed_crc32c == crc);
	compressed[0] = 99;
	digest[0] = 0;
	assert(owner->compressed_bytes[0] == 1);
	assert(owner->original_sha256[0] == 0x5a);
	assert(swapz_ci_owned_valid(owner));
	parent.bi_swapz_ci_sideband = owner;
	assert(fixture_clone(&parent, &clone) == 0);
	assert(refcount_read(&owner->references) == 2);
	owner->compressed_crc32c ^= 1U;
	struct bio rejected = { 0 };
	assert(fixture_clone(&parent, &rejected) == -EOPNOTSUPP);
	assert(rejected.bi_swapz_ci_sideband == NULL);
	assert(refcount_read(&owner->references) == 2);
	owner->compressed_crc32c ^= 1U;
	swapz_ci_bio_detach(&parent);
	assert(refcount_read(&owner->references) == 1);
	swapz_ci_bio_detach(&clone);
	swapz_ci_bio_detach(&clone);
	assert(freed_allocations == freed_before + 1);
	/* Failure cases may never return a borrowed or partially initialized owner. */
	/* Restore the borrowed SHA only for the independent invalid-input probes. */
	digest[0] = 0x5a;
	const u32 new_crc = ~crc32c(~0U, compressed, sizeof(compressed));
	assert(!swapz_ci_owned_create(compressed, 32, 0, digest, 17, 29, 1, 1, new_crc, GFP_KERNEL));
	assert(!swapz_ci_owned_create(compressed, 32, 3569, digest, 17, 29, 1, 1, new_crc, GFP_KERNEL));
	assert(!swapz_ci_owned_create(compressed, 32, (size_t)-1, digest, 17, 29, 1, 1, new_crc, GFP_KERNEL));
	assert(!swapz_ci_owned_create(compressed, 1, 32, digest, 17, 29, 1, 1, new_crc, GFP_KERNEL));
	assert(!swapz_ci_owned_create(compressed, 3569, 32, digest, 17, 29, 1, 1, new_crc, GFP_KERNEL));
	assert(!swapz_ci_owned_create(compressed, 32, 32, NULL, 17, 29, 1, 1, new_crc, GFP_KERNEL));
	assert(!swapz_ci_owned_create(compressed, 32, 32, missing_digest, 17, 29, 1, 1, new_crc, GFP_KERNEL));
	assert(!swapz_ci_owned_create(compressed, 32, 32, compressed, 17, 29, 1, 1, new_crc, GFP_KERNEL));
	assert(!swapz_ci_owned_create(compressed, 32, 32, digest, 0, 29, 1, 1, new_crc, GFP_KERNEL));
	assert(!swapz_ci_owned_create(compressed, 32, 32, digest, 17, 0, 1, 1, new_crc, GFP_KERNEL));
	assert(!swapz_ci_owned_create(compressed, 32, 32, digest, 17, 29, 2, 1, new_crc, GFP_KERNEL));
	assert(!swapz_ci_owned_create(compressed, 32, 32, digest, 17, 29, 1, 2, new_crc, GFP_KERNEL));
	assert(!swapz_ci_owned_create(compressed, 32, 32, digest, 17, 29, 1, 1, new_crc ^ 1U, GFP_KERNEL));
	fail_next_kzalloc = 1;
	assert(!swapz_ci_owned_create(compressed, 32, 32, digest, 17, 29, 1, 1, new_crc, GFP_KERNEL));
	assert(fail_next_kzalloc == 0);
	assert(freed_allocations == freed_before + 2); /* CRC refusal allocates, then frees. */
	assert(swapz_ci_live_compressed_admit(&parent, 17) == -EOPNOTSUPP);
}
