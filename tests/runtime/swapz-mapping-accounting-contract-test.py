#!/usr/bin/env python3
"""Rootless production-C mapping accounting and failed-replacement contract.

Compiles actual mapping-accounting functions extracted verbatim from
kernel/dm-swapz.c against bounded user-mode metadata. No kernel, mapper,
swap, module, NBD, physical backing or destructive operation.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
KERNEL = ROOT / "kernel" / "dm-swapz.c"
FUNCTIONS = ("swapz_mapping_valid", "swapz_mapping_segment",
             "swapz_unaccount_mapping", "swapz_invalidate_mapping",
             "swapz_install_mapping")


def exact_function(src: str, name: str) -> str:
    matches = list(re.finditer(
        r"\bstatic\s+(?:inline\s+)?(?:bool|void|u32)\s+" +
        re.escape(name) + r"\s*\([^;{}]*\)\s*\{", src, re.DOTALL,
    ))
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {name} production-C function")
    start, brace = matches[0].start(), matches[0].end() - 1
    depth = 0
    for pos in range(brace, len(src)):
        if src[pos] == "{":
            depth += 1
        elif src[pos] == "}":
            depth -= 1
            if depth == 0:
                return src[start:pos + 1]
    raise AssertionError(f"unterminated C function {name}")


def enforce_contract(src: str) -> None:
    install = exact_function(src, "swapz_install_mapping")
    unaccount = exact_function(src, "swapz_unaccount_mapping")
    invalid = exact_function(src, "swapz_invalidate_mapping")
    if ("replacing_same_block = swapz_mapping_valid(mapping)" not in install
            or "mapping->physical_block == physical_block" not in install):
        raise AssertionError("full same-block replacement exception missing")
    if (install.find("physical_block >= context->physical_blocks") < 0 or
            install.find("segment >= context->segment_count") < 0 or
            install.find("SWAPZ_MAX_PACKED_RECORDS && !replacing_same_block") < 0):
        raise AssertionError("destination pre-validation incomplete")
    if "mapping->physical_block = physical_block;" not in install:
        raise AssertionError("mapping publication must follow validated live accounting")
    if not (install.index("physical_block >= context->physical_blocks") <
            install.index("swapz_unaccount_mapping(context, mapping)") <
            install.index("context->block_live_records[physical_block]++") <
            install.index("mapping->physical_block = physical_block;")):
        raise AssertionError("destination validation must precede old-live unaccount")
    if not (install.index("swapz_unaccount_mapping(context, mapping)") <
            install.index("if (unlikely(context->failed))", install.index("swapz_unaccount_mapping(context, mapping)")) <
            install.index("context->block_live_records[physical_block]++")):
        raise AssertionError("failed old unaccount must block new mapping publication")
    if ("context->block_live_records[physical_block] == 0" not in unaccount
            or "context->segment_live_blocks[segment] == 0" not in unaccount):
        raise AssertionError("old-live underflow detection removed")
    if "swapz_unaccount_mapping(context, mapping);" not in invalid:
        raise AssertionError("discard invalidation bypasses old accounting")

PREFIX = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
#define SWAPZ_SEGMENT_BLOCKS 256U
#define SWAPZ_MAX_PACKED_RECORDS 64U
#define SWAPZ_EMPTY_BLOCK UINT32_MAX
#define SWAPZ_MAP_VALID 1U
#define SWAPZ_MAP_COMPRESSED 2U
#define WARN_ON_ONCE(x) (x)
#define unlikely(x) (x)
struct swapz_mapping {
    u32 physical_block; u16 stored_length; u8 record_index; u8 flags;
};
struct swapz_context {
    bool failed;
    u32 physical_blocks, segment_count;
    u8 block_live_records[512];
    u16 segment_live_blocks[2];
    struct swapz_mapping mappings[3];
    int failures;
};
static void swapz_set_failed(struct swapz_context *c,int err) {
    (void)err; c->failed=true; c->failures++;
}
"""

