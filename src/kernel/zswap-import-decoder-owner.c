// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-import-decoder-owner.h"

#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
#include <errno.h>
#include <string.h>
#else
#include <linux/compiler.h>
#include <linux/errno.h>
#include <linux/string.h>
#endif

/* The tag comes from a separately verified original selected driver. It is
 * NOT inferred from the compressed payload or the retired crypto pool. */
static int swapz_zswap_import_decoder_profile_valid(swapz_u8 codec,
						      swapz_u8 version)
{
	return (codec == SWAPZ_ZSWAP_IMPORT_LZ4_CODEC &&
		version == SWAPZ_ZSWAP_IMPORT_VERSION) ||
		(codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC &&
		 version == SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION);
}

int swapz_zswap_import_decoder_owner_init(
	struct swapz_zswap_import_decoder_owner *owner,
	swapz_u8 original_codec, swapz_u8 original_version)
{
	if (!owner)
		return -EINVAL;
	if (!swapz_zswap_import_decoder_profile_valid(original_codec,
							    original_version))
		return -EOPNOTSUPP;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (pthread_mutex_init(&owner->lock, NULL))
		return -EIO;
	if (pthread_cond_init(&owner->drained, NULL)) {
		pthread_mutex_destroy(&owner->lock);
		return -EIO;
	}
#else
	spin_lock_init(&owner->lock);
	init_waitqueue_head(&owner->drained);
#endif
	owner->codec = original_codec;
	owner->version = original_version;
	owner->active_readers = 0U;
	owner->closing = 0U;
	return 0;
}

int swapz_zswap_import_decoder_owner_get(
	struct swapz_zswap_import_decoder_owner *owner,
	struct swapz_zswap_import_decoder_lease *lease)
{
	int result = 0;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long irq_flags;
#endif
	if (!owner || !lease)
		return -EINVAL;
	if (lease->owner)
		return -EBUSY;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (pthread_mutex_lock(&owner->lock))
		return -EIO;
#else
	spin_lock_irqsave(&owner->lock, irq_flags);
#endif
	if (owner->closing)
		result = -ESHUTDOWN;
	else if (owner->active_readers == ~0U)
		result = -EOVERFLOW;
	else {
		++owner->active_readers;
		lease->codec = owner->codec;
		lease->version = owner->version;
		lease->owner = owner;
	}
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	pthread_mutex_unlock(&owner->lock);
#else
	spin_unlock_irqrestore(&owner->lock, irq_flags);
#endif
	return result;
}

int swapz_zswap_import_decoder_owner_decode(
	const struct swapz_zswap_import_decoder_lease *lease,
	const struct swapz_zswap_import_record *record,
	const struct swapz_zswap_import_read_authority *authority,
	const swapz_u8 *compressed_bytes, swapz_u32 compressed_capacity,
	swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *output, swapz_u32 output_capacity,
	const swapz_u8 *independent_original_page)
{
	if (!lease || !lease->owner)
		return -EINVAL;
	if (!record || record->codec != lease->codec ||
	    record->version != lease->version)
		return -EOPNOTSUPP;
	/* The lease remains held through the complete original decoder call.
	 * Never dereference the owner or a retired zswap pool in this path. */
	return swapz_zswap_import_decode(record, authority,
		compressed_bytes, compressed_capacity, scratch,
		scratch_capacity, output, output_capacity,
		independent_original_page);
}

int swapz_zswap_import_decoder_owner_put(
	struct swapz_zswap_import_decoder_lease *lease)
{
	struct swapz_zswap_import_decoder_owner *owner;
	int wake_drainer;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long irq_flags;
#endif
	if (!lease || !lease->owner)
		return -EALREADY;
	owner = lease->owner;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (pthread_mutex_lock(&owner->lock))
		return -EIO;
#else
	spin_lock_irqsave(&owner->lock, irq_flags);
#endif
	if (owner->active_readers == 0U) {
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
		pthread_mutex_unlock(&owner->lock);
#else
		spin_unlock_irqrestore(&owner->lock, irq_flags);
#endif
		return -EUCLEAN;
	}
	/* Clear under lock and before the final decrement: a completed close
	 * never leaves a reusable lease. On lock failure, retain ownership. */
	lease->owner = NULL;
	lease->codec = 0U;
	lease->version = 0U;
	--owner->active_readers;
	wake_drainer = owner->closing && owner->active_readers == 0U;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (wake_drainer)
		pthread_cond_broadcast(&owner->drained);
	pthread_mutex_unlock(&owner->lock);
#else
	spin_unlock_irqrestore(&owner->lock, irq_flags);
	if (wake_drainer)
		wake_up_all(&owner->drained);
#endif
	return 0;
}

int swapz_zswap_import_decoder_owner_close_and_drain(
	struct swapz_zswap_import_decoder_owner *owner)
{
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long irq_flags;
#endif
	if (!owner)
		return -EINVAL;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (pthread_mutex_lock(&owner->lock))
		return -EIO;
	owner->closing = 1U;
	while (owner->active_readers != 0U) {
		if (pthread_cond_wait(&owner->drained, &owner->lock)) {
			pthread_mutex_unlock(&owner->lock);
			return -EIO;
		}
	}
	pthread_mutex_unlock(&owner->lock);
#else
	spin_lock_irqsave(&owner->lock, irq_flags);
	owner->closing = 1U;
	spin_unlock_irqrestore(&owner->lock, irq_flags);
	wait_event(owner->drained, READ_ONCE(owner->active_readers) == 0U);
#endif
	return 0;
}
