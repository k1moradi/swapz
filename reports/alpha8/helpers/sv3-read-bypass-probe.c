// SPDX-License-Identifier: GPL-2.0-only
// Test-only upper BIO ordering probe for an owned swapz3/null_blk mapping.
#include <linux/bio.h>
#include <linux/blkdev.h>
#include <linux/completion.h>
#include <linux/highmem.h>
#include <linux/delay.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/atomic.h>

#define PAGE_BYTES 4096U
#define MAX_PENDING 63U
#define DISJOINT_SLOT 2048U

struct probe_op {
	struct completion done;
	struct bio *bio;
	struct page *page;
	int status;
	u64 completion_seq;
	u32 logical;
	u32 generation;
	bool raw;
};

static char *target;
static unsigned int mode;
static unsigned int count = 1;
static unsigned int expected_bypass = 1;
static unsigned int expected_read_error;
static unsigned int seed_only;
static unsigned int skip_prefill;
static unsigned int pause_before_submit_ms;
static unsigned int read_logical = DISJOINT_SLOT;
module_param(target, charp, 0400);
module_param(mode, uint, 0400);
module_param(count, uint, 0400);
module_param(expected_bypass, uint, 0400);
module_param(expected_read_error, uint, 0400);
module_param(seed_only, uint, 0400);
module_param(skip_prefill, uint, 0400);
module_param(pause_before_submit_ms, uint, 0400);
module_param(read_logical, uint, 0400);
MODULE_PARM_DESC(target, "exact test-owned DM target block node");
MODULE_PARM_DESC(mode, "0=disjoint mixed; 1=compressed; 2=raw; 3=compressed-to-raw; 4=raw-to-compressed; 5=duplicate writes");
MODULE_PARM_DESC(count, "pending writes, 1..63 (duplicate mode permits up to 4)");
MODULE_PARM_DESC(expected_bypass, "expected alpha.8 read_bypass value");
MODULE_PARM_DESC(expected_read_error, "expect the disjoint read to fail and pending writes to be rejected");
MODULE_PARM_DESC(seed_only, "write only the disjoint baseline compressed page");
MODULE_PARM_DESC(skip_prefill, "do not rewrite the disjoint baseline page");
MODULE_PARM_DESC(pause_before_submit_ms, "bounded pause before the queued write/read BIOs are submitted");
MODULE_PARM_DESC(read_logical, "disjoint baseline/read logical slot");

static atomic64_t completion_order = ATOMIC64_INIT(0);

static void fill_page(struct page *page, u32 logical, u32 generation, bool raw)
{
	u8 *p = kmap_local_page(page);
	u32 i;

	if (!raw) {
		memset(p, (u8)(0x41U + (logical + generation) % 31U), PAGE_BYTES);
	} else {
		u32 x = 0x9e3779b9U ^ (logical * 0x85ebca6bU) ^
			(generation * 0xc2b2ae35U);

		for (i = 0; i < PAGE_BYTES; ++i) {
			x ^= x << 13;
			x ^= x >> 17;
			x ^= x << 5;
			p[i] = (u8)x;
		}
	}
	kunmap_local(p);
}

static bool page_matches(struct page *page, u32 logical, u32 generation,
			 bool raw)
{
	u8 *p = kmap_local_page(page);
	u32 i;
	bool equal = true;

	if (!raw) {
		u8 value = (u8)(0x41U + (logical + generation) % 31U);

		for (i = 0; i < PAGE_BYTES; ++i)
			if (p[i] != value) {
				equal = false;
				break;
			}
	} else {
		u32 x = 0x9e3779b9U ^ (logical * 0x85ebca6bU) ^
			(generation * 0xc2b2ae35U);

		for (i = 0; i < PAGE_BYTES; ++i) {
			u8 value;

			x ^= x << 13;
			x ^= x >> 17;
			x ^= x << 5;
			value = (u8)x;
			if (p[i] != value) {
				equal = false;
				break;
			}
		}
	}
	kunmap_local(p);
	return equal;
}

static void probe_endio(struct bio *bio)
{
	struct probe_op *op = bio->bi_private;

	op->status = blk_status_to_errno(bio->bi_status);
	op->completion_seq = atomic64_inc_return(&completion_order);
	bio_put(bio);
	complete(&op->done);
}

