/* Original block/bio.c helper is extracted verbatim; no clone simulator
 * can prove real BIO ownership, live source slot or target mapped authority.
 */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#define BIO_CLONED 2U
struct swapz_ci_owned_payload { uint32_t immutable; };
struct bio_iter {
	unsigned int bi_size;
	unsigned int bi_idx;
	unsigned int bi_offset;
};
struct bio {
	unsigned int bi_flags;
	unsigned int bi_vcnt;
	struct bio_iter bi_iter;
	struct swapz_ci_owned_payload *bi_swapz_ci_sideband;
	bool bi_swapz_ci_full_clone_owned;
};
/* ROUND043_EXACT_ORIGINAL_BIO_CLONE_C */
int main(void)
{
	struct swapz_ci_owned_payload owner = {.immutable = 1U};
	struct bio original = {
		.bi_iter = {.bi_size = 4096U},
		.bi_swapz_ci_sideband = &owner,
	};
	struct bio clone = original;

	assert(swapz_round043_bio_clone_owner_is_independent(&original));
	original.bi_swapz_ci_full_clone_owned = true;
	assert(!swapz_round043_bio_clone_owner_is_independent(&original));
	clone.bi_flags = 1U << BIO_CLONED;
	assert(!swapz_round043_bio_clone_owner_is_independent(&clone));
	clone.bi_swapz_ci_full_clone_owned = true;
	assert(swapz_round043_bio_clone_owner_is_independent(&clone));
	clone.bi_swapz_ci_sideband = NULL;
	assert(!swapz_round043_bio_clone_owner_is_independent(&clone));
	clone.bi_swapz_ci_sideband = &owner;
	clone.bi_vcnt = 1U;
	assert(!swapz_round043_bio_clone_owner_is_independent(&clone));
	clone.bi_vcnt = 0U;
	clone.bi_iter.bi_size = 2048U;
	assert(!swapz_round043_bio_clone_owner_is_independent(&clone));
	clone.bi_iter.bi_size = 4096U;
	clone.bi_iter.bi_idx = 1U;
	assert(!swapz_round043_bio_clone_owner_is_independent(&clone));
	clone.bi_iter.bi_idx = 0U;
	clone.bi_iter.bi_offset = 512U;
	assert(!swapz_round043_bio_clone_owner_is_independent(&clone));
	clone.bi_iter.bi_offset = 0U;
	assert(swapz_round043_bio_clone_owner_is_independent(&clone));
	assert(!swapz_round043_bio_clone_owner_is_independent(NULL));
	puts("ROUND031_REAL_ROUND043_ORIGINAL_BIO_CLONE_C_HOST_PASS");
	return 0;
}
