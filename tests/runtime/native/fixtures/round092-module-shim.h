/* SPDX-License-Identifier: GPL-2.0-only */
/* Host-only module lifetime ABI; not a Linux module loader. */
#ifndef R092_MODULE_SHIM_H
#define R092_MODULE_SHIM_H
#include <stdbool.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
struct module {
	atomic_bool live;
	atomic_uint refs;
};
static inline bool try_module_get(struct module *owner)
{
	if (!owner)
		return true;
	if (!atomic_load(&owner->live))
		return false;
	(void)atomic_fetch_add(&owner->refs, 1U);
	return true;
}
static inline void module_put(struct module *owner)
{
	if (owner && !atomic_fetch_sub(&owner->refs, 1U)) {
		fprintf(stderr, "R092_FIRST_ERROR module_ref_underflow\n");
		exit(77);
	}
}
#endif
