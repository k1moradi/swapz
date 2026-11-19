/*
 * Host compiles the EXACT original mm/zswap.c Round042 pure C helper verbatim.
 * No actual zswap STORED object, natural MM pressure, swapoff or DM target.
 * All fabricated source identity and owner references are SYNTHETIC only.
 */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint64_t u64;
typedef uint32_t u32;

/* ROUND042_EXACT_ORIGINAL_STORED_WRITEBACK_C */

static struct swapz_round042_stored_writeback_observation sample(void)
{
	struct swapz_round042_stored_writeback_observation observation = {
		.source_swap_entry = UINT64_C(0x100000025),
		.current_swap_entry = UINT64_C(0x100000025),
		.source_allocation_epoch = 17U,
		.current_allocation_epoch = 17U,
		.source_stored_identity = 29U,
		.current_stored_identity = 29U,
		.original_store_crc32c = UINT32_C(0xa19be32f),
		.copied_source_crc32c = UINT32_C(0xa19be32f),
		.compressed_length = 912U,
		.decoded_length = 4096U,
		.original_xarray_matches = true,
		.folio_locked = true,
		.folio_swapcache = true,
		.original_decompressed_to_folio = true,
		.copied_payload_independently_owned = true,
	};
	return observation;
}

int main(void)
{
	struct swapz_round042_stored_writeback_observation witness = sample();
	struct swapz_round042_stored_writeback_observation unchanged = witness;
#define REFUSE(status) assert(swapz_round042_stored_writeback_refuse(&witness) == (status))
	REFUSE(-EOPNOTSUPP);
	assert(memcmp(&witness, &unchanged, sizeof(witness)) == 0);
	witness.original_xarray_matches = false;
	REFUSE(-ESTALE);
	witness = sample();
	witness.current_swap_entry++;
	REFUSE(-ESTALE);
	witness = sample();
	witness.current_allocation_epoch++;
	REFUSE(-ESTALE);
	witness = sample();
	witness.current_stored_identity++;
	REFUSE(-ESTALE);
	witness = sample();
	witness.copied_source_crc32c++;
	REFUSE(-ESTALE);
	witness = sample();
	witness.original_store_crc32c = 0U;
	REFUSE(-ESTALE);
	witness = sample();
	witness.compressed_length = 3569U;
	REFUSE(-ERANGE);
	witness = sample();
	witness.decoded_length = 2048U;
	REFUSE(-ERANGE);
	witness = sample();
	witness.folio_locked = false;
	REFUSE(-ESTALE);
	witness = sample();
	witness.folio_swapcache = false;
	REFUSE(-ESTALE);
	witness = sample();
	witness.original_decompressed_to_folio = false;
	REFUSE(-ESTALE);
	witness = sample();
	witness.copied_payload_independently_owned = false;
	REFUSE(-EOPNOTSUPP);
	witness = sample();
	witness.original_entry_erased = true;
	REFUSE(-ESTALE);
	witness.original_entry_freed = true;
	REFUSE(-EOPNOTSUPP);
	witness.delayed_bio_completion = true;
	witness.original_folio_writeback_started = true;
	witness.original_swap_area_ref_held = true;
	witness.allocation_incarnation_ref_held = true;
	witness.current_dm_target_gc_ref_held = true;
	REFUSE(-EOPNOTSUPP);
	assert(swapz_round042_stored_writeback_refuse(NULL) == -EINVAL);
	puts("ROUND031_REAL_ROUND042_ORIGINAL_STORED_WRITEBACK_C_HOST_PASS");
	return 0;
}
