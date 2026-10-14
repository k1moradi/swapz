/* SPDX-License-Identifier: GPL-2.0-only */
/* Deterministic rootless property and failure test for the exact V3 engine C. */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "engine.h"

#define LOGICAL_PAGES 128U
#define PHYSICAL_BLOCKS 4096U
#define ITERATIONS_PER_CAP 100U
#define CHECK(condition) do { \
	if (!(condition)) { \
		fprintf(stderr, "FAIL line=%d expression=%s\n", __LINE__, \
			#condition); \
		return 1; \
	} \
} while (0)

struct memory_disk {
	sv3_u8 *bytes;
	sv3_u32 write_calls;
	sv3_u32 write_blocks;
	sv3_u32 read_blocks;
	sv3_u32 fail_on;
};

static struct sv3_authority authority;
static struct sv3_map maps[LOGICAL_PAGES];
static sv3_u16 live[PHYSICAL_BLOCKS];
static sv3_u8 classes[PHYSICAL_BLOCKS];
static sv3_u8 write_scratch[SV3_MAX_EXTENT_BYTES];
static sv3_u8 read_scratch[SV3_MAX_EXTENT_BYTES];
static sv3_u8 data_store[SV3_MAX_RECORDS][SV3_MAX_COMPRESSED];
static sv3_u8 output[SV3_MAX_COMPRESSED];
static sv3_u8 reference[LOGICAL_PAGES][SV3_MAX_COMPRESSED];
static sv3_u16 reference_length[LOGICAL_PAGES];
static int reference_valid[LOGICAL_PAGES];
static struct sv3_compressed_page pages[SV3_MAX_RECORDS];
static struct sv3_engine engine;
static struct memory_disk disk;
static uint32_t random_state = 0x0d3a5eedU;

static uint32_t next_random(void)
{
	random_state ^= random_state << 13;
	random_state ^= random_state >> 17;
	random_state ^= random_state << 5;
	return random_state;
}

static int lower_write(void *opaque, sv3_u32 start, sv3_u8 blocks,
		       const sv3_u8 *source, sv3_u8 *completed)
{
	struct memory_disk *memory = opaque;
	sv3_u8 written = blocks;

	*completed = 0;
	if (start >= PHYSICAL_BLOCKS || blocks > PHYSICAL_BLOCKS - start)
		return -ERANGE;
	memory->write_calls++;
	if (memory->write_calls == memory->fail_on)
		written = blocks > 1 ? 1 : 0;
	if (written) {
		memcpy(memory->bytes + (size_t)start * SV3_BLOCK_BYTES, source,
		       (size_t)written * SV3_BLOCK_BYTES);
		memory->write_blocks += written;
		*completed = written;
	}
	return written == blocks ? 0 : -EIO;
}

static int lower_read(void *opaque, sv3_u32 start, sv3_u8 blocks,
		      sv3_u8 *destination)
{
	struct memory_disk *memory = opaque;

	if (start >= PHYSICAL_BLOCKS || blocks > PHYSICAL_BLOCKS - start)
		return -ERANGE;
	memcpy(destination, memory->bytes + (size_t)start * SV3_BLOCK_BYTES,
	       (size_t)blocks * SV3_BLOCK_BYTES);
	memory->read_blocks += blocks;
	return 0;
}

static int initialize_engine(unsigned read_cap)
{
	memset(reference_length, 0, sizeof(reference_length));
	memset(reference_valid, 0, sizeof(reference_valid));
	disk.write_calls = 0;
	disk.write_blocks = 0;
	disk.read_blocks = 0;
	disk.fail_on = 0;
	if (sv3_authority_init(&authority, maps, live, classes,
			       LOGICAL_PAGES, PHYSICAL_BLOCKS))
		return -1;
	memset(&engine, 0, sizeof(engine));
	engine.authority = &authority;
	engine.io.opaque = &disk;
	engine.io.write_extent = lower_write;
	engine.io.read_blocks = lower_read;
	engine.write_scratch = write_scratch;
	engine.read_scratch = read_scratch;
	engine.max_read_blocks_per_record = (sv3_u8)read_cap;
	return 0;
}

static int verify_page(unsigned logical_page)
{
	sv3_u16 output_length = 0;
	int result;

	if (!reference_valid[logical_page])
		return 0;
	result = sv3_engine_read_page(&engine, logical_page, output,
				      sizeof(output), &output_length);
	if (result || output_length != reference_length[logical_page] ||
	    memcmp(output, reference[logical_page], output_length)) {
		fprintf(stderr,
			"oracle mismatch page=%u result=%d got=%u expected=%u\n",
			logical_page, result, output_length,
			reference_length[logical_page]);
		return -1;
	}
	return 0;
}

static void update_reference(const struct sv3_compressed_page *page)
{
	reference_valid[page->logical_page] = 1;
	reference_length[page->logical_page] = page->length;
	memcpy(reference[page->logical_page], page->payload, page->length);
}

