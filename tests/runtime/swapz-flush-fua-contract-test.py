#!/usr/bin/env python3
"""Rootless exact-production-C REQ_PREFLUSH/FUA ordering contract.

Executes the actual kernel preflush/flush dispatch and physical batch staging
functions with finite fake BIO, lower flush, and buffer APIs. No dm-io,
real disk, physical persistence, module, or privileged operation is executed.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "kernel/dm-swapz.c"

def fn(src, name):
    pat = r"\bstatic\s+(?:void|int|bool)\s+" + re.escape(name) + r"\s*\([^;{}]*\)\s*\{"
    matches = list(re.finditer(pat, src, re.S))
    if len(matches) != 1:
        raise AssertionError("unique production function absent: " + name)
    start, opening, depth = matches[0].start(), matches[0].end()-1, 0
    for i in range(opening, len(src)):
        if src[i] == "{": depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0: return src[start:i+1]
    raise AssertionError("unterminated: " + name)

def guard(src):
    dispatch, flush, stage, lower, final, mapped = (
        fn(src, n) for n in ("swapz_process_bio", "swapz_process_flush",
            "swapz_stage_write_block", "swapz_submit_stream_buffer",
            "swapz_finalize_stream_buffer", "swapz_map"))
    for body, markers, msg in (
        (dispatch, ["if (bio->bi_opf & REQ_PREFLUSH)",
            "swapz_flush_pack(context, false, true)",
            "swapz_flush_write_batch(context)",
            "blkdev_issue_flush(context->backing->bdev)",
            "if (bio_op(bio) == REQ_OP_WRITE && !bio_sectors(bio))",
            "switch (bio_op(bio))"], "preflush execution ordering"),
        (flush, ["swapz_flush_pack(context, false, true)",
            "swapz_flush_write_batch(context)",
            "blkdev_issue_flush(context->backing->bdev)",
            "swapz_complete_bio(bio, error)"], "standalone flush ordering"),
        (stage, ["buffer->write_flags |=", "swapz_complete_bio(target->bio, 0)"],
            "FUA flags before staged acknowledgment")):
        indexes = [body.find(x) for x in markers]
        if -1 in indexes or indexes != sorted(indexes):
            raise AssertionError(msg)
    if "if (error)" not in dispatch or "swapz_set_failed(context, error);" not in dispatch:
        raise AssertionError("preflush failure not sticky")
    if "swapz_set_failed(context, error);" not in flush:
        raise AssertionError("flush failure not sticky")
    if "(REQ_FUA | REQ_SYNC | REQ_META | REQ_PRIO | REQ_SWAP)" not in stage:
        raise AssertionError("FUA batch aggregation missing")
    if "!(target->bio->bi_opf & REQ_FUA)" not in stage:
        raise AssertionError("FUA early completion permitted")
    if "REQ_OP_WRITE | REQ_SWAP | buffer->write_flags" not in lower:
        raise AssertionError("FUA not submitted to dm-io")
    if "swapz_complete_bio(record->bio, 0)" not in final:
        raise AssertionError("late FUA upper completion missing")
    if "const bool empty_preflush =" not in mapped:
        raise AssertionError("zero-sector preflush rejected by mapping admission")

DISPATCH_C = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define REQ_OP_READ 0U
#define REQ_OP_WRITE 1U
#define REQ_OP_DISCARD 2U
#define REQ_OP_FLUSH 3U
#define REQ_PREFLUSH (1U<<8)
#define REQ_FUA (1U<<9)
#define SWAPZ_STRATEGY_STAGED 2
#define unlikely(x) (x)
struct bio { unsigned int op, bi_opf, sectors; int completes, error; };
struct swapz_context {
    int failed, strategy, pack_error, batch_error, flush_error, write_error;
    int pack, batch, flush, writes;
    struct { void *bdev; } dev, *backing;
    char events[32]; int pos;
};
static struct swapz_context *active;
static void mark(struct swapz_context *c, char x) { c->events[c->pos++]=x; }
static unsigned int bio_op(struct bio *b) { return b->op; }
static unsigned int bio_sectors(struct bio *b) { return b->sectors; }
static int swapz_flush_pack(struct swapz_context *c,bool compact,bool rotate) {
    (void)compact;(void)rotate;c->pack++;mark(c,'P');return c->pack_error;
}
static int swapz_flush_write_batch(struct swapz_context *c) {
    c->batch++;mark(c,'B');return c->batch_error;
}
static int blkdev_issue_flush(void *device) {
    if (device!=active->backing->bdev) return -EUCLEAN;
    active->flush++;mark(active,'F');return active->flush_error;
}
static void swapz_set_failed(struct swapz_context *c,int error) {
    (void)error;c->failed=1;mark(c,'!');
}
static void swapz_complete_bio(struct bio *b,int error) {
    b->completes++;b->error=error;mark(active,'C');
}
static int swapz_process_write(struct swapz_context *c,struct bio *b) {
    (void)b;c->writes++;mark(c,'W');return c->write_error;
}
static int swapz_process_read(struct swapz_context *c,struct bio *b) {
    (void)b;mark(c,'R');return 0;
}
static int swapz_process_discard(struct swapz_context *c,struct bio *b) {
    (void)b;mark(c,'D');return 0;
}
"""
DISPATCH_END = r"""
int main(int argc,char **argv) {
    struct swapz_context c={0};struct bio b={0};
    int mode,err=0;const char *sequence=NULL;
    if(argc!=2||sscanf(argv[1],"%d",&mode)!=1||mode<0||mode>12)return 60;
    active=&c;c.backing=&c.dev;c.dev.bdev=(void*)0x1234;
    b.op=REQ_OP_WRITE;b.sectors=8;b.bi_opf=REQ_FUA;
    switch(mode) {
    case 0:b.bi_opf|=REQ_PREFLUSH;sequence="PBFW";break;
    case 1:b.bi_opf|=REQ_PREFLUSH;b.sectors=0;sequence="PBFC";break;
    case 2:b.bi_opf|=REQ_PREFLUSH;c.pack_error=-EIO;err=-EIO;sequence="P!C";break;
    case 3:b.bi_opf|=REQ_PREFLUSH;c.batch_error=-EIO;err=-EIO;sequence="PB!C";break;
    case 4:b.bi_opf|=REQ_PREFLUSH;c.flush_error=-EIO;err=-EIO;sequence="PBF!C";break;
    case 5:b.bi_opf|=REQ_PREFLUSH;c.write_error=-ENOSPC;err=-ENOSPC;sequence="PBFWC";break;
    case 6:b.op=REQ_OP_FLUSH;b.bi_opf=0;b.sectors=0;sequence="PBFC";break;
    case 7:b.op=REQ_OP_FLUSH;b.bi_opf=0;b.sectors=0;c.flush_error=-EIO;err=-EIO;sequence="PBF!C";break;
    case 8:c.failed=1;err=-EIO;sequence="C";break;
    case 9:sequence="W";break;
    case 10:b.op=REQ_OP_DISCARD;b.bi_opf=REQ_PREFLUSH;sequence="PBFD";break;
    case 11:b.op=REQ_OP_READ;b.bi_opf=REQ_PREFLUSH;sequence="PBFR";break;
    case 12:b.op=REQ_OP_FLUSH;b.bi_opf=0;b.sectors=0;c.pack_error=-EIO;err=-EIO;sequence="P!C";break;
    }
    swapz_process_bio(&c,&b);
    if(strcmp(c.events,sequence)) return 20;
    if(b.completes != (strchr(sequence,'C')?1:0))return 21;
    if(b.completes && b.error!=err)return 22;
    if(strchr(sequence,'W') && c.writes!=1)return 23;
    if(!strchr(sequence,'W') && c.writes)return 24;
    if((mode==2||mode==3||mode==4||mode==7||mode==12) && !c.failed)return 25;
    if(mode==0 && (c.pack!=1||c.batch!=1||c.flush!=1))return 26;
    puts("PREFLUSH_ORDER_OK");return 0;
}
"""
STAGE_C = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stddef.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
typedef uint32_t blk_opf_t;
#define REQ_FUA (1U<<9)
#define REQ_SYNC (1U<<10)
#define REQ_META (1U<<11)
#define REQ_PRIO (1U<<12)
#define REQ_SWAP (1U<<13)
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_MAX_PACKED_RECORDS 64U
#define SWAPZ_BUFFER_FILL 1U
#define SWAPZ_MAP_COMPRESSED 2U
#define SWAPZ_STRATEGY_STAGED 2U
#define WARN_ON_ONCE(x) (x)
struct list_head { struct list_head *next,*prev; };
#define INIT_LIST_HEAD(n) do {(n)->next=(n);(n)->prev=(n);}while(0)
#define list_empty(n) ((n)->next==(n))
static void list_add_tail(struct list_head *n,struct list_head *h) {
    n->next=h;n->prev=h->prev;h->prev->next=n;h->prev=n;
}
struct bio;
struct swapz_per_bio { struct list_head list; struct bio *bio; u8 block_index,record_index; };
struct bio { struct swapz_per_bio entry; u32 bi_opf; int completes,error; };
static struct swapz_per_bio *dm_per_bio_data(struct bio *b, size_t size) {
    (void)size;return &b->entry;
}
static void list_del_init(struct list_head *node) {
    node->prev->next=node->next;node->next->prev=node->prev;
    INIT_LIST_HEAD(node);
}
struct swapz_pending_record { struct bio *bio;u32 logical_page,generation;u16 stored_length;u8 record_index; };
struct swapz_write_batch_record { struct bio *bio;u32 logical_page,generation;u16 stored_length;u8 record_index,flags;bool upper_completed; };
struct swapz_write_batch_block { u8 record_count;bool compaction;struct swapz_write_batch_record records[64]; };
 struct swapz_stream_buffer { struct list_head owned_bios;u8 data[8192];struct swapz_write_batch_block blocks[2];u32 start_block,block_count;blk_opf_t write_flags;u8 id,state; };
 struct swapz_context { struct swapz_stream_buffer stream;struct list_head pending_bios;struct swapz_pending_record pending[64];u32 max_batch_blocks,strategy,physical;int failed,ensure_error,staged;struct { u32 staged_early_completions; } stats; };
