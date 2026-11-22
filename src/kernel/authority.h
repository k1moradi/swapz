/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_EXTENT_AUTHORITY_H
#define SWAPZ_EXTENT_AUTHORITY_H
#if defined(SWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST) && \
    !defined(SWAPZ_ROUND066_IMPORT_DISK_TEST)
#error "round067 payload verification requires the dormant round066 allocator"
#endif
#include "codec.h"

#define SWAPZ_SEGMENT_BLOCKS 256U
#define SWAPZ_FOREGROUND_HEADROOM_BLOCKS SWAPZ_SEGMENT_BLOCKS
#define SWAPZ_LINUX_SWAP_HEADER_BLOCKS 1U
#define SWAPZ_MAP_RECORD_INDEX_MASK 0x3fU
#define SWAPZ_MAP_DELTA64_FLAG 0x80U
/* Set only together with SWAPZ_MAP_DELTA64_FLAG (DELTA64_SHUF8 records). */
#define SWAPZ_MAP_SHUF8_FLAG 0x40U

/*
 * Shared admission window for kernel authority and userspace mapper planning.
 * Callers validate the physical geometry and addressability appropriate to
 * their execution environment before using this capacity-only predicate.
 */
static inline int swapz_authority_capacity_window(
	swapz_u32 logical_pages, swapz_u32 physical_blocks,
	swapz_u32 *reserve_blocks)
{
	swapz_u32 foreground_blocks;
	swapz_u32 reserve;
	swapz_u64 required_blocks;

	if (!logical_pages)
		return 0;
	/* Division before addition keeps ceil(logical_pages / 8) in u32. */
	reserve = (logical_pages / 8U) + (logical_pages % 8U != 0U);
	if (reserve < 2U * SWAPZ_SEGMENT_BLOCKS)
		reserve = 2U * SWAPZ_SEGMENT_BLOCKS;
	if (reserve >= physical_blocks)
		return 0;
	foreground_blocks = ((physical_blocks - reserve) /
			     SWAPZ_SEGMENT_BLOCKS) * SWAPZ_SEGMENT_BLOCKS;
	/*
	 * The rotating GC reserve is not foreground allocation authority.
	 * Retain one complete ordinary segment so a 100%-RAW logical fill can
	 * publish its first COW overwrite before any victim becomes reclaimable.
	 * Widen before addition so a near-u32 logical count cannot wrap.
	 */
	required_blocks = (swapz_u64)logical_pages +
			  SWAPZ_FOREGROUND_HEADROOM_BLOCKS;
	if (required_blocks > foreground_blocks)
		return 0;
	if (reserve_blocks)
		*reserve_blocks = reserve;
	return 1;
}

/*
 * Experimental worker-owned volatile mapping authority. Caller provisions
 * all arrays. It does NOT implement physical recycling or GC. On failure,
 * an allocated extent is permanently abandoned: NEVER reuse a possibly
 * partially written location before a separately verified reclaim path.
 */
struct swapz_map {
	swapz_u32 start_block;
	swapz_u32 generation;
	/* These interpretations are exclusive: raw mappings keep their volatile
	 * CRC here; compressed mappings keep their zero-extended on-extent payload
	 * offset. The u32 width initializes the full union in either encoding. */
	union {
		swapz_u32 raw_crc32c;
		swapz_u32 payload_offset;
	};
	/* Compressed payload integrity is authoritative RAM state. RAW mappings
	 * continue to use raw_crc32c above; this field remains zero for RAW. */
	swapz_u32 payload_crc32c;
	/* Volatile compressed payload bytes (4096 for raw). Required for
	 * real live-byte GC victim selection without reading every extent. */
	swapz_u16 payload_length;
	swapz_u8 record_index;
	/* One byte stores legal extent size plus raw/valid/shared state. */
	union {
		swapz_u8 state;
		struct {
			swapz_u8 extent_blocks:3;
			swapz_u8 raw:1;
			swapz_u8 valid:1;
			/* Multi-record compressed extents retain this on every sibling. */
			swapz_u8 shared_extent:1;
			swapz_u8 reserved:2;
		};
	};
};

_Static_assert(sizeof(struct swapz_map) == 20,
	       "swapz_map must stay compact for full-capacity RAM metadata");

static inline swapz_u8 swapz_map_record_index(const struct swapz_map *map)
{
	return map->record_index & SWAPZ_MAP_RECORD_INDEX_MASK;
}

static inline swapz_u8 swapz_map_encoding(const struct swapz_map *map)
{
	if (!(map->record_index & SWAPZ_MAP_DELTA64_FLAG))
		return SWAPZ_ENCODING_LZ4;
	return (map->record_index & SWAPZ_MAP_SHUF8_FLAG) ?
		SWAPZ_ENCODING_DELTA64_SHUF8 : SWAPZ_ENCODING_DELTA64;
}

