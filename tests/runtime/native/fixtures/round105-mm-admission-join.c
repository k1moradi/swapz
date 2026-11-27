/* SPDX-License-Identifier: GPL-2.0-only */
/* Exact staged terminal inc and debt header; kernel locks, RCU and BIO
 * mechanics are host substitutes. No native execution or authorization. */
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

typedef uint64_t u64;
typedef uint32_t u32;
typedef uint64_t sector_t;
#define MAX_SWAPFILES 32
#define SWAPZ_TERMINAL_HOST_TEST 1
#define SWAPZ_ROUND104_INTEGRATION_TEST 1
#define SWAPZ_ROUND103_EXTERNAL_JOIN_TEST 1
#define EXPORT_SYMBOL_GPL(symbol)
#define READ_ONCE(value) (value)
#define DEFINE_SPINLOCK(name) int name
static unsigned checks, locks, readers, mutexes, losses, records, callbacks;
#define CHECK(condition) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "R105_A11_FIRST_ERROR line=%d %s\n", __LINE__, #condition); \
		exit(77); \
	} \
} while (0)
#define spin_lock_irqsave(lock, flags) do { CHECK(!*(lock)); (flags) = 0; *(lock) = 1; ++locks; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); CHECK(*(lock) && locks); *(lock) = 0; --locks; } while (0)
#define rcu_access_pointer(pointer) (pointer)
#define rcu_dereference(pointer) (pointer)
#define rcu_assign_pointer(pointer, value) ((pointer) = (value))
static void rcu_read_lock(void) { ++readers; }
static void rcu_read_unlock(void) { CHECK(readers); --readers; }
static void mutex_lock(int *lock) { CHECK(!*lock && !locks); *lock = 1; ++mutexes; }
static void mutex_unlock(int *lock) { CHECK(*lock && mutexes); *lock = 0; --mutexes; }
static void synchronize_rcu(void) { CHECK(!locks && !mutexes && !readers); }
static u64 atomic64_read(const u64 *value) { return *value; }
static void atomic64_set(u64 *value, u64 next) { *value = next; }
static u64 swapz_mm_next(u64 *value) { return ++*value; }
static int atomic_read_acquire(const int *value) { return *value; }
struct file { unsigned refs; };
static unsigned file_puts;
static void fput(struct file *file) { CHECK(!locks && !mutexes && file->refs); --file->refs; ++file_puts; }
struct block_device { unsigned identity; };
struct swapz_mm_trial_scope {
	u64 identity, session, table_epoch, target_epoch, area_epoch;
	struct block_device *bdev;
	void *broker;
	u32 swap_type;
	sector_t first_sector, sector_count;
};
struct bio {
	struct block_device *bi_bdev;
	void (*bi_end_io)(struct bio *);
	unsigned flags, bi_status;
	void *bi_private;
};
enum { BIO_CHAIN = 1U, BIO_CLONED = 2U, BIO_REMAPPED = 4U };
static bool bio_flagged(const struct bio *bio, unsigned flag) { return !!(bio->flags & flag); }
static bool swapz_bio_is_chain_child(const struct bio *bio) { (void)bio; return false; }
#define blk_status_to_errno(status) (-(int)(status))
#define SWAPZ_OBS_UPPER_ENDIO 19U
struct swapz_observation_record { u32 event, status; u64 operation, original; };
static struct swapz_observation_record last;
static void swapz_mm_observation_emit(const struct swapz_observation_record *record)
{
	CHECK(!locks && record->event == SWAPZ_OBS_UPPER_ENDIO);
	last = *record;
	++records;
}
static void swapz_trial_byte_invalidate(void) { CHECK(!locks); ++losses; }
static int swapz_mm_busy, swapz_mm_scope_lock;
static bool swapz_mm_scope_transition, swapz_mm_scope_capture_stopped;
static u64 swapz_mm_area_epochs[MAX_SWAPFILES], swapz_mm_area_sequence;
static struct swapz_mm_trial_scope swapz_mm_scope_storage;
static const struct swapz_mm_trial_scope *swapz_mm_scope, *swapz_mm_capture_scope;
static struct file *swapz_mm_scope_file;
static unsigned swapz_mm_scope_cap = 1;
static bool fail_put;
static int swapz_ticket_broker_put(unsigned *cap) { CHECK(*cap == 1); if (fail_put) return -EIO; --*cap; return 0; }
#include "actual-snapshot.h"
u64 swapz_mm_trial_area_epoch(u32 type);
#include "swapz-trial-terminal.inc"
#include "actual-scope-control.h"

