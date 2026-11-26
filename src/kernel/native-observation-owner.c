/* SPDX-License-Identifier: GPL-2.0-only */
#include "native-observation-owner.h"

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
	if (trial_gate.used || !capacity || capacity > SWAPZ_OBSERVATION_MAX_RECORDS ||
	    !scope_digest(scope, digest))
		goto unlock;
	records = kvcalloc(capacity, sizeof(*records), GFP_KERNEL);
	if (!records)
		goto unlock;
	if (!swapz_observation_init(&trial_recorder, records, capacity, digest) ||
	    !swapz_observation_publish(&trial_gate, &trial_recorder)) {
		kvfree(records);
		trial_recorder.records = NULL;
		goto unlock;
	}
	result = true;
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

bool swapz_trial_observation_release(void)
{
	bool result = false;

	mutex_lock(&trial_control);
	if (trial_joined && trial_recorder.records && trial_recorder.drained) {
		kvfree(trial_recorder.records);
		trial_recorder.records = NULL;
		result = true;
	}
	mutex_unlock(&trial_control);
	return result;
}
