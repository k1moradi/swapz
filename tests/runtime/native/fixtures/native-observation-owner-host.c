/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual selected adapter + actual owner, host substitutes only. */
#include "native-observation-owner-host-model.h"
#include "native-observation-owner.h"
#include <openssl/sha.h>
#include <sched.h>

static pthread_rwlock_t model_rcu = PTHREAD_RWLOCK_INITIALIZER;
static atomic_uint readers, reservations;
static unsigned allocations, frees, hashes, joins, checks;
static bool fail_allocate;

#define CHECK(condition) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "owner check failed line %d: %s\n", __LINE__, #condition); \
		exit(1); \
	} \
} while (0)

bool model_try_cmpxchg(atomic_t *counter, int *previous, int next)
{
	(void)atomic_fetch_add(&reservations, 1U);
	return atomic_compare_exchange_strong_explicit(&counter->value, previous, next,
		memory_order_relaxed, memory_order_relaxed);
}
void model_read_lock(void)
{
	(void)atomic_fetch_add(&readers, 1U);
	if (pthread_rwlock_rdlock(&model_rcu))
		abort();
}
void model_read_unlock(void)
{
	if (pthread_rwlock_unlock(&model_rcu))
		abort();
}
void model_synchronize_rcu(void)
{
	if (pthread_rwlock_wrlock(&model_rcu) || pthread_rwlock_unlock(&model_rcu))
		abort();
}
void *model_kvcalloc(size_t count, size_t size, int flags)
{
	(void)flags;
	++allocations;
	return fail_allocate ? NULL : calloc(count, size);
}
void model_kvfree(void *pointer)
{
	++frees;
	free(pointer);
}
void sha256(const u8 *bytes, unsigned int length, u8 *digest)
{
	++hashes;
	if (!SHA256(bytes, length, digest))
		abort();
}

static struct swapz_trial_observation_scope scope(void)
{
	struct swapz_trial_observation_scope value = {
		.session = 11, .epoch = 12, .target_epoch = 13,
		.registration_epoch = 14, .first_logical = 7, .page_count = 2,
	};

	memcpy(value.source, SWAPZ_OBSERVATION_BUILD_SOURCE, 40);
	memset(value.kernel_sha256, '1', sizeof(value.kernel_sha256));
	memset(value.module_sha256, '2', sizeof(value.module_sha256));
	memset(value.workload_sha256, '3', sizeof(value.workload_sha256));
	memset(value.run_nonce, '4', sizeof(value.run_nonce));
	memset(value.target, '5', sizeof(value.target));
	return value;
}

static void disabled(void)
{
	unsigned before_readers = atomic_load(&readers);
	unsigned before_reservations = atomic_load(&reservations);
	unsigned before_hashes = hashes, before_allocations = allocations;
	/* No event construction/dereference, mutex, allocation or hash. */
	for (unsigned index = 0; index < 16U; ++index) {
		CHECK(!swapz_trial_observation_active());
		CHECK(!swapz_trial_observation_mint());
		CHECK(!swapz_trial_observation_append(NULL));
	}
	CHECK(atomic_load(&readers) == before_readers);
	CHECK(atomic_load(&reservations) == before_reservations);
	CHECK(hashes == before_hashes && allocations == before_allocations);
}

static bool join_empty(void *context)
{
	++joins;
	return *(const bool *)context;
}

static bool file_sink(void *context, const u8 *bytes, size_t length)
{
	return fwrite(bytes, 1, length, context) == length;
}
static bool reject_sink(void *context, const u8 *bytes, size_t length)
{
	(void)context;
	(void)bytes;
	(void)length;
	return false;
}

static void save(const char *path)
{
	FILE *file = fopen(path, "wb");

	CHECK(file != NULL);
	CHECK(!swapz_trial_observation_export(reject_sink, NULL));
	CHECK(swapz_trial_observation_export(file_sink, file));
	CHECK(!fclose(file));
}

struct terminal_debt {
	pthread_t thread;
	atomic_bool paused, proceed;
	u64 operation, original;
	bool completed;
};

static void *upper_and_cleanup(void *context)
{
	struct terminal_debt *debt = context;

	/* Deliberately paused before even the active hint. The external join
	 * owns this whole invocation, not just entered RCU critical sections.
	 */
	atomic_store_explicit(&debt->paused, true, memory_order_release);
	while (!atomic_load_explicit(&debt->proceed, memory_order_acquire))
		sched_yield();
	if (swapz_trial_observation_active()) {
		struct swapz_observation_record upper = {
			.event = SWAPZ_OBS_UPPER_ENDIO,
			.operation = debt->operation, .original = debt->original,
		};
		struct swapz_observation_record cleanup = {
			.event = SWAPZ_OBS_CLEANUP, .flags = 7,
		};

		debt->completed = swapz_trial_observation_append(&upper) &&
			swapz_trial_observation_append(&cleanup);
	}
	return NULL;
}

static bool join_terminal(void *context)
{
	struct terminal_debt *debt = context;

	++joins;
	/* Revoke this fixture's only producer source and join terminal debt.
	 * Owner's gate must still be active for the actual upper observation.
	 */
	atomic_store_explicit(&debt->proceed, true, memory_order_release);
	return !pthread_join(debt->thread, NULL) && debt->completed;
}