SUFFIX = r"""
static struct swapz_context c;
static void init(void) {
    memset(&c, 0, sizeof(c));
    c.physical_blocks=512;c.segment_count=2;
    c.block_live_records[10]=1;c.segment_live_blocks[0]=1;
    c.mappings[0]=(struct swapz_mapping){.physical_block=10,
        .stored_length=20,.record_index=0,.flags=SWAPZ_MAP_VALID};
}
static int validate_old(u8 live, u16 seg) {
    return c.mappings[0].physical_block==10 &&
        c.mappings[0].flags==SWAPZ_MAP_VALID &&
        c.mappings[0].stored_length==20 &&
        c.block_live_records[10]==live &&
        c.segment_live_blocks[0]==seg;
}
static int run(int n) {
    init();
    switch(n) {
    case 0: /* Move to another segment. */
        swapz_install_mapping(&c,0,260,4,1,SWAPZ_MAP_COMPRESSED);
        if(c.failed||c.block_live_records[10]||
           c.block_live_records[260]!=1||c.segment_live_blocks[0]||
           c.segment_live_blocks[1]!=1||c.mappings[0].physical_block!=260||
           c.mappings[0].flags!=(SWAPZ_MAP_VALID|SWAPZ_MAP_COMPRESSED))return 10;
        break;
    case 1: /* Move within current segment. */
        swapz_install_mapping(&c,0,11,22,0,0);
        if(c.failed||c.block_live_records[10]||c.block_live_records[11]!=1||
           c.segment_live_blocks[0]!=1||c.mappings[0].physical_block!=11)return 11;
        break;
    case 2: /* Invalid replacement leaves old live count intact. */
        swapz_install_mapping(&c,0,512,4,0,0);
        if(!c.failed||!validate_old(1,1)||c.segment_live_blocks[1])return 12;
        break;
    case 3: /* UINT32_MAX must not index any metadata. */
        swapz_install_mapping(&c,0,UINT32_MAX,4,0,0);
        if(!c.failed||!validate_old(1,1))return 13;
        break;
    case 4: /* Full different destination must preserve the old mapping. */
        c.block_live_records[260]=64;c.segment_live_blocks[1]=1;
        swapz_install_mapping(&c,0,260,4,1,SWAPZ_MAP_COMPRESSED);
        if(!c.failed||!validate_old(1,1)||
           c.block_live_records[260]!=64||c.segment_live_blocks[1]!=1)return 14;
        break;
    case 5: /* A full SAME block may replace its one old live record. */
        c.block_live_records[10]=64;
        swapz_install_mapping(&c,0,10,7,1,SWAPZ_MAP_COMPRESSED);
        if(c.failed||c.block_live_records[10]!=64||c.segment_live_blocks[0]!=1||
           c.mappings[0].stored_length!=7||c.mappings[0].record_index!=1)return 15;
        break;
    case 6: /* A previously failed target must not mutate old counters. */
        c.failed=true;
        swapz_install_mapping(&c,0,260,4,0,0);
        if(!validate_old(1,1)||c.block_live_records[260]||c.failures)return 16;
        break;
    case 7: /* Corrupt old live count blocks new publication. */
        c.block_live_records[10]=0;
        swapz_install_mapping(&c,0,260,4,0,0);
        if(!c.failed||!validate_old(0,1)||c.block_live_records[260])return 17;
        break;
    case 8: /* An empty initial page can be installed. */
        c.mappings[0].flags=0;c.mappings[0].physical_block=SWAPZ_EMPTY_BLOCK;
        c.block_live_records[10]=0;c.segment_live_blocks[0]=0;
        swapz_install_mapping(&c,0,260,4,0,0);
        if(c.failed||c.block_live_records[260]!=1||c.segment_live_blocks[1]!=1||
           c.mappings[0].physical_block!=260)return 18;
        break;
    case 9: /* Invalidate valid mapping. */
        swapz_invalidate_mapping(&c,0);
        if(c.failed||c.block_live_records[10]||c.segment_live_blocks[0]||
           c.mappings[0].flags||c.mappings[0].physical_block!=SWAPZ_EMPTY_BLOCK)return 19;
        break;
    case 10: /* Invalidate empty mapping. */
        c.mappings[0].flags=0;c.mappings[0].physical_block=SWAPZ_EMPTY_BLOCK;
        c.block_live_records[10]=0;c.segment_live_blocks[0]=0;
        swapz_invalidate_mapping(&c,0);
        if(c.failed||c.segment_live_blocks[0]||c.mappings[0].flags)return 20;
        break;
    case 11: /* Destination with 63 live records permits one more. */
        c.block_live_records[260]=63;c.segment_live_blocks[1]=1;
        swapz_install_mapping(&c,0,260,4,0,0);
        if(c.failed||c.block_live_records[260]!=64||c.segment_live_blocks[1]!=1||
           c.block_live_records[10]||c.segment_live_blocks[0])return 21;
        break;
    case 12: /* Same-block replacement with only one old record. */
        swapz_install_mapping(&c,0,10,4,0,0);
        if(c.failed||c.block_live_records[10]!=1||c.segment_live_blocks[0]!=1)return 22;
        break;
    case 13: /* Invalid old metadata blocks even legal same-block replacement. */
        c.block_live_records[10]=0;
        swapz_install_mapping(&c,0,10,4,0,0);
        if(!c.failed||!validate_old(0,1))return 23;
        break;
    case 14: /* Two live refs to old compressed block: decrement exactly one. */
        c.block_live_records[10]=2;
        c.mappings[1]=(struct swapz_mapping){.physical_block=10,
            .stored_length=14,.flags=SWAPZ_MAP_VALID};
        swapz_install_mapping(&c,0,260,4,0,0);
        if(c.failed||c.block_live_records[10]!=1||c.segment_live_blocks[0]!=1||
           c.block_live_records[260]!=1||c.segment_live_blocks[1]!=1||
           c.mappings[1].physical_block!=10)return 24;
        break;
    case 15: /* Unaccounting an impossible old physical block fails closed. */
        c.mappings[0].physical_block=512;
        swapz_install_mapping(&c,0,260,4,0,0);
        if(!c.failed||c.mappings[0].physical_block!=512||
           c.block_live_records[260])return 25;
        break;
    default:return 60;
    }
    printf("MAPPING_ACCOUNTING_CASE_%d_OK\n",n);
    return 0;
}
int main(int argc,char **argv) {
    int n=-1;
    if(argc!=2||sscanf(argv[1],"%d",&n)!=1||n<0||n>15)return 61;
    return run(n);
}
"""

class MappingAccountingContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src=KERNEL.read_text(encoding="utf-8")
        enforce_contract(cls.src)
        cc=shutil.which("cc")
        if cc is None:
            raise AssertionError("mandatory userspace C compiler unavailable")
        cls.tmp=tempfile.TemporaryDirectory(prefix="swapz-mapping-c-")
        cls.binary=Path(cls.tmp.name)/"mapping-accounting"
        program=Path(cls.tmp.name)/"mapping-accounting.c"
        program.write_text(PREFIX + "\n" +
            "\n".join(exact_function(cls.src,n) for n in FUNCTIONS) +
            "\n" + SUFFIX, encoding="utf-8")
        r=subprocess.run([cc,"-std=c11","-O2","-Wall","-Wextra","-Werror",
            "-o",str(cls.binary),str(program)],
            capture_output=True,text=True,timeout=15)
        if r.returncode:
            raise AssertionError("exact mapping production C compile failed: "+r.stderr)
    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_case(self,case):
        r=subprocess.run([str(self.binary),str(case)],capture_output=True,
                         text=True,timeout=3)
        self.assertEqual(r.returncode,0,f"case {case}: {r.stdout} {r.stderr}")
        self.assertIn(f"MAPPING_ACCOUNTING_CASE_{case}_OK",r.stdout)

    def test_replacement_and_failed_destination_matrix(self):
        for case in range(16):
            with self.subTest(case=case):
                self.run_case(case)

    def test_source_order_is_fail_closed(self):
        enforce_contract(self.src)

    def test_original_late_validation_mutation_is_rejected(self):
        original=exact_function(self.src,"swapz_install_mapping")
        unaccount="\tswapz_unaccount_mapping(context, mapping);"
        self.assertIn(unaccount,original)
        mutation=original.replace(unaccount,"",1)
        insertion=mutation.index("\tif (WARN_ON_ONCE(physical_block >=")
        mutation=mutation[:insertion]+unaccount+"\n"+mutation[insertion:]
        self.assertNotEqual(mutation,original)
        with self.assertRaisesRegex(AssertionError,"destination validation must precede"):
            enforce_contract(self.src.replace(original,mutation,1))

    def test_same_full_physical_block_exception_mutation_is_rejected(self):
        original=exact_function(self.src,"swapz_install_mapping")
        bad=original.replace("SWAPZ_MAX_PACKED_RECORDS && !replacing_same_block",
                             "SWAPZ_MAX_PACKED_RECORDS")
        self.assertNotEqual(bad,original)
        with self.assertRaisesRegex(AssertionError,"destination pre-validation"):
            enforce_contract(self.src.replace(original,bad,1))

    def test_mapping_publication_before_old_account_mutation_is_rejected(self):
        original=exact_function(self.src,"swapz_install_mapping")
        bad=original.replace("\tmapping->physical_block = physical_block;",
                             "\t/* removed mapping publication */",1)
        self.assertNotEqual(bad,original)
        with self.assertRaisesRegex(AssertionError,"mapping publication must follow"):
            enforce_contract(self.src.replace(original,bad,1))

    def test_unaccount_underflow_guard_mutation_is_rejected(self):
        original=exact_function(self.src,"swapz_unaccount_mapping")
        bad=original.replace("context->block_live_records[physical_block] == 0",
                             "false",1)
        self.assertNotEqual(bad,original)
        with self.assertRaisesRegex(AssertionError,"underflow detection"):
            enforce_contract(self.src.replace(original,bad,1))

if __name__ == "__main__":
    unittest.main(verbosity=2)
