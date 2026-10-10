#!/usr/bin/env python3
"""Rootless exact-C upper BIO ownership ledger and malformed-count regression.

Extracts production completion, registration and failed-buffer draining
functions verbatim; Linux list primitives are bounded user-mode stand-ins.
No module, device, swap, privileged operations, or kernel I/O.
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

def exact_function(source: str, name: str) -> str:
    match = list(re.finditer(
        r"\bstatic\s+(?:void|bool)\s+" + re.escape(name) + r"\s*\([^;{}]*\)\s*\{",
        source, flags=re.DOTALL))
    if len(match) != 1:
        raise AssertionError("expected exactly one production function " + name)
    depth = 0
    for index in range(match[0].end() - 1, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if not depth:
                return source[match[0].start():index + 1]
    raise AssertionError("unterminated production C: " + name)

PREFIX = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
#define SWAPZ_MAX_PACKED_RECORDS 64U
#define WARN_ON_ONCE(x) ((void)(x))
#define unlikely(x) (x)
#define likely(x) (x)
#define min(a,b) ((a)<(b)?(a):(b))
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
#define list_for_each_entry(entry,head,member) \
    for (struct list_head *iter=(head)->next; \
         iter!=(head) && ((entry)=container_of(iter,struct swapz_per_bio,member),1); \
         iter=iter->next)

struct list_head { struct list_head *next, *prev; };
#define INIT_LIST_HEAD(node) do { (node)->next=(node); (node)->prev=(node); } while(0)
#define list_empty(node) ((node)->next == (node))
#define container_of(ptr,type,field) ((type *)((char *)(ptr)-offsetof(type,field)))
#define list_first_entry(head,type,field) container_of((head)->next,type,field)
static void list_add_tail(struct list_head *item, struct list_head *head) {
    item->prev=head->prev;item->next=head;
    head->prev->next=item;head->prev=item;
}
static void list_del_init(struct list_head *item) {
    item->prev->next=item->next;item->next->prev=item->prev;
    INIT_LIST_HEAD(item);
}

struct bio;
struct swapz_per_bio { struct list_head list; struct bio *bio; u8 block_index, record_index; };
struct bio {
    struct swapz_per_bio entry;
    int completes, bi_status;
};
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
    struct list_head owned_bios;
    struct swapz_write_batch_block *blocks;
    u32 block_count;
    u8 id;
};
struct swapz_context {
    bool failed;
    u32 max_batch_blocks, logical_pages;
    int clears, failures;
};
static struct swapz_per_bio *dm_per_bio_data(struct bio *b, size_t size) {
    (void)size;
    return &b->entry;
}
static int errno_to_blk_status(int error) { return error; }
static void bio_endio(struct bio *b) { b->completes++; }
static void swapz_set_failed(struct swapz_context *c, int error) {
    (void)error;
    c->failed=true;c->failures++;
}
static void swapz_clear_staged_ref(struct swapz_context *c, u32 logical_page,
                                   u32 generation, u8 buffer_id, u32 block_index,
                                   u8 record_index) {
    (void)logical_page;(void)generation;(void)buffer_id;
    (void)block_index;(void)record_index;
    c->clears++;
}
"""

