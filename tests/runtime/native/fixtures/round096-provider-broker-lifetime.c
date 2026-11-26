/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual frozen gate and built-in broker owner; the external route join,
 * one-shot capability consumption and storage pin are explicit host adapters.
 * This is not a native reload, storage integration or authorization test.
 */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "round094-owner-shim.h"
#include "zswap-original-ticket.h"
#include "zswap-original-decoder-shared.h"

static unsigned int checks, allocations;
static struct swapz_original_decoder_shared *fail_owner;
static swapz_u8 pages[2][SWAPZ_BLOCK_BYTES], compressed[2][4608];
static struct swapz_original_decode_record records[2];

#define CHECK(label, condition) do { ++checks; if (!(condition)) { \
	fprintf(stderr, "R096_A7_FIRST_ERROR %s line=%d\n", label, __LINE__); \
	exit(77); } } while (0)

int round085_compress(swapz_u8, const swapz_u8 *, swapz_u32, swapz_u8 *,
	swapz_u32, swapz_u32 *);
int __real_swapz_zswap_import_decoder_owner_get(
	struct swapz_zswap_import_decoder_owner *, struct swapz_zswap_import_decoder_lease *);
int __wrap_swapz_zswap_import_decoder_owner_get(
	struct swapz_zswap_import_decoder_owner *provider,
	struct swapz_zswap_import_decoder_lease *lease)
{
	if (fail_owner && provider == &fail_owner->providers[1])
		return -EIO;
	return __real_swapz_zswap_import_decoder_owner_get(provider, lease);
}

static void must(int error)
{
	if (error)
		abort();
}

void r094_owner_mutex_lock(pthread_mutex_t *lock) { must(pthread_mutex_lock(lock)); }
void r094_owner_mutex_unlock(pthread_mutex_t *lock) { must(pthread_mutex_unlock(lock)); }
void *r094_owner_allocate(size_t bytes)
{
	void *pointer = aligned_alloc(64U, (bytes + 63U) & ~(size_t)63U);
	if (pointer)
		++allocations;
	return pointer;
}
void r094_owner_free(void *pointer)
{
	if (pointer) {
		if (!allocations)
			abort();
		--allocations;
		free(pointer);
	}
}
void r094_owner_after_enter(void) {}

struct authority {
	struct swapz_ticket_cap retained;
	bool consumed;
	unsigned int reservations;
	atomic_uint external;
	atomic_bool pin_live;
};

/* This consumption flag is HOST boundary state, not a production provider
 * epoch counter. Only the real built-in owner issues the identity. The cap
 * stays retained until every external borrower and decoder has drained.
 */
static int reserve_epoch(void *context, swapz_u64 *epoch)
{
	struct authority *authority = context;
	++authority->reservations;
	if (authority->consumed || !authority->retained.broker ||
	    !authority->retained.session ||
	    authority->retained.session != authority->retained.epoch)
		return -ESTALE;
	authority->consumed = true;
	*epoch = authority->retained.epoch;
	return 0;
}

static int snapshot(void *context, swapz_u64 pin,
	struct swapz_original_decoder_value_snapshot *output)
{
	struct authority *authority = context;
	unsigned int profile;

	if (!atomic_load(&authority->pin_live) || !pin || pin > 2U)
		return -ESTALE;
	profile = (unsigned int)(pin - 1U);
	*output = (struct swapz_original_decoder_value_snapshot) {
		.handle = {authority->retained.epoch, 1U, profile,
			(swapz_u8)(profile + 1U), 1U},
		.record = records[profile],
		.compressed_bytes = compressed[profile],
		.compressed_capacity = sizeof(compressed[profile]),
	};
	return 0;
}

static void open_cap(struct authority *authority)
{
	atomic_init(&authority->external, 0U);
	atomic_init(&authority->pin_live, false);
	CHECK("broker_open", !swapz_mm_broker_owner_open(2U, 3568U, 7136U,
		&authority->retained));
	CHECK("retained_exact_cap", authority->retained.broker &&
		authority->retained.session &&
		authority->retained.session == authority->retained.epoch && allocations == 3U);
}

static int bind(struct authority *authority,
	struct swapz_original_decoder_shared_gate *gate,
	struct swapz_original_decoder_shared *owner)
{
	const struct swapz_original_decoder_shared_ops ops = {
		.context = authority, .reserve_epoch = reserve_epoch, .snapshot = snapshot,
	};
	return swapz_original_decoder_shared_gate_open(gate, owner, &ops, 2U,
		authority->retained.session, authority->retained.epoch);
}

