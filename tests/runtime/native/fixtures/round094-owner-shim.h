/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef R094_OWNER_SHIM_H
#define R094_OWNER_SHIM_H
#include "round092-module-shim.h"
#include <pthread.h>
#include <stddef.h>
void r094_owner_mutex_lock(pthread_mutex_t *lock);
void r094_owner_mutex_unlock(pthread_mutex_t *lock);
void *r094_owner_allocate(size_t bytes);
void r094_owner_free(void *pointer);
void r094_owner_after_enter(void);
#endif