static void clean(const char *path)
{
	struct swapz_trial_observation_scope current = scope(), bad = current;
	struct terminal_debt debt = {0};
	u64 descriptor, clone;
	struct swapz_observation_record record;

	disabled();
	CHECK(!swapz_trial_observation_start(NULL, 8));
	CHECK(!swapz_trial_observation_start(&current, 0));
	CHECK(!swapz_trial_observation_start(&current, 8193));
	memcpy(bad.source, SWAPZ_OBSERVATION_MAPPING_SOURCE, 40);
	CHECK(!swapz_trial_observation_start(&bad, 8));
	bad = current;
	bad.run_nonce[0] = 'G';
	CHECK(!swapz_trial_observation_start(&bad, 8));
	bad = current;
	bad.first_logical = UINT32_MAX;
	CHECK(!swapz_trial_observation_start(&bad, 8));
	bad = current;
	memset(bad.target, '0', sizeof(bad.target));
	CHECK(!swapz_trial_observation_start(&bad, 8));
	CHECK(!allocations && !hashes);
	fail_allocate = true;
	CHECK(!swapz_trial_observation_start(&current, 8));
	CHECK(allocations == 1 && hashes == 1 && !frees);
	disabled();
	fail_allocate = false;
	CHECK(swapz_trial_observation_start(&current, 8));
	CHECK(!swapz_trial_observation_start(&current, 8));
	CHECK(swapz_trial_observation_active());
	CHECK(!swapz_trial_observation_release());
	CHECK(!swapz_trial_observation_export(reject_sink, NULL));
	CHECK(!swapz_trial_observation_stop(NULL, NULL));
	debt.operation = swapz_trial_observation_mint();
	debt.original = swapz_trial_observation_mint();
	descriptor = swapz_trial_observation_mint();
	clone = swapz_trial_observation_mint();
	CHECK(debt.operation == 1 && debt.original == 2 && descriptor == 3 && clone == 4);
	record = (struct swapz_observation_record){
		.event = SWAPZ_OBS_ACCEPT, .operation_kind = SWAPZ_OBS_DISCARD_BIO,
		.operation = debt.operation, .original = debt.original,
		.descriptor = descriptor, .clone = clone, .logical = 7,
	};
	CHECK(swapz_trial_observation_append(&record));
	record = (struct swapz_observation_record){
		.event = SWAPZ_OBS_DISPATCH, .operation = debt.operation, .flags = 1,
	};
	CHECK(swapz_trial_observation_append(&record));
	record = (struct swapz_observation_record){
		.event = SWAPZ_OBS_DISCARD, .operation = debt.operation, .new_generation = 1,
	};
	CHECK(swapz_trial_observation_append(&record));
	record = (struct swapz_observation_record){
		.event = SWAPZ_OBS_CLONE_ENDIO, .operation = debt.operation,
		.descriptor = descriptor, .clone = clone,
	};
	CHECK(swapz_trial_observation_append(&record));
	CHECK(!pthread_create(&debt.thread, NULL, upper_and_cleanup, &debt));
	while (!atomic_load_explicit(&debt.paused, memory_order_acquire))
		sched_yield();
	CHECK(swapz_trial_observation_stop(join_terminal, &debt));
	CHECK(debt.completed && joins == 1);
	disabled();
	save(path);
	CHECK(swapz_trial_observation_release());
	CHECK(frees == 1 && allocations == 2 && hashes == 2);
	CHECK(!swapz_trial_observation_release());
	CHECK(!swapz_trial_observation_start(&current, 8));
	CHECK(!swapz_trial_observation_stop(join_empty, NULL));
	disabled();
}

static void loss(const char *path, const char *mode)
{
	struct swapz_trial_observation_scope current = scope();
	struct swapz_observation_record record = {
		.event = SWAPZ_OBS_CLEANUP, .flags = 7,
	};
	bool joined = true, failed = false;

	CHECK(swapz_trial_observation_start(&current, 1));
	CHECK(swapz_trial_observation_mint() == 1);
	CHECK(swapz_trial_observation_append(&record));
	if (!strcmp(mode, "join")) {
		CHECK(!swapz_trial_observation_stop(join_empty, &failed));
		CHECK(joins == 1);
		CHECK(!swapz_trial_observation_export(reject_sink, NULL));
		CHECK(!swapz_trial_observation_release());
		CHECK(!frees);
		disabled();
	} else if (!strcmp(mode, "overflow")) {
		CHECK(!swapz_trial_observation_append(&record));
	} else {
		record.sequence = 1;
		CHECK(!swapz_trial_observation_append(&record));
	}
	CHECK(swapz_trial_observation_stop(join_empty, &joined));
	CHECK(joins == (!strcmp(mode, "join") ? 2U : 1U));
	save(path);
	CHECK(swapz_trial_observation_release());
	CHECK(allocations == 1 && frees == 1 && hashes == 1);
	disabled();
}

int main(int argc, char **argv)
{
	if (argc != 3)
		return 2;
	if (!strcmp(argv[1], "clean"))
		clean(argv[2]);
	else if (!strcmp(argv[1], "join") || !strcmp(argv[1], "overflow") ||
		 !strcmp(argv[1], "invalid"))
		loss(argv[2], argv[1]);
	else
		return 2;
	printf("mode=%s checks=%u allocations=%u frees=%u hashes=%u joins=%u host_substitutes=1 auth=0\n",
		argv[1], checks, allocations, frees, hashes, joins);
	return 0;
}
