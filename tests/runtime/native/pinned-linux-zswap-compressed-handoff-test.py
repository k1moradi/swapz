#!/usr/bin/env python3
"""Source-linked negative tests for the compile-disabled pinned Linux handoff."""
from __future__ import annotations
import importlib.util
import hashlib
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
typedef uint64_t u64;
typedef struct { unsigned long val; } swp_entry_t;
typedef struct { atomic_int value; } atomic_t;
static int atomic_read(const atomic_t *x) { return atomic_load(&x->value); }
static void atomic_set(atomic_t *x, int v) { atomic_store(&x->value, v); }
static int atomic_cmpxchg(atomic_t *x,int old,int next) {
    int observed=old;
    atomic_compare_exchange_strong(&x->value,&observed,next);
    return observed;
}
#define PAGE_SIZE 4096U
#define GFP_KERNEL 0
struct folio { bool locked; };
struct zswap_entry { swp_entry_t swpentry; unsigned int length; unsigned long handle; u8 pool_idx; };
struct zswap_pool { const char *tfm_name; void *zs_pool; u8 idx; };
struct scatterlist { const u8 *data; unsigned int len; };
struct xarray { struct zswap_entry *ptr; };
static struct xarray tree;
static struct zswap_pool host_pool = { "lz4", &tree, 0 };
static u8 zpool_bytes[PAGE_SIZE];
static u8 host_original_page[PAGE_SIZE];
/* Independently precomputed SHA256 of original 4096 bytes: byte[i]=i%251. */
static const u8 trusted_original_sha256[32] = {
    0xd6,0x7c,0x65,0x6e,0x01,0x75,0x66,0x50,
    0xd7,0x77,0x17,0xb0,0x83,0x99,0x85,0xa0,
    0x56,0xec,0x28,0xff,0xe1,0x74,0x60,0x1d,
    0x69,0x0f,0xc4,0x07,0xa2,0xce,0xff,0xca
};
static int freed, allocations, alloc_fail;
static bool folio_test_locked(const struct folio *folio) { return folio->locked; }
static struct xarray *swap_zswap_tree(swp_entry_t key) { (void)key; return &tree; }
static unsigned long swp_offset(swp_entry_t key) { return key.val; }
static void *xa_load(struct xarray *x,unsigned long i) { (void)i; return x->ptr; }
static struct zswap_pool *zswap_entry_pool(struct zswap_entry *e) { (void)e; return &host_pool; }
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
/* Castagnoli CRC32C is not the old producer's IEEE CRC32 polynomial. */
static u32 crc32c(u32 initial,const u8 *bytes,size_t size) {
    u32 result=initial; for(size_t i=0;i<size;i++) {result^=bytes[i];
       for(unsigned int j=0;j<8;j++) result=(result>>1)^((result&1U)?0x82f63b78U:0U);}
    return result;
}
/* Only fixed independent original-page SHA is modeled by this host shim:
 * kernel crypto execution and runtime cost remain NOT_RUN. */
