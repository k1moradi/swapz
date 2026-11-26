/* SPDX-License-Identifier: GPL-2.0-only */
/* R097 cold owner host substitutes; use frozen R096 atomic/RCU shim. */
#ifndef SWAPZ_OBSERVATION_OWNER_HOST_MODEL_H
#define SWAPZ_OBSERVATION_OWNER_HOST_MODEL_H
#include "native-observation-adapter-host-model.h"
#include <stdio.h>
#include <stdlib.h>

#define DEFINE_MUTEX(name) pthread_mutex_t name = PTHREAD_MUTEX_INITIALIZER
static inline void mutex_lock(pthread_mutex_t *mutex)
{
	if (pthread_mutex_lock(mutex))
		abort();
}
static inline void mutex_unlock(pthread_mutex_t *mutex)
{
	if (pthread_mutex_unlock(mutex))
		abort();
}
/* Declaration accepts the trailing semicolon under -Wpedantic. */
#define EXPORT_SYMBOL_GPL(symbol) extern int model_export_##symbol
#define GFP_KERNEL 0
void *model_kvcalloc(size_t count, size_t size, int flags);
void model_kvfree(void *pointer);
void sha256(const u8 *bytes, unsigned int length, u8 *digest);
#define kvcalloc model_kvcalloc
#define kvfree model_kvfree
#endif