static struct block_device mapper = {1};
static struct file mapper_file = {1}, area_file = {1};
static unsigned callback_debt;
static int join(void) { return swapz_mm_trial_scope_join_external(17, 11, 12, 13); }
static int detach(void) { return swapz_mm_trial_scope_detach_files(17, 11, 12, 13); }
static int snapshot(struct swapz_mm_trial_terminal_snapshot *out) { return swapz_mm_trial_scope_terminal_snapshot(17, 11, 12, 13, out); }
static void original_endio(struct bio *bio)
{
	CHECK(!locks && !mutexes && bio->bi_end_io == original_endio);
	CHECK(bio->bi_private == &callbacks);
	/* Detach before the real callback; retain its ticket through return. */
	CHECK(!swapz_trial_debt_find(&swapz_mm_terminal_debt, bio, SWAPZ_TRIAL_DM));
	CHECK(swapz_mm_terminal_debt.count == callback_debt);
	CHECK(join() != 0);
	struct swapz_mm_trial_terminal_snapshot observed;
	CHECK(!snapshot(&observed) && observed.dm_callbacks == 1 && observed.dm_entrants == 1);
	CHECK(detach() != 0);
	++callbacks;
	free(bio); /* the wrapper must not touch the original after this */
}
static struct bio *enter(u64 *entrant)
{
	struct bio *bio = calloc(1, sizeof(*bio));
	CHECK(bio);
	*bio = (struct bio){ .bi_bdev = &mapper, .bi_end_io = original_endio,
		.bi_status = EIO, .bi_private = &callbacks };
	*entrant = swapz_mm_trial_dm_enter(bio);
	CHECK(*entrant && bio->bi_end_io != original_endio);
	CHECK(swapz_mm_terminal_debt.count == 2);
	return bio;
}
static void retire(void)
{
	swapz_mm_trial_area_offline(2);
	CHECK(!swapz_mm_capture_scope && swapz_mm_scope);
	CHECK(!swapz_mm_trial_scope_stop_capture(17));
	swapz_mm_trial_area_retired(2);
	CHECK(swapz_mm_area_drained);
}
static void callback_then_leave(struct bio *bio, u64 entrant, bool retired)
{
	callback_debt = 2;
	bio->bi_end_io(bio);
	CHECK(callbacks == 1 && swapz_mm_terminal_debt.count == 1);
	if (retired)
		CHECK(join() == -EBUSY);
	swapz_mm_trial_dm_leave(entrant);
	CHECK(!swapz_mm_terminal_debt.count);
	if (retired)
		CHECK(!join());
}
int main(int argc, char **argv)
{
	if (argc != 2)
		return 2;
	swapz_mm_trial_area_online(2);
	swapz_mm_scope_storage = (struct swapz_mm_trial_scope){
		.identity = 17, .session = 11, .table_epoch = 12, .target_epoch = 13,
		.area_epoch = swapz_mm_trial_area_epoch(2), .swap_type = 2,
		.bdev = &mapper, .first_sector = 56, .sector_count = 16 };
	swapz_mm_scope = swapz_mm_capture_scope = &swapz_mm_scope_storage;
	swapz_mm_scope_file = &mapper_file;
	swapz_mm_area_file = &area_file;
	u64 entrant;
	struct bio *bio = enter(&entrant);
	if (!strcmp(argv[1], "accepted-before-offline")) {
		CHECK(swapz_mm_trial_dm_origin(bio, 56));
		swapz_mm_trial_dm_complete(bio, 31, 32);
		retire();
		CHECK(!swapz_mm_trial_dm_origin(bio, 56));
		callback_then_leave(bio, entrant, true);
		CHECK(records == 1 && !losses && last.operation == 31 &&
		      last.original == 32 && last.status == EIO);
	} else if (!strcmp(argv[1], "offline-before-origin")) {
		retire();
		CHECK(!swapz_mm_trial_dm_origin(bio, 56));
		CHECK(losses == 1 && !records);
		callback_then_leave(bio, entrant, true);
		CHECK(!records && losses == 1 && !swapz_mm_terminal_debt.fault);
	} else if (!strcmp(argv[1], "reused-epoch")) {
		swapz_mm_trial_area_offline(2);
		swapz_mm_trial_area_online(2);
		CHECK(swapz_mm_trial_area_epoch(2) != swapz_mm_scope_storage.area_epoch);
		CHECK(!swapz_mm_trial_dm_origin(bio, 56));
		CHECK(losses == 1 && swapz_mm_terminal_debt.fault);
		callback_then_leave(bio, entrant, false);
		CHECK(!records);
	} else if (!strcmp(argv[1], "missing-correlation")) {
		CHECK(swapz_mm_trial_dm_origin(bio, 56));
		retire();
		callback_then_leave(bio, entrant, true);
		CHECK(!records && losses == 1 && !swapz_mm_terminal_debt.fault);
	} else if (!strcmp(argv[1], "unobserved")) {
		CHECK(!swapz_mm_trial_dm_origin(bio, 80));
		retire();
		callback_then_leave(bio, entrant, true);
		CHECK(!records && !losses);
	} else if (!strcmp(argv[1], "detach")) {
		struct swapz_mm_trial_terminal_snapshot observed = {};
		CHECK(detach() == -EBUSY);
		CHECK(swapz_mm_trial_scope_detach_files(17, 11, 12, 14) == -ESTALE);
		retire();
		CHECK(join() == -EBUSY && detach() == -EBUSY);
		callback_then_leave(bio, entrant, true);
		CHECK(!snapshot(&observed) && observed.area_retired && observed.capture_stopped && observed.terminal_joined && observed.terminal_closed && !observed.fault);
		CHECK(!observed.dm_callbacks && !observed.dm_entrants && !observed.mm_callbacks && !observed.carrier_busy);
		CHECK(!detach() && file_puts == 2 && !mapper_file.refs && !area_file.refs);
		CHECK(!swapz_mm_scope_storage.bdev && !swapz_mm_scope && swapz_mm_scope_cap == 1);
		CHECK(!snapshot(&observed) && observed.files_detached && !detach() && file_puts == 2);
		CHECK(!join() && swapz_mm_trial_scope_stop_capture(17) == -EALREADY);
		fail_put = true;
		CHECK(swapz_mm_trial_scope_revoke(17) == -EIO && swapz_mm_scope_cap == 1);
		CHECK(!snapshot(&observed) && observed.files_detached);
		fail_put = false;
		CHECK(!swapz_mm_trial_scope_revoke(17) && !swapz_mm_scope_cap && file_puts == 2);
		CHECK(snapshot(&observed) == -ESTALE && detach() == -ESTALE && join() == -ESTALE);
	} else if (!strcmp(argv[1], "partial-correlation")) {
		CHECK(swapz_mm_trial_dm_origin(bio, 56));
		swapz_mm_trial_dm_complete(bio, 31, 0);
		CHECK(losses && swapz_mm_terminal_debt.fault);
		callback_then_leave(bio, entrant, false);
		CHECK(!records && losses >= 2);
	} else {
		CHECK(false);
	}
	CHECK(!locks && !readers && !mutexes);
	printf("R105_A11_HOST_ONLY mode=%s checks=%u AUTH0\n", argv[1], checks);
	return 0;
}