static inline swapz_u8 swapz_map_pack_record_index(swapz_u8 index,
						   swapz_u8 encoding)
{
	return (index & SWAPZ_MAP_RECORD_INDEX_MASK) |
		(encoding == SWAPZ_ENCODING_DELTA64 ? SWAPZ_MAP_DELTA64_FLAG :
		 encoding == SWAPZ_ENCODING_DELTA64_SHUF8 ?
		 SWAPZ_MAP_DELTA64_FLAG | SWAPZ_MAP_SHUF8_FLAG : 0U);
}

struct swapz_tx_record {
	swapz_u32 logical_page;
	swapz_u32 generation;
	/* Compressed descriptor authority is immutable RAM transaction state once
	 * bound. Legacy serialized fixtures are userspace-test compatibility only
	 * and are never a production lower-media format. */
	swapz_u32 payload_crc32c;
	swapz_u16 payload_offset;
	swapz_u16 payload_length;
	swapz_u8 encoding;
	swapz_u8 compressed_metadata_bound;
	swapz_u8 reserved[2];
};

struct swapz_tx {
	swapz_u32 start_block;
	swapz_u32 sequence;
	swapz_u8 extent_blocks;
	swapz_u8 count;
	/* Explicit representation authority. Production requires one: lower media
	 * contains payload bytes and deterministic zero padding only. Zero is
	 * reserved for userspace-only legacy fixture compatibility. */
	swapz_u8 compressed_data_only;
	swapz_u8 reserved;
	struct swapz_tx_record records[SWAPZ_MAX_RECORDS];
};

/*
 * Serialized publication-preflight scratch. Keeping these bounded aggregates
 * in the authority object avoids multi-kilobyte kernel stack frames while
 * eliminating repeated authority scans and temporary global GC mutations.
 */
struct swapz_finish_extent_delta {
	swapz_u32 start_block;
	swapz_u8 references;
	swapz_u8 reserved[3];
};

struct swapz_finish_segment_delta {
	swapz_u32 segment;
	swapz_u32 live_bytes;
	swapz_u32 io_cost;
	swapz_u16 min_live_blocks;
	swapz_u8 mapped_pages;
	swapz_u8 reserved;
};

typedef int (*swapz_dead_segment_recycle_fn)(void *opaque,
					      swapz_u32 segment);

