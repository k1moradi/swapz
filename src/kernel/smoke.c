// SPDX-License-Identifier: GPL-2.0-only
/*
 * Independent, NON-DM research module. Its initializer performs in-memory
 * codec and transaction self-tests only. NEVER registers a target, handles
 * swap, opens a block device, or interacts with V2.2 production mappings.
 */
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/string.h>
#include "authority.h"

static int __init swapz_module_init(void)
{
	struct swapz_authority *authority = NULL;
	struct swapz_builder builder;
	struct swapz_tx tx;
	struct swapz_decoded decoded;
	struct swapz_map *maps = NULL;
	swapz_u16 *live = NULL;
	swapz_u8 *classes = NULL;
	swapz_u8 *extent = NULL;
	swapz_u8 *compressed = NULL;
	const swapz_u8 *stored;
	swapz_u32 pages[7];
	swapz_u32 index;
	int error;

	extent = kvzalloc(SWAPZ_MAX_EXTENT_BYTES, GFP_KERNEL);
	compressed = kmalloc(2072, GFP_KERNEL);
	maps = kvcalloc(16, sizeof(*maps), GFP_KERNEL);
	live = kvcalloc(1024, sizeof(*live), GFP_KERNEL);
	classes = kvcalloc(1024, sizeof(*classes), GFP_KERNEL);
	authority = kzalloc(sizeof(*authority), GFP_KERNEL);
	if (!extent || !compressed || !maps || !live || !classes ||
	    !authority) {
		error = -ENOMEM;
		goto out;
	}
	error = swapz_authority_init(authority, maps, live, classes, 16, 1024);
	if (error)
		goto out;
	for (index = 0; index < ARRAY_SIZE(pages); ++index)
		pages[index] = index;
	error = swapz_stage(authority, pages, ARRAY_SIZE(pages), 4, &tx);
	if (error)
		goto out;
	error = swapz_begin(&builder, extent, SWAPZ_MAX_EXTENT_BYTES,
			  tx.sequence);
	if (error)
		goto abort;
	for (index = 0; index < ARRAY_SIZE(pages); ++index) {
		memset(compressed, (u8)(index + 1U), 2072);
		error = swapz_append(&builder, tx.records[index].logical_page,
				   tx.records[index].generation,
				   compressed, 2072);
		if (error)
			goto abort;
	}
	/* Exact 16KiB full class packs 7 records but NOT an eighth. */
	memset(compressed, 0x7f, 2072);
	if (swapz_append(&builder, 7, 1, compressed, 2072) != -ENOSPC) {
		error = -EUCLEAN;
		goto abort;
	}
	error = swapz_seal(&builder);
	if (error)
		goto abort;
	/* The complete extent write has been simulated IN MEMORY. */
	error = swapz_finish(authority, &tx, extent, SWAPZ_MAX_EXTENT_BYTES, 4, 0);
	if (error)
		goto out;
	for (index = 0; index < ARRAY_SIZE(pages); ++index) {
		error = swapz_read_authoritative(authority, index, &maps[index],
					       extent, SWAPZ_MAX_EXTENT_BYTES,
					       &decoded, &stored);
		if (error)
			goto out;
		memset(compressed, (u8)(index + 1U), 2072);
		if (decoded.logical_page != index || decoded.generation != 1 ||
		    decoded.payload_length != 2072 ||
		    memcmp(stored, compressed, 2072)) {
			error = -EUCLEAN;
			goto out;
		}
	}
	if (live[tx.start_block] != 7 || authority->committed_blocks != 4) {
		error = -EUCLEAN;
		goto out;
	}
	/* CRC32C corruption is rejected by the authoritative read path. */
	extent[decoded.payload_offset] ^= 0x40;
	if (swapz_read_authoritative(authority, 6, &maps[6], extent,
				   SWAPZ_MAX_EXTENT_BYTES, &decoded,
				   &stored) != -EBADMSG) {
		error = -EUCLEAN;
		goto out;
	}
	pr_info("swapz V3 research: in-memory 16KiB transaction, 7 x 2072B, mapping and CRC32C PASS; NO DM or block I/O\n");
	error = 0;
	goto out;
abort:
	/* On every pre-submission failure the reserved range stays quarantined. */
	swapz_abort(authority, &tx);
out:
	kvfree(extent);
	kfree(compressed);
	kvfree(maps);
	kvfree(live);
	kvfree(classes);
	kfree(authority);
	return error;
}

static void __exit swapz_module_exit(void)
{
	pr_info("swapz V3 codec/authority research module unloaded\n");
}

module_init(swapz_module_init);
module_exit(swapz_module_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("swapz experimental V3 format + mapping research; no block I/O");
MODULE_AUTHOR("swapz research");
