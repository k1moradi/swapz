#!/usr/bin/env python3
"""Source-linked negative tests for the compile-disabled pinned Linux handoff."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

STAGER = Path(__file__).resolve().parents[2] / 'tools/stage-pinned-linux-zswap-origin.py'
loader = importlib.util.spec_from_file_location('compressed_producer_stage', STAGER)
assert loader and loader.loader
stage = importlib.util.module_from_spec(loader)
sys.modules[loader.name] = stage
loader.loader.exec_module(stage)

HOST_SHIMS = r'''
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef struct { unsigned long val; } swp_entry_t;
typedef struct { atomic_int value; } atomic_t;
static int atomic_read(const atomic_t *x) { return atomic_load(&x->value); }
static void atomic_set(atomic_t *x, int v) { atomic_store(&x->value, v); }
static int atomic_cmpxchg(atomic_t *x,int old,int new) {
    atomic_compare_exchange_strong(&x->value,&old,new); return old;
}
#define PAGE_SIZE 4096U
#define GFP_KERNEL 0
struct folio { bool locked; };
struct zswap_entry { swp_entry_t swpentry; unsigned int length; unsigned long handle; };
struct zswap_pool { const char *tfm_name; void *zs_pool; };
struct scatterlist { const u8 *data; unsigned int len; };
struct xarray { struct zswap_entry *ptr; };
static struct xarray tree;
static struct zswap_pool pool = { "lz4", &tree };
static u8 zpool_bytes[PAGE_SIZE];
static int freed, allocations, alloc_fail;
static bool folio_test_locked(const struct folio *folio) { return folio->locked; }
static struct xarray *swap_zswap_tree(swp_entry_t key) { (void)key; return &tree; }
static unsigned long swp_offset(swp_entry_t key) { return key.val; }
static void *xa_load(struct xarray *x,unsigned long i) { (void)i; return x->ptr; }
static struct zswap_pool *zswap_entry_pool(struct zswap_entry *e) { (void)e; return &pool; }
static void *kmalloc(size_t n,int gfp) { (void)gfp; void *p=alloc_fail?NULL:malloc(n); if(p) ++allocations; return p; }
static void kfree(void *p) { if(p) { ++freed; free(p); } }
static void zs_obj_read_sg_begin(void *pool,unsigned long handle,struct scatterlist *sg,unsigned int len) {
    (void)pool; (void)handle; sg[0].data=zpool_bytes; sg[0].len=len;
}
static void zs_obj_read_sg_end(void *pool,unsigned long handle) { (void)pool; (void)handle; }
static void memcpy_from_sglist(u8 *dst,const struct scatterlist *sg,unsigned int off,unsigned int len) {
    assert(off+len<=sg->len); memcpy(dst,sg->data+off,len);
}
static u32 crc32(u32 initial,const u8 *bytes,size_t size) {
    u32 result=~initial; for(size_t i=0;i<size;i++) {result^=bytes[i];
       for(unsigned int j=0;j<8;j++) result=(result>>1)^((result&1U)?0xedb88320U:0U);}
    return ~result;
}
'''
HOST_CASES = r'''
struct callback_attempt { struct zswap_swapz_owned_payload *owner; bool finished; };
static void *finish_owner(void *opaque) {
    struct callback_attempt *attempt=opaque;
    attempt->finished=zswap_swapz_owned_payload_finish(attempt->owner,-EIO);
    return NULL;
}
int main(void) {
    struct zswap_entry entry={.swpentry={.val=7},.length=200};
    swp_entry_t key={.val=7}; struct folio locked={true}, unlocked={false};
    struct zswap_swapz_owned_payload owner={0}; tree.ptr=&entry;
    for (unsigned int i=0;i<PAGE_SIZE;i++) zpool_bytes[i]=(u8)(i%251U);
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&unlocked)==-EINVAL);
    assert(zswap_swapz_capture_owned_payload(NULL,&entry,key,&locked)==-EINVAL);
    tree.ptr=NULL; assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked)==-ENOENT);
    tree.ptr=&entry; entry.swpentry.val=8;
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked)==-ESTALE);
    entry.swpentry.val=7; entry.length=0;
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked)==-EMSGSIZE);
    entry.length=3569;
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked)==-EMSGSIZE);
    entry.length=200; pool.tfm_name="other";
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked)==-EOPNOTSUPP);
    pool.tfm_name="lz4"; alloc_fail=1;
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked)==-ENOMEM);
    alloc_fail=0;
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked)==0);
    assert(owner.compressed_length==200 && owner.decoded_length==4096);
    zpool_bytes[0]^=1U; assert(owner.owned_bytes[0]!=zpool_bytes[0]);
    struct zswap_swapz_owned_payload clone; memcpy(&clone,&owner,sizeof(clone));
    assert(!zswap_swapz_owned_payload_submit(&clone));
    assert(!zswap_swapz_owned_payload_abort(&clone));
    owner.crc32^=1U; assert(!zswap_swapz_owned_payload_submit(&owner));
    owner.crc32^=1U; owner.codec=ZSWAP_SWAPZ_CODEC_UNKNOWN;
    assert(!zswap_swapz_owned_payload_submit(&owner));
    owner.codec=ZSWAP_SWAPZ_CODEC_LZ4;
    const u8 *original_copy=owner.owned_bytes;
    owner.owned_bytes=zpool_bytes; /* Forged public pointer cannot steal allocation. */
    assert(!zswap_swapz_owned_payload_submit(&owner));
    owner.owned_bytes=original_copy;
    assert(zswap_swapz_owned_payload_submit(&owner));
    assert(!zswap_swapz_owned_payload_abort(&owner));
    assert(!zswap_swapz_owned_payload_submit(&owner));
    pthread_t first_thread,second_thread;
    struct callback_attempt first={.owner=&owner},second={.owner=&owner};
    assert(pthread_create(&first_thread,NULL,finish_owner,&first)==0);
    assert(pthread_create(&second_thread,NULL,finish_owner,&second)==0);
    assert(pthread_join(first_thread,NULL)==0);
    assert(pthread_join(second_thread,NULL)==0);
    assert(first.finished!=second.finished);
    assert(!zswap_swapz_owned_payload_finish(&owner,0));
    assert(freed==1 && allocations==1 && owner.completion_error==-EIO);
    struct zswap_swapz_owned_payload aborted={0};
    pool.tfm_name="zstd"; entry.length=3568;
    assert(zswap_swapz_capture_owned_payload(&aborted,&entry,key,&locked)==0);
    assert(aborted.codec==ZSWAP_SWAPZ_CODEC_ZSTD);
    assert(zswap_swapz_owned_payload_abort(&aborted));
    assert(!zswap_swapz_owned_payload_abort(&aborted));
    assert(freed==2 && allocations==2);
    struct zswap_swapz_owned_payload successful={0};
    entry.length=1;
    assert(zswap_swapz_capture_owned_payload(&successful,&entry,key,&locked)==0);
    assert(zswap_swapz_owned_payload_submit(&successful));
    assert(zswap_swapz_owned_payload_finish(&successful,0));
    assert(!zswap_swapz_owned_payload_finish(&successful,-EIO));
    assert(freed==3 && allocations==3); return 0;
}
'''

class CompressedHandoffTests(unittest.TestCase):
    def test_frozen_default_unchanged(self):
        self.assertEqual(stage.LINUX_COMMIT,'c339f4010dea8b0d754f84ace70cd1b089878ef8')
        self.assertEqual(stage.ORIGINAL_BLOBS['mm/zswap.c'],'ae19e301fced7e357a4c7587dfdd6abb890b9163')
        self.assertEqual(set(stage.COMPRESSED_HANDOFF_EDITS),{'mm/zswap.c'})
        for path, edits in stage.EDITS.items():
            old='\n/* excerpt */\n'.join(edit.before for edit in edits)
            self.assertEqual(stage.render_source(path,old),stage.render_source(path,old,compressed_handoff=False))

    def test_opt_in_missing_duplicate_repeated_refused(self):
        original='\n/* excerpt */\n'.join(e.before for e in stage.EDITS['mm/zswap.c'])
        anchor=stage.COMPRESSED_HANDOFF_EDITS['mm/zswap.c'][0].before
        with self.assertRaises(stage.StagingError):
            stage.render_source('mm/zswap.c',original,compressed_handoff=True)
        with self.assertRaises(stage.StagingError):
            stage.render_source('mm/zswap.c',original+anchor+anchor,compressed_handoff=True)
        staged=stage.render_source('mm/zswap.c',original+anchor,compressed_handoff=True)
        self.assertIn('SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI',staged)
        with self.assertRaises(stage.StagingError):
            stage.render_source('mm/zswap.c',staged,compressed_handoff=True)

    def test_explicit_off_and_ownership_semantics(self):
        c=stage.COMPRESSED_HANDOFF_SOURCE
        self.assertEqual(c.count('#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED'),1)
        for token in ('ZSWAP_SWAPZ_COMPRESSED_MAX 3568U','ZSWAP_SWAPZ_LOGICAL_BYTES 4096U',
                      'folio_test_locked','xa_load','entry->swpentry.val','pool->tfm_name',
                      'memcpy_from_sglist','zs_obj_read_sg_end','crc32(0,','owner_state',
                      'atomic_cmpxchg','-ENOMEM','-ECANCELED','self != transfer'):
            with self.subTest(token=token): self.assertIn(token,c)
        self.assertNotIn('REQ_ZSWAP_WRITEBACK',c)
        self.assertNotIn('submit_bio(',c)

    def test_compiled_guarded_producer_gcc_clang_ubsan(self):
        c=stage.COMPRESSED_HANDOFF_SOURCE
        head='#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */'
        tail='#endif /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */'
        self.assertEqual(c.count(head),1)
        body=c.split(head,1)[1].split(tail,1)[0].replace('#include <linux/crc32.h>','')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'host.c';path.write_text(HOST_SHIMS+body+HOST_CASES)
            compilers=[x for x in ('gcc','clang') if shutil.which(x)]
            self.assertTrue(compilers)
            for compiler in compilers:
                with self.subTest(compiler=compiler):
                    out=Path(directory)/compiler
                    args=[compiler,'-std=gnu11','-Wall','-Wextra','-Wconversion','-Werror',
                          '-fsanitize=undefined','-fno-sanitize-recover=all','-pthread','-O1',
                          str(path),'-o',str(out)]
                    built=subprocess.run(args,capture_output=True,text=True,timeout=30)
                    self.assertEqual(built.returncode,0,built.stderr)
                    completed=subprocess.run([str(out)],capture_output=True,text=True,timeout=30)
                    self.assertEqual(completed.returncode,0,completed.stderr)

    def test_workflow_prototype_isolation(self):
        source=(STAGER.parents[2]/'.github/workflows/phase-a-zswap-origin-prototype.yml').read_text()
        self.assertIn('pinned-linux-zswap-compressed-handoff-test.py',source)
        self.assertNotIn('--with-compressed-handoff-prototype',source)

if __name__=='__main__': unittest.main(verbosity=2)
