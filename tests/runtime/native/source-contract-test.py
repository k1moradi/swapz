#!/usr/bin/env python3
"""Fail-closed source qualifications for *real* swapz vs codec-only smoke.

This is not a replacement for live kernel BIO/GC tests. It prevents CI and
future privileged harnesses from accidentally selecting the old swapz module
or the standalone memory-only research smoke instead of the real DM target.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]
DM = (ROOT / "src/kernel/dm-target.c").read_text()
ENGINE = (ROOT / "src/kernel/engine.c").read_text()
AUTH = (ROOT / "src/kernel/authority.c").read_text()
CODEC = (ROOT / "src/kernel/codec.c").read_text()
MK = (ROOT / "src/kernel/Makefile").read_text()
README = (ROOT / "docs/README.md").read_text()


def body(symbol: str) -> str:
    match = re.search(r"static\s+(?:int|void|bool|u64|unsigned\s+long|enum\s+hrtimer_restart|const\s+u8\s*\*)\s*" + re.escape(symbol) +
                      r"\s*\([^;]*?\)\s*\{", DM, re.S)
    if not match:
        raise AssertionError(f"Missing production symbol {symbol}")
    start = match.end()
    depth = 1
    for pos in range(start, len(DM)):
        if DM[pos] == "{":
            depth += 1
        elif DM[pos] == "}":
            depth -= 1
            if depth == 0:
                return DM[start:pos]
    raise AssertionError("Unclosed function: " + symbol)


def source_body(symbol: str, source: str) -> str:
    match = re.search(r"(?:static\s+)?(?:int|void|swapz_u32)\s+" + re.escape(symbol) +
                      r"\s*\([^;]*?\)\s*\{", source, re.S)
    if not match:
        raise AssertionError(f"Missing source symbol {symbol}")
    start = match.end()
    depth = 1
    for pos in range(start, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                return source[start:pos]
    raise AssertionError("Unclosed source function: " + symbol)


class SwapzProductionSourceQualification(unittest.TestCase):
    def test_publish_crc_probe_times_only_final_payload_crc(self):
        descriptor = source_body("swapz_lookup_validated_descriptor", CODEC)
        validated = source_body("swapz_lookup_validated", CODEC)
        finish = source_body("swapz_finish", AUTH)
        self.assertNotIn("swapz_crc32c_bytes", descriptor)
        self.assertIn("swapz_crc32c_bytes", validated)
        self.assertIn("swapz_lookup_validated_descriptor", finish)
        self.assertIn("swapz_publish_crc32c(a, payload, decoded.payload_length)",
                      finish)
        self.assertNotIn("swapz_lookup_validated(image", finish)

    def test_completed_dry_probe_is_removed_and_queue_starvation_probe_is_bounded(self):
        lower = body("swapz_lower")
        self.assertNotIn("dry_pack_", DM)
        self.assertIn("prep_lower_write_start_queued", lower)
        self.assertIn("prep_lower_write_end_queued", lower)
        self.assertIn("ctx->preparation_queued", lower)
        self.assertIn("ctx->preparation_queued++", DM)
        self.assertGreaterEqual(DM.count("ctx->preparation_queued--"), 2)

    def test_gc_tracks_committed_victim_distribution(self):
        gc = body("swapz_gc_compact_one_inner")
        self.assertIn("gc_segment_evictions[victim]", gc)
        self.assertIn("gc_distinct_victims", DM)
        self.assertIn("gc_victim_min_evictions", DM)
        self.assertIn("gc_victim_max_evictions", DM)
        self.assertIn("kvfree(ctx->gc_segment_evictions)", DM)

    def test_dead_segment_probe_and_trim_lifecycle_are_fail_safe(self):
        pick = source_body("swapz_pick_dead_segment", AUTH)
        eligible = source_body("swapz_dead_segment_eligible", AUTH)
        claim = source_body("swapz_claim_dead_segment", AUTH)
        self.assertIn("!a->segment_mapped_pages[segment]", eligible)
        self.assertIn("a->alloc_probe_segments++", pick)
        self.assertIn("a->balance_segment_opens", pick)
        self.assertIn("programs < best", pick)
        self.assertIn("a->alloc_probe_full_scans++", claim)
        self.assertIn("for (off = 0; off < SWAPZ_SEGMENT_BLOCKS; ++off)", claim)
        self.assertIn("swapz_page_list_validate_segment(a, segment)", claim)
        self.assertIn("a->segment_program_counts[segment]++", claim)
        stage = source_body("swapz_stage", AUTH)
        self.assertIn("tail_waste = SWAPZ_SEGMENT_BLOCKS -", stage)
        self.assertLess(stage.index("tail_waste = SWAPZ_SEGMENT_BLOCKS -"),
                        stage.index("error = swapz_pick_dead_segment(a)"))
        self.assertNotIn("swapz_placement_start", AUTH)
        resume = source_body("swapz_batch_resume", AUTH)
        self.assertNotIn("packed_placement", resume)
        self.assertNotIn("tx->start_block % tx->extent_blocks", resume)

        discard = body("swapz_discard_dead_segment")
        lower = body("swapz_lower")
        async_submit = body("swapz_submit_inflight_write")
        dirty = body("swapz_mark_segments_dirty")
        status = body("swapz_status")
        self.assertIn("segment_discards_skipped_already_trimmed", discard)
        self.assertIn("READ_ONCE(ctx->segment_trimmed[segment])", discard)
        self.assertIn("WRITE_ONCE(ctx->segment_trimmed[segment], 1)", discard)
        self.assertIn("swapz_mark_segments_dirty(ctx, block, blocks)", lower)
        self.assertIn("swapz_mark_segments_dirty(ctx, inflight->run.start_block",
                      async_submit)
        self.assertIn("WRITE_ONCE(ctx->segment_trimmed[segment], 0)", dirty)
        upper_discard = body("swapz_discard")
        self.assertIn("became_dead", upper_discard)
        self.assertIn("swapz_discard_dead_segment(ctx, old_segment)", upper_discard)
        self.assertNotIn("swapz_packed_placement", DM)
        self.assertNotIn("module_param_named(packed_placement", DM)
        self.assertIn("packed_placement=%u", status)
        engine = (ROOT / "src/kernel/engine.c").read_text()
        self.assertNotIn("packed_placement", engine)
        self.assertIn("alignment_cursor % SWAPZ_SEGMENT_BLOCKS", engine)
        self.assertIn("alignment_hole_blocks_foreground", status)
        self.assertIn("segment_tail_waste_blocks_foreground", status)
        self.assertIn("segment_tail_waste_blocks_gc", status)
        self.assertIn("alloc_probe_full_scans", status)
        self.assertIn("segment_program_sum", status)
        self.assertIn("logical_open_balance=%u", status)
        self.assertIn("module_param_named(logical_open_balance", DM)
        self.assertIn("swapz_enable_segment_page_lists", DM)
        self.assertIn("ctx->segment_first_page", DM)
        self.assertIn("ctx->page_next_in_segment", DM)
        self.assertIn("balance_segment_opens = swapz_logical_open_balance", DM)

    def test_codec_append_rejects_invalid_length_before_payload_hash(self):
        append = source_body("swapz_append", CODEC)
        guard = append.index("length > SWAPZ_MAX_COMPRESSED")
        payload_hash = append.index("swapz_crc32c_bytes(payload, length)")
        self.assertLess(guard, payload_hash)
        self.assertIn("!payload || !length", append)

    def test_separate_target_and_release_metadata(self):
        self.assertRegex(DM, r'\.name\s*=\s*"swapz"')
        self.assertRegex(DM, r'MODULE_ALIAS\("dm-swapz"\)')
        version = (ROOT / "src/kernel/VERSION").read_text().strip()
        self.assertRegex(version, r"^3\.0\.0-alpha\.[0-9]+$")
        self.assertIn('#include "swapz-version.h"', DM)
        self.assertIn("MODULE_VERSION(SWAPZ_ALPHA_VERSION)", DM)
        self.assertNotIn('#define SWAPZ_ALPHA_VERSION "3.0.0-alpha.', DM)
        self.assertIn('swapz-version.h', MK)
        self.assertIn('$(CURDIR)/VERSION', MK)
        self.assertIn('^3[.]0[.]0-alpha[.][0-9]+', MK)
        dkms = (ROOT / "dkms.conf").read_text()
        self.assertIn('BASH_SOURCE[0]', dkms)
        self.assertIn('src/kernel/VERSION', dkms)
        self.assertNotIn('PACKAGE_VERSION="' + version + '"', dkms)
        self.assertIn("obj-m += dm-swapz.o", MK)
        self.assertNotIn('"swapz3"', DM)
        for path in ("docs/README.md", "docs/VISION.md",
                     "docs/coding_standards.md", "docs/testing_standards.md",
                     "docs/compile.md", "docs/benchmark.md"):
            with self.subTest(naming_policy=path):
                document = (ROOT / path).read_text()
                self.assertIn("Immutable naming policy (read before every prompt)",
                              document)
                self.assertIn("Device Mapper target is exactly `swapz`",
                              document)
                self.assertIn("module alias is `dm-swapz`", document)
        self.assertNotIn("SWAPZ_BUILD_SMOKE", MK)
        self.assertNotIn("swapz_extent", MK)
        # A public README must link to the single version source rather
        # than becoming a second, manually edited alpha-number string.
        self.assertIn(
            "[`src/kernel/VERSION`](../src/kernel/VERSION)", README)
        self.assertIn("single source of truth", README)

    def test_write_saturation_evidence_stays_private_bounded_and_write_only(self):
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        reporter = (ROOT / "tests/tools/run-tests.py").read_text()
        for qd in ("1", "4", "8", "32"):
            self.assertIn("for qd in 1 4 8 32", loaded)
        self.assertIn("--read-pct 0", loaded)
        self.assertIn("--write-only-qd", loaded)
        self.assertIn("--sustained-write", loaded)
        self.assertIn("START_WRITE_SATURATION_PAIR_QD=", loaded)
        self.assertIn("PASS_WRITE_SATURATION_PAIR_QD=", loaded)
        self.assertIn("WRITE_ONLY_QD=0", pair)
        self.assertIn("READ_PCT=0", pair)
        self.assertIn("PACKED_READ=0", pair)
        self.assertIn("ASYNC_PREPARE && !WRITE_ONLY_QD", pair)
        self.assertIn("def parse_write_saturation", reporter)
        self.assertIn('"replay_mode": obj.get("replay_mode")', reporter)
        self.assertIn('arm.get("replay_mode") != "persistent-write"', reporter)
        self.assertIn("PASS_WRITE_SATURATION_EVIDENCE", reporter)
        self.assertIn("FAST_QD4_QD8_QD32_PAIRED_95PCT_CI", reporter)
        self.assertIn("fast_qd4_paired", reporter)
        self.assertIn("fast_qd8_paired", reporter)
        self.assertIn("fast_qd32_paired", reporter)
        self.assertIn("$qd == 4 || $qd == 8 || $qd == 32", loaded)
        self.assertIn("confirmation_modes=(0 1 1 0 0 1 1 0 0 1)", loaded)


    def test_lz4_foreground_size_histogram_is_attempt_side_only(self):
        accept = body("swapz_accept_write")
        status = body("swapz_status")
        self.assertIn("length = LZ4_compress_fast(", accept)
        self.assertIn("ctx->lz4_attempts++", accept)
        self.assertIn("ctx->lz4_size_bins[5]++", accept)
        self.assertIn("ctx->lz4_accepted_bytes += length", accept)
        for threshold in ("256", "1024", "2048", "3072"):
            self.assertIn(f"length <= {threshold}", accept)
        self.assertLess(accept.index("length = LZ4_compress_fast("),
                        accept.index("ctx->lz4_attempts++"))
        self.assertLess(accept.index("ctx->lz4_size_bins[5]++"),
                        accept.index("if (length <= 0 && bulk_raw_eligible)"))
        self.assertIn("lz4_attempts=%llu lz4_accepted_bytes=%llu", status)
        self.assertIn("lz4_size_3073_3568=%llu lz4_raw_fallback=%llu", status)
        self.assertIn("ctx->lz4_size_bins[5]", status)
        self.assertNotIn("LZ4_compress_fast(", body("swapz_gc_compact_one_inner"))

    def test_exact_zero_write_elides_lower_io_without_losing_ordering(self):
        accept = body("swapz_accept_write")
        read = body("swapz_read")
        status = body("swapz_status")
        self.assertIn("length > 0 && length <= 64", accept)
        self.assertIn("inline_zero = swapz_page_is_zero(input)", accept)
        self.assertIn("(prepared_async ? entry->prepared_page->zero : inline_zero)",
                      accept)
        self.assertLess(accept.index("inline_zero = swapz_page_is_zero(input)"),
                        accept.index("kunmap_local(mapped_input)"))
        self.assertIn("swapz_flush_window(ctx)", accept)
        self.assertIn("swapz_discard_page(&ctx->authority, logical)", accept)
        self.assertIn("ctx->logical_write_bytes += SWAPZ_BLOCK_BYTES", accept)
        self.assertIn("ctx->zero_elided_pages++", accept)
        self.assertIn("swapz_complete(bio, error)", accept)
        self.assertIn("swapz_issue_flush(ctx)", accept)
        self.assertLess(accept.index("swapz_flush_window(ctx);",
                                    accept.index("inline_zero = swapz_page_is_zero(input)")),
                        accept.index("swapz_discard_page(&ctx->authority"))
        self.assertIn("if (!map->valid)", read)
        self.assertIn("memset(ctx->read_page, 0, SWAPZ_BLOCK_BYTES)", read)
        self.assertIn("zero_elided=%llu", status)
        # The predicate itself is exercised by an actual-C native test.
        engine = (ROOT / "src/kernel/engine.c").read_text()
        self.assertIn("int swapz_page_is_zero(", engine)

    def test_targeted_read_metadata_and_payload_diagnostics_are_success_only(self):
        engine = (ROOT / "src/kernel/engine.c").read_text()
        header = (ROOT / "src/kernel/engine.h").read_text()
        status = body("swapz_status")
        self.assertIn("read_metadata_requests", header)
        self.assertIn("read_payload_requests", header)
        self.assertIn("read_payload_blocks", header)
        self.assertIn("engine->read_metadata_requests++", engine)
        self.assertIn("engine->read_payload_requests++", engine)
        self.assertIn("engine->read_payload_blocks += count", engine)
        self.assertLess(engine.index("error = engine->io.read_blocks(", engine.index(
            "int swapz_engine_read_page(")),
            engine.index("engine->read_metadata_requests++"))
        self.assertIn("read_meta_reqs=%u read_payload_reqs=%u", status)
        self.assertIn("read_payload_blocks=%u", status)
        self.assertIn("read_meta_cache_hits=%u", status)
        self.assertIn("read_meta_lru_hits=%u", status)
        self.assertIn("read_full_extent_reqs=%u read_full_cache_hits=%u", status)
        self.assertIn("read_two_block_skips=%u", status)
        self.assertIn("read_two_block_skips++", engine)
        self.assertIn("peek.payload_offset != observed.payload_offset", engine)
        engine_read = source_body("swapz_engine_read_page", engine)
        peeked_authority = source_body("swapz_read_authoritative_peeked", AUTH)
        self.assertIn("swapz_read_authoritative_peeked(", engine_read)
        self.assertNotIn("swapz_read_authoritative(", engine_read)
        self.assertIn("swapz_crc32c_bytes(", peeked_authority)
        self.assertIn("swapz_disk_sequence(", peeked_authority)
        self.assertNotIn("swapz_lookup(", peeked_authority)
        self.assertIn("payload_offsets[index] = decoded.payload_offset",
                      (ROOT / "src/kernel/authority.c").read_text())
        self.assertIn("read_full_extent_requests", header)
        self.assertIn("read_full_extent_cache_hits", header)
        self.assertIn("engine->read_full_extent_requests++", engine)
        self.assertIn("engine->read_full_extent_cache_hits++", engine)
        self.assertIn("engine->max_read_blocks_per_record != 1", engine)
        self.assertIn("engine->read_metadata_cache_hits++", engine)
        self.assertIn("engine->read_metadata_lru_hits++", engine)
        self.assertIn("swapz_read_metadata_lru_lookup(", engine)
        self.assertIn("swapz_read_metadata_lru_commit(", engine)
        self.assertIn("#define SWAPZ_READ_METADATA_CACHE_ENTRIES 512U", header)
        lookup = source_body("swapz_read_metadata_lru_lookup", engine)
        lru_commit = source_body("swapz_read_metadata_lru_commit", engine)
        self.assertIn("swapz_u16 index;", lookup)
        self.assertIn("swapz_u16 index, slot = 0;", lru_commit)
        self.assertIn("slot = (swapz_u16)hit_slot", lru_commit)
        self.assertIn("engine->read_metadata_lru_valid", engine)
        self.assertIn("engine->read_metadata_cache +", engine)
        self.assertIn("memset(engine->read_metadata_lru_valid, 0", engine)
        invalidate = source_body("swapz_engine_invalidate_read_cache", engine)
        self.assertIn("if (engine->read_metadata_lru_clock)", invalidate)
        self.assertLess(invalidate.index("if (engine->read_metadata_lru_clock)"),
                        invalidate.index("memset(engine->read_metadata_lru_valid, 0"))
        self.assertIn("engine->read_cache_valid = 0", engine)
        self.assertIn("swapz_engine_invalidate_read_cache(engine)", engine)
        self.assertIn("swapz_engine_invalidate_read_cache(e)", engine)
        self.assertIn("swapz_invalidate_read_caches(ctx)", body("swapz_lower"))
        self.assertIn("swapz_invalidate_read_caches(ctx)", body("swapz_process"))
        self.assertIn("ctx->engine.read_metadata_cache =",
                      body("swapz_ctr"))
        self.assertIn("SWAPZ_READ_METADATA_CACHE_ENTRIES * SWAPZ_BLOCK_BYTES",
                      body("swapz_ctr"))
        self.assertIn("vfree(ctx->engine.read_metadata_cache)",
                      body("swapz_free"))

    def test_synthetic_anon_fixture_is_deterministic_and_size_exact(self):
        import importlib.util
        path = ROOT / "tests/runtime/benchmark/anon-page-fixture.py"
        spec = importlib.util.spec_from_file_location("anon_page_fixture", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in module.PROFILES:
            a = module.page_bytes(123, 7, name)
            self.assertEqual(len(a), 4096, name)
            self.assertEqual(a, module.page_bytes(123, 7, name))
        self.assertEqual(len(module.schedule(7, 103, module.parse_weights(
            module.DEFAULT_WEIGHTS))), 103)
        # Fully deterministic without installing liblz4 on rootless CI:
        # the fake compressor exercises manifest/scheduling logic, not
        # the real compression size measurement claim.
        fake = lambda src, dst, page_size, cap, acceleration: (
            0 if bytes(src)[:4] == b"\\0" * 4 else 1024)
        raw_a, report_a = module.generate(91, 31, module.parse_weights(
            module.DEFAULT_WEIGHTS), fake)
        raw_b, report_b = module.generate(91, 31, module.parse_weights(
            module.DEFAULT_WEIGHTS), fake)
        self.assertEqual(raw_a, raw_b)
        self.assertEqual(report_a, report_b)
        self.assertEqual(len(raw_a), 31 * 4096)
        self.assertEqual(sum(report_a["lz4_size_buckets"].values()), 31)
        self.assertEqual(sum(report_a["profile_pages"].values()), 31)
        self.assertEqual(report_a["fixture_sha256"],
                         __import__("hashlib").sha256(raw_a).hexdigest())
        self.assertEqual(module.classify(0), "raw")
        self.assertEqual(module.classify(3568), "3073_3568")
        self.assertEqual(module.classify(256), "1_256")

    def test_actual_liblz4_anonymous_page_controls(self):
        import importlib.util
        path = ROOT / "tests/runtime/benchmark/anon-page-fixture.py"
        spec = importlib.util.spec_from_file_location("anon_page_fixture", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            compress = module.lz4_compressor()
        except RuntimeError as err:
            self.skipTest(str(err))
        zero = module.measure(compress, module.page_bytes(444, 0, "zero"))
        entropy = module.measure(compress, module.page_bytes(444, 0, "entropy"))
        self.assertGreater(zero, 0)
        self.assertLessEqual(zero, 256)
        self.assertEqual(entropy, 0)
        pages, info = module.generate(
            444, 70, module.parse_weights(module.DEFAULT_WEIGHTS), compress)
        self.assertEqual(len(pages), 70 * 4096)
        self.assertEqual(sum(info["lz4_size_buckets"].values()), 70)
        self.assertEqual(info["raw_page_bytes"], info["raw_pages"] * 4096)
        self.assertGreater(info["lz4_accepted_payload_bytes"], 0)
        self.assertGreater(info["raw_pages"], 0)

    def test_identical_off_swapz_replay_contract(self):
        # Rootless regular files exercise the immutable plan and full-image
        # oracle. They do NOT claim a loaded swapz module test.
        import subprocess
        import sys
        script = ROOT / "tests/runtime/benchmark/io-replay-test.py"
        result = subprocess.run([sys.executable, str(script)],
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0,
                         result.stdout + "\\n" + result.stderr)
        self.assertIn("OK", result.stderr)

    def test_alpha_rejects_all_physical_devices(self):
        ctr = body("swapz_ctr")
        self.assertIn('disk_name, "nullb", 5', ctr)
        self.assertIn('swapz alpha accepts null_blk backing only', ctr)
        self.assertIn("goto fail;", ctr)

    def test_real_swapz_not_memory_smoke(self):
        for snippet in ("dm_register_target(&swapz_target)",
                        "LZ4_compress_fast(", "LZ4_decompress_safe(",
                        "dm_io(&req,", "DM_IO_VMA", "SWAPZ_SECTORS"):
            self.assertIn(snippet, DM)

    def test_allocation_has_gc_reserve_and_fail_closed_reuse(self):
        compact = body("swapz_gc_compact_one_inner")
        relocate = body("swapz_gc_relocate_one")
        self.assertIn("swapz_gc_compact_one(ctx)", body("swapz_flush_window"))
        self.assertIn("swapz_gc_compact_one(ctx)", body("swapz_raw_write"))
        self.assertIn("swapz_gc_choose_victim(ctx,", compact)
        self.assertIn("live_total += a->live_records[start + off]", AUTH)
        self.assertIn("a->segment_mapped_pages[segment]", AUTH)
        self.assertIn("if (live_total)", AUTH)
        self.assertIn("swapz_enable_segment_mapping_counts", AUTH)
        self.assertIn("swapz_gc_live_byte_cost(m)", AUTH)
        self.assertIn("a->segment_gc_live_bytes[segment] += bytes", AUTH)
        self.assertIn("swapz_gc_prefer(score, count, best, best_count)", DM)
        self.assertIn("swapz_gc_relocate_one(ctx, victim, logical)", compact)
        self.assertIn("swapz_engine_read_page(&ctx->engine", relocate)
        self.assertIn("swapz_gc_flush(ctx)", compact)
        self.assertIn("swapz_finish_raw(&ctx->authority", body("swapz_gc_move_raw"))
        self.assertIn("if (a->live_records[block])", compact)

    def test_discard_validates_entire_range_before_mutating(self):
        discard = body("swapz_discard")
        self.assertLess(discard.index("while (check_remaining)"),
                        discard.index("while (remaining)"))
        self.assertLess(discard.index("if (m->generation =="),
                        discard.index("swapz_discard_page(&ctx->authority"))
        self.assertIn("ctx->live_records[start]--", discard)
        self.assertIn("ctx->live_records[m->start_block]++", discard)
        self.assertIn("for (restore_sector = sector;", discard)
        self.assertLess(discard.index("ctx->live_records[start]--"),
                        discard.index("ctx->live_records[m->start_block]++"))
        self.assertLess(discard.index("ctx->live_records[m->start_block]++"),
                        discard.index("swapz_discard_page(&ctx->authority"))
        self.assertNotIn("discard_epoch", DM)
        self.assertNotIn("discard_count", DM)
        self.assertNotIn("discard_serial", DM)

    def test_fua_acknowledged_only_after_flush(self):
        flush = body("swapz_flush_window")
        self.assertLess(flush.index("swapz_issue_flush(ctx)"),
                        flush.index("swapz_complete(bio, 0)"))
        self.assertIn("if (error && needs_fua)", flush)
        self.assertNotIn("DM_MAPIO_KILL; /* Until FUA", body("swapz_map"))

    def test_valid_empty_flush_protocol_and_failure_accounting(self):
        # REQ_OP_FLUSH as a BIO is rejected in Linux blk-core itself.
        # The supported upper-bio encoding is zero sector WRITE|PREFLUSH.
        admitted = body("swapz_map")
        process = body("swapz_process")
        lower = body("swapz_issue_flush")
        raw = body("swapz_accept_write")
        drain = body("swapz_drain")
        self.assertIn("REQ_OP_WRITE && !count", admitted)
        self.assertIn("bio->bi_opf & REQ_PREFLUSH", admitted)
        self.assertNotIn("bio_op(bio) != REQ_OP_FLUSH", admitted)
        self.assertNotIn("case REQ_OP_FLUSH:", process)
        self.assertIn("if (bio->bi_opf & REQ_PREFLUSH)", process)
        self.assertIn("swapz_issue_flush(ctx)", process)
        self.assertIn("swapz_issue_flush(ctx)", raw)
        self.assertIn("swapz_issue_flush(ctx)", drain)
        self.assertIn("swapz_flush_accounted(&ctx->flush_meter", lower)
        self.assertIn("swapz_fail(ctx, error)", lower)
        self.assertIn("flush_calls=%llu flush_ok=%llu flush_err=%llu", DM)
        self.assertIn("flush_injected=%llu flush_fault_nth=%u", DM)
        self.assertIn("flush_fail_nth > 64U", body("swapz_ctr"))
        self.assertIn("flush_meter.fail_nth = flush_fail_nth", body("swapz_ctr"))

    def test_serialized_completed_lower_write_wall_wait_buckets(self):
        lower = body("swapz_lower")
        status = body("swapz_status")
        self.assertIn("elapsed_ns = swapz_elapsed_ns(section_start", lower)
        self.assertIn("ctx->lower_write_wall_ns += elapsed_ns", lower)
        self.assertIn("ctx->write_wait_le_1ms++", lower)
        self.assertIn("ctx->write_wait_1_to_4ms++", lower)
        self.assertIn("ctx->write_wait_gt_4ms++", lower)
        self.assertLess(lower.index("if (error || bitmap)"),
                        lower.index("ctx->write_wait_le_1ms++"))
        self.assertIn("write_wait_le1ms=%llu write_wait_1to4ms=%llu", status)
        self.assertIn("write_wait_gt4ms=%llu", status)

    def test_owned_nullblk_lower_write_fault_is_pre_submission_and_counted(self):
        # This tests fail-closed propagation through the actual dm_io adapter.
        # It cannot model a device-originated partial/torn write.
        ctor = body("swapz_ctr")
        lower = body("swapz_lower")
        status = body("swapz_status")
        self.assertIn('disk_name, "nullb", 5', ctor)
        self.assertIn("argc < 1 || argc > 9", ctor)
        self.assertIn("write_fail_nth > 65535U", ctor)
        self.assertIn("ctx->write_fault_nth = write_fail_nth", ctor)
        self.assertIn("op == REQ_OP_WRITE", lower)
        self.assertIn("++ctx->write_fault_calls == ctx->write_fault_nth", lower)
        self.assertIn("ctx->write_fault_injected++", lower)
        self.assertIn("return -EIO", lower)
        self.assertLess(lower.index("ctx->write_fault_injected++"),
                        lower.index("ctx->lower_write_submitted_reqs++"))
        self.assertLess(lower.index("ctx->write_fault_injected++"),
                        lower.index("error = dm_io(&req"))
        self.assertIn("swapz_lower(ctx, REQ_OP_WRITE", body("swapz_lower_write"))
        self.assertIn("swapz_lower(ctx, REQ_OP_WRITE", body("swapz_lower_write_run"))
        async_submit = body("swapz_submit_inflight_write")
        self.assertIn("++ctx->write_fault_calls == ctx->write_fault_nth", async_submit)
        self.assertIn("ctx->write_fault_injected++", async_submit)
        self.assertIn("write_fault_nth=%u write_fault_calls=%llu "
                      "write_fault_injected=%llu", status)
        self.assertIn("ctx->engine.bulk_enabled, ctx->write_fault_nth", status)

    def test_immutable_io_run_split_preserves_publication_gate(self):
        engine_h = (ROOT / "src/kernel/engine.h").read_text()
        engine = (ROOT / "src/kernel/engine.c").read_text()
        prepare = source_body("swapz_engine_prepare_batched_run", engine)
        complete = source_body("swapz_engine_complete_batched_run", engine)
        self.assertIn("struct swapz_io_run", engine_h)
        self.assertIn("swapz_u8 *bytes", engine_h)
        self.assertIn("struct swapz_tx *txs", engine_h)
        self.assertIn("swapz_batch_pause(e->authority, tx)", prepare)
        self.assertNotIn("e->io.write_run(", prepare)
        self.assertIn("swapz_batch_resume(e->authority, tx)", complete)
        self.assertIn("swapz_finish(", complete)
        self.assertIn("swapz_finish_raw(", complete)
        self.assertIn("swapz_bulk_abort(e, run, 0)", complete)
        self.assertLess(complete.index("swapz_batch_resume"),
                        complete.index("swapz_finish("))

    def test_bounded_lower_run_aggregation_preserves_commit_gate(self):
        engine = (ROOT / "src/kernel/engine.c").read_text()
        authority = (ROOT / "src/kernel/authority.c").read_text()
        writer = source_body("swapz_engine_write_window_batched_read_cap", engine)
        prepare = source_body("swapz_engine_prepare_batched_run", engine)
        complete = source_body("swapz_engine_complete_batched_run", engine)
        pause = source_body("swapz_batch_pause", authority)
        resume = source_body("swapz_batch_resume", authority)
        self.assertIn("SWAPZ_BULK_BLOCKS 64U",
                      (ROOT / "src/kernel/engine.h").read_text())
        self.assertIn("swapz_engine_write_window_batched_read_cap(&ctx->engine", DM)
        self.assertIn("ctx->engine.io.write_run = swapz_lower_write_run", DM)
        self.assertIn("swapz_batch_pause(e->authority, tx)", prepare)
        self.assertIn("swapz_engine_prepare_batched_run(", writer)
        planner = source_body("swapz_engine_plan_bounded_policy", engine)
        self.assertIn("swapz_u32 alignment_cursor", engine)
        self.assertIn("candidate_bytes != costs[position]", planner)
        self.assertIn("hole == best_hole && blocks > chosen_class", planner)
        self.assertIn("e->authority->next_block", prepare)
        self.assertIn("swapz_batch_resume(e->authority, tx)", complete)
        self.assertLess(writer.index("e->io.write_run"),
                        writer.index("swapz_engine_complete_batched_run"))
        self.assertLess(complete.index("swapz_batch_resume(e->authority, tx)"),
                        complete.index("swapz_finish("))
        self.assertIn("swapz_bulk_abort(e, run, 0)", complete)
        self.assertIn("a->batch_pending++", pause)
        self.assertIn("a->batch_replaying = 1", resume)
        self.assertIn("ctx->engine.bulk_writes", body("swapz_status"))
        self.assertIn("bulk_mode=%u", body("swapz_status"))
        ctor = body("swapz_ctr")
        self.assertIn("lower_bulk = 1", ctor)
        self.assertIn("lower_bulk > 2U", ctor)
        self.assertIn("ctx->engine.bulk_enabled = lower_bulk", ctor)
        self.assertIn("e->bulk_enabled == 1", prepare)
        self.assertIn("placed = e->authority->next_block;", prepare)
        self.assertIn("(e->bulk_enabled == 1 && placed != run_end)", prepare)
        self.assertIn("tx->start_block != run_start + run_blocks", prepare)
        self.assertIn("e->run_splits_by_hole++", prepare)
        self.assertIn("swapz_stage_batch(e->authority", prepare)
        self.assertIn("batch_hashes", authority)
        self.assertIn("batch_stage_allowed", authority)
        self.assertIn("a->batch_pending", source_body("swapz_gc_commit_rotation", authority))

    def test_partial_extent_read_cache_tracks_only_successful_blocks(self):
        engine_h = (ROOT / "src/kernel/engine.h").read_text()
        engine = (ROOT / "src/kernel/engine.c").read_text()
        read = source_body("swapz_engine_read_page", engine)
        invalidate = source_body("swapz_engine_invalidate_read_cache", engine)
        process = body("swapz_process")
        self.assertIn("read_cached_block_mask", engine_h)
        self.assertIn("read_extent_cache", engine_h)
        self.assertIn("engine->read_cached_block_mask = 0", invalidate)
        self.assertIn("read_extent_lru_valid", invalidate)
        self.assertIn("cached_mask = cached_metadata ?", read)
        self.assertIn("cached_mask |= 1U", read)
        self.assertIn("(1U << initial_blocks) - 1U", read)
        self.assertIn("while (start <= last && (cached_mask & (1U << start)))",
                      read)
        self.assertIn("while (start <= last && (cached_mask & (1U << last)))",
                      read)
        payload_read = read.index("engine->io.read_blocks",
                                  read.index("if (last >= start)"))
        residency_gate = read.index("if (observed.extent_blocks > 1 &&",
                                    payload_read)
        self.assertLess(payload_read, residency_gate)
        self.assertIn("engine->max_read_blocks_per_record != 1",
                      read[residency_gate:residency_gate + 300])
        self.assertLess(residency_gate,
                        read.index("cached_mask |=", residency_gate))
        self.assertIn("engine->read_cached_block_mask = cached_mask", read)
        self.assertIn("engine->read_cached_full = observed.extent_blocks > 1 &&",
                      read)
        self.assertIn("engine->max_read_blocks_per_record != 1",
                      read[read.index("engine->read_cached_full ="):])
        self.assertIn("swapz_read_extent_lru_commit(engine", read)
        self.assertIn("swapz_invalidate_read_caches(ctx)", process)


    def test_mixed_raw_lower_run_preserves_authority_and_barriers(self):
        engine = (ROOT / "src/kernel/engine.c").read_text()
        writer = source_body("swapz_engine_write_window_batched_read_cap", engine)
        prepare = source_body("swapz_engine_prepare_batched_run", engine)
        engine_complete = source_body("swapz_engine_complete_batched_run", engine)
        accept = body("swapz_accept_write")
        dm_complete = body("swapz_flush_window")
        process = body("swapz_process")
        self.assertIn("!ctx->engine.verify_after_write", accept)
        self.assertIn("ctx->engine.bulk_enabled", accept)
        self.assertIn("ctx->batch_count++", accept)
        self.assertIn(".raw = 1", accept)
        self.assertIn("ctx->batch[index].raw", body("swapz_order_window"))
        self.assertIn("run->raw[staged] = raw", prepare)
        self.assertIn("swapz_finish_raw(", engine_complete)
        self.assertLess(writer.index("e->io.write_run"),
                        writer.index("swapz_engine_complete_batched_run"))
        self.assertIn("ctx->planned[index].raw", dm_complete)
        self.assertIn("bulk_mixed_io=%u", body("swapz_status"))
        self.assertIn("bulk_raw_only_io=%u", body("swapz_status"))
        self.assertIn("bulk_raw_entries=%u", body("swapz_status"))
        self.assertLess(dm_complete.index("swapz_issue_flush(ctx)"),
                        dm_complete.index("swapz_complete(bio, 0)"))
        self.assertIn("swapz_flush_window(ctx)", process)
        self.assertIn("REQ_PREFLUSH", process)
        self.assertIn("swapz_raw_write(ctx, bio, logical)", accept)

    def test_gc_refuses_any_unpublished_lower_group(self):
        compact = body("swapz_gc_compact_one_inner")
        self.assertIn("a->batch_pending", compact)
        self.assertIn("a->batch_replaying", compact)
        self.assertLess(compact.index("a->batch_pending"),
                        compact.index("swapz_gc_choose_victim(ctx, &victim)"))
        drain = body("swapz_drain")
        self.assertIn("ctx->authority.batch_pending", drain)
        self.assertIn("ctx->authority.in_flight", drain)

    def test_gc_production_uses_exact_segment_mapping_counts(self):
        authority = (ROOT / "src/kernel/authority.c").read_text()
        finish = source_body("swapz_finish", authority)
        raw = source_body("swapz_finish_raw", authority)
        discard = source_body("swapz_discard_page", authority)
        dead = source_body("swapz_pick_dead_segment", authority)
        eligible = source_body("swapz_dead_segment_eligible", authority)
        claim = source_body("swapz_claim_dead_segment", authority)
        rotate = source_body("swapz_gc_commit_rotation", authority)
        ctor = body("swapz_ctr")
        compact = body("swapz_gc_compact_one_inner")
        self.assertIn("segment_mapped_pages", (ROOT / "src/kernel/authority.h").read_text())
        self.assertIn("segment_mapped_pages[new_segment]++", finish)
        self.assertIn("segment_mapped_pages[old_segments[index]]--", finish)
        self.assertIn("segment_mapped_pages[new_segment]++", raw)
        self.assertIn("segment_mapped_pages[old_segment]--", discard)
        self.assertIn("!a->segment_mapped_pages[segment]", eligible)
        self.assertIn("swapz_dead_segment_eligible(a, segment)", dead)
        self.assertIn("swapz_claim_dead_segment(a, segment, probe_start)", dead)
        self.assertIn("for (off = 0; off < SWAPZ_SEGMENT_BLOCKS; ++off)", claim)
        self.assertIn("if (live_total)", claim)
        self.assertIn("a->segment_mapped_pages[victim]", rotate)
        self.assertIn("ctx->segment_mapped_pages = kvcalloc", ctor)
        self.assertIn("swapz_enable_segment_mapping_counts(&ctx->authority", ctor)
        self.assertIn("a->segment_mapped_pages[victim]", compact)

    def test_gc_large_record_preflight_avoids_pointless_full_relocation(self):
        choose = body("swapz_gc_choose_victim")
        cost = (ROOT / "src/kernel/gc-cost.h").read_text()
        ctr = body("swapz_ctr")
        self.assertIn("SWAPZ_GC_UNSHAREABLE_MIN_LENGTH", cost)
        self.assertIn("swapz_gc_min_live_blocks", cost)
        self.assertIn("swapz_gc_candidate_can_free_block", cost)
        self.assertIn("a->segment_gc_min_live_blocks[segment] +=", AUTH)
        self.assertIn("swapz_gc_candidate_can_free_block", choose)
        self.assertIn("ctx->gc_no_headroom_skips++", choose)
        self.assertIn("gc_no_headroom_skips=%llu", body("swapz_status"))
        self.assertIn("ctx->gc_min_live_blocks = kvcalloc", ctr)

    def test_gc_io_aware_default_retains_old_control_policies(self):
        choose = body("swapz_gc_choose_victim")
        ctor = body("swapz_ctr")
        self.assertIn("gc_policy = 2", ctor)
        self.assertIn("gc_policy > 2U", ctor)
        self.assertIn("swapz_gc_estimated_io_cost(m)", AUTH)
        self.assertIn("a->segment_gc_io_cost[segment] += io_cost", AUTH)
        self.assertIn("case 0:", choose)
        self.assertIn("case 1:", choose)
        self.assertIn("score = ctx->gc_io_scores[segment]", choose)
        self.assertIn("gc_selected_io_estimate", body("swapz_status"))

    def test_gc_does_not_consume_or_complete_upper_bios(self):
        gc = body("swapz_gc_compact_one_inner")
        self.assertNotIn("swapz_complete(", gc)
        self.assertIn("ctx->gc_read_bytes", gc)
        self.assertIn("ctx->gc_write_bytes", gc)
        self.assertIn("a->gc_allocation = 0", gc)

    def test_worker_yields_after_finite_window_and_preserves_fifo(self):
        # Assert the finite-quantum semantics, not one obsolete decrement idiom.
        worker = body("swapz_worker")
        self.assertIn("SWAPZ_WORK_QUANTUM_BIOS", worker)
        self.assertIn("while (remaining && !list_empty(&local))", worker)
        self.assertIn("remaining -= processed_bios", worker)
        self.assertIn("unsigned int processed_bios = 1", worker)
        self.assertIn("list_splice_init(&local, &ctx->incoming)", worker)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", worker)
        self.assertIn("cond_resched()", worker)
        self.assertLess(worker.index("remaining -= processed_bios"),
                        worker.index("list_splice_init(&local, &ctx->incoming)"))
        self.assertLess(worker.index("swapz_flush_window(ctx)"),
                        worker.index("list_splice_init(&local, &ctx->incoming)"))

    def test_shutdown_completes_all_accepted_queued_bios(self):
        worker = body("swapz_worker")
        drain = body("swapz_drain")
        self.assertIn("for (;;)", worker)
        self.assertIn("remaining = SWAPZ_WORK_QUANTUM_BIOS", worker)
        self.assertIn("if (ctx->accepting)", worker)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", worker)
        self.assertIn("cond_resched();", worker)
        self.assertLess(worker.index("if (ctx->accepting)"),
                        worker.rindex("cond_resched();"))
        self.assertIn("drain_workqueue(ctx->workqueue)", drain)
        self.assertIn("swapz drain invariant: accepted BIOs remain", drain)
        self.assertIn("ctx->authority.batch_pending", drain)
        self.assertIn("ctx->authority.in_flight", drain)
        self.assertIn("swapz_fail(ctx, -EUCLEAN)", drain)

    def test_raw_crc_protection_and_gc_relocation(self):
        auth = (ROOT / "src/kernel/authority.c").read_text()
        auth_h = (ROOT / "src/kernel/authority.h").read_text()
        self.assertIn("raw_crc32c", auth_h)
        self.assertIn("swapz_verify_raw(", auth)
        self.assertIn("swapz_crc32c_bytes(raw_page, SWAPZ_BLOCK_BYTES)", auth)
        self.assertIn("swapz_verify_raw(&ctx->authority, logical, ctx->read_page)",
                      body("swapz_read"))
        self.assertIn("swapz_verify_raw(&ctx->authority, logical, ctx->input_page)",
                      body("swapz_gc_move_raw"))

    def test_gc_explicitly_forbids_paused_open_and_victim(self):
        authority = (ROOT / "src/kernel/authority.c").read_text()
        gc = body("swapz_gc_compact_one_inner")
        for name in ("gc_forbidden_open", "gc_forbidden_victim"):
            self.assertIn(name, authority)
            self.assertIn("a->" + name, gc)
        self.assertIn("segment == a->gc_forbidden_open", authority)
        self.assertIn("segment == a->gc_forbidden_victim", authority)
        self.assertIn("swapz_gc_begin_rotation(a, victim)", gc)
        self.assertIn("swapz_gc_commit_rotation(a, victim)", gc)
        self.assertIn("swapz_enable_segment_rotation(&ctx->authority", body("swapz_ctr"))
        self.assertIn("!ctx->segment_roles[segment]", body("swapz_gc_choose_victim"))
        self.assertIn("a->segment_foreground[dest] = 1", authority)
        self.assertIn("a->segment_foreground[victim] = 0", authority)

    def test_optional_write_verify_before_raw_publication(self):
        ctor = body("swapz_ctr")
        verifier = body("swapz_verify_raw_write")
        for name in ("swapz_gc_move_raw", "swapz_raw_write"):
            raw = body(name)
            self.assertLess(raw.index("swapz_verify_raw_write(ctx"),
                            raw.index("swapz_finish_raw(&ctx->authority"))
        self.assertIn("engine.verify_after_write = verify", ctor)
        self.assertIn("verify > 1U", ctor)
        self.assertIn("if (!ctx->engine.verify_after_write)", verifier)
        self.assertIn("return memcmp(", verifier)
        self.assertIn("-EBADMSG", verifier)

    def test_attempted_and_completed_lower_io_are_distinct(self):
        lower = body("swapz_lower")
        self.assertLess(lower.index("ctx->lower_write_submitted_reqs++"),
                        lower.index("error = dm_io(&req"))
        self.assertLess(lower.index("error = dm_io(&req"),
                        lower.index("ctx->physical_write_reqs++"))
        self.assertIn("one_page_windows", body("swapz_flush_window"))
        self.assertIn("worker_requeues", body("swapz_worker"))

    def test_online_batching_bounded_and_barrier_first(self):
        admitted = body("swapz_map")
        ctor = body("swapz_ctr")
        drain = body("swapz_drain")
        worker = body("swapz_worker")
        self.assertNotIn("msecs_to_jiffies", admitted)
        self.assertIn("REQ_PREFLUSH | REQ_FUA", admitted)
        self.assertIn("bio_op(bio) != REQ_OP_WRITE", admitted)
        self.assertIn("queue_delayed_work(ctx->workqueue", admitted)
        self.assertIn("mod_delayed_work(ctx->workqueue", admitted)
        self.assertIn("INIT_DELAYED_WORK(&ctx->worker", ctor)
        self.assertIn("ctx->window_size_counts[count]++", body("swapz_flush_window"))
        self.assertIn("ctx->one_page_close_reasons[close_reason]++",
                      body("swapz_flush_window"))
        self.assertIn("win1_read_conflict=%llu win1_read_unrelated=%llu",
                      body("swapz_status"))
        self.assertIn("win1_deadline=%llu win1_pack_ready=%llu",
                      body("swapz_status"))
        for field in ("win1_pack_tail_target=%llu",
                      "win1_pack_read_bypass=%llu",
                      "win1_pack_wave_interrupted=%llu"):
            self.assertIn(field, body("swapz_status"))
        flush = body("swapz_flush_window")
        self.assertIn("win1_pack_tail_target = count == 1U", flush)
        self.assertIn("ctx->retained_tail_target == 1U", flush)
        self.assertIn("win1_pack_read_bypass = count == 1U", flush)
        self.assertIn("ctx->retained_window_read_bypasses", flush)
        self.assertIn("win1_pack_wave_interrupted = count == 1U", flush)
        self.assertIn("ctx->retained_wave_interrupted", flush)
        self.assertIn("ctx->win1_pack_tail_target++", flush)
        self.assertIn("ctx->win1_pack_read_bypass++", flush)
        self.assertIn("ctx->win1_pack_wave_interrupted++", flush)
        self.assertIn("ctx->window_bins[0]++", body("swapz_flush_window"))
        self.assertIn("ctx->window_bins[5]++", body("swapz_flush_window"))
        self.assertIn("gc_read_reqs=%llu gc_write_reqs=%llu", DM)
        self.assertIn("ctx->gc_read_reqs += ctx->physical_read_reqs - before_read_reqs",
                      body("swapz_gc_compact_one_inner"))
        self.assertIn("flush_delayed_work(&ctx->worker)", drain)
        self.assertLess(worker.index("swapz_flush_window(ctx)"),
                        worker.index("list_splice_init(&local, &ctx->incoming)"))

    def test_gc_uses_committed_actual_payload_lengths(self):
        authority = (ROOT / "src/kernel/authority.c").read_text()
        self.assertIn("payload_lengths[index] = decoded.payload_length", authority)
        self.assertIn(".payload_length = payload_lengths[index]", authority)
        self.assertIn(".payload_length = SWAPZ_BLOCK_BYTES", authority)
        self.assertIn("peeked->payload_length != current_map->payload_length", authority)
        self.assertIn("ctx->gc_cost_policy", body("swapz_gc_choose_victim"))
        self.assertIn("gc_selected_live_bytes", body("swapz_gc_choose_victim"))
        # READ coalescing telemetry may appear in global status; GC cost must
        # still expose no synthetic/coalesced GC-byte estimator.
        self.assertNotIn("gc_coalesc", body("swapz_status"))

    def test_worker_close_reasons_cover_dependencies_and_control(self):
        flush = body("swapz_flush_window")
        write = body("swapz_accept_write")
        process = body("swapz_process")
        worker = body("swapz_worker")
        status = body("swapz_status")
        # The implementation snapshots the primary reason before resetting
        # next_window_close so the singleton cross-tab and legacy marginal
        # counter must index the same captured value.
        self.assertIn("ctx->window_close_reasons[close_reason]++", flush)
        self.assertIn("ctx->next_window_close = SWAPZ_CLOSE_UNKNOWN", flush)
        self.assertLess(flush.index("if (!count)"),
                        flush.index("ctx->window_close_reasons[close_reason]++"))
        self.assertIn("ctx->window_gc_pressure++", flush)
        for cause in ("FULL", "DUPLICATE", "ZERO", "FUA", "RAW"):
            self.assertIn("SWAPZ_CLOSE_" + cause, write)
        for cause in ("PREFLUSH", "READ_CONFLICT", "READ_UNRELATED", "DISCARD"):
            self.assertIn("SWAPZ_CLOSE_" + cause, process)
        for cause in ("QUANTUM", "IDLE", "SHUTDOWN"):
            self.assertIn("SWAPZ_CLOSE_" + cause, worker)
        for status_key in ("close_unknown", "close_full", "close_duplicate",
                           "close_zero", "close_fua", "close_raw",
                           "close_read_conflict", "close_read_unrelated",
                           "close_discard", "close_preflush", "close_quantum",
                           "close_idle", "close_shutdown", "close_other",
                           "window_gc_pressure"):
            self.assertIn(status_key + "=%llu", status)
        self.assertIn("swapz_flush_window(ctx)", process)
        self.assertIn("swapz_flush_window(ctx)", worker)

    def test_alpha10_open_age_counts_one_per_window_before_io(self):
        admitted = body("swapz_window_admit_clock")
        flush = body("swapz_flush_window")
        write = body("swapz_accept_write")
        status = body("swapz_status")
        self.assertIn("if (!ctx->batch_count)", admitted)
        self.assertIn("ctx->window_first_ns = ktime_get_ns()", admitted)
        self.assertEqual(write.count("swapz_window_admit_clock(ctx)"), 2)
        self.assertIn("end_ns = ktime_get_ns()", flush)
        self.assertIn("ctx->window_first_ns = 0", flush)
        self.assertLess(flush.index("ctx->window_age_sum_ns += open_age_ns"),
                        flush.index("swapz_order_window(ctx)"))
        for counter in ("window_age_le_100us++",
                        "window_age_101_1000us++", "window_age_gt_1000us++"):
            self.assertIn(counter, flush)
        for field in ("age_le100us", "age_101_1000us", "age_gt1000us",
                      "age_sum_ns", "age_max_ns"):
            self.assertIn(field + "=%llu", status)
        self.assertIn("#include <linux/ktime.h>", DM)

    def test_alpha20_worker_restores_finite_snapshot_requeue(self):
        worker = body("swapz_worker")
        header = (ROOT / "src/kernel/window-policy.h").read_text()
        status = body("swapz_status")
        self.assertIn("for (;;)", worker)
        self.assertIn("remaining = SWAPZ_WORK_QUANTUM_BIOS;", worker)
        self.assertLess(worker.index("for (;;)"),
                        worker.index("remaining = SWAPZ_WORK_QUANTUM_BIOS;"))
        self.assertIn("while (remaining && !list_empty(&local))", worker)
        self.assertIn("remaining -= processed_bios", worker)
        self.assertIn("unsigned int processed_bios = 1", worker)
        self.assertIn("list_splice_tail_init(&ctx->incoming, &local)", worker)
        self.assertIn("list_splice_init(&local, &ctx->incoming)", worker)
        self.assertIn("if (ctx->accepting) {", worker)
        self.assertIn("ctx->worker_requeues++", worker)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", worker)
        self.assertLess(worker.index("list_splice_init(&local, &ctx->incoming)"),
                        worker.index("ctx->worker_requeues++"))
        self.assertIn("cond_resched();", worker)
        self.assertNotIn("swapz_worker_can_inline_drain", worker)
        self.assertNotIn("swapz_worker_can_inline_drain", header)
        self.assertNotIn("worker_inline_drains", status)
        self.assertIn("hrtimer_cancel(&ctx->retention_timer)", body("swapz_drain"))
        self.assertIn("drain_workqueue(ctx->workqueue)", body("swapz_drain"))
        self.assertIn("swapz_flush_window(ctx)", worker)

    def test_retained_burst_target_learns_only_from_admitted_tail(self):
        flush = body("swapz_flush_window")
        worker = body("swapz_worker")
        sample = body("swapz_sample_pack_tail_locked")
        status = body("swapz_status")
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        self.assertIn("swapz_window_initial_burst_target", policy)
        self.assertIn("swapz_window_grow_burst_target", policy)
        self.assertIn("swapz_window_shrink_burst_target", policy)
        self.assertIn("swapz_window_burst_close_ready", policy)
        self.assertIn("ctx->retained_chain_completed", flush)
        self.assertIn("if (chain_continues)", flush)
        self.assertIn("ctx->pack_close_pending_tail_sample = packed_close", flush)
        self.assertIn("list_for_each_entry(entry, local, list)", sample)
        self.assertIn("list_for_each_entry(entry, &ctx->incoming, list)", sample)
        self.assertLess(sample.index("list_for_each_entry(entry, local, list)"),
                        sample.index("list_for_each_entry(entry, &ctx->incoming, list)"))
        self.assertIn("swapz_plain_retained_write(entry->bio)", sample)
        self.assertIn("if (!ctx->pack_close_pending_tail_sample)", sample)
        self.assertNotIn("base_completed", sample)
        self.assertIn("if (tail == 1U)", sample)
        self.assertIn("ctx->retained_tail_target = 0", sample)
        self.assertIn("ctx->single_tail_deferrals++", sample)
        self.assertIn("ctx->retained_single_tail_deferred = true", sample)
        self.assertIn("ctx->single_tail_other_clears++", sample)
        self.assertIn("ctx->retained_tail_target = tail", sample)
        self.assertIn("ctx->retained_single_tail_deferred = false", sample)
        self.assertNotIn("ctx->single_pack_deferred && !ctx->retained_tail_target", sample)
        self.assertIn("swapz_sample_pack_tail_locked(ctx, &local)", worker)
        self.assertIn("swapz_window_shrink_burst_target(", worker)
        self.assertIn("!ctx->retained_chain_completed", worker)
        target_ready = body("swapz_retained_target_close_ready")
        close_ready = body("swapz_retained_pack_close_ready")
        service_dry = body("swapz_service_proven_dry_pack")
        self.assertIn("ctx->retained_single_tail_deferred && ctx->batch_count == 1U",
                      target_ready)
        self.assertIn("ctx->retained_single_tail_deferred && ctx->batch_count == 1U",
                      close_ready)
        self.assertIn("swapz_service_proven_dry_pack(ctx)", close_ready)
        self.assertIn("ctx->batch_count", service_dry)
        self.assertIn("ctx->retained_chain_completed", service_dry)
        self.assertIn("ctx->retained_window_read_bypasses", service_dry)
        self.assertIn("ctx->retained_wave_interrupted", service_dry)
        self.assertIn("ctx->batch_count < 4U", service_dry)
        self.assertIn("!ctx->retained_tail_target", service_dry)
        self.assertIn("swapz_window_burst_close_ready(", close_ready)
        self.assertIn("retained_burst_target=%u", status)
        self.assertIn("if (count < 2U)", policy)
        accept = body("swapz_accept_write")
        companion = body("swapz_resolve_single_tail_companion")
        self.assertIn("swapz_resolve_single_tail_companion(ctx)", accept)
        self.assertIn("ctx->single_tail_companions++", companion)
        self.assertIn("ctx->retained_single_tail_deferred = false", companion)
        self.assertIn("bool deferred_single_tail = ctx->retained_single_tail_deferred", flush)
        self.assertIn("ctx->win1_deadline_deferred_tail++", flush)
        self.assertIn("ctx->win1_idle_deferred_tail++", flush)
        self.assertIn("ctx->single_tail_other_clears++", flush)
        self.assertIn("ctx->single_tail_other_clears++", worker)
        for field in ("single_tail_deferrals", "single_tail_companions",
                      "win1_deadline_deferred_tail", "win1_idle_deferred_tail",
                      "single_tail_other_clears"):
            self.assertIn(field + "=%llu", status)
            self.assertIn("ctx->" + field, status)
        terminal = body("swapz_account_single_tail_terminal")
        finalize = body("swapz_finalize_inflight_write")
        process = body("swapz_process")
        parallel_batch = body("swapz_try_parallel_read_batch")
        self.assertIn("ctx->single_tail_deferred_start_ns = ktime_get_ns()", sample)
        self.assertNotIn("SWAPZ_SINGLE_TAIL_CUTOFF_NS", DM)
        self.assertNotIn("swapz_window_single_tail_deadline_ns(", DM)
        self.assertNotIn("single_tail_age_cutoff_closes", DM)
        self.assertNotIn("single_tail_cutoff_late_companions", DM)
        self.assertNotIn("single_tail_cutoff_original_deadline_ns", DM)
        deadline = body("swapz_retention_deadline_ns")
        self.assertIn("swapz_window_retention_deadline_ns(", deadline)
        self.assertNotIn("single_tail_deferred_start_ns", deadline)
        self.assertIn("!ctx->retained_single_tail_deferred", worker)
        self.assertIn("ctx->single_tail_lower_done_seen = false", sample)
        self.assertIn("ctx->single_tail_read_bypass_seen = false", sample)
        self.assertIn("elapsed <= 250000ULL", terminal)
        self.assertIn("elapsed <= 500000ULL", terminal)
        self.assertIn("elapsed <= 1000000ULL", terminal)
        self.assertIn("elapsed <= 1250000ULL", terminal)
        self.assertIn("elapsed <= 1500000ULL", terminal)
        self.assertIn("elapsed <= 1750000ULL", terminal)
        self.assertIn("single_tail_companion_age_1001_1250us", terminal)
        self.assertIn("single_tail_companion_age_1251_1500us", terminal)
        self.assertIn("single_tail_companion_age_1501_1750us", terminal)
        self.assertIn("single_tail_companion_age_gt1750us", terminal)
        self.assertIn("single_tail_companion_after_lower_done", terminal)
        self.assertIn("single_tail_deadline_after_read_bypass", terminal)
        self.assertIn("single_tail_deadline_after_both", terminal)
        self.assertIn("ctx->single_tail_lower_done_seen = true", finalize)
        self.assertIn("swapz_note_single_tail_read_bypass(ctx)", process)
        self.assertIn("swapz_note_single_tail_read_bypass(ctx)", parallel_batch)
        for label, member in (
                ("single_tail_comp_age_le250us", "single_tail_companion_age_le250us"),
                ("single_tail_comp_age_251_500us", "single_tail_companion_age_251_500us"),
                ("single_tail_comp_age_501_1000us", "single_tail_companion_age_501_1000us"),
                ("single_tail_comp_age_gt1000us", "single_tail_companion_age_gt1000us"),
                ("single_tail_comp_age_1001_1250us", "single_tail_companion_age_1001_1250us"),
                ("single_tail_comp_age_1251_1500us", "single_tail_companion_age_1251_1500us"),
                ("single_tail_comp_age_1501_1750us", "single_tail_companion_age_1501_1750us"),
                ("single_tail_comp_age_gt1750us", "single_tail_companion_age_gt1750us"),
                ("single_tail_deadline_age_le250us", "single_tail_deadline_age_le250us"),
                ("single_tail_deadline_age_251_500us", "single_tail_deadline_age_251_500us"),
                ("single_tail_deadline_age_501_1000us", "single_tail_deadline_age_501_1000us"),
                ("single_tail_deadline_age_gt1000us", "single_tail_deadline_age_gt1000us"),
                ("single_tail_comp_after_lower_done", "single_tail_companion_after_lower_done"),
                ("single_tail_comp_after_read_bypass", "single_tail_companion_after_read_bypass"),
                ("single_tail_comp_after_both", "single_tail_companion_after_both"),
                ("single_tail_deadline_after_lower_done", "single_tail_deadline_after_lower_done"),
                ("single_tail_deadline_after_read_bypass", "single_tail_deadline_after_read_bypass"),
                ("single_tail_deadline_after_both", "single_tail_deadline_after_both")):
            self.assertIn(label + "=%llu", status)
            self.assertIn("ctx->" + member, status)

    def test_worker_wall_and_scheduler_cpu_attribution_are_separate(self):
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        lower = body("swapz_lower")
        accept = body("swapz_accept_write")
        read = body("swapz_read")
        flush = body("swapz_flush_window")
        producer = body("swapz_preparation_worker")
        worker = body("swapz_worker")
        status = body("swapz_status")
        engine_prepare = source_body("swapz_engine_prepare_batched_run", ENGINE)
        engine_complete = source_body("swapz_engine_complete_batched_run", ENGINE)
        self.assertIn("static inline unsigned long long swapz_elapsed_ns", policy)
        self.assertIn("end_ns >= start_ns ? end_ns - start_ns : 0", policy)
        self.assertIn("section_start = ktime_get_ns();", lower)
        self.assertLess(lower.index("section_start = ktime_get_ns();"),
                        lower.index("error = dm_io("))
        self.assertIn("ctx->lower_read_wall_ns +=", lower)
        self.assertIn("ctx->lower_write_wall_ns +=", lower)
        self.assertIn("ctx->lz4_wall_ns += swapz_elapsed_ns", accept)
        self.assertLess(accept.index("length = LZ4_compress_fast("),
                        accept.index("ctx->lz4_wall_ns +="))
        self.assertIn("ctx->decode_wall_ns +=", read)
        self.assertIn("swapz_copy_bio_accounted(bio, ctx->read_page, true", read)
        self.assertIn("ctx->read_engine_nonio_wall_ns +=", read)
        self.assertIn("ctx->window_sort_wall_ns +=", flush)
        self.assertIn("ctx->window_commit_wall_ns +=", flush)
        self.assertIn("ctx->window_commit_nonio_wall_ns +=", flush)
        self.assertIn("e->plan_wall_ns +=", engine_prepare)
        self.assertIn("e->pack_wall_ns +=", engine_prepare)
        self.assertIn("e->publish_wall_ns +=", engine_complete)
        compact = body("swapz_gc_compact_one")
        self.assertIn("ctx->gc_wall_ns +=", compact)
        self.assertIn("swapz_gc_compact_one_inner(ctx)", compact)
        self.assertNotIn("ctx->gc_wall_ns +=", flush)
        self.assertIn("#include <linux/sched.h>", DM)
        self.assertNotIn("#include <linux/sched/cputime.h>", DM)
        self.assertNotIn("task_cputime_adjusted(current", DM)
        cpu_sample = body("swapz_worker_cpu_sample")
        self.assertIn("READ_ONCE(current->se.sum_exec_runtime)", cpu_sample)
        self.assertIn("cpu_start_ns = swapz_worker_cpu_sample()", producer)
        self.assertIn("cpu_start_ns = swapz_worker_cpu_sample()", worker)
        self.assertNotIn("swapz_read_slot_worker", DM)
        self.assertNotIn("read_worker_cpu_ns +=", DM)
        self.assertIn("ctx->preparation_worker_cpu_ns", producer)
        self.assertIn("ctx->ordered_worker_cpu_ns", worker)
        self.assertEqual(producer.count("return;"),
                         producer.count("swapz_account_worker_runtime("))
        self.assertEqual(worker.count("return;"),
                         worker.count("swapz_account_worker_runtime("))
        for key in ("lz4_wall_ns", "decode_wall_ns", "read_copy_wall_ns",
                    "read_copy_bytes", "read_engine_nonio_wall_ns",
                    "window_sort_wall_ns", "window_commit_wall_ns",
                    "window_commit_nonio_wall_ns", "engine_plan_wall_ns",
                    "engine_pack_wall_ns", "engine_publish_wall_ns",
                    "engine_publish_crc_wall_ns",
                    "lower_read_wall_ns", "lower_write_wall_ns",
                    "ordered_worker_wall_ns", "ordered_worker_cpu_ns",
                    "read_worker_cpu_ns", "gc_wall_ns",
                    "gc_choose_wall_ns", "gc_choose_calls",
                    "gc_choose_map_entries", "gc_choose_segment_entries",
                    "gc_relocation_map_entries", "ordered_crc_wall_ns",
                    "prep_lower_write_samples",
                    "prep_lower_write_start_queued",
                    "prep_lower_write_start_nonempty",
                    "prep_lower_write_end_queued",
                    "prep_lower_write_end_nonempty"):
            self.assertIn(key + "=%llu", status)
            self.assertIn("ctx->" + key, status)
        self.assertIn("engine_publish_auth_wall_ns=%llu", status)
        self.assertIn("engine_publish_auth_wall_ns", status)
        self.assertIn("prep_crc_wall_ns=%llu", status)
        self.assertIn("ctx->preparation_crc_wall_ns", status)
        self.assertIn("ordered_lz4_wall_ns=%llu", status)
        self.assertIn("ctx->lz4_wall_ns", status)
        self.assertIn("prep_lz4_wall_ns=%llu", status)
        self.assertIn("ctx->preparation_lz4_wall_ns", status)
        self.assertIn("ordered_write_copy_wall_ns=%llu", status)
        self.assertIn("ctx->ordered_write_copy_wall_ns", status)
        self.assertIn("prep_write_copy_wall_ns=%llu", status)
        self.assertIn("ctx->preparation_copy_wall_ns", status)
        self.assertIn("prep_worker_wall_ns=%llu", status)
        self.assertIn("ctx->preparation_worker_wall_ns", status)
        self.assertIn("ordered_worker_cpu_ns=%llu", status)
        self.assertIn("ctx->ordered_worker_cpu_ns", status)
        self.assertIn("prep_worker_cpu_ns=%llu", status)
        self.assertIn("ctx->preparation_worker_cpu_ns", status)
        self.assertIn("read_worker_cpu_ns=%llu", status)
        self.assertIn("ctx->read_worker_cpu_ns", status)
        self.assertIn("engine_prehashed_records=%u", status)
        self.assertIn("ctx->engine.prehashed_records", status)
        self.assertIn("batch_snapshot_crc_wall_ns=%llu", status)
        self.assertIn("batch_pause_crc_wall_ns=%llu", status)
        self.assertIn("batch_resume_crc_wall_ns=%llu", status)
        self.assertIn("ctx->authority.batch_snapshot_crc_wall_ns", status)
        self.assertIn("ctx->authority.batch_pause_crc_wall_ns", status)
        self.assertIn("ctx->authority.batch_resume_crc_wall_ns", status)
        self.assertIn("swapz_engine_write_window_batched_read_cap(", flush)
        codec = (ROOT / "src/kernel/codec.c").read_text()
        authority = (ROOT / "src/kernel/authority.c").read_text()
        self.assertIn("swapz_append_prehashed(", codec)
        self.assertIn("swapz_lookup_validated(", codec)
        self.assertIn("swapz_lookup_validated_descriptor(", codec)
        self.assertIn("swapz_lookup_validated_descriptor(image, bytes_total, index",
                      authority)
        self.assertIn("swapz_publish_crc32c(a, payload, decoded.payload_length)",
                      authority)
        self.assertIn("swapz_batch_snapshot_crc32c(", authority)
        self.assertIn("&a->batch_pause_crc_wall_ns", authority)
        self.assertIn("&a->batch_resume_crc_wall_ns", authority)
        snapshot = source_body("swapz_batch_snapshot_crc32c", authority)
        self.assertIn("swapz_crc32c_bytes(tx, sizeof(*tx))", snapshot)
        self.assertIn("a->batch_snapshot_crc_wall_ns += elapsed", snapshot)
        self.assertIn("*phase_wall_ns += elapsed", snapshot)
        self.assertNotIn("offsetof(", snapshot)
        self.assertIn("swapz_crc32c_bytes(prepared->bytes", producer)
        self.assertIn("payload_crc32c_valid", accept)
        self.assertNotIn("swapz_note_dry_pack_close", DM)
        self.assertNotIn("swapz_note_dry_pack_followup_locked", DM)

    def test_id61_native_gc_scan_scaling_is_bounded_and_reported(self):
        scale = (ROOT / "tests/runtime/native/gc/scan-scaling.c").read_text()
        suites = (ROOT / "tests/suites/Makefile").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        authority = (ROOT / "src/kernel/authority.h").read_text()

        self.assertIn("262144U, 1048576U", scale)
        self.assertIn("legacy_score_scan", scale)
        self.assertIn("incremental_select", scale)
        self.assertIn("relocation_scan", scale)
        self.assertIn("SWAPZ_GC_SCAN_SCALE_EVIDENCE=", scale)
        self.assertIn("gc-scan-scaling", suites)
        self.assertIn("def parse_gc_scan_scale_evidence", runner)
        self.assertIn("OFFLINE_NATIVE_GC_SCALE_ONLY", runner)
        self.assertNotIn("reverse_index", authority)
        self.assertNotIn("logical_backref", authority)

    def test_id63_read_coalescing_is_cache_coherent(self):
        header = (ROOT / "src/kernel/engine.h").read_text()
        engine = (ROOT / "src/kernel/engine.c").read_text()
        batch = body("swapz_try_parallel_read_batch")
        slot_run = body("swapz_read_slot_run")
        lower = body("swapz_parallel_lower_read")
        invalidation = body("swapz_invalidate_read_caches")
        ctor = body("swapz_ctr")
        freeing = body("swapz_free")
        status = body("swapz_status")

        self.assertIn("#define SWAPZ_PARALLEL_READ_SLOTS 2U", header)
        self.assertIn("#define SWAPZ_READ_EXTENT_CACHE_ENTRIES 16U", header)
        self.assertIn("read_extent_cache", header)
        self.assertIn("swapz_engine_prime_read_slot", header)
        self.assertIn("swapz_engine_absorb_read_slot", header)
        self.assertIn("swapz_engine_required_read_range", header)
        self.assertIn("swapz_engine_required_read_range_cached", header)
        self.assertIn("swapz_engine_coalesced_span", header)
        self.assertIn("swapz_engine_coalesce_read_pair", header)
        self.assertIn("read_coalesced_block_mask", header)
        self.assertIn("struct swapz_read_slot", DM)
        self.assertIn("struct swapz_engine engine;", DM)
        self.assertIn("struct bio *bios[SWAPZ_MAX_RECORDS]", DM)
        self.assertIn("u8 *read_pages", DM)
        self.assertIn("bool parallel_reads_enabled", DM)
        self.assertNotIn("read_workqueue", DM)
        self.assertNotIn("swapz_read_slot_worker", DM)
        self.assertIn("SWAPZ_MERGE_READ_COUNTER(physical_read_blocks)", engine)
        self.assertIn("swapz_read_extent_lru_lookup", engine)
        self.assertIn("swapz_read_extent_lru_commit", engine)
        self.assertIn("swapz_engine_prime_read_slot", engine)
        self.assertIn("swapz_engine_absorb_read_slot", engine)
        self.assertIn("int swapz_engine_required_read_range", engine)
        self.assertIn("int swapz_engine_required_read_range_cached", engine)
        self.assertIn("int swapz_engine_coalesced_span", engine)
        self.assertIn("int swapz_engine_coalesce_read_pair", engine)
        self.assertIn("engine->read_coalesced_block_mask", engine)
        self.assertIn("read_extent_lru_valid",
                      source_body("swapz_engine_invalidate_read_cache", engine))
        self.assertIn("!ctx->read_grouping_enabled", batch)
        self.assertIn("list_for_each_entry(entry, local, list)", batch)
        self.assertIn("swapz_read_can_parallel(ctx, entry->bio)", batch)
        self.assertIn("swapz_parallel_read_extent", batch)
        self.assertIn("swapz_engine_prime_read_slot(&ctx->engine", batch)
        self.assertIn("swapz_engine_required_read_range_cached(", batch)
        self.assertIn("if (!have1 || !ctx->read_coalescing_enabled)", batch)
        self.assertIn("if (!passive_adjacent)", batch)
        self.assertIn("if (!coalesce)", batch)
        self.assertNotIn("if (slot0->bio_count < 2U)", batch)
        self.assertNotIn("have1 = false;", batch)
        self.assertLess(
            batch.index("if (!have1 || !ctx->read_coalescing_enabled)"),
            batch.index("swapz_read_slot_prepare(slot0"))
        self.assertLess(batch.index("if (!passive_adjacent)"),
                        batch.index("swapz_read_slot_prepare(slot0"))
        self.assertLess(batch.index("swapz_engine_required_read_range_cached("),
                        batch.index("swapz_engine_prime_read_slot(&ctx->engine"))
        self.assertLess(batch.index("if (!coalesce)"),
                        batch.index("swapz_engine_prime_read_slot(&ctx->engine"))
        self.assertLess(batch.index("if (!coalesce)"),
                        batch.index("list_del_init(&entry->list)"))
        self.assertNotIn("queue_work(ctx->read_workqueue", batch)
        self.assertNotIn("wait_for_completion(&slot0->done)", batch)
        self.assertNotIn("flush_work(&slot0->work)", batch)
        self.assertIn("slot0->error = swapz_read_slot_run(slot0)", batch)
        self.assertIn("slot1->error = swapz_read_slot_run(slot1)", batch)
        self.assertIn("swapz_engine_absorb_read_slot", body("swapz_merge_read_slot"))
        self.assertIn("*processed_out = selected", batch)
        self.assertIn("swapz_copy_bio_accounted(", batch)
        self.assertIn("swapz_complete(slot0->bios[index]", batch)
        success_complete = batch.rindex("swapz_complete(slot0->bios[index], 0)")
        success_absorb = batch.rindex(
            "swapz_engine_absorb_read_slot(&ctx->engine, &slot0->engine)")
        self.assertLess(success_complete, success_absorb)
        self.assertNotIn("swapz_complete(", slot_run)
        self.assertNotIn("swapz_finish(", slot_run)
        self.assertNotIn("swapz_stage(", slot_run)
        self.assertIn("for (index = 0; index < slot->bio_count; ++index)", slot_run)
        self.assertIn("REQ_OP_READ | REQ_SWAP | REQ_SYNC", lower)
        self.assertNotIn("ctx->physical_read_reqs++", lower)
        self.assertIn("slot->physical_read_reqs++", lower)
        self.assertIn("swapz_engine_invalidate_read_cache(&ctx->engine)", invalidation)
        self.assertIn("swapz_engine_invalidate_read_cache(&ctx->read_slots[slot].engine)",
                      invalidation)
        self.assertIn("static bool swapz_parallel_reads = true;", DM)
        self.assertIn("module_param_named(parallel_reads, swapz_parallel_reads, bool, 0444)", DM)
        self.assertIn("static bool swapz_read_coalesce = true;", DM)
        self.assertIn("module_param_named(read_coalesce, swapz_read_coalesce, bool, 0444)", DM)
        self.assertIn("ctx->read_grouping_enabled = swapz_parallel_reads;", ctor)
        self.assertIn("ctx->read_coalescing_enabled =", ctor)
        self.assertIn("ctx->parallel_reads_enabled = false;", ctor)
        self.assertNotIn("bdev_get_queue(ctx->backing->bdev)->nr_requests > 1U", ctor)
        self.assertIn("if (ctx->read_grouping_enabled)", ctor)
        self.assertIn("SWAPZ_READ_EXTENT_CACHE_ENTRIES * SWAPZ_MAX_EXTENT_BYTES", ctor)
        self.assertNotIn('"swapz-read"', ctor)
        self.assertIn("slot->engine.read_scratch = vzalloc(SWAPZ_MAX_EXTENT_BYTES)", ctor)
        self.assertIn("slot->read_pages = vzalloc(", ctor)
        self.assertIn("vfree(ctx->engine.read_extent_cache)", freeing)
        self.assertIn("vfree(ctx->read_slots[slot].read_pages)", freeing)
        self.assertIn("read_worker_cpu_ns=%llu", status)
        self.assertIn("read_grouping_enabled=%u", status)
        self.assertIn("read_coalescing_enabled=%u", status)
        self.assertIn("parallel_reads_enabled=%u", status)
        self.assertIn("parallel_read_pairs=%llu", status)
        self.assertIn("parallel_read_same_extent_pairs=%llu", status)
        self.assertIn("parallel_read_distinct_extent_pairs=%llu", status)
        self.assertIn("parallel_read_adjacent_extent_pairs=%llu", status)
        self.assertIn("parallel_read_adjacent_extent_blocks=%llu", status)
        self.assertIn("parallel_read_coalesced_pairs=%llu", status)
        self.assertIn("parallel_read_coalesced_reqs_saved=%llu", status)
        self.assertIn("parallel_read_coalesced_blocks=%llu", status)
        self.assertIn("parallel_read_coalesce_extra_blocks=%llu", status)
        for field in (
                "parallel_read_coalesce_skip_cached",
                "parallel_read_coalesce_skip_noncontig_slot",
                "parallel_read_coalesce_skip_gap",
                "parallel_read_coalesce_skip_other"):
            self.assertIn(field + "=%llu", status)

        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertIn("--parallel-reads 0|1", pair)
        self.assertIn("--read-coalesce 0|1", pair)
        self.assertIn('"parallel_reads=$PARALLEL_READS"', pair)
        self.assertIn('"read_coalesce=$READ_COALESCE"', pair)
        self.assertIn("read_grouping_enabled=$expected_grouping", pair)
        self.assertIn("read_coalescing_enabled=$expected_coalescing", pair)
        self.assertIn("expected_parallel=0", pair)
        self.assertIn("parallel_reads_enabled=$expected_parallel", pair)
        self.assertNotIn('for parallel_reads in "${directional_modes[@]}"', loaded)
        self.assertNotIn("START_BURST_GUARD_AB=", loaded)
        self.assertNotIn("PASS_BURST_GUARD_AB=", loaded)
        self.assertNotIn("--guard-inflight-zero-shrink", pair)
        self.assertIn("guard_inflight_zero_shrink=0", pair)
        self.assertNotIn("START_PARALLEL_READ_AB=", loaded)
        self.assertNotIn("START_SD_READ_GROUPING_AB=", loaded)
        self.assertIn("START_READ_COALESCE_AB=", loaded)
        self.assertIn('for read_coalesce in "${confirmation_modes[@]}"', loaded)
        self.assertIn("START_SD_READ_COALESCE_AB=", loaded)
        self.assertIn("--lower-mbps 10 --hw-queue-depth 1 --completion-nsec 1000000",
                      loaded)
        self.assertNotIn("def parse_parallel_read_ab", runner)
        self.assertNotIn("PASS_PARALLEL_READ_DIRECTIONAL_CONTROL", runner)
        self.assertNotIn("def parse_burst_guard_ab", runner)
        self.assertNotIn("PASS_BURST_GUARD_AB_CONFIRMATION", runner)
        self.assertIn("def parse_read_coalesce_ab", runner)
        self.assertIn("PASS_READ_COALESCE_AB_CONFIRMATION", runner)
        self.assertNotIn("def parse_sd_read_grouping_ab", runner)
        self.assertNotIn("PASS_SD_READ_GROUPING_DIRECTIONAL_CONTROL", runner)
        self.assertIn("def parse_sd_read_coalesce_ab", runner)
        self.assertIn("PASS_SD_READ_COALESCE_AB_CONFIRMATION", runner)
        self.assertIn("CONFIRMATION_SEQUENCE = (0, 1, 1, 0, 0, 1, 1, 0, 0, 1)",
                      runner)
        self.assertNotIn("DIRECTIONAL_SEQUENCE =", runner)
        self.assertIn("def paired_ci95", runner)
        self.assertIn('kernel["parallel_read_pairs"]', runner)
        self.assertIn("parallel_read_coalesced_reqs_saved", runner)
        self.assertIn("parallel_read_coalesce_extra_blocks", runner)

    def test_id67_delta64_is_single_candidate_with_arch_dispatch(self):
        predictor = (ROOT / "src/kernel/predictor.h").read_text()
        internal = (ROOT / "src/kernel/predictor-internal.h").read_text()
        dispatch = (ROOT / "src/kernel/predictor.c").read_text()
        sse2 = (ROOT / "src/kernel/predictor-sse2.c").read_text()
        avx2 = (ROOT / "src/kernel/predictor-avx2.c").read_text()
        neon = (ROOT / "src/kernel/predictor-neon.c").read_text()
        qualification = (
            ROOT / "tests/runtime/native/codec/predictor-qualification.c").read_text()
        suites = (ROOT / "tests/suites/Makefile").read_text()
        kbuild = (ROOT / "src/kernel/Makefile").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        workflow = (ROOT / ".github/workflows/product-codec.yml").read_text()
        authority = (ROOT / "src/kernel/authority.c").read_text()
        codec = (ROOT / "src/kernel/codec.c").read_text()
        engine = (ROOT / "src/kernel/engine.c").read_text()

        for retired in ("swapz_predict_cl_delta32x2",
                        "swapz_predict_cl_bytedelta8",
                        "swapz_predict_delta32",
                        "swapz_predict_delta64_512",
                        "swapz_predict_xor64"):
            self.assertNotIn(retired, predictor)
            self.assertNotIn(retired, internal)
            self.assertNotIn(retired, qualification)

        self.assertIn("swapz_predict_delta64_sample_score", predictor)
        self.assertIn("swapz_predict_delta64", predictor)
        self.assertIn("swapz_unpredict_delta64", predictor)
        self.assertIn("swapz_predict_delta64_scalar", internal)
        self.assertIn("swapz_predict_delta64_sample_score_scalar", internal)
        self.assertIn("SWAPZ_PREDICTOR_STAGE1_PAIRS 8U", predictor)
        self.assertIn("SWAPZ_PREDICTOR_SAMPLE_PAIRS 32U", predictor)

        self.assertIn("DEFINE_STATIC_CALL", dispatch)
        self.assertIn("static_call_update", dispatch)
        self.assertIn("kernel_fpu_begin()", dispatch)
        self.assertNotIn("swapz_predictor_score_call", dispatch)
        self.assertIn("return swapz_predict_delta64_sample_score_scalar(input);",
                      dispatch)
        self.assertIn("kernel_fpu_end()", dispatch)
        self.assertIn("X86_FEATURE_AVX2", dispatch)
        self.assertIn("XFEATURE_MASK_YMM", dispatch)
        self.assertIn("X86_FEATURE_XMM2", dispatch)
        self.assertIn("kernel_fpu_available()", dispatch)
        self.assertIn('"avx2"', dispatch)
        self.assertIn('"sse2"', dispatch)
        self.assertIn('"neon"', dispatch)
        self.assertIn("__builtin_cpu_supports(\"avx2\")", dispatch)

        self.assertIn("__attribute__((vector_size(16)))", sse2)
        self.assertIn("__attribute__((vector_size(32)))", avx2)
        self.assertIn("vpslldq", avx2)
        self.assertIn("vpermq", avx2)
        self.assertIn("Advanced SIMD/NEON", neon)
        self.assertIn("__attribute__((vector_size(16)))", neon)
        for retired_score in (
                "swapz_predict_delta64_sample_score_sse2",
                "swapz_predict_delta64_sample_score_avx2",
                "swapz_predict_delta64_sample_score_neon"):
            self.assertNotIn(retired_score, internal)
            self.assertNotIn(retired_score, sse2 + avx2 + neon)

        self.assertIn("predictor.o", kbuild)
        self.assertIn("predictor-sse2.o predictor-avx2.o", kbuild)
        self.assertIn("CFLAGS_predictor-avx2.o += $(CC_FLAGS_FPU) -mavx2",
                      kbuild)
        self.assertIn("CFLAGS_REMOVE_predictor-avx2.o", kbuild)
        self.assertIn("predictor-neon.o", kbuild)
        self.assertIn("CFLAGS_REMOVE_predictor-neon.o += $(CC_FLAGS_NO_FPU)",
                      kbuild)

        self.assertIn("PREDICTOR_TRANSFORM_NAMES = (\"delta64\",)", runner)
        self.assertIn("PREDICTOR_BACKENDS", runner)
        self.assertIn("swapz_predictor_init()", qualification)
        self.assertIn("swapz_predictor_transform_backend_name()", qualification)
        self.assertIn("swapz_predictor_inverse_backend_name()", qualification)
        self.assertIn("swapz_predict_delta64_scalar(page, scalar_transform_page)",
                      qualification)
        self.assertIn("swapz_predict_delta64_sample_score_scalar(page)",
                      qualification)
        self.assertIn("routed_blocks_saved", qualification)
        self.assertIn("benchmark_classifier", qualification)
        self.assertIn("scalar_ns_per_page", qualification)
        self.assertIn("scalar_transform_ns_per_page", qualification)
        self.assertIn("scalar_inverse_ns_per_page", qualification)
        self.assertIn("backend_benchmarks", qualification)
        self.assertIn("routed_cpu_ns_per_page", qualification)
        self.assertIn("ns_per_saved_block", qualification)
        self.assertIn("TRANSFORM_BENCH_REPEATS 64U", qualification)
        self.assertIn("-msse2 -c $(KERNEL)/predictor-sse2.c", suites)
        self.assertIn("-mavx2 -c $(KERNEL)/predictor-avx2.c", suites)
        rootless = (ROOT / "tests/tools/test-rootless.sh").read_text()
        self.assertIn("predictor-sse2.disasm", rootless)
        self.assertIn("predictor-avx2.disasm", rootless)
        self.assertNotIn("objdump -d build/tests/native/predictor-sse2.o |",
                         rootless)
        self.assertIn("liblz4-dev", workflow)

        self.assertIn('#include "predictor.h"', DM)
        init_start = DM.index("static int __init swapz_dm_init")
        init_end = DM.index("static void __exit swapz_dm_exit", init_start)
        init = DM[init_start:init_end]
        self.assertIn("swapz_predictor_init()", init)
        self.assertNotIn("swapz_predict_delta64(", DM)
        self.assertNotIn('#include "predictor.h"', authority)
        self.assertNotIn('#include "predictor.h"', codec)
        self.assertNotIn('#include "predictor.h"', engine)
        self.assertNotIn("payload_filter", codec)
        self.assertNotIn("policy_length", DM)

    def test_id64_is_retired_after_completion_aware_zero_tail_sampling(self):
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        worker = body("swapz_worker")
        flush = body("swapz_flush_window")
        status = body("swapz_status")
        self.assertNotIn("module_param_named(guard_inflight_zero_shrink", DM)
        self.assertNotIn("swapz_window_guard_burst_target_shrink", policy)
        self.assertNotIn("ctx->burst_shrink_inflight_zero_skips++", worker)
        self.assertNotIn("ctx->last_pack_tail_zero_inflight", DM)
        self.assertNotIn("ctx->burst_shrink_after_inflight_zero++", worker)
        self.assertIn("if (!tail && inflight)", body("swapz_sample_pack_tail_locked"))
        self.assertIn("guard_inflight_zero_shrink=%u", status)
        self.assertIn("burst_shrink_inflight_zero_skips=%llu", status)
        self.assertIn("burst_shrink_after_inflight_zero=%llu", status)
        self.assertNotIn("--guard-inflight-zero-shrink", pair)
        self.assertNotIn("START_BURST_GUARD_AB=", loaded)
        self.assertIn("(count > 4U || READ_ONCE(ctx->preparation_queued) > 0U)",
                      flush)

    def test_alpha17_uniform_compressed_windows_skip_greedy_reordering(self):
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        reorder = body("swapz_order_window")
        greedy = body("swapz_order_window_greedy")
        flush = body("swapz_flush_window")
        self.assertIn("swapz_window_uniform_compressed(", policy)
        self.assertIn("!pending || !count || count > SWAPZ_MAX_RECORDS", policy)
        self.assertIn("pending[0].raw || !pending[0].length", policy)
        self.assertIn("pending[index].raw || pending[index].length != length",
                      policy)
        self.assertIn("swapz_window_uniform_compressed(ctx->batch", reorder)
        self.assertIn("ctx->planned_to_batch[position] = position", reorder)
        self.assertIn("swapz_order_window_greedy(ctx)", reorder)
        self.assertLess(reorder.index("swapz_order_window_greedy(ctx)"),
                        reorder.index("ctx->planned[position] ="))
        self.assertIn("ctx->used[largest] = 1", greedy)
        self.assertIn("ctx->planned_to_batch[position++] = (u8)largest",
                      greedy)
        self.assertIn("if (index != position)", reorder)
        self.assertIn("swapz_order_window(ctx)", flush)
        self.assertIn("swapz_engine_write_window_batched_read_cap", flush)

    def test_retention_timer_keeps_ordinary_pinned_deadline(self):
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        worker = body("swapz_worker")
        status = body("swapz_status")
        self.assertIn("swapz_retention_timer_needs_arm(", policy)
        self.assertIn("swapz_window_timer_enabled(retain_ms) && !queued", policy)
        self.assertNotIn("swapz_retention_timer_needs_rearm(", policy)
        self.assertNotIn("hrtimer_get_expires(", worker)
        self.assertIn("hrtimer_is_queued(&ctx->retention_timer)", worker)
        self.assertIn("ns_to_ktime(swapz_retention_deadline_ns(ctx))", worker)
        self.assertLess(worker.index("hrtimer_is_queued(&ctx->retention_timer)"),
                        worker.index("hrtimer_start(&ctx->retention_timer"))
        self.assertIn("ctx->retain_timer_arms++", worker)
        self.assertIn("ctx->retain_timer_arm_skips++", worker)
        self.assertIn("HRTIMER_MODE_ABS", worker)
        self.assertIn("retain_timer_arm_skips=%llu", status)
        self.assertIn("ctx->retain_timer_arm_skips", status)
        self.assertIn("hrtimer_cancel(&ctx->retention_timer)", body("swapz_drain"))
        self.assertIn("hrtimer_cancel(&ctx->retention_timer)", body("swapz_free"))

    def test_alpha15_nonretained_hot_path_skips_unarmed_timer_cancel(self):
        window = (ROOT / "src/kernel/window-policy.h").read_text()
        flush = body("swapz_flush_window")
        worker = body("swapz_worker")
        drain = body("swapz_drain")
        free = body("swapz_free")
        self.assertIn("static inline int swapz_window_timer_enabled", window)
        self.assertIn("return retain_ms != 0;", window)
        self.assertIn("if (swapz_window_timer_enabled(ctx->retain_ms))", flush)
        self.assertIn("hrtimer_cancel(&ctx->retention_timer);", flush)
        self.assertLess(
            flush.index("if (swapz_window_timer_enabled(ctx->retain_ms))"),
            flush.index("hrtimer_cancel(&ctx->retention_timer);"))
        self.assertIn("swapz_window_timer_enabled(ctx->retain_ms)", worker)
        self.assertIn("hrtimer_start(&ctx->retention_timer", worker)
        # Drain and free always cancel, even if admission was disabled.
        self.assertIn("hrtimer_cancel(&ctx->retention_timer);", drain)
        self.assertIn("hrtimer_cancel(&ctx->retention_timer);", free)

    def test_alpha21_geometry_early_closure_only_after_valid_admission(self):
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        writer = body("swapz_accept_write")
        flush = body("swapz_flush_window")
        status = body("swapz_status")
        self.assertIn("swapz_window_pack_ready(", policy)
        self.assertIn("extent_bytes += pending[i].length", policy)
        self.assertIn("sizeof(struct swapz_header)", policy)
        self.assertIn("count * sizeof(struct swapz_record)", policy)
        for count in (2, 3, 4, 6):
            self.assertIn("count == %dU" % count, policy)
        self.assertIn("static inline int swapz_window_single_pack_ready(", policy)
        self.assertIn("static inline int swapz_window_pack_ready(", policy)
        self.assertIn("swapz_window_extent_fits(", policy)
        self.assertIn("!retain_ms || read_budget || !pending", policy)
        self.assertIn("extent_blocks * SWAPZ_BLOCK_BYTES", policy)
        self.assertIn("pending[i].raw", policy)
        self.assertLess(writer.index("ctx->batch_count++"),
                        writer.index("swapz_window_single_pack_ready("))
        self.assertLess(writer.index("ctx->batch_count++"),
                        writer.index("swapz_window_pack_ready("))
        self.assertLess(writer.index("if (bio->bi_opf & REQ_FUA)",
                                     writer.index("ctx->batch_count++")),
                        writer.index("swapz_window_pack_ready("))
        worker = body("swapz_worker")
        # Admission may close exactly at the refreshed effective target;
        # below-target service-proven closure remains worker-tail owned.
        self.assertIn("ctx->next_window_close = SWAPZ_CLOSE_PACK_READY", writer)
        self.assertIn("ctx->next_window_close = SWAPZ_CLOSE_PACK_READY", worker)
        self.assertNotIn("worker_followup_bios", DM)
        refresh = body("swapz_refresh_accepted_followup")
        self.assertIn("spin_lock_irqsave(&ctx->queue_lock, flags)", refresh)
        self.assertIn("!list_empty(&ctx->incoming)", refresh)
        self.assertIn("ctx->worker_has_immediate_followup = true", refresh)
        self.assertIn("swapz_refresh_accepted_followup(ctx)", writer)
        self.assertLess(writer.index("ctx->batch_count++"),
                        writer.index("swapz_refresh_accepted_followup(ctx)"))
        self.assertLess(writer.index("swapz_refresh_accepted_followup(ctx)"),
                        writer.index("swapz_window_single_pack_ready("))
        local_successor = worker.index("entry->list.next != &local")
        initial_refresh = worker.index("swapz_refresh_accepted_followup(ctx)",
                                       local_successor)
        list_delete = worker.index("list_del_init(&entry->list)")
        self.assertLess(local_successor, initial_refresh)
        self.assertLess(initial_refresh, list_delete)
        post_process = worker.index("swapz_process(ctx, entry->bio)")
        tail_guard = worker.index(
            "if (remaining > 1U && list_empty(&local))", post_process)
        tail_splice = worker.index(
            "list_splice_tail_init(&ctx->incoming, &local)", tail_guard)
        self.assertLess(post_process, tail_guard)
        self.assertLess(tail_guard, tail_splice)
        self.assertNotIn("!ctx->worker_has_immediate_followup",
                         worker[post_process:tail_guard])
        self.assertIn("ctx->accepted_burst_pack_ready = true", writer)
        self.assertIn("ctx->accepted_burst_extensions++", writer)
        self.assertIn("ctx->single_pack_deferred = true", writer)
        target_ready = body("swapz_retained_target_close_ready")
        self.assertIn("ctx->single_pack_deferred, 0", target_ready)
        self.assertIn("swapz_retained_target_close_ready(ctx)", writer)
        self.assertIn("!ctx->worker_has_immediate_followup", writer)
        self.assertNotIn("swapz_retained_pack_close_ready(ctx)", writer)
        self.assertIn("swapz_retained_pack_close_ready(ctx)", worker)
        self.assertIn("!ctx->worker_has_immediate_followup", worker)
        self.assertIn("!swapz_retention_expired(ctx)", worker)
        self.assertLess(worker.index("swapz_process(ctx, entry->bio)"),
                        worker.index("list_splice_tail_init(&ctx->incoming, &local)"))
        self.assertLess(worker.index("list_splice_tail_init(&ctx->incoming, &local)"),
                        worker.index("ctx->accepted_burst_tail_flushes++"))
        self.assertLess(worker.index("swapz_sample_pack_tail_locked(ctx, &local)"),
                        worker.index("list_splice_tail_init(&ctx->incoming, &local)"))
        self.assertLess(worker.index("ctx->accepted_burst_tail_flushes++"),
                        worker.index("ctx->worker_has_immediate_followup = false"))
        self.assertIn("ctx->accepted_burst_pack_ready = false", flush)
        self.assertIn("ctx->single_pack_deferred = false", flush)
        self.assertIn("ctx->single_pack_deferrals++", writer)
        self.assertIn("ctx->packed_early_commits++", writer)
        self.assertIn("ctx->packed_early_commits++", worker)
        self.assertIn("swapz_flush_window(ctx)", writer)
        self.assertIn("swapz_flush_window(ctx)", worker)
        self.assertIn("close_pack_ready=%llu", status)
        for field in ("pack_close_tail_target", "pack_close_tail_target_le4",
                      "pack_close_burst_target", "pack_close_service_dry",
                      "pack_close_burst_admission", "pack_close_burst_worker",
                      "pack_close_burst_target_le4", "pack_close_burst_target_5_8",
                      "pack_close_burst_target_9_16", "pack_close_burst_target_17_64",
                      "pack_close_burst_count_le4", "pack_close_burst_count_5_8",
                      "pack_close_burst_count_9_16", "pack_close_burst_count_17_64",
                      "pack_close_burst_overshoot",
                      "pack_tail_samples", "pack_tail_zero_inflight",
                      "pack_tail_zero_idle", "pack_tail_one_inflight",
                      "pack_tail_one_idle", "pack_tail_many_inflight",
                      "pack_tail_many_idle", "burst_target_grows",
                      "burst_target_shrinks",
                      "burst_shrink_after_read_bypass",
                      "burst_shrink_other",
                      "burst_shrink_target_le8",
                      "burst_shrink_target_9_32",
                      "burst_shrink_target_gt32",
                      "k1_ready_wait_windows", "k1_ready_wait_records",
                      "k1_ready_wait_wall_ns", "k1_ready_wait_max_records",
                      "k1_ready_wait_pack_ready", "k1_ready_wait_full",
                      "k1_ready_wait_deadline", "k1_ready_wait_fence",
                      "k1_ready_wait_other"):
            self.assertIn(field + "=%llu", status)
            self.assertIn("ctx->" + field, status)
        for retired in ("burst_shrink_inflight_zero_skips",
                        "burst_shrink_after_inflight_zero"):
            self.assertIn(retired + "=%llu", status)
            self.assertNotIn("ctx->" + retired, DM)
        self.assertIn("SWAPZ_PACK_CLOSE_TAIL_TARGET", writer)
        self.assertIn("SWAPZ_PACK_CLOSE_BURST_TARGET", writer)
        self.assertIn("SWAPZ_PACK_CLOSE_SERVICE_DRY", worker)
        self.assertIn("pack_close_cause", flush)
        self.assertIn("ctx->pack_close_tail_target++", flush)
        self.assertIn("ctx->pack_close_tail_target_le4++", flush)
        self.assertIn("ctx->pack_close_burst_target++", flush)
        self.assertIn("ctx->pack_close_service_dry++", flush)
        self.assertIn("ctx->pack_close_burst_admission++", flush)
        self.assertIn("ctx->pack_close_burst_worker++", flush)
        self.assertIn("ctx->pack_close_burst_target_le4++", flush)
        self.assertIn("ctx->pack_close_burst_count_le4++", flush)
        self.assertIn("ctx->pack_close_burst_overshoot++", flush)
        sample = body("swapz_sample_pack_tail_locked")
        self.assertIn("READ_ONCE(ctx->inflight_write.active)", sample)
        self.assertIn("!completion_done(&ctx->inflight_write.lower_done)", sample)
        self.assertLess(sample.index("if (!tail && inflight)"),
                        sample.index("ctx->pack_tail_samples++"))
        self.assertIn("ctx->pack_tail_samples++", sample)
        for field in ("pack_tail_zero_idle", "pack_tail_one_inflight",
                      "pack_tail_one_idle", "pack_tail_many_inflight",
                      "pack_tail_many_idle", "burst_target_grows"):
            self.assertIn("ctx->" + field + "++", sample)
        self.assertNotIn("ctx->pack_tail_zero_inflight++", sample)
        self.assertNotIn("swapz_window_guard_burst_target_shrink(", worker)
        self.assertNotIn("ctx->burst_shrink_inflight_zero_skips++", worker)
        self.assertNotIn("ctx->last_pack_tail_zero_inflight", DM)
        self.assertNotIn("ctx->burst_shrink_after_inflight_zero++", worker)
        self.assertIn("ctx->burst_shrink_after_read_bypass++", worker)
        self.assertIn("ctx->burst_shrink_other++", worker)
        self.assertIn("ctx->burst_shrink_target_le8++", worker)
        self.assertIn("ctx->burst_shrink_target_9_32++", worker)
        self.assertIn("ctx->burst_shrink_target_gt32++", worker)
        self.assertNotIn("pack_tail_zero_deferred", DM)
        self.assertNotIn("pack_ready_busy_deferrals", DM)
        self.assertNotIn("hold_zero_after_finalize", DM)
        self.assertNotIn("swapz_inflight_write_busy", DM)
        self.assertIn("ctx->k1_ready_wait_windows++", flush)
        self.assertIn("!completion_done(&ctx->inflight_write.lower_done)", flush)
        self.assertIn("ctx->pipeline_finalize_wait_wall_ns", flush)
        self.assertIn("SWAPZ_BURST_CLOSE_ADMISSION", writer)
        self.assertIn("SWAPZ_BURST_CLOSE_WORKER", worker)
        self.assertIn("ctx->next_burst_close_target =", writer)
        self.assertIn("ctx->retained_burst_target", writer)
        self.assertIn("ctx->next_burst_close_target =", worker)
        self.assertIn("packed_early_commits=%llu", status)
        self.assertIn("single_pack_deferrals=%llu accepted_burst_extensions=%llu", status)
        self.assertIn("accepted_burst_tail_flushes=%llu", status)
        self.assertIn("accepted_burst_read_caps=%llu", status)
        self.assertIn("bool accepted_burst_extended = ctx->accepted_burst_pack_ready", flush)
        self.assertIn("swapz_u8 planning_read_cap = ctx->engine.max_read_blocks_per_record", flush)
        self.assertIn("if (accepted_burst_extended && !planning_read_cap)", flush)
        self.assertIn("planning_read_cap = 2U", flush)
        self.assertIn("ctx->accepted_burst_read_caps++", flush)
        self.assertIn("swapz_engine_write_window_batched_read_cap(&ctx->engine", flush)
        self.assertIn("planning_read_cap);", flush)
        self.assertNotIn("swapz_engine_plan_stats(", flush)
        self.assertNotIn("cap3", flush)
        self.assertIn("ctx->window_close_reasons[close_reason]++", flush)

    def test_dead_segment_trim_is_post_deadness_and_advisory(self):
        authority = (ROOT / "src/kernel/authority.c").read_text()
        gc = body("swapz_gc_compact_one_inner")
        discard = body("swapz_discard_dead_segment")
        status = body("swapz_status")
        self.assertIn("a->dead_segment_recycle", authority)
        self.assertLess(authority.index("if (used && a->dead_segment_recycle)"),
                        authority.index("memset(a->live_records + start"))
        self.assertIn("swapz_gc_commit_rotation(a, victim)", gc)
        self.assertLess(gc.index("swapz_gc_commit_rotation(a, victim)"),
                        gc.index("swapz_discard_dead_segment(ctx, victim)"))
        self.assertIn("a->active_start / SWAPZ_SEGMENT_BLOCKS == segment", discard)
        self.assertIn("a->batch_segment == segment", discard)
        self.assertIn("ctx->inflight_write.run.start_block / SWAPZ_SEGMENT_BLOCKS == segment", discard)
        self.assertIn("bdev_max_discard_sectors(ctx->backing->bdev)", discard)
        self.assertIn("blkdev_issue_discard(ctx->backing->bdev", discard)
        self.assertIn("error == -EOPNOTSUPP", discard)
        for field in ("segment_discards_eligible", "segment_discards_issued",
                      "segment_discards_completed", "segment_discards_unsupported",
                      "segment_discards_failed", "segment_discard_sectors",
                      "segment_discard_wall_ns"):
            self.assertIn(field + "=%llu", status)

    def test_timed_window_telemetry_uses_measurement_snapshots(self):
        replay = (ROOT / "tests/runtime/benchmark/io-replay.py").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertIn("WINDOW_INTERVAL_FIELDS", replay)
        self.assertIn("KERNEL_WRITE_COUNTER_FIELDS", replay)
        self.assertIn(
            'KERNEL_WRITE_GAUGE_FIELDS = ("retained_burst_target",)', replay)
        self.assertIn("counters[key] = after[key]", replay)
        self.assertIn("TIMED_WINDOW_COUNTER_FIELDS", runner)
        self.assertIn("def timed_window_error", runner)
        self.assertIn("PACK_CLOSE_PRIMARY_FIELDS", runner)
        self.assertIn("BURST_CLOSE_DETAIL_FIELDS", runner)
        self.assertIn("TAIL_SAMPLE_FIELDS", runner)
        self.assertIn("burst_shrink_inflight_zero_skips", runner)
        self.assertIn("burst_shrink_after_inflight_zero", runner)
        self.assertIn("parallel_read_coalesce_skip_noncontig_slot", runner)
        self.assertIn("K1_READY_WAIT_FIELDS", runner)
        self.assertIn("burst_close_detail_delta_paired_95pct_ci", runner)
        self.assertIn("Mixed burst-close split", runner)
        self.assertIn("Mixed post-PACK tail samples", runner)
        self.assertIn("K=1 ready wait win/records/ms", runner)
        self.assertIn("pack_close_burst_admission", replay)
        self.assertIn("pack_tail_zero_inflight", replay)
        self.assertIn("k1_ready_wait_windows", replay)
        self.assertIn("pipeline_finalize_wait_wall_ns", replay)
        self.assertIn("pack_close_burst_target_5_8", replay)
        self.assertIn("single_tail_comp_age_1001_1250us", runner)
        self.assertIn("ordered_worker_cpu_ns", runner)
        self.assertIn("read_worker_cpu_ns", runner)
        self.assertIn('"kernel_write_path": obj.get("kernel_write_path")',
                      runner)
        self.assertIn(
            "Full-process status includes prefill/warmup/post-mixed work",
            runner)
        self.assertIn(
            "Never use full-process window counters for the QD pilot", runner)

    def test_alpha12_retention_has_absolute_timer_and_drain(self):
        deadline = body("swapz_retention_deadline_ns")
        expiry = body("swapz_retention_expired")
        wake = body("swapz_retention_wake")
        process = body("swapz_process")
        worker = body("swapz_worker")
        flush = body("swapz_flush_window")
        mapping = body("swapz_map")
        drain = body("swapz_drain")
        ctr = body("swapz_ctr")
        status = body("swapz_status")
        self.assertIn("ctx->window_first_ns", deadline)
        self.assertIn("swapz_window_retention_deadline_ns", deadline)
        self.assertNotIn("swapz_window_single_tail_deadline_ns", deadline)
        self.assertNotIn("SWAPZ_SINGLE_TAIL_CUTOFF_NS", DM)
        self.assertNotIn("single_tail_deferred_start_ns", deadline)
        self.assertIn("swapz_window_deadline_expired", expiry)
        self.assertIn("swapz_retention_deadline_ns(ctx)", expiry)
        self.assertIn("ktime_get_ns()", expiry)
        self.assertNotIn("nsecs_to_jiffies64", DM)
        self.assertNotIn("swapz_retention_delay", DM)
        self.assertIn("hrtimer_start(&ctx->retention_timer", worker)
        self.assertIn("swapz_retention_timer_needs_arm(", worker)
        self.assertIn("ns_to_ktime(swapz_retention_deadline_ns(ctx))", worker)
        self.assertIn("HRTIMER_MODE_ABS", worker)
        self.assertIn("spin_lock_irqsave(&ctx->queue_lock", wake)
        self.assertIn("if (ctx->accepting)", wake)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", wake)
        self.assertIn("return HRTIMER_NORESTART", wake)
        for forbidden in ("swapz_flush_window(", "swapz_complete(", "swapz_lower(",
                          "ctx->batch", "ctx->authority", "ctx->window_first_ns"):
            self.assertNotIn(forbidden, wake)
        self.assertIn("SWAPZ_CLOSE_DEADLINE", process)
        before_deadline = process.index("ctx->deadline_before_bio++")
        before_gate = process.rfind("!ctx->worker_has_immediate_followup",
                                    0, before_deadline)
        self.assertGreaterEqual(before_gate, 0)
        after_deadline = process.index("ctx->deadline_after_read++")
        after_gate = process.rfind("!ctx->worker_has_immediate_followup",
                                   before_deadline, after_deadline)
        self.assertGreater(after_gate, before_deadline)
        self.assertIn("ctx->deadline_worker_with_local++", worker)
        self.assertIn("ctx->deadline_worker_empty++", worker)
        self.assertIn("!list_empty(&local)", worker)
        self.assertIn("#define SWAPZ_SINGLETON_DEADLINE_STREAK 2U", DM)
        self.assertIn("ctx->singleton_deadline_streak++", worker)
        self.assertIn("ctx->singleton_fast_close = true", worker)
        self.assertIn("ctx->singleton_fast_close = false", worker)
        self.assertIn("ctx->singleton_fast_close && ctx->batch_count == 1U",
                      worker)
        learned_close = worker.index(
            "ctx->singleton_fast_close && ctx->batch_count == 1U")
        timer_arm = worker.index("hrtimer_start(&ctx->retention_timer",
                                 learned_close)
        self.assertLess(learned_close, timer_arm)
        self.assertIn("ctx->next_window_close = SWAPZ_CLOSE_IDLE",
                      worker[learned_close:timer_arm])
        self.assertIn("ctx->singleton_deadline_streak = 0", flush)
        self.assertIn("ctx->singleton_fast_close = false", flush)
        self.assertIn("bool ordering_boundary =", flush)
        ordering_start = flush.index("bool ordering_boundary =")
        hard_start = flush.index("bool hard_boundary =")
        ordering_reset = flush.index("if (ordering_boundary)")
        empty_flush = flush.index("if (!count)")
        self.assertLess(ordering_start, hard_start)
        self.assertLess(ordering_reset, empty_flush)
        ordering_definition = flush[ordering_start:hard_start]
        for reason in ("SWAPZ_CLOSE_FUA", "SWAPZ_CLOSE_PREFLUSH",
                       "SWAPZ_CLOSE_DISCARD", "SWAPZ_CLOSE_SHUTDOWN",
                       "SWAPZ_CLOSE_OTHER"):
            self.assertIn(reason, ordering_definition)
        self.assertNotIn("SWAPZ_CLOSE_IDLE", ordering_definition)
        self.assertNotIn("SWAPZ_CLOSE_DEADLINE", ordering_definition)
        ordering_reset_block = flush[ordering_reset:empty_flush]
        self.assertIn("ctx->singleton_deadline_streak = 0",
                      ordering_reset_block)
        self.assertIn("ctx->singleton_fast_close = false",
                      ordering_reset_block)
        self.assertIn("swapz_flush_window(ctx)", process)
        self.assertIn("ctx->retain_worker_passes++", worker)
        self.assertIn("ctx->retain_timer_arms++", worker)
        self.assertIn("SWAPZ_CLOSE_SHUTDOWN", worker)
        self.assertIn("ctx->batch_count >= ctx->max_window", worker)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", mapping)
        self.assertIn("WRITE_ONCE(ctx->accepting, false)", drain)
        self.assertLess(drain.index("WRITE_ONCE(ctx->accepting, false)"),
                        drain.index("hrtimer_cancel(&ctx->retention_timer)"))
        self.assertLess(drain.index("spin_unlock_irqrestore"),
                        drain.index("hrtimer_cancel(&ctx->retention_timer)"))
        self.assertLess(drain.index("hrtimer_cancel(&ctx->retention_timer)"),
                        drain.index("flush_delayed_work(&ctx->worker)"))
        freeing = body("swapz_free")
        self.assertLess(freeing.index("hrtimer_cancel(&ctx->retention_timer)"),
                        freeing.index("destroy_workqueue(ctx->workqueue)"))
        self.assertLess(ctr.index("hrtimer_setup(&ctx->retention_timer"),
                        ctr.index("error = dm_get_device("))
        self.assertIn("KERNEL_VERSION(6, 13, 0)", ctr)
        self.assertIn("hrtimer_init(&ctx->retention_timer", ctr)
        self.assertIn("flush_delayed_work(&ctx->worker)", drain)
        self.assertIn("drain_workqueue(ctx->workqueue)", drain)
        self.assertIn("argc > 9", ctr)
        self.assertIn("retain > SWAPZ_MAX_RETAIN_MS", ctr)
        self.assertIn("ctx->retain_ms = retain", ctr)
        for field in ("retain_ms=%u", "retain_passes=%llu",
                      "retain_timer_arms=%llu", "close_deadline=%llu",
                      "deadline_before_bio=%llu",
                      "deadline_after_read=%llu",
                      "deadline_worker_with_local=%llu",
                      "deadline_worker_empty=%llu"):
            self.assertIn(field, status)
        self.assertIn("SWAPZ_CLOSE_DEADLINE", DM)
        self.assertIn("if (bio->bi_opf & REQ_FUA)", body("swapz_accept_write"))

    def test_retained_writes_prepare_before_the_deadline(self):
        mapping = body("swapz_map")
        self.assertIn("!bio_sectors(bio) || ctx->retain_ms", mapping)
        self.assertLess(mapping.index("!bio_sectors(bio) || ctx->retain_ms"),
                        mapping.index("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)"))
        self.assertIn("queue_delayed_work(ctx->workqueue, &ctx->worker, 0)", mapping)
        self.assertNotIn("msecs_to_jiffies", mapping)
        self.assertNotIn("window_first_ns", mapping)
        self.assertNotIn("hrtimer_start", mapping)

    def test_retained_reads_require_independence_and_abort_on_failure(self):
        independent = body("swapz_read_is_independent")
        process = body("swapz_process")
        flush = body("swapz_flush_window")
        for fence in ("!READ_ONCE(ctx->accepting)", "ctx->failed",
                      "ctx->authority.in_flight", "ctx->authority.batch_replaying",
                      "REQ_PREFLUSH | REQ_FUA"):
            self.assertIn(fence, independent)
        self.assertIn("ctx->authority.batch_pending && !inflight_active", independent)
        run_fence = body("swapz_inflight_run_touches_logical")
        self.assertIn("ctx->authority.batch_pending != run->extent_count", run_fence)
        self.assertIn("tx->records[record].logical_page == logical", run_fence)
        self.assertIn("swapz_inflight_run_touches_logical(ctx, logical)", independent)
        self.assertIn("swapz_window_read_independent(ctx->batch, ctx->batch_count",
                      independent)
        self.assertIn("logical, ctx->retain_ms, blocked", independent)
        bypass = process[process.index("if (op == REQ_OP_READ &&"):
                         process.index("if (op != REQ_OP_WRITE ||")]
        self.assertIn("swapz_read_is_independent(ctx, bio)", bypass)
        self.assertLess(bypass.index("error = swapz_read(ctx, bio)"),
                        bypass.index("swapz_fail(ctx, error)"))
        self.assertLess(bypass.index("swapz_fail(ctx, error)"),
                        bypass.index("swapz_flush_window(ctx)"))
        self.assertIn("u64 read_start_ns = ktime_get_ns()", bypass)
        self.assertIn("u64 read_end_ns = ktime_get_ns()", bypass)
        self.assertIn("ctx->window_first_ns += read_elapsed", bypass)
        self.assertIn("ctx->window_first_ns = read_end_ns", bypass)
        service_shift = bypass.index("ctx->window_first_ns += read_elapsed")
        completion = bypass.index("swapz_complete(bio, error)")
        self.assertLess(bypass.index("error = swapz_read(ctx, bio)"),
                        service_shift)
        self.assertLess(service_shift, completion)
        self.assertIn("if (!error && !ctx->worker_has_immediate_followup &&",
                      bypass)
        deadline_gate = bypass.index("!ctx->worker_has_immediate_followup",
                                     completion)
        deadline_expiry = bypass.index("swapz_retention_expired(ctx)",
                                       deadline_gate)
        self.assertLess(completion, deadline_gate)
        self.assertLess(deadline_gate, deadline_expiry)
        self.assertLess(flush.index("if (!count)"),
                        flush.index("ctx->single_pack_deferred = false"))
        self.assertIn("ctx->retained_wave_interrupted", flush)
        evidence_reset = flush[flush.rindex("if (!ctx->retain_ms"):
                               flush.rindex("return 0;")]
        self.assertIn("packed_close && !ctx->worker_has_immediate_followup",
                      evidence_reset)
        self.assertIn("close_reason == SWAPZ_CLOSE_DUPLICATE", evidence_reset)
        self.assertIn("ctx->retained_window_read_bypasses = 0", evidence_reset)
        self.assertIn("ctx->retained_wave_interrupted = false", evidence_reset)
        self.assertIn("swapz_refresh_accepted_followup(ctx)", process)
        normal_read = process[process.index("case REQ_OP_READ:"):
                              process.index("case REQ_OP_DISCARD:")]
        self.assertIn("ctx->retained_window_read_bypasses++", normal_read)
        abort = flush[flush.index("if (ctx->failed)"):
                      flush.index("swapz_order_window(ctx)")]
        self.assertIn("swapz_complete(ctx->batch[index].bio, error)", abort)
        self.assertIn("goto accounted;", abort)
        self.assertNotIn("planned_to_batch", abort)
        self.assertNotIn("swapz_engine_write", abort)
        self.assertLess(flush.index("accounted:"), flush.index("ctx->batch_count = 0"))
        self.assertIn("retained_read_bypasses=%llu", body("swapz_status"))

    def test_id61_foreground_gc_pressure_evidence_is_observational(self):
        choose = body("swapz_gc_choose_victim")
        compact_inner = body("swapz_gc_compact_one_inner")
        compact = body("swapz_gc_compact_one")
        status = body("swapz_status")
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        oracle = (ROOT / "tests/tools/device-roundtrip.c").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        ctor = body("swapz_ctr")

        self.assertIn("ctx->gc_choose_calls++", choose)
        self.assertNotIn("ctx->gc_choose_map_entries++", choose)
        self.assertIn("ctx->segment_mapped_pages[segment]", choose)
        self.assertIn("ctx->gc_scores[segment]", choose)
        self.assertIn("ctx->authority.balance_segment_opens", choose)
        self.assertIn("programs < best_programs", choose)
        self.assertIn("swapz_enable_segment_gc_accounting", ctor)
        self.assertIn("ctx->gc_choose_segment_entries++", choose)
        self.assertIn("ctx->gc_relocation_map_entries++", compact_inner)
        self.assertIn("a->segment_first_page[victim]", compact_inner)
        self.assertIn("next = a->page_next_in_segment[logical]", compact_inner)
        self.assertLess(
            compact_inner.index("next = a->page_next_in_segment[logical]"),
            compact_inner.index("swapz_gc_relocate_one(ctx, victim, logical)"))
        self.assertIn("visited_victim_pages >= expected_victim_pages", compact_inner)
        self.assertIn("visited_victim_pages != expected_victim_pages", compact_inner)
        self.assertIn("ctx->gc_choose_wall_ns +=", compact_inner)
        self.assertIn("ctx->gc_wall_ns +=", compact)
        self.assertIn("swapz_gc_compact_one_inner(ctx)", compact)
        for name in (
                "gc_choose_wall_ns", "gc_choose_calls",
                "gc_choose_map_entries", "gc_choose_segment_entries",
                "gc_relocation_map_entries"):
            self.assertIn(name + "=%llu", status)
            self.assertIn("ctx->" + name, status)

        self.assertIn("GC_PRESSURE_ROUND=", oracle)
        self.assertIn("CLOCK_MONOTONIC", oracle)
        self.assertIn("write_p99_ns", oracle)
        self.assertIn("PASS_LOADED_GC_PRESSURE=", deploy)
        self.assertIn("gc_fraction_ppm", deploy)
        self.assertIn("gc_choose_map_entries == 0", deploy)
        self.assertIn("gc_relocation_map_entries == gc_pages", deploy)
        self.assertIn('"gc_pressure": re.compile(', runner)
        self.assertIn('"gc_fraction_ppm": gc_fraction_ppm', runner)
        self.assertIn('"gc_no_headroom_skips": gc_no_headroom_skips', runner)

        # This phase measures the current foreground collector only. It does
        # not add a background worker or alter victim scoring/allocation.
        self.assertNotIn("gc_workqueue", DM)
        self.assertNotIn("queue_work(ctx->gc", DM)
        self.assertNotIn("kthread", compact_inner)

    def test_gc_status_is_truthful(self):
        self.assertIn("mode=alpha-live-gc", body("swapz_status"))
        self.assertNotIn("mode=alpha-no-gc", body("swapz_status"))
        self.assertIn("experimental live GC", DM)

    def test_k1_ping_pong_lower_run_keeps_publication_on_ordered_worker(self):
        submit = body("swapz_submit_inflight_write")
        done = body("swapz_async_lower_write_done")
        finalize = body("swapz_finalize_inflight_write")
        flush = body("swapz_flush_window")
        worker = body("swapz_worker")
        drain = body("swapz_drain")
        self.assertIn(".fn = swapz_async_lower_write_done", submit)
        self.assertIn("DM_IO_VMA", submit)
        self.assertIn("complete(&inflight->lower_done)", done)
        self.assertNotIn("swapz_finish(", done)
        self.assertNotIn("bio_endio", done)
        self.assertIn("swapz_engine_complete_batched_run", finalize)
        self.assertIn("ctx->pipeline_active_wall_ns +=", finalize)
        self.assertIn("swapz_complete(inflight->bios[index]", finalize)
        self.assertIn("prepared == count", flush)
        self.assertIn("async_submitted = true", flush)
        self.assertIn("ctx->inflight_write.bios[index] = bio", flush)
        self.assertIn("pipeline_collected_pages", DM)
        self.assertIn("pipeline_active_wall_ns=%llu", body("swapz_status"))
        self.assertIn("completion_done(&ctx->inflight_write.lower_done)", worker)
        self.assertIn("wait_for_completion(&ctx->inflight_write.lower_done)", drain)
        self.assertIn("READ_ONCE(ctx->inflight_write.active)", drain)

    def test_bvec_iterator_is_not_double_advanced_for_folio_slices(self):
        copy = body("swapz_copy_bio")
        direct = body("swapz_map_single_bio_input")
        self.assertIn("bio_for_each_segment(vec, bio, iter)", copy)
        self.assertIn("kmap_local_page(vec.bv_page)", copy)
        self.assertNotIn("nth_page(", copy)
        self.assertIn("bio_for_each_segment(vec, bio, iter)", direct)
        self.assertNotIn("nth_page(", direct)

    def test_async_lz4_preparation_overlaps_lower_io_without_publication(self):
        producer = body("swapz_preparation_worker")
        accept = body("swapz_accept_write")
        mapper = body("swapz_map")
        ordered = body("swapz_worker")
        lower = body("swapz_lower")
        finish = body("swapz_complete")
        release = body("swapz_release_prepared")
        ctor = body("swapz_ctr")
        drain = body("swapz_drain")
        freeing = body("swapz_free")
        status = body("swapz_status")
        benchmark = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()

        self.assertRegex(DM, r"static\s+bool\s+swapz_async_prepare\s*=\s*true\s*;")
        self.assertIn(
            "module_param_named(async_prepare, swapz_async_prepare, bool, 0444);",
            DM)
        self.assertIn("ctx->async_prepare = swapz_async_prepare", ctor)
        self.assertIn("INIT_WORK(&ctx->preparation_worker, swapz_preparation_worker)", ctor)
        self.assertIn('"swapz", WQ_MEM_RECLAIM | WQ_UNBOUND, 1', ctor)
        self.assertIn('"swapz-lz4", WQ_MEM_RECLAIM | WQ_UNBOUND,', ctor)
        self.assertIn("mempool_create_kmalloc_pool(", ctor)
        self.assertIn("ctx->preparation_lz4_workmem", ctor)
        self.assertIn("sema_init(&ctx->preparation_slots, SWAPZ_MAX_RECORDS)", ctor)
        self.assertIn("down_trylock(&ctx->preparation_slots)", producer)
        self.assertNotIn("down(&ctx->preparation_slots)", producer)
        self.assertIn("mempool_alloc(ctx->preparation_pool, GFP_NOIO)", producer)
        self.assertLess(producer.index("down_trylock(&ctx->preparation_slots)"),
                        producer.index("spin_lock_irqsave(&ctx->queue_lock, flags)"))
        self.assertLess(producer.index("down_trylock(&ctx->preparation_slots)"),
                        producer.index("list_del_init(&entry->preparation_list)"))
        self.assertIn("LZ4_compress_fast(", producer)
        self.assertIn("ctx->preparation_lz4_workmem", producer)
        self.assertIn("if (atomic_read(&ctx->lower_write_active))", producer)
        self.assertIn("list_first_entry(&ctx->preparation_incoming", producer)
        self.assertIn("list_last_entry(&ctx->preparation_incoming", producer)
        self.assertIn("list_is_singular(&ctx->preparation_incoming)", producer)
        self.assertIn("SWAPZ_PREPARATION_TAIL_CLAIM_MIN", producer)
        self.assertIn("atomic_xchg(&ctx->preparation_tail_credit, 0)", producer)
        self.assertLess(producer.index("list_is_singular(&ctx->preparation_incoming)"),
                        producer.index("atomic_xchg(&ctx->preparation_tail_credit, 0)"))
        self.assertIn("ctx->preparation_producer_head_claims++", producer)
        self.assertIn("ctx->preparation_producer_tail_claims++", producer)
        self.assertIn("if (tail_claim && !atomic_read(&ctx->lower_write_active) &&",
                      producer)
        self.assertIn("!atomic_read(&ctx->preparation_tail_credit)", producer)
        self.assertNotIn("ctx->lz4_workmem", producer)
        self.assertIn("complete(&entry->preparation_finished)", producer)
        for forbidden in ("swapz_complete(", "swapz_finish(", "swapz_stage(",
                          "swapz_flush_window(", "dm_io(", "bio_endio(",
                          "swapz_engine_write_window"):
            self.assertNotIn(forbidden, producer)
        self.assertIn("queue_work(ctx->preparation_workqueue", mapper)
        self.assertIn("atomic_read(&ctx->lower_write_active)", mapper)
        self.assertIn("atomic_read(&ctx->preparation_tail_credit)", mapper)
        self.assertIn("ctx->preparation_queued >= SWAPZ_PREPARATION_TAIL_WAKE_MIN",
                      mapper)
        self.assertNotIn("atomic_read(&ctx->ordered_worker_busy)", mapper)
        self.assertNotIn("ctx->batch_count", mapper)
        self.assertNotIn("ctx->incoming.next != &entry->list", mapper)
        self.assertNotIn("ctx->preparation_incoming.next != &entry->preparation_list",
                         mapper)
        self.assertNotIn("list_is_singular(&ctx->preparation_incoming)", mapper)
        self.assertLess(mapper.index("list_add_tail(&entry->list"),
                        mapper.index("queue_work(ctx->preparation_workqueue"))
        self.assertIn("queue_work(ctx->preparation_workqueue", lower)
        self.assertIn("ctx->preparation_queued", lower)
        self.assertIn("ctx->prep_lower_write_start_queued", lower)
        self.assertIn("ctx->prep_lower_write_end_queued", lower)
        self.assertLess(lower.index("atomic_set(&ctx->lower_write_active, 1)"),
                        lower.index("queue_work(ctx->preparation_workqueue"))
        self.assertLess(lower.index("queue_work(ctx->preparation_workqueue"),
                        lower.index("error = dm_io("))
        self.assertIn("wait_for_completion(&entry->preparation_finished)", ordered)
        self.assertIn("!list_empty(&entry->preparation_list)", ordered)
        self.assertIn("list_del_init(&entry->preparation_list)", ordered)
        self.assertIn("entry->preparation_inline = true", ordered)
        self.assertNotIn("ordered_worker_busy", DM)
        self.assertIn("atomic_set(&ctx->preparation_tail_credit, 1)", ordered)
        self.assertIn("atomic_set(&ctx->preparation_tail_credit, 0)", ordered)
        parallel_read = body("swapz_try_parallel_read_batch")
        self.assertNotIn("atomic_set(&ctx->preparation_tail_credit, 1)",
                         parallel_read)
        nonwrite_start = ordered.index("} else if (ctx->async_prepare)")
        nonwrite_end = ordered.index("} else {", nonwrite_start)
        self.assertNotIn("queue_work(ctx->preparation_workqueue",
                         ordered[nonwrite_start:nonwrite_end])
        self.assertIn("bool inline_preparation = false", ordered)
        self.assertIn("inline_preparation = true", ordered)
        self.assertIn("!ctx->batch_count", ordered)
        self.assertIn("ctx->singleton_fast_close", ordered)
        self.assertIn("ctx->preparation_ordered_inline++", ordered)
        self.assertIn("ctx->preparation_ordered_handoffs++", ordered)
        self.assertIn("ctx->preparation_ordered_waits++", ordered)
        self.assertIn("ctx->preparation_ordered_wait_wall_ns +=", ordered)
        self.assertIn("completion_done(&entry->preparation_finished)", ordered)
        self.assertIn("list_splice_init(&ctx->incoming, &local)", ordered)
        self.assertIn("SWAPZ_PREPARATION_STARTER_WAKE_MIN", ordered)
        self.assertIn("SWAPZ_PREPARATION_TAIL_WAKE_MIN", ordered)
        self.assertIn("ctx->preparation_wave_kicks++", ordered)
        self.assertIn("#define SWAPZ_PREPARATION_TAIL_WAKE_MIN 4U", DM)
        self.assertIn("#define SWAPZ_PREPARATION_TAIL_CLAIM_MIN 2U", DM)
        wave_splice = ordered.index("list_splice_init(&ctx->incoming, &local)")
        wave_kick = ordered.index("ctx->preparation_wave_kicks++")
        first_entry = ordered.index("entry = list_first_entry(&local")
        self.assertLess(wave_splice, wave_kick)
        self.assertLess(wave_kick, first_entry)
        steal = ordered.index("entry->preparation_inline = true")
        producer_kick = ordered.index("queue_work(ctx->preparation_workqueue",
                                      steal)
        self.assertLess(steal, producer_kick)
        self.assertIn("spin_lock_irqsave(&ctx->queue_lock, flags)", ordered)
        self.assertLess(ordered.index("wait_for_completion("),
                        ordered.index("swapz_process(ctx, entry->bio)"))
        self.assertIn("prepared_async = ctx->async_prepare && !entry->preparation_inline", accept)
        self.assertIn("entry->prepared_page->bytes", accept)
        self.assertIn("ctx->lz4_workmem", accept)
        self.assertIn("swapz_release_prepared(bio)", accept)
        self.assertIn("swapz_release_prepared(bio)", finish)
        self.assertLess(finish.index("swapz_release_prepared(bio)"),
                        finish.index("bio_endio(bio)"))
        self.assertIn("mempool_free(", release)
        self.assertIn("up(entry->preparation_slots)", release)
        self.assertIn("atomic_set(&ctx->lower_write_active, 1)", lower)
        self.assertIn("atomic_set(&ctx->lower_write_active, 0)", lower)
        flush = body("swapz_flush_window")
        count_return = flush.index("if (!count)")
        credit_reset = flush.index("atomic_set(&ctx->preparation_tail_credit, 0)")
        self.assertLess(count_return, credit_reset)
        self.assertIn("atomic_set(&ctx->preparation_tail_credit, 0)", ctor)
        self.assertIn("prep_producer_head_claims=%llu prep_producer_tail_claims=%llu",
                      status)
        self.assertIn("prep_ordered_inline=%llu prep_ordered_handoffs=%llu", status)
        self.assertIn("prep_ordered_waits=%llu prep_wait_wall_ns=%llu", status)
        self.assertIn("prep_lower_write_overlap_ns=%llu prep_wave_kicks=%llu",
                      status)
        self.assertIn("ctx->preparation_lz4_lower_write_overlap_ns +=", producer)
        flush = body("swapz_flush_window")
        self.assertIn("!ctx->retained_window_read_bypasses", flush)
        self.assertIn("(count > 4U || READ_ONCE(ctx->preparation_queued) > 0U)",
                      flush)
        self.assertIn("drain_workqueue(ctx->preparation_workqueue)", drain)
        self.assertLess(drain.index("drain_workqueue(ctx->preparation_workqueue)"),
                        drain.index("drain_workqueue(ctx->workqueue)"))
        self.assertIn("destroy_workqueue(ctx->preparation_workqueue)", freeing)
        self.assertIn("mempool_destroy(ctx->preparation_pool)", freeing)
        self.assertIn("kfree(ctx->preparation_lz4_workmem)", freeing)
        self.assertIn("ctx->lz4_wall_ns + ctx->preparation_lz4_wall_ns", status)
        self.assertIn("write_copy_wall_ns=%llu write_copy_bytes=%llu", status)
        self.assertIn("direct_lz4_input_pages=%llu", status)
        self.assertIn("static const u8 *swapz_map_single_bio_input", DM)
        self.assertIn("swapz_map_single_bio_input(entry->bio", producer)
        self.assertIn("swapz_map_single_bio_input(bio", accept)
        self.assertIn("kunmap_local(mapped_input)", producer)
        self.assertIn("kunmap_local(mapped_input)", accept)
        self.assertIn("bulk_raw_eligible", accept)
        self.assertIn("raw_staged_in_batch", accept)
        self.assertIn("length <= 0 && mapped_input && bulk_raw_eligible", accept)
        self.assertIn("else if (!raw_staged_in_batch)", accept)
        self.assertNotIn("ctx->input_page, input, SWAPZ_BLOCK_BYTES", accept)
        self.assertIn("ctx->preparation_copy_wall_ns +", status)
        self.assertIn("ctx->ordered_write_copy_wall_ns", status)
        self.assertIn("swapz_copy_bio_accounted(entry->bio", producer)
        self.assertIn("swapz_memcpy_accounted(prepared->bytes", producer)
        self.assertIn("swapz_memcpy_accounted(", accept)
        self.assertIn("async_prepare=%u guard_inflight_zero_shrink=%u",
                      status)
        self.assertIn("prep_lower_write_overlap_starts=%llu", status)
        self.assertIn("insmod \"$MODULE\" \"async_prepare=$ASYNC_PREPARE\"",
                      benchmark)
        self.assertRegex(benchmark, r"(?m)^ASYNC_PREPARE=0$")
        self.assertIn("--async-prepare", benchmark)
        self.assertIn("async_prepare=1([[:space:]]|$)", deploy)
        self.assertIn('status_u64 "$packed_before" async_prepare', deploy)
        self.assertGreaterEqual(deploy.count('insmod "$MODULE"'), 2)
        self.assertIn("RATE_MODE != unpaced", benchmark)
        # The mandatory run now has exactly TWO delay-modeled owned-RAM
        # environments, not the historical bandwidth/uncapped controls.
        self.assertIn("LOWER_MBPS=0", benchmark)
        self.assertIn("10:1000000:1|80:150000:64", benchmark)
        self.assertIn('echo "$LOWER_MBPS" > "$config/mbps"', benchmark)
        self.assertIn('echo "$COMPLETION_NSEC" > "$config/completion_nsec"', benchmark)
        self.assertIn('echo "$IRQMODE" > "$config/irqmode"', benchmark)
        self.assertIn('echo "$QUEUE_MODE" > "$config/queue_mode"', benchmark)
        self.assertIn('echo "$SUBMIT_QUEUES" > "$config/submit_queues"', benchmark)
        self.assertIn('echo "$HW_QUEUE_DEPTH" > "$config/hw_queue_depth"', benchmark)
        self.assertIn("PASS_RAM_MODEL_LOWER_MBPS=", benchmark)
        self.assertIn("LOWER_MBPS=$LOWER_MBPS", benchmark)
        self.assertIn("def device_model_limits", runner)
        self.assertIn("unmerged_4k_latency_ceiling_mbps", runner)
        self.assertIn("DEVICE MODEL LIMITS", runner)
        replay = (ROOT / "tests/runtime/benchmark/io-replay.py").read_text()
        self.assertIn('prep.add_argument("--sustained-write"', replay)
        self.assertIn('replay_mode = "persistent-write"', replay)
        self.assertIn("def persistent_write_worker(lane)", replay)
        self.assertIn("ready = threading.Barrier(mf[\"qd\"] + 1)", replay)
        self.assertIn("start_gate = threading.Barrier(mf[\"qd\"] + 1)", replay)
        self.assertIn('Path("/sys/block") / disk_name / "inflight"', replay)
        self.assertIn("LOWER_INFLIGHT_SAMPLE_INTERVAL_NS = 500000", replay)
        self.assertIn('"lower_inflight": lower_inflight', replay)

    def test_loaded_dirty_source_gate_ignores_only_canonical_report(self):
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        benchmark = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        pathspec = "' :(exclude)test_results.json.xz'".replace("' :", "':")
        for script in (deploy, benchmark):
            self.assertIn("export GIT_OPTIONAL_LOCKS=0", script)
            self.assertLess(script.index("export GIT_OPTIONAL_LOCKS=0"),
                            script.index("git branch --show-current"))
            self.assertIn("git diff --quiet -- . " + pathspec, script)
            self.assertIn("git diff --cached --quiet -- . " + pathspec, script)
            self.assertNotIn("git diff --quiet && git diff --cached --quiet", script)

    def test_owned_nullblk_smoke_qualifies_retained_synthetic_faults(self):
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        # These are deliberately pre-submission injections on the already
        # authenticated RAM null_blk lower, not claims about torn/device faults.
        self.assertIn('echo 2 > "$CONFIG/queue_mode"', deploy)
        self.assertIn('echo 1 > "$CONFIG/submit_queues"', deploy)
        self.assertIn('echo 1 > "$CONFIG/hw_queue_depth"', deploy)
        self.assertIn("PASS_RETAINED_SYNTHETIC_WRITE_FAULT=", deploy)
        self.assertIn("PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=", deploy)
        self.assertIn('--table "0 32768 swapz $LOWER 0 64 1 2 0 1 1 2"', deploy)
        self.assertIn('--table "0 32768 swapz $LOWER 0 64 1 2 1 1 0 2"', deploy)
        self.assertIn('status_u64 "$write_fault_status_before" retain_ms', deploy)
        self.assertIn('status_u64 "$flush_fault_status_before" retain_ms', deploy)
        self.assertIn('write_fault_lower_after[6] == write_fault_lower_before[6]',
                      deploy)
        self.assertIn('status_u64 "$write_fault_status_after" write_fault_injected',
                      deploy)
        self.assertIn('status_u64 "$flush_fault_status_after" flush_injected',
                      deploy)
        self.assertIn('status_u64 "$flush_fault_status_after" flush_err', deploy)
        self.assertIn('flush_fault_lower_after[6] > flush_fault_lower_before[6]',
                      deploy)
        self.assertIn('if timeout --signal=TERM --kill-after=5s 20s dd', deploy)
        self.assertIn("PASS_LOADED_ORACLE_PROFILE=", deploy)
        self.assertIn("raw_writes == 64", deploy)
        self.assertIn("flush_ok == flush_calls", deploy)
        self.assertIn("START_LOADED_LIVE_GC", deploy)
        self.assertIn("--gc-stress 5", deploy)
        self.assertIn("gc_victims >= 2", deploy)
        self.assertIn("gc_rotations == gc_victims", deploy)
        self.assertIn("gc_victim != gc_destination", deploy)
        self.assertIn("PASS_LOADED_LIVE_GC=", deploy)
        self.assertIn("PASS_LOADED_GC_PRESSURE=", deploy)
        self.assertIn("PASS_LOADED_DISCARD_TRIM=", deploy)
        self.assertIn("--discard-pages 0 256", deploy)
        self.assertIn("--raw-write-series 4096", deploy)
        self.assertIn("trim_reuse_delta >= 1", deploy)
        self.assertIn("PASS_LOADED_PACKED_PLACEMENT=", deploy)
        self.assertNotIn('insmod "$MODULE" packed_placement=1', deploy)
        self.assertIn("packed_holes == 0 && packed_splits == 0", deploy)
        self.assertIn("tail_waste_fg == alignment_hole_fg", deploy)
        self.assertIn("tail_waste_gc == alignment_hole_gc", deploy)
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        runner = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertNotIn("START_PACKED_PLACEMENT_REGIME=", loaded)
        self.assertNotIn("START_PACKED_PLACEMENT_AB=", loaded)
        self.assertNotIn("placement_modes=", loaded)
        self.assertNotIn("--packed-placement", pair)
        self.assertNotIn("PACKED_PLACEMENT", pair)
        self.assertNotIn("packed_placement_ab_verdict", runner)
        self.assertIn("GC_PRESSURE_ROUND=", (ROOT / "tests/tools/device-roundtrip.c").read_text())
        self.assertIn("START_LOADED_SUSPEND_DRAIN", deploy)
        self.assertIn('--table "0 32768 swapz $LOWER 0 64 1 2 0 1 0 4"', deploy)
        self.assertIn("timer_arms > lifecycle_windows", deploy)
        self.assertIn('while kill -0 "$writer_pid" 2>/dev/null', deploy)
        self.assertNotIn("for i in {1..400}", deploy)
        self.assertLess(deploy.index('>"$SESSION/suspend-writer.log" 2>&1 &'),
                        deploy.index('while kill -0 "$writer_pid" 2>/dev/null'))
        self.assertIn('dmsetup suspend "$DMNAME"', deploy)
        self.assertIn('dmsetup resume "$DMNAME"', deploy)
        self.assertIn("observed_open:$open_window", deploy)
        self.assertIn("lifecycle_failed == 0", deploy)
        self.assertIn("PASS_LOADED_SUSPEND_DRAIN=", deploy)
        self.assertNotIn("shutdown_after > shutdown_before", deploy)
        self.assertIn("SUSPENDED=0", deploy)
        self.assertNotIn("dmsetup remove -f", deploy)
        self.assertNotIn("dmsetup remove --force", deploy)
        oracle = (ROOT / "tests/tools/device-roundtrip.c").read_text()
        self.assertIn("--write-series", oracle)
        self.assertIn("--verify-series", oracle)
        self.assertIn("--raw-write-series", oracle)
        self.assertIn("--raw-verify-series", oracle)
        self.assertIn("--discard-pages", oracle)
        self.assertIn("BLKDISCARD", oracle)
        self.assertIn("--gc-stress", oracle)
        self.assertIn("GC_PAGES = 4096", oracle)
        self.assertIn("gc_expected_round", oracle)
        self.assertIn("(page % 256U) < round", oracle)
        self.assertIn("offset < rounds - 1U ? offset : rounds - 1U", oracle)
        self.assertIn("LIVE_GC_EVIDENCE=", deploy)
        self.assertIn("dead_segment_reuses", deploy)
        self.assertIn("gc_no_headroom_skips", deploy)
        self.assertIn("open_flags &= ~O_SYNC", oracle)
        self.assertIn('const char *prefix = "/dev/mapper/swapz-demo-"', oracle)
        self.assertNotIn("tests/runtime/write-fault.sh", deploy)
        self.assertNotIn("tests/runtime/read-fault.sh", deploy)

    def test_map_and_teardown_are_owned(self):
        admitted = body("swapz_map")
        drained = body("swapz_drain")
        self.assertIn("dm_per_bio_data(", admitted)
        self.assertIn("WQ_MEM_RECLAIM", body("swapz_ctr"))
        self.assertIn("drain_workqueue(ctx->workqueue)", drained)
        self.assertLess(drained.index("mod_delayed_work(ctx->workqueue"),
                        drained.index("flush_delayed_work(&ctx->worker)"))
        self.assertLess(drained.index("flush_delayed_work(&ctx->worker)"),
                        drained.index("drain_workqueue(ctx->workqueue)"))
        self.assertIn("cancel_delayed_work_sync(&ctx->worker)", body("swapz_free"))
        self.assertIn("destroy_workqueue(ctx->workqueue)", body("swapz_free"))
        self.assertLess(admitted.index("spin_lock_irqsave(&ctx->queue_lock"),
                        admitted.index("if (!ctx->accepting)"))
        self.assertLess(admitted.index("if (!ctx->accepting)"),
                        admitted.index("list_add_tail(&entry->list"))
        self.assertLess(admitted.index("queue_delayed_work(ctx->workqueue"),
                        admitted.index("spin_unlock_irqrestore(&ctx->queue_lock, flags);\n\treturn DM_MAPIO_SUBMITTED"))
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", admitted)
        self.assertIn("flush_delayed_work(&ctx->worker)", drained)
        self.assertLess(drained.index("WRITE_ONCE(ctx->accepting, false)"),
                        drained.index("drain_workqueue(ctx->workqueue)"))
        self.assertIn("spin_lock_irqsave(&ctx->queue_lock", drained)


if __name__ == "__main__":
    unittest.main(verbosity=2)
