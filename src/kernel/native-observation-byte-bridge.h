/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_NATIVE_OBSERVATION_BYTE_BRIDGE_H
#define SWAPZ_NATIVE_OBSERVATION_BYTE_BRIDGE_H
#include "native-observation-integration.h"
#include "native-observation-adapter.h"
#include "native-observation-byte-collector.h"

/* Built-in owner only; serialized by its cold mutex. No external entry or
 * activation. Prepare before recorder publication; abort only if unpublished.
 * Close receives the actual external join result, never calls it again.
 */
bool swapz_byte_bridge_prepare(struct swapz_observation_recorder *recorder,
			      u32 first, u32 pages);
void swapz_byte_bridge_abort(void);
void swapz_byte_bridge_close(bool joined);
bool swapz_byte_bridge_release(void);
typedef bool (*swapz_byte_record_sink)(void *context,
				      const struct swapz_byte_record *record);
bool swapz_byte_bridge_export(swapz_byte_record_sink sink, void *context);
#endif
