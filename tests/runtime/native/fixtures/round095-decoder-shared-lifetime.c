// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-decoder-shared.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(label, condition) do { ++checks; if (!(condition)) { \
	fprintf(stderr, "FIRST_ERROR round095-agent7 %s line=%d\n", label, __LINE__); \
	exit(77); } } while (0)

int round085_compress(swapz_u8, const swapz_u8 *, swapz_u32, swapz_u8 *,
	swapz_u32, swapz_u32 *);
void *__real_memcpy(void *, const void *, size_t);
void *__wrap_memcpy(void *, const void *, size_t);
int __real_pthread_mutex_lock(pthread_mutex_t *);
int __wrap_pthread_mutex_lock(pthread_mutex_t *);
int __real_swapz_zswap_import_decoder_owner_get(
	struct swapz_zswap_import_decoder_owner *, struct swapz_zswap_import_decoder_lease *);
int __wrap_swapz_zswap_import_decoder_owner_get(
	struct swapz_zswap_import_decoder_owner *, struct swapz_zswap_import_decoder_lease *);

enum pause_kind { NO_PAUSE, PRE_PROVIDER, BEFORE_COPY, AFTER_COPY };
static struct swapz_original_decoder_shared owner;
static struct swapz_original_decoder_shared_gate admission;
static pthread_mutex_t control = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static _Thread_local enum pause_kind reader_pause;
static int paused, resume_reader, fail_second_get;
static void *observed_output;
static unsigned int checks, reserve_calls;
static swapz_u64 issued_epoch, storage_epoch;
static swapz_u8 pages[2][SWAPZ_BLOCK_BYTES], compressed[2][4608];
static struct swapz_original_decode_record descriptors[2];
static swapz_u8 pin_live;

static void pause_here(void)
{
	if (__real_pthread_mutex_lock(&control))
		abort();
	paused = 1;
	if (pthread_cond_broadcast(&changed))
		abort();
	while (!resume_reader)
		if (pthread_cond_wait(&changed, &control))
			abort();
	if (pthread_mutex_unlock(&control))
		abort();
}

/* Deterministic pauses inside the actual source-linked provider path.
 * Only the selected reader thread and exact target lock/output are paused. */
int __wrap_pthread_mutex_lock(pthread_mutex_t *lock)
{
	if (reader_pause == PRE_PROVIDER && lock == &owner.lock)
		pause_here();
	return __real_pthread_mutex_lock(lock);
}

void *__wrap_memcpy(void *destination, const void *source, size_t size)
{
	void *result;

	if (reader_pause == BEFORE_COPY && destination == observed_output &&
	    size == SWAPZ_BLOCK_BYTES)
		pause_here();
	result = __real_memcpy(destination, source, size);
	if (reader_pause == AFTER_COPY && destination == observed_output &&
	    size == SWAPZ_BLOCK_BYTES)
		pause_here();
	return result;
}

int __wrap_swapz_zswap_import_decoder_owner_get(
	struct swapz_zswap_import_decoder_owner *provider,
	struct swapz_zswap_import_decoder_lease *lease)
{
	if (fail_second_get && provider == &owner.providers[1])
		return -EIO;
	return __real_swapz_zswap_import_decoder_owner_get(provider, lease);
}

/* Explicit external broker-session and pinned-storage boundary adapter.
 * A new owner_open in native composition must provide this identity; the
 * fixture never claims actual built-in broker or native reload evidence. */
static int reserve_epoch(void *context, swapz_u64 *epoch)
{
	(void)context;
	++reserve_calls;
	*epoch = issued_epoch;
	storage_epoch = issued_epoch;
	return 0;
}

static int snapshot(void *context, swapz_u64 pin,
	struct swapz_original_decoder_value_snapshot *out)
{
	unsigned int index;

	(void)context;
	if (!pin_live || !pin || pin > 2U)
		return -ESTALE;
	index = (unsigned int)(pin - 1U);
	*out = (struct swapz_original_decoder_value_snapshot){
		.handle = {storage_epoch, 1U, index, (swapz_u8)(index + 1U), 1U},
		.record = descriptors[index],
		.compressed_bytes = compressed[index],
		.compressed_capacity = sizeof(compressed[index]),
	};
	return 0;
}

static const struct swapz_original_decoder_shared_ops authority = {
	.reserve_epoch = reserve_epoch, .snapshot = snapshot,
};

