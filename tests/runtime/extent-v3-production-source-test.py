#!/usr/bin/env python3
"""Fail-closed source qualifications for *real* swapz3 vs codec-only smoke.

This is not a replacement for live kernel BIO/GC tests. It prevents CI and
future privileged harnesses from accidentally selecting the old swapz module
or the standalone memory-only V3 smoke instead of the real DM target.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
DM = (ROOT / "kernel/extent-v3/dm-target.c").read_text()
AUTH = (ROOT / "kernel/extent-v3/authority.c").read_text()
MK = (ROOT / "kernel/extent-v3/Makefile").read_text()
GOALS = (ROOT / "V3_GOALS.md").read_text()


def body(symbol: str) -> str:
    match = re.search(r"static\s+(?:int|void)\s+" + re.escape(symbol) +
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
        self.assertIn("3.0.0-alpha.7", GOALS)

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

    def test_synthetic_anon_fixture_is_deterministic_and_size_exact(self):
        import importlib.util
        path = ROOT / "tests/runtime/anon-page-fixture.py"
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
