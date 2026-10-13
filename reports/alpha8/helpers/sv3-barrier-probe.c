// SPDX-License-Identifier: GPL-2.0-only
// Test-only real upper BIO probe for barriers, FUA, discard and readback.
#include <linux/bio.h>
#include <linux/blkdev.h>
#include <linux/completion.h>
#include <linux/highmem.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/atomic.h>

#define PAGE_BYTES 4096U
struct probe_op {
	struct completion done;
	struct bio *bio;
	struct page *page;
	int status;
	u64 seq;
	u32 logical;
	u32 generation;
	bool raw;
};
static char *target;
module_param(target, charp, 0400);
MODULE_PARM_DESC(target, "exact test-owned swapz3 target block node");
static atomic64_t completion_order = ATOMIC64_INIT(0);

static void fill(struct page *page, u32 logical, u32 generation, bool raw)
{
	u8 *p = kmap_local_page(page);
	u32 i;

	if (!raw) {
		memset(p, (u8)(0x31U + (logical + generation) % 47U), PAGE_BYTES);
	} else {
		u32 x = 0x7f4a7c15U ^ logical * 0x9e3779b9U ^ generation;

		for (i = 0; i < PAGE_BYTES; ++i) {
			x ^= x << 13;
			x ^= x >> 17;
			x ^= x << 5;
			p[i] = (u8)x;
		}
	}
	kunmap_local(p);
}

static bool matches(struct page *page, u32 logical, u32 generation, bool raw,
		    bool zero)
{
	u8 *p = kmap_local_page(page);
	u32 i;
	bool equal = true;

	if (zero) {
		for (i = 0; i < PAGE_BYTES; ++i)
			if (p[i]) { equal = false; break; }
	} else if (!raw) {
	u8 expected = (u8)(0x31U + (logical + generation) % 47U);

		for (i = 0; i < PAGE_BYTES; ++i)
			if (p[i] != expected) { equal = false; break; }
	} else {
		u32 x = 0x7f4a7c15U ^ logical * 0x9e3779b9U ^ generation;

		for (i = 0; i < PAGE_BYTES; ++i) {
			u8 expected;
			x ^= x << 13; x ^= x >> 17; x ^= x << 5;
			expected = (u8)x;
			if (p[i] != expected) { equal = false; break; }
		}
	}
	kunmap_local(p);
	return equal;
}

static void endio(struct bio *bio)
{
	struct probe_op *op = bio->bi_private;
	op->status = blk_status_to_errno(bio->bi_status);
	op->seq = atomic64_inc_return(&completion_order);
	bio_put(bio);
	complete(&op->done);
}

static int prepare(struct block_device *bdev, struct probe_op *op, u32 logical,
		   u32 generation, bool raw, unsigned int opf)
{
	void *address;
	unsigned int max_vecs = (opf & REQ_OP_MASK) == REQ_OP_DISCARD ? 0 : 1;

	memset(op, 0, sizeof(*op));
	init_completion(&op->done);
	op->status = -EINPROGRESS;
	op->logical = logical; op->generation = generation; op->raw = raw;
	if ((opf & REQ_OP_MASK) == REQ_OP_READ ||
	    (opf & REQ_OP_MASK) == REQ_OP_WRITE) {
		op->page = alloc_page(GFP_KERNEL);
		if (!op->page) return -ENOMEM;
		if ((opf & REQ_OP_MASK) == REQ_OP_WRITE) fill(op->page, logical, generation, raw);
	}
	op->bio = bio_alloc(bdev, max_vecs, opf, GFP_KERNEL);
	if (!op->bio) return -ENOMEM;
	op->bio->bi_iter.bi_sector = (sector_t)logical * 8U;
	op->bio->bi_private = op;
	op->bio->bi_end_io = endio;
	if ((opf & REQ_OP_MASK) == REQ_OP_DISCARD)
		op->bio->bi_iter.bi_size = PAGE_BYTES;
	else if (!((opf & REQ_OP_MASK) == REQ_OP_WRITE &&
		   (opf & REQ_PREFLUSH) && !bio_sectors(op->bio))) {
		address = page_address(op->page);
		if (!address || bio_add_page(op->bio, op->page, PAGE_BYTES, 0) != PAGE_BYTES)
			return -EIO;
	}
	return 0;
}

