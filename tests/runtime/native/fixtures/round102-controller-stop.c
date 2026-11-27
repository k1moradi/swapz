/* SPDX-License-Identifier: GPL-2.0-only */
/* Extracted actual target and built-in bridge. Serial lock/RCU boundary. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>

typedef uint64_t u64;
struct scope { u64 identity; };
struct swapz_dm {
	int queue_lock;
	struct scope original_scope;
	bool original_scope_capture_stopped;
	int original_scope_stop_error;
	bool accepting;
};
struct dm_target { struct swapz_dm *private; };
static struct swapz_dm *live;
static u64 mm_identity;
static bool mm_stopped;
static int mm_error;
static unsigned int calls, loss, checks;

#define CHECK(condition) do { ++checks; assert(condition); } while (0)
#define spin_lock_irqsave(lock, flags) do { CHECK(!*(lock)); *(lock) = 1; (flags) = 0; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { CHECK(*(lock)); *(lock) = 0; (void)(flags); } while (0)

static int swapz_mm_trial_scope_stop_capture(u64 identity)
{
	++calls;
	CHECK(!live->queue_lock);
	CHECK(live->original_scope_capture_stopped);
	CHECK(live->accepting);
	if (identity != mm_identity)
		return -ESTALE;
	if (mm_error)
		return mm_error;
	if (mm_stopped)
		return -EALREADY;
	mm_stopped = true;
	return 0;
}
static void swapz_scope_observe_invalid(void)
{
	++loss;
}
#include "actual-controller-stop.h"

int main(void)
{
	struct swapz_dm target = { .accepting = true };
	struct dm_target ti = { .private = &target };
	live = &target;
	mm_identity = 43;
	CHECK(swapz_trial_controller_stop_capture(0) == -EINVAL);
	swapz_presuspend(&ti);
	CHECK(calls == 0 && !loss && !target.original_scope_capture_stopped);
	CHECK(!swapz_scope_external_join_missing(&target));
	target.original_scope.identity = mm_identity;
	swapz_presuspend(&ti);
	CHECK(calls == 1 && mm_stopped && target.original_scope_capture_stopped);
	CHECK(target.original_scope.identity == mm_identity && target.accepting);
	CHECK(!target.original_scope_stop_error && !loss);
	CHECK(swapz_scope_external_join_missing(&target));
	swapz_scope_stop_capture(&target);
	CHECK(calls == 2 && !loss && !target.original_scope_stop_error);
	/* Wrong identity must remain quarantined even after a later refusal. */
	target = (struct swapz_dm){ .original_scope = {44}, .accepting = true };
	swapz_presuspend(&ti);
	CHECK(calls == 3 && loss == 1 && target.original_scope_stop_error == -ESTALE);
	CHECK(target.original_scope_capture_stopped && target.original_scope.identity == 44);
	CHECK(swapz_scope_external_join_missing(&target));
	target.original_scope.identity = mm_identity;
	mm_error = -EBUSY;
	swapz_scope_stop_capture(&target);
	CHECK(calls == 4 && loss == 2 && target.original_scope_stop_error == -ESTALE);
	mm_error = 0;
	swapz_scope_stop_capture(&target);
	CHECK(calls == 5 && loss == 2 && target.original_scope_stop_error == -ESTALE);
	CHECK(target.original_scope_capture_stopped && target.accepting);
	CHECK(swapz_scope_external_join_missing(&target));
	printf("R102_A3_STOP_HOST_ONLY checks=%u AUTH=0\n", checks);
	return 0;
}
