// SPDX-License-Identifier: GPL-2.0-only
/* Rootless counterfactual only: no source authentication or lower I/O. */
#define _POSIX_C_SOURCE 200809L
#include "codec.h"
#include "predictor-route.h"
#include <linux/lzo.h>
#include <lz4.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <inttypes.h>

typedef uint8_t u8;
typedef uint64_t u64;
enum { PAGE = 4096, SHARED_COUNT = 192, COUNT = 224, PAIRS = 20, CAP = 8192 };
enum original_codec { ORIGINAL_LZ4 = 1, ORIGINAL_LZO1X = 2 };
enum category { ZERO, SAME, RANDOM, REPEATED, STRUCTURED, MIXED, PATTERN512, CATEGORIES };
struct source {
    u8 page[PAGE], compressed[CAP];
    unsigned int length;
    enum category category;
    bool eligible;
};
struct record {
    u8 bytes[PAGE], encoding;
    unsigned int length;
    swapz_u32 crc;
    bool raw, zero;
    enum original_codec original_codec; /* meaningful only for preserved bytes */
};
static struct source corpus[COUNT];
static struct record records[2][COUNT];
static u8 readback[COUNT][PAGE], plain[PAGE], transform[PAGE], candidate_compression_buffer[PAGE], inverse[PAGE];
static unsigned int selected[COUNT], selected_count;
static void *lz4_memory, *lzo_memory;

#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "ROUND111_CODEC_FIRST_ERROR line=%d check=%s\n", __LINE__, #condition); \
    exit(EXIT_FAILURE); } } while (0)

static uint64_t clock_ns(clockid_t clock)
{
    struct timespec stamp;
    CHECK(clock_gettime(clock, &stamp) == 0);
    return (uint64_t)stamp.tv_sec * UINT64_C(1000000000) + (uint64_t)stamp.tv_nsec;
}
static u64 ktime_get_ns(void) { return clock_ns(CLOCK_MONOTONIC); }
static u64 swapz_elapsed_ns(u64 start, u64 end) { return end >= start ? end - start : 0; }
static int host_lz4_fast(const u8 *input, u8 *output, int length,
                         int capacity, int acceleration, void *memory)
{
    return LZ4_compress_fast_extState(memory, (const char *)input,
                                    (char *)output, length, capacity, acceleration);
}
static int host_lz4_default(const u8 *input, u8 *output, unsigned int length,
                            unsigned int capacity, void *memory)
{
    CHECK(length <= CAP && capacity <= CAP);
    return host_lz4_fast(input, output, (int)length, (int)capacity, 1, memory);
}
/* Unchanged original wrapper bodies; narrow upstream signed/width diagnostics. */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wconversion"
#pragma GCC diagnostic ignored "-Wsign-conversion"
#define LZ4_compress_default host_lz4_default
#include "round052-original-crypto-lz4-extracted.inc"
#undef LZ4_compress_default
#include "round056-original-crypto-lzo-wrapper.inc"
#pragma GCC diagnostic pop

/* Only the two policy fields consumed by the verbatim production function. */
struct swapz_dm { bool delta64_rescue_enabled; int delta64_lz4_acceleration; };
#define LZ4_compress_fast host_lz4_fast
#include "ordinary-extracted.inc"
#undef LZ4_compress_fast

/* Match production accumulated counters; inspect outside timed batches. */
static struct swapz_delta64_stats ordinary_stats;
static u64 ordinary_lz4_wall_ns;

