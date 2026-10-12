// SPDX-License-Identifier: GPL-2.0-only
/*
 * An independently loadable, non-DM research module. Initialization only
 * exercises the exact kernel codec in memory. It never opens block devices,
 * registers a DM target, handles swap or changes production V2.2 behavior.
 */
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/string.h>
#include "codec.h"

static int __init sv3_module_init(void)
{
	struct sv3_builder builder;
	struct sv3_decoded decoded;
	const sv3_u8 *stored;
	sv3_u8 *extent;
	sv3_u8 *payload;
	sv3_u32 index;
	int error;

	extent = kvzalloc(SV3_MAX_EXTENT_BYTES, GFP_KERNEL);
	payload = kmalloc(2072, GFP_KERNEL);
	if (!extent || !payload) {
		error = -ENOMEM;
		goto out;
	}
	error = sv3_begin(&builder, extent, SV3_MAX_EXTENT_BYTES, 1);
	if (error)
		goto out;
	for (index = 0; index < 7; ++index) {
		memset(payload, (u8)(index + 1U), 2072);
		error = sv3_append(&builder, index, 1, payload, 2072);
		if (error)
			goto out;
	}
	/* The 8th ~50%-like record does not fit in a 16KiB extent. */
	memset(payload, 0x7f, 2072);
	if (sv3_append(&builder, 7, 1, payload, 2072) != -ENOSPC) {
		error = -EUCLEAN;
		goto out;
	}
	error = sv3_seal(&builder);
	if (error)
		goto out;
	error = sv3_validate(extent, SV3_MAX_EXTENT_BYTES);
	if (error)
		goto out;
	for (index = 0; index < 7; ++index) {
		error = sv3_lookup(extent, SV3_MAX_EXTENT_BYTES, index,
				  &decoded, &stored);
		if (error)
			goto out;
		memset(payload, (u8)(index + 1U), 2072);
		if (decoded.logical_page != index || decoded.generation != 1 ||
		    decoded.payload_length != 2072 ||
		    memcmp(stored, payload, 2072)) {
			error = -EUCLEAN;
			goto out;
		}
	}
	/* Corrupt a spanning payload, not metadata: fail CRC32C closed. */
	extent[decoded.payload_offset]++;
	if (sv3_lookup(extent, SV3_MAX_EXTENT_BYTES, 6,
		       &decoded, &stored) != -EBADMSG) {
		error = -EUCLEAN;
		goto out;
	}
	pr_info("swapz V3 codec research: 7 x 2072B in 16KiB; CRC32C guard PASS; no DM target registered\n");
	error = 0;
out:
	kvfree(extent);
	kfree(payload);
	return error;
}

static void __exit sv3_module_exit(void)
{
	pr_info("swapz V3 codec research module unloaded\n");
}

module_init(sv3_module_init);
module_exit(sv3_module_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("swapz version-3 aligned extent CODEC ONLY; no backing I/O");
MODULE_AUTHOR("swapz research");