static void close_cap(struct authority *authority)
{
	const swapz_u64 session = authority->retained.session;
	const swapz_u64 epoch = authority->retained.epoch;
	CHECK("external_joined", !atomic_load(&authority->external) &&
		!atomic_load(&authority->pin_live));
	CHECK("broker_begin", !swapz_mm_broker_owner_begin_close(session, epoch));
	CHECK("cap_only_busy", swapz_mm_broker_owner_finish_close(session, epoch) == -EBUSY &&
		allocations == 3U);
	CHECK("cap_drop", !swapz_ticket_broker_put(&authority->retained));
	CHECK("broker_destroy", !swapz_mm_broker_owner_finish_close(session, epoch) &&
		!allocations);
}

static swapz_u64 failed_bind(void)
{
	struct authority authority = {0};
	struct swapz_original_decoder_shared_gate first = {0}, recreated = {0};
	struct swapz_original_decoder_shared owner = {0}, second = {0};
	swapz_u64 session;

	open_cap(&authority);
	session = authority.retained.session;
	CHECK("first_gate_init", !swapz_original_decoder_shared_gate_init(&first));
	fail_owner = &owner;
	CHECK("failed_second_codec_get", bind(&authority, &first, &owner) == -EIO);
	fail_owner = NULL;
	CHECK("failed_identity_consumed", authority.consumed && authority.reservations == 1U);
	CHECK("failed_provider_unwound", !owner.retained[0].owner && !owner.retained[1].owner);
	CHECK("recreated_gate_init", !swapz_original_decoder_shared_gate_init(&recreated));
	CHECK("fresh_gate_does_not_reissue_cap",
		bind(&authority, &recreated, &second) == -ESTALE);
	CHECK("external_consumption_checked", authority.reservations == 2U);
	must(pthread_mutex_destroy(&first.lock));
	must(pthread_mutex_destroy(&recreated.lock));
	close_cap(&authority);
	return session;
}

enum pause_kind { BEFORE_GATE, AFTER_RETURN };
struct read_job {
	struct authority *authority;
	struct swapz_original_decoder_shared_gate *gate;
	struct swapz_original_decoder_value_handle value;
	swapz_u64 session, pin;
	enum pause_kind pause;
	pthread_barrier_t entered, resume;
	swapz_u8 output[SWAPZ_BLOCK_BYTES];
	int result;
};

static void meet(pthread_barrier_t *barrier)
{
	int error = pthread_barrier_wait(barrier);
	if (error != PTHREAD_BARRIER_SERIAL_THREAD)
		must(error);
}

static bool unchanged(const struct read_job *job)
{
	for (unsigned int index = 0U; index < sizeof(job->output); ++index)
		if (job->output[index] != 0xa5U)
			return false;
	return true;
}

static int decode(struct read_job *job)
{
	swapz_u8 scratch[SWAPZ_BLOCK_BYTES], verified[SWAPZ_BLOCK_BYTES];

	return swapz_original_decoder_shared_gate_read(job->gate, job->session,
		job->pin, &job->value, 3568U, scratch, sizeof(scratch),
		verified, sizeof(verified), job->output, sizeof(job->output));
}

static void *read_thread(void *context)
{
	struct read_job *job = context;
	/* Models a caller that has already borrowed the published route and
	 * retained the exact pin. No new route borrower starts after revoke.
	 */
	atomic_fetch_add(&job->authority->external, 1U);
	atomic_store(&job->authority->pin_live, true);
	if (job->pause == BEFORE_GATE) {
		meet(&job->entered);
		meet(&job->resume);
	}
	job->result = decode(job);
	if (job->pause == AFTER_RETURN) {
		meet(&job->entered);
		meet(&job->resume);
	}
	atomic_store(&job->authority->pin_live, false);
	atomic_fetch_sub(&job->authority->external, 1U);
	return NULL;
}

/* Modeled external revoke/join boundary; the actual gate cannot observe a
 * caller before its lock or after return. Do not mistake this check for an
 * implementation of Linux RCU or the actual storage adapter's pin drainage.
 */
static int finish_joined(struct authority *authority,
	struct swapz_original_decoder_shared_gate *gate, swapz_u64 session)
{
	if (atomic_load(&authority->external) || atomic_load(&authority->pin_live))
		return -EBUSY;
	return swapz_original_decoder_shared_gate_finish_close(gate, session);
}

static swapz_u64 read_case(swapz_u64 previous, unsigned int profile,
	enum pause_kind pause)
{
	struct authority authority = {0};
	struct swapz_original_decoder_shared_gate gate = {0};
	struct swapz_original_decoder_shared owner = {0};
	struct read_job job = {.authority = &authority, .gate = &gate, .pause = pause,
		.pin = profile + 1U};
	swapz_u64 session;
	pthread_t thread;

