/* Round056: source-extracted pinned BIO clone operations, host scalar boundary.
 * No actual DM map, MM source slot, STORED data, or upper BIO ACK is present.
 */
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned int gfp_t;
typedef unsigned int blk_opf_t;
typedef uint64_t sector_t;
struct block_device { unsigned int identity; };
struct bio_vec { void *page; unsigned int length; unsigned int offset; };
struct bio_iter {
	sector_t bi_sector;
	unsigned int bi_size;
	unsigned int bi_idx;
	unsigned int bi_offset;
};
struct bio {
	void *bi_next;
	struct block_device *bi_bdev;
	blk_opf_t bi_opf;
	unsigned int bi_flags;
	unsigned int bi_ioprio;
	unsigned int bi_write_hint;
	unsigned int bi_write_stream;
	unsigned int bi_bvec_gap_bit;
	struct bio_iter bi_iter;
	struct bio_vec *bi_io_vec;
	void *bi_dmabuf_map;
	int __bi_remaining;
};
struct bio_set { unsigned int unused; };
enum { BIO_CLONED = 1, BIO_REMAPPED = 2 };
enum { REQ_OP_WRITE = 1, REQ_OP_ZONE_APPEND = 2 };
static unsigned int allocation_count;
static unsigned int release_count;
/* Test allocation ledger: an expected mutant failure also owns cleanup. */
static struct bio *live_bios[4];
static bool reject_next_allocation;
static bool reject_next_integrity;

static void bio_set_flag(struct bio *bio, unsigned int flag)
{
	bio->bi_flags |= (1U << flag);
}
static bool bio_flagged(const struct bio *bio, unsigned int flag)
{
	return (bio->bi_flags & (1U << flag)) != 0U;
}
static bool op_is_dmabuf(blk_opf_t operation)
{
	(void)operation;
	return false;
}
static void bio_clone_blkg_association(struct bio *clone, const struct bio *source)
{
	(void)clone;
	(void)source;
}
static int bio_crypt_clone(struct bio *clone, const struct bio *source, gfp_t flags)
{
	(void)clone; (void)source; (void)flags;
	return 0;
}
static bool bio_integrity(const struct bio *bio)
{
	(void)bio;
	return reject_next_integrity;
}
static int bio_integrity_clone(struct bio *clone, const struct bio *source,
			       gfp_t flags)
{
	(void)clone; (void)source; (void)flags;
	return -ENOMEM;
}
static void bio_associate_blkg(struct bio *bio) { (void)bio; }
static void bio_uninit(struct bio *bio) { (void)bio; }
static void atomic_set(int *destination, int value) { *destination = value; }
static void bio_init(struct bio *bio, struct block_device *device,
		     struct bio_vec *vectors, unsigned short capacity,
		     blk_opf_t operation)
{
	(void)capacity;
	memset(bio, 0, sizeof(*bio));
	bio->bi_bdev = device;
	bio->bi_opf = operation;
	bio->bi_io_vec = vectors;
	atomic_set(&bio->__bi_remaining, 1);
}
static struct bio *bio_alloc_bioset(struct block_device *device,
				    unsigned short vectors, blk_opf_t operation,
				    gfp_t flags, struct bio_set *set)
{
	struct bio *bio;
	(void)vectors; (void)flags; (void)set;
	if (reject_next_allocation) {
		reject_next_allocation = false;
		return NULL;
	}
	bio = calloc(1U, sizeof(*bio));
	if (bio) {
		bio_init(bio, device, NULL, 0U, operation);
		if (allocation_count >= sizeof(live_bios) / sizeof(live_bios[0])) {
			free(bio);
			return NULL;
		}
		live_bios[allocation_count++] = bio;
	}
	return bio;
}
static void bio_put(struct bio *bio)
{
	if (bio) {
		for (unsigned int index = 0U;
		     index < sizeof(live_bios) / sizeof(live_bios[0]); ++index)
			if (live_bios[index] == bio)
				live_bios[index] = NULL;
		release_count++;
		free(bio);
	}
}
/* Expected semantic mutant assertions must not produce a spurious LSan red. */
static void release_live_bios_after_assertion(void)
{
	for (unsigned int index = 0U;
	     index < sizeof(live_bios) / sizeof(live_bios[0]); ++index) {
		free(live_bios[index]);
		live_bios[index] = NULL;
	}
}
#define BIO_RESET_BYTES offsetof(struct bio, bi_io_vec)
/* ROUND056_EXTRACT_RESET */
/* ROUND056_EXTRACT_PRIVATE_CLONE */
/* ROUND056_EXTRACT_ALLOC_CLONE */
/* ROUND056_EXTRACT_INIT_CLONE */

struct clone_observer {
	const struct bio *clone;
	const struct bio_vec *original_vectors;
	const struct block_device *original_device;
	sector_t original_sector;
	unsigned int original_bytes;
	unsigned int terminal_count;
	unsigned int release_count;
	bool attached;
};

