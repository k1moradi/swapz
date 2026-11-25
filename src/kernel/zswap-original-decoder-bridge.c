// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-decoder-bridge.h"

#ifdef SWAPZ_ORIGINAL_STORAGE_TEST
#include "zswap-original-storage.h"

#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
#include <errno.h>
#include <string.h>
#else
#include <linux/errno.h>
#include <linux/string.h>
#endif

#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
static int bridge_lock(struct swapz_original_decoder_bridge *bridge)
{
	return pthread_mutex_lock(&bridge->lock) ? -EIO : 0;
}
static void bridge_unlock(struct swapz_original_decoder_bridge *bridge)
{
	pthread_mutex_unlock(&bridge->lock);
}
#else
/* These calls run in the serialized sleepable ordered storage owner and its
 * synchronous reader path; the lock protects only bounded in-memory state. */
static void bridge_lock(struct swapz_original_decoder_bridge *bridge,
			unsigned long *flags)
{
	spin_lock_irqsave(&bridge->lock, *flags);
}
static void bridge_unlock(struct swapz_original_decoder_bridge *bridge,
			  unsigned long *flags)
{
	spin_unlock_irqrestore(&bridge->lock, *flags);
}
#endif

static int original_codec_index(swapz_u8 codec, swapz_u8 version)
{
	if (version != SWAPZ_ZSWAP_IMPORT_VERSION)
		return -1;
	if (codec == SWAPZ_ZSWAP_IMPORT_LZ4_CODEC)
		return 0;
	if (codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)
		return 1;
	return -1;
}

/* Only compare token addresses, never dereference an untrusted opaque value. */
static struct swapz_original_decoder_bridge_token *find_active_token(
	struct swapz_original_decoder_bridge *bridge, const void *token)
{
	unsigned int index;

	for (index = 0; index < bridge->issued_tokens; ++index)
		if (token == &bridge->tokens[index].lease &&
		    bridge->tokens[index].active)
			return &bridge->tokens[index];
	return NULL;
}

static void *decoder_get(void *context, swapz_u8 codec, swapz_u8 version)
{
	struct swapz_original_decoder_bridge *bridge = context;
	struct swapz_original_decoder_bridge_token *token;
	int index = original_codec_index(codec, version);
	void *result = NULL;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!bridge || index < 0)
		return NULL;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (bridge_lock(bridge))
		return NULL;
#else
	bridge_lock(bridge, &flags);
#endif
	if (!bridge->closing && !bridge->faulted &&
	    bridge->issued_tokens < SWAPZ_ORIGINAL_DECODER_BRIDGE_TOKENS) {
		token = &bridge->tokens[bridge->issued_tokens];
		/* Never recycle this token address, including failed get attempts.
		 * The frozen callback API has no generation to distinguish ABA. */
		token->issued = 1U;
		++bridge->issued_tokens;
		if (!swapz_zswap_import_decoder_owner_get(&bridge->owners[index],
								   &token->lease)) {
			token->active = 1U;
			++bridge->active_tokens;
			result = &token->lease;
		}
	}
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	bridge_unlock(bridge);
#else
	bridge_unlock(bridge, &flags);
#endif
	return result;
}

static void decoder_put(void *context, void *lease)
{
	struct swapz_original_decoder_bridge *bridge = context;
	struct swapz_original_decoder_bridge_token *token;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!bridge || !lease)
		return;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (bridge_lock(bridge))
		return;
#else
	bridge_lock(bridge, &flags);
#endif
	token = find_active_token(bridge, lease);
	if (token) {
		if (swapz_zswap_import_decoder_owner_put(&token->lease))
			bridge->faulted = 1U;
		else {
			token->active = 0U;
			--bridge->active_tokens;
		}
	}
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	bridge_unlock(bridge);
#else
	bridge_unlock(bridge, &flags);
#endif
}

static int lower_write(void *context, swapz_u32 start, const swapz_u8 *image,
		       swapz_u32 length, swapz_u32 *completed)
{
	struct swapz_original_decoder_bridge *bridge = context;

	if (!bridge || bridge->closing || bridge->faulted)
		return -ESHUTDOWN;
	return bridge->lower_write(bridge->lower_context, start, image,
				   length, completed);
}

