// SPDX-License-Identifier: GPL-2.0-only
/*
 * Rootless Kbuild-only original Linux decoder dependency probe.
 *
 * This is NOT the dm-swapz product, a functional kernel test, or a live
 * decoder lease. No I/O, source pool, memory pressure or ACK is performed.
 * Its module_init always refuses activation, even if someone tries to load it.
 * A retained, never-invoked data relocation roots the actual selected
 * import decoder's LZO1X, LZ4, SHA256 and real swapz CRC C consumer through
 * genuine GPL Module.symvers and native modpost in both ZSWAP configurations.
 * Merely annotating an otherwise unreachable static function __used did not
 * establish that the final module retained every decoder relocation.
 */
#include <linux/errno.h>
#include <linux/module.h>

#include "zswap-import-codec.h"

#if SWAPZ_ZSWAP_IMPORT_ACTIVE != 0U
#error "Round060 original decoder import must remain completely dormant"
#endif

/*
 * All pointers have caller-owned, non-aliasing lifetimes for the synchronous
 * call. No original selected crypto_acomp or retired zswap-pool pointer is
 * stored or referenced. This symbol is never invoked by the probe module.
 */
static noinline __used int round060_pinned_original_decoder_reference(
	const struct swapz_zswap_import_record *record,
	const struct swapz_zswap_import_read_authority *authority,
	const swapz_u8 *compressed_bytes, swapz_u32 compressed_capacity,
	swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *output, swapz_u32 output_capacity,
	const swapz_u8 *independent_original_page)
{
	return swapz_zswap_import_decode(record, authority, compressed_bytes,
					compressed_capacity, scratch,
					scratch_capacity, output, output_capacity,
					independent_original_page);
}

/*
 * Root the entire REAL swapz_zswap_import_decode() call path in the final
 * module ELF even though module_init always rejects loading. The function
 * pointer's address relocation is emitted as read-only test data; it is not
 * an alternate decoder, an import admission switch or a runnable callback.
 * This pins only build-time code/symbol references, never live module refs.
 */
static typeof(round060_pinned_original_decoder_reference) *
	const round060_original_decoder_consumer_root __used =
		round060_pinned_original_decoder_reference;

#ifdef SWAPZ_ROUND060_MISSING_DECODER_EXPORT_NEGATIVE_TEST
/*
 * A deliberately UNEXPORTED test symbol must be rejected by the real
 * original Linux modpost; compile failure or a suppressed modpost error is
 * not a successful negative link test.
 */
extern int round060_unavailable_original_decoder_export(void);

static noinline __used int round060_unavailable_decoder_reference(void)
{
	return round060_unavailable_original_decoder_export();
}

/*
 * Keep the intentionally undefined relocation alive through the native
 * negative module link. A compiler failure is not a negative modpost PASS.
 */
static typeof(round060_unavailable_decoder_reference) *
	const round060_missing_decoder_export_root __used =
		round060_unavailable_decoder_reference;
#endif

static int __init round060_original_decoder_noauth_init(void)
{
	/* Strict source-only: no loaded kernel activation permission. */
	return -EOPNOTSUPP;
}

static void __exit round060_original_decoder_noauth_exit(void)
{
	/* No resource was allocated: this function is never run by CI. */
}

module_init(round060_original_decoder_noauth_init);
module_exit(round060_original_decoder_noauth_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Compile-only original LZO1X and LZ4 decoder GPL proof; no authorization");