static int prepare_op(struct block_device *bdev, struct probe_op *op,
		  u32 logical, u32 generation, bool raw, bool write)
{
	void *address;

	memset(op, 0, sizeof(*op));
	init_completion(&op->done);
	op->logical = logical;
	op->generation = generation;
	op->raw = raw;
	op->status = -EINPROGRESS;
	op->page = alloc_page(GFP_KERNEL);
	if (!op->page)
		return -ENOMEM;
	if (write)
		fill_page(op->page, logical, generation, raw);
	op->bio = bio_alloc(bdev, 1, write ? REQ_OP_WRITE : REQ_OP_READ,
			    GFP_KERNEL);
	if (!op->bio)
		return -ENOMEM;
	op->bio->bi_iter.bi_sector = (sector_t)logical * 8U;
	op->bio->bi_private = op;
	op->bio->bi_end_io = probe_endio;
	address = page_address(op->page);
	if (!address || bio_add_page(op->bio, op->page, PAGE_BYTES, 0) != PAGE_BYTES)
		return -EIO;
	return 0;
}

static void release_op(struct probe_op *op)
{
	if (op->bio)
		bio_put(op->bio);
	if (op->page)
		__free_page(op->page);
	op->bio = NULL;
	op->page = NULL;
}

static int wait_op(struct probe_op *op, const char *kind, u32 index)
{
	unsigned long waited = wait_for_completion_timeout(&op->done, 60 * HZ);

	if (!waited) {
		pr_err("SV3BYPASS timeout kind=%s index=%u; retain BIO/page until completion\n",
		       kind, index);
		wait_for_completion(&op->done);
	}
	return op->status;
}

static bool mode_old_raw(void)
{
	return mode == 2 || mode == 4;
}

static bool mode_new_raw(u32 index)
{
	if (mode == 2 || mode == 3)
		return true;
	if (mode == 4)
		return false;
	if (mode == 0)
		return index & 1U;
	return false;
}

static int write_and_wait(struct block_device *bdev, u32 logical,
			  u32 generation, bool raw, const char *tag)
{
	struct probe_op op;
	int error = prepare_op(bdev, &op, logical, generation, raw, true);

	if (error) {
		release_op(&op);
		return error;
	}
	submit_bio(op.bio);
	op.bio = NULL;
	error = wait_op(&op, tag, logical);
	release_op(&op);
	return error;
}

static int read_and_wait(struct block_device *bdev, u32 logical,
			 u32 generation, bool raw, const char *tag)
{
	struct probe_op op;
	int error = prepare_op(bdev, &op, logical, generation, raw, false);

	if (error) {
		release_op(&op);
		return error;
	}
	submit_bio(op.bio);
	op.bio = NULL;
	error = wait_op(&op, tag, logical);
	if (!error && !page_matches(op.page, logical, generation, raw))
		error = -EBADMSG;
	release_op(&op);
	return error;
}