SUFFIX = r"""
static struct swapz_context c;
static struct swapz_write_batch_block blocks[2][2];
static struct swapz_stream_buffer buffers[2];
static struct bio bios[3];
static void setup(void) {
    memset(&c,0,sizeof(c));
    memset(blocks,0,sizeof(blocks));
    memset(buffers,0,sizeof(buffers));
    memset(bios,0,sizeof(bios));
    c.max_batch_blocks=2;
    c.logical_pages=3;
    for(int i=0;i<2;i++) {
        buffers[i].blocks=blocks[i];
        buffers[i].id=(u8)i;
        buffers[i].block_count=2;
        INIT_LIST_HEAD(&buffers[i].owned_bios);
        blocks[i][0].record_count=1;
        blocks[i][1].record_count=1;
    }
    for(int i=0;i<3;i++) {
        bios[i].entry.bio=&bios[i];
        INIT_LIST_HEAD(&bios[i].entry.list);
    }
    blocks[0][0].records[0].bio=&bios[0];
    blocks[0][0].records[0].logical_page=0;
    blocks[0][1].records[0].bio=&bios[1];
    blocks[0][1].records[0].logical_page=1;
    swapz_register_owned_bio(&buffers[0],&bios[0],0,0);
    swapz_register_owned_bio(&buffers[0],&bios[1],1,0);
}
static int run_identity(int n, bool mutant) {
    bool match;
    setup();
    switch(n) {
    case 11: break; /* Correct independent mapping. */
    case 12: blocks[0][1].records[0].bio=&bios[0]; break; /* Duplicated BIO. */
    case 13: /* Swapped pointers with unchanged owner count. */
        blocks[0][0].records[0].bio=&bios[1];
        blocks[0][1].records[0].bio=&bios[0];
        break;
    case 14: /* Foreign buffer's owner pointer. */
        blocks[1][0].records[0].bio=&bios[2];
        swapz_register_owned_bio(&buffers[1],&bios[2],0,0);
        blocks[0][1].records[0].bio=&bios[2];
        break;
    case 15: blocks[0][1].records[0].bio=NULL; break;
    case 16: { /* Legal repack moves descriptors and owner slots together. */
        struct swapz_write_batch_record tmp=blocks[0][0].records[0];
        blocks[0][0].records[0]=blocks[0][1].records[0];
        blocks[0][1].records[0]=tmp;
        bios[0].entry.block_index=1;
        bios[1].entry.block_index=0;
        break;
    }
    case 17: bios[0].entry.block_index=1; break; /* Stale owner coordinate. */
    case 18: /* Already completed staged write. */
        swapz_complete_bio(&bios[0],0);
        blocks[0][0].records[0].bio=NULL;
        blocks[0][0].records[0].upper_completed=true;
        break;
    case 19: swapz_complete_bio(&bios[0],0); break; /* Stale completed pointer. */
    default: return 80;
    }
    match=swapz_stream_bios_match(&c,&buffers[0]);
    if (mutant) {
        if (n!=12 || !match) return 81;
        puts("OLD_COUNT_MATCH_ACCEPTS_DUPLICATE_BIO_POINTER");
        return 0;
    }
    if (match != (n==11 || n==16 || n==18)) return 82;
    return 0;
}
static int run_case(int n, bool mutant) {
    setup();
    switch(n) {
    case 0:
        swapz_complete_bio(&bios[0],0);
        swapz_complete_bio(&bios[1],0);
        if (bios[0].completes!=1||bios[1].completes!=1||
            !list_empty(&buffers[0].owned_bios)) return 20;
        break;
    case 1:
        buffers[0].block_count=0;
        swapz_complete_buffer_bios(&c,&buffers[0],-EIO);
        break;
    case 2:
        buffers[0].block_count=UINT32_MAX;
        swapz_complete_buffer_bios(&c,&buffers[0],-EIO);
        if(!c.failed) return 22;
        break;
    case 3:
        blocks[0][0].record_count=0;
        blocks[0][1].record_count=0;
        swapz_complete_buffer_bios(&c,&buffers[0],-EIO);
        break;
    case 4:
        blocks[0][0].record_count=65;
        swapz_complete_buffer_bios(&c,&buffers[0],-EIO);
        if(!c.failed) return 24;
        break;
    case 5: {
        /* Simulated compaction relocates descriptors; owner nodes do not move. */
        struct swapz_write_batch_record tmp=blocks[0][0].records[0];
        blocks[0][0].records[0]=blocks[0][1].records[0];
        blocks[0][1].records[0]=tmp;
        swapz_complete_buffer_bios(&c,&buffers[0],-EIO);
        break;
    }
    case 6:
        swapz_complete_bio(&bios[0],0);
        blocks[0][0].records[0].bio=NULL;
        swapz_complete_buffer_bios(&c,&buffers[0],-EIO);
        if (bios[0].bi_status!=0||bios[0].completes!=1) return 26;
        break;
    case 7:
        blocks[0][0].records[0].logical_page=UINT32_MAX;
        swapz_complete_buffer_bios(&c,&buffers[0],-EIO);
        if(!c.failed)return 27;
        break;
    case 8:
        blocks[1][0].records[0].bio=&bios[2];
        blocks[1][0].records[0].logical_page=2;
        swapz_register_owned_bio(&buffers[1],&bios[2],0,0);
        swapz_complete_buffer_bios(&c,&buffers[0],-EIO);
        if (bios[2].completes || list_empty(&buffers[1].owned_bios))
            return 28;
        swapz_complete_buffer_bios(&c,&buffers[1],-EIO);
        if (bios[2].completes!=1 || !list_empty(&buffers[1].owned_bios))
            return 29;
        break;
    case 9:
        swapz_complete_bio(&bios[0],0);
        blocks[0][0].records[0].bio=NULL;
        blocks[0][0].records[0].upper_completed=true;
        swapz_complete_buffer_bios(&c,&buffers[0],-EIO);
        if(bios[0].completes!=1||bios[0].bi_status) return 30;
        break;
    case 10:
        /* A pending pack BIO is still detached from any stream ledger. */
        swapz_complete_bio(&bios[2],-EIO);
        if(bios[2].completes!=1||!list_empty(&bios[2].entry.list))
            return 31;
        swapz_complete_buffer_bios(&c,&buffers[0],-EIO);
        break;
    default: return 60;
    }
    if(n==0)return 0;
    if(mutant) {
        if(n!=1||bios[0].completes||bios[1].completes||
           list_empty(&buffers[0].owned_bios))
            return 65;
        puts("OLD_ZERO_COUNT_STRANDS_OWNED_UPPER_BIOS");
        return 0;
    }
    if(bios[0].completes!=1||bios[1].completes!=1||
       (n!=6 && n!=9 && bios[0].bi_status!=-EIO)||
       bios[1].bi_status!=-EIO||
       !list_empty(&buffers[0].owned_bios))
        return 70;
    return 0;
}
int main(int argc,char **argv) {
    char *end=NULL;long n;
    int result;
    if(argc!=3)return 80;
    n=strtol(argv[1],&end,10);
    if(end==argv[1]||*end||n<0||n>19)return 81;
    result=n>=11?run_identity((int)n,argv[2][0]=='m'):
         run_case((int)n,argv[2][0]=='m');
    if(!result)printf("UPPER_BIO_OWNER_CASE_%ld_OK\n",n);
    return result;
}
"""

