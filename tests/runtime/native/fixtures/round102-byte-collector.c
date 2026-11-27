/* SPDX-License-Identifier: GPL-2.0-only */
#include "native-observation-byte-collector.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static struct swapz_byte_collector *fresh(void)
{
	struct swapz_byte_collector *collector = calloc(1, sizeof(*collector));
	assert(collector && swapz_byte_start(collector, 1, 16));
	return collector;
}
static bool join_ok(void *context) { return context != NULL; }
static void dispose(struct swapz_byte_collector *collector)
{
	assert(swapz_byte_release(collector));
	assert(!swapz_byte_start(collector, 1, 1));
	assert(!pthread_mutex_destroy(&collector->lock));
	free(collector);
}
static void write_one(struct swapz_byte_collector *collector, u64 id, unsigned char *page)
{
	assert(swapz_byte_begin(collector, SWAPZ_BYTE_WRITE, 1, id, id+1, page, 4096));
	assert(swapz_byte_accept(collector, id, id+1, id+2, id+3, id+4));
	assert(swapz_byte_clone(collector, id, id+2, id+3, id+5, 0));
	assert(swapz_byte_upper(collector, id, id+1, id+2, id+3, id+6, 0));
	assert(swapz_byte_user(collector, id, id+1, 0, NULL, 0));
}
int main(void)
{
	unsigned char page[4096];
	const struct swapz_byte_record *records;
	unsigned int count, index;
	struct swapz_byte_collector *collector = fresh();
	memset(page, 17, sizeof(page));
	write_one(collector, 10, page);
	memset(page, 34, sizeof(page));
	assert(swapz_byte_begin(collector, SWAPZ_BYTE_READ, 1, 20, 21, NULL, 0));
	assert(swapz_byte_accept(collector, 20, 21, 22, 23, 24));
	assert(swapz_byte_pin(collector, 20, 23, 25, 26));
	assert(swapz_byte_copy(collector, 20, 23, 25, 27, page, sizeof(page)));
	memset(page, 51, sizeof(page));
	assert(swapz_byte_unpin(collector, 20, 23, 25, 28));
	assert(swapz_byte_clone(collector, 20, 22, 23, 29, 0));
	assert(swapz_byte_upper(collector, 20, 21, 22, 23, 30, 0));
	assert(swapz_byte_user(collector, 20, 21, 0, page, sizeof(page)));
	memset(page, 68, sizeof(page));
	assert(!swapz_byte_export(collector, &records, &count));
	assert(swapz_byte_stop(collector, join_ok, collector));
	assert(swapz_byte_export(collector, &records, &count) && count == 2);
	for (index = 0; index < sizeof(page); ++index) {
		assert(records[0].input_page[index] == 17);
		assert(records[1].final_copy[index] == 34);
		assert(records[1].user_page[index] == 51);
	}
	dispose(collector);
	for (index = 0; index < 10; ++index) {
		collector = fresh();
		switch (index) {
		case 0: assert(!swapz_byte_begin(collector, SWAPZ_BYTE_WRITE, 1, 0, 2, page, 4096)); break;
		case 1: assert(!swapz_byte_begin(collector, SWAPZ_BYTE_WRITE, 1, 1, 2, page, 4095)); break;
		case 2: write_one(collector, 10, page); assert(!swapz_byte_begin(collector, SWAPZ_BYTE_WRITE, 1, 10, 11, page, 4096)); break;
		case 3: assert(swapz_byte_begin(collector, SWAPZ_BYTE_READ, 1, 1, 2, NULL, 0)); assert(swapz_byte_accept(collector, 1, 2, 3, 4, 5)); assert(!swapz_byte_copy(collector, 1, 4, 6, 7, page, 4096)); break;
		case 4: assert(swapz_byte_begin(collector, SWAPZ_BYTE_READ, 1, 1, 2, NULL, 0)); break;
		case 5: for (unsigned int n = 0; n < 64; ++n) write_one(collector, 10 + 10*n, page); assert(!swapz_byte_begin(collector, SWAPZ_BYTE_WRITE, 1, 1000, 1001, page, 4096)); break;
		case 6: assert(swapz_byte_begin(collector, SWAPZ_BYTE_WRITE, 1, 1, 2, page, 4096)); assert(!swapz_byte_accept(collector, 1, 2, 1, 4, 5)); break;
		case 7: assert(swapz_byte_begin(collector, SWAPZ_BYTE_WRITE, 1, 1, 2, page, 4096)); assert(swapz_byte_accept(collector, 1, 2, 3, 4, 5)); assert(!swapz_byte_upper(collector, 1, 2, 3, 4, 6, 0)); break;
		case 8: assert(swapz_byte_begin(collector, SWAPZ_BYTE_WRITE, 1, 1, 2, page, 4096)); assert(!swapz_byte_accept(collector, 1, 2, 3, 4, 8193)); break;
		case 9: write_one(collector, 10, page); swapz_byte_invalidate(collector); break;
		}
		assert(!swapz_byte_stop(collector, join_ok, collector));
		assert(!swapz_byte_export(collector, &records, &count));
		dispose(collector);
	}
	collector = fresh();
	write_one(collector, 10, page);
	assert(!swapz_byte_stop(collector, join_ok, NULL));
	assert(!swapz_byte_release(collector));
	assert(!swapz_byte_stop(collector, join_ok, collector));
	assert(!swapz_byte_export(collector, &records, &count));
	dispose(collector);
	puts("ROUND102_BYTE_COLLECTOR_HOST PASS: immutable copies, 10 invalid cases, retained join");
}