static uint32_t next_random(uint32_t *state)
{
    uint32_t value = *state;
    value ^= value << 13; value ^= value >> 17; value ^= value << 5;
    return *state = value;
}
static void generate(void)
{
    uint32_t state = UINT32_C(0x31415926);
    for (unsigned int index = 0; index < COUNT; ++index) {
        struct source *source = &corpus[index];
        source->category = index < SHARED_COUNT ? (enum category)(index % PATTERN512) : PATTERN512;
        for (unsigned int offset = 0; offset < PAGE; ++offset) {
            u8 random_byte = (u8)next_random(&state);
            switch (source->category) {
            case ZERO: source->page[offset] = 0; break;
            case SAME: source->page[offset] = (u8)(index + 1U); break;
            case RANDOM: source->page[offset] = random_byte; break;
            case REPEATED: source->page[offset] = offset < 512U + index * 8U ?
                random_byte : source->page[offset % 512U]; break;
            case STRUCTURED: {
                uint64_t word = UINT64_C(0x1234567800000000) + index * 512U + offset / 8U;
                source->page[offset] = (u8)(word >> ((offset % 8U) * 8U));
                break;
            }
            case MIXED: source->page[offset] = offset < 2048U + index * 8U ?
                random_byte : 0; break;
            case PATTERN512: source->page[offset] = offset >= 512U ? source->page[offset % 512U] :
                offset < 2U ? (u8)offset : random_byte; break;
            default: CHECK(false);
            }
        }
    }
}
static void original_decode(enum original_codec codec, const u8 *input,
                            unsigned int length, u8 *output)
{
    CHECK(length > 0 && length <= CAP);
    if (codec == ORIGINAL_LZ4) {
        CHECK(LZ4_decompress_safe((const char *)input, (char *)output,
                                  (int)length, PAGE) == PAGE);
    } else {
        unsigned int output_length = PAGE;
        CHECK(codec == ORIGINAL_LZO1X);
        CHECK(__lzo_decompress(input, length, output, &output_length) == 0);
        CHECK(output_length == PAGE);
    }
}
static void ordinary_write(const u8 *page, struct record *record)
{
    struct swapz_dm ctx = { true, SWAPZ_LZ4_DELTA64_ACCELERATION_DEFAULT };
    record->original_codec = 0;
    int length = swapz_compress_page(&ctx, page, record->bytes, transform,
                                    candidate_compression_buffer, lz4_memory, &ordinary_lz4_wall_ns,
                                    &record->encoding, &ordinary_stats, &record->zero);
    CHECK(length >= 0 && length <= (int)SWAPZ_MAX_COMPRESSED);
    CHECK(!record->zero || length > 0);
    record->raw = !record->zero && length == 0;
    if (record->zero) {
        record->length = 0;
    } else if (record->raw) {
        record->length = PAGE;
        memcpy(record->bytes, page, PAGE);
    } else {
        record->length = (unsigned int)length;
    }
    record->crc = swapz_crc32c_bytes(record->bytes, record->length);
}
/* Separate the actual decoder/inverse from the inclusive CRC-checked read. */
static void ordinary_decode(const struct record *record, u8 *output)
{
    CHECK(record->original_codec == 0);
    if (record->zero) {
        CHECK(!record->raw && record->length == 0);
        memset(output, 0, PAGE);
    } else if (record->raw) {
        CHECK(record->length == PAGE);
        memcpy(output, record->bytes, PAGE);
    } else if (record->encoding == SWAPZ_ENCODING_LZ4) {
        CHECK(record->length >= 1U && record->length <= SWAPZ_MAX_COMPRESSED);
        CHECK(LZ4_decompress_safe((const char *)record->bytes, (char *)output,
                                  (int)record->length, PAGE) == PAGE);
    } else {
        CHECK(record->encoding == SWAPZ_ENCODING_DELTA64_SHUF8);
        CHECK(record->length >= 1U && record->length <= SWAPZ_MAX_COMPRESSED);
        CHECK(LZ4_decompress_safe((const char *)record->bytes, (char *)inverse,
                                  (int)record->length, PAGE) == PAGE);
        swapz_unpredict_delta64_shuf8(inverse, transform, output);
    }
}
static void ordinary_read(const struct record *record, u8 *output)
{
    CHECK(record->crc == swapz_crc32c_bytes(record->bytes, record->length));
    ordinary_decode(record, output);
}
static void preserve_write(enum original_codec codec, const struct source *source,
                           struct record *record)
{
    /* Original namespace is deliberately external, never a disk encoding. */
    CHECK(source->length >= 1U && source->length <= SWAPZ_MAX_COMPRESSED);
    CHECK(codec == ORIGINAL_LZ4 || codec == ORIGINAL_LZO1X);
    record->raw = false;
    record->zero = false;
    record->original_codec = codec;
    record->encoding = SWAPZ_ENCODING_INVALID;
    record->length = source->length;
    memcpy(record->bytes, source->compressed, source->length);
    record->crc = swapz_crc32c_bytes(record->bytes, record->length);
}
static void preserve_read(enum original_codec codec, const struct record *record, u8 *output)
{
    CHECK(record->encoding == SWAPZ_ENCODING_INVALID && !record->raw && !record->zero);
    CHECK(record->original_codec == codec);
    CHECK(record->length >= 1U && record->length <= SWAPZ_MAX_COMPRESSED);
    CHECK(record->crc == swapz_crc32c_bytes(record->bytes, record->length));
    original_decode(record->original_codec, record->bytes, record->length, output);
}
static uint64_t pack_model(unsigned int arm, unsigned int capacity)
{
    uint64_t total = 0;
    unsigned int occupied = 0, count = 0;
    for (unsigned int index = 0; index < selected_count; ++index) {
        const struct record *record = &records[arm][selected[index]];
        if (record->zero) continue;
        if (record->raw) { total += PAGE; continue; }
        if (count == SWAPZ_MAX_RECORDS || occupied + record->length > capacity) {
            total += capacity; occupied = count = 0;
        }
        occupied += record->length; ++count;
    }
    return total + (occupied ? capacity : 0U);
}
/* Exercise the actual planner/builder/read on compatible ordinary records.
 * The opaque original namespace is refused by the ordinary builder. */
