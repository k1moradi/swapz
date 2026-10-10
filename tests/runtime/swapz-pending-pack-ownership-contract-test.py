#!/usr/bin/env python3
"""Rootless exact-production-C pending-pack BIO ownership and count fault matrix.

Compiles the production pack registration, preflight, addition, flush, failure
drain and BIO completion functions verbatim. Kernel data-movement/IO seams are
bounded mocks, never privileged, no module, device, swap, NBD or loop usage.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "kernel" / "dm-swapz.c"
FUNCTIONS = (
    "swapz_complete_bio", "swapz_pack_bios_match",
    "swapz_register_pending_bio", "swapz_reset_pack",
    "swapz_fail_pending_pack_bios", "swapz_fail_unsent_upper_bios",
    "swapz_pack_can_fit", "swapz_flush_pack", "swapz_add_compressed_record",
)

def exact_function(src: str, name: str) -> str:
    matches = list(re.finditer(
        r"\bstatic\s+(?:bool|void|int)\s+" + re.escape(name) +
        r"\s*\([^;{}]*\)\s*\{", src, re.DOTALL))
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one production {name}: {len(matches)}")
    start = matches[0].start()
    depth = 0
    for i in range(matches[0].end() - 1, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i+1]
    raise AssertionError(f"unterminated production C: {name}")

PREFIX = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
typedef uint64_t u64;
#define SWAPZ_MAX_PACKED_RECORDS 64U
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_CONTAINER_BASE_BYTES 8U
#define SWAPZ_CONTAINER_MAGIC 0x53574150U
#define SWAPZ_CONTAINER_VERSION 1U
#define SWAPZ_MAP_COMPRESSED 2U
#define WARN_ON_ONCE(expr) ((void)(expr))
#define unlikely(expr) (expr)
#define likely(expr) (expr)
#define min(a,b) ((a)<(b)?(a):(b))
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
#define cpu_to_le32(n) (n)
#define cpu_to_le16(n) (n)
struct list_head {struct list_head *next,*prev;};
#define INIT_LIST_HEAD(n) do {(n)->next=(n);(n)->prev=(n);}while(0)
#define list_empty(n) ((n)->next==(n))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_first_entry(h,t,m) container_of((h)->next,t,m)
#define list_for_each_entry(entry,head,member) \
    for (struct list_head *it=(head)->next; \
         it!=(head) && ((entry)=container_of(it,struct swapz_per_bio,member),1); \
         it=it->next)
static void list_add_tail(struct list_head *x, struct list_head *h) {
    x->next=h; x->prev=h->prev; h->prev->next=x; h->prev=x;
}
static void list_del_init(struct list_head *x) {
    x->prev->next=x->next; x->next->prev=x->prev;
    INIT_LIST_HEAD(x);
}
struct bio;
struct swapz_per_bio {
    struct list_head list;
    struct bio *bio;
    u8 block_index,record_index;
};
struct bio {
    struct swapz_per_bio entry;
    int completes,bi_status;
};
struct swapz_pending_record {
    struct bio *bio;u32 logical_page,generation;u16 stored_length;u8 record_index;
};
struct swapz_record_disk {u32 logical_page;u16 offset,length;};
struct swapz_container_disk {u32 magic;u16 version,record_count;};
struct swapz_stream_buffer {
    struct list_head owned_bios;
    struct bio *staged[64];
    u32 staged_count;
};
struct swapz_context {
    u8 pack_data[SWAPZ_BLOCK_BYTES];
    void *pack_buffer;
    unsigned int pack_payload_start,pack_record_count;
    struct list_head pending_bios;
    struct swapz_pending_record pending[SWAPZ_MAX_PACKED_RECORDS];
    struct swapz_stream_buffer stream;
    unsigned int fails,failed,stage_error,ensure_error,stages,unsent_drains;
    struct {u64 compressed_payload_bytes, compressed_pages;} stats;
};
static struct swapz_per_bio *dm_per_bio_data(struct bio *bio,size_t size) {
    (void)size;return &bio->entry;
}
static int errno_to_blk_status(int err) {return err;}
static void bio_endio(struct bio *bio) {bio->completes++;}
static void swapz_set_failed(struct swapz_context *c,int error) {
    (void)error;c->failed=true;c->fails++;
}
static struct swapz_stream_buffer *swapz_fill_buffer(struct swapz_context *c) {
    return &c->stream;
}
static void swapz_complete_buffer_bios(struct swapz_context *c,
                                       struct swapz_stream_buffer *b,int error) {
    (void)b;(void)error;c->unsent_drains++;
}
static int swapz_ensure_physical_block(struct swapz_context *c,bool allow) {
    (void)allow;return c->ensure_error;
}
static struct swapz_record_disk *swapz_container_record(void *data,u32 index) {
    return &((struct swapz_record_disk *)((char *)data+
                                          SWAPZ_CONTAINER_BASE_BYTES))[index];
}
static int swapz_stage_write_block(struct swapz_context *c,const void *data,
                                    const struct swapz_pending_record *records,
                                    unsigned int count,u8 flags,
                                    bool compaction,bool rotation) {
    (void)data;(void)flags;(void)compaction;(void)rotation;
    c->stages++;
    if (c->stage_error) return (int)c->stage_error;
    if (count>SWAPZ_MAX_PACKED_RECORDS) return -EUCLEAN;
    for (unsigned int i=0;i<count;i++) {
        struct bio *bio=records[i].bio;
        struct swapz_per_bio *entry;
        if (!bio) continue;
        entry=dm_per_bio_data(bio,sizeof(*entry));
        list_del_init(&entry->list);
        entry->block_index=0;
        entry->record_index=(u8)i;
        list_add_tail(&entry->list,&c->stream.owned_bios);
        c->stream.staged[c->stream.staged_count++]=bio;
    }
    return 0;
}
"""
SUFFIX = r"""
static struct swapz_context c;
static struct bio bios[65];
static const unsigned char compressed[32]={42};
static unsigned int members(const struct list_head *h) {
    unsigned int n=0;
    for (const struct list_head *it=h->next;it!=h;it=it->next) {
        if (++n>65) return 10000;
    }
    return n;
}
static void setup(void) {
    memset(&c,0,sizeof(c));memset(bios,0,sizeof(bios));
    c.pack_buffer=c.pack_data;
    INIT_LIST_HEAD(&c.pending_bios);
    INIT_LIST_HEAD(&c.stream.owned_bios);
    c.pack_payload_start=SWAPZ_BLOCK_BYTES;
    for (int i=0;i<65;i++) {
        bios[i].entry.bio=&bios[i];
        INIT_LIST_HEAD(&bios[i].entry.list);
    }
}
static int add(unsigned int index, bool with_bio) {
    return swapz_add_compressed_record(
        &c,with_bio?&bios[index]:NULL,index,1,
        compressed,32,false,true);
}
static int drain_once(int error) {
    swapz_fail_unsent_upper_bios(&c,error);
    return (int)members(&c.pending_bios);
}
static void stream_complete(int error) {
    while (!list_empty(&c.stream.owned_bios)) {
        struct swapz_per_bio *e =
           list_first_entry(&c.stream.owned_bios,struct swapz_per_bio,list);
        swapz_complete_bio(e->bio,error);
    }
}
static int run(int mode,bool mutant) {
    int rc;
    setup();
    switch(mode) {
    case 0: /* Two valid pack owners transfer to one stream and complete once. */
        if(add(0,true)||add(1,true)||!swapz_pack_bios_match(&c)||
           members(&c.pending_bios)!=2)return 10;
        if(swapz_flush_pack(&c,false,true)||c.pack_record_count||
           members(&c.pending_bios)!=0||members(&c.stream.owned_bios)!=2||
           c.stream.staged[0]!=&bios[0]||c.stream.staged[1]!=&bios[1])
           return 11;
        stream_complete(0);
        if(bios[0].completes!=1||bios[1].completes!=1||
           members(&c.stream.owned_bios))return 12;
        return 0;
    case 1: /* Zero count conceals one accepted BIO. */
    case 2: /* Truncated count conceals second accepted BIO. */
    case 3: /* Arbitrarily oversized count must never index pending[]. */
    case 4: /* Flush must reject oversized count and fail both owners. */
    case 5: /* Flush must reject zero count and fail both owners. */
    case 6: /* Flush must reject truncated count and fail both owners. */
    case 9: /* Repeated unsent cleanup is idempotent. */
    case 11: /* Duplicate descriptor pointer with same pending owner count. */
    case 12: /* Append fails closed without overwriting a hidden owner. */
    case 13: /* Empty-looking pack cannot admit a new current BIO. */
    case 15: /* A count beyond 64 cannot accept another compressed page. */
        if(add(0,true)||add(1,true))return 20;
        if(mode==1||mode==5||mode==13)c.pack_record_count=0;
        if(mode==2||mode==6||mode==12)c.pack_record_count=1;
        if(mode==3||mode==4||mode==15)c.pack_record_count=UINT32_MAX;
        if(mode==11)c.pending[1].bio=&bios[0];
        if(mode==9)c.failed=true;
        if(mode==12||mode==13||mode==15) {
            rc=add(2,true);
            if(rc!=-EUCLEAN||bios[2].completes||members(&c.pending_bios)!=2)
                return 22;
        }
        if(mode==4||mode==5||mode==6||mode==11) {
            rc=swapz_flush_pack(&c,false,true);
            if(rc!=-EUCLEAN||c.stages)return 23;
        } else {
            rc=drain_once(-EIO);
            if(rc)return 24;
        }
        if(mutant) {
            if(mode!=1||bios[0].completes||bios[1].completes||
               members(&c.pending_bios)!=2)return 25;
            puts("OLD_ZERO_COUNT_SKIPS_PENDING_PACK_OWNERS");
            return 0;
        }
        if(bios[0].completes!=1||bios[1].completes!=1||
           bios[0].bi_status != ((mode==4||mode==5||mode==6||mode==11)?
                                  -EUCLEAN:-EIO) ||
           c.pack_record_count||members(&c.pending_bios)||
           !c.failed)return 26;
        if(mode==9) {
            drain_once(-EIO);
            if(bios[0].completes!=1||bios[1].completes!=1)
                return 27;
        }
        return 0;
    case 7: /* Real production record insertion: full 64 descriptor pack. */
        for(unsigned int i=0;i<64;i++)
            if(add(i,true))return 30;
        if(c.pack_record_count!=64||members(&c.pending_bios)!=64||
           !swapz_pack_bios_match(&c))return 31;
        if(swapz_flush_pack(&c,false,true)||members(&c.pending_bios)||
           members(&c.stream.owned_bios)!=64||c.stream.staged_count!=64)
           return 32;
        stream_complete(0);
        for(int i=0;i<64;i++)if(bios[i].completes!=1)return 33;
        return 0;
    case 8: /* Stage rejection: ledger must not transfer before success. */
        if(add(0,true)||add(1,true))return 40;
        c.stage_error=-EIO;
        rc=swapz_flush_pack(&c,false,true);
        if(rc!=-EIO||c.stream.staged_count||members(&c.pending_bios)||
           members(&c.stream.owned_bios)||bios[0].completes!=1||
           bios[1].completes!=1||bios[0].bi_status!=-EIO)return 41;
        return 0;
    case 10: /* Pure-GC compaction records correctly own no upper BIOs. */
        if(add(0,false)||add(1,false)||members(&c.pending_bios)||
           !swapz_pack_bios_match(&c))return 50;
        if(swapz_flush_pack(&c,true,true)||c.stream.staged_count||
           c.pack_record_count)return 51;
        return 0;
    case 14: /* Healthy empty pack; no work and no false failure. */
        if(swapz_flush_pack(&c,false,true)||c.failed||c.stages||
           members(&c.pending_bios))return 60;
        return 0;
    default:return 80;
    }
}
int main(int argc,char **argv) {
    char *end=NULL;long mode;
    int rc;
    if(argc!=3)return 91;
    mode=strtol(argv[1],&end,10);
    if(end==argv[1]||*end||mode<0||mode>15)return 92;
    rc=run((int)mode,argv[2][0]=='m');
    if(!rc)printf("PENDING_PACK_CASE_%ld_OK\n",mode);
    else fprintf(stderr,"PENDING_PACK_CASE_%ld_ERROR_%d\n",mode,rc);
    return rc;
}
"""

