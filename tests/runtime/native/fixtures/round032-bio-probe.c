// SPDX-License-Identifier: GPL-2.0-only
/*
 * Round032 compiler/modpost ONLY: this original-source external GPL module
 * intentionally references the real exported original kernel BIO copy view.
 * Not a production DM consumer. Never loaded, and no block I/O issued.
 * The empty source_bio is deliberately rejected if anyone attempts to run.
 */
#include <linux/module.h>
#include <linux/bio.h>
#include <linux/errno.h>
#include <linux/init.h>

#if !defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) || \
    !defined(SWAPZ_ROUND031_MM_BIO_SOURCE) || \
    !defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
#error "Round032 GPL copy-out probe may be compiled only with original CI source"
#endif

static int __init swapz_round032_probe_init(void)
{
	struct swapz_ci_lz4_owned_view_v1 snapshot = {};
	u8 borrowed_output = 0;

	/* The full exported symbol MUST resolve in the same original Linux
	 * Module.symvers via modpost. No real BIO, no loading, no I/O.
	 */
	return swapz_ci_bio_snapshot_lz4_v1(NULL, &snapshot,
					   &borrowed_output, 1U);
}

static void __exit swapz_round032_probe_exit(void)
{
}

module_init(swapz_round032_probe_init);
module_exit(swapz_round032_probe_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Round032 source-only original pinned BIO GPL export modpost probe");