static uint64_t production_pack(void)
{
    struct swapz_compressed_page pages[SWAPZ_MAX_RECORDS];
    swapz_u8 classes[SWAPZ_MAX_RECORDS], takes[SWAPZ_MAX_RECORDS], extent_count;
    struct swapz_decoded descriptors[SWAPZ_MAX_RECORDS];
    struct swapz_ram_extent builder;
    u8 extent[SWAPZ_MAX_EXTENT_BYTES];
    uint64_t total = 0;
    unsigned int cursor = 0;
    while (cursor < selected_count) {
        swapz_u8 count = 0;
        while (cursor < selected_count && count < SWAPZ_MAX_RECORDS) {
            unsigned int logical = selected[cursor++];
            const struct record *record = &records[0][logical];
            if (record->zero) continue;
            if (record->raw) { total += PAGE; continue; }
            pages[count++] = (struct swapz_compressed_page){
                .logical_page = logical, .payload = record->bytes,
                .length = (swapz_u16)record->length, .encoding = record->encoding };
        }
        if (!count) continue;
        CHECK(swapz_engine_plan_bounded(pages, count, 0, classes, takes, &extent_count) == 0);
        unsigned int position = 0;
        for (unsigned int extent_index = 0; extent_index < extent_count; ++extent_index) {
            unsigned int bytes = (unsigned int)classes[extent_index] * PAGE;
            CHECK(swapz_ram_extent_begin(&builder, extent, bytes, 1, descriptors,
                                         takes[extent_index]) == 0);
            for (unsigned int entry = 0; entry < takes[extent_index]; ++entry) {
                const struct swapz_compressed_page *page = &pages[position + entry];
                CHECK(swapz_ram_extent_append(&builder, page->logical_page, 1,
                                              page->payload, page->length, page->encoding) == 0);
            }
            CHECK(swapz_ram_extent_seal(&builder) == 0);
            for (unsigned int entry = 0; entry < takes[extent_index]; ++entry) {
                const struct swapz_compressed_page *page = &pages[position + entry];
                const u8 *payload = NULL;
                CHECK(swapz_ram_extent_read(&builder, (swapz_u8)entry, page->logical_page,
                                            1, &payload) == 0);
                CHECK(memcmp(payload, page->payload, page->length) == 0);
                struct record restored = records[0][page->logical_page];
                memcpy(restored.bytes, payload, restored.length);
                ordinary_read(&restored, plain);
                CHECK(memcmp(plain, corpus[page->logical_page].page, PAGE) == 0);
            }
            position += takes[extent_index]; total += bytes;
        }
        CHECK(position == count);
    }
    CHECK(swapz_ram_extent_begin(&builder, extent, PAGE, 1, descriptors, 1) == 0);
    CHECK(swapz_ram_extent_append(&builder, 1, 1, records[1][selected[0]].bytes,
                                  (swapz_u16)records[1][selected[0]].length,
                                  SWAPZ_ENCODING_INVALID) == -EINVAL);
    CHECK(builder.count == 0 && builder.payload_start == PAGE);
    return total;
}
static void run_arm(enum original_codec codec, unsigned int arm, uint64_t *write, uint64_t *read)
{
    if (arm == 0) {
        memset(&ordinary_stats, 0, sizeof(ordinary_stats));
        ordinary_lz4_wall_ns = 0;
    }
    uint64_t start = clock_ns(CLOCK_THREAD_CPUTIME_ID);
    for (unsigned int index = 0; index < selected_count; ++index) {
        unsigned int logical = selected[index];
        const struct source *source = &corpus[logical];
        if (arm == 0) {
            original_decode(codec, source->compressed, source->length, plain);
            ordinary_write(plain, &records[arm][logical]);
        } else {
            preserve_write(codec, source, &records[arm][logical]);
        }
    }
    *write = clock_ns(CLOCK_THREAD_CPUTIME_ID) - start;
    start = clock_ns(CLOCK_THREAD_CPUTIME_ID);
    for (unsigned int index = 0; index < selected_count; ++index) {
        unsigned int logical = selected[index];
        if (arm == 0) ordinary_read(&records[arm][logical], readback[logical]);
        else preserve_read(codec, &records[arm][logical], readback[logical]);
    }
    *read = clock_ns(CLOCK_THREAD_CPUTIME_ID) - start;
    /* Consume every output and the immutable payload outside the timer. */
    for (unsigned int index = 0; index < selected_count; ++index) {
        unsigned int logical = selected[index];
        CHECK(memcmp(readback[logical], corpus[logical].page, PAGE) == 0);
        if (arm == 1) {
            CHECK(records[arm][logical].length == corpus[logical].length);
            CHECK(memcmp(records[arm][logical].bytes, corpus[logical].compressed,
                         corpus[logical].length) == 0);
        }
    }
}
/* Independent micro-batches: same selected logical IDs and output footprint.
 * Payload operations use each arm's actual length; no timer subtraction.
 * A compiler barrier is shared by all operations, including the empty control.
 */
