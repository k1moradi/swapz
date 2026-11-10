/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_SUPERBLOCK_H
#define SWAPZ_SUPERBLOCK_H

/*
 * Physical backing is an existing ordinary Linux SWAPSPACE2 partition.
 * The first 4096-byte page remains byte-for-byte owned by Linux swap and is
 * never a swapz metadata area. swapz allocates only from the following page.
 */
#define SWAPZ_SUPERBLOCK_BYTES 4096U
#define SWAPZ_LINUX_SWAP_MAGIC_BYTES 10U
#define SWAPZ_LINUX_SWAP_VERSION_OFFSET 1024U
#define SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET 1028U
#define SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET 1032U
#define SWAPZ_LINUX_SWAP_UUID_OFFSET 1036U
#define SWAPZ_LINUX_SWAP_UUID_BYTES 16U
#define SWAPZ_LINUX_SWAP_BAD_PAGE_LIST_OFFSET 1536U
#define SWAPZ_LINUX_SWAP_MAX_BAD_PAGES \
	((SWAPZ_SUPERBLOCK_BYTES - SWAPZ_LINUX_SWAP_MAGIC_BYTES - \
	  SWAPZ_LINUX_SWAP_BAD_PAGE_LIST_OFFSET) / sizeof(unsigned int))

struct swapz_linux_swap_layout {
	unsigned int last_page;
	unsigned int bad_pages;
	unsigned char byte_swapped;
};

static inline unsigned int swapz_sb_get_u32(const unsigned char *bytes)
{
	return (unsigned int)bytes[0] |
	       ((unsigned int)bytes[1] << 8) |
	       ((unsigned int)bytes[2] << 16) |
	       ((unsigned int)bytes[3] << 24);
}

static inline unsigned int swapz_sb_bswap_u32(unsigned int value)
{
	return ((value & 0x000000ffU) << 24) |
	       ((value & 0x0000ff00U) << 8) |
	       ((value & 0x00ff0000U) >> 8) |
	       ((value & 0xff000000U) >> 24);
}

static inline unsigned int swapz_sb_decode_u32(const unsigned char *bytes,
					       unsigned char byte_swapped)
{
	unsigned int value = swapz_sb_get_u32(bytes);

	return byte_swapped ? swapz_sb_bswap_u32(value) : value;
}

static inline unsigned int swapz_linux_swap_bad_page(
	const unsigned char *block, const struct swapz_linux_swap_layout *layout,
	unsigned int index)
{
	if (!block || !layout || index >= layout->bad_pages)
		return 0;
	return swapz_sb_decode_u32(
		block + SWAPZ_LINUX_SWAP_BAD_PAGE_LIST_OFFSET +
			index * sizeof(unsigned int),
		layout->byte_swapped);
}

/*
 * Parse the Linux v1 SWAPSPACE2 header without imposing swapz's allocator
 * geometry. Linux permits a declared area smaller than the block device,
 * optional bad-page entries, and the historical byte-swapped v1 encoding.
 * Callers decide which clean pages/segments are usable; this function never
 * modifies the header.
 */
static inline int swapz_linux_swap_header_parse(
	const unsigned char *block, unsigned long long device_bytes,
	struct swapz_linux_swap_layout *layout)
{
	static const unsigned char magic[SWAPZ_LINUX_SWAP_MAGIC_BYTES] = {
		'S', 'W', 'A', 'P', 'S', 'P', 'A', 'C', 'E', '2'
	};
	const unsigned long long complete_pages =
		device_bytes / SWAPZ_SUPERBLOCK_BYTES;
	struct swapz_linux_swap_layout parsed;
	unsigned int raw_version;
	unsigned int index;

	if (!block || complete_pages < 2U)
		return 0;
	for (index = 0; index < SWAPZ_LINUX_SWAP_MAGIC_BYTES; ++index)
		if (block[SWAPZ_SUPERBLOCK_BYTES -
			  SWAPZ_LINUX_SWAP_MAGIC_BYTES + index] != magic[index])
			return 0;