struct swapz_authority {
	/*
	 * The ordered DM owner exclusively mutates this array and its sidecars;
	 * full-map proof calls may cond_resched() under its sleepable mutex.
	 * Never call proof-bearing authority operations with IRQs disabled, in
	 * RCU read-side sections or under a spinlock. No separate reader may
	 * mutate this memory while a proof is suspended.
	 */
	struct swapz_map *maps;		/* [logical_pages] */
	swapz_u16 *live_records;		/* [physical_blocks]; extent START */
	swapz_u8 *extent_classes;		/* [physical_blocks]; extent START */
	/* Transaction sequence is extent-scoped, not page-scoped. Store its
	 * offset from the first indexed compressed extent in each 1MiB segment. */
	swapz_u8 *extent_sequence_delta;	/* [physical_blocks]; extent START */
	swapz_u32 *segment_sequence_base;	/* [physical_segments] */
	swapz_u32 sequence_segment_count;
	swapz_u32 logical_pages;
	swapz_u32 physical_blocks;
	swapz_u32 reserve_blocks;
	/*
	 * Optional production GC segment roles: one byte per 1MiB segment.
	 * 1 = foreground writable; 0 = reserved GC destination. Roles are
	 * exchanged ONLY after a fully verified live relocation. A fixed
	 * numeric "reserve tail" is not sustainable across GC cycles.
	 * NULL retains the original research allocator/test behavior.
	 */
	swapz_u8 *segment_foreground;
	/* Optional exact logical-map occupancy per 1MiB segment. Nonzero counts
	 * reject reuse in O(1); a previously claimed zero candidate still needs
	 * an independent authoritative-map proof before irreversible reclaim. */
	swapz_u32 *segment_mapped_pages;
	/*
	 * Optional monotonic logical segment-open counts. The exact value is
	 * allocator telemetry, not physical NAND wear. Because claim increments
	 * before any extent can be staged and the count never decreases, zero is
	 * also the production allocator's "never previously claimed" witness.
	 * This is only a cached hint: even a false-zero witness cannot bypass
	 * the authoritative full logical-map scan before segment reuse.
	 */
	swapz_u32 *segment_program_counts;
	/* Optional exact logical-page membership lists per physical segment. */
	swapz_u32 *segment_first_page;
	swapz_u32 *segment_last_page;
	swapz_u32 *page_prev_in_segment;
	swapz_u32 *page_next_in_segment;
	/* Optional per-segment GC scores maintained with map publication. */
	swapz_u32 *segment_gc_live_bytes;
	swapz_u32 *segment_gc_io_cost;
	swapz_u16 *segment_gc_min_live_blocks;
	swapz_u32 segment_count;
	swapz_u32 gc_destination;
	swapz_u32 next_block;
	swapz_u32 open_segment;		/* UINT32_MAX before the first allocation */
	swapz_u32 next_segment_probe;
	/* Placement/allocation evidence only; never participates in policy. */
	unsigned long long alignment_hole_blocks_foreground;
	unsigned long long alignment_hole_blocks_gc;
	unsigned long long segment_tail_waste_blocks_foreground;
	unsigned long long segment_tail_waste_blocks_gc;
	unsigned long long alloc_probe_segments;
	unsigned long long alloc_probe_full_scans;
	unsigned long long alloc_probe_wall_ns;
	swapz_u32 recycled_dead_segments;
	/*
	 * Optional caller hook invoked only after a previously written 1MiB
	 * segment is proven wholly dead and immediately before allocator reuse.
	 * A negative return blocks reuse without mutating authority state.
	 */
	swapz_dead_segment_recycle_fn dead_segment_recycle;
	void *dead_segment_recycle_opaque;
	/*
	 * Runtime-only opt-in. Preserves old research append-only semantics by
	 * default; the separately reviewed Device Mapper target enables this.
	 */
	swapz_u8 reuse_dead_segments;
	/* Only the serialized GC worker may set this, never foreground. */
	swapz_u8 gc_allocation;
	/* GC may NOT allocate into the paused foreground OPEN segment or
	 * the victim being relocated, even if its current live count is zero. */
	swapz_u32 gc_forbidden_open;
	swapz_u32 gc_forbidden_victim;
	swapz_u32 next_sequence;
	swapz_u32 abandoned_blocks;
	swapz_u32 committed_blocks;
	swapz_u32 active_start;
	swapz_u32 active_sequence;
	swapz_u8 active_blocks;
	swapz_u8 active_count;
	/*
	 * Worker-owned immutable staged descriptor snapshot. The caller may
	 * retain or mutate its returned swapz_tx, but publication must never trust
	 * caller-supplied record identities or generations absent this match.
	 */
	struct swapz_tx active_tx;
	int in_flight;
	/*
	 * Bounded writer-only group: immutable transactions are kept in the
	 * engine, and none are published until a combined lower write finishes.
	 * Unlike in_flight, batch_pending can represent up to 64 RESERVED
	 * extents in ONE physical segment, but zero committed mappings.
	 */
	swapz_u8 batch_pending;
	swapz_u8 batch_replaying;
	swapz_u8 batch_stage_allowed;
	swapz_u8 batch_consumed;
	swapz_u32 batch_segment;
	swapz_u32 batch_first_sequence;
	/* CRC of the exact immutable staged transaction snapshots,
	 * including record identities and generations. A forged caller
	 * snapshot can never publish an unrelated page into a batch. */
	swapz_u32 batch_hashes[SWAPZ_MAX_RECORDS];
	/* Representation is part of the immutable paused identity. A caller-side
	 * raw/compressed flag is never sufficient publication authority. */
	swapz_u8 batch_raw[SWAPZ_MAX_RECORDS];
	/* Diagnostic only: exact wall time inside final publication payload CRC32C
	 * calls. Native builds leave this at zero; it never affects authority. */
	unsigned long long publish_crc_wall_ns;
	/* Exact wall time hashing immutable paused transaction snapshots.
	 * This measures the existing full-struct CRC only; it changes no
	 * transaction identity, protection scope or publication semantics. */
	unsigned long long batch_snapshot_crc_wall_ns;
	/* Phase split for the same unchanged full-transaction snapshot hash.
	 * pause is outside engine publish; resume is inside publish authority. */
	unsigned long long batch_pause_crc_wall_ns;
	unsigned long long batch_resume_crc_wall_ns;
	/* Single ordered authority owner; never shared across publications. */
	struct swapz_finish_extent_delta
		finish_extent_deltas[SWAPZ_MAX_RECORDS];
	struct swapz_finish_segment_delta
		finish_segment_deltas[SWAPZ_MAX_RECORDS];
};

/*
 * Enable rotating GC reserve ownership, using a preallocated segment_count
 * byte array. Must be called on a fresh authority before staging any write.
 * Initially first physical-reserve segments are foreground and the tail
 * is reserve; after successful GC, victim and destination exchange roles.
 */
int swapz_enable_segment_rotation(struct swapz_authority *authority,
				swapz_u8 *segment_roles,
				swapz_u32 segment_count);
/* Attach a caller-owned exact mapping-count sidecar on a fresh rotating
 * authority. Native/research callers may omit it and retain full-map checks. */
int swapz_enable_segment_mapping_counts(struct swapz_authority *authority,
				      swapz_u32 *segment_mapped_pages,
				      swapz_u32 segment_count);
int swapz_enable_segment_program_counts(struct swapz_authority *authority,
				      swapz_u32 *segment_program_counts,
				      swapz_u32 segment_count);
int swapz_enable_segment_page_lists(struct swapz_authority *authority,
				  swapz_u32 *segment_first_page,
				  swapz_u32 *segment_last_page,
				  swapz_u32 *page_prev_in_segment,
				  swapz_u32 *page_next_in_segment,
				  swapz_u32 segment_count,
				  swapz_u32 logical_pages);
