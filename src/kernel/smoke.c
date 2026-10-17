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

static int __init sv3_module_init(void)
{
	struct sv3_authority *authority = NULL;
	struct sv3_builder builder;
	struct sv3_tx tx;
	struct sv3_decoded decoded;
	struct sv3_map *maps = NULL;
	sv3_u16 *live = NULL;
	sv3_u8 *classes = NULL;
	sv3_u8 *extent = NULL;
	sv3_u8 *compressed = NULL;
	const sv3_u8 *stored;
	sv3_u32 pages[7];
	sv3_u32 index;
	int error;

	extent = kvzalloc(SV3_MAX_EXTENT_BYTES, GFP_KERNEL);
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
	error = sv3_authority_init(authority, maps, live, classes, 16, 1024);
	if (error)
		goto out;
	for (index = 0; index < ARRAY_SIZE(pages); ++index)
		pages[index] = index;
	error = sv3_stage(authority, pages, ARRAY_SIZE(pages), 4, &tx);
	if (error)
		goto out;
	error = sv3_begin(&builder, extent, SV3_MAX_EXTENT_BYTES,
			  tx.sequence);
	if (error)
		goto abort;
	for (index = 0; index < ARRAY_SIZE(pages); ++index) {
		memset(compressed, (u8)(index + 1U), 2072);
		error = sv3_append(&builder, tx.records[index].logical_page,
				   tx.records[index].generation,
				   compressed, 2072);
		if (error)
			goto abort;
	}
	/* Exact 16KiB full class packs 7 records but NOT an eighth. */
	memset(compressed, 0x7f, 2072);
	if (sv3_append(&builder, 7, 1, compressed, 2072) != -ENOSPC) {
		error = -EUCLEAN;
		goto abort;
	}
	error = sv3_seal(&builder);
	if (error)
		goto abort;
	/* The complete extent write has been simulated IN MEMORY. */
	error = sv3_finish(authority, &tx, extent, SV3_MAX_EXTENT_BYTES, 4, 0);
	if (error)
		goto out;
	for (index = 0; index < ARRAY_SIZE(pages); ++index) {
		error = sv3_read_authoritative(authority, index, &maps[index],
					       extent, SV3_MAX_EXTENT_BYTES,
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
	if (sv3_read_authoritative(authority, 6, &maps[6], extent,
				   SV3_MAX_EXTENT_BYTES, &decoded,
				   &stored) != -EBADMSG) {
		error = -EUCLEAN;
		goto out;
	}
	pr_info("swapz V3 research: in-memory 16KiB transaction, 7 x 2072B, mapping and CRC32C PASS; NO DM or block I/O\n");
	error = 0;
	goto out;
abort:
	/* On every pre-submission failure the reserved range stays quarantined. */
	sv3_abort(authority, &tx);
out:
	kvfree(extent);
	kfree(compressed);
	kvfree(maps);
	kvfree(live);
	kvfree(classes);
	kfree(authority);
	return error;
}

static void __exit sv3_module_exit(void)
{
	pr_info("swapz V3 codec/authority research module unloaded\n");
}

module_init(sv3_module_init);
module_exit(sv3_module_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("swapz experimental V3 format + mapping research; no block I/O");
MODULE_AUTHOR("swapz research");