	open_cap(&authority);
	session = authority.retained.session;
	CHECK("broker_epoch_nonreuse_across_recreated_gate", session > previous);
	CHECK("fresh_gate_init", !swapz_original_decoder_shared_gate_init(&gate));
	CHECK("fresh_exact_cap_bind", !bind(&authority, &gate, &owner));
	CHECK("cap_consumed_once", authority.consumed && authority.reservations == 1U);
	job.value = (struct swapz_original_decoder_value_handle) {
		previous, 1U, profile, (swapz_u8)(profile + 1U), 1U};
	job.session = previous;
	memset(job.output, 0xa5, sizeof(job.output));
	atomic_store(&authority.external, 1U);
	atomic_store(&authority.pin_live, true);
	CHECK("stale_session_after_gate_recreation", decode(&job) == -ESTALE);
	job.session = session;
	CHECK("stale_value_after_gate_recreation", decode(&job) == -ESTALE);
	CHECK("stale_output_unchanged", unchanged(&job));
	job.value.lifecycle_epoch = session;
	CHECK("real_codec_exact_page", !decode(&job) &&
		!memcmp(job.output, pages[profile], sizeof(job.output)));
	atomic_store(&authority.pin_live, false);
	atomic_store(&authority.external, 0U);

	memset(job.output, 0xa5, sizeof(job.output));
	must(pthread_barrier_init(&job.entered, NULL, 2U));
	must(pthread_barrier_init(&job.resume, NULL, 2U));
	must(pthread_create(&thread, NULL, read_thread, &job));
	meet(&job.entered);
	CHECK("external_debt_outside_gate", atomic_load(&authority.external) == 1U &&
		atomic_load(&authority.pin_live) && !atomic_load(&gate.entrants) &&
		!atomic_load(&owner.active_reads));
	if (pause == AFTER_RETURN)
		CHECK("returned_exact_page", !job.result &&
			!memcmp(job.output, pages[profile], sizeof(job.output)));
	/* Route publication is revoked here; fixture never starts another
	 * borrower. The gate fences admission; external join still required. */
	CHECK("gate_begin", !swapz_original_decoder_shared_gate_begin_close(&gate, session));
	CHECK("external_join_required", finish_joined(&authority, &gate, session) == -EBUSY);
	CHECK("broker_begin_with_cap",
		!swapz_mm_broker_owner_begin_close(session, authority.retained.epoch));
	CHECK("broker_busy_while_external_pin_retained",
		swapz_mm_broker_owner_finish_close(session, authority.retained.epoch) == -EBUSY);
	meet(&job.resume);
	must(pthread_join(thread, NULL));
	if (pause == BEFORE_GATE) {
		CHECK("pre_gate_refused_after_close", job.result == -ESTALE);
		CHECK("closed_output_unchanged", unchanged(&job));
	}
	CHECK("joined_finish", !finish_joined(&authority, &gate, session));
	must(pthread_barrier_destroy(&job.entered));
	must(pthread_barrier_destroy(&job.resume));
	must(pthread_mutex_destroy(&gate.lock));
	close_cap(&authority);
	return session;
}

int main(void)
{
	swapz_u64 session = failed_bind();

	for (unsigned int profile = 0U; profile < 2U; ++profile) {
		for (unsigned int index = 0U; index < SWAPZ_BLOCK_BYTES; ++index)
			pages[profile][index] = (swapz_u8)(index % 131U == 0U ? 0x69U + profile : 0U);
		records[profile] = (struct swapz_original_decode_record) {
			.decoded_length = SWAPZ_BLOCK_BYTES,
			.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
			.codec = (swapz_u8)(profile + 1U), .version = 1U,
		};
		CHECK("compress", !round085_compress((swapz_u8)(profile + 1U),
			pages[profile], SWAPZ_BLOCK_BYTES, compressed[profile],
			sizeof(compressed[profile]), &records[profile].compressed_length));
		records[profile].compressed_crc32c = swapz_crc32c_bytes(compressed[profile],
			records[profile].compressed_length);
		CHECK("sha", !swapz_zswap_import_sha256(pages[profile], records[profile].original_sha256));
	}
	session = read_case(session, 0U, BEFORE_GATE);
	(void)read_case(session, 1U, AFTER_RETURN);
	printf("PASS R096_A7 checks=%u broker_sessions=3 codecs=2 external_pauses=2 AUTH0\n", checks);
	return 0;
}