int swapz_enable_segment_gc_accounting(struct swapz_authority *authority,
				     swapz_u32 *live_bytes,
				     swapz_u32 *io_cost,
				     swapz_u16 *min_live_blocks,
				     swapz_u32 segment_count);
/* Begin GC into ONE entirely dead reserve segment (not a foreground one).
 * Caller preserves the foreground cursor until commit; no nested GC. */
int swapz_gc_begin_rotation(struct swapz_authority *authority, swapz_u32 victim);
/*
 * Recovery-only bounded roll-forward. The current destination must be full and
 * the original victim must already be wholly dead. Rebind that dead victim as
 * the next reserve destination and make the full destination the next victim;
 * GC ownership remains active throughout and no mapping/generation is changed.
 */
int swapz_gc_roll_forward_rotation(struct swapz_authority *authority,
				   swapz_u32 exhausted_destination);
/*
 * Recovery-only destination advance for a 2/4-block extent that cannot fit
 * the current destination tail while the original victim is still live.
 * Claims another wholly-dead reserve before changing the blocked destination
 * role; failure leaves the authenticated rotation cursor/roles unchanged.
 */
int swapz_gc_advance_rotation_destination(struct swapz_authority *authority,
					 swapz_u32 blocked_destination);
/* Swap physical roles ONLY after the source victim is wholly dead.
 * Leaves foreground cursor inside new (formerly reserve) destination. */
int swapz_gc_commit_rotation(struct swapz_authority *authority, swapz_u32 victim);

struct swapz_authority_geometry {
	/* Caller-provided data blocks after protected Linux swap page zero and
	 * segment rounding. Production has no swapz on-media header. */
	swapz_u32 usable_physical_blocks;
	/* GC reserve at maximum_logical_pages; never includes foreground headroom. */
	swapz_u32 gc_reserve_blocks;
	/* Ordinary COW bootstrap space retained separately from the GC reserve. */
	swapz_u32 required_foreground_headroom_blocks;
	/* Largest logical page count admitted on this build's integer widths. */
	swapz_u32 maximum_logical_pages;
	swapz_u64 logical_mapper_bytes;
	/* Linux swap page zero is metadata and is not usable anonymous-page swap. */
	swapz_u64 linux_usable_swap_bytes;
};

/*
 * Allocation-free capacity calculator for constructor/userspace preflight.
 * Returns the maximum logical geometry admitted by the same policy used by
 * swapz_authority_validate_geometry(), including this build's size_t limits.
 */
int swapz_authority_capacity(swapz_u32 physical_blocks,
			     struct swapz_authority_geometry *geometry);

/*
 * Single allocation-free geometry admission gate. swapz_authority_init()
 * rechecks this exact policy before touching caller memory. The GC reserve is
 * max(ceil(logical_pages / 8), two segments), and one additional foreground
 * segment is retained for RAW copy-on-write bootstrap. Returns -EOVERFLOW if a
 * capacity-index byte length exceeds size_t; successful admission does not
 * prove allocation feasibility. reserve_blocks may be NULL when only admission
 * is needed and remains untouched on failure.
 */
int swapz_authority_validate_geometry(swapz_u32 logical_pages,
				      swapz_u32 physical_blocks,
				      swapz_u32 *reserve_blocks);
/* Returns -ENOSPC unless capacity supports pages + COW headroom + GC reserve. */
int swapz_authority_init(struct swapz_authority *authority,
		       struct swapz_map *maps, swapz_u16 *live_records,
		       swapz_u8 *extent_classes, swapz_u32 logical_pages,
		       swapz_u32 physical_blocks);
/* Install the compact per-extent sequence index before staging any writes. */
int swapz_enable_extent_sequence_index(struct swapz_authority *authority,
				       swapz_u8 *sequence_delta,
				       swapz_u32 *segment_sequence_base,
				       swapz_u32 segment_count);
/* Resolve the authoritative volatile RAM sequence for a live extent start. */
int swapz_extent_sequence_lookup(const struct swapz_authority *authority,
				swapz_u32 start_block,
				swapz_u32 *sequence);
/* Reserves physical blocks; single worker, one pending transaction. */
int swapz_stage(struct swapz_authority *authority, const swapz_u32 *logical_pages,
	      swapz_u8 count, swapz_u8 blocks, struct swapz_tx *out);
/* Bind one compressed descriptor into both caller and authority-owned staged
 * transaction snapshots before lower submission. Rebinding different metadata
 * is stale-handle corruption; RAW transactions leave these fields unbound. */
int swapz_bind_compressed_record(struct swapz_authority *authority,
			       struct swapz_tx *transaction,
			       swapz_u8 record_index,
			       swapz_u16 payload_offset,
			       swapz_u16 payload_length,
			       swapz_u32 payload_crc32c,
			       swapz_u8 encoding);
/* Seal the compressed transaction representation after every descriptor has
 * been bound. This is immutable publication authority, not a media probe. */
int swapz_mark_compressed_data_only(struct swapz_authority *authority,
				    struct swapz_tx *transaction);
