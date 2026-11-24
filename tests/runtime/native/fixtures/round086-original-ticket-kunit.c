// SPDX-License-Identifier: GPL-2.0-only
/* Isolated pinned-Linux KUnit fixture. No live MM/DM or production wiring. */
#include <kunit/test.h>
#include <linux/errno.h>
#include <linux/irqflags.h>
#include <linux/kernel.h>
#include <linux/preempt.h>
#include <linux/smp.h>
#include <linux/string.h>
#include "zswap-original-ticket.h"

#if !defined(__KERNEL__) || !defined(SWAPZ_ORIGINAL_TICKET_TEST)
#error "Round086 requires actual kernel adapter"
#endif
static_assert(SWAPZ_ORIGINAL_TICKET_ACTIVE == 0U);
static_assert(SWAPZ_MAX_COMPRESSED == 3568U);

struct r086_fixture {
	struct swapz_ticket_broker broker;
	struct swapz_ticket_slot slots[2];
	swapz_u32 indices[2];
	swapz_u8 storage[8192 + SWAPZ_TICKET_ALIGNMENT - 1U];
	swapz_u8 source[4096];
};

static struct r086_fixture *r086_alloc(struct kunit *test, swapz_u32 maximum,
	swapz_u64 budget)
{
	struct r086_fixture *fixture = kunit_kzalloc(test, sizeof(*fixture), GFP_KERNEL);
	size_t stride = maximum == 3568U ? 3584U : 4096U;
	int error;

	if (!fixture)
		return NULL;
	memset(fixture->source, 0x5b, sizeof(fixture->source));
	error = swapz_ticket_init(&fixture->broker, fixture->slots,
		sizeof(fixture->slots), PTR_ALIGN(&fixture->storage[0], SWAPZ_TICKET_ALIGNMENT),
		stride * 2U, fixture->indices, sizeof(fixture->indices),
		2U, maximum, budget, 17U, 23U);
	KUNIT_EXPECT_EQ(test, error, 0);
	return error ? NULL : fixture;
}

static struct swapz_ticket_key r086_key(struct r086_fixture *fixture, swapz_u32 length)
{
	struct swapz_ticket_key key = {
		.area_epoch = 3, .store_sequence = 4, .target_session = 17,
		.table_epoch = 23, .target_epoch = 9, .dm_generation = 8,
		.length = length, .decoded_length = 4096,
		.representation = SWAPZ_TICKET_ORIGINAL,
		.codec = SWAPZ_TICKET_LZ4, .version = 1,
	};
	key.sha256[0] = 1;
	key.crc = swapz_crc32c_bytes(fixture->source, length);
	return key;
}

static void r086_usage(struct kunit *test, struct r086_fixture *fixture,
	swapz_u32 count, swapz_u64 bytes)
{
	struct swapz_ticket_usage usage;

	KUNIT_ASSERT_EQ(test, swapz_ticket_usage(&fixture->broker, &usage), 0);
	KUNIT_EXPECT_EQ(test, usage.live_slots, count);
	KUNIT_EXPECT_EQ(test, usage.reserved_bytes, bytes);
	KUNIT_EXPECT_EQ(test, usage.total_bytes, sizeof(fixture->broker) +
		sizeof(fixture->slots) + sizeof(fixture->indices) + usage.payload_bytes);
}

static void r086_finish(struct kunit *test, struct r086_fixture *fixture)
{
	r086_usage(test, fixture, 0, 0);
	KUNIT_EXPECT_EQ(test, swapz_ticket_close(&fixture->broker), 0);
	KUNIT_EXPECT_EQ(test, swapz_ticket_destroy(&fixture->broker), 0);
}

