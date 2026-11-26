/* SPDX-License-Identifier: GPL-2.0-only */
/* Host substitutes ONLY. Not Linux RCU or native barrier qualification. */
#ifndef SWAPZ_OBSERVATION_HOST_MODEL_H
#define SWAPZ_OBSERVATION_HOST_MODEL_H
#include <assert.h>
#include <limits.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdatomic.h>
#include <string.h>
typedef uint64_t u64;
typedef uint32_t u32;
typedef uint8_t u8;
#define U8_MAX UINT8_MAX
#define __rcu
typedef struct { atomic_int value; } atomic_t;
static inline int atomic_read(const atomic_t *counter)
{
	return atomic_load_explicit(&counter->value, memory_order_relaxed);
}
static inline void atomic_set(atomic_t *counter, int value)
{
	atomic_store_explicit(&counter->value, value, memory_order_relaxed);
}
static inline void atomic_or(int value, atomic_t *counter)
{
	(void)atomic_fetch_or_explicit(&counter->value, value, memory_order_relaxed);
}
bool model_try_cmpxchg(atomic_t *counter, int *previous, int next);
void model_read_lock(void);
void model_read_unlock(void);
void model_synchronize_rcu(void);
#define atomic_try_cmpxchg_relaxed model_try_cmpxchg
#define rcu_read_lock model_read_lock
#define rcu_read_unlock model_read_unlock
#define synchronize_rcu model_synchronize_rcu
#define rcu_access_pointer(pointer) __atomic_load_n(&(pointer), __ATOMIC_RELAXED)
#define rcu_dereference(pointer) __atomic_load_n(&(pointer), __ATOMIC_ACQUIRE)
#define rcu_assign_pointer(pointer, value) __atomic_store_n(&(pointer), (value), __ATOMIC_RELEASE)
#define RCU_INIT_POINTER(pointer, value) __atomic_store_n(&(pointer), (value), __ATOMIC_RELAXED)
#define smp_load_acquire(pointer) __atomic_load_n((pointer), __ATOMIC_ACQUIRE)
#define smp_store_release(pointer, value) __atomic_store_n((pointer), (value), __ATOMIC_RELEASE)
#endif
