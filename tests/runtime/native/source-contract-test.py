#!/usr/bin/env python3
"""Fail-closed source qualifications for *real* swapz3 vs codec-only smoke.

This is not a replacement for live kernel BIO/GC tests. It prevents CI and
future privileged harnesses from accidentally selecting the old swapz module
or the standalone memory-only V3 smoke instead of the real DM target.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]
DM = (ROOT / "kernel/extent-v3/dm-target.c").read_text()
AUTH = (ROOT / "kernel/extent-v3/authority.c").read_text()
MK = (ROOT / "kernel/extent-v3/Makefile").read_text()
README = (ROOT / "README.md").read_text()


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


class V3ProductionSourceQualification(unittest.TestCase):
    def test_separate_target_and_3_0_alpha_version(self):
        self.assertRegex(DM, r'\.name\s*=\s*"swapz3"')
        self.assertRegex(DM, r'MODULE_ALIAS\("dm-swapz3"\)')
        version = (ROOT / "kernel/extent-v3/VERSION").read_text().strip()
        self.assertRegex(version, r"^3\.0\.0-alpha\.[0-9]+$")
        self.assertIn(f'SV3_ALPHA_VERSION "{version}"', DM)
        self.assertIn("obj-m += dm-swapz.o", MK)
        self.assertIn("SV3_BUILD_SMOKE", MK)
        self.assertIn(f"revision: **{version}", README)

    def test_lz4_foreground_size_histogram_is_attempt_side_only(self):
        accept = body("sv3_accept_write")
        status = body("sv3_status")
        self.assertIn("length = LZ4_compress_fast(", accept)
        self.assertIn("ctx->lz4_attempts++", accept)
        self.assertIn("ctx->lz4_size_bins[5]++", accept)
        self.assertIn("ctx->lz4_accepted_bytes += length", accept)
        for threshold in ("256", "1024", "2048", "3072"):
            self.assertIn(f"length <= {threshold}", accept)
        self.assertLess(accept.index("length = LZ4_compress_fast("),
                        accept.index("ctx->lz4_attempts++"))
        self.assertLess(accept.index("ctx->lz4_size_bins[5]++"),
                        accept.index("if (length <= 0 && ctx->engine.bulk_enabled"))
        self.assertIn("lz4_attempts=%llu lz4_accepted_bytes=%llu", status)
        self.assertIn("lz4_size_3073_3568=%llu lz4_raw_fallback=%llu", status)
        self.assertIn("ctx->lz4_size_bins[5]", status)
        self.assertNotIn("LZ4_compress_fast(", body("sv3_gc_compact_one"))

    def test_exact_zero_write_elides_lower_io_without_losing_ordering(self):
        accept = body("sv3_accept_write")
        read = body("sv3_read")
        status = body("sv3_status")
        self.assertIn("length > 0 && length <= 64", accept)
        self.assertIn("sv3_page_is_zero(ctx->input_page)", accept)
        self.assertIn("sv3_flush_window(ctx)", accept)
        self.assertIn("sv3_discard_page(&ctx->authority, logical)", accept)
        self.assertIn("ctx->logical_write_bytes += SV3_BLOCK_BYTES", accept)
        self.assertIn("ctx->zero_elided_pages++", accept)
        self.assertIn("sv3_complete(bio, error)", accept)
        self.assertIn("sv3_issue_flush(ctx)", accept)
        self.assertLess(accept.index("sv3_flush_window(ctx);",
                                    accept.index("sv3_page_is_zero")),
                        accept.index("sv3_discard_page(&ctx->authority"))
        self.assertIn("if (!map->valid)", read)
        self.assertIn("memset(ctx->read_page, 0, SV3_BLOCK_BYTES)", read)
        self.assertIn("zero_elided=%llu", status)
        # The predicate itself is exercised by an actual-C native test.
        engine = (ROOT / "kernel/extent-v3/engine.c").read_text()
        self.assertIn("int sv3_page_is_zero(", engine)

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

    def test_identical_off_v3_replay_contract(self):
        # Rootless regular files exercise the immutable plan and full-image
        # oracle. They do NOT claim a loaded V3 module test.
        import subprocess
        import sys
        script = ROOT / "tests/runtime/benchmark/io-replay-test.py"
        result = subprocess.run([sys.executable, str(script)],
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0,
                         result.stdout + "\\n" + result.stderr)
        self.assertIn("OK", result.stderr)

    def test_alpha_rejects_all_physical_devices(self):
        ctr = body("sv3_ctr")
        self.assertIn('disk_name, "nullb", 5', ctr)
        self.assertIn('swapz3 alpha accepts null_blk backing only', ctr)
        self.assertIn("goto fail;", ctr)

    def test_real_v3_not_memory_smoke(self):
        for snippet in ("dm_register_target(&sv3_target)",
                        "LZ4_compress_fast(", "LZ4_decompress_safe(",
                        "dm_io(&req,", "DM_IO_VMA", "SV3_SECTORS"):
            self.assertIn(snippet, DM)

    def test_allocation_has_gc_reserve_and_fail_closed_reuse(self):
        self.assertIn("sv3_gc_compact_one(ctx)", body("sv3_flush_window"))
        self.assertIn("sv3_gc_compact_one(ctx)", body("sv3_raw_write"))
        self.assertIn("sv3_gc_choose_victim(ctx,", body("sv3_gc_compact_one"))
        self.assertIn("if (a->live_records[start + off])", AUTH)
        self.assertIn("if (map->start_block / SV3_SEGMENT_BLOCKS == segment)", AUTH)
        self.assertIn("cost = sv3_gc_live_byte_cost(m)", DM)
        self.assertIn("ctx->gc_scores[segment] += cost", DM)
        self.assertIn("sv3_gc_prefer(score, count, best, best_count)", DM)
        self.assertIn("sv3_engine_read_page(&ctx->engine", body("sv3_gc_compact_one"))
        self.assertIn("sv3_gc_flush(ctx)", body("sv3_gc_compact_one"))
        self.assertIn("sv3_finish_raw(&ctx->authority", body("sv3_gc_move_raw"))
        self.assertIn("if (a->live_records[block])", body("sv3_gc_compact_one"))

    def test_discard_validates_entire_range_before_mutating(self):
        discard = body("sv3_discard")
        self.assertLess(discard.index("while (check_remaining)"),
                        discard.index("while (remaining)"))
        self.assertLess(discard.index("if (m->generation =="),
                        discard.index("sv3_discard_page(&ctx->authority"))
        self.assertIn("ctx->discard_epoch[start]", discard)
        self.assertIn("ctx->discard_count[start]", discard)
        self.assertIn("ctx->live_records[start]", discard)
        self.assertLess(discard.index("++ctx->discard_count[start]"),
                        discard.index("sv3_discard_page(&ctx->authority"))

    def test_fua_acknowledged_only_after_flush(self):
        flush = body("sv3_flush_window")
        self.assertLess(flush.index("sv3_issue_flush(ctx)"),
                        flush.index("sv3_complete(bio, 0)"))
        self.assertIn("if (error && needs_fua)", flush)
        self.assertNotIn("DM_MAPIO_KILL; /* Until FUA", body("sv3_map"))

    def test_valid_empty_flush_protocol_and_failure_accounting(self):
        # REQ_OP_FLUSH as a BIO is rejected in Linux blk-core itself.
        # The supported upper-bio encoding is zero sector WRITE|PREFLUSH.
        admitted = body("sv3_map")
        process = body("sv3_process")
        lower = body("sv3_issue_flush")
        raw = body("sv3_accept_write")
        drain = body("sv3_drain")
        self.assertIn("REQ_OP_WRITE && !count", admitted)
        self.assertIn("bio->bi_opf & REQ_PREFLUSH", admitted)
        self.assertNotIn("bio_op(bio) != REQ_OP_FLUSH", admitted)
        self.assertNotIn("case REQ_OP_FLUSH:", process)
        self.assertIn("if (bio->bi_opf & REQ_PREFLUSH)", process)
        self.assertIn("sv3_issue_flush(ctx)", process)
        self.assertIn("sv3_issue_flush(ctx)", raw)
        self.assertIn("sv3_issue_flush(ctx)", drain)
        self.assertIn("sv3_flush_accounted(&ctx->flush_meter", lower)
        self.assertIn("sv3_fail(ctx, error)", lower)
        self.assertIn("flush_calls=%llu flush_ok=%llu flush_err=%llu", DM)
        self.assertIn("flush_injected=%llu flush_fault_nth=%u", DM)
        self.assertIn("flush_fail_nth > 64U", body("sv3_ctr"))
        self.assertIn("flush_meter.fail_nth = flush_fail_nth", body("sv3_ctr"))

    def test_owned_nullblk_lower_write_fault_is_pre_submission_and_counted(self):
        # This tests fail-closed propagation through the actual dm_io adapter.
        # It cannot model a device-originated partial/torn write.
        ctor = body("sv3_ctr")
        lower = body("sv3_lower")
        status = body("sv3_status")
        self.assertIn('disk_name, "nullb", 5', ctor)
        self.assertIn("argc < 1 || argc > 10", ctor)
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
        self.assertIn("sv3_lower(ctx, REQ_OP_WRITE", body("sv3_lower_write"))
        self.assertIn("sv3_lower(ctx, REQ_OP_WRITE", body("sv3_lower_write_run"))
        self.assertIn("write_fault_nth=%u write_fault_calls=%llu "
                      "write_fault_injected=%llu", status)
        self.assertIn("ctx->engine.bulk_enabled, ctx->write_fault_nth", status)

    def test_bounded_lower_run_aggregation_preserves_commit_gate(self):
        engine = (ROOT / "kernel/extent-v3/engine.c").read_text()
        authority = (ROOT / "kernel/extent-v3/authority.c").read_text()
        writer = source_body("sv3_engine_write_window_batched", engine)
        flush = source_body("sv3_bulk_flush", engine)
        pause = source_body("sv3_batch_pause", authority)
        resume = source_body("sv3_batch_resume", authority)
        self.assertIn("SV3_BULK_BLOCKS 64U",
                      (ROOT / "kernel/extent-v3/engine.h").read_text())
        self.assertIn("sv3_engine_write_window_batched(&ctx->engine", DM)
        self.assertIn("ctx->engine.io.write_run = sv3_lower_write_run", DM)
        self.assertIn("sv3_batch_pause(e->authority, tx)", writer)
        self.assertIn("sv3_bulk_flush(e, run_start", writer)
        self.assertIn("sv3_batch_resume(e->authority, tx)", flush)
        self.assertLess(flush.index("e->io.write_run"),
                        flush.index("sv3_batch_resume(e->authority, tx)"))
        self.assertLess(flush.index("sv3_batch_resume(e->authority, tx)"),
                        flush.index("sv3_finish(e->authority, tx"))
        self.assertIn("sv3_bulk_abort(e, count, 0)", flush)
        self.assertIn("a->batch_pending++", pause)
        self.assertIn("a->batch_replaying = 1", resume)
        self.assertIn("ctx->engine.bulk_writes", body("sv3_status"))
        self.assertIn("bulk_mode=%u", body("sv3_status"))
        ctor = body("sv3_ctr")
        self.assertIn("lower_bulk = 1", ctor)
        self.assertIn("lower_bulk > 2U", ctor)
        self.assertIn("ctx->engine.bulk_enabled = lower_bulk", ctor)
        self.assertIn("e->bulk_enabled == 1", writer)
        self.assertIn("aligned != run_start + run_blocks", writer)
        self.assertIn("sv3_stage_batch(e->authority", writer)
        self.assertIn("batch_hashes", authority)
        self.assertIn("batch_stage_allowed", authority)
        self.assertIn("a->batch_pending", source_body("sv3_gc_commit_rotation", authority))

    def test_mixed_raw_lower_run_preserves_authority_and_barriers(self):
        engine = (ROOT / "kernel/extent-v3/engine.c").read_text()
        writer = source_body("sv3_engine_write_window_batched", engine)
        flush = source_body("sv3_bulk_flush", engine)
        accept = body("sv3_accept_write")
        complete = body("sv3_flush_window")
        process = body("sv3_process")
        self.assertIn("!ctx->engine.verify_after_write", accept)
        self.assertIn("ctx->engine.bulk_enabled", accept)
        self.assertIn("ctx->batch_count++", accept)
        self.assertIn(".raw = 1", accept)
        self.assertIn("ctx->batch[index].raw", body("sv3_order_window"))
        self.assertIn("e->bulk_raw[staged] = raw", writer)
        self.assertIn("sv3_finish_raw(e->authority, tx", flush)
        self.assertLess(flush.index("e->io.write_run"),
                        flush.index("sv3_finish_raw(e->authority, tx"))
        self.assertIn("ctx->planned[index].raw", complete)
        self.assertIn("bulk_mixed_io=%u", body("sv3_status"))
        self.assertIn("bulk_raw_only_io=%u", body("sv3_status"))
        self.assertIn("bulk_raw_entries=%u", body("sv3_status"))
        self.assertLess(complete.index("sv3_issue_flush(ctx)"),
                        complete.index("sv3_complete(bio, 0)"))
        self.assertIn("sv3_flush_window(ctx)", process)
        self.assertIn("REQ_PREFLUSH", process)
        self.assertIn("sv3_raw_write(ctx, bio, logical)", accept)

    def test_gc_refuses_any_unpublished_lower_group(self):
        compact = body("sv3_gc_compact_one")
        self.assertIn("a->batch_pending", compact)
        self.assertIn("a->batch_replaying", compact)
        self.assertLess(compact.index("a->batch_pending"),
                        compact.index("sv3_gc_choose_victim(ctx, &victim)"))
        drain = body("sv3_drain")
        self.assertIn("ctx->authority.batch_pending", drain)
        self.assertIn("ctx->authority.in_flight", drain)

    def test_gc_large_record_preflight_avoids_pointless_full_relocation(self):
        choose = body("sv3_gc_choose_victim")
        cost = (ROOT / "kernel/extent-v3/gc-cost.h").read_text()
        ctr = body("sv3_ctr")
        self.assertIn("SV3_GC_UNSHAREABLE_MIN_LENGTH", cost)
        self.assertIn("sv3_gc_min_live_blocks", cost)
        self.assertIn("sv3_gc_candidate_can_free_block", cost)
        self.assertIn("ctx->gc_min_live_blocks[segment] +=", choose)
        self.assertIn("sv3_gc_candidate_can_free_block", choose)
        self.assertIn("ctx->gc_no_headroom_skips++", choose)
        self.assertIn("gc_no_headroom_skips=%llu", body("sv3_status"))
        self.assertIn("ctx->gc_min_live_blocks = kvcalloc", ctr)

    def test_gc_io_aware_default_retains_old_control_policies(self):
        choose = body("sv3_gc_choose_victim")
        ctor = body("sv3_ctr")
        self.assertIn("gc_policy = 2", ctor)
        self.assertIn("gc_policy > 2U", ctor)
        self.assertIn("sv3_gc_estimated_io_cost(m)", choose)
        self.assertIn("ctx->gc_io_scores[segment] += io_cost", choose)
        self.assertIn("case 0:", choose)
        self.assertIn("case 1:", choose)
        self.assertIn("score = ctx->gc_io_scores[segment]", choose)
        self.assertIn("gc_selected_io_estimate", body("sv3_status"))

    def test_gc_does_not_consume_or_complete_upper_bios(self):
        gc = body("sv3_gc_compact_one")
        self.assertNotIn("sv3_complete(", gc)
        self.assertIn("ctx->gc_read_bytes", gc)
        self.assertIn("ctx->gc_write_bytes", gc)
        self.assertIn("a->gc_allocation = 0", gc)

    def test_worker_yields_after_finite_window_and_preserves_fifo(self):
        worker = body("sv3_worker")
        self.assertIn("SV3_WORK_QUANTUM_BIOS", worker)
        self.assertIn("if (!--remaining)", worker)
        self.assertIn("list_splice_init(&local, &ctx->incoming)", worker)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", worker)
        self.assertIn("cond_resched()", worker)
        self.assertLess(worker.index("sv3_flush_window(ctx)"),
                        worker.index("list_splice_init(&local, &ctx->incoming)"))

    def test_shutdown_completes_all_accepted_queued_bios(self):
        worker = body("sv3_worker")
        drain = body("sv3_drain")
        self.assertIn("for (;;)", worker)
        self.assertIn("remaining = SV3_WORK_QUANTUM_BIOS", worker)
        self.assertIn("if (ctx->accepting)", worker)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", worker)
        self.assertIn("cond_resched();", worker)
        self.assertLess(worker.index("if (ctx->accepting)"),
                        worker.rindex("cond_resched();"))
        self.assertIn("drain_workqueue(ctx->workqueue)", drain)
        self.assertIn("V3 drain invariant: accepted BIOs remain", drain)
        self.assertIn("ctx->authority.batch_pending", drain)
        self.assertIn("ctx->authority.in_flight", drain)
        self.assertIn("sv3_fail(ctx, -EUCLEAN)", drain)

    def test_raw_crc_protection_and_gc_relocation(self):
        auth = (ROOT / "kernel/extent-v3/authority.c").read_text()
        auth_h = (ROOT / "kernel/extent-v3/authority.h").read_text()
        self.assertIn("raw_crc32c", auth_h)
        self.assertIn("sv3_verify_raw(", auth)
        self.assertIn("sv3_crc32c_bytes(raw_page, SV3_BLOCK_BYTES)", auth)
        self.assertIn("sv3_verify_raw(&ctx->authority, logical, ctx->read_page)",
                      body("sv3_read"))
        self.assertIn("sv3_verify_raw(&ctx->authority, logical, ctx->input_page)",
                      body("sv3_gc_move_raw"))

    def test_gc_explicitly_forbids_paused_open_and_victim(self):
        authority = (ROOT / "kernel/extent-v3/authority.c").read_text()
        gc = body("sv3_gc_compact_one")
        for name in ("gc_forbidden_open", "gc_forbidden_victim"):
            self.assertIn(name, authority)
            self.assertIn("a->" + name, gc)
        self.assertIn("segment == a->gc_forbidden_open", authority)
        self.assertIn("segment == a->gc_forbidden_victim", authority)
        self.assertIn("sv3_gc_begin_rotation(a, victim)", gc)
        self.assertIn("sv3_gc_commit_rotation(a, victim)", gc)
        self.assertIn("sv3_enable_segment_rotation(&ctx->authority", body("sv3_ctr"))
        self.assertIn("!ctx->segment_roles[segment]", body("sv3_gc_choose_victim"))
        self.assertIn("a->segment_foreground[dest] = 1", authority)
        self.assertIn("a->segment_foreground[victim] = 0", authority)

    def test_optional_write_verify_before_raw_publication(self):
        ctor = body("sv3_ctr")
        verifier = body("sv3_verify_raw_write")
        for name in ("sv3_gc_move_raw", "sv3_raw_write"):
            raw = body(name)
            self.assertLess(raw.index("sv3_verify_raw_write(ctx"),
                            raw.index("sv3_finish_raw(&ctx->authority"))
        self.assertIn("engine.verify_after_write = verify", ctor)
        self.assertIn("verify > 1U", ctor)
        self.assertIn("if (!ctx->engine.verify_after_write)", verifier)
        self.assertIn("return memcmp(", verifier)
        self.assertIn("-EBADMSG", verifier)

    def test_attempted_and_completed_lower_io_are_distinct(self):
        lower = body("sv3_lower")
        self.assertLess(lower.index("ctx->lower_write_submitted_reqs++"),
                        lower.index("error = dm_io(&req"))
        self.assertLess(lower.index("error = dm_io(&req"),
                        lower.index("ctx->physical_write_reqs++"))
        self.assertIn("one_page_windows", body("sv3_flush_window"))
        self.assertIn("worker_requeues", body("sv3_worker"))

    def test_online_batching_bounded_and_barrier_first(self):
        admitted = body("sv3_map")
        ctor = body("sv3_ctr")
        drain = body("sv3_drain")
        worker = body("sv3_worker")
        self.assertIn("SV3_MAX_COALESCE_MS", DM)
        self.assertIn("msecs_to_jiffies(ctx->coalesce_ms)", admitted)
        self.assertIn("REQ_PREFLUSH | REQ_FUA", admitted)
        self.assertIn("bio_op(bio) != REQ_OP_WRITE", admitted)
        self.assertIn("queue_delayed_work(ctx->workqueue", admitted)
        self.assertIn("mod_delayed_work(ctx->workqueue", admitted)
        self.assertIn("INIT_DELAYED_WORK(&ctx->worker", ctor)
        self.assertIn("coalesce > SV3_MAX_COALESCE_MS", ctor)
        self.assertIn("ctx->window_size_counts[count]++", body("sv3_flush_window"))
        self.assertIn("ctx->window_bins[0]++", body("sv3_flush_window"))
        self.assertIn("ctx->window_bins[5]++", body("sv3_flush_window"))
        self.assertIn("gc_read_reqs=%llu gc_write_reqs=%llu", DM)
        self.assertIn("ctx->gc_read_reqs += ctx->physical_read_reqs - before_read_reqs",
                      body("sv3_gc_compact_one"))
        self.assertIn("flush_delayed_work(&ctx->worker)", drain)
        self.assertLess(worker.index("sv3_flush_window(ctx)"),
                        worker.index("list_splice_init(&local, &ctx->incoming)"))

    def test_gc_uses_committed_actual_payload_lengths(self):
        authority = (ROOT / "kernel/extent-v3/authority.c").read_text()
        self.assertIn("payload_lengths[index] = decoded.payload_length", authority)
        self.assertIn(".payload_length = payload_lengths[index]", authority)
        self.assertIn(".payload_length = SV3_BLOCK_BYTES", authority)
        self.assertIn("decoded->payload_length != current->payload_length", authority)
        self.assertIn("ctx->gc_cost_policy", body("sv3_gc_choose_victim"))
        self.assertIn("gc_selected_live_bytes", body("sv3_gc_choose_victim"))
        self.assertIn("gc_cost_policy, ctx->coalesce_ms", body("sv3_status"))

    def test_worker_close_reasons_cover_dependencies_and_control(self):
        flush = body("sv3_flush_window")
        write = body("sv3_accept_write")
        process = body("sv3_process")
        worker = body("sv3_worker")
        status = body("sv3_status")
        self.assertIn("ctx->window_close_reasons[ctx->next_window_close]++", flush)
        self.assertIn("ctx->next_window_close = SV3_CLOSE_UNKNOWN", flush)
        self.assertLess(flush.index("if (!count)"),
                        flush.index("ctx->window_close_reasons[ctx->next_window_close]++"))
        self.assertIn("ctx->window_gc_pressure++", flush)
        for cause in ("FULL", "DUPLICATE", "ZERO", "FUA", "RAW"):
            self.assertIn("SV3_CLOSE_" + cause, write)
        for cause in ("PREFLUSH", "READ_CONFLICT", "READ_UNRELATED", "DISCARD"):
            self.assertIn("SV3_CLOSE_" + cause, process)
        for cause in ("QUANTUM", "IDLE", "SHUTDOWN"):
            self.assertIn("SV3_CLOSE_" + cause, worker)
        for status_key in ("close_unknown", "close_full", "close_duplicate",
                           "close_zero", "close_fua", "close_raw",
                           "close_read_conflict", "close_read_unrelated",
                           "close_discard", "close_preflush", "close_quantum",
                           "close_idle", "close_shutdown", "close_other",
                           "window_gc_pressure"):
            self.assertIn(status_key + "=%llu", status)
        self.assertIn("sv3_flush_window(ctx)", process)
        self.assertIn("sv3_flush_window(ctx)", worker)

    def test_alpha10_open_age_counts_one_per_window_before_io(self):
        admitted = body("sv3_window_admit_clock")
        flush = body("sv3_flush_window")
        write = body("sv3_accept_write")
        status = body("sv3_status")
        self.assertIn("if (!ctx->batch_count)", admitted)
        self.assertIn("ctx->window_first_ns = ktime_get_ns()", admitted)
        self.assertEqual(write.count("sv3_window_admit_clock(ctx)"), 2)
        self.assertIn("end_ns = ktime_get_ns()", flush)
        self.assertIn("ctx->window_first_ns = 0", flush)
        self.assertLess(flush.index("ctx->window_age_sum_ns += open_age_ns"),
                        flush.index("sv3_order_window(ctx)"))
        for counter in ("window_age_le_100us++",
                        "window_age_101_1000us++", "window_age_gt_1000us++"):
            self.assertIn(counter, flush)
        for field in ("age_le100us", "age_101_1000us", "age_gt1000us",
                      "age_sum_ns", "age_max_ns"):
            self.assertIn(field + "=%llu", status)
        self.assertIn("#include <linux/ktime.h>", DM)

    def test_alpha12_retention_has_absolute_timer_and_drain(self):
        expiry = body("sv3_retention_expired")
        wake = body("sv3_retention_wake")
        process = body("sv3_process")
        worker = body("sv3_worker")
        mapping = body("sv3_map")
        drain = body("sv3_drain")
        ctr = body("sv3_ctr")
        status = body("sv3_status")
        self.assertIn("ctx->window_first_ns", expiry)
        self.assertIn("sv3_window_retention_expired", expiry)
        self.assertIn("ktime_get_ns(), ctx->retain_ms", expiry)
        self.assertNotIn("nsecs_to_jiffies64", DM)
        self.assertNotIn("sv3_retention_delay", DM)
        self.assertIn("hrtimer_start(&ctx->retention_timer", worker)
        self.assertIn("ctx->window_first_ns +", worker)
        self.assertIn("ctx->retain_ms * 1000000ULL", worker)
        self.assertIn("HRTIMER_MODE_ABS", worker)
        self.assertIn("spin_lock_irqsave(&ctx->queue_lock", wake)
        self.assertIn("if (ctx->accepting)", wake)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", wake)
        self.assertIn("return HRTIMER_NORESTART", wake)
        for forbidden in ("sv3_flush_window(", "sv3_complete(", "sv3_lower(",
                          "ctx->batch", "ctx->authority", "ctx->window_first_ns"):
            self.assertNotIn(forbidden, wake)
        self.assertIn("SV3_CLOSE_DEADLINE", process)
        self.assertIn("sv3_flush_window(ctx)", process)
        self.assertIn("ctx->retain_worker_passes++", worker)
        self.assertIn("ctx->retain_timer_arms++", worker)
        self.assertIn("SV3_CLOSE_SHUTDOWN", worker)
        self.assertIn("ctx->batch_count >= ctx->max_window", worker)
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", mapping)
        self.assertIn("WRITE_ONCE(ctx->accepting, false)", drain)
        self.assertLess(drain.index("WRITE_ONCE(ctx->accepting, false)"),
                        drain.index("hrtimer_cancel(&ctx->retention_timer)"))
        self.assertLess(drain.index("spin_unlock_irqrestore"),
                        drain.index("hrtimer_cancel(&ctx->retention_timer)"))
        self.assertLess(drain.index("hrtimer_cancel(&ctx->retention_timer)"),
                        drain.index("flush_delayed_work(&ctx->worker)"))
        freeing = body("sv3_free")
        self.assertLess(freeing.index("hrtimer_cancel(&ctx->retention_timer)"),
                        freeing.index("destroy_workqueue(ctx->workqueue)"))
        self.assertLess(ctr.index("hrtimer_setup(&ctx->retention_timer"),
                        ctr.index("error = dm_get_device("))
        self.assertIn("KERNEL_VERSION(6, 13, 0)", ctr)
        self.assertIn("hrtimer_init(&ctx->retention_timer", ctr)
        self.assertIn("flush_delayed_work(&ctx->worker)", drain)
        self.assertIn("drain_workqueue(ctx->workqueue)", drain)
        self.assertIn("argc > 10", ctr)
        self.assertIn("retain > SV3_MAX_RETAIN_MS", ctr)
        self.assertIn("ctx->retain_ms = retain", ctr)
        for field in ("retain_ms=%u", "retain_passes=%llu",
                      "retain_timer_arms=%llu", "close_deadline=%llu"):
            self.assertIn(field, status)
        self.assertIn("SV3_CLOSE_DEADLINE", DM)
        self.assertIn("if (bio->bi_opf & REQ_FUA)", body("sv3_accept_write"))

    def test_retained_writes_prepare_before_the_deadline(self):
        mapping = body("sv3_map")
        retained = mapping[mapping.index("} else if (ctx->retain_ms)"):
                           mapping.index("} else if (queue_delayed_work")]
        self.assertIn("mod_delayed_work(ctx->workqueue, &ctx->worker, 0)", retained)
        self.assertNotIn("queue_delayed_work", retained)
        self.assertNotIn("window_first_ns", mapping)
        self.assertNotIn("hrtimer_start", mapping)

    def test_retained_reads_require_independence_and_abort_on_failure(self):
        independent = body("sv3_read_is_independent")
        process = body("sv3_process")
        flush = body("sv3_flush_window")
        for fence in ("!READ_ONCE(ctx->accepting)", "ctx->failed",
                      "ctx->authority.in_flight", "ctx->authority.batch_pending",
                      "REQ_PREFLUSH | REQ_FUA"):
            self.assertIn(fence, independent)
        self.assertIn("sv3_window_read_independent(ctx->batch, ctx->batch_count",
                      independent)
        self.assertIn("logical, ctx->retain_ms, blocked", independent)
        bypass = process[process.index("if (op == REQ_OP_READ &&"):
                         process.index("if (op != REQ_OP_WRITE ||")]
        self.assertIn("sv3_read_is_independent(ctx, bio)", bypass)
        self.assertLess(bypass.index("error = sv3_read(ctx, bio)"),
                        bypass.index("sv3_fail(ctx, error)"))
        self.assertLess(bypass.index("sv3_fail(ctx, error)"),
                        bypass.index("sv3_flush_window(ctx)"))
        self.assertIn("if (!error && sv3_retention_expired(ctx))", bypass)
        self.assertLess(bypass.index("sv3_complete(bio, error)"),
                        bypass.index("if (!error && sv3_retention_expired(ctx))"))
        abort = flush[flush.index("if (ctx->failed)"):
                      flush.index("sv3_order_window(ctx)")]
        self.assertIn("sv3_complete(ctx->batch[index].bio, error)", abort)
        self.assertIn("goto accounted;", abort)
        self.assertNotIn("planned_to_batch", abort)
        self.assertNotIn("sv3_engine_write", abort)
        self.assertLess(flush.index("accounted:"), flush.index("ctx->batch_count = 0"))
        self.assertIn("retained_read_bypasses=%llu", body("sv3_status"))

    def test_gc_status_is_truthful(self):
        self.assertIn("mode=alpha-live-gc", body("sv3_status"))
        self.assertNotIn("mode=alpha-no-gc", body("sv3_status"))
        self.assertIn("experimental live GC", DM)

    def test_map_and_teardown_are_owned(self):
        admitted = body("sv3_map")
        drained = body("sv3_drain")
        self.assertIn("dm_per_bio_data(", admitted)
        self.assertIn("WQ_MEM_RECLAIM", body("sv3_ctr"))
        self.assertIn("drain_workqueue(ctx->workqueue)", drained)
        self.assertLess(drained.index("mod_delayed_work(ctx->workqueue"),
                        drained.index("flush_delayed_work(&ctx->worker)"))
        self.assertLess(drained.index("flush_delayed_work(&ctx->worker)"),
                        drained.index("drain_workqueue(ctx->workqueue)"))
        self.assertIn("cancel_delayed_work_sync(&ctx->worker)", body("sv3_free"))
        self.assertIn("destroy_workqueue(ctx->workqueue)", body("sv3_free"))
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
