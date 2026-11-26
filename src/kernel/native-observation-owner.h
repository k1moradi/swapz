/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_NATIVE_OBSERVATION_OWNER_H
#define SWAPZ_NATIVE_OBSERVATION_OWNER_H

/* Explicit test-only staging; never an admission or activation interface. */
#ifndef SWAPZ_TRIAL_OBSERVATION
#error "trial observation requires explicit development staging"
#endif
#include "native-observation-adapter.h"

/* Only these three guarded GPL symbols cross the built-in/DM boundary.
 * Active is a hint, not a lifetime pin or authorization. Build the record
 * only after active; mint/append recheck the permanent one-shot RCU gate.
 * A zero token or false append loses evidence, never changes I/O success.
 */
bool swapz_trial_observation_active(void);
u64 swapz_trial_observation_mint(void);
bool swapz_trial_observation_append(const struct swapz_observation_record *record);

/* Fixed ASCII hex, no NUL required, no raw device/host identity. All
 * fields are independent, caller-supplied scope assertions. The build's
 * exact Git source is separately pinned at compile time. M3568 only.
 */
struct swapz_trial_observation_scope {
	char source[40];
	char kernel_sha256[64];
	char module_sha256[64];
	char workload_sha256[64];
	char run_nonce[32];
	char target[32];
	u64 session;
	u64 epoch;
	u64 target_epoch;
	u64 registration_epoch;
	u32 first_logical;
	u32 page_count;
};

/* Built-in controller only, no exports or callers installed in this round.
 * Cold process context. The mutex serializes control, including callbacks;
 * callbacks must never reenter control, and no producer-required lock may
 * be held. Start is one-shot per boot (no reopening after publication).
 * Owner allocates and releases its bounded virtually contiguous array.
 * Stop's synchronous callback must revoke ALL external event admissions
 * and join all callers, including paused pre-active/pre-RCU entrants and
 * deferred debts, while recorder remains available for terminal events.
 * Caller supplies a currently live callback; owner never retains it.
 * Failed join disables/drains RCU, sets sticky incomplete loss, retains
 * storage, and refuses export/free until a later genuine join succeeds.
 * Gate is static for the entire built-in lifetime, even after release.
 * Success means sealed observation transport, NOT native authorization.
 */
typedef bool (*swapz_trial_observation_join)(void *context);
bool swapz_trial_observation_start(const struct swapz_trial_observation_scope *scope,
				    size_t capacity);
bool swapz_trial_observation_stop(swapz_trial_observation_join join, void *context);
bool swapz_trial_observation_export(swapz_observation_sink sink, void *context);
bool swapz_trial_observation_release(void);

#endif