/*
 * Read-only: 1 only if staging one `blocks` extent now reuses the open segment
 * with no segment pick/recycle (synchronous DISCARD callback) and no -ENOSPC.
 * Lets a caller that may not wait for lower I/O prove allocation is I/O-free.
 */
int swapz_open_segment_fits(const struct swapz_authority *authority,
			    swapz_u8 blocks);
/*
 * IMPORTANT: success requires full extent I/O completion (not submission).
 * The caller must provide the exact completed on-media bytes. Verify all
 * record CRC32Cs and old-authority invariants BEFORE publishing any mapping.
 */
int swapz_finish(struct swapz_authority *authority, const struct swapz_tx *tx,
	       const void *extent, swapz_u32 bytes_total,
	       swapz_u8 completed_blocks, int io_error);
/*
 * Serialized batched-lower-write transition: transfer the active stage
 * to a caller-owned immutable swapz_tx snapshot without publishing mappings.
 * Stage further extents ONLY inside the same physical segment. On lower
 * completion restore snapshots in sequence and use normal swapz_finish().
 * Failed lower writes require resume+abort of every snapshot. No upper BIO
 * may be acknowledged during this protocol.
 */
int swapz_stage_batch(struct swapz_authority *authority,
		    const swapz_u32 *logical_pages, swapz_u8 count,
		    swapz_u8 blocks, struct swapz_tx *out);
/* Private production batch fast path after one complete window-wide
 * uniqueness proof. Range and generation checks remain fail-closed. */
int swapz_stage_batch_unique(struct swapz_authority *authority,
			   const swapz_u32 *logical_pages, swapz_u8 count,
			   swapz_u8 blocks, struct swapz_tx *out);
int swapz_batch_pause(struct swapz_authority *authority, const struct swapz_tx *tx);
/* Engine-owned variant binds the physical representation to the same paused
 * transaction identity before lower submission. */
int swapz_batch_pause_run(struct swapz_authority *authority,
			 const struct swapz_tx *tx, swapz_u8 raw);
/*
 * Drop only the newest paused snapshot before any replay has started.
 * This is the fail-closed rollback primitive for a second prepared lower run:
 * older snapshots remain pending and authoritative mappings stay unchanged.
 */
int swapz_batch_abort_tail(struct swapz_authority *authority,
			  const struct swapz_tx *tx);
/* Authenticate the entire oldest paused lower run before ANY replay or map
 * publication. On mismatch, leave every reservation pending/quarantined;
 * the ordered caller must fail the run, never retry it as newly available. */
int swapz_batch_authenticate_run(struct swapz_authority *authority,
				 const struct swapz_tx *transactions,
				 const swapz_u8 *raw_entries,
				 swapz_u8 extent_count);
int swapz_batch_resume(struct swapz_authority *authority, const struct swapz_tx *tx);
/* Cancel an abandoned physical region; old mappings remain authoritative. */
int swapz_abort(struct swapz_authority *authority, const struct swapz_tx *tx);
/*
 * Raw 4KiB fallback occupies one whole aligned block and has no serialized
 * lower-media descriptor. Its identity, generation and CRC remain volatile
 * RAM authority. The caller must stage exactly one record / one block and
 * call finish_raw only after the WHOLE lower write completes.
 */
int swapz_finish_raw(struct swapz_authority *authority, const struct swapz_tx *tx,
		   const void *raw_page, swapz_u8 completed_blocks, int io_error);
/* Check raw payload integrity against volatile authoritative CRC. */
int swapz_verify_raw(const struct swapz_authority *authority,
		   swapz_u32 logical_page, const void *raw_page);
/* RAM-metadata compressed READ authority. The caller supplies bytes at the
 * observed payload offset; no serialized extent header/descriptor is trusted
 * or required. Mapping identity is rechecked before payload CRC validation. */
int swapz_read_authoritative_payload(const struct swapz_authority *authority,
				   swapz_u32 logical_page,
				   const struct swapz_map *observed,
				   const swapz_u8 *stored,
				   const swapz_u8 **payload);
/*
 * Allocation-free multi-page DISCARD preflight. It temporarily models cached
 * authority accounting under the serialized owner and restores it before
 * return; success authorizes only the subsequent ordinary discard-page calls.
 */
int swapz_prevalidate_discard_range(struct swapz_authority *authority,
				    swapz_u32 first_logical,
				    swapz_u32 page_count);
/* Serialized explicit logical discard: invalidate and advance generation. */
int swapz_discard_page(struct swapz_authority *authority, swapz_u32 logical_page);
/*
 * Legacy userspace-fixture compatibility after swapz_peek() validates a
 * serialized synthetic extent. Production kernel compressed READs use
 * swapz_read_authoritative_payload() from volatile RAM mapping authority and
 * never parse lower-media swapz metadata.
 */
int swapz_read_authoritative_peeked_payload(
				  const struct swapz_authority *authority,
				  swapz_u32 logical_page,
				  const struct swapz_map *observed,
				  const void *metadata, swapz_u32 bytes_total,
				  const struct swapz_decoded *peeked,
				  const swapz_u8 *stored,
				  const swapz_u8 **payload);
