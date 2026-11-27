/* SPDX-License-Identifier: GPL-2.0-only */
#include "native-observation-owner.h"
#ifdef SWAPZ_ROUND104_INTEGRATION_TEST
#include "native-observation-byte-bridge.h"
#endif

#ifdef MODULE
#error "trial observation owner must be built in"
#endif
#ifndef SWAPZ_OBSERVATION_BUILD_SOURCE
#error "stage exact build source as a quoted Git commit SHA"
#endif
#include <crypto/sha2.h>
#include <linux/build_bug.h>
#include <linux/export.h>
#include <linux/kernel.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/vmalloc.h>

#define OBS_LINUX_SOURCE "c339f4010dea8b0d754f84ace70cd1b089878ef8"
static const char build_source[] = SWAPZ_OBSERVATION_BUILD_SOURCE;
static_assert(sizeof(build_source) == 41);

/* Never reinitialize the gate: even a caller paused before RCU may access
 * its static address after stop/release. No module or target pointer here.
 */
static struct swapz_observation_gate trial_gate;
static struct swapz_observation_recorder trial_recorder;
static DEFINE_MUTEX(trial_control);
static bool trial_joined;

bool swapz_trial_observation_active(void)
{
	return rcu_access_pointer(trial_gate.active) != NULL;
}
EXPORT_SYMBOL_GPL(swapz_trial_observation_active);

u64 swapz_trial_observation_mint(void)
{
	return swapz_observation_mint(&trial_gate);
}
EXPORT_SYMBOL_GPL(swapz_trial_observation_mint);

bool swapz_trial_observation_append(const struct swapz_observation_record *record)
{
	return swapz_observation_append(&trial_gate, record);
}
EXPORT_SYMBOL_GPL(swapz_trial_observation_append);

u64 swapz_trial_observation_append_sequence(const struct swapz_observation_record *record)
{
	return swapz_observation_append_sequence(&trial_gate, record);
}
EXPORT_SYMBOL_GPL(swapz_trial_observation_append_sequence);

static bool hex_field(const char *field, size_t length)
{
	bool nonzero = false;

	for (size_t index = 0; index < length; ++index) {
		char character = field[index];

		if (!((character >= '0' && character <= '9') ||
		      (character >= 'a' && character <= 'f')))
			return false;
		nonzero |= character != '0';
	}
	return nonzero;
}

/* Hash canonical ASCII sorted-key compact JSON, same as the frozen v2
 * validator. Do not trust a caller-supplied scope digest. The v2 header's
 * mapping-source remains historical schema lineage, while the scope digest
 * binds exact current source and artifacts. No manifest bytes exported here.
 * Cold path only; no SHA, formatting or allocation in the wrappers.
 */
static bool scope_digest(const struct swapz_trial_observation_scope *scope,
			 u8 digest[32])
{
	char manifest[896];
	int length;

	if (!scope || !hex_field(build_source, 40) ||
	    !memcmp(build_source, SWAPZ_OBSERVATION_MAPPING_SOURCE, 40) ||
	    memcmp(scope->source, build_source, 40) ||
	    !hex_field(scope->kernel_sha256, 64) ||
	    !hex_field(scope->module_sha256, 64) ||
	    !hex_field(scope->workload_sha256, 64) ||
	    !hex_field(scope->run_nonce, 32) || !hex_field(scope->target, 32) ||
	    !scope->session || !scope->epoch || !scope->target_epoch ||
	    !scope->registration_epoch || !scope->first_logical ||
	    !scope->page_count || scope->page_count > 4096U ||
	    scope->page_count - 1U > (u32)~0U - scope->first_logical)
		return false;

	length = snprintf(manifest, sizeof(manifest),
		"{\"epoch\":%llu,\"first_logical\":%u,\"kernel_sha256\":\"%.64s\","
		"\"linux_source\":\"%s\",\"mapping_source\":\"%s\","
		"\"module_sha256\":\"%.64s\",\"page_count\":%u,\"profile\":\"M3568\","
		"\"registration_epoch\":%llu,\"run_nonce\":\"%.32s\",\"session\":%llu,"
		"\"source\":\"%.40s\",\"target\":\"%.32s\",\"target_epoch\":%llu,"
		"\"workload_sha256\":\"%.64s\"}",
		(unsigned long long)scope->epoch, scope->first_logical,
		scope->kernel_sha256, OBS_LINUX_SOURCE, SWAPZ_OBSERVATION_MAPPING_SOURCE,
		scope->module_sha256, scope->page_count,
		(unsigned long long)scope->registration_epoch, scope->run_nonce,
		(unsigned long long)scope->session, scope->source, scope->target,
		(unsigned long long)scope->target_epoch, scope->workload_sha256);
	if (length <= 0 || (size_t)length >= sizeof(manifest))
		return false;
	sha256((const u8 *)manifest, (unsigned int)length, digest);
	return true;
}