class UpperBioOwnershipExactC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src=SOURCE.read_text(encoding="utf-8")
        cc=shutil.which("cc")
        if not cc: raise AssertionError("mandatory C compiler missing")
        completion=exact_function(src,"swapz_complete_bio")
        register=exact_function(src,"swapz_register_owned_bio")
        drain=exact_function(src,"swapz_complete_buffer_bios")
        identities=exact_function(src,"swapz_stream_bios_match")
        stage=src[src.index("static int swapz_stage_write_block("):
                  src.index("static int swapz_flush_pack(")]
        constructor=src[src.index("static int swapz_ctr("):]
        read=src[src.index("static int swapz_read_staged("):
                 src.index("static bool swapz_page_has_uncommitted_generation(")]
        if "swapz_register_owned_bio(buffer, source->bio," not in stage:
            raise AssertionError("staging does not register independent ownership")
        if "INIT_LIST_HEAD(&buffer->owned_bios)" not in constructor:
            raise AssertionError("stream buffer ownership ledger not initialized")
        if "context->failed && !record->upper_completed" not in read:
            raise AssertionError("failed readback permits unacknowledged staged write")
        if "while (!list_empty(&buffer->owned_bios))" not in drain:
            raise AssertionError("failed BIO completion depends on corrupt counts")
        if "list_del_init(&entry->list)" not in completion:
            raise AssertionError("completed BIO retains dangling ownership node")
        cls.tmp=tempfile.TemporaryDirectory(prefix="swapz-owned-bio-exact-c-")
        directory=Path(cls.tmp.name)
        validator_bad = identities.replace(
            "block->records[entry->record_index].bio != entry->bio",
            "false", 1)
        if validator_bad == identities:
            raise AssertionError("identity comparison mutation not applied")
        def compile_one(label: str, body: str, checker: str = identities):
            path=directory/(label+".c")
            exe=directory/label
            path.write_text(PREFIX+"\n"+completion+"\n"+register+"\n"+
                            checker+"\n"+body+"\n"+SUFFIX,encoding="utf-8")
            result=subprocess.run(
                [cc,"-std=c11","-O2","-Wall","-Wextra","-Werror",
                 "-o",str(exe),str(path)],
                capture_output=True,text=True,timeout=15)
            if result.returncode:
                raise AssertionError(f"{label} compile failed: {result.stderr}")
            return exe
        cls.production=compile_one("production",drain)
        # Executable old control flow: bounds-based walk but no independent drain.
        marker="\tstruct swapz_per_bio *entry;\n"
        start=drain.index("\n\t/*\n\t * Even a zeroed record_count")
        old=drain.replace(marker,"",1)
        start=old.index("\n\t/*\n\t * Even a zeroed record_count")
        old=old[:start]+"\n}"
        # Legacy directly completes only descriptors reached by counts.
        old=old.replace(
            "\t\t\trecord->bio = NULL;",
            "\t\t\tswapz_complete_bio(record->bio, error);\n"
            "\t\t\trecord->bio = NULL;",1)
        cls.mutant=compile_one("count-dependent-mutant",old)
        cls.identity_mutant=compile_one("identity-check-mutant",drain,
                                        checker=validator_bad)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def check(self,scenario,mutant=False):
        process=subprocess.run(
            [str(self.identity_mutant if mutant and scenario>=11 else
                 self.mutant if mutant else self.production),str(scenario),
             "mutant" if mutant else "production"],
            capture_output=True,text=True,timeout=3)
        self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        self.assertIn(f"UPPER_BIO_OWNER_CASE_{scenario}_OK",process.stdout)
        if mutant:
            self.assertIn("OLD_COUNT_MATCH_ACCEPTS_DUPLICATE_BIO_POINTER"
                          if scenario>=11 else
                          "OLD_ZERO_COUNT_STRANDS_OWNED_UPPER_BIOS",
                          process.stdout)

    def test_exact_ownership_rejects_duplicate_swap_and_cross_buffer(self):
        for scenario in (12,13,14,15,17,19):
            with self.subTest(case=scenario): self.check(scenario)

    def test_valid_ownership_repack_and_early_ack(self):
        for scenario in (11,16,18):
            with self.subTest(case=scenario): self.check(scenario)

    def test_count_only_mutant_accepts_duplicate_pointer(self):
        self.check(12,mutant=True)

    def test_zero_and_oversized_block_counts_cannot_strand_bios(self):
        for i in (1,2,3,4):
            with self.subTest(scenario=i): self.check(i)
    def test_record_moves_dont_move_or_lose_ownership(self):
        self.check(5)
    def test_partial_early_completion_and_pending_pack_are_once_only(self):
        for i in (6,9,10):
            with self.subTest(scenario=i): self.check(i)
    def test_untrusted_logical_page_does_not_break_bio_completion(self):
        self.check(7)
    def test_two_buffers_have_disjoint_ownership(self):
        self.check(8)
    def test_normal_ownership_registration_and_completion(self):
        self.check(0)
    def test_removed_independent_ledger_strands_zero_count_bios(self):
        self.check(1,mutant=True)

if __name__=="__main__":
    unittest.main(verbosity=2)
