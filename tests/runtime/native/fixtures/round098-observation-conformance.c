/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual frozen event constructors + selected owner/adapter; host-only
 * carrier shape, lower/upper transitions, SHA, atomics and RCU primitives.
 */
#include "frozen-owner-support.inc"
#include <errno.h>

/* Only fields accessed by the extracted constructors, with original widths.
 * Not the native carrier layout or actual MM/broker lifetime proof.
 */
struct swapz_ticket_key {
	u64 area_epoch, store_sequence, slot_offset;
	u64 logical_page, dm_generation;
	u32 swap_type, length, decoded_length;
	u8 sha256[32];
	u8 representation, codec, version, dictionary;
};
struct swapz_mm_carrier {
	u8 scratch[3568];
	struct swapz_observation_record observation;
};
#include "frozen-mm-events.inc"
#include "frozen-dm-missing.inc"

static struct swapz_ticket_key key(void)
{
	struct swapz_ticket_key value = {
		.area_epoch = 13, .store_sequence = 15, .slot_offset = 7,
		.logical_page = 7, .dm_generation = 1, .swap_type = 2,
		.length = 32, .decoded_length = 4096, .representation = 90,
		.codec = 1, .version = 1,
	};
	memset(value.sha256, 7, sizeof(value.sha256));
	return value;
}

static u64 mint(void)
{
	u64 token = swapz_trial_observation_mint();
	CHECK(token != 0);
	return token;
}

static void emit(struct swapz_observation_record record)
{
	CHECK(swapz_trial_observation_append(&record));
}

static struct swapz_observation_record capture(const struct swapz_ticket_key *source)
{
	struct swapz_observation_record record = {
		.event = SWAPZ_OBS_CAPTURE, .operation = mint(),
		.operation_kind = SWAPZ_OBS_TYPED_WRITE,
		.logical = (u32)source->logical_page, .swap_type = source->swap_type,
		.slot = source->slot_offset, .area_epoch = source->area_epoch,
		.store = source->store_sequence, .generation = (u32)source->dm_generation,
		.compressed_length = source->length, .decoded_length = source->decoded_length,
		.codec = source->codec, .tag = source->representation,
		.version = source->version, .dictionary = source->dictionary,
	};
	memset(record.compressed_sha256, 6, sizeof(record.compressed_sha256));
	memcpy(record.page_sha256, source->sha256, sizeof(record.page_sha256));
	return record;
}

static bool sink(void *context, const u8 *bytes, size_t length)
{
	return fwrite(bytes, 1, length, context) == length;
}

static bool join_done(void *context)
{
	++joins;
	return *(const bool *)context;
}

static void finish(const char *path)
{
	bool joined = true;
	FILE *file;

	CHECK(swapz_trial_observation_stop(join_done, &joined));
	CHECK(!swapz_trial_observation_active());
	file = fopen(path, "wb");
	CHECK(file != NULL);
	CHECK(swapz_trial_observation_export(sink, file));
	CHECK(!fclose(file));
	CHECK(swapz_trial_observation_release());
	CHECK(allocations == 1 && frees == 1);
}

/* Exercise the *actual* R097 functions in separate captures. Each output
 * must have no invalid record retained, with sticky INVALID in its footer.
 */
static void frozen_bad(const char *mode)
{
	struct swapz_mm_carrier carrier = {0};
	struct swapz_ticket_key source = key();

	if (!strcmp(mode, "frozen-dm")) {
		swapz_round097_observe_missing_lineage();
		return;
	}
	if (!strcmp(mode, "frozen-preparation")) {
		swapz_mm_observation_capture(&carrier, &source);
		return;
	}
	carrier.observation = capture(&source);
	emit(carrier.observation);
	if (!strcmp(mode, "frozen-bind")) {
		swapz_mm_observation_bind(&carrier);
		return;
	}
	if (!strcmp(mode, "frozen-drop")) {
		swapz_mm_observation_release(&carrier);
		return;
	}
	carrier.observation.original = mint();
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_BIND, .operation = carrier.observation.operation,
		.original = carrier.observation.original,
	});
	if (!strcmp(mode, "frozen-upper"))
		swapz_mm_observation_endio(&carrier, 0);
	else if (!strcmp(mode, "frozen-release"))
		swapz_mm_observation_release(&carrier);
	else
		abort();
}