bool swapz_trial_observation_start(const struct swapz_trial_observation_scope *scope,
				    size_t capacity)
{
	struct swapz_observation_record *records;
	u8 digest[32];
	bool result = false;

	mutex_lock(&trial_control);
#ifdef SWAPZ_ROUND104_INTEGRATION_TEST
	if (!scope || !scope->page_count || scope->page_count > SWAPZ_BYTE_LOGICAL_PAGES)
		goto unlock;
#endif
	if (trial_gate.used || !capacity || capacity > SWAPZ_OBSERVATION_MAX_RECORDS ||
	    !scope_digest(scope, digest))
		goto unlock;
	records = kvcalloc(capacity, sizeof(*records), GFP_KERNEL);
	if (!records)
		goto unlock;
	if (!swapz_observation_init(&trial_recorder, records, capacity, digest))
		goto free_records;
#ifdef SWAPZ_ROUND104_INTEGRATION_TEST
	/* Both bounded allocations must exist before publishing the recorder.
	 * The collector gate stays inactive until exact validated scope bind.
	 */
	if (!swapz_byte_bridge_prepare(&trial_recorder, scope->first_logical, scope->page_count))
		goto free_records;
#endif
	if (!swapz_observation_publish(&trial_gate, &trial_recorder)) {
#ifdef SWAPZ_ROUND104_INTEGRATION_TEST
		swapz_byte_bridge_abort();
#endif
		goto free_records;
	}
	result = true;
	goto unlock;
free_records:
	kvfree(records);
	trial_recorder.records = NULL;
unlock:
	mutex_unlock(&trial_control);
	return result;
}

bool swapz_trial_observation_stop(swapz_trial_observation_join join, void *context)
{
	bool result = false;

	mutex_lock(&trial_control);
	if (!trial_recorder.records || !join)
		goto unlock;
	if (!trial_joined) {
		/* Join may record real terminal events; no callback is retained.
		 * If revoke/join fails, invalidate capture before the RCU drain,
		 * keep storage and require a successful retry before export/free.
		 */
		trial_joined = join(context);
		if (!trial_joined)
			atomic_or(SWAPZ_OBS_LOST_LATE, &trial_recorder.loss);
	}
#ifdef SWAPZ_ROUND104_INTEGRATION_TEST
	/* Actual external callback ran once above with both gates live. */
	swapz_byte_bridge_close(trial_joined);
#endif
	if (!swapz_observation_stop(&trial_gate) || !trial_joined)
		goto unlock;
	result = swapz_observation_seal(&trial_recorder);
unlock:
	mutex_unlock(&trial_control);
	return result;
}

bool swapz_trial_observation_export(swapz_observation_sink sink, void *context)
{
	bool result;

	mutex_lock(&trial_control);
	result = trial_joined && trial_recorder.records &&
		swapz_observation_export(&trial_recorder, sink, context);
	mutex_unlock(&trial_control);
	return result;
}

#ifdef SWAPZ_ROUND104_INTEGRATION_TEST
/* Private outer framing, independent of the unchanged v2 recorder wire.
 * Fixed prefix: magic[8], version, wire bytes, operation count, byte section
 * bytes, scope SHA256[32]. Per operation: 11 u64, 4 u32, then zero or one
 * 4096-byte page. No native structure is emitted. No allocation or 4K stack.
 */
#define PRIVATE_HEADER_BYTES 56U
#define PRIVATE_RECORD_BYTES 104U
struct private_export {
	swapz_observation_sink sink;
	void *context;
	u32 count, bytes;
};

static void private_u32(u8 **output, u32 value)
{
	for (unsigned int index = 0; index < 4; ++index) {
		*(*output)++ = (u8)value;
		value >>= 8;
	}
}

static void private_u64(u8 **output, u64 value)
{
	for (unsigned int index = 0; index < 8; ++index) {
		*(*output)++ = (u8)value;
		value >>= 8;
	}
}

static u32 private_page_kind(enum swapz_byte_kind kind)
{
	switch (kind) {
	case SWAPZ_BYTE_WRITE:
	case SWAPZ_BYTE_FALLBACK:
	case SWAPZ_BYTE_ORDINARY:
	case SWAPZ_BYTE_ERROR:
		return 1;
	case SWAPZ_BYTE_READ:
		return 2;
	case SWAPZ_BYTE_DISCARD:
		return 0;
	default:
		return 3;
	}
}