int swapz_read_authoritative_peeked(const struct swapz_authority *authority,
				  swapz_u32 logical_page,
				  const struct swapz_map *observed,
				  const void *extent, swapz_u32 bytes_total,
				  const struct swapz_decoded *peeked,
				  const swapz_u8 **payload);

/*
 * Round059 owner-only compressed-import witness. Entirely absent with the
 * diagnostic guard undefined; never changes the 20-byte production map ABI.
 * The witness is NOT map authority, native source ownership, durable I/O or
 * permission to ACK. All methods run under ONE serialized owner, including
 * pin/put. A future concurrent reader requires its own reviewed synchronization.
 */
#define SWAPZ_AUTHORITY_IMPORT_ACTIVE 0U
#if defined(SWAPZ_ROUND059_AUTHORITY_IMPORT_LIFETIME_TEST) || \
    defined(SWAPZ_ROUND066_IMPORT_DISK_TEST)
#define SWAPZ_AUTHORITY_IMPORT_CAPACITY 8U
#define SWAPZ_AUTHORITY_IMPORT_STAGING_LIMIT 2U
#define SWAPZ_AUTHORITY_IMPORT_LZ4 1U
#define SWAPZ_AUTHORITY_IMPORT_LZO1X 2U

enum swapz_authority_import_state {
	SWAPZ_AUTHORITY_IMPORT_EMPTY = 0,
	SWAPZ_AUTHORITY_IMPORT_RESERVED,
	SWAPZ_AUTHORITY_IMPORT_SUBMITTED,
	SWAPZ_AUTHORITY_IMPORT_LOWER_CONFIRMED,
	SWAPZ_AUTHORITY_IMPORT_QUARANTINED,
	SWAPZ_AUTHORITY_IMPORT_RETIRED,
};

struct swapz_authority_import_spec {
	swapz_u64 source_swap_slot;
	swapz_u64 source_entry_identity;
	swapz_u64 source_store_generation;
	swapz_u64 gc_epoch;
	swapz_u32 logical_page;
	swapz_u32 compressed_crc32c;
	swapz_u16 compressed_length;
	swapz_u8 codec;
	swapz_u8 codec_version;
	swapz_u8 requested_fua;
	swapz_u8 original_sha256[32];
};

struct swapz_authority_import_record {
	struct swapz_authority_import_spec spec;
	swapz_u64 ticket;
	swapz_u32 generation;
	swapz_u32 start_block; /* Data-block relative; first physical 4KiB excluded. */
	swapz_u32 sequence;
	swapz_u8 extent_blocks;
	swapz_u8 state;
	swapz_u8 reader_pins; /* Single-owner bounded retained witness, NOT upper READ. */
	swapz_u8 upper_ack_count; /* ALWAYS zero until a separately owned DM interface. */
};

struct swapz_authority_import_pool {
	const struct swapz_authority *authority;
	struct swapz_authority_import_record
		records[SWAPZ_AUTHORITY_IMPORT_CAPACITY];
	swapz_u64 next_ticket;
	swapz_u8 staged;
	swapz_u8 closing;
};

void swapz_authority_import_init(struct swapz_authority_import_pool *pool,
				const struct swapz_authority *authority);
int swapz_authority_import_begin(struct swapz_authority_import_pool *pool,
				 const struct swapz_tx *transaction,
				 const struct swapz_authority_import_spec *spec,
				 swapz_u64 *ticket);
int swapz_authority_import_submit(struct swapz_authority_import_pool *pool,
				  swapz_u64 ticket);
int swapz_authority_import_lower_done(struct swapz_authority_import_pool *pool,
				      swapz_u64 ticket, int lower_error,
				      swapz_u8 completed_blocks,
				      int flush_completed);
int swapz_authority_import_try_publish(struct swapz_authority_import_pool *pool,
				       swapz_u64 ticket);
int swapz_authority_import_pin_witness(struct swapz_authority_import_pool *pool,
				       swapz_u64 ticket,
				       struct swapz_authority_import_spec *view);
int swapz_authority_import_put_witness(struct swapz_authority_import_pool *pool,
				       swapz_u64 ticket);
int swapz_authority_import_gc_move(struct swapz_authority_import_pool *pool,
				   swapz_u64 ticket, swapz_u64 next_gc_epoch);
int swapz_authority_import_abort(struct swapz_authority_import_pool *pool,
				 swapz_u64 ticket);
int swapz_authority_import_close(struct swapz_authority_import_pool *pool);

/*
 * Round066 isolated DISK-side allocation owner. This is not the diagnostic
 * Round059 witness, nor a production map, decoder, DMA, BIO or ACK interface.
 * All methods run only under the same serialized/sleepable authority owner.
 * Caller allocates this fixed-size object; no heap/stack hot-path buffers.
 * A retained reader pin keeps the ORIGINAL extent's real live_records start
 * occupied until its final put, including across a modeled GC replacement.
 */