static void r086_capacity_one(struct kunit *test, swapz_u32 maximum)
{
	struct r086_fixture *fixture = r086_alloc(test, maximum, maximum + 1U);
	struct swapz_ticket_ref first = {}, second = {}, third = {};
	struct swapz_ticket_usage usage;
	struct swapz_ticket_key key;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	KUNIT_ASSERT_EQ(test, swapz_ticket_usage(&fixture->broker, &usage), 0);
	KUNIT_EXPECT_EQ(test, usage.stride, (size_t)(maximum == 3568U ? 3584U : 4096U));
	KUNIT_EXPECT_EQ(test, usage.payload_bytes, 2U * usage.stride);
	key = r086_key(fixture, maximum);
	KUNIT_ASSERT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &first), 0);
	key = r086_key(fixture, 2);
	KUNIT_EXPECT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &second), -ENOSPC);
	KUNIT_EXPECT_PTR_EQ(test, second.broker, NULL);
	r086_usage(test, fixture, 1, maximum);
	key = r086_key(fixture, 1);
	KUNIT_ASSERT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &second), 0);
	KUNIT_EXPECT_NE(test, first.index, second.index);
	KUNIT_EXPECT_EQ(test, swapz_ticket_put(&first), 0);
	KUNIT_ASSERT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &first), 0);
	/* Count exhausted despite spare byte credit. */
	KUNIT_EXPECT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &third), -ENOSPC);
	r086_usage(test, fixture, 2, 2);
	KUNIT_EXPECT_EQ(test, swapz_ticket_put(&first), 0);
	KUNIT_EXPECT_EQ(test, swapz_ticket_put(&second), 0);
	r086_finish(test, fixture);
}

static void r086_capacity(struct kunit *test)
{
	r086_capacity_one(test, 3568);
	r086_capacity_one(test, 4095);
	kunit_info(test, "R086_SIZEOF broker=%zu slot=%zu ref=%zu key=%zu index=%zu",
		sizeof(struct swapz_ticket_broker), sizeof(struct swapz_ticket_slot),
		sizeof(struct swapz_ticket_ref), sizeof(struct swapz_ticket_key),
		sizeof(swapz_u32));
}

static void r086_irq_and_contention(struct kunit *test)
{
	struct r086_fixture *fixture = r086_alloc(test, 3568, 128);
	struct swapz_ticket_ref first = {}, declined = {};
	struct swapz_ticket_key key;
	unsigned long flags;
	bool before_irq, after_irq, failed_irq, disabled_irq;
	int before_preempt, after_preempt, locked_preempt, failed_preempt;
	int reserve_error, claim_error, disabled_error, put_error;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	KUNIT_ASSERT_TRUE(test, IS_ENABLED(CONFIG_SMP));
	KUNIT_ASSERT_TRUE(test, IS_ENABLED(CONFIG_DEBUG_SPINLOCK));
	key = r086_key(fixture, 64);
	before_irq = irqs_disabled();
	before_preempt = preempt_count();
	KUNIT_ASSERT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &first), 0);
	after_irq = irqs_disabled();
	after_preempt = preempt_count();
	KUNIT_EXPECT_EQ(test, after_irq, before_irq);
	KUNIT_EXPECT_EQ(test, after_preempt, before_preempt);
	KUNIT_ASSERT_EQ(test, swapz_ticket_seal(&first, fixture->source, 64), 0);

	/* Deliberately hold the broker's OWN lock to exercise failed trylock.
	 * SMP is mandatory: UP debug locks diagnose failure as a kernel bug.
	 * No assertions, printing, sleeping, allocation or foreign lock here. */
	spin_lock_irqsave(&fixture->broker.lock, flags);
	locked_preempt = preempt_count();
	reserve_error = swapz_ticket_reserve(&fixture->broker, &key, &declined);
	claim_error = swapz_ticket_claim(&first, &key);
	failed_irq = irqs_disabled();
	failed_preempt = preempt_count();
	spin_unlock_irqrestore(&fixture->broker.lock, flags);
	KUNIT_EXPECT_EQ(test, reserve_error, -EAGAIN);
	KUNIT_EXPECT_EQ(test, claim_error, -EAGAIN);
	KUNIT_EXPECT_TRUE(test, failed_irq);
	KUNIT_EXPECT_EQ(test, failed_preempt, locked_preempt);
	KUNIT_EXPECT_EQ(test, (bool)irqs_disabled(), before_irq);
	KUNIT_EXPECT_EQ(test, preempt_count(), before_preempt);
	KUNIT_EXPECT_PTR_EQ(test, declined.broker, NULL);
	r086_usage(test, fixture, 1, 64);

	/* Success also restores the incoming disabled state, not just enabled. */
	local_irq_save(flags);
	disabled_error = swapz_ticket_claim(&first, &key);
	disabled_irq = irqs_disabled();
	put_error = swapz_ticket_put(&first);
	failed_irq = irqs_disabled();
	local_irq_restore(flags);
	KUNIT_EXPECT_EQ(test, disabled_error, 0);
	KUNIT_EXPECT_EQ(test, put_error, 0);
	KUNIT_EXPECT_TRUE(test, disabled_irq);
	KUNIT_EXPECT_TRUE(test, failed_irq);
	KUNIT_EXPECT_EQ(test, (bool)irqs_disabled(), before_irq);
	KUNIT_EXPECT_EQ(test, preempt_count(), before_preempt);
	r086_finish(test, fixture);
}

