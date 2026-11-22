/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_OWNER_H
#define SWAPZ_ZSWAP_IMPORT_DECODER_OWNER_H

/*
 * Dormant, separately retained original native decoder reader ownership.
 * This never authenticates a zswap source slot or enables imported I/O.
 * Callers must independently own the immutable record, compressed bytes,
 * scratch and output throughout each synchronous read. No source pool, tfm,
 * BIO, zswap xarray or codec-provider module pointer is borrowed here.
 *
 * The owning module must itself link the original selected LZO1X and LZ4
 * symbols. Kernel module symbol resolution pins modular decoder providers
 * for the consumer module's lifetime; built-in providers need no module ref.
 * No per-page module_get/module_put, allocation or MM reclaim is performed.
 *
 * owner storage must remain alive from init through close_and_drain and
 * until all concurrent get attempts have quiesced. Each lease is exclusively
 * accessed by one reader, initialized to zero, and put exactly once. Close
 * requires sleepable context, and MUST NOT be called by its own live reader.
 */
#include "zswap-import-codec.h"

#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
#include <pthread.h>
#else
#include <linux/spinlock.h>
#include <linux/wait.h>
#endif

struct swapz_zswap_import_decoder_owner {
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	pthread_mutex_t lock;
	pthread_cond_t drained;
#else
	spinlock_t lock;
	wait_queue_head_t drained;
#endif
	unsigned int active_readers;
	swapz_u8 codec;
	swapz_u8 version;
	swapz_u8 closing;
};

struct swapz_zswap_import_decoder_lease {
	struct swapz_zswap_import_decoder_owner *owner;
	swapz_u8 codec;
	swapz_u8 version;
};

int swapz_zswap_import_decoder_owner_init(
	struct swapz_zswap_import_decoder_owner *owner,
	swapz_u8 original_codec, swapz_u8 original_version);
int swapz_zswap_import_decoder_owner_get(
	struct swapz_zswap_import_decoder_owner *owner,
	struct swapz_zswap_import_decoder_lease *lease);
int swapz_zswap_import_decoder_owner_decode(
	const struct swapz_zswap_import_decoder_lease *lease,
	const struct swapz_zswap_import_record *record,
	const struct swapz_zswap_import_read_authority *authority,
	const swapz_u8 *compressed_bytes, swapz_u32 compressed_capacity,
	swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *output, swapz_u32 output_capacity,
	const swapz_u8 *independent_original_page);
int swapz_zswap_import_decoder_owner_put(
	struct swapz_zswap_import_decoder_lease *lease);
int swapz_zswap_import_decoder_owner_close_and_drain(
	struct swapz_zswap_import_decoder_owner *owner);

#endif /* SWAPZ_ZSWAP_IMPORT_DECODER_OWNER_H */