static void sha256(const u8 *bytes, unsigned int size, u8 out[32]) {
    if (size==PAGE_SIZE && memcmp(bytes,host_original_page,PAGE_SIZE)==0)
        memcpy(out,trusted_original_sha256,32);
    else memset(out,0,32);
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
    const u8 crc_vector[9] = {'1','2','3','4','5','6','7','8','9'};
    assert(~crc32c(~0U,crc_vector,sizeof(crc_vector))==0xe3069283U);
    assert(crc32(0,crc_vector,sizeof(crc_vector))==0xcbf43926U);
    struct zswap_entry entry={.swpentry={.val=7},.length=200};
    swp_entry_t key={.val=7}; struct folio locked={true}, unlocked={false};
    struct zswap_swapz_owned_payload owner={0}; tree.ptr=&entry;
    struct zswap_swapz_stored_proof proof={0};
    for (unsigned int i=0;i<PAGE_SIZE;i++) {
        host_original_page[i]=(u8)(i%251U);
        zpool_bytes[i]=(u8)(i%251U);
    }
    assert(zswap_swapz_bind_stored_entry(&proof,&entry,key,17,&unlocked,
                                        host_original_page,PAGE_SIZE)==-EINVAL);
    assert(zswap_swapz_bind_stored_entry(&proof,&entry,key,0,&locked,
                                        host_original_page,PAGE_SIZE)==-EINVAL);
    assert(zswap_swapz_bind_stored_entry(&proof,&entry,key,17,&locked,
                                        host_original_page,PAGE_SIZE-1)==-EINVAL);
    host_pool.tfm_name="zstd";
    assert(zswap_swapz_bind_stored_entry(&proof,&entry,key,17,&locked,
                                        host_original_page,PAGE_SIZE)==-EOPNOTSUPP);
    host_pool.tfm_name="lz4";
    host_original_page[0]^=1U;
    assert(zswap_swapz_bind_stored_entry(&proof,&entry,key,17,&locked,
                                        zpool_bytes,PAGE_SIZE)==-ENODATA);
    host_original_page[0]^=1U;
    assert(zswap_swapz_bind_stored_entry(&proof,&entry,key,17,&locked,
                                        host_original_page,PAGE_SIZE)==0);
    assert(memcmp(proof.original_sha256,trusted_original_sha256,32)==0);
    assert(zswap_swapz_bind_stored_entry(&proof,&entry,key,17,&locked,
                                        host_original_page,PAGE_SIZE)==-EINVAL);
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&unlocked,&proof,17)==-EINVAL);
    assert(zswap_swapz_capture_owned_payload(NULL,&entry,key,&locked,&proof,17)==-EINVAL);
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked,&proof,18)==-ESTALE);
    proof.admitted=false;
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked,&proof,17)==-ESTALE);
    proof.admitted=true;
    tree.ptr=NULL; assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked,&proof,17)==-ENOENT);
    tree.ptr=&entry; entry.swpentry.val=8;
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked,&proof,17)==-ESTALE);
    entry.swpentry.val=7; entry.length=0;
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked,&proof,17)==-EMSGSIZE);
    entry.length=3569;
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked,&proof,17)==-EMSGSIZE);
    entry.length=200; host_pool.tfm_name="other";
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked,&proof,17)==-EOPNOTSUPP);
    host_pool.tfm_name="lz4"; alloc_fail=1;
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked,&proof,17)==-ENOMEM);
    alloc_fail=0;
    assert(zswap_swapz_capture_owned_payload(&owner,&entry,key,&locked,&proof,17)==0);
    assert(owner.compressed_length==200 && owner.decoded_length==4096);
    assert(owner.slot_generation==17 && owner.representation_version==1);
    assert(owner.representation==ZSWAP_SWAPZ_REPR_ZSWAP_LZ4_V1);
    assert(memcmp(owner.original_sha256,trusted_original_sha256,32)==0);
    assert(owner.payload_crc32c==~crc32c(~0U,owner.owned_bytes,200));
    assert(owner.payload_crc32c!=crc32(0,owner.owned_bytes,200));
    zpool_bytes[0]^=1U; assert(owner.owned_bytes[0]!=zpool_bytes[0]);
    struct zswap_swapz_owned_payload clone; memcpy(&clone,&owner,sizeof(clone));
    assert(!zswap_swapz_owned_payload_submit(&clone));
    assert(!zswap_swapz_owned_payload_abort(&clone));
    owner.payload_crc32c=crc32(0,owner.owned_bytes,owner.compressed_length);
    assert(!zswap_swapz_owned_payload_submit(&owner));
    owner.payload_crc32c=~crc32c(~0U,owner.owned_bytes,owner.compressed_length);
    owner.payload_crc32c^=1U; assert(!zswap_swapz_owned_payload_submit(&owner));
    owner.payload_crc32c^=1U; owner.codec=ZSWAP_SWAPZ_CODEC_UNKNOWN;
    assert(!zswap_swapz_owned_payload_submit(&owner));
    owner.codec=ZSWAP_SWAPZ_CODEC_LZ4;
    const u8 *original_copy=owner.owned_bytes;
    owner.owned_bytes=zpool_bytes; /* Forged public pointer cannot steal allocation. */
    assert(!zswap_swapz_owned_payload_submit(&owner));
    owner.owned_bytes=original_copy;
    u8 *owning_allocation=owner.owned_allocation;
    owning_allocation[0]^=1U;
    assert(!zswap_swapz_owned_payload_submit(&owner));
    owning_allocation[0]^=1U;
    owner.slot_generation=0;
    assert(!zswap_swapz_owned_payload_submit(&owner));
    owner.slot_generation=17;
    owner.representation_version=2;
    assert(!zswap_swapz_owned_payload_submit(&owner));
    owner.representation_version=1;
    owner.representation=ZSWAP_SWAPZ_REPR_RAW_4096;
    assert(!zswap_swapz_owned_payload_submit(&owner));
    owner.representation=ZSWAP_SWAPZ_REPR_ZSWAP_LZ4_V1;
    memset(owner.original_sha256,0,32);
    assert(!zswap_swapz_owned_payload_submit(&owner));
    memcpy(owner.original_sha256,trusted_original_sha256,32);
    assert(zswap_swapz_owned_payload_submit(&owner));
    struct zswap_swapz_compressed_carrier_v1 carrier={0};
    assert(zswap_swapz_carrier_snapshot_source_only(&carrier,&owner)==0);
    assert(carrier.payload_owner==&owner && carrier.immutable_payload==owner.owned_bytes);
    assert(carrier.compressed_length==owner.compressed_length &&
           carrier.original_decoded_length==4096 &&
           carrier.store_generation==owner.slot_generation &&
           carrier.stored_slot.val==key.val &&
           carrier.payload_crc32c==owner.payload_crc32c);
    assert(memcmp(carrier.original_sha256,owner.original_sha256,32)==0);
    assert(zswap_swapz_carrier_publish_disabled(&carrier,true,true,true,true,true)==-EOPNOTSUPP);
    carrier.source_only_untrusted=false; /* A forged live origin is still refused. */
    assert(zswap_swapz_carrier_publish_disabled(&carrier,true,true,true,true,true)==-EOPNOTSUPP);
    assert(zswap_swapz_carrier_publish_disabled(&carrier,true,false,true,true,true)==-EOPNOTSUPP);
    assert(zswap_swapz_carrier_publish_disabled(&carrier,true,true,false,true,true)==-EOPNOTSUPP);
    assert(zswap_swapz_carrier_publish_disabled(&carrier,true,true,true,false,true)==-EOPNOTSUPP);
    assert(zswap_swapz_carrier_publish_disabled(&carrier,true,true,true,true,false)==-EOPNOTSUPP);
    carrier.source_only_untrusted=true;
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
    host_pool.tfm_name="zstd"; entry.length=3568;
    /* A stored proof for 200 bytes cannot authorize a different allocation. */
    assert(zswap_swapz_capture_owned_payload(&aborted,&entry,key,&locked,&proof,17)==-ESTALE);
    host_pool.tfm_name="lz4";
    assert(zswap_swapz_capture_owned_payload(&aborted,&entry,key,&locked,&proof,17)==-ESTALE);
    struct zswap_swapz_stored_proof large_proof={0};
    assert(zswap_swapz_bind_stored_entry(&large_proof,&entry,key,17,&locked,
                                        host_original_page,PAGE_SIZE)==0);
    host_pool.tfm_name="zstd";
    assert(zswap_swapz_capture_owned_payload(&aborted,&entry,key,&locked,&large_proof,17)==-EOPNOTSUPP);
    host_pool.tfm_name="lz4";
    assert(zswap_swapz_capture_owned_payload(&aborted,&entry,key,&locked,&large_proof,17)==0);
    assert(aborted.codec==ZSWAP_SWAPZ_CODEC_LZ4);
    assert(zswap_swapz_owned_payload_abort(&aborted));
    assert(!zswap_swapz_owned_payload_abort(&aborted));
    assert(freed==2 && allocations==2);
    assert(!zswap_swapz_owned_payload_submit(&aborted));
    struct zswap_swapz_owned_payload successful={0};
    entry.length=1;
    assert(zswap_swapz_capture_owned_payload(&successful,&entry,key,&locked,&proof,17)==-ESTALE);
    struct zswap_swapz_stored_proof tiny_proof={0};
    assert(zswap_swapz_bind_stored_entry(&tiny_proof,&entry,key,17,&locked,
                                        host_original_page,PAGE_SIZE)==0);
    assert(zswap_swapz_capture_owned_payload(&successful,&entry,key,&locked,&tiny_proof,17)==0);
    assert(zswap_swapz_owned_payload_submit(&successful));
    assert(zswap_swapz_owned_payload_finish(&successful,0));
    assert(!zswap_swapz_owned_payload_finish(&successful,-EIO));
    assert(freed==3 && allocations==3);
    round023_stored_allocation_identity_regression();
    return 0;
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
                      'memcpy_from_sglist','zs_obj_read_sg_end','~crc32c(~0U,','original_sha256','slot_generation','ZSWAP_SWAPZ_REPR_ZSWAP_LZ4_V1',
                      'owner_state',
                      'atomic_cmpxchg','-ENOMEM','-ECANCELED','self != transfer'):
            with self.subTest(token=token): self.assertIn(token,c)
        self.assertNotIn('REQ_ZSWAP_WRITEBACK',c)
        # The old CRC32 producer contract is forbidden in compressed v1.
        self.assertNotIn('crc32(0,',c)
        self.assertIn('~crc32c(~0U,',c)
        self.assertNotIn('bio->bi_iter.bi_size',c)
        self.assertNotIn('submit_bio(',c)

    def test_round022_crc32c_sha_and_source_mutation_refusals(self):
        page=bytes(index%251 for index in range(4096))
        self.assertEqual(hashlib.sha256(page).hexdigest(),
                         'd67c656e01756650d77717b0839985a056ec28ffe174601d690fc407a2ceffca')
        source=stage.COMPRESSED_HANDOFF_SOURCE
        stage.validate_disabled_compressed_contract(source)
        mutations=(
            ('#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */',
             '#if 1 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */'),
            ('~crc32c(~0U, owned_bytes, entry->length)', 'crc32(0, owned_bytes, entry->length)'),
            ('proof->generation != generation', 'proof->generation == generation'),
            ('sha256(original_page, ZSWAP_SWAPZ_LOGICAL_BYTES, proof->original_sha256);',
             'memcpy(proof->original_sha256, original_page, ZSWAP_SWAPZ_DIGEST_BYTES);'),
            ('transfer->codec == ZSWAP_SWAPZ_CODEC_LZ4',
             'transfer->codec == ZSWAP_SWAPZ_CODEC_ZSTD'),
            ('transfer->representation == ZSWAP_SWAPZ_REPR_ZSWAP_LZ4_V1',
             'transfer->representation == ZSWAP_SWAPZ_REPR_RAW_4096'),
        )
        for before,after in mutations:
            with self.subTest(source_mutation=before):
                self.assertIn(before,source)
                with self.assertRaises(stage.StagingError):
                    stage.validate_disabled_compressed_contract(
                        source.replace(before,after,1))

    def test_round023_source_stored_allocation_proof_drift(self):
        source=stage.COMPRESSED_HANDOFF_SOURCE
        stage.validate_disabled_compressed_contract(source)
        for before,after in (
            ('entry->length != proof->stored_length',
             'entry->length == proof->stored_length'),
            ('entry->handle != proof->stored_handle',
             'entry->handle == proof->stored_handle'),
            ('pool != proof->stored_pool',
             'pool == proof->stored_pool'),
            ('proof->stored_handle = entry->handle;',
             'proof->stored_handle = 0;'),
            ('proof->stored_length = entry->length;',
             'proof->stored_length = 0;'),
            ('proof->stored_pool = pool;',
             'proof->stored_pool = NULL;'),
        ):
            with self.subTest(mutated_anchor=before):
                self.assertIn(before, source)
                with self.assertRaises(stage.StagingError):
                    stage.validate_disabled_compressed_contract(
                        source.replace(before,after,1))

    def test_round023_no_live_bio_compressed_carrier(self):
        source=stage.COMPRESSED_HANDOFF_SOURCE
        self.assertEqual(source.count('#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED'),1)
        for token in ('struct zswap_swapz_compressed_carrier_v1',
                      'zswap_swapz_carrier_snapshot_source_only(',
                      'zswap_swapz_carrier_publish_disabled(',
                      'source_only_untrusted',
                      'original_decoded_length',
                      'clones_preserve_owner',
                      'splits_preserve_owner',
                      'merges_preserve_owner',
                      'retries_preserve_owner'):
            with self.subTest(token=token): self.assertIn(token,source)
        self.assertNotIn('submit_bio(',source)
        self.assertNotIn('REQ_ZSWAP_WRITEBACK',source)
        # An ordinary 4096-byte BIO cannot carry variable compressed bytes.
        self.assertIn('return -EOPNOTSUPP;',source)

    def test_round024_source_probe_mutations_and_workflow(self):
        probe = stage.ROUND024_ZSWAP_KBUILD_PROBE_SOURCE
        stage.validate_round024_probe(probe)
        for before, after in (
            ("#if defined(SWAPZ_ROUND024_ZSWAP_KBUILD_PROBE)", "#if 1"),
            ("return -EOPNOTSUPP;", "return 0;"),
            ("folio_test_locked(locked_folio)", "true"),
            ("xa_load(swap_zswap_tree(source_slot),", "unverified_load("),
            ("stored_pool->idx != stored_entry->pool_idx",
             "stored_pool->idx == stored_entry->pool_idx"),
        ):
            with self.subTest(mutation=before):
                with self.assertRaises(stage.StagingError):
                    stage.validate_round024_probe(
                        probe.replace(before, after, 1))
        workflow = (STAGER.parents[2] /
                    ".github/workflows/phase-a-zswap-origin-prototype.yml"
                    ).read_text(encoding="utf-8")
        self.assertIn("--with-round024-zswap-kbuild-probe", workflow)
        self.assertIn("KCFLAGS=-DSWAPZ_ROUND024_ZSWAP_KBUILD_PROBE=1",
                      workflow)
        self.assertIn("zswap_swapz_round024_producer_kbuild_probe", workflow)

    def test_round024_exact_probe_gcc_clang_asan_ubsan(self):
        body = stage.COMPRESSED_HANDOFF_SOURCE.split(
            "#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */",
            1)[1].split(
            "#endif /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */",
            1)[0]
        for header in ("#include <linux/crc32c.h>", "#include <crypto/sha2.h>"):
            body = body.replace(header, "")
        fixture = (Path(__file__).parent / "fixtures" /
                   "round024-producer-kbuild-probe.c").read_text(
                       encoding="utf-8")
        # HOST_CASES already calls the original Round023 regression.
        # Include that exact original C fixture before the test main.
        stored_identity_fixture = (Path(__file__).parent / "fixtures" /
                                   "round023-producer-proof-identity.c").read_text(
                                       encoding="utf-8")
        # The real pinned pool has an idx field. Round023's host-only pool
        # fixture predates the idx field now used by this exact-source probe.
        # Extend only the in-memory fixture initializer, never the original C
        # file or any staged Linux source; retain strict -Werror for both.
        old_pool_initializer = 'struct zswap_pool other_pool = { "lz4", &tree };'
        self.assertEqual(stored_identity_fixture.count(old_pool_initializer), 1)
        stored_identity_fixture = stored_identity_fixture.replace(
            old_pool_initializer,
            'struct zswap_pool other_pool = { "lz4", &tree, 0 };', 1)
        main = HOST_CASES.replace(
            "int main(void) {",
            "int main(void) {\n    round024_compiler_probe_negatives();\n", 1)
        self.assertNotEqual(main, HOST_CASES)
        source = (HOST_SHIMS + body +
                  "#define SWAPZ_ROUND024_ZSWAP_KBUILD_PROBE 1\n" +
                  stage.ROUND024_ZSWAP_KBUILD_PROBE_SOURCE +
                  fixture + stored_identity_fixture + main)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "round024-probe.c"
            path.write_text(source, encoding="utf-8")
            compilers = [compiler for compiler in ("gcc", "clang")
                         if shutil.which(compiler)]
            self.assertTrue(compilers)
            for compiler in compilers:
                with self.subTest(compiler=compiler):
                    binary = Path(directory) / compiler
                    command = [compiler, "-std=gnu11", "-O1", "-g",
                               "-Wall", "-Wextra", "-Wconversion", "-Wshadow",
                               "-Werror", "-fsanitize=address,undefined",
                               "-fno-sanitize-recover=all", "-pthread",
                               str(path), "-o", str(binary)]
                    build = subprocess.run(command, capture_output=True,
                                           text=True, timeout=60)
                    self.assertEqual(build.returncode, 0, build.stderr)
                    result = subprocess.run([str(binary)], capture_output=True,
                                            text=True, timeout=40)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_compiled_guarded_producer_gcc_clang_ubsan(self):
        c=stage.COMPRESSED_HANDOFF_SOURCE
        head='#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */'
        tail='#endif /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */'
        self.assertEqual(c.count(head),1)
        body=c.split(head,1)[1].split(tail,1)[0]
        for header in ('#include <linux/crc32c.h>', '#include <crypto/sha2.h>'):
            body=body.replace(header,'')
        identity_fixture = (Path(__file__).parent / "fixtures" /
                            "round023-producer-proof-identity.c").read_text(
                                encoding="utf-8")
        # The real pool now has an idx; adapt only the synthetic old
        # fixture's two-field initializer without modifying that C file.
        old_pool_initializer = 'struct zswap_pool other_pool = { "lz4", &tree };'
        self.assertEqual(identity_fixture.count(old_pool_initializer), 1)
        identity_fixture = identity_fixture.replace(
            old_pool_initializer,
            'struct zswap_pool other_pool = { "lz4", &tree, 0 };', 1)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'host.c'
            path.write_text(HOST_SHIMS+body+identity_fixture+HOST_CASES,
                            encoding="utf-8")
            compilers=[x for x in ('gcc','clang') if shutil.which(x)]
            self.assertTrue(compilers)
            for compiler in compilers:
                with self.subTest(compiler=compiler):
                    out=Path(directory)/compiler
                    args=[compiler,'-std=gnu11','-Wall','-Wextra','-Wconversion','-Werror',
                          '-Wshadow','-fsanitize=address,undefined','-fno-sanitize-recover=all','-pthread','-O1',
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