/* A negative host gate, NOT a real original source or target authorization. */
static bool full_original_clone(const struct clone_observer *owner,
				const struct bio *current)
{
	return owner->attached && owner->terminal_count == 0U &&
	       owner->clone == current && bio_flagged(current, BIO_CLONED) &&
	       owner->original_device == current->bi_bdev &&
	       owner->original_vectors == current->bi_io_vec &&
	       owner->original_bytes == 4096U &&
	       current->bi_iter.bi_size == 4096U &&
	       current->bi_iter.bi_sector == owner->original_sector &&
	       current->bi_iter.bi_idx == 0U &&
	       current->bi_iter.bi_offset == 0U;
}
static int terminal(struct clone_observer *owner)
{
	if (!owner->attached || owner->terminal_count)
		return -EALREADY;
	owner->terminal_count++;
	owner->release_count++;
	owner->attached = false;
	return 0;
}
#define CHECK(condition, stage) do { \
	if (!(condition)) { \
		fprintf(stderr, "ROUND056_CLONE_FIRST_ERROR stage=%s line=%d\n", \
			stage, __LINE__); \
		release_live_bios_after_assertion(); \
		return 1; \
	} \
} while (0)

int main(void)
{
	struct block_device original_device = { .identity = 7U };
	struct block_device foreign_device = { .identity = 11U };
	struct bio_vec original_vectors[1] = { { .length = 4096U } };
	struct bio original = {};
	struct bio initialized = {};
	struct bio *clone;
	struct bio_set set = {};
	struct clone_observer observer;
	unsigned int prior_release;

	bio_init(&original, &original_device, original_vectors, 1U,
		 REQ_OP_WRITE);
	original.bi_iter.bi_sector = 16U;
	original.bi_iter.bi_size = 4096U;
	clone = bio_alloc_clone(&original_device, &original, 0U, &set);
	CHECK(clone != NULL, "alloc-clone");
	CHECK(bio_flagged(clone, BIO_CLONED), "original-cloned-bit");
	CHECK(clone->bi_io_vec == original_vectors, "shared-real-bvec");
	CHECK(clone->bi_iter.bi_sector == 16U &&
	      clone->bi_iter.bi_size == 4096U, "full-real-iterator");
	CHECK(clone->bi_bdev == &original_device, "original-bdev");
	observer = (struct clone_observer) {
		.clone = clone, .original_vectors = original_vectors,
		.original_device = &original_device,
		.original_sector = 16U, .original_bytes = 4096U,
		.attached = true,
	};
	CHECK(full_original_clone(&observer, clone), "full-clone");
	clone->bi_iter.bi_size = 2048U;
	CHECK(!full_original_clone(&observer, clone), "split-invalidates");
	clone->bi_iter.bi_size = 4096U;
	clone->bi_iter.bi_sector++;
	CHECK(!full_original_clone(&observer, clone), "remap-invalidates");
	clone->bi_iter.bi_sector = 16U;
	clone->bi_iter.bi_offset = 1U;
	CHECK(!full_original_clone(&observer, clone), "trim-invalidates");
	clone->bi_iter.bi_offset = 0U;
	clone->bi_bdev = &foreign_device;
	CHECK(!full_original_clone(&observer, clone), "wrong-bdev");
	clone->bi_bdev = &original_device;
	clone->bi_io_vec = NULL;
	CHECK(!full_original_clone(&observer, clone), "wrong-vectors");
	clone->bi_io_vec = original_vectors;
	CHECK(full_original_clone(&observer, clone), "restore-full-view");
	CHECK(terminal(&observer) == 0, "one-terminal");
	CHECK(!full_original_clone(&observer, clone), "late-after-terminal");
	CHECK(terminal(&observer) == -EALREADY, "duplicate-terminal");
	CHECK(observer.terminal_count == 1U &&
	      observer.release_count == 1U, "one-release");
	bio_put(clone);

	CHECK(bio_init_clone(&original_device, &initialized, &original, 0U)
	      == 0, "init-clone");
	CHECK(bio_flagged(&initialized, BIO_CLONED) &&
	      initialized.bi_io_vec == original_vectors, "init-shared-view");
	bio_reset(&initialized, &original_device, REQ_OP_WRITE);
	CHECK(!bio_flagged(&initialized, BIO_CLONED) &&
	      initialized.bi_iter.bi_size == 0U, "reset-invalidates");
	bio_uninit(&initialized);

	reject_next_allocation = true;
	prior_release = release_count;
	CHECK(bio_alloc_clone(&original_device, &original, 0U, &set) == NULL,
	      "allocation-failure");
	CHECK(release_count == prior_release, "failure-no-double-release");
	reject_next_integrity = true;
	clone = bio_alloc_clone(&original_device, &original, 0U, &set);
	CHECK(clone == NULL, "clone-integrity-failure");
	CHECK(release_count == prior_release + 1U,
	      "clone-error-releases-allocation");
	reject_next_integrity = false;
	CHECK(allocation_count == release_count, "allocation-balanced");
	puts("ROUND056_REAL_ORIGINAL_CLONE_FRAGMENT_C_PASS");
	puts("SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED");
	return 0;
}