#if defined(SWAPZ_ROUND066_IMPORT_DISK_TEST)
#define SWAPZ_IMPORT_DISK_ACTIVE 0U
#define SWAPZ_IMPORT_DISK_CAPACITY 8U

enum swapz_import_disk_state {
	SWAPZ_IMPORT_DISK_EMPTY = 0,
	SWAPZ_IMPORT_DISK_RESERVED,
	SWAPZ_IMPORT_DISK_SUBMITTED,
	SWAPZ_IMPORT_DISK_QUARANTINED,
	SWAPZ_IMPORT_DISK_OWNED,
	SWAPZ_IMPORT_DISK_RETIRED,
};

struct swapz_import_disk_record {
	struct swapz_authority_import_spec spec; /* Native codec is NOT swapz LZ4. */
	swapz_u64 ticket;
	swapz_u64 replaces_ticket; /* Exact pinned old ownership, not a pointer. */
	swapz_u32 start_block;
	swapz_u32 sequence;
	swapz_u32 ordinary_generation;
	swapz_u8 extent_blocks;
	swapz_u8 state;
	swapz_u8 reader_pins;
	swapz_u8 live_owned;
};

struct swapz_import_disk_pool {
	struct swapz_authority *authority;
	struct swapz_import_disk_record records[SWAPZ_IMPORT_DISK_CAPACITY];
	swapz_u64 next_ticket;
	swapz_u8 closing;
};

struct swapz_import_disk_view {
	struct swapz_authority_import_spec spec;
	swapz_u64 ticket;
	swapz_u32 start_block;
	swapz_u32 sequence;
	swapz_u32 ordinary_generation;
	swapz_u8 extent_blocks;
};

/* Bound the entire optional owner; zero additional bytes in normal kernels. */
_Static_assert(sizeof(struct swapz_import_disk_pool) <= 1536U,
	       "imported test-only allocation owner exceeds fixed RAM budget");

void swapz_import_disk_init(struct swapz_import_disk_pool *pool,
			    struct swapz_authority *authority);
/* Claims an ACTUAL swapz_stage reservation, not a parallel extent allocator.
 * replaces_ticket=0 for a fresh isolated mapping; a nonzero live ticket is
 * mandatory for a modeled GC replacement with increasing gc_epoch. */
int swapz_import_disk_stage(struct swapz_import_disk_pool *pool,
			    const struct swapz_authority_import_spec *spec,
			    swapz_u8 extent_blocks, swapz_u64 replaces_ticket,
			    struct swapz_tx *transaction, swapz_u64 *ticket);
int swapz_import_disk_submit(struct swapz_import_disk_pool *pool,
			     swapz_u64 ticket);
/* All lower completion / FUA / flush results here are TEST-SUPPLIED receipts.
 * This never submits a BIO or verifies physical durable storage. */
int swapz_import_disk_complete(struct swapz_import_disk_pool *pool,
			       swapz_u64 ticket,
			       const struct swapz_tx *transaction,
			       int lower_error, swapz_u8 completed_blocks,
			       int flush_completed);
/* Returns a retained VOLATILE map snapshot, not a production upper READ. */
int swapz_import_disk_pin(struct swapz_import_disk_pool *pool,
			  swapz_u64 ticket, struct swapz_import_disk_view *view);
int swapz_import_disk_put(struct swapz_import_disk_pool *pool,
			  swapz_u64 ticket);
int swapz_import_disk_retire(struct swapz_import_disk_pool *pool,
			     swapz_u64 ticket);
int swapz_import_disk_abort(struct swapz_import_disk_pool *pool,
			    swapz_u64 ticket);
/* Closing fences new work; submitted callbacks and retained readers drain
 * before caller may free the pool or the authority arrays. */
int swapz_import_disk_close(struct swapz_import_disk_pool *pool);

#if defined(SWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST)
/*
 * Round067: payload-only memory-backed lower test, layered on the ACTUAL
 * Round066 reservation/physical pin owner. Bytes remain in caller-owned
 * contiguous RAM (DATA index start_block, physical index start_block+1).
 * Neither receipt nor this reader is an authenticated native source BIO,
 * physical FUA, device READ, decoder-provider lease or upper ACK.
 *
 * The caller MUST hold the same ordered authority owner for every call.
 * For read_pinned, the caller already holds a successful pin() and retains
 * it until it finishes the independently decoded full page.
 */
int swapz_import_disk_complete_payload(struct swapz_import_disk_pool *pool,
					swapz_u64 ticket,
					const struct swapz_tx *transaction,
					const swapz_u8 *lower_extent,
					swapz_u32 actual_extent_bytes,
					int lower_error, swapz_u8 completed_blocks,
					int flush_completed);
int swapz_import_disk_read_pinned(struct swapz_import_disk_pool *pool,
				  const struct swapz_import_disk_view *view,
				  const swapz_u8 *lower_extent,
				  swapz_u32 actual_read_bytes,
				  swapz_u8 *compressed_destination,
				  swapz_u32 destination_capacity);