static void r086_seal_claim(struct kunit *test)
{
	struct r086_fixture *fixture = r086_alloc(test, 4095, 4095);
	struct swapz_ticket_ref producer = {}, reader = {};
	struct swapz_ticket_view view = {};
	struct swapz_ticket_key key, wrong;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	KUNIT_EXPECT_EQ(test, swapz_crc32c_bytes("123456789", 9), (swapz_u32)0xe3069283);
	key = r086_key(fixture, 4095);
	key.codec = SWAPZ_TICKET_LZO1X;
	KUNIT_ASSERT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &producer), 0);
	KUNIT_EXPECT_EQ(test, swapz_ticket_retain(&producer, &reader), -EAGAIN);
	KUNIT_EXPECT_EQ(test, swapz_ticket_claim(&producer, &key), -EALREADY);
	KUNIT_ASSERT_EQ(test, swapz_ticket_seal(&producer, fixture->source, key.length), 0);
	KUNIT_ASSERT_EQ(test, swapz_ticket_view(&producer, &view), 0);
	KUNIT_EXPECT_EQ(test, view.key.codec, key.codec);
	KUNIT_EXPECT_EQ(test, view.key.crc, key.crc);
	KUNIT_EXPECT_EQ(test, memcmp(view.bytes, fixture->source, key.length), 0);
	fixture->source[0] = 0;
	KUNIT_EXPECT_EQ(test, view.bytes[0], (swapz_u8)0x5b);
	KUNIT_EXPECT_EQ(test, swapz_ticket_seal(&producer, fixture->source, key.length), -EALREADY);
	wrong = key;
	++wrong.target_epoch;
	KUNIT_EXPECT_EQ(test, swapz_ticket_claim(&producer, &wrong), -ESTALE);
	wrong = key;
	++wrong.sha256[0];
	KUNIT_EXPECT_EQ(test, swapz_ticket_claim(&producer, &wrong), -ESTALE);
	KUNIT_ASSERT_EQ(test, swapz_ticket_retain(&producer, &reader), 0);
	KUNIT_EXPECT_EQ(test, swapz_ticket_claim(&reader, &key), 0);
	KUNIT_EXPECT_EQ(test, swapz_ticket_claim(&producer, &key), -EALREADY);
	KUNIT_EXPECT_EQ(test, swapz_ticket_cancel(&producer), -EBUSY);
	KUNIT_EXPECT_EQ(test, swapz_ticket_put(&producer), 0);
	r086_usage(test, fixture, 1, 4095);
	KUNIT_EXPECT_EQ(test, view.bytes[0], (swapz_u8)0x5b);
	KUNIT_EXPECT_EQ(test, swapz_ticket_put(&reader), 0);
	r086_finish(test, fixture);
}

/* IPI executes actual APIs on the other online virtual CPU, without any
 * assertion or allocation in the callback; main owns no broker lock. */
