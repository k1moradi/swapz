// SPDX-License-Identifier: GPL-2.0-only
/* Compile/link-only type witness. No registration, initcall or lower I/O
 * is performed by this translation unit; caller owns all contexts.
 * The lower operations are supplied by a real prospective caller, not
 * fabricated success callbacks. The decoder calls are the frozen C API. */
#include <linux/errno.h>
#include "zswap-original-storage-value.h"

struct round094_value_context {
	struct swapz_original_decoder_handle_owner *decoder;
	struct swapz_original_storage_ops lower;
};

static int value_write(void *opaque, swapz_u32 start, const swapz_u8 *bytes,
		       swapz_u32 length, swapz_u32 *completed)
{
	struct round094_value_context *context = opaque;

	return context->lower.write(context->lower.context, start, bytes, length, completed);
}

static int value_flush(void *opaque)
{
	struct round094_value_context *context = opaque;

	return context->lower.flush(context->lower.context);
}

static int value_read(void *opaque, swapz_u32 start, swapz_u8 *bytes,
		      swapz_u32 length, swapz_u32 *completed)
{
	struct round094_value_context *context = opaque;

	return context->lower.read(context->lower.context, start, bytes, length, completed);
}

static int value_decoder_get(void *opaque, swapz_u8 codec, swapz_u8 version,
			     struct swapz_original_decoder_value_handle *handle)
{
	struct round094_value_context *context = opaque;

	return swapz_original_decoder_handle_get(context->decoder, codec, version, handle);
}

static int value_decoder_put(void *opaque,
			     const struct swapz_original_decoder_value_handle *handle)
{
	struct round094_value_context *context = opaque;

	return swapz_original_decoder_handle_put(context->decoder, handle);
}

static int value_decoder_read(void *opaque,
	const struct swapz_original_decoder_value_snapshot *snapshot,
	swapz_u32 ceiling, swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *verified, swapz_u32 verified_capacity,
	swapz_u8 *output, swapz_u32 output_capacity)
{
	struct round094_value_context *context = opaque;

	return swapz_original_decoder_handle_read(context->decoder, snapshot, ceiling,
		scratch, scratch_capacity, verified, verified_capacity, output, output_capacity);
}

/* Non-exported link witness only: no caller is installed in dm-target. */
int round094_value_bind(struct swapz_shared_storage_value *storage,
	struct swapz_authority *authority, struct round094_value_context *context);
int round094_value_bind(struct swapz_shared_storage_value *storage,
	struct swapz_authority *authority, struct round094_value_context *context)
{
	struct swapz_shared_storage_value_ops ops = {
		.context = context,
		.write = value_write,
		.flush = value_flush,
		.read = value_read,
		.decoder_get = value_decoder_get,
		.decoder_put = value_decoder_put,
		.decoder_read = value_decoder_read,
	};

	if (!context || !context->decoder || !context->lower.write ||
	    !context->lower.flush || !context->lower.read)
		return -EINVAL;
	return swapz_shared_storage_value_init(storage, authority, &ops);
}
