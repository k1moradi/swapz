// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-ticket.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(condition) do { if (!(condition)) { \
	fprintf(stderr, "FIRST_ERROR line=%d %s\n", __LINE__, #condition); \
	exit(77); } } while (0)

struct fixture {
	struct swapz_ticket_broker broker;
	struct swapz_ticket_slot slots[2];
	swapz_u32 indices[2];
	_Alignas(64) swapz_u8 bytes[8192];
	swapz_u8 source[4096];
};
static int setup(struct fixture *f, swapz_u32 maximum, swapz_u64 budget)
{
	size_t stride = maximum == 3568U ? 3584U : 4096U;
	memset(f, 0, sizeof(*f));
	memset(f->source, 0x5b, sizeof(f->source));
	return swapz_ticket_init(&f->broker, f->slots, sizeof(f->slots),
		f->bytes, stride * 2U, f->indices, sizeof(f->indices),
		2U, maximum, budget, 17U, 23U);
}
static struct swapz_ticket_key key_for(struct fixture *f, swapz_u32 length)
{
	struct swapz_ticket_key key = {
		.area_epoch = 3, .store_sequence = 4, .slot_offset = 0,
		.target_session = 17, .table_epoch = 23, .target_epoch = 9,
		.logical_page = 0, .dm_generation = 8, .swap_type = 0,
		.length = length, .decoded_length = 4096,
		.representation = SWAPZ_TICKET_ORIGINAL, .codec = SWAPZ_TICKET_LZ4,
		.version = 1
	};
	key.sha256[0] = 1U;
	key.crc = swapz_crc32c_bytes(f->source, length);
	return key;
}
static void usage(struct fixture *f, swapz_u32 count, swapz_u64 bytes)
{
	struct swapz_ticket_usage snapshot;
	CHECK(swapz_ticket_usage(&f->broker, &snapshot) == 0);
	CHECK(snapshot.live_slots == count && snapshot.reserved_bytes == bytes);
	CHECK(snapshot.total_bytes == sizeof(f->broker) + sizeof(f->slots) +
		sizeof(f->indices) + snapshot.payload_bytes);
}
static void finish(struct fixture *f)
{
	usage(f, 0, 0);
	CHECK(swapz_ticket_close(&f->broker) == 0);
	CHECK(swapz_ticket_destroy(&f->broker) == 0);
}
static void invalid_init(void)
{
	struct fixture f = {0};
	CHECK(setup(&f, 4096U, 1U) == -EMSGSIZE);
	CHECK(swapz_ticket_init(&f.broker, f.slots, sizeof(f.slots), f.bytes + 1,
		8192U, f.indices, sizeof(f.indices), 2, 4095, 1, 17, 23) == -EINVAL);
	CHECK(swapz_ticket_init(&f.broker, f.slots, sizeof(f.slots), f.bytes,
		8191U, f.indices, sizeof(f.indices), 2, 4095, 1, 17, 23) == -EMSGSIZE);
	CHECK(swapz_ticket_init(&f.broker, f.slots, sizeof(f.slots), f.bytes,
		8192U, (swapz_u32 *)(void *)f.bytes, sizeof(f.indices),
		2, 4095, 1, 17, 23) == -EINVAL);
	CHECK(swapz_ticket_init(&f.broker, f.slots, sizeof(f.slots), f.bytes,
		8192U, f.indices, sizeof(f.indices), 2, 4095, 8191, 17, 23) == -EMSGSIZE);
}
static void capacity(swapz_u32 maximum)
{
	struct fixture f;
	struct swapz_ticket_ref a = {0}, b = {0}, c = {0};
	struct swapz_ticket_usage snapshot;
	struct swapz_ticket_key key;
	CHECK(setup(&f, maximum, (swapz_u64)maximum * 2U) == 0);
	CHECK(swapz_ticket_usage(&f.broker, &snapshot) == 0);
	CHECK(snapshot.stride == (maximum == 3568U ? 3584U : 4096U));
	CHECK(snapshot.payload_bytes == snapshot.stride * 2U);
	key = key_for(&f, maximum);
	CHECK(swapz_ticket_reserve(&f.broker, &key, &a) == 0);
	CHECK(swapz_ticket_reserve(&f.broker, &key, &b) == 0);
	CHECK(a.index != b.index && a.generation != b.generation);
	usage(&f, 2, (swapz_u64)maximum * 2U);
	CHECK(swapz_ticket_reserve(&f.broker, &key, &c) == -ENOSPC && !c.broker);
	CHECK(swapz_ticket_put(&a) == 0);
	CHECK(swapz_ticket_put(&b) == 0);
	/* Isolate count exhaustion from byte exhaustion. */
	key = key_for(&f, 1);
	CHECK(swapz_ticket_reserve(&f.broker, &key, &a) == 0);
	CHECK(swapz_ticket_reserve(&f.broker, &key, &b) == 0);
	CHECK(swapz_ticket_reserve(&f.broker, &key, &c) == -ENOSPC);
	CHECK(swapz_ticket_put(&a) == 0);
	CHECK(swapz_ticket_put(&b) == 0);
	finish(&f);
}
static void rejection(void)
{
	struct fixture f;
	struct swapz_ticket_ref a = {0}, b = {0};
	struct swapz_ticket_key key, wrong;
	CHECK(setup(&f, 3568U, 3568U) == 0);
	key = key_for(&f, 3567);
	CHECK(swapz_ticket_reserve(&f.broker, &key, &a) == 0);
	wrong = key_for(&f, 2);
	CHECK(swapz_ticket_reserve(&f.broker, &wrong, &b) == -ENOSPC);
	CHECK(swapz_ticket_put(&a) == 0);
	wrong = key_for(&f, 3569);
	CHECK(swapz_ticket_reserve(&f.broker, &wrong, &b) == -EMSGSIZE);
	wrong = key_for(&f, 0);
	CHECK(swapz_ticket_reserve(&f.broker, &wrong, &b) == -EMSGSIZE);
	wrong = key; wrong.codec = 3;
	CHECK(swapz_ticket_reserve(&f.broker, &wrong, &b) == -EINVAL);
	wrong = key; wrong.version = 2;
	CHECK(swapz_ticket_reserve(&f.broker, &wrong, &b) == -EINVAL);
	wrong = key; wrong.dictionary = 1;
	CHECK(swapz_ticket_reserve(&f.broker, &wrong, &b) == -EINVAL);
	wrong = key; wrong.representation = 0;
	CHECK(swapz_ticket_reserve(&f.broker, &wrong, &b) == -EINVAL);
	wrong = key; wrong.store_sequence = 0;
	CHECK(swapz_ticket_reserve(&f.broker, &wrong, &b) == -EINVAL);
	wrong = key; wrong.decoded_length = 4095;
	CHECK(swapz_ticket_reserve(&f.broker, &wrong, &b) == -EINVAL);
	wrong = key; wrong.target_session = 18;
	CHECK(swapz_ticket_reserve(&f.broker, &wrong, &b) == -ESTALE);
	wrong = key; wrong.table_epoch = 24;
	CHECK(swapz_ticket_reserve(&f.broker, &wrong, &b) == -ESTALE);
	CHECK(!b.broker && !b.generation && !b.session && !b.index);
	CHECK(pthread_mutex_lock(&f.broker.lock) == 0);
	CHECK(swapz_ticket_reserve(&f.broker, &key, &b) == -EAGAIN);
	CHECK(pthread_mutex_unlock(&f.broker.lock) == 0);
	f.broker.next_generation = ~(swapz_u64)0;
	CHECK(swapz_ticket_reserve(&f.broker, &key, &b) == -EOVERFLOW);
	finish(&f);
}
static void seal_claim(void)
{
	struct fixture f;
	struct swapz_ticket_ref a = {0}, b = {0}, stale;
	struct swapz_ticket_key key, wrong;
	struct swapz_ticket_view view = {0};
	swapz_u64 generation;
	swapz_u32 old_index;
	CHECK(setup(&f, 4095U, 8190U) == 0);
	wrong = key_for(&f, 4096);
	CHECK(swapz_ticket_reserve(&f.broker, &wrong, &a) == -EMSGSIZE);
	key = key_for(&f, 4095);
	key.codec = SWAPZ_TICKET_LZO1X;
	CHECK(swapz_ticket_reserve(&f.broker, &key, &a) == 0);
	CHECK(swapz_ticket_view(&a, &view) == -ESTALE && !view.bytes);
	CHECK(swapz_ticket_retain(&a, &b) == -EAGAIN && !b.broker);
	CHECK(swapz_ticket_claim(&a, &key) == -EALREADY);
	CHECK(swapz_ticket_seal(&a, f.source, key.length) == 0);
	CHECK(swapz_ticket_view(&a, &view) == 0);
	CHECK(view.key.length == 4095U && view.key.codec == SWAPZ_TICKET_LZO1X);
	CHECK(!memcmp(view.bytes, f.source, key.length));
	f.source[0] = 0;
	CHECK(view.bytes[0] == 0x5bU);
	CHECK(swapz_ticket_seal(&a, f.source, key.length) == -EALREADY);
	wrong = key; wrong.store_sequence++;
	CHECK(swapz_ticket_claim(&a, &wrong) == -ESTALE);
	wrong = key; wrong.target_epoch++;
	CHECK(swapz_ticket_claim(&a, &wrong) == -ESTALE);
	wrong = key; wrong.sha256[0]++;
	CHECK(swapz_ticket_claim(&a, &wrong) == -ESTALE);
	CHECK(swapz_ticket_retain(&a, &b) == 0);
	CHECK(f.slots[a.index].refs == 2U);
	CHECK(swapz_ticket_claim(&b, &key) == 0);
	CHECK(swapz_ticket_claim(&a, &key) == -EALREADY);
	CHECK(swapz_ticket_cancel(&a) == -EBUSY);
	generation = a.generation;
	old_index = a.index;
	CHECK(swapz_ticket_put(&a) == 0);
	CHECK(swapz_ticket_put(&a) == -EALREADY);
	usage(&f, 1, 4095);
	CHECK(view.bytes[0] == 0x5bU);
	CHECK(swapz_ticket_put(&b) == 0);
	/* Stale identifier never used as a fabricated ownership put. */
	stale = (struct swapz_ticket_ref){&f.broker, 17, generation, old_index};
	key = key_for(&f, 1);
	CHECK(swapz_ticket_reserve(&f.broker, &key, &a) == 0);
	CHECK(a.generation != generation && a.index == old_index);
	CHECK(swapz_ticket_seal(&a, f.source, 1) == 0);
	view.bytes = NULL;
	view.key.length = 123;
	CHECK(swapz_ticket_view(&stale, &view) == -ESTALE);
	CHECK(!view.bytes && view.key.length == 123U);
	CHECK(swapz_ticket_put(&a) == 0);
	finish(&f);
}
static void bad_copy(void)
{
	struct fixture f;
	struct swapz_ticket_ref a = {0}, b = {0};
	struct swapz_ticket_key key;
	struct swapz_ticket_view view = {0};
	CHECK(setup(&f, 3568U, 7136U) == 0);
	key = key_for(&f, 64);
	CHECK(swapz_ticket_reserve(&f.broker, &key, &a) == 0);
	CHECK(swapz_ticket_seal(&a, f.source, 63) == -EINVAL);
	CHECK(swapz_ticket_view(&a, &view) == -ESTALE);
	CHECK(swapz_ticket_put(&a) == 0);
	CHECK(swapz_ticket_reserve(&f.broker, &key, &a) == 0);
	f.source[1] ^= 1U;
	CHECK(swapz_ticket_seal(&a, f.source, 64) == -EBADMSG);
	CHECK(swapz_ticket_retain(&a, &b) == -ESTALE);
	CHECK(swapz_ticket_put(&a) == 0);
	key = key_for(&f, 64);
	CHECK(swapz_ticket_reserve(&f.broker, &key, &a) == 0);
	CHECK(swapz_ticket_seal(&a, f.source, 64) == 0);
	f.slots[a.index].refs = ~(swapz_u32)0;
	CHECK(swapz_ticket_retain(&a, &b) == -EOVERFLOW && !b.broker);
	f.slots[a.index].refs = 1U;
	CHECK(swapz_ticket_cancel(&a) == 0);
	CHECK(swapz_ticket_claim(&a, &key) == -ESTALE);
	CHECK(swapz_ticket_put(&a) == 0);
	finish(&f);
}
struct race {
	pthread_barrier_t barrier;
	struct swapz_ticket_ref ref;
	struct swapz_ticket_key key;
};
static void rendezvous(pthread_barrier_t *barrier)
{
	int result = pthread_barrier_wait(barrier);
	CHECK(result == 0 || result == PTHREAD_BARRIER_SERIAL_THREAD);
}
static void *reader(void *argument)
{
	struct race *race = argument;
	struct swapz_ticket_ref late = {0};
	struct swapz_ticket_view view;
	rendezvous(&race->barrier);
	rendezvous(&race->barrier);
	CHECK(swapz_ticket_claim(&race->ref, &race->key) == -ESTALE);
	CHECK(swapz_ticket_retain(&race->ref, &late) == -ESTALE);
	CHECK(swapz_ticket_view(&race->ref, &view) == 0 && view.bytes[0] == 0x5bU);
	CHECK(swapz_ticket_put(&race->ref) == 0);
	rendezvous(&race->barrier);
	return NULL;
}
static void revoke_close(void)
{
	struct fixture f;
	struct swapz_ticket_ref a = {0}, b = {0}, late = {0};
	struct race race = {0};
	struct swapz_ticket_key key, next;
	pthread_t thread;
	CHECK(setup(&f, 3568U, 64U) == 0);
	key = key_for(&f, 64);
	CHECK(swapz_ticket_reserve(&f.broker, &key, &a) == 0);
	CHECK(swapz_ticket_seal(&a, f.source, 64) == 0);
	CHECK(swapz_ticket_retain(&a, &race.ref) == 0);
	race.key = key;
	CHECK(pthread_barrier_init(&race.barrier, NULL, 2) == 0);
	CHECK(pthread_create(&thread, NULL, reader, &race) == 0);
	rendezvous(&race.barrier);
	CHECK(swapz_ticket_revoke(&f.broker, 23) == -ESTALE);
	CHECK(swapz_ticket_revoke(&f.broker, 24) == 0);
	CHECK(swapz_ticket_claim(&a, &key) == -ESTALE);
	CHECK(swapz_ticket_retain(&a, &late) == -ESTALE);
	next = key; next.table_epoch = 24;
	CHECK(swapz_ticket_reserve(&f.broker, &next, &b) == -ENOSPC);
	CHECK(swapz_ticket_put(&a) == 0);
	usage(&f, 1, 64);
	CHECK(swapz_ticket_close(&f.broker) == -EBUSY);
	CHECK(swapz_ticket_reserve(&f.broker, &next, &b) == -ESHUTDOWN);
	/* No simultaneous API entrant; blocked worker owns a retained lease. */
	CHECK(swapz_ticket_destroy(&f.broker) == -EBUSY);
	rendezvous(&race.barrier);
	rendezvous(&race.barrier);
	CHECK(pthread_join(thread, NULL) == 0);
	CHECK(pthread_barrier_destroy(&race.barrier) == 0);
	finish(&f);
}
int main(void)
{
	invalid_init();
	capacity(3568U);
	capacity(4095U);
	rejection();
	seal_claim();
	bad_copy();
	revoke_close();
	printf("PASS_HOST_ONLY ROUND084_AGENT11 actual broker; sizeof broker=%zu slot=%zu ref=%zu key=%zu index=%zu\n",
		sizeof(struct swapz_ticket_broker), sizeof(struct swapz_ticket_slot),
		sizeof(struct swapz_ticket_ref), sizeof(struct swapz_ticket_key), sizeof(swapz_u32));
	return 0;
}
