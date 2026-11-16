#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>

#define PAGE_SIZE 4096U
#define GFP_KERNEL 0
#define NO_INTERLEAVE_INDEX 0
#define BIT(n) (1U << (n))
#define ZSWPWB 0
#define REQ_OP_WRITE 1U
#define REQ_OP_READ 0U
#define REQ_SWAP 4U
#define SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK 1U
#define IS_ERR_OR_NULL(ptr) ((ptr) == NULL)
#define IS_ERR(ptr) ((ptr) == NULL)
#define PTR_ERR(ptr) (-ENOMEM)

typedef unsigned long pgoff_t;
typedef struct { unsigned long val; } swp_entry_t;
struct obj_cgroup { unsigned int events; };
struct zswap_entry { swp_entry_t swpentry; struct obj_cgroup *objcg; unsigned int compressed_length; bool freed; };
struct xarray { struct zswap_entry *entry; };
struct folio { unsigned char bytes[PAGE_SIZE]; bool locked, uptodate, dropbehind, released; };
struct mempolicy { int placeholder; };
struct swap_info_struct { int placeholder; };
struct swap_io_ctx { unsigned int swap_origin; bool issued; };
struct bio_observation { unsigned int operation, length, swap_origin; };
struct bio { unsigned int bi_opf, bi_swap_origin; };
#define bio_op(bio) ((bio)->bi_opf & REQ_OP_WRITE)
static struct xarray stored_entries;
static struct folio swap_cache;
static struct swap_info_struct swap_device;
static struct mempolicy swap_policy;
static struct bio_observation observed_bio;
static unsigned char original_page[PAGE_SIZE];
static bool device_available, cache_available, decompression_success;
static unsigned int decompress_count, erase_count, free_count, write_count, submit_count, cleanup_count;
static int mock_current;
#define current (&mock_current)

static pgoff_t swp_offset(swp_entry_t entry) { return entry.val; }
static struct swap_info_struct *get_swap_device(swp_entry_t entry) {
    (void)entry; return device_available ? &swap_device : NULL;
}
static struct mempolicy *get_task_policy(int *task) { (void)task; return &swap_policy; }
static void put_swap_device(struct swap_info_struct *device) { (void)device; }
static struct folio *__swap_cache_alloc_folio(swp_entry_t entry, int flags,
        unsigned int mask, void *placeholder, struct mempolicy *policy, int offset) {
    (void)entry; (void)flags; (void)mask; (void)placeholder; (void)policy; (void)offset;
    if (!cache_available) return NULL;
    swap_cache.locked = true;
    return &swap_cache;
}
static void folio_clear_active(struct folio *folio) { (void)folio; }
static struct xarray *swap_zswap_tree(swp_entry_t entry) {
    (void)entry; return &stored_entries;
}
static struct zswap_entry *xa_load(struct xarray *tree, pgoff_t offset) {
    (void)offset; return tree->entry;
}
static bool zswap_decompress(struct zswap_entry *entry, struct folio *folio) {
    decompress_count++;
    if (!decompression_success || entry->compressed_length == 0 ||
        entry->compressed_length >= PAGE_SIZE) return false;
    memcpy(folio->bytes, original_page, PAGE_SIZE); /* Stub decoder, NOT kernel codec. */
    return true;
}
static void xa_erase(struct xarray *tree, pgoff_t offset) {
    (void)offset; erase_count++; tree->entry = NULL;
}
static void count_vm_event(int event) { (void)event; }
static void count_objcg_events(struct obj_cgroup *objcg, int event, unsigned int count) {
    (void)event; objcg->events += count;
}
static void zswap_entry_free(struct zswap_entry *entry) { free_count++; entry->freed = true; }
static void folio_mark_uptodate(struct folio *folio) { folio->uptodate = true; }
static void folio_set_dropbehind(struct folio *folio) { folio->dropbehind = true; }
static void folio_put(struct folio *folio) { folio->released = true; }
static void __swap_writeout(struct swap_io_ctx *ctx, struct folio *folio) {
    assert(folio->uptodate && folio->dropbehind && folio->locked && folio->released);
    write_count++;
    observed_bio.operation = REQ_OP_WRITE | REQ_SWAP;
    observed_bio.swap_origin = ctx->swap_origin;
    observed_bio.length = PAGE_SIZE;
    ctx->issued = true;
}
static void swap_write_submit(struct swap_io_ctx *ctx) { assert(ctx->issued); submit_count++; }
static void swap_cache_del_folio(struct folio *folio) { (void)folio; cleanup_count++; }
static void folio_unlock(struct folio *folio) { folio->locked = false; }
