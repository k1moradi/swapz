#!/usr/bin/env python3
"""Rootless exact-C proof that generation scanning validates pack owners first.

Compiles the production pending owner validator, prior-generation scanner,
rewrite barrier and foreground write function verbatim. Two old-code mutants
remove the new preflight: they hide an older accepted BIO or inspect an
artificial in-bounds 65th canary beyond the logical 64-slot pack capacity.
No real out-of-bounds access, device I/O, module, swap or privileges.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "kernel/dm-swapz.c"
FUNCTIONS = (
    "swapz_pack_bios_match",
    "swapz_page_has_uncommitted_generation",
    "swapz_commit_previous_generation",
    "swapz_process_write",
)

def exact_function(source: str, name: str) -> str:
    found = list(re.finditer(
        r"\bstatic\s+(?:bool|int)\s+" + re.escape(name) +
        r"\s*\([^;{}]*\)\s*\{", source, re.DOTALL))
    if len(found) != 1:
        raise AssertionError(f"expected one production function {name}: {len(found)}")
    first = found[0].start()
    depth = 0
    for i in range(found[0].end()-1, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if not depth:
                return source[first:i+1]
    raise AssertionError(f"unterminated {name}")

PREFIX = r"""
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
typedef uint64_t sector_t;
#define SWAPZ_BLOCK_SECTORS 8ULL
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_MAX_PACKED_RECORDS 64U
#define unlikely(x) (x)
struct list_head {struct list_head *next,*prev;};
#define INIT_LIST_HEAD(p) do {(p)->next=(p);(p)->prev=(p);} while(0)
#define list_empty(p) ((p)->next==(p))
#define container_of(p,t,member) ((t *)((char *)(p)-offsetof(t,member)))
#define list_first_entry(p,t,member) container_of((p)->next,t,member)
#define list_for_each_entry(entry,head,member) \
    for(struct list_head *it=(head)->next; \
        it!=(head) && ((entry)=container_of(it,struct swapz_per_bio,member),1); \
        it=it->next)