static struct swapz_stream_buffer *swapz_fill_buffer(struct swapz_context *c){return &c->stream;}
static int swapz_submit_fill_buffer(struct swapz_context *c){(void)c;return -EIO;}
static int swapz_reap_inflight(struct swapz_context *c,bool wait){(void)c;(void)wait;return -EIO;}
static int swapz_ensure_physical_block(struct swapz_context *c,bool rotate){(void)rotate;return c->ensure_error;}
static u32 swapz_current_physical_block(struct swapz_context *c){return c->physical;}
static int swapz_flush_write_batch(struct swapz_context *c){(void)c;return -EIO;}
static void swapz_set_failed(struct swapz_context *c,int error){(void)error;c->failed=1;}
static void swapz_set_staged_ref(struct swapz_context *c,u32 pg,u32 gen,u8 id,u32 bi,u8 ri){(void)pg;(void)gen;(void)id;(void)bi;(void)ri;c->staged++;}
static void swapz_complete_bio(struct bio *b,int error){list_del_init(&b->entry.list);b->completes++;b->error=error;}
static void swapz_register_owned_bio(struct swapz_stream_buffer *buffer,struct bio *bio,u8 block_index,u8 record_index) {
    bio->entry.block_index=block_index;bio->entry.record_index=record_index;
    list_add_tail(&bio->entry.list,&buffer->owned_bios);
}
static void swapz_note_block_written(struct swapz_context *c){c->physical++;}
"""
STAGE_END = r"""
int main(int argc,char **argv) {
    struct swapz_context c={0};struct bio fua={0},plain={0};
    struct swapz_pending_record rec[1]={{0}};unsigned char data[4096]={42};
    struct swapz_write_batch_record *first,*next;int mode,rc;
    if(argc!=2||sscanf(argv[1],"%d",&mode)!=1||mode<0||mode>7)return 60;
    c.max_batch_blocks=2;c.physical=10;c.strategy=SWAPZ_STRATEGY_STAGED;
    c.stream.id=0;c.stream.state=SWAPZ_BUFFER_FILL;
    INIT_LIST_HEAD(&c.stream.owned_bios);
    INIT_LIST_HEAD(&c.pending_bios);
    INIT_LIST_HEAD(&fua.entry.list);
    INIT_LIST_HEAD(&plain.entry.list);
    fua.entry.bio=&fua;plain.entry.bio=&plain;
    fua.bi_opf=REQ_FUA|REQ_SYNC;
    rec[0].bio=&fua;rec[0].logical_page=3;rec[0].generation=4;
    rec[0].stored_length=5;
    if(mode==0||mode==3)fua.bi_opf=0;
    if(mode==2)c.strategy=1;
    if(mode==4)c.ensure_error=-EIO;
    if(mode==5)c.stream.state=0;
    if(mode==6)fua.bi_opf=REQ_FUA|REQ_PRIO;
    if(mode==7) {
        c.pending[0]=rec[0];
        list_add_tail(&fua.entry.list,&c.pending_bios);
    }
    rc=swapz_stage_write_block(&c,data,mode==7?c.pending:rec,1,mode==2?0:SWAPZ_MAP_COMPRESSED,
                                mode==3,false);
    if(mode==4)return rc==-EIO&&!c.stream.block_count&&!fua.completes?0:21;
    if(mode==5)return rc==-EUCLEAN&&c.failed&&!fua.completes?0:22;
    if(rc||c.stream.block_count!=1||c.staged!=1)return 23;
    if(mode==7 && (!list_empty(&c.pending_bios) ||
                   list_empty(&c.stream.owned_bios) ||
                   fua.entry.block_index!=0 || fua.entry.record_index!=0))
        return 29;
    first=&c.stream.blocks[0].records[0];
    if(mode==0){
        if(fua.completes!=1||first->bio||!first->upper_completed)return 24;
    }else if(fua.completes||first->bio!=&fua||first->upper_completed)return 25;
    if((c.stream.write_flags&(REQ_FUA|REQ_SYNC|REQ_PRIO)) !=
       (fua.bi_opf&(REQ_FUA|REQ_SYNC|REQ_PRIO)))return 26;
    if(mode==1){
        plain.bi_opf=REQ_META;rec[0].bio=&plain;rec[0].logical_page=4;
        rc=swapz_stage_write_block(&c,data,rec,1,SWAPZ_MAP_COMPRESSED,false,false);
        if(rc||c.stream.block_count!=2||c.staged!=2)return 27;
        next=&c.stream.blocks[1].records[0];
        if(plain.completes!=1||next->bio||!next->upper_completed||
           fua.completes||first->bio!=&fua||
           !(c.stream.write_flags&REQ_FUA)||!(c.stream.write_flags&REQ_META))return 28;
    }
    puts("FUA_STAGING_OK");return 0;
}
"""

class FlushFUAContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = SOURCE.read_text(encoding="utf-8")
        guard(cls.src)
        cc=shutil.which("cc")
        if cc is None: raise AssertionError("userspace C compiler unavailable")
        cls.tmp=tempfile.TemporaryDirectory(prefix="swapz-fua-c-")
        cls.binaries={}
        for label,prefix,names,suffix in (
            ("dispatch",DISPATCH_C,("swapz_process_flush","swapz_process_bio"),DISPATCH_END),
            ("stage",STAGE_C,("swapz_stage_write_block",),STAGE_END)):
            path=Path(cls.tmp.name)/(label+".c")
            exe=Path(cls.tmp.name)/label
            path.write_text(prefix+"\n"+"\n".join(fn(cls.src,n) for n in names)+
                            "\n"+suffix,encoding="utf-8")
            cp=subprocess.run([cc,"-std=c11","-O2","-Wall","-Wextra","-Werror",
                               "-o",str(exe),str(path)],
                              capture_output=True,text=True,timeout=15)
            if cp.returncode: raise AssertionError(label+" production C compile: "+cp.stderr)
            cls.binaries[label]=exe
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def run_case(self,label,case):
        cp=subprocess.run([str(self.binaries[label]),str(case)],
                          capture_output=True,text=True,timeout=3)
        self.assertEqual(cp.returncode,0,f"{label} {case} {cp.stdout} {cp.stderr}")
    def test_dispatch_preflush_and_failure_matrix(self):
        for mode in range(13):
            with self.subTest(mode=mode): self.run_case("dispatch",mode)
    def test_stage_fua_mixed_record_and_early_completion_matrix(self):
        for mode in range(8):
            with self.subTest(mode=mode): self.run_case("stage",mode)
    def test_source_identity(self): guard(self.src)
    def mutation(self,name,needle,replacement,msg):
        old=fn(self.src,name)
        self.assertIn(needle,old)
        with self.assertRaisesRegex(AssertionError,msg):
            guard(self.src.replace(old,old.replace(needle,replacement,1),1))
    def test_mutation_preflush_bypass(self):
        self.mutation("swapz_process_bio","if (bio->bi_opf & REQ_PREFLUSH)",
                      "if (false)","preflush execution ordering")
    def test_mutation_fua_drop_at_stage(self):
        self.mutation("swapz_stage_write_block",
                      "(REQ_FUA | REQ_SYNC | REQ_META | REQ_PRIO | REQ_SWAP)",
                      "(REQ_SYNC | REQ_META | REQ_PRIO | REQ_SWAP)",
                      "FUA batch aggregation")
    def test_mutation_fua_early_complete(self):
        self.mutation("swapz_stage_write_block","!(target->bio->bi_opf & REQ_FUA)",
                      "true","FUA early completion")
    def test_mutation_fua_drop_at_submit(self):
        self.mutation("swapz_submit_stream_buffer","REQ_OP_WRITE | REQ_SWAP | buffer->write_flags",
                      "REQ_OP_WRITE | REQ_SWAP","FUA not submitted")
    def test_mutation_flush_completion_removed(self):
        self.mutation("swapz_process_flush","swapz_complete_bio(bio, error);",
                      "/* removed */","standalone flush ordering")
    def test_mutation_zero_length_preflush_not_special(self):
        self.mutation("swapz_process_bio",
                      "if (bio_op(bio) == REQ_OP_WRITE && !bio_sectors(bio))",
                      "if (false)","preflush execution ordering")

if __name__=="__main__": unittest.main(verbosity=2)
