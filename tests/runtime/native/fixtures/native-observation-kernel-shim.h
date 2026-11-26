/* SPDX-License-Identifier: GPL-2.0-only */
/* Host-only substitutes for Linux atomic and barrier primitives. */
#ifndef SWAPZ_OBSERVATION_KERNEL_SHIM_H
#define SWAPZ_OBSERVATION_KERNEL_SHIM_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <limits.h>
#include <stdatomic.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
#define U8_MAX UINT8_MAX
typedef struct { _Atomic int counter; } atomic_t;
extern _Atomic unsigned shim_reads, shim_cas, shim_acquires, shim_ors;
extern const atomic_t *shim_fail_cas;
void shim_before_release(const void *address);
static inline void atomic_set(atomic_t *value, int next)
{
	atomic_store_explicit(&value->counter, next, memory_order_relaxed);
}
static inline int atomic_read(const atomic_t *value)
{
	atomic_fetch_add_explicit(&shim_reads, 1U, memory_order_relaxed);
	return atomic_load_explicit(&value->counter, memory_order_relaxed);
}
static inline bool atomic_try_cmpxchg_relaxed(atomic_t *value, int *old, int next)
{
	atomic_fetch_add_explicit(&shim_cas, 1U, memory_order_relaxed);
	if (value == shim_fail_cas)
		return false;
	return atomic_compare_exchange_strong_explicit(&value->counter, old, next,
			memory_order_relaxed, memory_order_relaxed);
}
static inline void atomic_or(int flags, atomic_t *value)
{
	atomic_fetch_add_explicit(&shim_ors, 1U, memory_order_relaxed);
	atomic_fetch_or_explicit(&value->counter, flags, memory_order_relaxed);
}
#define WRITE_ONCE(address, value) __atomic_store_n(&(address), (value), __ATOMIC_RELAXED)
#define smp_load_acquire(address) \
	(atomic_fetch_add_explicit(&shim_acquires, 1U, memory_order_relaxed), \
	 __atomic_load_n((address), __ATOMIC_ACQUIRE))
#define smp_store_release(address, value) do { \
	shim_before_release(address); \
	__atomic_store_n((address), (value), __ATOMIC_RELEASE); \
} while (0)
#endif
