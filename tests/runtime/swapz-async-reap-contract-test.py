#!/usr/bin/env python3
"""Rootless production-C async timeout, late callback and BIO ownership tests.

Compiles VERBATIM production callback, ref-matching, upper-BIO completion,
finalize and reap functions with finite deterministic user-mode kernel seams.
Never accesses devices, swap, module loading, or privileged cleanup.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "kernel" / "dm-swapz.c"
PURE = (
    "swapz_stream_record_current",
    "swapz_staged_ref_matches",
    "swapz_clear_staged_ref",
    "swapz_stream_io_complete",
    "swapz_complete_buffer_bios",
    "swapz_finalize_stream_buffer",
    "swapz_reap_inflight",
)


def function(source: str, name: str) -> str:
    found = list(re.finditer(r"\bstatic\s+(?:bool|int|void)\s+" +
                            re.escape(name) + r"\s*\([^;{}]*\)\s*\{",
                            source, re.DOTALL))
    if len(found) != 1:
        raise AssertionError(f"exactly one production function required: {name}")
    begin, opening = found[0].start(), found[0].end() - 1
    depth = 0
    for pos in range(opening, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if not depth:
                return source[begin:pos+1]
    raise AssertionError(f"unterminated function {name}")


def source_contract(source: str) -> None:
    callback = function(source, "swapz_stream_io_complete")
    submit = function(source, "swapz_submit_stream_buffer")
    reap = function(source, "swapz_reap_inflight")
    final = function(source, "swapz_finalize_stream_buffer")
    bios = function(source, "swapz_complete_buffer_bios")
    install = function(source, "swapz_install_mapping")
    teardown = source[source.index("static void swapz_dtr("):
                      source.index("static int swapz_ctr(")]
    if not (callback.index("buffer->io_error =") <
            callback.index("complete(&buffer->completion)") <
            callback.index("atomic_dec_and_test(&context->async_callbacks)")):
        raise AssertionError("callback publication order corrupted")
    if not (submit.index("atomic_inc(&context->async_callbacks)") <
            submit.index("dm_io(&request") <
            submit.index("if (error) {")):
        raise AssertionError("dm-io submission callback reference ordering corrupted")
    if "buffer->io_error = error;" not in submit or \
            "complete(&buffer->completion);" not in submit:
        raise AssertionError("synchronous dm-io rejection lost completion token")
    if not (reap.index("if (try_wait_for_completion(&buffer->completion))") <
            reap.index("report_timeout:") < reap.index("completed:")):
        raise AssertionError("late completion not preferred over timeout")
    timeout = reap[reap.index("report_timeout:"):reap.index("completed:")]
    if "swapz_complete_buffer_bios(context, buffer, -ETIMEDOUT);" not in timeout:
        raise AssertionError("timeout leaves upper BIOs uncompleted")
    if "swapz_reset_stream_buffer" in timeout or \
            "context->inflight_buffer_id = -1;" in timeout:
        raise AssertionError("timeout recycles lower-owned memory before callback")
    if not (reap.index("cancel_delayed_work_sync") <
            reap.index("context->inflight_buffer_id = -1;") <
            reap.index("swapz_finalize_stream_buffer")):
        raise AssertionError("reaping finalizes buffer without callback token")
    if "if (buffer->watchdog_reported)" not in reap or \
            "try_wait_for_completion" not in reap:
        raise AssertionError("duplicate watchdog reporting not prevented")
    if "record->bio = NULL;" not in bios:
        raise AssertionError("upper BIO completion ownership not cleared")
    if "record->upper_completed &&" not in final or \
            "if (retain) {" not in final or \
            "record->bio = NULL;" not in final:
        raise AssertionError("failed lower write discards acknowledged staged data")
    if "if (unlikely(context->failed))" not in install:
        raise AssertionError("late lower success can publish mapping after failure")
    if ("swapz_wait_async_callbacks(context)" not in teardown or
            teardown.index("swapz_wait_async_callbacks(context)") >=
            teardown.index("swapz_free_context(context)")):
        raise AssertionError("context freed before callback ownership drained")


PREFIX = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint64_t u64;
typedef uint16_t u16;
typedef uint8_t u8;
#define SWAPZ_ASYNC_WATCHDOG_MS 30000U
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_MAX_PACKED_RECORDS 64U
#define SWAPZ_MAP_COMPRESSED 2U
#define SWAPZ_MAX_COMPRESSED_BYTES 3568U
#define SWAPZ_BUFFER_FREE 0U
#define SWAPZ_BUFFER_FILL 1U
#define SWAPZ_BUFFER_INFLIGHT 2U
#define unlikely(x) (x)
#define likely(x) (x)
#define min(a,b) ((a)<(b)?(a):(b))
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,y) ((x)=(y))
#define msecs_to_jiffies(x) (x)
#define max_t(t,a,b) ((t)(a)>(t)(b)?(t)(a):(t)(b))
struct completion { int done; };
struct delayed_work { int cancels; };
struct work_struct { int flag; };
struct stub_queue { int queues; };
struct stub_atomic { int value; };
struct stub_wait { int wakes; };
struct bio { int completes, error; };
struct swapz_context;
struct swapz_write_batch_record {
    struct bio *bio;
    u32 logical_page, generation;
    u16 stored_length;
    u8 record_index, flags;
    bool upper_completed;
};
struct swapz_write_batch_block {
    u8 record_count;
    bool compaction;
    struct swapz_write_batch_record records[SWAPZ_MAX_PACKED_RECORDS];
};
struct swapz_stream_buffer {
    struct swapz_context *context;
    struct swapz_write_batch_block *blocks;
    u32 start_block, block_count;
    u8 id, state;
    int io_error;
    bool watchdog_expired, watchdog_reported;
    struct completion completion;
    struct delayed_work watchdog_work;
};
struct swapz_staged_ref {
    u32 generation;
    u8 block_index, record_index, buffer_id, valid;
};
struct swapz_stats {
    u64 physical_write_bytes, physical_write_requests, multi_block_write_requests;
    u64 max_write_batch_blocks, staged_cancellations, compaction_write_bytes;
    u64 async_watchdog_timeouts;
};
struct swapz_context {
    struct swapz_stream_buffer stream_buffers[2];
    struct swapz_staged_ref staged_refs[2];
    u32 generations[2];
    u32 logical_pages, max_batch_blocks, physical_blocks;
    struct swapz_stats stats;
    int inflight_buffer_id, installed, resets, failed_events;
    bool failed, accepting_io;
    struct stub_atomic async_callbacks;
    struct stub_wait async_callback_wait;
    struct stub_queue *workqueue;
    struct work_struct io_work;
};
static int boundary_race;
static void complete(struct completion *c) { c->done++; }
static int try_wait_for_completion(struct completion *c) {
    if (!c->done) return 0;
    c->done--; return 1;
}
static unsigned long wait_for_completion_timeout(struct completion *c, unsigned long ticks) {
    (void)ticks;
    if (boundary_race) { boundary_race=0; complete(c); return 0; }
    return (unsigned long)try_wait_for_completion(c);
}
static int cancel_delayed_work_sync(struct delayed_work *w) { w->cancels++; return 1; }
static int atomic_dec_and_test(struct stub_atomic *a) { return --a->value==0; }
static void wake_up_all(struct stub_wait *w) { w->wakes++; }
static void queue_work(struct stub_queue *q, struct work_struct *w) { (void)w; q->queues++; }
static void swapz_set_failed(struct swapz_context *c, int err) {
    (void)err; c->failed=true; c->failed_events++;
}
static void swapz_complete_bio(struct bio *b, int err) {
    b->completes++; b->error=err;
}
static void swapz_install_mapping(struct swapz_context *c, u32 pg,
                                  u32 phys, u16 length, u8 idx, u8 flags) {
    (void)pg; (void)phys; (void)length; (void)idx; (void)flags;
    if (!c->failed) c->installed++;
}
static void swapz_reset_stream_buffer(struct swapz_context *c,
                                      struct swapz_stream_buffer *b, u8 state) {
    c->resets++; b->state=state; b->block_count=0;
}
"""
SUFFIX = r"""
static struct swapz_context c;
static struct swapz_write_batch_block blocks[2];
#define block blocks[0]
static struct bio b;
static struct bio b2;
static struct stub_queue q;
static void setup(bool outstanding, bool early) {
    struct swapz_stream_buffer *stream;
    memset(&c,0,sizeof(c));
    memset(blocks,0,sizeof(blocks));
    memset(&b,0,sizeof(b));
    memset(&b2,0,sizeof(b2));
    memset(&q,0,sizeof(q));
    boundary_race=0;
    stream=&c.stream_buffers[0];
    stream->context=&c;
    stream->blocks=&block;
    stream->block_count=1;
    stream->start_block=9;
    stream->state=SWAPZ_BUFFER_INFLIGHT;
    stream->id=0;
    c.generations[0]=7;
    c.logical_pages=2;
    c.physical_blocks=32;
    c.max_batch_blocks=1;
    c.inflight_buffer_id=0;
    c.accepting_io=true;
    c.async_callbacks.value=1;
    c.workqueue=&q;
    block.record_count=1;
    block.records[0].logical_page=0;
    block.records[0].generation=7;
    block.records[0].record_index=0;
    block.records[0].stored_length=4;
    block.records[0].flags=SWAPZ_MAP_COMPRESSED;
    block.records[0].upper_completed=early;
    if (outstanding) block.records[0].bio=&b;
    c.staged_refs[0].valid=1;
    c.staged_refs[0].generation=7;
}
static int scenario(int id) {
    struct swapz_stream_buffer *s=&c.stream_buffers[0];
    int result;
    if (id==0) {
        setup(false,false);
        c.inflight_buffer_id=-1;
        if (swapz_reap_inflight(&c,false) || c.resets) return 1;
    } else if (id==1) {
        setup(true,false);
        if (swapz_reap_inflight(&c,false)!=-EAGAIN || b.completes ||
            c.failed || c.resets || c.inflight_buffer_id!=0) return 2;
    } else if (id==2 || id==3 || id==4) {
        setup(true,false);
        if (id==2 || id==4) s->watchdog_expired=true;
        result=swapz_reap_inflight(&c,id==3);
        if (result!=-ETIMEDOUT || !c.failed || c.resets ||
            c.inflight_buffer_id!=0 || s->state!=SWAPZ_BUFFER_INFLIGHT ||
            c.stats.async_watchdog_timeouts!=1 || b.completes!=1 ||
            b.error!=-ETIMEDOUT || block.records[0].bio) return 3;
        if (swapz_reap_inflight(&c,false)!=-EAGAIN ||
            swapz_reap_inflight(&c,true)!=-ETIMEDOUT ||
            c.stats.async_watchdog_timeouts!=1 || b.completes!=1)
            return 4;
        if (id==4) {
            swapz_stream_io_complete(0,s);
            result=swapz_reap_inflight(&c,false);
            if (result!=-EUCLEAN || c.resets || c.installed ||
                c.inflight_buffer_id!=-1 || b.completes!=1 ||
                c.async_callbacks.value!=0) return 5;
        }
    } else if (id==5 || id==6 || id==7 || id==8) {
        const bool failure=(id==6 || id==8);
        setup(id==5 || id==6,id==7 || id==8);
        swapz_stream_io_complete(failure?1:0,s);
        result=swapz_reap_inflight(&c,false);
        if (id==5 && (result || c.failed || c.installed!=1 ||
                      c.resets!=1 || b.completes!=1 || b.error ||
                      c.staged_refs[0].valid)) return 6;
        if (id==6 && (result!=-EIO || !c.failed || c.installed ||
                      c.resets!=1 || b.completes!=1 || b.error!=-EIO ||
                      c.staged_refs[0].valid)) return 7;
        if (id==7 && (result || c.installed!=1 || c.resets!=1 ||
                      c.staged_refs[0].valid)) return 8;
        if (id==8 && (result!=-EIO || !c.failed || c.installed ||
                      c.resets || !c.staged_refs[0].valid ||
                      s->state!=SWAPZ_BUFFER_INFLIGHT)) return 9;
        if (c.async_callbacks.value!=0 || c.async_callback_wait.wakes!=1 ||
            q.queues!=1 || s->watchdog_work.cancels!=1 ||
            c.inflight_buffer_id!=-1) return 10;
        if (swapz_reap_inflight(&c,false)!=0) return 11;
    } else if (id==9 || id==10) {
        setup(true,false);
        if (id==9) boundary_race=1;
        else complete(&s->completion);
        result=swapz_reap_inflight(&c,id==9);
        if (result || c.failed || c.stats.async_watchdog_timeouts ||
            b.completes!=1 || c.installed!=1 || c.resets!=1) return 12;
    } else if (id==11 || id==12) {
        setup(false,true);
        s->watchdog_expired=true;
        if (swapz_reap_inflight(&c,false)!=-ETIMEDOUT ||
            !c.staged_refs[0].valid) return 13;
        swapz_stream_io_complete(id==11?1:0,s);
        result=swapz_reap_inflight(&c,false);
        if (result!=(id==11?-EIO:-EUCLEAN) || c.installed || c.resets ||
            !c.staged_refs[0].valid || c.inflight_buffer_id!=-1 ||
            s->state!=SWAPZ_BUFFER_INFLIGHT) return 14;
    } else if (id==13) {
        setup(true,false);
        c.generations[0]=8;
        swapz_stream_io_complete(0,s);
        result=swapz_reap_inflight(&c,false);
        if (result || c.installed || b.completes!=1 || b.error ||
            c.staged_refs[0].valid || c.resets!=1) return 15;
    } else if (id==14) {
        setup(true,false);
        c.accepting_io=false;
        swapz_stream_io_complete(1,s);
        if (q.queues || c.async_callbacks.value ||
            c.async_callback_wait.wakes!=1) return 16;
        if (swapz_reap_inflight(&c,true)!=-EIO || b.completes!=1) return 17;
    } else if (id==15) {
        setup(true,false);
        s->watchdog_reported=true;
        if (swapz_reap_inflight(&c,true)!=-ETIMEDOUT ||
            c.stats.async_watchdog_timeouts || b.completes ||
            c.inflight_buffer_id!=0) return 18;
    } else if (id>=16 && id<=23) {
        /* Fault-inject in-memory metadata after the lower write was submitted.
         * Finalization must fail before any success publication or unsafe index. */
        setup(true,false);
        if (id==16) s->block_count=2;
        if (id==17) block.record_count=65;
        if (id==18) block.records[0].logical_page=2;
        if (id==19) block.records[0].record_index=1;
        if (id==20) block.records[0].flags=4;
        if (id==21) block.records[0].flags=0;
        if (id==22 || id==23) {
            c.max_batch_blocks=2;
            s->block_count=2;
            blocks[1].record_count=1;
            blocks[1].records[0].logical_page=1;
            blocks[1].records[0].generation=7;
            blocks[1].records[0].record_index=1; /* Wrong descriptor slot. */
            blocks[1].records[0].stored_length=4;
            blocks[1].records[0].flags=SWAPZ_MAP_COMPRESSED;
        }
        if (id==23) {
            b.completes=1; /* Upper BIO was already acknowledged. */
            block.records[0].bio=NULL;
            block.records[0].upper_completed=true;
        }
        swapz_stream_io_complete(id==23?1:0,s);
        result=swapz_reap_inflight(&c,false);
        if (result!=-EUCLEAN || !c.failed ||
            c.installed || c.resets || s->state!=SWAPZ_BUFFER_INFLIGHT ||
            c.inflight_buffer_id!=-1 || c.async_callbacks.value ||
            !s->completion.reinits && false) return 30;
        if (id==23) {
            if (b.completes!=1 || !c.staged_refs[0].valid) return 31;
        } else if (b.completes!=1 || b.error!=-EUCLEAN ||
                   block.records[0].bio) return 32;
    } else if (id==24) {
        setup(true,false);
        c.max_batch_blocks=2;
        s->block_count=2;
        blocks[1].record_count=1;
        blocks[1].records[0].logical_page=1;
        blocks[1].records[0].generation=7;
        blocks[1].records[0].stored_length=4;
        blocks[1].records[0].flags=SWAPZ_MAP_COMPRESSED;
        blocks[1].records[0].bio=&b2;
        c.generations[1]=7;
        c.staged_refs[1]=(struct swapz_staged_ref){
            .valid=1,.generation=7,.buffer_id=0,.block_index=1,.record_index=0};
        swapz_stream_io_complete(0,s);
        result=swapz_reap_inflight(&c,false);
        if (result || c.failed || c.installed!=2 || c.resets!=1 ||
            b.completes!=1 || b2.completes!=1 ||
            c.staged_refs[0].valid || c.staged_refs[1].valid) return 33;
    } else if (id==25 || id==26 || id==27) {
        setup(true,false);
        if (id==25) s->start_block=c.physical_blocks;
        if (id==26) s->block_count=0;
        if (id==27) block.record_count=0;
        swapz_stream_io_complete(1,s);
        result=swapz_reap_inflight(&c,false);
        if (result!=-EUCLEAN || !c.failed || c.installed ||
            c.resets || s->state!=SWAPZ_BUFFER_INFLIGHT) return 34;
    } else return 50;
    return 0;
}
int main(int argc, char **argv) {
    int i, rc;
    if (argc!=2 || sscanf(argv[1],"%d",&i)!=1 || i<0 || i>27) return 60;
    rc=scenario(i);
    if (rc) { fprintf(stderr,"scenario %d failed code %d\n",i,rc); return rc; }
    printf("ASYNC_REAP_%d_OK\n",i);
    return 0;
}
"""


