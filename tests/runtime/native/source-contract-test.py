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
MK = (ROOT / "src/kernel/Makefile").read_text()
README = (ROOT / "docs/README.md").read_text()


def body(symbol: str) -> str:
    match = re.search(r"static\s+(?:int|void|bool|unsigned\s+long|enum\s+hrtimer_restart)\s+" + re.escape(symbol) +
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
    match = re.search(r"(?:static\s+)?(?:int|void)\s+" + re.escape(symbol) +
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

    def test_write_saturation_pilot_stays_private_bounded_and_write_only(self):
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        pair = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        reporter = (ROOT / "tests/tools/run-tests.py").read_text()
        for qd in ("1", "4", "8", "32"):
            self.assertIn("for qd in 1 4 8 32", loaded)
        self.assertIn("--read-pct 0", loaded)
        self.assertIn("--write-only-qd", loaded)
        self.assertIn("START_WRITE_SATURATION_PAIR_QD=", loaded)
        self.assertIn("PASS_WRITE_SATURATION_PAIR_QD=", loaded)
        self.assertIn("WRITE_ONLY_QD=0", pair)
        self.assertIn("READ_PCT=0", pair)
        self.assertIn("PACKED_READ=0", pair)
        self.assertIn("ASYNC_PREPARE && !WRITE_ONLY_QD", pair)
        self.assertIn("def parse_write_saturation", reporter)
        self.assertIn("PASS_WRITE_SATURATION_PILOT", reporter)
        self.assertIn("NOT_ESTABLISHED_ONE_PAIR_PER_MODE_QD", reporter)


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
        self.assertNotIn("LZ4_compress_fast(", body("swapz_gc_compact_one"))

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
        self.assertIn("swapz_engine_invalidate_read_cache(&ctx->engine)",
                      body("swapz_lower"))
        self.assertIn("swapz_engine_invalidate_read_cache(&ctx->engine)",
                      body("swapz_process"))
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
        self.assertIn("swapz_gc_compact_one(ctx)", body("swapz_flush_window"))
        self.assertIn("swapz_gc_compact_one(ctx)", body("swapz_raw_write"))
        self.assertIn("swapz_gc_choose_victim(ctx,", body("swapz_gc_compact_one"))
        self.assertIn("if (a->live_records[start + off])", AUTH)
        self.assertIn("if (map->start_block / SWAPZ_SEGMENT_BLOCKS == segment)", AUTH)
        self.assertIn("cost = swapz_gc_live_byte_cost(m)", DM)
        self.assertIn("ctx->gc_scores[segment] += cost", DM)
        self.assertIn("swapz_gc_prefer(score, count, best, best_count)", DM)
        self.assertIn("swapz_engine_read_page(&ctx->engine", body("swapz_gc_compact_one"))
        self.assertIn("swapz_gc_flush(ctx)", body("swapz_gc_compact_one"))
        self.assertIn("swapz_finish_raw(&ctx->authority", body("swapz_gc_move_raw"))
        self.assertIn("if (a->live_records[block])", body("swapz_gc_compact_one"))

    def test_discard_validates_entire_range_before_mutating(self):
        discard = body("swapz_discard")
        self.assertLess(discard.index("while (check_remaining)"),
                        discard.index("while (remaining)"))
        self.assertLess(discard.index("if (m->generation =="),
                        discard.index("swapz_discard_page(&ctx->authority"))
        self.assertIn("ctx->discard_epoch[start]", discard)
        self.assertIn("ctx->discard_count[start]", discard)
        self.assertIn("ctx->live_records[start]", discard)
        self.assertLess(discard.index("++ctx->discard_count[start]"),
                        discard.index("swapz_discard_page(&ctx->authority"))

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
        self.assertIn("write_fault_nth=%u write_fault_calls=%llu "
                      "write_fault_injected=%llu", status)
        self.assertIn("ctx->engine.bulk_enabled, ctx->write_fault_nth", status)

    def test_bounded_lower_run_aggregation_preserves_commit_gate(self):
        engine = (ROOT / "src/kernel/engine.c").read_text()
        authority = (ROOT / "src/kernel/authority.c").read_text()
        writer = source_body("swapz_engine_write_window_batched_read_cap", engine)
        flush = source_body("swapz_bulk_flush", engine)
        pause = source_body("swapz_batch_pause", authority)
        resume = source_body("swapz_batch_resume", authority)
        self.assertIn("SWAPZ_BULK_BLOCKS 64U",
                      (ROOT / "src/kernel/engine.h").read_text())
        self.assertIn("swapz_engine_write_window_batched_read_cap(&ctx->engine", DM)
        self.assertIn("ctx->engine.io.write_run = swapz_lower_write_run", DM)
        self.assertIn("swapz_batch_pause(e->authority, tx)", writer)
        self.assertIn("swapz_bulk_flush(e, run_start", writer)
        planner = source_body("swapz_engine_plan_bounded_policy", engine)
        self.assertIn("swapz_u32 alignment_cursor", engine)
        self.assertIn("candidate_bytes != costs[position]", planner)
        self.assertIn("hole == best_hole && blocks > chosen_class", planner)
        self.assertIn("e->authority->next_block", writer)
        self.assertIn("swapz_batch_resume(e->authority, tx)", flush)
        self.assertLess(flush.index("e->io.write_run"),
                        flush.index("swapz_batch_resume(e->authority, tx)"))
        self.assertLess(flush.index("swapz_batch_resume(e->authority, tx)"),
                        flush.index("swapz_finish(e->authority, tx"))
        self.assertIn("swapz_bulk_abort(e, count, 0)", flush)
        self.assertIn("a->batch_pending++", pause)
        self.assertIn("a->batch_replaying = 1", resume)
        self.assertIn("ctx->engine.bulk_writes", body("swapz_status"))
        self.assertIn("bulk_mode=%u", body("swapz_status"))
        ctor = body("swapz_ctr")
        self.assertIn("lower_bulk = 1", ctor)
        self.assertIn("lower_bulk > 2U", ctor)
        self.assertIn("ctx->engine.bulk_enabled = lower_bulk", ctor)
        self.assertIn("e->bulk_enabled == 1", writer)
        self.assertIn("aligned != run_start + run_blocks", writer)
        self.assertIn("swapz_stage_batch(e->authority", writer)
        self.assertIn("batch_hashes", authority)
        self.assertIn("batch_stage_allowed", authority)
        self.assertIn("a->batch_pending", source_body("swapz_gc_commit_rotation", authority))

    def test_mixed_raw_lower_run_preserves_authority_and_barriers(self):
        engine = (ROOT / "src/kernel/engine.c").read_text()
        writer = source_body("swapz_engine_write_window_batched_read_cap", engine)
        flush = source_body("swapz_bulk_flush", engine)
        accept = body("swapz_accept_write")
        complete = body("swapz_flush_window")
        process = body("swapz_process")
        self.assertIn("!ctx->engine.verify_after_write", accept)
        self.assertIn("ctx->engine.bulk_enabled", accept)
        self.assertIn("ctx->batch_count++", accept)
        self.assertIn(".raw = 1", accept)
        self.assertIn("ctx->batch[index].raw", body("swapz_order_window"))
        self.assertIn("e->bulk_raw[staged] = raw", writer)
        self.assertIn("swapz_finish_raw(e->authority, tx", flush)
        self.assertLess(flush.index("e->io.write_run"),
                        flush.index("swapz_finish_raw(e->authority, tx"))
        self.assertIn("ctx->planned[index].raw", complete)
        self.assertIn("bulk_mixed_io=%u", body("swapz_status"))
        self.assertIn("bulk_raw_only_io=%u", body("swapz_status"))
        self.assertIn("bulk_raw_entries=%u", body("swapz_status"))
        self.assertLess(complete.index("swapz_issue_flush(ctx)"),
                        complete.index("swapz_complete(bio, 0)"))
        self.assertIn("swapz_flush_window(ctx)", process)
        self.assertIn("REQ_PREFLUSH", process)
        self.assertIn("swapz_raw_write(ctx, bio, logical)", accept)

    def test_gc_refuses_any_unpublished_lower_group(self):
        compact = body("swapz_gc_compact_one")
        self.assertIn("a->batch_pending", compact)
        self.assertIn("a->batch_replaying", compact)
        self.assertLess(compact.index("a->batch_pending"),
                        compact.index("swapz_gc_choose_victim(ctx, &victim)"))
        drain = body("swapz_drain")
        self.assertIn("ctx->authority.batch_pending", drain)
        self.assertIn("ctx->authority.in_flight", drain)

    def test_gc_large_record_preflight_avoids_pointless_full_relocation(self):
        choose = body("swapz_gc_choose_victim")
        cost = (ROOT / "src/kernel/gc-cost.h").read_text()
        ctr = body("swapz_ctr")
        self.assertIn("SWAPZ_GC_UNSHAREABLE_MIN_LENGTH", cost)
        self.assertIn("swapz_gc_min_live_blocks", cost)
        self.assertIn("swapz_gc_candidate_can_free_block", cost)
        self.assertIn("ctx->gc_min_live_blocks[segment] +=", choose)
        self.assertIn("swapz_gc_candidate_can_free_block", choose)
        self.assertIn("ctx->gc_no_headroom_skips++", choose)
        self.assertIn("gc_no_headroom_skips=%llu", body("swapz_status"))
        self.assertIn("ctx->gc_min_live_blocks = kvcalloc", ctr)

    def test_gc_io_aware_default_retains_old_control_policies(self):
        choose = body("swapz_gc_choose_victim")
        ctor = body("swapz_ctr")
        self.assertIn("gc_policy = 2", ctor)
        self.assertIn("gc_policy > 2U", ctor)
        self.assertIn("swapz_gc_estimated_io_cost(m)", choose)
        self.assertIn("ctx->gc_io_scores[segment] += io_cost", choose)
        self.assertIn("case 0:", choose)
        self.assertIn("case 1:", choose)
        self.assertIn("score = ctx->gc_io_scores[segment]", choose)
        self.assertIn("gc_selected_io_estimate", body("swapz_status"))

    def test_gc_does_not_consume_or_complete_upper_bios(self):
        gc = body("swapz_gc_compact_one")
        self.assertNotIn("swapz_complete(", gc)
        self.assertIn("ctx->gc_read_bytes", gc)
        self.assertIn("ctx->gc_write_bytes", gc)
        self.assertIn("a->gc_allocation = 0", gc)

    def test_worker_yields_after_finite_window_and_preserves_fifo(self):
        # Assert the finite-quantum semantics, not one obsolete decrement idiom.
        worker = body("swapz_worker")
        self.assertIn("SWAPZ_WORK_QUANTUM_BIOS", worker)
        self.assertIn("while (remaining && !list_empty(&local))", worker)
        self.assertIn("remaining--", worker)
        self.assertIn("list_splice_init(&local, &ctx->incoming)", worker)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", worker)
        self.assertIn("cond_resched()", worker)
        self.assertLess(worker.index("remaining--"),
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
        gc = body("swapz_gc_compact_one")
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
        self.assertIn("ctx->window_bins[0]++", body("swapz_flush_window"))
        self.assertIn("ctx->window_bins[5]++", body("swapz_flush_window"))
        self.assertIn("gc_read_reqs=%llu gc_write_reqs=%llu", DM)
        self.assertIn("ctx->gc_read_reqs += ctx->physical_read_reqs - before_read_reqs",
                      body("swapz_gc_compact_one"))
        self.assertIn("flush_delayed_work(&ctx->worker)", drain)
        self.assertLess(worker.index("swapz_flush_window(ctx)"),
                        worker.index("list_splice_init(&local, &ctx->incoming)"))

    def test_gc_uses_committed_actual_payload_lengths(self):
        authority = (ROOT / "src/kernel/authority.c").read_text()
        self.assertIn("payload_lengths[index] = decoded.payload_length", authority)
        self.assertIn(".payload_length = payload_lengths[index]", authority)
        self.assertIn(".payload_length = SWAPZ_BLOCK_BYTES", authority)
        self.assertIn("peeked->payload_length != current->payload_length", authority)
        self.assertIn("ctx->gc_cost_policy", body("swapz_gc_choose_victim"))
        self.assertIn("gc_selected_live_bytes", body("swapz_gc_choose_victim"))
        self.assertNotIn("coalesce", body("swapz_status"))

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
        self.assertIn("remaining--", worker)
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
        self.assertIn("ctx->retained_tail_target = tail", sample)
        self.assertNotIn("ctx->single_pack_deferred && !ctx->retained_tail_target", sample)
        self.assertIn("swapz_sample_pack_tail_locked(ctx, &local)", worker)
        self.assertIn("swapz_window_shrink_burst_target(", worker)
        self.assertIn("!ctx->retained_chain_completed", worker)
        close_ready = body("swapz_retained_pack_close_ready")
        self.assertIn("ctx->batch_count", close_ready)
        self.assertIn("ctx->retained_chain_completed", close_ready)
        self.assertIn("ctx->retained_window_read_bypasses", close_ready)
        self.assertIn("ctx->retained_wave_interrupted", close_ready)
        self.assertIn("ctx->batch_count < 4U", close_ready)
        self.assertIn("!ctx->retained_tail_target", close_ready)
        self.assertIn("swapz_window_burst_close_ready(", close_ready)
        self.assertIn("retained_burst_target=%u", status)

    def test_alpha18_worker_phase_wall_times_are_cumulative_not_cpu(self):
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        lower = body("swapz_lower")
        accept = body("swapz_accept_write")
        read = body("swapz_read")
        flush = body("swapz_flush_window")
        producer = body("swapz_preparation_worker")
        worker = body("swapz_worker")
        status = body("swapz_status")
        engine_write = source_body("swapz_engine_write_window_batched_read_cap",
                                   ENGINE)
        engine_bulk_flush = source_body("swapz_bulk_flush", ENGINE)
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
        self.assertIn("e->plan_wall_ns +=", engine_write)
        self.assertIn("e->pack_wall_ns +=", engine_write)
        self.assertIn("e->publish_wall_ns +=", engine_bulk_flush)
        self.assertIn("ctx->gc_wall_ns +=", flush)
        self.assertNotIn("#include <linux/sched/cputime.h>", DM)
        self.assertNotIn("task_cputime_adjusted(current", DM)
        self.assertNotIn("current->se.sum_exec_runtime", DM)
        self.assertEqual(producer.count("return;"),
                         producer.count("swapz_account_worker_wall("))
        self.assertEqual(worker.count("return;"),
                         worker.count("swapz_account_worker_wall("))
        for key in ("lz4_wall_ns", "decode_wall_ns", "read_copy_wall_ns",
                    "read_copy_bytes", "read_engine_nonio_wall_ns",
                    "window_sort_wall_ns", "window_commit_wall_ns",
                    "window_commit_nonio_wall_ns", "engine_plan_wall_ns",
                    "engine_pack_wall_ns", "engine_publish_wall_ns",
                    "lower_read_wall_ns", "lower_write_wall_ns",
                    "ordered_worker_wall_ns", "gc_wall_ns",
                    "ordered_crc_wall_ns",
                    "dry_pack_close_events", "dry_pack_followup_events",
                    "dry_pack_followup_sum_ns",
                    "dry_pack_followup_le10us", "dry_pack_followup_11_50us",
                    "dry_pack_followup_51_200us",
                    "dry_pack_followup_gt200us"):
            self.assertIn(key + "=%llu", status)
            self.assertIn("ctx->" + key, status)
        self.assertIn("prep_crc_wall_ns=%llu", status)
        self.assertIn("ctx->preparation_crc_wall_ns", status)
        self.assertIn("prep_worker_wall_ns=%llu", status)
        self.assertIn("ctx->preparation_worker_wall_ns", status)
        self.assertIn("engine_prehashed_records=%u", status)
        self.assertIn("ctx->engine.prehashed_records", status)
        self.assertIn("swapz_engine_write_window_batched_read_cap(", flush)
        codec = (ROOT / "src/kernel/codec.c").read_text()
        authority = (ROOT / "src/kernel/authority.c").read_text()
        self.assertIn("swapz_append_prehashed(", codec)
        self.assertIn("swapz_lookup_validated(", codec)
        self.assertIn("swapz_lookup_validated(image, bytes_total, index",
                      authority)
        self.assertIn("swapz_crc32c_bytes(prepared->bytes", producer)
        self.assertIn("payload_crc32c_valid", accept)
        self.assertIn("swapz_note_dry_pack_close(ctx)", worker)
        self.assertIn("swapz_note_dry_pack_followup_locked", DM)

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

    def test_alpha16_no_rearm_of_already_queued_retention_timer(self):
        policy = (ROOT / "src/kernel/window-policy.h").read_text()
        worker = body("swapz_worker")
        status = body("swapz_status")
        self.assertIn("swapz_retention_timer_needs_arm(", policy)
        self.assertIn("swapz_window_timer_enabled(retain_ms) && !queued", policy)
        self.assertIn("hrtimer_is_queued(&ctx->retention_timer)", worker)
        self.assertIn("swapz_retention_timer_needs_arm(ctx->retain_ms", worker)
        self.assertLess(worker.index("hrtimer_is_queued(&ctx->retention_timer)"),
                        worker.index("hrtimer_start(&ctx->retention_timer"))
        self.assertIn("ctx->retain_timer_arms++", worker)
        self.assertIn("ctx->retain_timer_arm_skips++", worker)
        self.assertIn("ctx->window_first_ns +", worker)
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
        self.assertIn("close_pack_ready=%llu packed_early_commits=%llu", status)
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

    def test_alpha12_retention_has_absolute_timer_and_drain(self):
        expiry = body("swapz_retention_expired")
        wake = body("swapz_retention_wake")
        process = body("swapz_process")
        worker = body("swapz_worker")
        flush = body("swapz_flush_window")
        mapping = body("swapz_map")
        drain = body("swapz_drain")
        ctr = body("swapz_ctr")
        status = body("swapz_status")
        self.assertIn("ctx->window_first_ns", expiry)
        self.assertIn("swapz_window_retention_expired", expiry)
        self.assertIn("ktime_get_ns(), ctx->retain_ms", expiry)
        self.assertNotIn("nsecs_to_jiffies64", DM)
        self.assertNotIn("swapz_retention_delay", DM)
        self.assertIn("hrtimer_start(&ctx->retention_timer", worker)
        self.assertIn("ctx->window_first_ns +", worker)
        self.assertIn("ctx->retain_ms * 1000000ULL", worker)
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
                      "ctx->authority.in_flight", "ctx->authority.batch_pending",
                      "REQ_PREFLUSH | REQ_FUA"):
            self.assertIn(fence, independent)
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

    def test_gc_status_is_truthful(self):
        self.assertIn("mode=alpha-live-gc", body("swapz_status"))
        self.assertNotIn("mode=alpha-no-gc", body("swapz_status"))
        self.assertIn("experimental live GC", DM)

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

        self.assertIn("module_param_named(async_prepare", DM)
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
        self.assertNotIn("atomic_read(&ctx->ordered_worker_busy)", mapper)
        self.assertNotIn("ctx->batch_count", mapper)
        self.assertNotIn("ctx->incoming.next != &entry->list", mapper)
        self.assertNotIn("ctx->preparation_incoming.next != &entry->preparation_list",
                         mapper)
        self.assertNotIn("list_is_singular(&ctx->preparation_incoming)", mapper)
        self.assertLess(mapper.index("list_add_tail(&entry->list"),
                        mapper.index("queue_work(ctx->preparation_workqueue"))
        self.assertIn("queue_work(ctx->preparation_workqueue", lower)
        self.assertIn("!list_empty(&ctx->preparation_incoming)", lower)
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
        self.assertIn("!list_is_singular(&ctx->preparation_incoming)", ordered)
        self.assertIn("ctx->preparation_wave_kicks++", ordered)
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
        self.assertIn("async_prepare=%u prep_lower_write_overlap_starts=%llu",
                      status)
        self.assertIn("insmod \"$MODULE\" \"async_prepare=$ASYNC_PREPARE\"",
                      benchmark)
        self.assertIn("--async-prepare", benchmark)
        self.assertIn("RATE_MODE != unpaced", benchmark)
        # The mandatory run now has exactly TWO delay-modeled owned-RAM
        # environments, not the historical bandwidth/uncapped controls.
        self.assertIn("LOWER_MBPS=0", benchmark)
        self.assertIn("10:1000000|80:150000", benchmark)
        self.assertIn('echo "$LOWER_MBPS" > "$config/mbps"', benchmark)
        self.assertIn('echo "$COMPLETION_NSEC" > "$config/completion_nsec"', benchmark)
        self.assertIn('echo "$IRQMODE" > "$config/irqmode"', benchmark)
        self.assertIn("PASS_RAM_MODEL_LOWER_MBPS=", benchmark)
        self.assertIn("LOWER_MBPS=$LOWER_MBPS", benchmark)

    def test_owned_nullblk_smoke_qualifies_retained_synthetic_faults(self):
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        # These are deliberately pre-submission injections on the already
        # authenticated RAM null_blk lower, not claims about torn/device faults.
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
        self.assertIn("START_LOADED_SUSPEND_DRAIN", deploy)
        self.assertIn('--table "0 32768 swapz $LOWER 0 64 1 2 0 1 0 4"', deploy)
        self.assertIn("timer_arms > lifecycle_windows", deploy)
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
        self.assertIn("--gc-stress", oracle)
        self.assertIn("GC_PAGES = 4096", oracle)
        self.assertIn("page % 256U", oracle)
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