/* New positive event-specific construction; NOT actual fixed MM/DM code.
 * The independent oracle compares every byte of a deterministic host page.
 * Compressed digest and transitions are fixture inputs, not native codecs/I/O.
 */
static void clean_trace(void)
{
	struct swapz_ticket_key source = key();
	u8 expected[4096], copied[4096];
	struct swapz_observation_record captured, record;
	u64 operation, original, clone, descriptor, extent, lower, pin;
	u64 write_operation, write_original, write_descriptor;

	for (size_t index = 0; index < sizeof(expected); ++index)
		expected[index] = (u8)(index % 251U);
	memcpy(copied, expected, sizeof(copied));
	CHECK(!memcmp(expected, copied, sizeof(expected)));
	sha256(expected, sizeof(expected), source.sha256);
	captured = capture(&source);
	emit(captured);
	operation = captured.operation;
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_PREPARATION,
		.operation = operation, .flags = 1});
	original = mint();
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_BIND,
		.operation = operation, .original = original});
	clone = mint();
	descriptor = mint();
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_ACCEPT,
		.operation = operation, .operation_kind = SWAPZ_OBS_TYPED_WRITE,
		.original = original, .clone = clone, .descriptor = descriptor, .flags = 1,
		.logical = captured.logical, .swap_type = captured.swap_type,
		.slot = captured.slot, .area_epoch = captured.area_epoch,
		.store = captured.store, .generation = captured.generation});
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_PREPARATION,
		.operation = operation, .flags = 2});
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_DISPATCH,
		.operation = operation, .flags = 1});
	extent = mint();
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_RESERVE,
		.operation = operation, .extent = extent, .credit = 1});
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_CLAIM,
		.operation = operation, .descriptor = descriptor, .credit = 1});
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_PREPARATION,
		.operation = operation, .flags = 4});
	lower = mint();
	record = (struct swapz_observation_record){.event = SWAPZ_OBS_LOWER_SUBMIT,
		.operation = operation, .lower = lower, .extent = extent, .flags = 2,
		.requested = 4096, .compressed_length = captured.compressed_length};
	memcpy(record.compressed_sha256, captured.compressed_sha256, 32);
	emit(record);
	record = (struct swapz_observation_record){.event = SWAPZ_OBS_LOWER_COMPLETE,
		.operation = operation, .lower = lower, .completed = 4096};
	memcpy(record.observed_sha256, captured.compressed_sha256, 32);
	emit(record);
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_FLUSH,
		.operation = operation, .extent = extent});
	record = (struct swapz_observation_record){.event = SWAPZ_OBS_PUBLISH,
		.operation = operation, .extent = extent, .new_generation = 1, .gc_epoch = 1,
		.compressed_length = captured.compressed_length, .decoded_length = 4096,
		.codec = captured.codec, .tag = captured.tag, .version = captured.version};
	memcpy(record.compressed_sha256, captured.compressed_sha256, 32);
	memcpy(record.page_sha256, captured.page_sha256, 32);
	emit(record);
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_CLONE_ENDIO,
		.operation = operation, .descriptor = descriptor, .clone = clone});
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_UPPER_ENDIO,
		.operation = operation, .original = original});
	write_operation = operation;
	write_original = original;
	write_descriptor = descriptor;

	/* A read is a distinct operation, same authoritative source key.
	 * Deferred write debts may retire after read acceptance.
	 */
	operation = mint();
	original = mint();
	clone = mint();
	descriptor = mint();
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_ACCEPT,
		.operation = operation, .operation_kind = SWAPZ_OBS_TYPED_READ,
		.logical = captured.logical, .original = original,
		.clone = clone, .descriptor = descriptor});
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_CANDIDATE_RELEASE,
		.operation = write_operation, .descriptor = write_descriptor});
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_CARRIER_RELEASE,
		.operation = write_operation, .original = write_original});
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_DISPATCH,
		.operation = operation, .flags = 2});
	pin = mint();
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_PIN,
		.operation = operation, .pin = pin, .extent = extent, .gc_epoch = 1,
		.logical = captured.logical, .swap_type = captured.swap_type,
		.slot = captured.slot, .area_epoch = captured.area_epoch,
		.store = captured.store, .generation = captured.generation});
	lower = mint();
	record = (struct swapz_observation_record){.event = SWAPZ_OBS_LOWER_SUBMIT,
		.operation = operation, .lower = lower, .extent = extent, .flags = 1,
		.requested = 4096, .compressed_length = captured.compressed_length};
	memcpy(record.compressed_sha256, captured.compressed_sha256, 32);
	emit(record);
	record = (struct swapz_observation_record){.event = SWAPZ_OBS_LOWER_COMPLETE,
		.operation = operation, .lower = lower, .completed = 4096};
	memcpy(record.observed_sha256, captured.compressed_sha256, 32);
	emit(record);
	CHECK(!memcmp(expected, copied, sizeof(expected)));
	record = (struct swapz_observation_record){.event = SWAPZ_OBS_ORACLE,
		.operation = operation, .pin = pin, .decoded_length = 4096,
		.compared = 4096, .flags = 1};
	memcpy(record.page_sha256, source.sha256, 32);
	sha256(copied, sizeof(copied), record.observed_sha256);
	emit(record);
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_PIN_RELEASE,
		.operation = operation, .pin = pin});
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_CLONE_ENDIO,
		.operation = operation, .descriptor = descriptor, .clone = clone});
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_UPPER_ENDIO,
		.operation = operation, .original = original});

	/* Capture dropped before any original BIO exists, no invented ACK. */
	source.store_sequence++;
	record = capture(&source);
	emit(record);
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_CAPTURE_DROP,
		.operation = record.operation, .status = EOPNOTSUPP});
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_CARRIER_RELEASE,
		.operation = record.operation});
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_CLEANUP, .flags = 7});
}