int main(void)
{
	static const sv3_u16 payload_lengths[] = {
		26, 257, 512, 1048, 1055, 1590, 1600, 2072, 2082, 2200,
		2224, 3000, 3500, 3568
	};
	static const unsigned read_caps[] = {0, 1, 2, 3};
	unsigned total_records = 0;

	disk.bytes = calloc(PHYSICAL_BLOCKS, SV3_BLOCK_BYTES);
	CHECK(disk.bytes != NULL);

	for (unsigned cap_index = 0;
	     cap_index < sizeof(read_caps) / sizeof(read_caps[0]); cap_index++) {
		unsigned read_cap = read_caps[cap_index];
		unsigned generated_records = 0;

		CHECK(initialize_engine(read_cap) == 0);
		for (unsigned iteration = 0;
		     iteration < ITERATIONS_PER_CAP; iteration++) {
			unsigned count = 1U + next_random() % SV3_MAX_RECORDS;
			sv3_u8 order[LOGICAL_PAGES];
			sv3_u8 committed = 0;
			int result;

			generated_records += count;
			total_records += count;
			for (unsigned i = 0; i < LOGICAL_PAGES; i++)
				order[i] = (sv3_u8)i;
			for (unsigned i = 0; i < count; i++) {
				unsigned j = i + next_random() %
					(LOGICAL_PAGES - i);
				sv3_u8 temporary = order[i];
				order[i] = order[j];
				order[j] = temporary;
			}
			for (unsigned i = 0; i < count; i++) {
				unsigned logical_page = order[i];
				sv3_u16 length = payload_lengths[
					next_random() % (sizeof(payload_lengths) /
						       sizeof(payload_lengths[0]))];

				pages[i].logical_page = logical_page;
				pages[i].payload = data_store[i];
				pages[i].length = length;
				for (unsigned j = 0; j < length; j++)
					data_store[i][j] = (sv3_u8)next_random();
			}
			result = sv3_engine_write_window(&engine, pages,
							 (sv3_u8)count,
							 &committed);
			CHECK(result == 0);
			CHECK(committed == count);
			CHECK(!authority.in_flight);
			for (unsigned i = 0; i < count; i++) {
				update_reference(&pages[i]);
				CHECK(verify_page(pages[i].logical_page) == 0);
			}
			for (unsigned sample = 0; sample < 4; sample++)
				CHECK(verify_page(next_random() % LOGICAL_PAGES) == 0);
		}

		/* Duplicate logical IDs must occupy separate planned extents. */
		{
			sv3_u8 plan[SV3_MAX_RECORDS];
			sv3_u8 takes[SV3_MAX_RECORDS];
			sv3_u8 groups = 0;
			sv3_u8 committed = 0;

			pages[0] = (struct sv3_compressed_page) {
				.logical_page = 7,
				.payload = data_store[0],
				.length = 2072,
			};
			pages[1] = (struct sv3_compressed_page) {
				.logical_page = 7,
				.payload = data_store[1],
				.length = 2072,
			};
			memset(data_store[0], 0x31, pages[0].length);
			memset(data_store[1], 0xa7, pages[1].length);
			CHECK(sv3_engine_plan_bounded(pages, 2, (sv3_u8)read_cap,
						      plan, takes, &groups) == 0);
			CHECK(groups == 2 && takes[0] == 1);
			CHECK(sv3_engine_write_window(&engine, pages, 2,
						      &committed) == 0);
			CHECK(committed == 2);
			update_reference(&pages[1]);
			CHECK(verify_page(7) == 0);
		}

		/* A partial second extent commits only the first complete prefix. */
		{
			sv3_u8 plan[SV3_MAX_RECORDS];
			sv3_u8 takes[SV3_MAX_RECORDS];
			sv3_u8 groups = 0;
			sv3_u8 committed = 0;
			sv3_u8 prefix;
			int result;

			for (unsigned i = 0; i < 16; i++) {
				pages[i] = (struct sv3_compressed_page) {
					.logical_page = i,
					.payload = data_store[i],
					.length = 2072,
				};
				memset(data_store[i], (int)(0x40 + i), 2072);
			}
			CHECK(sv3_engine_plan_bounded(pages, 16,
						      (sv3_u8)read_cap, plan,
						      takes, &groups) == 0);
			CHECK(groups > 1);
			prefix = takes[0];
			disk.fail_on = disk.write_calls + 2;
			result = sv3_engine_write_window(&engine, pages, 16,
							 &committed);
			CHECK(result == -EIO);
			CHECK(committed == prefix);
			CHECK(!authority.in_flight);
			for (unsigned i = 0; i < 16; i++) {
				if (i < prefix)
					update_reference(&pages[i]);
				CHECK(verify_page(pages[i].logical_page) == 0);
			}
			CHECK(authority.abandoned_blocks > 0);
			disk.fail_on = 0;
		}

		printf("RANDOM_ENGINE_PASS cap=%u windows=%u generated_records=%u "
		       "writes=%u blocks=%u reads=%u next_block=%u\n",
		       read_cap, ITERATIONS_PER_CAP, generated_records,
		       disk.write_calls, disk.write_blocks, disk.read_blocks,
		       authority.next_block);
	}

	free(disk.bytes);
	printf("RANDOM_ENGINE_ALL_CAPS_PASS seed=0x0d3a5eed iterations=400 "
	       "generated_records=%u plus duplicate/fault cases records=pass\n",
	       total_records);
	return 0;
}