enum micro_op {
    MICRO_EMPTY, MICRO_ORIGINAL_DECODE, MICRO_ORDINARY_DECODE,
    MICRO_ORDINARY_CRC, MICRO_PRESERVE_CRC, MICRO_ORDINARY_COPY,
    MICRO_PRESERVE_COPY, MICRO_CLOCK_SCORE, MICRO_INVERSE, MICRO_COUNT
};
static u8 inverse_input[COUNT][PAGE];
static swapz_u32 micro_crc[COUNT], micro_scores[COUNT];
static unsigned int inverse_count;
static volatile u64 micro_wall_sink;

static void prepare_micro(void)
{
    inverse_count = 0;
    for (unsigned int index = 0; index < selected_count; ++index) {
        unsigned int logical = selected[index];
        const struct record *record = &records[0][logical];
        micro_scores[logical] = swapz_predict_delta64_sample_score(corpus[logical].page);
        if (!record->raw && !record->zero && record->encoding == SWAPZ_ENCODING_DELTA64_SHUF8) {
            CHECK(LZ4_decompress_safe((const char *)record->bytes, (char *)inverse_input[logical],
                                      (int)record->length, PAGE) == PAGE);
            ++inverse_count;
        }
    }
}

static uint64_t micro_batch(enum original_codec codec, enum micro_op operation)
{
    if (operation == MICRO_INVERSE && !inverse_count) return 0;
    struct swapz_delta64_stats micro_stats = {0};
    u64 wall_total = 0;
    uint64_t start = clock_ns(CLOCK_THREAD_CPUTIME_ID);
    for (unsigned int index = 0; index < selected_count; ++index) {
        unsigned int logical = selected[index];
        const struct record *ordinary_record = &records[0][logical];
        const struct record *preserved_record = &records[1][logical];
        __asm__ volatile("" : : "r"(logical) : "memory");
        switch (operation) {
        case MICRO_EMPTY: break;
        case MICRO_ORIGINAL_DECODE:
            original_decode(codec, preserved_record->bytes, preserved_record->length, readback[logical]);
            break;
        case MICRO_ORDINARY_DECODE:
            ordinary_decode(ordinary_record, readback[logical]);
            break;
        case MICRO_ORDINARY_CRC:
            micro_crc[logical] = swapz_crc32c_bytes(ordinary_record->bytes, ordinary_record->length);
            break;
        case MICRO_PRESERVE_CRC:
            micro_crc[logical] = swapz_crc32c_bytes(preserved_record->bytes, preserved_record->length);
            break;
        case MICRO_ORDINARY_COPY:
            memcpy(readback[logical], ordinary_record->bytes, ordinary_record->length);
            break;
        case MICRO_PRESERVE_COPY:
            memcpy(readback[logical], preserved_record->bytes, preserved_record->length);
            break;
        case MICRO_CLOCK_SCORE: {
            u64 wall_start = ktime_get_ns();
            u64 wall_end = ktime_get_ns();
            wall_total += swapz_elapsed_ns(wall_start, wall_end);
            swapz_delta64_note_score(&micro_stats, micro_scores[logical]);
            break;
        }
        case MICRO_INVERSE:
            if (!ordinary_record->raw && !ordinary_record->zero &&
                ordinary_record->encoding == SWAPZ_ENCODING_DELTA64_SHUF8)
                swapz_unpredict_delta64_shuf8(inverse_input[logical], transform, readback[logical]);
            break;
        default: CHECK(false);
        }
    }
    uint64_t elapsed = clock_ns(CLOCK_THREAD_CPUTIME_ID) - start;
    /* Consume and validate all outputs after stopping the batch timer. */
    for (unsigned int index = 0; index < selected_count; ++index) {
        unsigned int logical = selected[index];
        const struct record *ordinary_record = &records[0][logical];
        const struct record *preserved_record = &records[1][logical];
        switch (operation) {
        case MICRO_ORIGINAL_DECODE: case MICRO_ORDINARY_DECODE:
            CHECK(memcmp(readback[logical], corpus[logical].page, PAGE) == 0);
            break;
        case MICRO_ORDINARY_CRC:
            CHECK(micro_crc[logical] == ordinary_record->crc);
            break;
        case MICRO_PRESERVE_CRC:
            CHECK(micro_crc[logical] == preserved_record->crc);
            break;
        case MICRO_ORDINARY_COPY:
            CHECK(memcmp(readback[logical], ordinary_record->bytes, ordinary_record->length) == 0);
            break;
        case MICRO_PRESERVE_COPY:
            CHECK(memcmp(readback[logical], preserved_record->bytes, preserved_record->length) == 0);
            break;
        case MICRO_INVERSE:
            if (!ordinary_record->raw && !ordinary_record->zero &&
                ordinary_record->encoding == SWAPZ_ENCODING_DELTA64_SHUF8)
                CHECK(memcmp(readback[logical], corpus[logical].page, PAGE) == 0);
            break;
        case MICRO_EMPTY: case MICRO_CLOCK_SCORE: break;
        default: CHECK(false);
        }
    }
    if (operation == MICRO_CLOCK_SCORE) {
        CHECK(micro_stats.score_0_7 + micro_stats.score_8_15 +
              micro_stats.score_16_23 + micro_stats.score_ge24 == selected_count);
        micro_wall_sink = wall_total;
    }
    return elapsed;
}