	raw_version = swapz_sb_get_u32(
		block + SWAPZ_LINUX_SWAP_VERSION_OFFSET);
	if (raw_version == 1U)
		parsed.byte_swapped = 0U;
	else if (swapz_sb_bswap_u32(raw_version) == 1U)
		parsed.byte_swapped = 1U;
	else
		return 0;

	parsed.last_page = swapz_sb_decode_u32(
		block + SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET,
		parsed.byte_swapped);
	parsed.bad_pages = swapz_sb_decode_u32(
		block + SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET,
		parsed.byte_swapped);
	if (!parsed.last_page ||
	    (unsigned long long)parsed.last_page >= complete_pages ||
	    parsed.bad_pages > SWAPZ_LINUX_SWAP_MAX_BAD_PAGES)
		return 0;

	for (index = 0; index < parsed.bad_pages; ++index) {
		unsigned int bad_page =
			swapz_linux_swap_bad_page(block, &parsed, index);

		/*
		 * Match Linux swapon semantics: duplicate listed pages are not a
		 * header-format error. Linux still charges every list entry from
		 * si->pages; swapz separately deduplicates contaminated segments
		 * when constructing its lower-data map.
		 */
		if (!bad_page || bad_page > parsed.last_page)
			return 0;
	}
	if (layout)
		*layout = parsed;
	return 1;
}

static inline int swapz_linux_swap_segment_has_bad_page(
	const unsigned char *block, const struct swapz_linux_swap_layout *layout,
	unsigned int segment_pages, unsigned int raw_segment)
{
	unsigned int index;

	if (!block || !layout || !segment_pages)
		return 1;
	for (index = 0; index < layout->bad_pages; ++index) {
		unsigned int bad_page =
			swapz_linux_swap_bad_page(block, layout, index);

		if (bad_page &&
		    (bad_page - 1U) / segment_pages == raw_segment)
			return 1;
	}
	return 0;
}

static inline unsigned int swapz_linux_swap_clean_segment_count(
	const unsigned char *block, const struct swapz_linux_swap_layout *layout,
	unsigned int segment_pages)
{
	unsigned int full_segments;
	unsigned int contaminated = 0;
	unsigned int index;

	if (!block || !layout || !segment_pages)
		return 0;
	full_segments = layout->last_page / segment_pages;
	for (index = 0; index < layout->bad_pages; ++index) {
		unsigned int bad_page =
			swapz_linux_swap_bad_page(block, layout, index);
		unsigned int raw_segment;
		unsigned int previous;
		int already_counted = 0;

		if (!bad_page)
			return 0;
		raw_segment = (bad_page - 1U) / segment_pages;
		/* A bad page in the incomplete data tail costs no usable segment. */
		if (raw_segment >= full_segments)
			continue;
		for (previous = 0; previous < index; ++previous) {
			unsigned int earlier =
				swapz_linux_swap_bad_page(block, layout, previous);

			if (earlier &&
			    (earlier - 1U) / segment_pages == raw_segment) {
				already_counted = 1;
				break;
			}
		}
		if (!already_counted)
			contaminated++;
	}
	return contaminated <= full_segments ?
		full_segments - contaminated : 0;
}

/*
 * Strict contiguous-layout helper retained for mapper/test fixtures that need
 * the historical full-device shape. Physical backing admission uses the full
 * parser plus the RAM clean-segment map and must not call this stricter helper.
 */
static inline int swapz_linux_swap_header_valid(
	const unsigned char *block, unsigned long long device_bytes)
{
	struct swapz_linux_swap_layout layout;
	const unsigned long long complete_pages =
		device_bytes / SWAPZ_SUPERBLOCK_BYTES;

	if (!swapz_linux_swap_header_parse(block, device_bytes, &layout))
		return 0;
	return !layout.bad_pages &&
	       (unsigned long long)layout.last_page == complete_pages - 1U;
}

#endif