static void release(struct probe_op *op)
{
	if (op->bio) bio_put(op->bio);
	if (op->page) __free_page(op->page);
	op->bio = NULL; op->page = NULL;
}

static int wait(struct probe_op *op, const char *label)
{
	unsigned long waited = wait_for_completion_timeout(&op->done, 60 * HZ);
	if (!waited) {
		pr_err("SV3BAR timeout label=%s logical=%u; retaining BIO/page until completion\n", label, op->logical);
		wait_for_completion(&op->done);
	}
	pr_info("SV3BAR completion label=%s logical=%u status=%d seq=%llu\n",
		label, op->logical, op->status, op->seq);
	return op->status;
}

static int submit_wait(struct block_device *bdev, u32 logical, u32 generation,
		       bool raw, unsigned int opf, bool zero)
{
	struct probe_op op;
	int error = prepare(bdev, &op, logical, generation, raw, opf);
	if (error) { release(&op); return error; }
	submit_bio(op.bio); op.bio = NULL;
	error = wait(&op, "single");
	if (!error && (opf & REQ_OP_MASK) == REQ_OP_READ &&
	    !matches(op.page, logical, generation, raw, zero)) error = -EBADMSG;
	release(&op);
	return error;
}

static int run(struct block_device *bdev)
{
	struct probe_op pair[2], flush, fua, discard;
	int error = 0;
	u64 old_seq;

	/* Pending compressed+raw writes must complete before empty PREFLUSH. */
	if (prepare(bdev, &pair[0], 0, 1, false, REQ_OP_WRITE) ||
	    prepare(bdev, &pair[1], 1, 1, true, REQ_OP_WRITE)) return -ENOMEM;
	submit_bio(pair[0].bio); pair[0].bio = NULL;
	submit_bio(pair[1].bio); pair[1].bio = NULL;
	if (prepare(bdev, &flush, 0, 0, false, REQ_OP_WRITE | REQ_PREFLUSH)) return -ENOMEM;
	pr_info("SV3BAR submit zero-sector WRITE|PREFLUSH logical=0 sectors=%u\n", bio_sectors(flush.bio));
	submit_bio(flush.bio); flush.bio = NULL;
	if (wait(&flush, "preflush")) error++;
	if (wait(&pair[0], "preflush-prior-compressed")) error++;
	if (wait(&pair[1], "preflush-prior-raw")) error++;
	if (!(flush.seq > pair[0].seq && flush.seq > pair[1].seq)) error++;
	if (submit_wait(bdev, 0, 1, false, REQ_OP_READ, false) ||
	    submit_wait(bdev, 1, 1, true, REQ_OP_READ, false)) error++;

	/* A compressed pending write followed by a real upper FUA BIO. */
	if (prepare(bdev, &pair[0], 2, 1, false, REQ_OP_WRITE) ||
	    prepare(bdev, &fua, 3, 2, true, REQ_OP_WRITE | REQ_FUA)) return -ENOMEM;
	submit_bio(pair[0].bio); pair[0].bio = NULL;
	pr_info("SV3BAR submit upper WRITE|FUA logical=3 bytes=%u\n", PAGE_BYTES);
	submit_bio(fua.bio); fua.bio = NULL;
	if (wait(&fua, "mixed-window-fua-raw")) error++;
	if (wait(&pair[0], "fua-prior-compressed")) error++;
	if (!(fua.seq > pair[0].seq)) error++;
	if (submit_wait(bdev, 2, 1, false, REQ_OP_READ, false) ||
	    submit_wait(bdev, 3, 2, true, REQ_OP_READ, false)) error++;

	/* Separate compressed and raw FUA writes. */
	if (submit_wait(bdev, 4, 2, false, REQ_OP_WRITE | REQ_FUA, false)) error++;
	if (submit_wait(bdev, 5, 2, true, REQ_OP_WRITE | REQ_FUA, false)) error++;
	if (submit_wait(bdev, 4, 2, false, REQ_OP_READ, false) ||
	    submit_wait(bdev, 5, 2, true, REQ_OP_READ, false)) error++;

	/* Same-page discard must drain the pending write before invalidation. */
	if (prepare(bdev, &pair[0], 6, 1, false, REQ_OP_WRITE) ||
	    prepare(bdev, &discard, 6, 0, false, REQ_OP_DISCARD)) return -ENOMEM;
	submit_bio(pair[0].bio); pair[0].bio = NULL;
	pr_info("SV3BAR submit DISCARD logical=6 while prior write queued\n");
	submit_bio(discard.bio); discard.bio = NULL;
	if (wait(&discard, "same-page-discard")) error++;
	if (wait(&pair[0], "same-page-discard-prior-write")) error++;
	if (!(discard.seq > pair[0].seq)) error++;
	if (submit_wait(bdev, 6, 0, false, REQ_OP_READ, true)) error++;

	/* An unrelated discard preserves its pending neighboring write. */
	if (prepare(bdev, &pair[0], 7, 1, false, REQ_OP_WRITE) ||
	    prepare(bdev, &discard, 8, 0, false, REQ_OP_DISCARD)) return -ENOMEM;
	submit_bio(pair[0].bio); pair[0].bio = NULL;
	submit_bio(discard.bio); discard.bio = NULL;
	if (wait(&discard, "unrelated-discard")) error++;
	if (wait(&pair[0], "unrelated-discard-prior-write")) error++;
	if (submit_wait(bdev, 7, 1, false, REQ_OP_READ, false) ||
	    submit_wait(bdev, 8, 0, false, REQ_OP_READ, true)) error++;

	/* Two compressed siblings share a window; discarding one preserves the other. */
	if (prepare(bdev, &pair[0], 9, 1, false, REQ_OP_WRITE) ||
	    prepare(bdev, &pair[1], 10, 1, false, REQ_OP_WRITE)) return -ENOMEM;
	submit_bio(pair[0].bio); pair[0].bio = NULL;
	submit_bio(pair[1].bio); pair[1].bio = NULL;
	if (wait(&pair[0], "shared-sibling-9") || wait(&pair[1], "shared-sibling-10")) error++;
	if (prepare(bdev, &discard, 9, 0, false, REQ_OP_DISCARD)) return -ENOMEM;
	submit_bio(discard.bio); discard.bio = NULL;
	if (wait(&discard, "shared-sibling-discard")) error++;
	if (submit_wait(bdev, 9, 0, false, REQ_OP_READ, true) ||
	    submit_wait(bdev, 10, 1, false, REQ_OP_READ, false)) error++;

	pr_info("SV3BAR result errors=%d\n", error);
	(void)old_seq;
	return error ? -EIO : 0;
}

static int __init probe_init(void)
{
	struct file *file;
	int error;
	if (!target) return -EINVAL;
	file = bdev_file_open_by_path(target, BLK_OPEN_READ | BLK_OPEN_WRITE,
				      THIS_MODULE, NULL);
	if (IS_ERR(file)) return PTR_ERR(file);
	pr_info("SV3BAR begin target=%s\n", target);
	error = run(file_bdev(file));
	fput(file);
	return error;
}
static void __exit probe_exit(void) { pr_info("SV3BAR unload\n"); }
module_init(probe_init);
module_exit(probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Test-only upper FUA/PREFLUSH/discard ordering probe");
