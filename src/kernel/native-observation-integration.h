/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_NATIVE_OBSERVATION_INTEGRATION_H
#define SWAPZ_NATIVE_OBSERVATION_INTEGRATION_H

/* R104 immutable declaration-only integration contract. No implementation,
 * admission or activation is provided here. All control is guarded, one-shot
 * and externally lifetime-fenced; see docs/handoff/zswapz/round104/frozen-contract.md.
 */
#ifndef SWAPZ_ROUND104_INTEGRATION_TEST
#error "Round104 integration requires explicit development staging"
#endif
#include <linux/types.h>

struct file;
struct swapz_mm_trial_scope;
struct swapz_observation_record;

/* A11: non-sleeping, RCU-safe exact capture-publication identity query.
 * No reference transfer, false on capture stop or scope mismatch.
 */
bool swapz_mm_trial_scope_matches_exact(const struct swapz_mm_trial_scope *scope,
                                      const struct file *mapper_file);

/* A2: cold bind to independently validated scope, after recorder start.
 * Active is a hint; every hot call must recheck actual lifetime.
 */
bool swapz_trial_byte_bind_scope(u64 identity, u32 swap_type, u64 area_epoch);
bool swapz_trial_byte_active(void);

/* Copy real original 4096-byte source before compression, not decoder output.
 * The private staging token is never a wire identity. Zero means no retained
 * input; finish with actual committed store sequence, zero abandons it.
 */
u64 swapz_trial_byte_stage_input(u64 identity, u32 swap_type, u64 area_epoch,
                                u64 slot, const void *bytes, size_t length);
void swapz_trial_byte_finish_input(u64 input_token, u64 store_sequence);

/* Call after append_sequence at the real transition. No second append.
 * Bytes: original ordinary WRITE ACCEPT or final BIO ORACLE under live pin;
 * otherwise NULL/0. Evidence loss does not change I/O success.
 */
bool swapz_trial_byte_event(const struct swapz_observation_record *record,
                           u64 sequence, const void *bytes, size_t length);
void swapz_trial_byte_invalidate(void);

#endif
