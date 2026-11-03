/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_PRIMARY_H
#define SWAPZ_PRIMARY_H

#include <sys/types.h>

int swapz_primary_partition_lock_acquire(void);
/* Internal lifecycle primitive; caller must hold the matching partition lock. */
int swapz_primary_claim_partition_owner_at(int recovery_fd, int lock_fd,
						  const char *run_id,
						  uid_t expected_owner);
/* Atomically replace a durable state record while holding the partition lock. */
int swapz_primary_replace_record_at(int recovery_fd, const char *name,
				    const char *run_id, const char *record,
				    uid_t expected_owner);
int swapz_primary_command(int argc, char **argv);

#endif /* SWAPZ_PRIMARY_H */