struct r086_remote {
	const struct swapz_ticket_ref *source;
	struct swapz_ticket_ref lease;
	int error;
	int cpu;
	bool irq_before, irq_after;
};
static void r086_remote_retain(void *argument)
{
	struct r086_remote *remote = argument;

	remote->cpu = raw_smp_processor_id();
	remote->irq_before = irqs_disabled();
	remote->error = swapz_ticket_retain(remote->source, &remote->lease);
	remote->irq_after = irqs_disabled();
}
static void r086_remote_put(void *argument)
{
	struct r086_remote *remote = argument;

	remote->cpu = raw_smp_processor_id();
	remote->irq_before = irqs_disabled();
	remote->error = swapz_ticket_put(&remote->lease);
	remote->irq_after = irqs_disabled();
}
static void r086_revoke_close(struct kunit *test)
{
	struct r086_fixture *fixture = r086_alloc(test, 3568, 64);
	struct swapz_ticket_ref first = {}, late = {};
	struct swapz_ticket_key key, next;
	struct swapz_ticket_view view;
	struct r086_remote remote = {};
	int current_cpu, other_cpu, dispatch_error;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	KUNIT_ASSERT_GE(test, num_online_cpus(), 2U);
	key = r086_key(fixture, 64);
	KUNIT_ASSERT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &first), 0);
	KUNIT_ASSERT_EQ(test, swapz_ticket_seal(&first, fixture->source, 64), 0);
	remote.source = &first;
	current_cpu = get_cpu();
	other_cpu = current_cpu == 0 ? 1 : 0;
	dispatch_error = smp_call_function_single(other_cpu, r086_remote_retain, &remote, 1);
	put_cpu();
	KUNIT_ASSERT_EQ(test, dispatch_error, 0);
	KUNIT_ASSERT_EQ(test, remote.error, 0);
	KUNIT_EXPECT_EQ(test, remote.cpu, other_cpu);
	KUNIT_EXPECT_EQ(test, remote.irq_after, remote.irq_before);
	KUNIT_EXPECT_EQ(test, swapz_ticket_revoke(&fixture->broker, 23), -ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_ticket_revoke(&fixture->broker, 24), 0);
	KUNIT_EXPECT_EQ(test, swapz_ticket_claim(&first, &key), -ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_ticket_retain(&first, &late), -ESTALE);
	next = key;
	next.table_epoch = 24;
	KUNIT_EXPECT_EQ(test, swapz_ticket_reserve(&fixture->broker, &next, &late), -ENOSPC);
	KUNIT_EXPECT_EQ(test, swapz_ticket_put(&first), 0);
	r086_usage(test, fixture, 1, 64);
	KUNIT_EXPECT_EQ(test, swapz_ticket_close(&fixture->broker), -EBUSY);
	KUNIT_EXPECT_EQ(test, swapz_ticket_reserve(&fixture->broker, &next, &late), -ESHUTDOWN);
	KUNIT_EXPECT_EQ(test, swapz_ticket_retain(&remote.lease, &late), -ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_ticket_destroy(&fixture->broker), -EBUSY);
	KUNIT_ASSERT_EQ(test, swapz_ticket_view(&remote.lease, &view), 0);
	KUNIT_EXPECT_EQ(test, view.bytes[0], (swapz_u8)0x5b);
	/* synchronous dispatch joins the remote final put before destroy */
	current_cpu = get_cpu();
	other_cpu = current_cpu == 0 ? 1 : 0;
	dispatch_error = smp_call_function_single(other_cpu, r086_remote_put, &remote, 1);
	put_cpu();
	KUNIT_ASSERT_EQ(test, dispatch_error, 0);
	KUNIT_EXPECT_EQ(test, remote.error, 0);
	KUNIT_EXPECT_EQ(test, remote.cpu, other_cpu);
	KUNIT_EXPECT_EQ(test, remote.irq_after, remote.irq_before);
	r086_finish(test, fixture);
}

