/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_PRIMARY_H
#define SWAPZ_PRIMARY_H

int swapz_primary_partition_lock_acquire(void);
int swapz_primary_command(int argc, char **argv);

#endif /* SWAPZ_PRIMARY_H */
