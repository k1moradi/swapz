/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual selected owner/adapter with frozen Linux primitive host shims.
 * This helper only starts/stops isolated host evidence; no native controller.
 */
#include "native-observation-owner-host-model.h"
#include "native-observation-owner.h"
#include <openssl/sha.h>

bool model_try_cmpxchg(atomic_t *counter, int *previous, int next)
{
	return atomic_compare_exchange_strong_explicit(&counter->value, previous, next,
		memory_order_relaxed, memory_order_relaxed);
}
/* Fixture serializes every invocation; no native concurrency claim. */
void model_read_lock(void) {}
void model_read_unlock(void) {}
void model_synchronize_rcu(void) {}
void *model_kvcalloc(size_t count, size_t size, int flags)
{
	(void)flags;
	return calloc(count, size);
}
void model_kvfree(void *pointer) { free(pointer); }
void sha256(const u8 *bytes, unsigned int length, u8 *digest)
{
	if (!SHA256(bytes, length, digest))
		abort();
}

bool r098_recorder_start(u64 session, u64 epoch, u64 target_epoch, u64 registration)
{
	struct swapz_trial_observation_scope scope = {
		.session = session, .epoch = epoch, .target_epoch = target_epoch,
		.registration_epoch = registration, .first_logical = 1U, .page_count = 1U,
	};

	memcpy(scope.source, SWAPZ_OBSERVATION_BUILD_SOURCE, 40);
	memset(scope.kernel_sha256, '1', sizeof(scope.kernel_sha256));
	memset(scope.module_sha256, '2', sizeof(scope.module_sha256));
	memset(scope.workload_sha256, '3', sizeof(scope.workload_sha256));
	memset(scope.run_nonce, '4', sizeof(scope.run_nonce));
	memset(scope.target, '5', sizeof(scope.target));
	return swapz_trial_observation_start(&scope, 32U);
}
static bool joined(void *context) { (void)context; return true; }
struct witness {
	unsigned records, loss;
	u64 operation, original, clone, descriptor, extent, lower;
	bool valid;
};
static u64 read_le(const u8 *bytes, unsigned length)
{
	u64 value = 0;
	for (unsigned index = 0; index < length; ++index)
		value |= (u64)bytes[index] << (8U * index);
	return value;
}
static bool sink(void *opaque, const u8 *bytes, size_t length)
{
	struct witness *w = opaque;
	if (length == SWAPZ_OBSERVATION_HEADER_BYTES)
		return true;
	if (length == SWAPZ_OBSERVATION_FOOTER_BYTES) {
		w->loss = (unsigned)read_le(bytes + 16, 4);
		return read_le(bytes + 8, 8) == w->records;
	}
	if (length != SWAPZ_OBSERVATION_RECORD_BYTES)
		return false;
	const u64 op = read_le(bytes + 8, 8);
	const u64 descriptor = read_le(bytes + 16, 8), clone = read_le(bytes + 24, 8);
	const u64 original = read_le(bytes + 32, 8), lower = read_le(bytes + 40, 8);
	const u64 extent = read_le(bytes + 48, 8);
	const unsigned event = (unsigned)read_le(bytes + 104, 4);
	++w->records;
	if (event == SWAPZ_OBS_CAPTURE)
		w->operation = op;
	if (event == SWAPZ_OBS_BIND)
		w->original = original;
	if (event == SWAPZ_OBS_ACCEPT) {
		w->descriptor = descriptor;
		w->clone = clone;
		w->valid &= original == w->original && descriptor && clone && descriptor != clone;
	}
	if (event == SWAPZ_OBS_RESERVE)
		w->extent = extent;
	if (event == SWAPZ_OBS_LOWER_SUBMIT) {
		w->lower = lower;
		w->valid &= extent == w->extent && lower != 0;
	}
	if (event == SWAPZ_OBS_LOWER_COMPLETE)
		w->valid &= lower == w->lower;
	if (event == SWAPZ_OBS_FLUSH || event == SWAPZ_OBS_PUBLISH)
		w->valid &= extent == w->extent;
	if (event == SWAPZ_OBS_CLAIM || event == SWAPZ_OBS_CANDIDATE_RELEASE || event == SWAPZ_OBS_CLONE_ENDIO)
		w->valid &= descriptor == w->descriptor;
	if (event == SWAPZ_OBS_CLONE_ENDIO)
		w->valid &= clone == w->clone;
	w->valid &= op == w->operation && op != 0;
	return true;
}
bool r098_recorder_finish(unsigned expected_count, unsigned expected_loss)
{
	struct witness w = {.valid = true};
	bool ok = swapz_trial_observation_stop(joined, NULL) &&
		swapz_trial_observation_export(sink, &w) && w.valid &&
		w.records == expected_count && w.loss == expected_loss;
	return swapz_trial_observation_release() && ok;
}