static int open_session(swapz_u64 session, swapz_u64 supplied)
{
	issued_epoch = supplied;
	return swapz_original_decoder_shared_gate_open(&admission, &owner,
		&authority, 2U, session, session);
}

struct reader_job {
	struct swapz_original_decoder_value_handle value;
	swapz_u64 session;
	swapz_u64 pin;
	enum pause_kind pause;
	swapz_u8 output[SWAPZ_BLOCK_BYTES];
	int result;
};

static int read_page(struct reader_job *job)
{
	swapz_u8 scratch[SWAPZ_BLOCK_BYTES], verified[SWAPZ_BLOCK_BYTES];

	return swapz_original_decoder_shared_gate_read(&admission, job->session,
		job->pin, &job->value, 3568U, scratch, sizeof(scratch),
		verified, sizeof(verified), job->output, sizeof(job->output));
}

static void *reader(void *argument)
{
	struct reader_job *job = argument;

	reader_pause = job->pause;
	job->result = read_page(job);
	return NULL;
}

static struct reader_job make_job(swapz_u64 session, unsigned int profile,
	enum pause_kind pause)
{
	struct reader_job job = {
		.value = {session, 1U, profile, (swapz_u8)(profile + 1U), 1U},
		.session = session, .pin = profile + 1U, .pause = pause,
	};

	memset(job.output, 0xa5, sizeof(job.output));
	return job;
}

static void unchanged(const struct reader_job *job)
{
	unsigned int index;

	for (index = 0U; index < SWAPZ_BLOCK_BYTES; ++index)
		if (job->output[index] != 0xa5U)
			break;
	CHECK("failure_output_unchanged", index == SWAPZ_BLOCK_BYTES);
}

static void start_reader(struct reader_job *job, pthread_t *thread)
{
	paused = resume_reader = 0;
	observed_output = job->output;
	CHECK("reader_start", !pthread_create(thread, NULL, reader, job));
	CHECK("control_lock", !pthread_mutex_lock(&control));
	while (!paused)
		CHECK("control_wait", !pthread_cond_wait(&changed, &control));
	CHECK("control_unlock", !pthread_mutex_unlock(&control));
}

static void join_reader(pthread_t thread)
{
	CHECK("resume_lock", !pthread_mutex_lock(&control));
	resume_reader = 1;
	CHECK("resume_signal", !pthread_cond_broadcast(&changed));
	CHECK("resume_unlock", !pthread_mutex_unlock(&control));
	CHECK("reader_join", !pthread_join(thread, NULL));
}

static void copy_case(swapz_u64 session, unsigned int profile, enum pause_kind pause)
{
	struct reader_job job = make_job(session, profile, pause);
	pthread_t thread;

	CHECK("fresh_session", !open_session(session, session));
	pin_live = 1U;
	start_reader(&job, &thread);
	CHECK("copy_counted", atomic_load(&owner.active_reads) == 1U);
	CHECK("copy_entrant", atomic_load(&admission.entrants) == 1U);
	CHECK("copy_released_codec", owner.providers[profile].active_readers == 1U);
	if (pause == BEFORE_COPY)
		unchanged(&job);
	else
		CHECK("copy_done", !memcmp(job.output, pages[profile], sizeof(job.output)));
	CHECK("close_begin", !swapz_original_decoder_shared_gate_begin_close(&admission, session));
	CHECK("copy_busy", swapz_original_decoder_shared_finish_close(&owner, session) == -EBUSY);
	CHECK("gate_copy_busy", swapz_original_decoder_shared_gate_finish_close(&admission, session) == -EBUSY);
	join_reader(thread);
	CHECK("exact_page", !job.result && !memcmp(job.output, pages[profile], sizeof(job.output)));
	CHECK("counts_drained", !atomic_load(&owner.active_reads) && !atomic_load(&admission.entrants));
	pin_live = 0U;
	CHECK("close_finish", !swapz_original_decoder_shared_gate_finish_close(&admission, session));
	memset(&owner, 0, sizeof(owner));
}

