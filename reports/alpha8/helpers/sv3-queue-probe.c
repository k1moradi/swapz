// Test-only upper-BIO submitter for the owned swapz3 null_blk target.
#include <linux/bio.h>
#include <linux/blkdev.h>
#include <linux/completion.h>
#include <linux/highmem.h>
#include <linux/delay.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/vmalloc.h>

#define TEST_PAGES 1024U
struct test_batch;
struct test_entry {
	struct test_batch *batch;
	struct page *page;
	struct bio *bio;
	int status;
};
struct test_batch {
	struct completion all_done;
	atomic_t completed;
	unsigned int count;
	struct test_entry *entries;
};
static char *target = "/dev/mapper/swapz3-a4-queue";
static char *run_tag = "alpha8";
static unsigned int count = TEST_PAGES;
static unsigned int hold_after_submit_ms;
module_param(target, charp, 0400);
module_param(run_tag, charp, 0400);
module_param(count, uint, 0400);
module_param(hold_after_submit_ms, uint, 0400);
MODULE_PARM_DESC(target, "exact test-owned swapz3 mapping path");
MODULE_PARM_DESC(run_tag, "unique evidence correlation tag");
MODULE_PARM_DESC(count, "number of one-page upper BIOs");
MODULE_PARM_DESC(hold_after_submit_ms, "hold the test helper after submit to permit concurrent suspend");

static void fill_page(u8 *dst, u32 page_id)
{
	u32 i;
	if (page_id % 5U) {
		for (i = 0; i < PAGE_SIZE; i++)
			dst[i] = (u8)(page_id * 13U + (i % 31U) * 7U);
	} else {
		u32 x = 0xa4210001U ^ (page_id * 0x9e3779b9U);
		for (i = 0; i < PAGE_SIZE; i++) {
			x ^= x << 13;
			x ^= x >> 17;
			x ^= x << 5;
			dst[i] = (u8)x;
		}
	}
}

static void test_end_io(struct bio *bio)
{
	struct test_entry *entry = bio->bi_private;
	struct test_batch *batch = entry->batch;
	int status = blk_status_to_errno(bio->bi_status);
	int completed;
	entry->status = status;
	bio_put(bio);
	completed = atomic_inc_return(&batch->completed);
	if (completed == batch->count)
		complete(&batch->all_done);
}

static int __init sv3_queue_probe_init(void)
{
	struct file *file;
	struct block_device *bdev;
	struct test_batch *batch;
	unsigned int i, errors = 0;
	unsigned long waited;
	int ret = 0;
	if (!count || count > TEST_PAGES || hold_after_submit_ms > 5000U)
		return -EINVAL;
	pr_info("SV3QUEUE begin tag=%s target=%s count=%u\n", run_tag, target, count);
	file = bdev_file_open_by_path(target, BLK_OPEN_READ | BLK_OPEN_WRITE,
				      THIS_MODULE, NULL);
	if (IS_ERR(file))
		return PTR_ERR(file);
	bdev = file_bdev(file);
	batch = kzalloc(sizeof(*batch), GFP_KERNEL);
	if (!batch) {
		ret = -ENOMEM;
		goto out_file;
	}
	batch->entries = kcalloc(count, sizeof(*batch->entries), GFP_KERNEL);
	if (!batch->entries) {
		ret = -ENOMEM;
		goto out_batch;
	}
	init_completion(&batch->all_done);
	atomic_set(&batch->completed, 0);
	batch->count = count;
	for (i = 0; i < count; i++) {
		struct test_entry *entry = &batch->entries[i];
		struct bio *bio;
		void *address;
		entry->batch = batch;
		entry->page = alloc_page(GFP_KERNEL);
		if (!entry->page) {
			ret = -ENOMEM;
			goto fail_unsubmitted;
		}
		address = kmap_local_page(entry->page);
		fill_page(address, i);
		kunmap_local(address);
		bio = bio_alloc(bdev, 1, REQ_OP_WRITE, GFP_KERNEL);
		if (!bio) {
			ret = -ENOMEM;
			goto fail_unsubmitted;
		}
		bio->bi_iter.bi_sector = (sector_t)i * (PAGE_SIZE >> 9);
		bio->bi_private = entry;
		bio->bi_end_io = test_end_io;
		entry->bio = bio;
		if (bio_add_page(bio, entry->page, PAGE_SIZE, 0) != PAGE_SIZE) {
			bio_put(bio);
			entry->bio = NULL;
			ret = -EIO;
			goto fail_unsubmitted;
		}
	}
	for (i = 0; i < count; i++) {
		struct test_entry *entry = &batch->entries[i];
		struct bio *bio = entry->bio;
		entry->bio = NULL;
		entry->status = -EINPROGRESS;
		submit_bio(bio);
	}
	pr_info("SV3QUEUE submitted tag=%s count=%u outstanding=%u\n", run_tag,
		count, count - (unsigned int)atomic_read(&batch->completed));
	if (hold_after_submit_ms)
		msleep(hold_after_submit_ms);
	waited = wait_for_completion_timeout(&batch->all_done, 90 * HZ);
	if (!waited) {
		pr_err("SV3QUEUE timeout tag=%s completed=%d submitted=%u; preserving ownership until drain\n",
		       run_tag, atomic_read(&batch->completed), count);
		wait_for_completion(&batch->all_done);
	}
	for (i = 0; i < count; i++) {
		if (batch->entries[i].status)
			errors++;
		__free_page(batch->entries[i].page);
	}
	pr_info("SV3QUEUE done tag=%s submitted=%u completed=%d errors=%u\n", run_tag,
		count, atomic_read(&batch->completed), errors);
	ret = errors ? -EIO : 0;
	kfree(batch->entries);
	kfree(batch);
	fput(file);
	return ret;

fail_unsubmitted:
	for (i = 0; i < count; i++) {
		struct test_entry *entry = &batch->entries[i];
		if (entry->bio)
			bio_put(entry->bio);
		if (entry->page)
			__free_page(entry->page);
	}
	kfree(batch->entries);
out_batch:
	kfree(batch);
out_file:
	fput(file);
	return ret;
}
static void __exit sv3_queue_probe_exit(void)
{
	pr_info("SV3QUEUE unloaded\n");
}
module_init(sv3_queue_probe_init);
module_exit(sv3_queue_probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Test-only 1024 upper BIO queue and suspend probe");