static void r086_generation_refs(struct kunit *test)
{
	struct r086_fixture *fixture = r086_alloc(test, 3568, 64);
	struct swapz_ticket_ref first = {}, stale, late = {};
	struct swapz_ticket_key key;
	struct swapz_ticket_view view = {};
	unsigned long flags;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	key = r086_key(fixture, 64);
	KUNIT_ASSERT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &first), 0);
	/* Deliberate stale identifier, never used to manufacture ownership. */
	stale = first;
	KUNIT_EXPECT_EQ(test, swapz_ticket_put(&first), 0);
	KUNIT_EXPECT_EQ(test, swapz_ticket_put(&first), -EALREADY);
	KUNIT_ASSERT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &first), 0);
	KUNIT_EXPECT_EQ(test, stale.index, first.index);
	KUNIT_EXPECT_NE(test, stale.generation, first.generation);
	KUNIT_ASSERT_EQ(test, swapz_ticket_seal(&first, fixture->source, 64), 0);
	view.key.length = 123;
	KUNIT_EXPECT_EQ(test, swapz_ticket_view(&stale, &view), -ESTALE);
	KUNIT_EXPECT_EQ(test, view.key.length, (swapz_u32)123);
	KUNIT_EXPECT_PTR_EQ(test, view.bytes, NULL);
	/* Quiescent white-box fault injection; no assertions under lock. */
	spin_lock_irqsave(&fixture->broker.lock, flags);
	fixture->slots[first.index].refs = ~(swapz_u32)0;
	spin_unlock_irqrestore(&fixture->broker.lock, flags);
	KUNIT_EXPECT_EQ(test, swapz_ticket_retain(&first, &late), -EOVERFLOW);
	KUNIT_EXPECT_PTR_EQ(test, late.broker, NULL);
	spin_lock_irqsave(&fixture->broker.lock, flags);
	fixture->slots[first.index].refs = 1;
	fixture->broker.next_generation = ~(swapz_u64)0;
	spin_unlock_irqrestore(&fixture->broker.lock, flags);
	KUNIT_EXPECT_EQ(test, swapz_ticket_put(&first), 0);
	KUNIT_EXPECT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &late), -EOVERFLOW);
	r086_finish(test, fixture);
}

static void r086_copy_failures(struct kunit *test)
{
	struct r086_fixture *fixture = r086_alloc(test, 3568, 64);
	struct swapz_ticket_ref first = {}, late = {};
	struct swapz_ticket_key key;
	struct swapz_ticket_view view = {};

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	key = r086_key(fixture, 4096);
	KUNIT_EXPECT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &first), -EMSGSIZE);
	key = r086_key(fixture, 64);
	key.codec = 3;
	KUNIT_EXPECT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &first), -EINVAL);
	key.codec = SWAPZ_TICKET_LZ4;
	KUNIT_ASSERT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &first), 0);
	KUNIT_EXPECT_EQ(test, swapz_ticket_seal(&first, fixture->source, 63), -EINVAL);
	KUNIT_EXPECT_EQ(test, swapz_ticket_view(&first, &view), -ESTALE);
	r086_usage(test, fixture, 1, 64);
	KUNIT_EXPECT_EQ(test, swapz_ticket_put(&first), 0);
	KUNIT_ASSERT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &first), 0);
	fixture->source[1] ^= 1;
	KUNIT_EXPECT_EQ(test, swapz_ticket_seal(&first, fixture->source, 64), -EBADMSG);
	KUNIT_EXPECT_EQ(test, swapz_ticket_retain(&first, &late), -ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_ticket_put(&first), 0);
	key = r086_key(fixture, 64);
	KUNIT_ASSERT_EQ(test, swapz_ticket_reserve(&fixture->broker, &key, &first), 0);
	KUNIT_EXPECT_EQ(test, swapz_ticket_cancel(&first), 0);
	KUNIT_EXPECT_EQ(test, swapz_ticket_claim(&first, &key), -ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_ticket_put(&first), 0);
	r086_finish(test, fixture);
}

static struct kunit_case r086_cases[] = {
	KUNIT_CASE(r086_capacity),
	KUNIT_CASE(r086_irq_and_contention),
	KUNIT_CASE(r086_seal_claim),
	KUNIT_CASE(r086_revoke_close),
	KUNIT_CASE(r086_generation_refs),
	KUNIT_CASE(r086_copy_failures),
	{}
};
static struct kunit_suite r086_suite = {
	.name = "swapz_round086_original_ticket",
	.test_cases = r086_cases,
};
kunit_test_suite(r086_suite);