static bool private_measure(void *context, const struct swapz_byte_record *record)
{
	struct private_export *state = context;
	u32 page_kind = private_page_kind(record->kind);

	if (state->count >= SWAPZ_BYTE_OPERATIONS || page_kind > 2)
		return false;
	++state->count;
	state->bytes += PRIVATE_RECORD_BYTES + (page_kind ? SWAPZ_BYTE_PAGE : 0U);
	return true;
}

static bool private_record(void *context, const struct swapz_byte_record *record)
{
	struct private_export *state = context;
	u8 header[PRIVATE_RECORD_BYTES], *output = header;
	u32 page_kind = private_page_kind(record->kind);

	private_u64(&output, record->operation);
	private_u64(&output, record->original);
	private_u64(&output, record->clone);
	private_u64(&output, record->descriptor);
	private_u64(&output, record->pin);
	private_u64(&output, record->accept_sequence);
	private_u64(&output, record->pin_sequence);
	private_u64(&output, record->copy_sequence);
	private_u64(&output, record->release_sequence);
	private_u64(&output, record->clone_sequence);
	private_u64(&output, record->upper_sequence);
	private_u32(&output, record->logical);
	private_u32(&output, (u32)record->kind);
	private_u32(&output, record->user_status);
	private_u32(&output, page_kind);
	return (size_t)(output - header) == sizeof(header) &&
		state->sink(state->context, header, sizeof(header)) &&
		(!page_kind || state->sink(state->context,
			page_kind == 1 ? record->input_page : record->final_copy,
			SWAPZ_BYTE_PAGE));
}

bool swapz_trial_observation_export_private(swapz_observation_sink sink, void *context)
{
	struct private_export state = {.sink = sink, .context = context};
	u8 header[PRIVATE_HEADER_BYTES], *output = header;
	u32 count, wire_bytes;
	bool result = false;

	mutex_lock(&trial_control);
	if (!sink || !trial_joined || !trial_recorder.records || !trial_recorder.sealed ||
	    atomic_read(&trial_recorder.loss) ||
	    !swapz_byte_bridge_export(private_measure, &state) || !state.count)
		goto unlock;
	count = (u32)atomic_read(&trial_recorder.count);
	if (!count || count > SWAPZ_OBSERVATION_MAX_RECORDS ||
	    trial_recorder.records[count - 1U].event != SWAPZ_OBS_CLEANUP)
		goto unlock;
	wire_bytes = SWAPZ_OBSERVATION_HEADER_BYTES + count * SWAPZ_OBSERVATION_RECORD_BYTES +
		SWAPZ_OBSERVATION_FOOTER_BYTES;
	memcpy(output, "SWZPRV1", 8);
	output += 8;
	private_u32(&output, 1);
	private_u32(&output, wire_bytes);
	private_u32(&output, state.count);
	private_u32(&output, state.bytes);
	memcpy(output, trial_recorder.scope_sha256, 32);
	output += 32;
	result = (size_t)(output - header) == sizeof(header) &&
		sink(context, header, sizeof(header)) &&
		swapz_observation_export(&trial_recorder, sink, context) &&
		swapz_byte_bridge_export(private_record, &state) &&
		sink(context, (const u8 *)"SWZPEND", 8);
unlock:
	mutex_unlock(&trial_control);
	return result;
}

bool swapz_trial_observation_export_bytes(swapz_byte_record_sink sink, void *context)
{
	bool result;

	mutex_lock(&trial_control);
	result = trial_joined && trial_recorder.records &&
		swapz_byte_bridge_export(sink, context);
	mutex_unlock(&trial_control);
	return result;
}
#endif

#ifdef SWAPZ_ROUND104_INTEGRATION_TEST
static void private_scrub(void *pointer, size_t length)
{
#ifdef __KERNEL__
	memzero_explicit(pointer, length);
#else
	volatile u8 *bytes = pointer;

	while (length--)
		*bytes++ = 0;
#endif
}
#endif

bool swapz_trial_observation_release(void)
{
	bool result = false;

	mutex_lock(&trial_control);
	if (trial_joined && trial_recorder.records && trial_recorder.drained) {
#ifdef SWAPZ_ROUND104_INTEGRATION_TEST
		if (!swapz_byte_bridge_release())
			goto unlock;
		private_scrub(trial_recorder.records,
			      trial_recorder.capacity * sizeof(*trial_recorder.records));
		private_scrub(trial_recorder.scope_sha256, sizeof(trial_recorder.scope_sha256));
#endif
		kvfree(trial_recorder.records);
		trial_recorder.records = NULL;
		result = true;
	}
#ifdef SWAPZ_ROUND104_INTEGRATION_TEST
unlock:
#endif
	mutex_unlock(&trial_control);
	return result;
}