int main(void)
{
	struct reader_job job, old;
	pthread_t thread;
	unsigned int profile, index, calls;

	CHECK("gate_init", !swapz_original_decoder_shared_gate_init(&admission));
	CHECK("mismatched_cap", swapz_original_decoder_shared_gate_open(&admission, &owner,
		&authority, 2U, 1U, 2U) == -EINVAL);
	CHECK("epoch_callback_mismatch", open_session(1U, 2U) == -ESTALE);
	calls = reserve_calls;
	CHECK("failed_epoch_burned", open_session(1U, 1U) == -ESTALE);
	CHECK("burn_before_callback", calls == reserve_calls);
	CHECK("epoch_exhaustion", open_session(~(swapz_u64)0, ~(swapz_u64)0) == -EINVAL);
	fail_second_get = 1;
	CHECK("init_partial_fail", open_session(2U, 2U) == -EIO);
	CHECK("init_unwind_first", !owner.retained[0].owner && !owner.providers[0].active_readers);
	CHECK("init_unwind_second", !owner.retained[1].owner && !owner.providers[1].active_readers);
	fail_second_get = 0;
	memset(&owner, 0, sizeof(owner));
	CHECK("failed_init_burned", open_session(2U, 2U) == -ESTALE);

	for (profile = 0U; profile < 2U; ++profile) {
		for (index = 0U; index < SWAPZ_BLOCK_BYTES; ++index)
			pages[profile][index] = (swapz_u8)(index % 127U == 0U ? 0x5aU + profile : 0U);
		descriptors[profile] = (struct swapz_original_decode_record){
			.decoded_length = SWAPZ_BLOCK_BYTES,
			.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
			.codec = (swapz_u8)(profile + 1U), .version = 1U,
		};
		CHECK("compress", !round085_compress((swapz_u8)(profile + 1U),
			pages[profile], SWAPZ_BLOCK_BYTES, compressed[profile],
			sizeof(compressed[profile]), &descriptors[profile].compressed_length));
		descriptors[profile].compressed_crc32c = swapz_crc32c_bytes(compressed[profile],
			descriptors[profile].compressed_length);
		CHECK("sha", !swapz_zswap_import_sha256(pages[profile],
			descriptors[profile].original_sha256));
	}
	copy_case(3U, 0U, BEFORE_COPY);
	copy_case(4U, 1U, AFTER_COPY);

	CHECK("prelock_open", !open_session(5U, 5U));
	pin_live = 1U;
	job = make_job(5U, 0U, PRE_PROVIDER);
	start_reader(&job, &thread);
	CHECK("prelock_counted", atomic_load(&admission.entrants) == 1U &&
		!atomic_load(&owner.active_reads));
	CHECK("prelock_begin", !swapz_original_decoder_shared_gate_begin_close(&admission, 5U));
	CHECK("prelock_busy", swapz_original_decoder_shared_gate_finish_close(&admission, 5U) == -EBUSY);
	join_reader(thread);
	CHECK("prelock_refused", job.result == -ESHUTDOWN);
	unchanged(&job);
	pin_live = 0U;
	CHECK("prelock_finish", !swapz_original_decoder_shared_gate_finish_close(&admission, 5U));
	memset(&owner, 0, sizeof(owner));
	CHECK("reused_session", open_session(5U, 5U) == -ESTALE);
	CHECK("reopen_new_session", !open_session(6U, 6U));
	pin_live = 1U;
	old = make_job(5U, 0U, NO_PAUSE);
	CHECK("stale_gate", read_page(&old) == -ESTALE);
	unchanged(&old);
	old.session = 6U;
	CHECK("stale_value", read_page(&old) == -ESTALE);
	unchanged(&old);
	job = make_job(6U, 0U, NO_PAUSE);
	CHECK("new_session_read", !read_page(&job) && !memcmp(job.output, pages[0], sizeof(job.output)));
	pin_live = 0U;
	CHECK("pin_refusal", read_page(&job) == -ESTALE);
	CHECK("last_begin", !swapz_original_decoder_shared_gate_begin_close(&admission, 6U));
	/* Inject an inconsistent second-owner count under exclusive quiescence.
	 * Quarantine intentionally retains static owner resources until exit. */
	++owner.providers[1].active_readers;
	CHECK("partial_close_refused", swapz_original_decoder_shared_gate_finish_close(&admission, 6U) == -EUCLEAN);
	CHECK("first_owner_intact", owner.retained[0].owner == &owner.providers[0] &&
		owner.providers[0].active_readers == 1U);
	CHECK("quarantine_no_reopen", open_session(7U, 7U) != 0);
	CHECK("gate_control_destroy", !pthread_mutex_destroy(&control));
	CHECK("gate_cond_destroy", !pthread_cond_destroy(&changed));
	printf("PASS ROUND095_AGENT7 checks=%u owner=%zu gate=%zu handle=%zu codecs=2 AUTH0\n",
		checks, sizeof(owner), sizeof(admission), sizeof(job.value));
	return 0;
}