static void report_case(enum original_codec codec, int stratum)
{
    unsigned int category_counts[CATEGORIES] = {0}, eligible_counts[CATEGORIES] = {0};
    unsigned int total_pages = 0, too_large = 0, unsupported = 0;
    unsigned int page_ids[COUNT];
    uint64_t payload[2] = {0}, bins[2][5] = {{0}}, raw[2] = {0};
    selected_count = 0;
    memset(&ordinary_stats, 0, sizeof(ordinary_stats));
    ordinary_lz4_wall_ns = 0;
    for (unsigned int logical = 0; logical < COUNT; ++logical) {
        const struct source *source = &corpus[logical];
        if (stratum < 0 ? logical >= SHARED_COUNT : (int)source->category != stratum)
            continue;
        page_ids[total_pages++] = logical;
        ++category_counts[source->category];
        if (source->eligible) {
            selected[selected_count++] = logical;
            ++eligible_counts[source->category];
        } else if (logical == SHARED_COUNT - 1U) {
            ++unsupported;
        } else if (source->category != ZERO && source->category != SAME) {
            ++too_large;
        }
    }
    CHECK(total_pages > 0);
    uint64_t write[2], read[2];
    if (selected_count) {
        for (unsigned int warmup = 0; warmup < 3; ++warmup) {
            run_arm(codec, warmup % 2U, &write[warmup % 2U], &read[warmup % 2U]);
            run_arm(codec, 1U - warmup % 2U, &write[1U - warmup % 2U], &read[1U - warmup % 2U]);
        }
    }
    printf("{\"codec\":%d,\"stratum\":%d,\"pages\":%u,\"eligible\":%u,\"zero\":%u,\"same\":%u,"
           "\"over_cap\":%u,\"unsupported_control\":%u,\"category_counts\":[",
           (int)codec, stratum, total_pages, selected_count, category_counts[ZERO], category_counts[SAME], too_large, unsupported);
    for (unsigned int i = 0; i < CATEGORIES; ++i) printf("%s%u", i ? "," : "", category_counts[i]);
    printf("],\"eligible_by_category\":[");
    for (unsigned int i = 0; i < CATEGORIES; ++i) printf("%s%u", i ? "," : "", eligible_counts[i]);
    printf("],\"pairs\":[");
    if (selected_count) {
        for (unsigned int pair = 0; pair < PAIRS; ++pair) {
            unsigned int first = pair % 2U, second = 1U - first;
            run_arm(codec, first, &write[first], &read[first]);
            run_arm(codec, second, &write[second], &read[second]);
            printf("%s[%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]",
                   pair ? "," : "", write[0], read[0], write[1], read[1]);
        }
    }
    for (unsigned int arm = 0; arm < 2; ++arm) {
        for (unsigned int index = 0; index < selected_count; ++index) {
            const struct record *record = &records[arm][selected[index]];
            unsigned int length = record->length;
            payload[arm] += length;
            bins[arm][length <= 512U ? 0 : length <= 1024U ? 1 :
                      length <= 2048U ? 2 : length <= 3568U ? 3 : 4]++;
            raw[arm] += record->raw;
        }
    }
    uint64_t packed = selected_count ? production_pack() : 0;
    printf("],\"payload_bytes\":[%" PRIu64 ",%" PRIu64 "],"
           "\"ordinary_raw_pages\":%" PRIu64 ",\"preserve_copy_bytes\":%" PRIu64 ","
           "\"ordinary_raw_copy_bytes\":%" PRIu64 ",\"ordinary_actual_planner_bytes\":%" PRIu64 ","
           "\"size_bins\":[", payload[0], payload[1], raw[0], payload[1], raw[0]*PAGE, packed);
    for (unsigned int arm = 0; arm < 2; ++arm) {
        printf("%s[", arm ? "," : "");
        for (unsigned int i = 0; i < 5; ++i) printf("%s%" PRIu64, i ? "," : "", bins[arm][i]);
        printf("]");
    }
    printf("],\"ordinary_last_batch_profile\":{\"lz4_wall_ns\":%" PRIu64
           ",\"rescue_wall_ns\":%" PRIu64 ",\"transform_calls\":%" PRIu64
           ",\"adopted\":%" PRIu64 "},\"fixed_class_model_bytes\":[",
           ordinary_lz4_wall_ns, ordinary_stats.wall_ns, ordinary_stats.transform_calls,
           ordinary_stats.adopted);
    for (unsigned int arm = 0; arm < 2; ++arm)
        printf("%s[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]", arm ? "," : "",
               pack_model(arm, PAGE), pack_model(arm, 2U*PAGE), pack_model(arm, 4U*PAGE));
    printf("],\"page_sizes\":[");
    /* All pages including fallback controls; original, ordinary and eligible tag. */
    for (unsigned int index = 0; index < total_pages; ++index) {
        unsigned int logical = page_ids[index];
        printf("%s[%u,%u,%u,%u]", index ? "," : "", logical, corpus[logical].length,
               records[0][logical].length, corpus[logical].eligible ? 1U : 0U);
    }
    prepare_micro();
    printf("],\"inverse_pages\":%u,\"micro_pairs\":[", inverse_count);
    if (selected_count) {
        for (unsigned int operation = 0; operation < MICRO_COUNT; ++operation)
            (void)micro_batch(codec, (enum micro_op)operation);
        for (unsigned int pair = 0; pair < PAIRS; ++pair) {
            uint64_t samples[MICRO_COUNT];
            for (unsigned int position = 0; position < MICRO_COUNT; ++position) {
                unsigned int operation = pair % 2U ? MICRO_COUNT - 1U - position : position;
                samples[operation] = micro_batch(codec, (enum micro_op)operation);
            }
            printf("%s[", pair ? "," : "");
            for (unsigned int operation = 0; operation < MICRO_COUNT; ++operation)
                printf("%s%" PRIu64, operation ? "," : "", samples[operation]);
            printf("]");
        }
    }
    puts("],\"byte_exact\":true}");
}
static void test_codec(enum original_codec codec)
{
    /* No record state inherited from the previous source codec. */
    memset(records, 0, sizeof(records));
    memset(&ordinary_stats, 0, sizeof(ordinary_stats));
    ordinary_lz4_wall_ns = 0;
    CHECK(strcmp(swapz_predictor_transform_backend_name(), "scalar") == 0);
    CHECK(strcmp(swapz_predictor_inverse_backend_name(), "scalar") == 0);
    for (unsigned int logical = 0; logical < COUNT; ++logical) {
        struct source *source = &corpus[logical];
        unsigned int length = CAP;
        int result = codec == ORIGINAL_LZ4 ?
            __lz4_compress_crypto(source->page, PAGE, source->compressed, &length, lz4_memory) :
            __lzo_compress(source->page, PAGE, source->compressed, &length, lzo_memory);
        CHECK(result == 0 && length > 0 && length <= CAP);
        source->length = length;
        original_decode(codec, source->compressed, length, plain);
        CHECK(memcmp(plain, source->page, PAGE) == 0);
        /* Preserve the R112 unsupported-profile control at its original ID. */
        source->eligible = logical != SHARED_COUNT - 1U && source->category != ZERO &&
            source->category != SAME && length <= SWAPZ_MAX_COMPRESSED;
        if (!source->eligible) {
            ordinary_write(plain, &records[0][logical]);
            ordinary_read(&records[0][logical], readback[logical]);
            CHECK(memcmp(readback[logical], source->page, PAGE) == 0);
            /* Declined arm is ordinary fallback, not opaque RAW. */
            ordinary_write(plain, &records[1][logical]);
            ordinary_read(&records[1][logical], readback[logical]);
            CHECK(memcmp(readback[logical], source->page, PAGE) == 0);
        }
    }
    report_case(codec, -1);
    for (int stratum = 0; stratum < CATEGORIES; ++stratum)
        report_case(codec, stratum);
}
int main(void)
{
    lz4_memory = malloc((size_t)LZ4_sizeofState());
    lzo_memory = malloc(LZO1X_MEM_COMPRESS);
    CHECK(lz4_memory && lzo_memory);
    /* Default scalar implementation; no kernel SIMD transition claims. */
    generate();
    test_codec(ORIGINAL_LZ4);
    test_codec(ORIGINAL_LZO1X);
    free(lzo_memory); free(lz4_memory);
    return 0;
}