static int run_probe(struct block_device *bdev)
{
	struct probe_op *pending;
	struct probe_op read_op = { };
	u32 read_page, writes, i, latest_generation;
	bool latest_raw;
	u64 min_write_seq = U64_MAX, max_write_seq = 0;
	int errors = 0, error;

	if (mode > 5 || !count || count > MAX_PENDING || expected_bypass > 1 ||
	    expected_read_error > 1 || seed_only > 1 || skip_prefill > 1 ||
	    pause_before_submit_ms > 10000U)
		return -EINVAL;
	if ((mode != 0 && mode != 5) && count > 4)
		return -EINVAL;
	if (mode == 5 && count > 4)
		return -EINVAL;

	read_page = mode == 0 ? read_logical : 0;
	if (seed_only) {
		error = write_and_wait(bdev, read_page, 1, false, "seed-only");
		pr_info("SV3BYPASS seed_done logical=%u error=%d\n", read_page, error);
		return error;
	}
	writes = count;
	pending = kcalloc(writes, sizeof(*pending), GFP_KERNEL);
	if (!pending)
		return -ENOMEM;
	if (!skip_prefill) {
		error = write_and_wait(bdev, read_page, 1, mode_old_raw(), "prefill");
		if (error) {
			pr_err("SV3BYPASS prefill failed logical=%u err=%d\n", read_page, error);
			kfree(pending);
			return error;
		}
	}

	latest_generation = mode == 0 ? 1 : 1;
	latest_raw = mode_old_raw();
	for (i = 0; i < writes; ++i) {
		u32 logical = mode == 0 ? i : 0;
		u32 generation = mode == 0 ? 2 : i + 2;
		bool raw = mode_new_raw(i);

		error = prepare_op(bdev, &pending[i], logical, generation, raw, true);
		if (error)
			goto setup_fail;
		latest_generation = generation;
		latest_raw = raw;
	}
	error = prepare_op(bdev, &read_op, read_page, mode == 0 ? 1 : latest_generation,
			   mode == 0 ? mode_old_raw() : latest_raw, false);
	if (error)
		goto setup_fail;

	pr_info("SV3BYPASS batch_ready mode=%u read_logical=%u skip_prefill=%u pause_ms=%u\n",
		mode, read_page, skip_prefill, pause_before_submit_ms);
	if (pause_before_submit_ms)
		msleep(pause_before_submit_ms);
	pr_info("SV3BYPASS submit mode=%u expected_bypass=%u writes=%u read_logical=%u\n",
		mode, expected_bypass, writes, read_page);
	for (i = 0; i < writes; ++i) {
		submit_bio(pending[i].bio);
		pending[i].bio = NULL;
	}
	submit_bio(read_op.bio);
	read_op.bio = NULL;

	error = wait_op(&read_op, "read", read_page);
	if (expected_read_error) {
		if (!error)
			errors++;
	} else if (error) {
		errors++;
	} else if (!page_matches(read_op.page,
			       mode == 0 ? read_page : read_page,
			       mode == 0 ? 1 : latest_generation,
			       mode == 0 ? mode_old_raw() : latest_raw))
		errors++;
	for (i = 0; i < writes; ++i) {
		int status = wait_op(&pending[i], "write", i);

		if (expected_read_error ? !status : status)
			errors++;
		if (pending[i].completion_seq < min_write_seq)
			min_write_seq = pending[i].completion_seq;
		if (pending[i].completion_seq > max_write_seq)
			max_write_seq = pending[i].completion_seq;
	}

	pr_info("SV3BYPASS order mode=%u read_seq=%llu min_write_seq=%llu max_write_seq=%llu read_status=%d expected_bypass=%u\n",
		mode, read_op.completion_seq, min_write_seq, max_write_seq,
		read_op.status, expected_bypass);
	if (expected_read_error) {
		/* The target is fail-closed: never read it again. */
	} else if (mode == 0) {
		if (expected_bypass && read_op.completion_seq >= min_write_seq)
			errors++;
		if (!expected_bypass && read_op.completion_seq <= max_write_seq)
			errors++;
	} else if (read_op.completion_seq <= max_write_seq) {
		errors++;
	}
	if (mode == 5) {
		error = read_and_wait(bdev, 0, writes + 1, false, "duplicate-readback");
		if (error)
			errors++;
	} else if (!expected_read_error && mode == 0) {
		for (i = 0; i < writes; ++i) {
			bool raw = mode_new_raw(i);

			error = read_and_wait(bdev, i, 2, raw, "readback");
			if (error)
				errors++;
		}
	} else if (!expected_read_error) {
		/* The earlier same-slot generations are intentionally stale. */
		error = read_and_wait(bdev, 0, latest_generation, latest_raw,
				      "latest-generation-readback");
		if (error)
			errors++;
	}
	if (!expected_read_error && mode == 0 &&
	    read_and_wait(bdev, read_page, 1, mode_old_raw(), "disjoint-readback"))
		errors++;
	pr_info("SV3BYPASS done mode=%u expected_bypass=%u expected_read_error=%u read_status=%d writes=%u errors=%d\n",
		mode, expected_bypass, expected_read_error, read_op.status,
		writes, errors);
	for (i = 0; i < writes; ++i)
		release_op(&pending[i]);
	release_op(&read_op);
	kfree(pending);
	return errors ? -EIO : 0;

setup_fail:
	for (i = 0; i < writes; ++i)
		release_op(&pending[i]);
	kfree(pending);
	return error;
}

static int __init sv3_read_bypass_probe_init(void)
{
	struct file *file;
	struct block_device *bdev;
	int error;

	if (!target)
		return -EINVAL;
	file = bdev_file_open_by_path(target, BLK_OPEN_READ | BLK_OPEN_WRITE,
				      THIS_MODULE, NULL);
	if (IS_ERR(file))
		return PTR_ERR(file);
	bdev = file_bdev(file);
	pr_info("SV3BYPASS begin target=%s mode=%u count=%u expected_bypass=%u\n",
		target, mode, count, expected_bypass);
	error = run_probe(bdev);
	fput(file);
	return error;
}

static void __exit sv3_read_bypass_probe_exit(void)
{
	pr_info("SV3BYPASS unload\n");
}
module_init(sv3_read_bypass_probe_init);
module_exit(sv3_read_bypass_probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Test-only owned-target read-bypass ordering probe");