static void list_add_tail(struct list_head *item,struct list_head *head) {
    item->prev=head->prev; item->next=head;
    head->prev->next=item;head->prev=item;
}
static void list_del_init(struct list_head *item) {
    item->prev->next=item->next;item->next->prev=item->prev;
    INIT_LIST_HEAD(item);
}
struct bio;
struct swapz_per_bio {
    struct list_head list;
    struct bio *bio;
    u8 block_index,record_index;
};
struct bio {struct {sector_t bi_sector;} bi_iter;u8 payload[SWAPZ_BLOCK_BYTES];};
struct swapz_staged_ref {u32 generation;u8 block_index,record_index,buffer_id,valid;};
struct swapz_pending_record {
    struct bio *bio;
    u32 logical_page,generation;
    u16 stored_length;
    u8 record_index;
};
struct swapz_context {
    struct list_head pending_bios;
    /* Deliberate extra canary slots for SAFE old-code mutant execution:
     * production has only SWAPZ_MAX_PACKED_RECORDS (64) slots. */
    struct swapz_pending_record pending[66];
    unsigned int pack_record_count;
    u32 logical_pages,generations[2];
    struct swapz_staged_ref staged_refs[2];
    void *write_buffer,*write_compressed_buffer;
    u8 write_data[SWAPZ_BLOCK_BYTES],compressed_data[SWAPZ_BLOCK_BYTES];
    struct {uint64_t logical_write_bytes;} stats;
    unsigned int fail_events,flush_pack,flush_batch,store_calls,copy_calls;
    unsigned int fail_flush,accepted_new,stored_generation;
};
static void swapz_set_failed(struct swapz_context *c,int err) {
    (void)err;c->fail_events++;
}
static int swapz_checked_page_index(u32 pages,sector_t sector,u32 *page) {
    if(sector%SWAPZ_BLOCK_SECTORS)return -EINVAL;
    if(sector/SWAPZ_BLOCK_SECTORS>=pages)return -ERANGE;
    *page=(u32)(sector/SWAPZ_BLOCK_SECTORS);return 0;
}
static int swapz_flush_pack(struct swapz_context *c,bool compact,bool rotate) {
    (void)compact;(void)rotate;
    c->flush_pack++;
    if(c->fail_flush)return -EIO;
    while(!list_empty(&c->pending_bios)) {
        struct swapz_per_bio *owner =
            list_first_entry(&c->pending_bios,struct swapz_per_bio,list);
        list_del_init(&owner->list);
    }
    c->pack_record_count=0;
    memset(c->pending,0,sizeof(c->pending));
    return 0;
}
static int swapz_flush_write_batch(struct swapz_context *c) {
    c->flush_batch++;
    for(unsigned int i=0;i<2;i++)c->staged_refs[i].valid=0;
    return 0;
}
static void swapz_copy_from_bio(struct bio *bio,void *dst) {
    (void)bio; memset(dst,0x5a,SWAPZ_BLOCK_BYTES);
}
static int swapz_store_page(struct swapz_context *c,struct bio *bio,u32 page,
                           u32 generation,const void *payload,void *compressed,
                           bool compact,bool rotate) {
    (void)bio;(void)page;(void)payload;(void)compressed;
    (void)compact;(void)rotate;
    c->store_calls++;c->accepted_new++;c->stored_generation=generation;
    return 0;
}
"""
SUFFIX = r"""
static struct swapz_context c;
static struct swapz_per_bio owners[64];
static struct bio bio;
static unsigned int ledger_count(void) {
    unsigned int n=0;
    for(struct list_head *p=c.pending_bios.next;p!=&c.pending_bios;p=p->next)
        if(++n>64)return 999;
    return n;
}
static void setup(void) {
    memset(&c,0,sizeof(c));
    memset(&owners,0,sizeof(owners));
    memset(&bio,0,sizeof(bio));
    INIT_LIST_HEAD(&c.pending_bios);
    for(unsigned int i=0;i<64;i++)INIT_LIST_HEAD(&owners[i].list);
    c.logical_pages=2;
    c.generations[0]=7;
    c.generations[1]=7;
    c.write_buffer=c.write_data;
    c.write_compressed_buffer=c.compressed_data;
}
static void add(unsigned int slot,unsigned int page,bool owner) {
    c.pending[slot].logical_page=page;
    c.pending[slot].generation=c.generations[page];
    c.pending[slot].record_index=(u8)slot;
    if(owner) {
        /* The identity validator checks pointer equality only, so a
         * typed unique non-NULL sentinel is sufficient in this harness. */
        c.pending[slot].bio=(struct bio *)&owners[slot];
        owners[slot].bio=c.pending[slot].bio;
        owners[slot].record_index=(u8)slot;
        list_add_tail(&owners[slot].list,&c.pending_bios);
    }
    if(slot>=c.pack_record_count)c.pack_record_count=slot+1;
}
static int run(int mode,bool mutant) {
    int rc;
    setup();
    switch(mode) {
    case 0: break; /* Empty pack. */
    case 1: add(0,0,true);break; /* Current prior generation. */
    case 2: add(0,1,true);add(1,0,true);break; /* Match later slot. */
    case 3: c.staged_refs[0].valid=1;c.staged_refs[0].generation=7;break;
    case 4: add(0,1,true);break; /* Only another page is pending. */
    case 5: add(0,0,true);c.pack_record_count=0;break; /* Hidden owner. */
    case 6: add(0,1,true);add(1,0,true);c.pack_record_count=1;break;
    case 7: c.pack_record_count=65; /* In-bounds test canary at logical slot 64. */
            c.pending[64].logical_page=0;
            c.pending[64].generation=7;
            c.pending[64].record_index=64;
            break;
    case 8: for(unsigned int i=0;i<64;i++)add(i,i==63?0:1,true);
            break;
    case 9: add(0,1,false);add(1,1,false);break; /* GC-only NULL BIOs. */
    case 10: c.staged_refs[0].valid=1;c.staged_refs[0].generation=7;
             add(0,1,true);c.pack_record_count=0;break;
    case 11: add(0,0,true);c.fail_flush=1;break;
    case 12: add(0,0,true);c.pending[0].record_index=1;break;
    case 13: add(0,0,true);c.pending[0].bio=NULL;break;
    case 14: add(0,0,true);owners[0].record_index=1;break;
    case 15: add(0,0,true);c.pending[0].bio=(struct bio *)&owners[1];break;
    case 16: c.staged_refs[0].valid=1;c.staged_refs[0].generation=6;break;
    case 17: add(0,1,false);add(1,0,false);break;
    case 18: c.generations[0]=UINT32_MAX;break;
    default:return 88;
    }
    rc=swapz_process_write(&c,&bio);
    if(mutant) {
        if(mode==5) {
            if(rc||c.generations[0]!=8||c.flush_pack||
               ledger_count()!=1||!c.accepted_new)return 80;
            puts("OLD_HIDDEN_PRIOR_BIO_ADVANCES_GENERATION");
            return 0;
        }
        if(mode==7) {
            if(rc||c.generations[0]!=8||c.flush_pack!=1||
               !c.accepted_new)return 81;
            puts("OLD_UNBOUNDED_SCANNER_READS_LOGICAL_SLOT_64");
            return 0;
        }
        return 82;
    }
    if(mode==5||mode==6||mode==7||mode==10||
       mode==12||mode==13||mode==14||mode==15) {
        if(rc!=-EUCLEAN||c.fail_events!=1||
           c.generations[0]!=7||c.store_calls||
           c.flush_pack||c.flush_batch||c.stats.logical_write_bytes||
           ledger_count()!=(mode==5||mode==12||mode==13||mode==14||mode==15?
                            1:mode==6?2:mode==10?1:0))
            return 20;
        return 0;
    }
    if(mode==11) {
        if(rc!=-EIO||c.generations[0]!=7||!c.flush_pack||
           c.store_calls||c.stats.logical_write_bytes)return 21;
        return 0;
    }
    if(rc||c.fail_events||c.store_calls!=1||c.accepted_new!=1||
       c.stats.logical_write_bytes!=SWAPZ_BLOCK_BYTES||
       c.stored_generation!=(mode==18?1:8))return 22;
    if((mode==1||mode==2||mode==3||mode==8||mode==17?
        1:0)!=(c.flush_pack?1:0))return 23;
    if(c.flush_pack && c.flush_batch!=1)return 24;
    if(!c.flush_pack && c.flush_batch)return 25;
    return 0;
}
int main(int argc,char **argv) {
    char *end=NULL;long n;
    int rc;
    if(argc!=3)return 90;
    n=strtol(argv[1],&end,10);
    if(end==argv[1]||*end||n<0||n>18)return 91;
    rc=run((int)n,argv[2][0]=='m');
    if(!rc)printf("GENERATION_SCAN_CASE_%ld_OK\n",n);
    else fprintf(stderr,"GENERATION_SCAN_CASE_%ld_ERROR_%d\n",n,rc);
    return rc;
}
"""

class GenerationScanPackPreflightExactC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text(encoding="utf-8")
        functions = {name:exact_function(source,name) for name in FUNCTIONS}
        prior = functions["swapz_commit_previous_generation"]
        check = "if (unlikely(!swapz_pack_bios_match(context)))"
        if prior.count(check) != 1 or not (prior.index(check) <
                                             prior.index("swapz_page_has_uncommitted_generation")):
            raise AssertionError("previous generation is scanned before pack preflight")
        if "return -EUCLEAN;" not in prior or "swapz_set_failed(context, -EUCLEAN);" not in prior:
            raise AssertionError("malformed generation scan must fail closed")
        old = prior.replace(
            """	if (unlikely(!swapz_pack_bios_match(context))) {
		swapz_set_failed(context, -EUCLEAN);
		return -EUCLEAN;
	}

