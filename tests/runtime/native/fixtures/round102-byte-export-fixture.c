/* SPDX-License-Identifier: GPL-2.0-only */
/* Synthetic two-operation wire fixture only. No device or host-file opener.
 * stdout is private test input to the Python verifier, never a CI log.
 */
#include "native-observation-byte-collector.h"
#include <assert.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

static bool joined(void *context) { return context != NULL; }
static void hex_page(const unsigned char *page)
{
	unsigned int index;
	if (!page) {
		fputs("null", stdout);
		return;
	}
	putchar('"');
	for (index = 0; index < SWAPZ_BYTE_PAGE; ++index)
		printf("%02x", (unsigned int)page[index]);
	putchar('"');
}
static void emit(const struct swapz_byte_record *record)
{
	printf("{\"operation\":%" PRIu64 ",\"original\":%" PRIu64
	       ",\"clone\":%" PRIu64 ",\"descriptor\":%" PRIu64
	       ",\"pin\":%" PRIu64 ",\"accept_sequence\":%" PRIu64
	       ",\"copy_sequence\":%" PRIu64 ",\"upper_sequence\":%" PRIu64
	       ",\"user_status\":%u,\"input_page\":", record->operation, record->original,
	       record->clone, record->descriptor, record->pin, record->accept_sequence,
	       record->copy_sequence, record->upper_sequence, record->user_status);
	hex_page(record->kind == SWAPZ_BYTE_WRITE ? record->input_page : NULL);
	fputs(",\"final_copy\":", stdout);
	hex_page(record->kind == SWAPZ_BYTE_READ ? record->final_copy : NULL);
	fputs(",\"user_page\":", stdout);
	hex_page(record->kind == SWAPZ_BYTE_READ ? record->user_page : NULL);
	putchar('}');
}
int main(void)
{
	unsigned char input[SWAPZ_BYTE_PAGE], final[SWAPZ_BYTE_PAGE], user[SWAPZ_BYTE_PAGE];
	const struct swapz_byte_record *records;
	unsigned int count;
	struct swapz_byte_collector *collector = calloc(1, sizeof(*collector));
	assert(collector && swapz_byte_start(collector, 7, 4));
	assert(fread(input, 1, sizeof(input), stdin) == sizeof(input));
	assert(fread(final, 1, sizeof(final), stdin) == sizeof(final));
	assert(fread(user, 1, sizeof(user), stdin) == sizeof(user) && fgetc(stdin) == EOF);
	assert(swapz_byte_begin(collector, SWAPZ_BYTE_WRITE, 7, 1, 2, input, sizeof(input)));
	assert(swapz_byte_accept(collector, 1, 2, 3, 4, 4));
	assert(swapz_byte_clone(collector, 1, 3, 4, 14, 0));
	assert(swapz_byte_upper(collector, 1, 2, 3, 4, 15, 0));
	assert(swapz_byte_user(collector, 1, 2, 0, NULL, 0));
	assert(swapz_byte_begin(collector, SWAPZ_BYTE_READ, 7, 7, 8, NULL, 0));
	assert(swapz_byte_accept(collector, 7, 8, 9, 10, 18));
	assert(swapz_byte_pin(collector, 7, 10, 12, 20));
	assert(swapz_byte_copy(collector, 7, 10, 12, 23, final, sizeof(final)));
	assert(swapz_byte_unpin(collector, 7, 10, 12, 24));
	assert(swapz_byte_clone(collector, 7, 9, 10, 25, 0));
	assert(swapz_byte_upper(collector, 7, 8, 9, 10, 26, 0));
	assert(swapz_byte_user(collector, 7, 8, 0, user, sizeof(user)));
	assert(swapz_byte_stop(collector, joined, collector));
	assert(swapz_byte_export(collector, &records, &count) && count == 2);
	putchar('[');
	emit(&records[0]);
	putchar(',');
	emit(&records[1]);
	puts("]");
	assert(swapz_byte_release(collector));
	assert(!pthread_mutex_destroy(&collector->lock));
	free(collector);
	return ferror(stdout) ? 1 : 0;
}
