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


class V3ProductionSourceQualification(unittest.TestCase):
    def test_separate_target_and_3_0_alpha_version(self):
        self.assertRegex(DM, r'\.name\s*=\s*"swapz3"')
        self.assertRegex(DM, r'MODULE_ALIAS\("dm-swapz3"\)')
        self.assertIn('SV3_ALPHA_VERSION "3.0.0-alpha.2"', DM)
        self.assertIn("obj-m += dm-swapz.o", MK)
        self.assertIn("SV3_BUILD_SMOKE", MK)
        self.assertIn("3.0.0-alpha.2", GOALS)

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
        self.assertIn("ctx->gc_scores[m->start_block / SV3_SEGMENT_BLOCKS]++", DM)
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
        self.assertLess(flush.index("blkdev_issue_flush("),
                        flush.index("sv3_complete(bio, 0)"))
        self.assertIn("if (error && needs_fua)", flush)
        self.assertNotIn("DM_MAPIO_KILL; /* Until FUA", body("sv3_map"))

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
        self.assertIn("queue_work(ctx->workqueue, &ctx->worker)", worker)
        self.assertLess(worker.index("sv3_flush_window(ctx)"),
                        worker.index("list_splice_init(&local, &ctx->incoming)"))

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
        self.assertLess(gc.index("a->gc_forbidden_victim = victim"),
                        gc.index("a->open_segment ="))

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

    def test_gc_status_is_truthful(self):
        self.assertIn("mode=alpha-live-gc", body("sv3_status"))
        self.assertNotIn("mode=alpha-no-gc", body("sv3_status"))
        self.assertIn("experimental live GC", DM)

    def test_map_and_teardown_are_owned(self):
        admitted = body("sv3_map")
        drained = body("sv3_drain")
        self.assertIn("dm_per_bio_data(", admitted)
        self.assertIn("WQ_MEM_RECLAIM", body("sv3_ctr"))
        self.assertIn("flush_workqueue(ctx->workqueue)", drained)
        self.assertIn("destroy_workqueue(ctx->workqueue)", body("sv3_free"))
        self.assertLess(admitted.index("spin_lock_irqsave(&ctx->queue_lock"),
                        admitted.index("if (!ctx->accepting)"))
        self.assertLess(admitted.index("if (!ctx->accepting)"),
                        admitted.index("list_add_tail(&entry->list"))
        self.assertLess(admitted.index("queue_work(ctx->workqueue"),
                        admitted.index("spin_unlock_irqrestore(&ctx->queue_lock, flags);\n\treturn DM_MAPIO_SUBMITTED"))
        self.assertLess(drained.index("WRITE_ONCE(ctx->accepting, false)"),
                        drained.index("flush_workqueue(ctx->workqueue)"))
        self.assertIn("spin_lock_irqsave(&ctx->queue_lock", drained)


if __name__ == "__main__":
    unittest.main(verbosity=2)