static int lower_flush(void *context)
{
	struct swapz_original_decoder_bridge *bridge = context;

	if (!bridge || bridge->closing || bridge->faulted)
		return -ESHUTDOWN;
	return bridge->lower_flush(bridge->lower_context);
}

static int lower_read(void *context, swapz_u32 start, swapz_u8 *image,
		      swapz_u32 length, swapz_u32 *completed)
{
	struct swapz_original_decoder_bridge *bridge = context;

	if (!bridge || bridge->closing || bridge->faulted)
		return -ESHUTDOWN;
	return bridge->lower_read(bridge->lower_context, start, image,
				  length, completed);
}

int swapz_original_decoder_bridge_init(
	struct swapz_original_decoder_bridge *bridge,
	const struct swapz_original_storage_ops *lower,
	struct swapz_original_storage_ops *wrapped)
{
	int result;

	if (!bridge || !lower || !wrapped || bridge == (const void *)lower ||
	    bridge == (const void *)wrapped || lower == wrapped ||
	    !lower->write || !lower->read || !lower->flush ||
	    lower->decoder_get || lower->decoder_put || lower->context == bridge)
		return -EINVAL;
	/* Fresh zero-initialized bridge only; never reset an active owner. */
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (pthread_mutex_init(&bridge->lock, NULL))
		return -EIO;
#else
	spin_lock_init(&bridge->lock);
#endif
	result = swapz_zswap_import_decoder_owner_init(&bridge->owners[0],
		SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, SWAPZ_ZSWAP_IMPORT_VERSION);
	if (result)
		goto fail_lock;
	result = swapz_zswap_import_decoder_owner_init(&bridge->owners[1],
		SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC, SWAPZ_ZSWAP_IMPORT_VERSION);
	if (result)
		goto fail_first;
	bridge->lower_context = lower->context;
	bridge->lower_write = lower->write;
	bridge->lower_read = lower->read;
	bridge->lower_flush = lower->flush;
	*wrapped = (struct swapz_original_storage_ops) {
		.context = bridge,
		.write = lower_write,
		.flush = lower_flush,
		.read = lower_read,
		.decoder_get = decoder_get,
		.decoder_put = decoder_put,
	};
	return 0;

fail_first:
	swapz_zswap_import_decoder_owner_close_and_drain(&bridge->owners[0]);
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	pthread_cond_destroy(&bridge->owners[0].drained);
	pthread_mutex_destroy(&bridge->owners[0].lock);
#endif
fail_lock:
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	pthread_mutex_destroy(&bridge->lock);
#endif
	return result;
}

static int overlaps_bridge(const struct swapz_original_decoder_bridge *bridge,
			   const void *address, swapz_u32 length)
{
	return swapz_zswap_import_ranges_overlap(bridge, (swapz_u32)sizeof(*bridge),
					       address, length);
}

int swapz_original_decoder_bridge_read(
	struct swapz_original_decoder_bridge *bridge,
	const struct swapz_original_decoder_snapshot *snapshot,
	swapz_u32 ceiling, swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *verified, swapz_u32 verified_capacity,
	swapz_u8 *output, swapz_u32 output_capacity)
{
	struct swapz_zswap_import_decoder_lease read_lease = {0};
	struct swapz_original_decoder_bridge_token *token;
	struct swapz_original_decode_record record;
	const swapz_u8 *compressed_bytes;
	swapz_u32 compressed_capacity;
	int result, release_result;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!bridge || !snapshot || !scratch || !verified || !output)
		return -EINVAL;
	if (scratch_capacity != SWAPZ_BLOCK_BYTES ||
	    verified_capacity != SWAPZ_BLOCK_BYTES ||
	    output_capacity != SWAPZ_BLOCK_BYTES ||
	    !snapshot->compressed_bytes || !snapshot->record_token)
		return -EINVAL;
	if (overlaps_bridge(bridge, snapshot, (swapz_u32)sizeof(*snapshot)) ||
	    overlaps_bridge(bridge, snapshot->compressed_bytes,
			    snapshot->record.compressed_length) ||
	    overlaps_bridge(bridge, scratch, SWAPZ_BLOCK_BYTES) ||
	    overlaps_bridge(bridge, verified, SWAPZ_BLOCK_BYTES) ||
	    overlaps_bridge(bridge, output, SWAPZ_BLOCK_BYTES) ||
	    swapz_zswap_import_ranges_overlap(output, SWAPZ_BLOCK_BYTES,
						scratch, SWAPZ_BLOCK_BYTES) ||
	    swapz_zswap_import_ranges_overlap(output, SWAPZ_BLOCK_BYTES,
						verified, SWAPZ_BLOCK_BYTES) ||
	    swapz_zswap_import_ranges_overlap(output, SWAPZ_BLOCK_BYTES,
						snapshot, (swapz_u32)sizeof(*snapshot)) ||
	    swapz_zswap_import_ranges_overlap(output, SWAPZ_BLOCK_BYTES,
						snapshot->compressed_bytes,
						snapshot->record.compressed_length) ||
	    swapz_zswap_import_ranges_overlap(verified, SWAPZ_BLOCK_BYTES,
						snapshot, (swapz_u32)sizeof(*snapshot)) ||
	    swapz_zswap_import_ranges_overlap(scratch, SWAPZ_BLOCK_BYTES,
						snapshot, (swapz_u32)sizeof(*snapshot)))
		return -EINVAL;
	/* Additional non-overlap is enforced by the original decode helper,
	 * which also checks its local record/lease and the owner storage. */
	compressed_bytes = snapshot->compressed_bytes;
	compressed_capacity = snapshot->compressed_capacity;
	record = snapshot->record;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (bridge_lock(bridge))
		return -EIO;