#if defined(SWAPZ_ROUND068_IMPORT_LOWER_BIO_TEST)
/*
 * The original pinned c339f4010dea8b0d754f84ace70cd1b089878ef8
 * include/linux/blk_types.h uses REQ_OP_READ=0, WRITE=1, FLUSH=2,
 * REQ_FUA bit17 and REQ_PREFLUSH bit18. The native KUnit separately
 * static-asserts these exact flag values against the ORIGINAL Linux types.
 * Host fixture requests have the same scalar layout but are NOT kernel BIOs.
 */
#define SWAPZ_IMPORT_LOWER_BIO_ACTIVE 0U
#define SWAPZ_IMPORT_LOWER_OP_READ 0U
#define SWAPZ_IMPORT_LOWER_OP_WRITE 1U
#define SWAPZ_IMPORT_LOWER_OP_FLUSH 2U
#define SWAPZ_IMPORT_LOWER_REQ_FUA (1U << 17U)
#define SWAPZ_IMPORT_LOWER_REQ_PREFLUSH (1U << 18U)
#define SWAPZ_IMPORT_LOWER_SECTORS_PER_BLOCK (SWAPZ_BLOCK_BYTES / 512U)

enum swapz_import_lower_phase {
	SWAPZ_IMPORT_LOWER_IDLE = 0,
	SWAPZ_IMPORT_LOWER_WRITE_PENDING,
	SWAPZ_IMPORT_LOWER_POSTFLUSH_PENDING,
	SWAPZ_IMPORT_LOWER_READ_PENDING,
	SWAPZ_IMPORT_LOWER_TERMINAL,
};

/* One callback only, with a monotonically increasing request token.
 * The original queued bvec/page buffers belong to the caller until its
 * terminal callback. This struct owns a full immutable TRANSACTION snapshot
 * for the whole asynchronous lower callback lifetime (never a stack borrow).
 * The lower memory buffer is owned by the fixture and remains valid until
 * callback+retained reader drain. No actual block_device or upper BIO here.
 */
struct swapz_import_lower_bio_request {
	swapz_u64 token;
	swapz_u64 sector;
	swapz_u32 opf;
	swapz_u32 bytes;
};
struct swapz_import_lower_bio_owner {
	struct swapz_import_disk_pool *pool;
	struct swapz_tx transaction;
	struct swapz_import_disk_view pinned_view;
	struct swapz_import_lower_bio_request pending;
	swapz_u64 ticket;
	swapz_u64 next_token;
	swapz_u8 phase;
	swapz_u8 closing;
	swapz_u8 direct_fua;
	swapz_u8 has_pin;
};
_Static_assert(sizeof(struct swapz_import_lower_bio_owner) <= 4096U,
	       "test-only lower callback owner exceeds bounded memory");

/*
 * ALL methods require the serialized sleepable ordered authority owner.
 * Actual native bio->bi_end_io runs in unspecified/IRQ context: it may ONLY
 * record completion, then hand this small result to that ordered worker.
 * This guard has NO real bio submission, kernel block queue or ACK.
 */
void swapz_import_lower_init(struct swapz_import_lower_bio_owner *owner,
			      struct swapz_import_disk_pool *pool);
int swapz_import_lower_begin_write(struct swapz_import_lower_bio_owner *owner,
				    const struct swapz_tx *transaction,
				    swapz_u64 ticket, int fua_supported,
				    struct swapz_import_lower_bio_request *request);
/* Return -EINPROGRESS only after successful full WRITE without FUA, which
 * explicitly requires a separate post-WRITE REQ_OP_FLUSH|REQ_PREFLUSH. */
int swapz_import_lower_end_write(struct swapz_import_lower_bio_owner *owner,
				  const struct swapz_import_lower_bio_request *observed,
				  swapz_u32 completed_bytes, int lower_error,
				  const swapz_u8 *lower_extent,
				  struct swapz_import_lower_bio_request *postflush);
int swapz_import_lower_end_flush(struct swapz_import_lower_bio_owner *owner,
				  const struct swapz_import_lower_bio_request *observed,
				  int lower_error, const swapz_u8 *lower_extent);
int swapz_import_lower_begin_read(struct swapz_import_lower_bio_owner *owner,
				   swapz_u64 ticket,
				   struct swapz_import_lower_bio_request *request);
int swapz_import_lower_end_read(struct swapz_import_lower_bio_owner *owner,
				 const struct swapz_import_lower_bio_request *observed,
				 swapz_u32 completed_bytes, int lower_error,
				 const swapz_u8 *lower_extent,
				 swapz_u8 *compressed_destination,
				 swapz_u32 destination_capacity);
/* Close is a fence, not a cancellation of a physically queued request.
 * Return -EBUSY until both lower callback and retained pin are drained. */
int swapz_import_lower_close(struct swapz_import_lower_bio_owner *owner);
#endif /* SWAPZ_ROUND068_IMPORT_LOWER_BIO_TEST */
#endif /* SWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST */
#endif /* SWAPZ_ROUND066_IMPORT_DISK_TEST */

#endif

#endif