class PendingPackOwnershipExactC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = SOURCE.read_text(encoding="utf-8")
        cc = shutil.which("cc")
        if not cc:
            raise AssertionError("mandatory userspace C compiler unavailable")
        chunks = {name: exact_function(src,name) for name in FUNCTIONS}
        stage = exact_function(src,"swapz_stage_write_block")
        constructor = src[src.index("static int swapz_ctr("):]
        if not ("if (records == context->pending)" in stage and
                "list_del_init(&entry->list)" in stage and
                "swapz_register_owned_bio(buffer, source->bio," in stage):
            raise AssertionError("pending-to-stream registration lacks explicit node move")
        if "INIT_LIST_HEAD(&context->pending_bios)" not in constructor:
            raise AssertionError("pending ledger is not initialized")
        if "swapz_pack_bios_match(context)" not in chunks["swapz_flush_pack"]:
            raise AssertionError("flush lacks malformed-pack preflight")
        if "swapz_pack_bios_match(context)" not in chunks["swapz_add_compressed_record"]:
            raise AssertionError("append may overwrite hidden pending owners")
        if "swapz_fail_pending_pack_bios(context, error)" not in chunks["swapz_flush_pack"]:
            raise AssertionError("failed flush is still count-dependent")
        cls.tmp = tempfile.TemporaryDirectory(prefix="swapz-pack-owner-exact-c-")
        directory = Path(cls.tmp.name)
        def compile_version(label: str, replacements: dict[str,str]):
            body = [replacements.get(name,chunks[name]) for name in FUNCTIONS]
            source_path = directory/(label+".c")
            binary = directory/label
            source_path.write_text(PREFIX+"\n"+"\n\n".join(body)+"\n"+SUFFIX,
                                   encoding="utf-8")
            p = subprocess.run([cc,"-std=c11","-O2","-Wall","-Wextra","-Werror",
                                "-o",str(binary),str(source_path)],
                               capture_output=True,text=True,timeout=15)
            if p.returncode:
                raise AssertionError(f"{label}: {p.stderr}")
            return binary
        cls.production = compile_version("production",{})
        unsent = chunks["swapz_fail_unsent_upper_bios"]
        old = unsent.replace(
            "swapz_fail_pending_pack_bios(context, error);",
            """for (unsigned int i=0;
                 i < min(context->pack_record_count, SWAPZ_MAX_PACKED_RECORDS);
                 ++i)
                    if (context->pending[i].bio)
                        swapz_complete_bio(context->pending[i].bio, error);
                swapz_reset_pack(context);""",1)
        if old==unsent:
            raise AssertionError("count-dependent mutant not constructed")
        cls.mutant = compile_version("count-dependent-mutant",
                                     {"swapz_fail_unsent_upper_bios":old})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check(self,n:int,mutant:bool=False):
        p = subprocess.run([str(self.mutant if mutant else self.production),
                            str(n),"mutant" if mutant else "production"],
                           text=True,capture_output=True,timeout=4)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn(f"PENDING_PACK_CASE_{n}_OK",p.stdout)
        if mutant:
            self.assertIn("OLD_ZERO_COUNT_SKIPS_PENDING_PACK_OWNERS",p.stdout)

    def test_valid_pending_to_stream_transfer_and_exactly_once(self):
        self.check(0)

    def test_zero_truncated_and_oversized_count_drain_owners(self):
        for n in (1,2,3):
            with self.subTest(case=n): self.check(n)

    def test_malformed_count_flush_rejects_before_staging(self):
        for n in (4,5,6):
            with self.subTest(case=n): self.check(n)

    def test_full_pack_64_owners(self):
        self.check(7)

    def test_failed_staging_retains_pending_ownership_until_error_completion(self):
        self.check(8)

    def test_repeated_failed_cleanup_is_idempotent(self):
        self.check(9)

    def test_gc_only_records_do_not_claim_upper_bio_ownership(self):
        self.check(10)

    def test_duplicate_pending_pointer_is_detected(self):
        self.check(11)

    def test_append_rejects_truncated_zero_and_oversized_count(self):
        for n in (12,13,15):
            with self.subTest(case=n): self.check(n)

    def test_empty_pack_is_noop(self):
        self.check(14)

    def test_count_dependent_old_cleanup_strands_owned_bios(self):
        self.check(1,mutant=True)

if __name__ == "__main__":
    unittest.main(verbosity=2)