#else
	bridge_lock(bridge, &flags);
#endif
	result = -ESHUTDOWN;
	if (!bridge->closing && !bridge->faulted) {
		result = -ESTALE;
		token = find_active_token(bridge, snapshot->record_token);
		if (token && token->lease.owner &&
		    token->lease.codec == record.codec &&
		    token->lease.version == record.version &&
		    bridge->active_reads != ~0U) {
			result = swapz_zswap_import_decoder_owner_get(
				token->lease.owner, &read_lease);
			if (!result)
				++bridge->active_reads;
		}
	}
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	bridge_unlock(bridge);
#else
	bridge_unlock(bridge, &flags);
#endif
	if (result)
		return result;
	result = swapz_original_decode(&read_lease, &record, ceiling,
		compressed_bytes, compressed_capacity, scratch, scratch_capacity,
		verified, verified_capacity);
	release_result = swapz_zswap_import_decoder_owner_put(&read_lease);
	if (release_result)
		result = -EIO;
	/* The record's independent lease may be put concurrently; the read
	 * lease, not the record token, holds the codec/module through decode. */
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (bridge_lock(bridge))
		return -EIO;
#else
	bridge_lock(bridge, &flags);
#endif
	/* Commit while still counted as a live reader, after successful put.
	 * Close cannot race the final copy, even on a different CPU. */
	if (!result)
		memcpy(output, verified, SWAPZ_BLOCK_BYTES);
	--bridge->active_reads;
	if (release_result)
		bridge->faulted = 1U;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	bridge_unlock(bridge);
#else
	bridge_unlock(bridge, &flags);
#endif
	return result;
}

int swapz_original_decoder_bridge_close(struct swapz_original_decoder_bridge *bridge)
{
	unsigned int index;
	int result = 0;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!bridge)
		return -EINVAL;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (bridge_lock(bridge))
		return -EIO;
#else
	bridge_lock(bridge, &flags);
#endif
	if (bridge->active_reads || bridge->active_tokens) {
		result = -EBUSY;
	} else if (bridge->closing) {
		result = -EALREADY;
	} else {
		bridge->closing = 1U;
	}
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	bridge_unlock(bridge);
#else
	bridge_unlock(bridge, &flags);
#endif
	if (result)
		return result;
	for (index = 0U; index < 2U; ++index) {
		result = swapz_zswap_import_decoder_owner_close_and_drain(
			&bridge->owners[index]);
		if (result)
			return result;
	}
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	for (index = 0U; index < 2U; ++index) {
		pthread_cond_destroy(&bridge->owners[index].drained);
		pthread_mutex_destroy(&bridge->owners[index].lock);
	}
	pthread_mutex_destroy(&bridge->lock);
#endif
	/* Stop all external invocations before freeing/reusing bridge storage.
	 * No live callback can be admitted after close and no wait holds the
	 * bridge lock while depending on an active reader. */
	return 0;
}
#endif /* SWAPZ_ORIGINAL_STORAGE_TEST */