/* Controller's join must finish terminal events before sealing. Deliberate
 * missing capacity while retiring a capture; no clean evidence on overflow.
 */
static bool join_terminal(void *context)
{
	const u64 operation = *(const u64 *)context;
	struct swapz_observation_record release = {
		.event = SWAPZ_OBS_CARRIER_RELEASE, .operation = operation,
	};

	++joins;
	CHECK(swapz_trial_observation_active());
	CHECK(!swapz_trial_observation_append(&release));
	return false;
}

static void terminal_overflow(const char *path)
{
	struct swapz_ticket_key source = key();
	struct swapz_observation_record record = capture(&source);

	emit(record);
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_CAPTURE_DROP,
		.operation = record.operation, .status = EOPNOTSUPP});
	CHECK(!swapz_trial_observation_stop(join_terminal, &record.operation));
	CHECK(!swapz_trial_observation_active());
	CHECK(!swapz_trial_observation_release());
	CHECK(!swapz_trial_observation_export(sink, NULL));
	/* Later join proves external debt retired, not that lost observation
	 * was recovered. The immutable footer must retain both loss flags.
	 */
	finish(path);
}

int main(int argc, char **argv)
{
	struct swapz_trial_observation_scope current = scope();

	if (argc != 3)
		return 2;
	CHECK(swapz_trial_observation_start(&current,
		!strcmp(argv[1], "terminal-overflow") ? 2U : 64U));
	if (!strcmp(argv[1], "clean"))
		clean_trace();
	else if (!strcmp(argv[1], "terminal-overflow")) {
		terminal_overflow(argv[2]);
		goto report;
	} else
		frozen_bad(argv[1]);
	finish(argv[2]);
report:
	printf("mode=%s checks=%u allocations=%u frees=%u joins=%u host_substitutes=1 auth=0\n",
		argv[1], checks, allocations, frees, joins);
	return 0;
}