""", "", 1)
        if old == prior or check in old:
            raise AssertionError("old behavior mutation was not applied")
        cc = shutil.which("cc")
        if not cc:
            raise AssertionError("mandatory C compiler unavailable")
        cls.tmp = tempfile.TemporaryDirectory(prefix="swapz-generation-scan-exact-c-")
        def compile_one(label,replacements):
            path = Path(cls.tmp.name)/(label+".c")
            executable = Path(cls.tmp.name)/label
            chunks=[replacements.get(n,functions[n]) for n in FUNCTIONS]
            if label=="unguarded-generation-mutant":
                chunks[0]=""  # The old version does not reference the validator.
            path.write_text(PREFIX+"\n"+"\n".join(chunks)+"\n"+SUFFIX,
                            encoding="utf-8")
            cp=subprocess.run([cc,"-std=c11","-O2","-Wall","-Wextra",
                               "-Werror","-o",str(executable),str(path)],
                              capture_output=True,text=True,timeout=15,check=False)
            if cp.returncode:
                raise AssertionError(f"{label} exact-C compilation failed: {cp.stderr}")
            return executable
        cls.production=compile_one("production",{})
        cls.mutant=compile_one("unguarded-generation-mutant",
                               {"swapz_commit_previous_generation":old})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check(self,n,mutant=False):
        cp=subprocess.run([str(self.mutant if mutant else self.production),
                           str(n),"mutant" if mutant else "production"],
                          capture_output=True,text=True,timeout=4)
        self.assertEqual(cp.returncode,0,cp.stdout+cp.stderr)
        self.assertIn(f"GENERATION_SCAN_CASE_{n}_OK",cp.stdout)
        if mutant:
            self.assertIn("OLD_HIDDEN_PRIOR_BIO_ADVANCES_GENERATION" if n==5 else
                          "OLD_UNBOUNDED_SCANNER_READS_LOGICAL_SLOT_64",cp.stdout)

    def test_healthy_empty_and_new_write(self):
        self.check(0)

    def test_pending_prior_generation_and_later_record_flush_before_rewrite(self):
        for n in (1,2,8):
            with self.subTest(case=n): self.check(n)

    def test_staged_previous_generation_and_stale_staged_reference(self):
        for n in (3,16):
            with self.subTest(case=n): self.check(n)

    def test_different_page_does_not_force_flush(self):
        self.check(4)

    def test_hidden_zero_and_truncated_counts_reject_before_generation_change(self):
        for n in (5,6,10):
            with self.subTest(case=n): self.check(n)

    def test_oversized_count_fails_without_out_of_bounds_read(self):
        self.check(7)

    def test_gc_only_records_remain_admitted(self):
        for n in (9,17):
            with self.subTest(case=n): self.check(n)

    def test_existing_full_64_record_pack_is_admitted(self):
        self.check(8)

    def test_prior_flush_error_keeps_generation(self):
        self.check(11)

    def test_owner_record_index_and_pointer_corruption_rejected(self):
        for n in (12,13,14,15):
            with self.subTest(case=n): self.check(n)

    def test_generation_wrap_skips_zero(self):
        self.check(18)

    def test_old_zero_count_mutant_advances_over_hidden_upper_bio(self):
        self.check(5,mutant=True)

    def test_old_oversized_count_mutant_reaches_safe_slot64_canary(self):
        self.check(7,mutant=True)

if __name__ == "__main__":
    unittest.main(verbosity=2)