class AsyncReapExactC(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        source_contract(cls.source)
        cc=shutil.which("cc")
        if cc is None:
            raise AssertionError("required rootless userspace C compiler missing")
        cls.tmp=tempfile.TemporaryDirectory(prefix="swapz-async-exact-c-")
        cls.binary=Path(cls.tmp.name)/"async-exact-c"
        program=Path(cls.tmp.name)/"async-exact-c.c"
        program.write_text(PREFIX+"\n"+"\n".join(function(cls.source,f) for f in PURE)+
                           "\n"+SUFFIX,encoding="utf-8")
        cp=subprocess.run([cc,"-std=c11","-O2","-Wall","-Wextra","-Werror",
                           "-o",str(cls.binary),str(program)],
                          capture_output=True,text=True,timeout=15)
        if cp.returncode:
            raise AssertionError("production C compilation failed: "+cp.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def run_case(self,i:int) -> None:
        cp=subprocess.run([str(self.binary),str(i)],capture_output=True,
                          text=True,timeout=3)
        self.assertEqual(cp.returncode,0,f"case={i} {cp.stdout} {cp.stderr}")
        self.assertIn(f"ASYNC_REAP_{i}_OK",cp.stdout)

    def test_malformed_late_completion_is_bounded_and_never_partially_publishes(self):
        for i in range(16,24):
            with self.subTest(case=i):
                self.run_case(i)

    def test_two_block_valid_finalize_still_publishes_and_completes(self):
        self.run_case(24)

    def test_bad_physical_extent_and_empty_counts_preserve_resident_buffer(self):
        for i in (25,26,27):
            with self.subTest(case=i):
                self.run_case(i)

    def test_no_inflight(self): self.run_case(0)
    def test_incomplete_nonblocking_reap(self): self.run_case(1)
    def test_watchdog_poll_sticky_once(self): self.run_case(2)
    def test_watchdog_wait_sticky_once(self): self.run_case(3)
    def test_timeout_late_success_cannot_publish_or_double_complete(self): self.run_case(4)
    def test_normal_lower_success_completes_once(self): self.run_case(5)
    def test_normal_lower_error_completes_once(self): self.run_case(6)
    def test_early_completed_staged_normal_success(self): self.run_case(7)
    def test_early_completed_staged_lower_error_retains_data(self): self.run_case(8)
    def test_completion_racing_timeout_wins(self): self.run_case(9)
    def test_completion_precedes_watchdog(self): self.run_case(10)
    def test_early_completed_timeout_and_late_error_retains_data(self): self.run_case(11)
    def test_early_completed_timeout_and_late_success_retains_data(self): self.run_case(12)
    def test_stale_generation_does_not_publish(self): self.run_case(13)
    def test_teardown_suppresses_requeue_and_drains_callback(self): self.run_case(14)
    def test_repeat_reported_timeout_does_not_double_count(self): self.run_case(15)

    def test_source_callback_release_contract(self): source_contract(self.source)

    def test_timeout_recycling_mutation_rejected(self):
        original=function(self.source,"swapz_reap_inflight")
        marker="swapz_complete_buffer_bios(context, buffer, -ETIMEDOUT);"
        self.assertIn(marker,original)
        changed=original.replace(marker,marker+"\n\tcontext->inflight_buffer_id = -1;",1)
        with self.assertRaisesRegex(AssertionError,"recycles lower-owned"):
            source_contract(self.source.replace(original,changed,1))

    def test_missing_upper_bio_clear_mutation_rejected(self):
        original=function(self.source,"swapz_complete_buffer_bios")
        marker="record->bio = NULL;"
        self.assertIn(marker,original)
        with self.assertRaisesRegex(AssertionError,"completion ownership"):
            source_contract(self.source.replace(original,original.replace(marker,"/* mutant */",1),1))

    def test_missing_callback_refwait_mutation_rejected(self):
        marker="swapz_wait_async_callbacks(context);"
        start=self.source.index("static void swapz_dtr(")
        end=self.source.index("static int swapz_ctr(",start)
        teardown=self.source[start:end]
        self.assertIn(marker,teardown)
        changed=teardown.replace(marker,"/* mutant skip callback drain */",1)
        with self.assertRaisesRegex(AssertionError,"freed before callback"):
            source_contract(self.source.replace(teardown,changed,1))

    def test_missing_submit_rejection_token_mutation_rejected(self):
        original=function(self.source,"swapz_submit_stream_buffer")
        marker="buffer->io_error = error;"
        self.assertIn(marker,original)
        with self.assertRaisesRegex(AssertionError,"rejection lost"):
            source_contract(self.source.replace(original,original.replace(marker,"/* drop error */",1),1))

    def test_missing_failed_staged_retain_mutation_rejected(self):
        original=function(self.source,"swapz_finalize_stream_buffer")
        marker="if (retain) {"
        self.assertIn(marker,original)
        with self.assertRaisesRegex(AssertionError,"discards acknowledged"):
            source_contract(self.source.replace(original,original.replace(marker,"if (false) {",1),1))


if __name__=="__main__":
    unittest.main(verbosity=2)
